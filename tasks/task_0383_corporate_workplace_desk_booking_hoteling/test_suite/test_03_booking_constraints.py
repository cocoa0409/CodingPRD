"""Reservation create gates: workday window, exclusive selector, reservation
limit, seat/room overlap geometry, neighborhood capacity boundary, team zoning,
suspension, the documented gate precedence, and the book/cancel occupancy
conservation invariant.

Translates queue-A difficulty rules `priority_pair_validation_conflict`,
`boundary_precision_check` (capacity boundary), `cross_entity_state_dependency`,
`resource_temporal_overlap`, `compensating_invariant` (occupancy count), and
queue-B Corner `validations` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_employee_headers,
    create_reservation_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# Corner: validations — workday, selector, limit, pagination
# ---------------------------------------------------------------------------
def test_reservation_outside_workday_window_rejected(api):
    """PRD §3.4: "the window must be valid and inside the floor's working day:
    start_minute must be strictly less than end_minute, and both must lie within
    the floor's [workday_start_minute, workday_end_minute] window; a window that
    inverts or falls outside the workday is rejected with ERR_OUTSIDE_WORKDAY
    (HTTP 422)."

    Design: Corner/validations/outside_workday_window_rejected
    """
    env = fx.setup_floor_plan(level=15, clock_date="2026-08-13", clock_minute=400)
    emp_id = env["employee"]["id"]
    # start_minute 500 sits below the floor's workday_start_minute (540)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=env["seat"]["id"],
            booking_date="2026-08-13", start_minute=500, end_minute=600,
            expected_seat_version=env["seat"]["version"]),
        make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WORKDAY)


def test_resource_target_mismatch_seat_type_with_room_id(api):
    """PRD §3.4: "A resource_type/seat_id/room_id combination that violates this
    exclusive selector — a SEAT without a seat, a ROOM without a room, or both
    set — is rejected with ERR_RESOURCE_TARGET_MISMATCH (HTTP 422)."

    Design: Corner/validations/resource_target_mismatch_seat_type_without_seat_id
    """
    floor, room, emp_a, emp_b = fx.setup_room_floor(level=16, clock_date="2026-08-14", clock_minute=500)
    emp_id = emp_a["id"]
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=None, room_id=room["id"],
            booking_date="2026-08-14", start_minute=600, end_minute=660,
            expected_room_version=room["version"]),
        make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_TARGET_MISMATCH)


def test_reservation_limit_reached_rejected(api):
    """PRD §3.4: "The employee must not already hold the policy's
    max_active_reservations_per_employee count of non-terminal (BOOKED or
    CHECKED_IN) reservations on the same floor and booking_date; exceeding it
    yields ERR_RESERVATION_LIMIT_REACHED (HTTP 409)."

    Design: Corner/validations/reservation_limit_reached_rejected
    """
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        2, level=17, max_active=1, clock_date="2026-08-15", clock_minute=500)
    emp = fx.create_employee(team_code="ENG")
    emp_id = emp["id"]
    fx.create_seat_reservation(emp_id, seats[0]["id"], "2026-08-15", 600, 660)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=seats[1]["id"],
            booking_date="2026-08-15", start_minute=700, end_minute=760,
            expected_seat_version=seats[1]["version"]),
        make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_RESERVATION_LIMIT_REACHED)


def test_invalid_pagination_limit_rejected(api):
    """PRD §2.3: "A limit outside the inclusive range of 1 to 100, or a negative
    offset, is rejected with ERR_INVALID_PAGINATION (HTTP 422)."

    Design: Corner/validations/invalid_pagination_limit_rejected
    """
    resp = api.list_reservations(FM, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION)


# ---------------------------------------------------------------------------
# Difficulty A: resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_seat_overlap_genuine_intersection_rejected(api):
    """PRD §3.4: "For a SEAT, the requested window must not intersect any existing
    non-terminal reservation or any active visitor pass on that seat; because
    windows are half-open, two bookings that merely touch at an endpoint (one
    ending exactly where the next begins) do not conflict, while any genuine
    overlap is rejected with ERR_SEAT_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/seat_half_open_overlap_touching_allowed_overlap_rejected
    """
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        1, level=15, cap_pct=100, max_active=5, clock_date="2026-07-06", clock_minute=500)
    seat = seats[0]
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    fx.create_seat_reservation(emp_a["id"], seat["id"], "2026-07-06", 540, 600)
    # 580..640 genuinely overlaps [540,600)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="SEAT", seat_id=seat["id"],
            booking_date="2026-07-06", start_minute=580, end_minute=640,
            expected_seat_version=fx.seat_version(seat["id"])),
        make_employee_headers(emp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_SEAT_DOUBLE_BOOKED)


def test_seat_overlap_touching_endpoint_allowed(api):
    """PRD §3.4: "because windows are half-open, two bookings that merely touch at
    an endpoint (one ending exactly where the next begins) do not conflict, while
    any genuine overlap is rejected with ERR_SEAT_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/seat_half_open_overlap_touching_allowed_overlap_rejected
    """
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        1, level=151, cap_pct=100, max_active=5, clock_date="2026-07-06", clock_minute=500)
    seat = seats[0]
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    fx.create_seat_reservation(emp_a["id"], seat["id"], "2026-07-06", 540, 600)
    # 600..660 touches the prior booking's end exactly -> allowed
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="SEAT", seat_id=seat["id"],
            booking_date="2026-07-06", start_minute=600, end_minute=660,
            expected_seat_version=fx.seat_version(seat["id"])),
        make_employee_headers(emp_b["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


def test_room_buffered_overlap_rejected(api):
    """PRD §3.4: "For a ROOM, the geometry is widened by the room's
    turnover_buffer_minute: the requested window with the turnover buffer appended
    after it must not intersect any existing non-terminal reservation on that
    room, and a conflict is rejected with ERR_ROOM_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_buffered_overlap_turnover_buffer_after_booking
    """
    floor, room, emp_a, emp_b = fx.setup_room_floor(
        level=16, turnover_buffer_minute=15, clock_date="2026-07-07", clock_minute=500)
    fx.create_room_reservation(emp_a["id"], room["id"], "2026-07-07", 600, 660)
    # the prior booking reserves [600, 660+15)=[600,675); a 660..720 booking
    # starts at 660 which falls inside that buffered tail -> rejected
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="ROOM", room_id=room["id"], seat_id=None,
            booking_date="2026-07-07", start_minute=660, end_minute=720,
            expected_room_version=fx.room_version(room["id"])),
        make_employee_headers(emp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED)


def test_room_booking_clear_of_buffer_allowed(api):
    """PRD §3.4: "For a ROOM, the geometry is widened by the room's
    turnover_buffer_minute: the requested window with the turnover buffer appended
    after it must not intersect any existing non-terminal reservation on that
    room, and a conflict is rejected with ERR_ROOM_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_buffered_overlap_turnover_buffer_after_booking
    """
    floor, room, emp_a, emp_b = fx.setup_room_floor(
        level=161, turnover_buffer_minute=15, clock_date="2026-07-07", clock_minute=500)
    fx.create_room_reservation(emp_a["id"], room["id"], "2026-07-07", 600, 660)
    # a 675..720 booking starts exactly where the buffered tail [600,675) ends
    # -> half-open, no intersection -> allowed
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="ROOM", room_id=room["id"], seat_id=None,
            booking_date="2026-07-07", start_minute=675, end_minute=720,
            expected_room_version=fx.room_version(room["id"])),
        make_employee_headers(emp_b["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty A: boundary_precision_check (capacity count boundary)
# ---------------------------------------------------------------------------
def test_neighborhood_capacity_boundary_distinct_plus_one_equals_cap_allowed(api):
    """PRD §3.9: "Otherwise the booking is allowed only when the count of distinct
    reserved seats plus one is at most effective_cap_seats; the boundary case
    where that sum exactly equals effective_cap_seats is allowed."

    Design: Difficulty/boundary_precision_check/neighborhood_capacity_boundary_distinct_plus_one_equals_cap_allowed
    """
    # 3 seats, cap_pct 60 -> effective_cap_seats = ceil(1.8) = 2
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        3, cap_pct=60, level=11, max_active=5, clock_date="2026-07-01", clock_minute=500)
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    fx.create_seat_reservation(emp_a["id"], seats[0]["id"], "2026-07-01", 540, 600)  # distinct=1
    # booking a 2nd distinct seat: 1 + 1 == 2 == cap -> allowed
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="SEAT", seat_id=seats[1]["id"],
            booking_date="2026-07-01", start_minute=540, end_minute=600,
            expected_seat_version=seats[1]["version"]),
        make_employee_headers(emp_b["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


def test_neighborhood_capacity_over_cap_rejected(api):
    """PRD §3.9: "A booking that would push the distinct count past the cap is
    rejected with ERR_NEIGHBORHOOD_CAPACITY_FULL."

    Design: Difficulty/boundary_precision_check/neighborhood_capacity_boundary_distinct_plus_one_equals_cap_allowed
    """
    # 3 seats, cap_pct 60 -> effective_cap_seats = 2; fill both, then attempt a 3rd
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        3, cap_pct=60, level=111, max_active=5, clock_date="2026-07-01", clock_minute=500)
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    emp_c = fx.create_employee(team_code="ENG")
    fx.create_seat_reservation(emp_a["id"], seats[0]["id"], "2026-07-01", 540, 600)
    fx.create_seat_reservation(emp_b["id"], seats[1]["id"], "2026-07-01", 540, 600)  # distinct=2==cap
    # a third distinct seat would make 2 + 1 = 3 > 2 -> rejected
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_c["id"], resource_type="SEAT", seat_id=seats[2]["id"],
            booking_date="2026-07-01", start_minute=540, end_minute=600,
            expected_seat_version=seats[2]["version"]),
        make_employee_headers(emp_c["id"]))
    validate_error(resp, ApiErrorId.ERR_NEIGHBORHOOD_CAPACITY_FULL)


# ---------------------------------------------------------------------------
# Difficulty A: cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_checkin_blocked_when_seat_out_of_service(api):
    """PRD §3.7: "Check-in is permitted only when the reservation is BOOKED, when
    the acting employee owns it, when the logical clock's current minute-of-day is
    at or before the reservation's checkin_deadline_minute (the grace window has
    not expired), and when the booked seat or room is still AVAILABLE (it has not
    been pulled OUT_OF_SERVICE). ... a check-in against a no-longer-available
    resource with ERR_RESOURCE_NOT_BOOKABLE."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_seat_available_reservation_to_seat
    """
    env = fx.setup_floor_plan(level=13, clock_date="2026-07-03", clock_minute=545)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-07-03", 540, 1080)
    get_success_data(api.seat_out_of_service(env["seat"]["id"], FM))
    resp = api.checkin_reservation(resv["id"], make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_BOOKABLE)


def test_checkin_allowed_when_seat_still_available(api):
    """PRD §3.7: "Check-in is permitted only when the reservation is BOOKED, when
    the acting employee owns it, when the logical clock's current minute-of-day is
    at or before the reservation's checkin_deadline_minute (the grace window has
    not expired), and when the booked seat or room is still AVAILABLE (it has not
    been pulled OUT_OF_SERVICE). ... A successful check-in advances occupancy_status
    from BOOKED to CHECKED_IN".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_seat_available_reservation_to_seat
    """
    # positive control of the Reservation -> Seat dependency: with the seat left
    # AVAILABLE, the same BOOKED->CHECKED_IN transition succeeds
    env = fx.setup_floor_plan(level=131, clock_date="2026-07-03", clock_minute=545)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-07-03", 540, 1080)
    checked = get_success_data(api.checkin_reservation(resv["id"], make_employee_headers(emp_id)))
    assert checked["occupancy_status"] == "CHECKED_IN"


def test_create_blocked_when_employee_suspended(api):
    """PRD §3.4: "The acting employee's booking_privilege must be ACTIVE; a
    SUSPENDED employee attempting to book is rejected with ERR_BOOKING_SUSPENDED
    (HTTP 409)."
    PRD §3.8: "if the recomputed score reaches the suspend threshold of 30, the
    employee's privilege flips to SUSPENDED and that employee's subsequent
    reservation creates are rejected with ERR_BOOKING_SUSPENDED."

    Design: Difficulty/cross_entity_state_dependency/create_requires_employee_active_reservation_to_employee
    """
    env = fx.setup_suspended_employee(booking_date="2026-07-04", level=14)
    emp_id = env["employee"]["id"]
    # employee is now SUSPENDED (score 30); a fresh booking on a clean later date
    fx.set_clock("2026-07-05", 545)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=env["seat2"]["id"],
            booking_date="2026-07-05", start_minute=540, end_minute=600,
            expected_seat_version=fx.seat_version(env["seat2"]["id"])),
        make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_BOOKING_SUSPENDED)
    emp = get_success_data(api.get_employee(emp_id, FM))
    assert emp["booking_privilege"] == "SUSPENDED"


def test_create_allowed_when_employee_active(api):
    """PRD §3.4: "The acting employee's booking_privilege must be ACTIVE; a
    SUSPENDED employee attempting to book is rejected with ERR_BOOKING_SUSPENDED
    (HTTP 409)."
    PRD §3.6: "An employee record begins in status ACTIVE (which may later be
    ARCHIVED), with strike_score at 0 and booking_privilege ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/create_requires_employee_active_reservation_to_employee
    """
    # positive control of the Reservation -> Employee dependency: a brand-new
    # employee (booking_privilege ACTIVE, strike_score 0) creates successfully
    env = fx.setup_floor_plan(level=141, clock_date="2026-07-04", clock_minute=500)
    emp_id = env["employee"]["id"]
    assert env["employee"]["booking_privilege"] == "ACTIVE"
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=env["seat"]["id"],
            booking_date="2026-07-04", start_minute=540, end_minute=600,
            expected_seat_version=env["seat"]["version"]),
        make_employee_headers(emp_id))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty A: priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_suspended_beats_seat_overlap(api):
    """PRD §3.4: "The acting employee's booking_privilege must be ACTIVE; a
    SUSPENDED employee attempting to book is rejected with ERR_BOOKING_SUSPENDED
    (HTTP 409). ... Overlap is enforced per resource against the existing
    committed schedule on the same booking_date." (the suspension gate is narrated
    in the gate paragraph, ahead of the overlap paragraph)
    PRD §2.6: "When several checks could fail on one request, they are evaluated
    in a fixed precedence so the returned error_id is deterministic."

    Design: Difficulty/priority_pair_validation_conflict/suspended_beats_seat_overlap_constraint_vs_temporal
    """
    # active employee Y holds a live BOOKED window 540..600; suspended employee X
    # then attempts the same window on the same seat -> both gates would fail
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        1, cap_pct=100, level=9, max_active=5, clock_date="2026-06-29", clock_minute=500)
    seat = seats[0]
    emp_y = fx.create_employee(team_code="ENG")
    emp_x = fx.create_employee(team_code="ENG")
    fx.create_seat_reservation(emp_y["id"], seat["id"], "2026-06-29", 540, 600)
    # suspend emp_x via 3 NO_SHOW releases on the same seat (non-overlapping
    # windows). All windows stay inside the default workday [540, 1080] and clear
    # of emp_y's live 540..600 booking, so the only gate exercised here is no-show.
    start = 700
    for _ in range(3):
        end = start + 40
        fx.set_clock("2026-06-29", start - 40)
        r = fx.create_seat_reservation(emp_x["id"], seat["id"], "2026-06-29", start, end)
        fx.set_clock("2026-06-29", end + 100)
        fx.release_reservation_as_no_show(r["id"])
        start = end + 20
    emp_x_data = get_success_data(api.get_employee(emp_x["id"], FM))
    assert emp_x_data["booking_privilege"] == "SUSPENDED"
    fx.set_clock("2026-06-29", 500)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_x["id"], resource_type="SEAT", seat_id=seat["id"],
            booking_date="2026-06-29", start_minute=540, end_minute=600,
            expected_seat_version=fx.seat_version(seat["id"])),
        make_employee_headers(emp_x["id"]))
    validate_error(resp, ApiErrorId.ERR_BOOKING_SUSPENDED)


def test_booking_suspended_in_isolation(api):
    """PRD §3.4: "The acting employee's booking_privilege must be ACTIVE; a
    SUSPENDED employee attempting to book is rejected with ERR_BOOKING_SUSPENDED
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_beats_seat_overlap_constraint_vs_temporal
    """
    # suspension is the only failing gate: target seat is free
    env = fx.setup_suspended_employee(booking_date="2026-06-29", level=91)
    emp_id = env["employee"]["id"]
    fx.set_clock("2026-06-30", 500)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=env["seat2"]["id"],
            booking_date="2026-06-30", start_minute=540, end_minute=600,
            expected_seat_version=fx.seat_version(env["seat2"]["id"])),
        make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_BOOKING_SUSPENDED)


def test_team_zoning_beats_capacity(api):
    """PRD §3.4: "For a SEAT reservation, if the floor's policy enforces team
    zoning and the seat's neighborhood declares a non-null team_code, the acting
    employee's team_code must equal that value, or the booking is rejected with
    ERR_TEAM_ZONING_VIOLATION (HTTP 409)." (the zoning gate is in the gate
    paragraph; the capacity gate is described later as one the seat booking
    "additionally faces")
    PRD §2.6: "When several checks could fail on one request, they are evaluated
    in a fixed precedence so the returned error_id is deterministic."

    Design: Difficulty/priority_pair_validation_conflict/team_zoning_beats_capacity_safety_vs_fiscal
    """
    # zone team_code=ENG, cap_pct=50 over 2 seats -> effective_cap_seats=1.
    # An ENG employee fills the zone to capacity, then a SALES employee attempts
    # the other seat -> both zoning (SALES != ENG) and capacity (1+1>1) would fail.
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        2, cap_pct=50, level=10, team_code="ENG", enforce_team_zoning=True,
        max_active=5, clock_date="2026-06-30", clock_minute=500)
    eng = fx.create_employee(team_code="ENG")
    sales = fx.create_employee(team_code="SALES")
    fx.create_seat_reservation(eng["id"], seats[0]["id"], "2026-06-30", 540, 600)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=sales["id"], resource_type="SEAT", seat_id=seats[1]["id"],
            booking_date="2026-06-30", start_minute=540, end_minute=600,
            expected_seat_version=seats[1]["version"]),
        make_employee_headers(sales["id"]))
    validate_error(resp, ApiErrorId.ERR_TEAM_ZONING_VIOLATION)


def test_team_zoning_violation_in_isolation(api):
    """PRD §3.4: "For a SEAT reservation, if the floor's policy enforces team
    zoning and the seat's neighborhood declares a non-null team_code, the acting
    employee's team_code must equal that value, or the booking is rejected with
    ERR_TEAM_ZONING_VIOLATION (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/team_zoning_beats_capacity_safety_vs_fiscal
    """
    # zoning is the only failing gate: cap is generous (100%), seat is free
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        2, cap_pct=100, level=101, team_code="ENG", enforce_team_zoning=True,
        max_active=5, clock_date="2026-06-30", clock_minute=500)
    sales = fx.create_employee(team_code="SALES")
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=sales["id"], resource_type="SEAT", seat_id=seats[0]["id"],
            booking_date="2026-06-30", start_minute=540, end_minute=600,
            expected_seat_version=seats[0]["version"]),
        make_employee_headers(sales["id"]))
    validate_error(resp, ApiErrorId.ERR_TEAM_ZONING_VIOLATION)


# ---------------------------------------------------------------------------
# Difficulty A: compensating_invariant (neighborhood occupancy count)
# ---------------------------------------------------------------------------
def test_book_then_cancel_conserves_neighborhood_occupancy(api):
    """PRD §3.7: "Cancellation advances occupancy_status to CANCELLED, frees the
    held seat or room window (decrementing neighborhood occupancy for the date)".
    PRD §3.9: "the system counts the distinct seats already reserved in that
    neighborhood on the requested booking_date — distinct seat_id values across
    reservations whose occupancy_status is BOOKED or CHECKED_IN."

    Design: Difficulty/compensating_invariant/book_then_cancel_conserves_neighborhood_occupancy_count
    """
    # cap_pct 60 over 3 seats -> effective_cap_seats=2. Book A and B (distinct=2,
    # at cap); cancel B (distinct back to 1); a third distinct seat C then fits.
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        3, cap_pct=60, level=17, max_active=5, clock_date="2026-07-08", clock_minute=500)
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    emp_c = fx.create_employee(team_code="ENG")
    fx.create_seat_reservation(emp_a["id"], seats[0]["id"], "2026-07-08", 540, 600)
    r_b = fx.create_seat_reservation(emp_b["id"], seats[1]["id"], "2026-07-08", 540, 600)
    cancelled = get_success_data(api.cancel_reservation(r_b["id"], make_employee_headers(emp_b["id"])))
    assert cancelled["occupancy_status"] == "CANCELLED"
    # distinct is back to 1, so booking a third distinct seat (1+1=2==cap) succeeds
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_c["id"], resource_type="SEAT", seat_id=seats[2]["id"],
            booking_date="2026-07-08", start_minute=540, end_minute=600,
            expected_seat_version=seats[2]["version"]),
        make_employee_headers(emp_c["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


def test_cancel_frees_same_seat_window_for_rebooking(api):
    """PRD §3.7: "Cancellation advances occupancy_status to CANCELLED, frees the
    held seat or room window (decrementing neighborhood occupancy for the date)".
    PRD §3.9: "If the seat being booked is already among those distinct reserved
    seats, no additional capacity is consumed (the same seat does not count
    twice)."

    Design: Difficulty/compensating_invariant/book_then_cancel_conserves_neighborhood_occupancy_count
    """
    # cap_pct 60 over 3 seats -> effective_cap_seats=2. Fill both A and B (at cap).
    # Cancel A, restoring the conserved distinct count; the SAME seat A can then be
    # re-booked because the cancel freed its window and occupancy slot.
    floor, nb, seats = fx.setup_neighborhood_with_seats(
        3, cap_pct=60, level=171, max_active=5, clock_date="2026-07-08", clock_minute=500)
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    emp_a2 = fx.create_employee(team_code="ENG")
    r_a = fx.create_seat_reservation(emp_a["id"], seats[0]["id"], "2026-07-08", 540, 600)
    fx.create_seat_reservation(emp_b["id"], seats[1]["id"], "2026-07-08", 540, 600)  # distinct=2==cap
    get_success_data(api.cancel_reservation(r_a["id"], make_employee_headers(emp_a["id"])))
    # seat A's window and occupancy slot are freed; re-booking the same seat succeeds
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_a2["id"], resource_type="SEAT", seat_id=seats[0]["id"],
            booking_date="2026-07-08", start_minute=540, end_minute=600,
            expected_seat_version=fx.seat_version(seats[0]["id"])),
        make_employee_headers(emp_a2["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"
