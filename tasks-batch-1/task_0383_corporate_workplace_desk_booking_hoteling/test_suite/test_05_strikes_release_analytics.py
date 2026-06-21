"""No-show release / void cascades, strike scoring and reinstatement, the
no-show sweep, and planned-vs-realized / empty-floor utilization analytics.

Translates queue-A difficulty rules `transitive_cascade`, `dual_variant_calc`
(utilization variant), `boundary_precision_check` (empty-floor variant), and
queue-B Corner `state_machines` / `calculations` instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_employee_headers,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


# ---------------------------------------------------------------------------
# Difficulty A: transitive_cascade — no-show release depth-3 -> suspend
# ---------------------------------------------------------------------------
def test_noshow_release_cascade_strike_to_suspend(api):
    """PRD §3.8: "Releasing a no-show advances occupancy_status from BOOKED to
    NO_SHOW_RELEASED and triggers a depth-three cascade. ... a NO_SHOW
    NoShowEvent of delta positive 10 is appended for the employee, the employee's
    strike_score is recomputed, and booking_privilege is re-derived; if the
    recomputed score reaches the suspend threshold of 30, the employee's privilege
    flips to SUSPENDED".

    Design: Difficulty/transitive_cascade/noshow_release_cascade_depth3_strike_to_suspend
    """
    env = fx.setup_floor_plan(level=7, grace_minutes=30, clock_date="2026-06-27", clock_minute=500)
    emp_id = env["employee"]["id"]
    seat_id = env["seat"]["id"]
    # accrue 2 prior strikes (score 20)
    fx.accrue_strikes(env, 2, booking_date="2026-06-26")
    # third grace-expired BOOKED reservation, then release it -> score 30 -> SUSPENDED
    fx.set_clock("2026-06-27", 545)
    r3 = fx.create_seat_reservation(emp_id, seat_id, "2026-06-27", 540, 600)
    fx.set_clock("2026-06-27", 700)
    released = get_success_data(api.release_reservation(r3["id"], FM))
    assert released["occupancy_status"] == "NO_SHOW_RELEASED"
    emp = get_success_data(api.get_employee(emp_id, FM))
    assert emp["strike_score"] == 30
    assert emp["booking_privilege"] == "SUSPENDED"


def test_single_noshow_release_adds_ten_strike(api):
    """PRD §3.8: "a NO_SHOW NoShowEvent of delta positive 10 is appended for the
    employee, the employee's strike_score is recomputed".
    PRD §3.6: "A NO_SHOW event carries a delta of positive 10 (the strike weight)".

    Design: Difficulty/transitive_cascade/noshow_release_cascade_depth3_strike_to_suspend
    """
    env = fx.setup_floor_plan(level=71, grace_minutes=30, clock_date="2026-06-27", clock_minute=545)
    emp_id = env["employee"]["id"]
    r = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-06-27", 540, 600)
    fx.set_clock("2026-06-27", 700)
    released = get_success_data(api.release_reservation(r["id"], FM))
    assert released["occupancy_status"] == "NO_SHOW_RELEASED"
    emp = get_success_data(api.get_employee(emp_id, FM))
    assert emp["strike_score"] == 10
    assert emp["booking_privilege"] == "ACTIVE"  # 10 < 30


# ---------------------------------------------------------------------------
# Difficulty A: transitive_cascade — cancel depth-2 -> billing void
# ---------------------------------------------------------------------------
def test_cancel_cascade_voids_billing_and_cancels_amenities(api):
    """PRD §3.8: "The same void cascade fires on a voluntary cancellation (Section
    3.7): the reservation's REQUESTED and APPROVED amenity lines are moved to
    CANCELLED, billing_status becomes VOID, and provisional_chargeback_cents
    resets to 0 — the only difference from a no-show release is that cancellation
    appends no strike event."

    Design: Difficulty/transitive_cascade/reservation_cancel_cascade_depth2_amenity_to_billing_void
    """
    # BOOKED reservation with one APPROVED amenity line -> billing PROVISIONAL
    env = fx.setup_floor_plan(level=8, clock_date="2026-06-28", clock_minute=500)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-06-28", 540, 1080)
    line = fx.add_amenity_line(resv["id"], emp_id, "MONITOR", 1000, 1)
    fx.approve_amenity_line(line["id"])
    cancelled = get_success_data(api.cancel_reservation(resv["id"], make_employee_headers(emp_id)))
    assert cancelled["occupancy_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "VOID"
    assert cancelled["provisional_chargeback_cents"] == 0
    line_after = get_success_data(api.get_amenity(line["id"], FM))
    assert line_after["line_status"] == "CANCELLED"


def test_cancel_appends_no_strike(api):
    """PRD §3.7: "A voluntary cancellation carries no strike — this is the
    deliberate difference from a no-show release."

    Design: Difficulty/transitive_cascade/reservation_cancel_cascade_depth2_amenity_to_billing_void
    """
    env = fx.setup_floor_plan(level=81, clock_date="2026-06-28", clock_minute=500)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-06-28", 540, 1080)
    line = fx.add_amenity_line(resv["id"], emp_id, "MONITOR", 1000, 1)
    fx.approve_amenity_line(line["id"])
    get_success_data(api.cancel_reservation(resv["id"], make_employee_headers(emp_id)))
    emp = get_success_data(api.get_employee(emp_id, FM))
    assert emp["strike_score"] == 0  # cancel adds no NO_SHOW strike
    assert emp["booking_privilege"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: state_machines — no-show sweep
# ---------------------------------------------------------------------------
def test_noshow_sweep_releases_grace_expired_booked(api):
    """PRD §3.8: "The sweep, driven by a FacilityManager, scans for every BOOKED
    reservation whose grace has expired at the current clock — optionally narrowed
    to a single booking_date — releases each one, and reports how many it released
    and their ids."

    Design: Corner/state_machines/noshow_sweep_releases_grace_expired_booked
    """
    env = fx.setup_floor_plan(level=11, grace_minutes=30, clock_date="2026-08-08", clock_minute=545)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-08-08", 540, 600)
    fx.set_clock("2026-08-08", 600)  # past deadline 540+30=570
    swept = get_success_data(api.advance_no_show_sweep(FM, booking_date="2026-08-08"))
    assert swept["released_count"] == 1
    after = get_success_data(api.get_reservation(resv["id"], FM))
    assert after["occupancy_status"] == "NO_SHOW_RELEASED"


# ---------------------------------------------------------------------------
# Corner: calculations — strike floor and reinstate
# ---------------------------------------------------------------------------
def test_strike_score_floors_at_zero_after_good_checkin(api):
    """PRD §3.6: "The score is recomputed by summing the deltas of all of the
    employee's ledger rows created strictly after the employee's most recent
    reinstatement (or all rows if the employee has never been reinstated), then
    flooring the result at 0 — accumulated good behavior can pull the score down
    but never below zero."
    PRD §3.6: "A NO_SHOW event carries a delta of positive 10 (the strike weight);
    a GOOD_CHECKIN event carries a delta of negative 3 (the good-behavior credit)."

    Design: Corner/calculations/strike_score_floors_at_zero_with_good_checkins
    """
    env = fx.setup_floor_plan(level=13, grace_minutes=30, clock_date="2026-08-10", clock_minute=545)
    emp_id = env["employee"]["id"]
    seat_id = env["seat"]["id"]
    # one NO_SHOW release -> score 10
    r1 = fx.create_seat_reservation(emp_id, seat_id, "2026-08-10", 540, 600)
    fx.set_clock("2026-08-10", 700)
    fx.release_reservation_as_no_show(r1["id"])
    # a within-grace check-in on a later reservation -> GOOD_CHECKIN -3 -> score 7
    fx.set_clock("2026-08-11", 545)
    r2 = fx.create_seat_reservation(emp_id, seat_id, "2026-08-11", 540, 600)
    get_success_data(api.checkin_reservation(r2["id"], make_employee_headers(emp_id)))
    emp = get_success_data(api.get_employee(emp_id, FM))
    assert emp["strike_score"] == 7
    assert emp["booking_privilege"] == "ACTIVE"


def test_reinstate_resets_strike_score_and_privilege(api):
    """PRD §3.6: "Reinstatement sets a new reinstatement baseline so that all
    prior ledger rows are excluded from future sums, recomputes strike_score to 0,
    and returns booking_privilege to ACTIVE."

    Design: Corner/calculations/reinstate_resets_strike_score_and_privilege
    """
    env = fx.setup_floor_plan(level=14, grace_minutes=30, clock_date="2026-08-12", clock_minute=500)
    emp_id = env["employee"]["id"]
    fx.accrue_strikes(env, 3, booking_date="2026-08-12")  # score 30 -> SUSPENDED
    suspended = get_success_data(api.get_employee(emp_id, FM))
    assert suspended["booking_privilege"] == "SUSPENDED"
    reinstated = get_success_data(api.reinstate_employee(emp_id, FM))
    assert reinstated["strike_score"] == 0
    assert reinstated["booking_privilege"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty A: dual_variant_calc — planned vs realized utilization
# ---------------------------------------------------------------------------
def test_utilization_planned_counts_booked(api):
    """PRD §3.11: "The planned variant (the default, also selected by mode
    PLANNED) counts occupancy for reservations whose occupancy_status is BOOKED,
    CHECKED_IN, or COMPLETED, capturing forward-looking demand."
    PRD §3.11: "the seat's percentage is the booked minutes divided by
    capacity_minutes, multiplied by 100, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/utilization_planned_vs_realized_diverge
    """
    # floor capacity 540; one CHECKED_IN 540..720 (180) + one BOOKED 720..900 (180)
    env = fx.setup_floor_plan(level=2, grace_minutes=30, clock_date="2026-06-21", clock_minute=545)
    emp_id = env["employee"]["id"]
    seat_id = env["seat"]["id"]
    ra = fx.create_seat_reservation(emp_id, seat_id, "2026-06-21", 540, 720)
    get_success_data(api.checkin_reservation(ra["id"], make_employee_headers(emp_id)))
    fx.create_seat_reservation(emp_id, seat_id, "2026-06-21", 720, 900)  # left BOOKED
    resp = api.get_floor_utilization(env["floor"]["id"], ANALYST,
                                     params={"date": "2026-06-21", "mode": "PLANNED"})
    data = validate_success(resp, expected_status=200)
    # (180 + 180) / 540 * 100 = 66.666... -> 66.67
    assert data["floor_utilization_pct"] == 66.67


def test_utilization_realized_excludes_booked_no_show(api):
    """PRD §3.11: "The realized variant (selected by mode REALIZED) counts only
    CHECKED_IN and COMPLETED reservations, excluding bookings that were never
    checked in, and so generally reports a lower number."

    Design: Difficulty/dual_variant_calc/utilization_planned_vs_realized_diverge
    """
    env = fx.setup_floor_plan(level=21, grace_minutes=30, clock_date="2026-06-21", clock_minute=545)
    emp_id = env["employee"]["id"]
    seat_id = env["seat"]["id"]
    ra = fx.create_seat_reservation(emp_id, seat_id, "2026-06-21", 540, 720)
    get_success_data(api.checkin_reservation(ra["id"], make_employee_headers(emp_id)))
    fx.create_seat_reservation(emp_id, seat_id, "2026-06-21", 720, 900)  # left BOOKED
    resp = api.get_floor_utilization(env["floor"]["id"], ANALYST,
                                     params={"date": "2026-06-21", "mode": "REALIZED"})
    data = validate_success(resp, expected_status=200)
    # only the CHECKED_IN 180 counts: 180 / 540 * 100 = 33.333... -> 33.33
    assert data["floor_utilization_pct"] == 33.33


# ---------------------------------------------------------------------------
# Difficulty A: boundary_precision_check — empty floor
# ---------------------------------------------------------------------------
def test_utilization_empty_floor_returns_zero_planned(api):
    """PRD §3.11: "A floor with zero non-retired seats reports a floor utilization
    of 0.00 with no division performed."

    Design: Difficulty/boundary_precision_check/utilization_empty_floor_zero_seats_returns_zero
    """
    site = fx.create_site(name="HQ12")
    floor = fx.create_floor(site["id"], level=12)
    fx.create_neighborhood(floor["id"], name="EmptyZone")  # no seats
    resp = api.get_floor_utilization(floor["id"], ANALYST,
                                     params={"date": "2026-07-02", "mode": "PLANNED"})
    data = validate_success(resp, expected_status=200)
    assert data["floor_utilization_pct"] == 0.00


def test_utilization_empty_floor_returns_zero_realized(api):
    """PRD §3.11: "A floor with zero non-retired seats reports a floor utilization
    of 0.00 with no division performed."

    Design: Difficulty/boundary_precision_check/utilization_empty_floor_zero_seats_returns_zero
    """
    site = fx.create_site(name="HQ12b")
    floor = fx.create_floor(site["id"], level=121)
    fx.create_neighborhood(floor["id"], name="EmptyZone2")  # no seats
    resp = api.get_floor_utilization(floor["id"], ANALYST,
                                     params={"date": "2026-07-02", "mode": "REALIZED"})
    data = validate_success(resp, expected_status=200)
    assert data["floor_utilization_pct"] == 0.00
