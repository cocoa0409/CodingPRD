"""Fitness classes: instructor pay estimate/final variants, per-session
rounding, seat conservation and waitlist promotion, completion gating, and
class-specific validation errors (PRD §2.7, §2.8, §2.9, §3.1, §3.8)."""
from test_helpers import (
    REC_ADMIN,
    ApiErrorId,
    api_client,
    class_context,
    create_class,
    create_eligible_member,
    create_facility,
    create_instructor,
    create_member,
    create_pool,
    make_member_headers,
    make_staff_headers,
    purchase_membership,
    register_for_class,
    register_members,
    set_clock,
    sign_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)

CLASS_START = "2026-09-08T18:00:00Z"
CLASS_END = "2026-09-08T19:00:00Z"
PAST_END = "2026-09-08T19:01:00Z"


def test_instructor_estimate_at_creation_has_no_bonus():
    """PRD §3.8: "A new class is `SCHEDULED` with `registered_count` and
    `waitlist_count` at zero, and its `instructor_pay_estimate_cents` is
    computed immediately as the duration in minutes times the instructor's
    `base_hourly_rate_cents`, divided by 60, rounded half-up — with no
    attendance bonus. `instructor_pay_cents` and `attendance_count` stay null
    until completion."

    Design: Difficulty/dual_variant_calc/instructor_estimate_vs_final_class_pay
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=5)
    fclass = ctx["class"]
    assert fclass["status"] == "SCHEDULED"
    assert fclass["duration_minutes"] == 60
    assert fclass["instructor_pay_estimate_cents"] == 3000  # 60 * 3000 / 60
    assert fclass["instructor_pay_cents"] is None
    assert fclass["attendance_count"] is None


def test_instructor_final_pay_with_attendance_bonus():
    """PRD §3.8: "Final instructor pay is computed at completion: the fill
    ratio is `attendance_count` divided by `capacity`; the bonus is 20 percent
    when the fill is at least 0.80, else 10 percent when the fill is at least
    0.50, else zero — bounds inclusive, so a capacity-10 class with 8
    attendees fills at exactly 0.80 and earns the 20 percent bonus.
    `instructor_pay_cents` is the duration times the base hourly rate, times
    one plus the bonus, divided by 60, rounded half-up to whole cents per
    session. The amount is added directly to the instructor's
    `payroll_paid_cents` — the instructor rail never passes through pending —
    and term payroll totals sum the already-rounded per-session values."
    PRD §3.8: "Completion moves every `REGISTERED` registration to `ATTENDED`,
    except those listed, which become `NO_SHOW` and increment their member's
    `no_show_count`; every `WAITLISTED` registration becomes `CANCELLED`."

    Design: Difficulty/dual_variant_calc/instructor_estimate_vs_final_class_pay
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=5)
    members, registrations = register_members(ctx["class"]["id"], 4,
                                              email_prefix="y")
    set_clock(PAST_END)
    completed = validate_success(api_client.complete_fitness_class(
        ctx["class"]["id"],
        {"no_show_registration_ids": [registrations[3]["id"]]},
        make_staff_headers(ctx["instructor"]["id"]),
    ))
    assert completed["status"] == "COMPLETED"
    assert completed["attendance_count"] == 3
    # fill 3/5 = 0.60 -> +10% tier: round_half_up(60 * 3000 * 1.1 / 60).
    assert completed["instructor_pay_cents"] == 3300
    reg_3 = validate_success(api_client.get_class_registration(
        registrations[3]["id"], REC_ADMIN))
    assert reg_3["status"] == "NO_SHOW"
    member_3 = validate_success(api_client.get_member(
        members[3]["id"], REC_ADMIN))
    assert member_3["no_show_count"] == 1
    staff = validate_success(api_client.get_staff(
        ctx["instructor"]["id"], REC_ADMIN))
    assert staff["payroll_paid_cents"] == 3300
    assert staff["payroll_pending_cents"] == 0, (
        "the instructor rail pays directly to paid, never pending"
    )


def _two_session_instructor_ctx():
    """Instructor (rate 3333, certified HIIT+SPIN) with two 50-minute classes,
    one attendee each (fill 0.25 -> no bonus); clock moved past both ends."""
    set_clock("2026-08-24T00:00:00Z")
    # Tuesday + Wednesday windows cover the two session dates.
    facility = create_facility(name="Studio", kind="ROOM", days=(1, 2))
    instructor = create_instructor(rate=3333, class_types=("HIIT", "SPIN"))
    class_1 = create_class(instructor["id"], facility["id"],
                           title="HIIT 50", class_type="HIIT",
                           start_at="2026-09-08T18:00:00Z",
                           end_at="2026-09-08T18:50:00Z", capacity=4)
    class_2 = create_class(instructor["id"], facility["id"],
                           title="Spin 50", class_type="SPIN",
                           start_at="2026-09-09T18:00:00Z",
                           end_at="2026-09-09T18:50:00Z", capacity=4)
    register_members(class_1["id"], 1, email_prefix="h1")
    register_members(class_2["id"], 1, email_prefix="h2")
    set_clock("2026-09-09T19:00:00Z")
    return instructor, class_1, class_2



def test_per_session_pay_rounds_half_up_each_session():
    """PRD §3.8: "`instructor_pay_cents` is the duration times the base hourly
    rate, times one plus the bonus, divided by 60, rounded half-up to whole
    cents per session."
    PRD §2.7: "instructor pay is rounded half-up *per session*, and term
    totals are sums of the already-rounded per-session values — never a sum of
    raw values rounded once."

    Design: Difficulty/combinatorial_formula/instructor_payroll_round_per_session_sum
    """
    instructor, class_1, class_2 = _two_session_instructor_ctx()
    for fclass in (class_1, class_2):
        completed = validate_success(api_client.complete_fitness_class(
            fclass["id"], {"no_show_registration_ids": []},
            make_staff_headers(instructor["id"]),
        ))
        # round_half_up(50 * 3333 / 60) = round_half_up(2777.5) per session.
        assert completed["instructor_pay_cents"] == 2778


def test_term_payroll_sums_rounded_sessions_not_raw():
    """PRD §2.7: "instructor pay is rounded half-up *per session*, and term
    totals are sums of the already-rounded per-session values — never a sum of
    raw values rounded once."

    Design: Difficulty/combinatorial_formula/instructor_payroll_round_per_session_sum
    """
    instructor, class_1, class_2 = _two_session_instructor_ctx()
    for fclass in (class_1, class_2):
        validate_success(api_client.complete_fitness_class(
            fclass["id"], {"no_show_registration_ids": []},
            make_staff_headers(instructor["id"]),
        ))
    staff = validate_success(api_client.get_staff(
        instructor["id"], REC_ADMIN))
    # 2778 + 2778 = 5556; a sum-then-round reading would yield
    # round_half_up(5555.0) = 5555 and must not be produced.
    assert staff["payroll_paid_cents"] == 5556


def test_registered_cancel_promotes_head_and_conserves_seat():
    """PRD §3.8: "Cancelling a `REGISTERED` entry decrements
    `registered_count` and then runs **waitlist promotion**: among the class's
    `WAITLISTED` registrations, the head is the one with the earliest
    registration `created_at`, ties broken by the candidate member's earlier
    `created_at`; the head is promoted to `REGISTERED`, decrementing
    `waitlist_count` by 1 while `registered_count` returns to its prior value
    — the seat is handed off, and the two counts are conserved. An empty
    waitlist makes promotion a no-op. Promotion never runs for a class that is
    `CANCELLED` or `COMPLETED`."

    Design: Difficulty/compensating_invariant/class_seat_conservation_through_promotion
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=2)
    members, registrations = register_members(ctx["class"]["id"], 3,
                                              email_prefix="s")
    reg_a, _, reg_c = registrations
    mid = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert mid["registered_count"] == 2
    assert mid["waitlist_count"] == 1

    validate_success(api_client.cancel_class_registration(
        reg_a["id"], make_member_headers(members[0]["id"])))
    after = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert after["registered_count"] == 2, (
        "the seat changed hands; the count is conserved"
    )
    assert after["waitlist_count"] == 0


def test_cancelled_and_promoted_registration_statuses():
    """PRD §3.8: "The new registration's initial status is capacity-dependent:
    `REGISTERED` when the class's `registered_count` is below `capacity` at
    creation — incrementing `registered_count` — and `WAITLISTED` otherwise,
    incrementing `waitlist_count`. A full class is not an error."
    PRD §3.8: "the head is promoted to `REGISTERED`, decrementing
    `waitlist_count` by 1 while `registered_count` returns to its prior value
    — the seat is handed off, and the two counts are conserved."

    Design: Difficulty/compensating_invariant/class_seat_conservation_through_promotion
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=2)
    members, registrations = register_members(ctx["class"]["id"], 3,
                                              email_prefix="s")
    reg_a, _, reg_c = registrations
    assert reg_c["status"] == "WAITLISTED", (
        "the third seat request overflowed the capacity-2 class"
    )
    validate_success(api_client.cancel_class_registration(
        reg_a["id"], make_member_headers(members[0]["id"])))
    reg_a_after = validate_success(api_client.get_class_registration(
        reg_a["id"], REC_ADMIN))
    assert reg_a_after["status"] == "CANCELLED"
    reg_c_after = validate_success(api_client.get_class_registration(
        reg_c["id"], REC_ADMIN))
    assert reg_c_after["status"] == "REGISTERED"


def test_stale_waiver_fires_before_class_time_conflict():
    """PRD §3.1: "A waiver is valid exactly when `waiver_signed_date` is not
    null and the academic year of `waiver_signed_date` equals the academic
    year of the logical current date — a waiver signed on 2026-09-15 is valid
    from 2026-08-01 through 2027-07-31 and becomes stale on 2027-08-01."
    PRD §2.8: "When a request fails multiple checks, the error returned is
    determined by a fixed priority order — lower priority number wins."
    (waiver validity is priority 7; temporal checks — including
    `ERR_CLASS_TIME_CONFLICT` — are priority 9.)

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_class_registration_precedence
    """
    set_clock("2026-09-01T09:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    member = sign_waiver(member)  # signed 2026-09-01 -> academic year 2026-27
    purchase_membership(member, "SUMMER_2027")  # pre-purchased; active later
    facility_1 = create_facility(name="Studio 1", kind="ROOM", days=(0,))
    facility_2 = create_facility(name="Studio 2", kind="ROOM", days=(0,))
    instructor = create_instructor(rate=3000, class_types=("YOGA", "PILATES"))
    class_c = create_class(instructor["id"], facility_1["id"],
                           title="Yoga C", class_type="YOGA",
                           start_at="2027-08-02T18:00:00Z",
                           end_at="2027-08-02T19:00:00Z", capacity=6)
    class_b = create_class(instructor["id"], facility_2["id"],
                           title="Pilates B", class_type="PILATES",
                           start_at="2027-08-02T18:30:00Z",
                           end_at="2027-08-02T19:15:00Z", capacity=6)
    set_clock("2027-07-30T09:00:00Z")  # waiver still valid for AY2026-27
    register_for_class(class_c["id"], member)
    set_clock("2027-08-01T09:00:00Z")  # academic year rolled: waiver stale
    # Both violations hold (stale waiver; 18:30-19:15 overlaps the 18:00-19:00
    # registration); the waiver check wins.
    resp = api_client.create_class_registration(
        class_b["id"], {"member_id": member["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID)


def test_rejected_registration_creates_no_row():
    """PRD §3.1: "A waiver is valid exactly when `waiver_signed_date` is not
    null and the academic year of `waiver_signed_date` equals the academic
    year of the logical current date — a waiver signed on 2026-09-15 is valid
    from 2026-08-01 through 2027-07-31 and becomes stale on 2027-08-01."
    PRD §2.3: "and class registrations by `fitness_class_id`, `member_id`,
    or `status`".

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_class_registration_precedence
    """
    set_clock("2026-09-01T09:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    member = sign_waiver(member)
    purchase_membership(member, "SUMMER_2027")
    facility_1 = create_facility(name="Studio 1", kind="ROOM", days=(0,))
    facility_2 = create_facility(name="Studio 2", kind="ROOM", days=(0,))
    instructor = create_instructor(rate=3000, class_types=("YOGA", "PILATES"))
    class_c = create_class(instructor["id"], facility_1["id"],
                           title="Yoga C", class_type="YOGA",
                           start_at="2027-08-02T18:00:00Z",
                           end_at="2027-08-02T19:00:00Z", capacity=6)
    class_b = create_class(instructor["id"], facility_2["id"],
                           title="Pilates B", class_type="PILATES",
                           start_at="2027-08-02T18:30:00Z",
                           end_at="2027-08-02T19:15:00Z", capacity=6)
    set_clock("2027-07-30T09:00:00Z")
    register_for_class(class_c["id"], member)
    set_clock("2027-08-01T09:00:00Z")
    resp = api_client.create_class_registration(
        class_b["id"], {"member_id": member["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID)
    _, meta = validate_paginated(api_client.list_class_registrations(
        REC_ADMIN, params={"member_id": member["id"]}))
    assert meta["total_count"] == 1, "only the class C registration exists"


def test_fill_rate_080_bonus_boundary():
    """PRD §3.8: "the bonus is 20 percent when the fill is at least 0.80, else
    10 percent when the fill is at least 0.50, else zero — bounds inclusive,
    so a capacity-10 class with 8 attendees fills at exactly 0.80 and earns
    the 20 percent bonus. `instructor_pay_cents` is the duration times the
    base hourly rate, times one plus the bonus, divided by 60, rounded half-up
    to whole cents per session."

    Design: Corner/calculations/fill_rate_080_bonus_boundary
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=5)
    register_members(ctx["class"]["id"], 4, email_prefix="b")
    set_clock(PAST_END)
    completed = validate_success(api_client.complete_fitness_class(
        ctx["class"]["id"], {"no_show_registration_ids": []},
        make_staff_headers(ctx["instructor"]["id"]),
    ))
    assert completed["attendance_count"] == 4
    # fill 4/5 = 0.80 hits the inclusive +20% tier: 60 * 3000 * 1.2 / 60.
    assert completed["instructor_pay_cents"] == 3600


def test_class_complete_before_end_returns_invalid_state():
    """PRD §3.8: "After the logical clock reaches a `SCHEDULED` class's
    `end_at`, the class's instructor or a `RecAdmin` completes it (before
    `end_at`, or on a non-`SCHEDULED` class, is `ERR_INVALID_STATE`; a `Staff`
    caller who is not the class's `instructor_staff_id` is `ERR_FORBIDDEN`),
    optionally listing `no_show_registration_ids`."

    Design: Corner/state_machines/class_complete_before_end_returns_invalid_state
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context()
    set_clock("2026-09-08T18:30:00Z")  # mid-class
    resp = api_client.complete_fitness_class(
        ctx["class"]["id"], {"no_show_registration_ids": []},
        make_staff_headers(ctx["instructor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fclass = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert fclass["status"] == "SCHEDULED"
    staff = validate_success(api_client.get_staff(
        ctx["instructor"]["id"], REC_ADMIN))
    assert staff["payroll_paid_cents"] == 0


def test_waitlist_cancel_no_promotion_vs_registered_cancel_promotes():
    """PRD §3.8: "A registration in `REGISTERED` or `WAITLISTED`, addressed by
    its `class_registration_id`, may be cancelled by the member or a
    `RecAdmin` (a registration in any other status is `ERR_INVALID_STATE`).
    Cancelling a `WAITLISTED` entry simply decrements `waitlist_count`.
    Cancelling a `REGISTERED` entry decrements `registered_count` and then
    runs **waitlist promotion**: among the class's `WAITLISTED` registrations,
    the head is the one with the earliest registration `created_at`, ties
    broken by the candidate member's earlier `created_at`; the head is
    promoted to `REGISTERED`, decrementing `waitlist_count` by 1 while
    `registered_count` returns to its prior value — the seat is handed off,
    and the two counts are conserved."

    Design: Corner/state_machines/waitlist_cancel_no_promotion_vs_registered_cancel_promotes
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=2)
    members, registrations = register_members(ctx["class"]["id"], 4,
                                              email_prefix="r")
    reg_a, _, reg_c, reg_d = registrations
    assert reg_c["status"] == "WAITLISTED"
    assert reg_d["status"] == "WAITLISTED"

    # Cancelling a WAITLISTED entry drains the waitlist with no promotion.
    validate_success(api_client.cancel_class_registration(
        reg_c["id"], make_member_headers(members[2]["id"])))
    mid = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert mid["registered_count"] == 2
    assert mid["waitlist_count"] == 1
    reg_d_mid = validate_success(api_client.get_class_registration(
        reg_d["id"], REC_ADMIN))
    assert reg_d_mid["status"] == "WAITLISTED"

    # Cancelling a REGISTERED entry promotes the new head.
    validate_success(api_client.cancel_class_registration(
        reg_a["id"], make_member_headers(members[0]["id"])))
    after = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert after["registered_count"] == 2
    assert after["waitlist_count"] == 0
    reg_d_after = validate_success(api_client.get_class_registration(
        reg_d["id"], REC_ADMIN))
    assert reg_d_after["status"] == "REGISTERED"

    # A CANCELLED registration cannot be cancelled again.
    resp = api_client.cancel_class_registration(
        reg_c["id"], make_member_headers(members[2]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_error_class_already_registered_and_time_conflict():
    """PRD §3.8: "A member self-registers for a class with their `member_id`,
    subject to the eligibility gates of §2.9, the uniqueness rule that the
    member must not already hold a `REGISTERED` or `WAITLISTED` registration
    for the same class (`ERR_CLASS_ALREADY_REGISTERED`), and a time-conflict
    rule: the member must not hold a `REGISTERED` registration in another
    `SCHEDULED` class whose half-open interval overlaps the candidate
    (`ERR_CLASS_TIME_CONFLICT`)."

    Design: Corner/errors/error_class_already_registered_and_time_conflict
    """
    set_clock("2026-08-24T00:00:00Z")
    facility_1 = create_facility(name="Studio 1", kind="ROOM")
    facility_2 = create_facility(name="Studio 2", kind="ROOM")
    instructor = create_instructor(rate=3000, class_types=("YOGA", "PILATES"))
    class_1 = create_class(instructor["id"], facility_1["id"],
                           title="Yoga C1", class_type="YOGA",
                           start_at=CLASS_START, end_at=CLASS_END, capacity=6)
    class_2 = create_class(instructor["id"], facility_2["id"],
                           title="Pilates C2", class_type="PILATES",
                           start_at="2026-09-08T18:30:00Z",
                           end_at="2026-09-08T19:15:00Z", capacity=6)
    member = create_eligible_member("mm@x.edu", full_name="Mem M")
    register_for_class(class_1["id"], member)

    resp1 = api_client.create_class_registration(
        class_1["id"], {"member_id": member["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_CLASS_ALREADY_REGISTERED)
    resp2 = api_client.create_class_registration(
        class_2["id"], {"member_id": member["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_CLASS_TIME_CONFLICT)


def test_error_instructor_not_certified():
    """PRD §3.8: "The instructor must be an `INSTRUCTOR` (otherwise
    `ERR_STAFF_NOT_INSTRUCTOR`) whose `certified_class_types` include the
    class's `class_type` (otherwise `ERR_INSTRUCTOR_NOT_CERTIFIED`)."

    Design: Corner/errors/error_instructor_not_certified
    """
    set_clock("2026-08-24T00:00:00Z")
    facility = create_facility(name="Studio", kind="ROOM")
    instructor = create_instructor(rate=3000, class_types=("YOGA",))
    resp = api_client.create_fitness_class(
        {"title": "HIIT PM", "class_type": "HIIT",
         "instructor_staff_id": instructor["id"],
         "facility_id": facility["id"],
         "start_at": CLASS_START, "end_at": "2026-09-08T18:45:00Z",
         "capacity": 5},
        REC_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_CERTIFIED)


def test_non_instructor_staff_cannot_complete_class():
    """PRD §3.8: "After the logical clock reaches a `SCHEDULED` class's
    `end_at`, the class's instructor or a `RecAdmin` completes it (before
    `end_at`, or on a non-`SCHEDULED` class, is `ERR_INVALID_STATE`; a `Staff`
    caller who is not the class's `instructor_staff_id` is `ERR_FORBIDDEN`),
    optionally listing `no_show_registration_ids`."

    Design: Corner/rbac/non_instructor_staff_cannot_complete_class
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context()
    other_instructor = create_instructor(rate=3000, name="Instr Two")
    set_clock(PAST_END)
    resp = api_client.complete_fitness_class(
        ctx["class"]["id"], {"no_show_registration_ids": []},
        make_staff_headers(other_instructor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    fclass = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert fclass["status"] == "SCHEDULED"


def test_waiver_signed_in_july_stale_by_august():
    """PRD §3.1: "Waiver validity is defined over academic years: for a date
    in August through December, its academic year begins August 1 of that
    calendar year; for a date in January through July, its academic year began
    August 1 of the previous calendar year; an academic-year window runs from
    its August 1 start through the following July 31 inclusive."
    PRD §2.9: "Each requires, in order: the member's `status` must be `ACTIVE`
    (a member under an injury hold is `SUSPENDED` and is rejected with
    `ERR_MEMBER_SUSPENDED`); the member must hold a waiver valid for the
    current academic year per §3.1 (otherwise `ERR_WAIVER_INVALID`); and the
    member must hold a membership whose lazily evaluated status is `ACTIVE`
    (otherwise `ERR_MEMBERSHIP_INACTIVE`)."

    Design: Corner/calculations/waiver_signed_in_july_stale_by_august
    """
    set_clock("2026-07-31T09:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    member = sign_waiver(member)
    assert member["waiver_signed_date"] == "2026-07-31"
    set_clock("2026-08-01T09:00:00Z")  # the academic year has rolled over
    purchase_membership(member, "FALL_2026")  # ACTIVE membership, FULL fee
    pool = create_pool()
    # The membership is ACTIVE, but the 2026-07-31 waiver belongs to the ended
    # academic year — and the waiver check runs before the membership check.
    resp = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-08-05T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID)
