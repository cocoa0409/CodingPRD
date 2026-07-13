"""Temporal overlap, numeric boundaries, capacity conservation, and safety validations
(PRD §3.2, §3.4, §3.8)."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_course_slot_guide, create_course, create_time_slot, create_guide,
    assign_guide, create_participant, create_booking, create_group,
    create_gear_item, checkout_gear, get_time_slot,
)

OP = TEST_USERS["operator_headers"]


# ── Guide temporal overlap: half-open, adjacency allowed ───────────────────
def _course_three_saturday_slots(api):
    """Course duration 90; slots A(10:00, end 11:30), B(11:30 adjacent), C(11:00 overlap)."""
    course = create_course(api)
    ts_a = create_time_slot(api, course["id"], start_at="2026-06-06T10:00:00Z")
    ts_b = create_time_slot(api, course["id"], start_at="2026-06-06T11:30:00Z")
    ts_c = create_time_slot(api, course["id"], start_at="2026-06-06T11:00:00Z")
    guide = create_guide(api)
    assign_guide(api, guide["id"], ts_a["id"])
    return guide, ts_a, ts_b, ts_c


def test_guide_adjacent_slot_assignment_allowed(api):
    """PRD §3.2: "Overlap is measured on the half-open interval from `start_at` up to but
    not including `end_at`, so two tours that merely touch — one ending exactly when the
    next begins — do not overlap and are allowed."

    Design: Difficulty/resource_temporal_overlap/guide_overlap_halfopen_adjacency_allowed
    """
    guide, ts_a, ts_b, ts_c = _course_three_saturday_slots(api)
    res = api.create_guide_assignment(
        {"guide_id": guide["id"], "time_slot_id": ts_b["id"]}, OP)
    ga = validate_success(res, 201)
    assert ga["status"] == "ASSIGNED"


def test_guide_overlapping_slot_assignment_rejected(api):
    """PRD §3.2: "a guide may not be double-booked: the assignment is refused with
    `ERR_GUIDE_DOUBLE_BOOKED` if the guide is already `ASSIGNED` to another slot whose time
    interval overlaps this slot's interval."

    Design: Difficulty/resource_temporal_overlap/guide_overlap_halfopen_adjacency_allowed
    """
    guide, ts_a, ts_b, ts_c = _course_three_saturday_slots(api)
    res = api.create_guide_assignment(
        {"guide_id": guide["id"], "time_slot_id": ts_c["id"]}, OP)
    validate_error(res, "ERR_GUIDE_DOUBLE_BOOKED", expected_status=409)


# ── Gear window overlap: buffered [start, end+30), touching allowed ────────
def _three_slots_gear_on_first(api):
    """Slots A(10:00), B(11:30), C(12:00) each with own guide + booking; a HARNESS is
    checked out to booking b_a (window [10:00, 12:00))."""
    course = create_course(api)
    ts_a = create_time_slot(api, course["id"], start_at="2026-06-06T10:00:00Z")
    ts_b = create_time_slot(api, course["id"], start_at="2026-06-06T11:30:00Z")
    ts_c = create_time_slot(api, course["id"], start_at="2026-06-06T12:00:00Z")
    for i, ts in enumerate((ts_a, ts_b, ts_c)):
        g = create_guide(api, name=f"G{i+1}")
        assign_guide(api, g["id"], ts["id"])
    b = {}
    for key, ts in (("a", ts_a), ("b", ts_b), ("c", ts_c)):
        p = create_participant(api, full_name=f"P {key}")
        b[key] = create_booking(api, ts["id"], p["id"])
    gear = create_gear_item(api, gear_type="HARNESS", size="M")
    checkout_gear(api, gear["id"], b["a"]["id"])
    return gear, b


def test_gear_back_to_back_within_buffer_rejected(api):
    """PRD §3.8: "Checkout is refused with `ERR_GEAR_UNAVAILABLE` if the item already has
    an outstanding checkout whose window overlaps the new booking's window."

    Design: Difficulty/resource_temporal_overlap/gear_overlap_buffered_backtoback_rejected
    """
    gear, b = _three_slots_gear_on_first(api)
    res = api.create_gear_checkout(
        {"gear_item_id": gear["id"], "booking_id": b["b"]["id"]}, OP)
    validate_error(res, "ERR_GEAR_UNAVAILABLE", expected_status=409)


def test_gear_after_cleaning_buffer_allowed(api):
    """PRD §3.8: "Overlap is measured on the half-open interval from `window_start` up to
    but not including `window_end`, so windows that merely touch at their endpoints do not
    overlap and are allowed — this is what lets one item serve back-to-back tours once the
    30-minute cleaning gap is respected."

    Design: Difficulty/resource_temporal_overlap/gear_overlap_buffered_backtoback_rejected
    """
    gear, b = _three_slots_gear_on_first(api)
    res = api.create_gear_checkout(
        {"gear_item_id": gear["id"], "booking_id": b["c"]["id"]}, OP)
    checkout = validate_success(res, 201)
    assert checkout["status"] == "OUT"


# ── Weight boundary: inclusive max ─────────────────────────────────────────
def test_weight_exactly_at_max_accepted(api):
    """PRD §3.4: "Their `weight_kg` must lie within the inclusive range from the course's
    `min_weight_kg` to `max_weight_kg`, or the booking is refused with
    `ERR_WEIGHT_OUT_OF_RANGE`."

    Design: Difficulty/boundary_precision_check/weight_at_max_inclusive_vs_over_on_booking
    """
    course, ts, guide = setup_course_slot_guide(api)  # max_weight_kg 120
    p = create_participant(api, full_name="Eq", weight_kg=120.0)
    booking = validate_success(
        api.create_booking({"time_slot_id": ts["id"], "participant_id": p["id"]}, OP), 201)
    assert booking["status"] == "CONFIRMED"


def test_weight_over_max_rejected(api):
    """PRD §3.4: "Their `weight_kg` must lie within the inclusive range from the course's
    `min_weight_kg` to `max_weight_kg`, or the booking is refused with
    `ERR_WEIGHT_OUT_OF_RANGE`."

    Design: Difficulty/boundary_precision_check/weight_at_max_inclusive_vs_over_on_booking
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api, full_name="Over", weight_kg=120.1)
    res = api.create_booking({"time_slot_id": ts["id"], "participant_id": p["id"]}, OP)
    validate_error(res, "ERR_WEIGHT_OUT_OF_RANGE", expected_status=422)


# ── Understaffing boundary: inclusive >= on assignment cancel ──────────────
def _slot_two_guides_four_bookings(api):
    """Capacity-8 slot, TWO guides ASSIGNED (assigned_capacity 8), four bookings."""
    course, ts, guide = setup_course_slot_guide(api, capacity=8)  # guide 1 assigned
    guide2 = create_guide(api, name="G2")
    ga2 = assign_guide(api, guide2["id"], ts["id"])
    for name in ("M1", "M2", "M3", "M4"):
        p = create_participant(api, full_name=name)
        create_booking(api, ts["id"], p["id"])
    # find the first guide's assignment id
    listed = api.list_guide_assignments(OP, params={"time_slot_id": ts["id"]}).json()["data"]
    ga1 = next(a for a in listed if a["guide_id"] == guide["id"])
    return ts, ga1, ga2


def test_understaff_cancel_at_capacity_boundary_allowed(api):
    """PRD §3.2: "with one fewer assigned guide, the remaining assigned capacity — that is,
    the assigned-guide count minus one, multiplied by `max_participants_per_guide` — must
    still be greater than or equal to the slot's current `booked_count`."

    Design: Difficulty/boundary_precision_check/understaff_boundary_inclusive_on_assignment_cancel
    """
    ts, ga1, ga2 = _slot_two_guides_four_bookings(api)
    # After cancelling one guide: (2-1)*4 = 4 >= booked_count 4 -> allowed (inclusive).
    cancelled = validate_success(api.cancel_guide_assignment(ga2["id"], OP), 200)
    assert cancelled["status"] == "CANCELLED"


def test_understaff_cancel_below_boundary_rejected(api):
    """PRD §3.2: "If withdrawing the guide would drop assigned capacity below the number of
    active bookings, the cancellation is refused with `ERR_UNDERSTAFFED`."

    Design: Difficulty/boundary_precision_check/understaff_boundary_inclusive_on_assignment_cancel
    """
    ts, ga1, ga2 = _slot_two_guides_four_bookings(api)
    validate_success(api.cancel_guide_assignment(ga2["id"], OP), 200)
    # Now cancelling the last guide: (1-1)*4 = 0 < booked_count 4 -> rejected.
    res = api.cancel_guide_assignment(ga1["id"], OP)
    validate_error(res, "ERR_UNDERSTAFFED", expected_status=409)


# ── Seat-capacity conservation across book / cancel ────────────────────────
def test_seat_released_returns_capacity_to_full_on_cancel(api):
    """PRD §3.4: "The `remaining_capacity` is the slot's `capacity` minus `booked_count`,
    floored at zero."
    PRD §3.6: "the seat is released, and any season-pass commitment is released."

    Design: Difficulty/compensating_invariant/seat_capacity_conserved_book_then_cancel
    """
    course, ts, guide = setup_course_slot_guide(api, capacity=4)
    p = create_participant(api)
    booking = create_booking(api, ts["id"], p["id"])
    assert get_time_slot(api, ts["id"])["remaining_capacity"] == 3
    api.cancel_booking(booking["id"], OP)
    assert get_time_slot(api, ts["id"])["remaining_capacity"] == 4


def test_active_booking_holds_one_seat(api):
    """PRD §3.4: "A slot's `booked_count` is the count of its bookings in the three active
    states `CONFIRMED`, `CHECKED_IN`, and `BRIEFED`; bookings that are `COMPLETED`,
    `CANCELLED`, `RAINCHECKED`, `NO_SHOW`, or `REDEEMED` do not occupy a seat."

    Design: Difficulty/compensating_invariant/seat_capacity_conserved_book_then_cancel
    """
    course, ts, guide = setup_course_slot_guide(api, capacity=4)
    p = create_participant(api)
    create_booking(api, ts["id"], p["id"])
    slot = get_time_slot(api, ts["id"])
    assert slot["booked_count"] == 1
    assert slot["remaining_capacity"] == 3


# ── Isolated safety / capacity validations ─────────────────────────────────
def test_guide_uncertified_assignment_rejected(api):
    """PRD §3.2: "the guide's `certification_level` must be at least the course's
    `difficulty_level`, otherwise the assignment is refused with `ERR_GUIDE_UNCERTIFIED`."

    Design: Corner/validations/guide_uncertified_422
    """
    course = create_course(api, difficulty_level=2)
    ts = create_time_slot(api, course["id"], start_at="2026-06-03T10:00:00Z")
    rookie = create_guide(api, name="Rookie", certification_level=1)
    res = api.create_guide_assignment(
        {"guide_id": rookie["id"], "time_slot_id": ts["id"]}, OP)
    validate_error(res, "ERR_GUIDE_UNCERTIFIED", expected_status=422)


def test_age_below_minimum_booking_rejected(api):
    """PRD §3.4: "Their `age_years` must be at least the course's `min_age_years`, or the
    booking is refused with `ERR_AGE_BELOW_MINIMUM`."

    Design: Corner/validations/age_below_minimum_returns_422
    """
    course, ts, guide = setup_course_slot_guide(api)  # min_age_years 8
    kid = create_participant(api, full_name="Kid", weight_kg=35,
                             birthdate="2019-06-04T00:00:00Z")  # age 6 at default clock
    res = api.create_booking({"time_slot_id": ts["id"], "participant_id": kid["id"]}, OP)
    validate_error(res, "ERR_AGE_BELOW_MINIMUM", expected_status=422)


def test_group_slot_mismatch_booking_rejected(api):
    """PRD §3.4: "A booking that names a `group_id` must target the same slot as the group:
    the group's `time_slot_id` must equal the booking's `time_slot_id`, otherwise the
    booking is refused with `ERR_GROUP_SLOT_MISMATCH`."

    Design: Corner/validations/group_slot_mismatch_returns_422
    """
    course = create_course(api)
    ts_a = create_time_slot(api, course["id"], start_at="2026-06-03T10:00:00Z")
    ts_b = create_time_slot(api, course["id"], start_at="2026-06-10T10:00:00Z")
    guide = create_guide(api)
    assign_guide(api, guide["id"], ts_b["id"])
    group = create_group(api, ts_a["id"], expected_size=2, name="Team")
    p = create_participant(api)
    res = api.create_booking(
        {"time_slot_id": ts_b["id"], "participant_id": p["id"], "group_id": group["id"]},
        OP)
    validate_error(res, "ERR_GROUP_SLOT_MISMATCH", expected_status=422)


def test_slot_full_second_booking_rejected(api):
    """PRD §3.4: "A booking is refused with `ERR_SLOT_FULL` unless `remaining_capacity` is
    at least 1 and admitting it would keep `booked_count` plus one no greater than the
    smaller of the slot's `capacity` and its assigned capacity".

    Design: Corner/validations/slot_full_returns_409
    """
    course, ts, guide = setup_course_slot_guide(api, capacity=1)
    p_a = create_participant(api, full_name="P A")
    p_b = create_participant(api, full_name="P B")
    create_booking(api, ts["id"], p_a["id"])  # fills the single seat
    res = api.create_booking({"time_slot_id": ts["id"], "participant_id": p_b["id"]}, OP)
    validate_error(res, "ERR_SLOT_FULL", expected_status=409)
