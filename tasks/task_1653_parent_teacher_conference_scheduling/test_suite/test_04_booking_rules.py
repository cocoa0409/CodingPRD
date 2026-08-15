"""Booking creation rules: window-state gate, link and enrollment gates,
duplicate rules, channel rules, family gap rule, caps, and compactness."""
import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    add_family,
    add_link,
    add_student,
    add_teacher,
    assert_booking,
    assert_window_counters,
    book_slot,
    create_booking_payload,
    create_waitlist_entry_payload,
    get_success_data,
    guardian_headers,
    open_booking,
    read_window,
    scenario_day_cap,
    scenario_compactness,
    scenario_travel_gap,
    setup_booked_slot,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Cross-entity gate: booking requires the window to be BOOKING_OPEN
# ---------------------------------------------------------------------------


def test_booking_rejected_while_window_published_then_succeeds(api):
    """PRD 3.4: "Creation is gated by a battery of checks, surfaced in the
    order of §2.7. The window must be `BOOKING_OPEN` (otherwise
    `ERR_INVALID_WINDOW_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_window_booking_open
    """
    ctx = setup_window_at_stage("PUBLISHED")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    slot = ctx["teacher_slots"][teacher_id][0]
    payload = create_booking_payload(slot["id"], party["students"][0]["id"], "IN_PERSON")

    rejected = api.create_booking(payload, party["guardian"])
    validate_error(rejected, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)

    open_booking(ctx["window"]["id"])
    created = validate_success(api.create_booking(payload, party["guardian"]), 201)
    assert_booking(created)
    assert created["status"] == "CONFIRMED"


def test_waitlist_join_rejected_while_window_published(api):
    """PRD 3.6: "The window must be `BOOKING_OPEN`; a guardian caller joins
    only for their own family and only while that family is `ACTIVE` (otherwise
    `ERR_FAMILY_RESTRICTED`, which staff callers bypass); the student must be
    `ENROLLED` and linked to the teacher per the same rules as booking."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_window_booking_open
    """
    ctx = setup_window_at_stage("PUBLISHED")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)

    rejected = api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party["students"][0]["id"],
                                      teacher_id, "EITHER"),
        party["guardian"],
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)


# ---------------------------------------------------------------------------
# Duplicate and link rules
# ---------------------------------------------------------------------------


def test_duplicate_booking_same_pair_rejected(api):
    """PRD 3.4: "Duplicates are refused with `ERR_DUPLICATE_BOOKING`: a student
    may hold at most one `CONFIRMED` booking with a given teacher per window,
    and in an `ELEMENTARY` window at most one `CONFIRMED` booking in the window
    altogether."

    Design: Corner/validations/duplicate_booking_same_pair_rejected
    """
    ctx = setup_booked_slot()
    teacher_id = ctx["teachers"][0]["id"]
    slot3 = ctx["teacher_slots"][teacher_id][3]
    response = api.create_booking(
        create_booking_payload(slot3["id"], ctx["student"]["id"], "IN_PERSON"),
        ctx["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BOOKING, 409)


def test_elementary_second_teacher_booking_rejected(api):
    """PRD 3.4: "Duplicates are refused with `ERR_DUPLICATE_BOOKING`: a student
    may hold at most one `CONFIRMED` booking with a given teacher per window,
    and in an `ELEMENTARY` window at most one `CONFIRMED` booking in the window
    altogether."

    Design: Corner/validations/elementary_second_teacher_booking_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN", teacher_specs=[{}, {}])
    t1, t2 = ctx["teachers"]
    family = add_family()
    student = add_student(family["id"], grade_level=3)
    add_link(student["id"], t1["id"], is_homeroom=True)
    add_link(student["id"], t2["id"])
    guardian = guardian_headers(family)

    slot_t1 = ctx["teacher_slots"][t1["id"]][0]
    slot_t2 = ctx["teacher_slots"][t2["id"]][3]
    book_slot(slot_t1["id"], student["id"], guardian)

    response = api.create_booking(
        create_booking_payload(slot_t2["id"], student["id"], "IN_PERSON"), guardian
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BOOKING, 409)


def test_secondary_multi_teacher_bookings_allowed(api):
    """PRD 3.1: "A `SchoolAdmin` creates one by supplying a human-readable
    `name` such as "Fall Conferences", a `term_label` such as "2026-FALL", and
    a `format` of either `ELEMENTARY` or `SECONDARY` — the format drives the
    booking rules later, since elementary families book a single homeroom
    conference while secondary families book per teacher."
    PRD 3.4: "Duplicates are refused with `ERR_DUPLICATE_BOOKING`: a student
    may hold at most one `CONFIRMED` booking with a given teacher per window,
    and in an `ELEMENTARY` window at most one `CONFIRMED` booking in the window
    altogether."

    Design: Corner/validations/secondary_multi_teacher_bookings_allowed
    """
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        window_overrides={"name": "Sec", "format": "SECONDARY"},
        teacher_specs=[
            {"grade_band": "SECONDARY", "subjects": ["math"]},
            {"grade_band": "SECONDARY", "subjects": ["eng"]},
            {"grade_band": "SECONDARY", "subjects": ["sci"]},
        ],
    )
    t1, t2, t3 = ctx["teachers"]
    family = add_family()
    student = add_student(family["id"], grade_level=9)
    for teacher in (t1, t2, t3):
        add_link(student["id"], teacher["id"])
    guardian = guardian_headers(family)

    targets = [
        ctx["teacher_slots"][t1["id"]][0],
        ctx["teacher_slots"][t2["id"]][1],
        ctx["teacher_slots"][t3["id"]][2],
    ]
    for slot in targets:
        booking = book_slot(slot["id"], student["id"], guardian)
        assert booking["status"] == "CONFIRMED"
    assert_window_counters(read_window(ctx["window"]["id"]), confirmed=3)


def test_duplicate_teacher_link_rejected(api, front_office_headers):
    """PRD 3.3: "Only one link may exist per student-teacher pair; a second
    attempt is rejected with `ERR_DUPLICATE_TEACHER_LINK`."

    Design: Corner/validations/duplicate_teacher_link_rejected
    """
    teacher = add_teacher()
    family = add_family()
    student = add_student(family["id"], grade_level=3)
    add_link(student["id"], teacher["id"], is_homeroom=True)

    response = api.create_teacher_link(
        student["id"], {"teacher_id": teacher["id"]}, front_office_headers
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TEACHER_LINK, 409)


def test_booking_without_teacher_link_rejected(api):
    """PRD 2.7: "Body-referenced identifiers must exist (`ERR_NOT_FOUND`); the
    student must be `ENROLLED` (`ERR_STUDENT_NOT_BOOKABLE`); a student-teacher
    link must exist — and for `ELEMENTARY` windows must be the homeroom link
    (`ERR_TEACHER_NOT_LINKED`)."
    PRD 3.4: "A student-teacher link must exist between the student and the
    slot's teacher, and for an `ELEMENTARY` window that link must be the
    homeroom link — `is_homeroom` set — otherwise `ERR_TEACHER_NOT_LINKED`."

    Design: Corner/validations/booking_without_teacher_link_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    family = add_family()
    student = add_student(family["id"], grade_level=3)
    guardian = guardian_headers(family)
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]

    response = api.create_booking(
        create_booking_payload(slot["id"], student["id"], "IN_PERSON"), guardian
    )
    validate_error(response, ApiErrorId.ERR_TEACHER_NOT_LINKED, 422)


def test_booking_withdrawn_student_rejected(api, front_office_headers):
    """PRD 3.4: "Creation is gated by a battery of checks, surfaced in the
    order of §2.7. The window must be `BOOKING_OPEN` (otherwise
    `ERR_INVALID_WINDOW_STATE`). The slot must be `OPEN` (otherwise
    `ERR_SLOT_NOT_AVAILABLE`), the teacher `ACTIVE` (otherwise
    `ERR_TEACHER_INACTIVE`), and the student `ENROLLED` (otherwise
    `ERR_STUDENT_NOT_BOOKABLE`)."

    Design: Corner/validations/booking_withdrawn_student_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    student = party["students"][0]
    get_success_data(api.withdraw_student(student["id"], front_office_headers))
    slot = ctx["teacher_slots"][teacher_id][0]

    # Even a staff on-behalf booking cannot target a WITHDRAWN student.
    response = api.create_booking(
        create_booking_payload(slot["id"], student["id"], "IN_PERSON"), front_office_headers
    )
    validate_error(response, ApiErrorId.ERR_STUDENT_NOT_BOOKABLE, 422)


def test_booking_unknown_slot_rejected(api):
    """PRD 2.7: "Body-referenced identifiers must exist (`ERR_NOT_FOUND`); the
    student must be `ENROLLED` (`ERR_STUDENT_NOT_BOOKABLE`); a student-teacher
    link must exist — and for `ELEMENTARY` windows must be the homeroom link
    (`ERR_TEACHER_NOT_LINKED`)."

    Design: Corner/validations/booking_unknown_slot_rejected
    """
    family = add_family()
    student = add_student(family["id"], grade_level=3)
    guardian = guardian_headers(family)
    response = api.create_booking(
        create_booking_payload(MISSING_UUID, student["id"], "IN_PERSON"), guardian
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# Channel rules and the family gap rule
# ---------------------------------------------------------------------------


def test_channel_not_allowed_rejected(api):
    """PRD 3.4: "The requested `channel` must be compatible with the slot's
    `channel_allowed` and the teacher's channel support flags, otherwise
    `ERR_CHANNEL_NOT_ALLOWED`."

    Design: Corner/validations/channel_not_allowed_rejected
    """
    # Default teacher supports in-person only, so its slots allow IN_PERSON.
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    slot = ctx["teacher_slots"][teacher_id][0]
    assert slot["channel_allowed"] == "IN_PERSON"

    response = api.create_booking(
        create_booking_payload(slot["id"], party["students"][0]["id"], "VIRTUAL"),
        party["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_CHANNEL_NOT_ALLOWED, 422)


def test_virtual_back_to_back_same_channel_allowed(api):
    """PRD 3.4: "The separation required between two bookings depends on their
    channels: zero minutes when both are `VIRTUAL`; the window's
    `buffer_minutes` when both are `IN_PERSON`; and the window's
    `travel_minutes` when the two channels differ."

    Design: Corner/validations/virtual_back_to_back_same_channel_allowed
    """
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        teacher_specs=[{"supports_in_person": True, "supports_virtual": True}],
    )
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(ctx, 2, grade_levels=[3, 4])

    first = book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"],
                      channel="VIRTUAL")
    second = book_slot(slots[1]["id"], party["students"][1]["id"], party["guardian"],
                       channel="VIRTUAL")
    assert first["status"] == "CONFIRMED"
    assert second["status"] == "CONFIRMED"


def test_family_travel_gap_exact_boundary_allowed(api):
    """PRD 3.4: "The separation required between two bookings depends on their
    channels: zero minutes when both are `VIRTUAL`; the window's
    `buffer_minutes` when both are `IN_PERSON`; and the window's
    `travel_minutes` when the two channels differ."
    PRD 3.4: "The pair conflicts unless the candidate starts at or after the
    existing booking's slot end plus the required separation, or the existing
    booking starts at or after the candidate's slot end plus the required
    separation — a separation exactly equal to the requirement is allowed. A
    violation is rejected with `ERR_FAMILY_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/family_channel_switch_travel_gap_boundary
    """
    ctx = scenario_travel_gap()
    slots, party = ctx["slots"], ctx["party"]
    book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"],
              channel="IN_PERSON")
    # Slot 2 starts 15:50 — exactly travel_minutes (30) after slot 0 ends 15:20.
    boundary = book_slot(slots[2]["id"], party["students"][1]["id"], party["guardian"],
                         channel="VIRTUAL")
    assert boundary["status"] == "CONFIRMED"


def test_family_mixed_channel_gap_violation_rejected(api):
    """PRD 3.4: "The pair conflicts unless the candidate starts at or after the
    existing booking's slot end plus the required separation, or the existing
    booking starts at or after the candidate's slot end plus the required
    separation — a separation exactly equal to the requirement is allowed. A
    violation is rejected with `ERR_FAMILY_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/family_channel_switch_travel_gap_boundary
    """
    ctx = scenario_travel_gap()
    slots, party = ctx["slots"], ctx["party"]
    book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"],
              channel="IN_PERSON")
    book_slot(slots[2]["id"], party["students"][1]["id"], party["guardian"],
              channel="VIRTUAL")
    # Slot 1 (15:25-15:45, IN_PERSON) leaves only a 5-minute gap to the VIRTUAL
    # booking at 15:50, below the 30-minute mixed-channel requirement.
    response = api.create_booking(
        create_booking_payload(slots[1]["id"], party["students"][2]["id"], "IN_PERSON"),
        party["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_FAMILY_SCHEDULE_CONFLICT, 409)
    assert_window_counters(read_window(ctx["window"]["id"]), confirmed=2)


# ---------------------------------------------------------------------------
# Capacity caps
# ---------------------------------------------------------------------------


def test_teacher_day_cap_boundary_third_booking_rejected(api):
    """PRD 3.4: "Two caps apply: the teacher's `CONFIRMED` bookings on the
    slot's `day_label` must still be below the effective daily cap — the
    smaller of the window's `teacher_daily_conf_cap` and the teacher's
    `daily_conf_cap_override` when the override is set — otherwise
    `ERR_TEACHER_DAY_FULL`; and the family's `CONFIRMED` bookings in the window
    must be below `family_conf_cap`, otherwise `ERR_FAMILY_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/teacher_day_cap_boundary_third_booking_rejected
    """
    ctx = scenario_day_cap(window_cap=2)
    slots, party = ctx["slots"], ctx["party"]
    first = book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"])
    second = book_slot(slots[1]["id"], party["students"][1]["id"], party["guardian"])
    assert first["status"] == "CONFIRMED" and second["status"] == "CONFIRMED"

    response = api.create_booking(
        create_booking_payload(slots[2]["id"], party["students"][2]["id"], "IN_PERSON"),
        party["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_TEACHER_DAY_FULL, 422)
    assert_window_counters(read_window(ctx["window"]["id"]), confirmed=2)


def test_teacher_day_cap_override_shrinks_effective_cap(api):
    """PRD 3.4: "Two caps apply: the teacher's `CONFIRMED` bookings on the
    slot's `day_label` must still be below the effective daily cap — the
    smaller of the window's `teacher_daily_conf_cap` and the teacher's
    `daily_conf_cap_override` when the override is set — otherwise
    `ERR_TEACHER_DAY_FULL`; and the family's `CONFIRMED` bookings in the window
    must be below `family_conf_cap`, otherwise `ERR_FAMILY_LIMIT_REACHED`."
    PRD 3.3: "Scheduling-relevant defaults matter: `room_location` defaults to
    null, `supports_in_person` defaults to true, `supports_virtual` defaults to
    false, and `daily_conf_cap_override` defaults to null — when set, the
    override replaces the window's `teacher_daily_conf_cap` for that teacher
    alone."

    Design: Difficulty/boundary_precision_check/teacher_day_cap_boundary_third_booking_rejected
    """
    # Window cap 2 but the teacher's override 1 makes the effective cap 1.
    ctx = scenario_day_cap(window_cap=2, teacher_override=1)
    slots, party = ctx["slots"], ctx["party"]
    first = book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"])
    assert first["status"] == "CONFIRMED"

    response = api.create_booking(
        create_booking_payload(slots[1]["id"], party["students"][1]["id"], "IN_PERSON"),
        party["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_TEACHER_DAY_FULL, 422)
    assert_window_counters(read_window(ctx["window"]["id"]), confirmed=1)


def test_family_cap_reached_rejected(api):
    """PRD 3.4: "Two caps apply: the teacher's `CONFIRMED` bookings on the
    slot's `day_label` must still be below the effective daily cap — the
    smaller of the window's `teacher_daily_conf_cap` and the teacher's
    `daily_conf_cap_override` when the override is set — otherwise
    `ERR_TEACHER_DAY_FULL`; and the family's `CONFIRMED` bookings in the window
    must be below `family_conf_cap`, otherwise `ERR_FAMILY_LIMIT_REACHED`."

    Design: Corner/validations/family_cap_reached_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN", window_overrides={"family_conf_cap": 2})
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(ctx, 3, grade_levels=[1, 2, 3])
    book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"])
    book_slot(slots[1]["id"], party["students"][1]["id"], party["guardian"])

    response = api.create_booking(
        create_booking_payload(slots[2]["id"], party["students"][2]["id"], "IN_PERSON"),
        party["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_FAMILY_LIMIT_REACHED, 422)


# ---------------------------------------------------------------------------
# Sibling compactness score (tiered gaps with channel-switch multiplier)
# ---------------------------------------------------------------------------


def test_compactness_score_grows_per_booking(api):
    """PRD 3.4: "Each adjacent pair contributes points based on the gap in
    minutes between the earlier slot's end and the later slot's start: a gap of
    at most fifteen minutes contributes 1 point; a gap longer than fifteen but
    at most forty-five minutes contributes 3 points; any longer gap contributes
    8 points. The contribution doubles when the two bookings use different
    channels. The score is the sum over all adjacent pairs, rounded half-up to
    two decimal places, and a family with a single qualifying booking scores
    0.00."

    Design: Difficulty/combinatorial_formula/sibling_compactness_tiered_channel_switch
    """
    ctx = scenario_compactness()
    teachers = ctx["teachers"]
    slot_a = ctx["teacher_slots"][teachers[0]["id"]][0]   # 15:00-15:20
    slot_b = ctx["teacher_slots"][teachers[1]["id"]][1]   # 15:25-15:45
    slot_c = ctx["teacher_slots"][teachers[2]["id"]][5]   # 17:20-17:40
    students = ctx["students"]
    guardian = ctx["guardian"]

    first = book_slot(slot_a["id"], students[0]["id"], guardian, channel="IN_PERSON")
    assert first["family_compactness_score"] == pytest.approx(0.00, abs=0.01)

    second = book_slot(slot_b["id"], students[1]["id"], guardian, channel="IN_PERSON")
    # Gap of 5 minutes, same channel: tier 1, single pair.
    assert second["family_compactness_score"] == pytest.approx(1.00, abs=0.01)

    third = book_slot(slot_c["id"], students[2]["id"], guardian, channel="VIRTUAL")
    # 1 + (95-minute tier-3 gap of 8 points doubled by the channel switch) = 17.
    assert third["family_compactness_score"] == pytest.approx(17.00, abs=0.01)


def test_compactness_score_stored_on_every_family_booking(api):
    """PRD 3.4: "Sibling logistics are quantified by `family_compactness_score`,
    a value stored on every booking of a family in a window and recomputed
    after every booking mutation — creation, cancellation, rescheduling, or
    waitlist claim — for that family-window pair."

    Design: Difficulty/combinatorial_formula/sibling_compactness_tiered_channel_switch
    """
    ctx = scenario_compactness()
    teachers = ctx["teachers"]
    slot_a = ctx["teacher_slots"][teachers[0]["id"]][0]
    slot_b = ctx["teacher_slots"][teachers[1]["id"]][1]
    slot_c = ctx["teacher_slots"][teachers[2]["id"]][5]
    students = ctx["students"]
    guardian = ctx["guardian"]

    first = book_slot(slot_a["id"], students[0]["id"], guardian, channel="IN_PERSON")
    book_slot(slot_b["id"], students[1]["id"], guardian, channel="IN_PERSON")
    book_slot(slot_c["id"], students[2]["id"], guardian, channel="VIRTUAL")

    # The first booking is re-read: it carries the recomputed shared score.
    reread = validate_success(api.get_booking(first["id"], guardian))
    assert_booking(reread)
    assert reread["family_compactness_score"] == pytest.approx(17.00, abs=0.01)
