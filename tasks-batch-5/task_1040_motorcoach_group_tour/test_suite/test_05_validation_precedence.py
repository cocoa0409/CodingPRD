"""Validation precedence pairs whose ordering the PRD states explicitly."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_tour_product, create_departure, create_driver, create_coach,
    get_departure, current_version,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ---------------------------------------------------------------------------
# Cross-entity dependency: an otherwise-valid confirm still needs the departure OPEN
# ---------------------------------------------------------------------------

def _valid_confirm_on_planning_setup(api):
    """PLANNING departure (coach assigned); booking pax 2 with 2 passengers and deposit
    paid — every confirm precondition satisfied EXCEPT the departure being OPEN."""
    tp = create_tour_product(base_price_per_person_cents=100000, deposit_per_person_cents=20000)
    coach = create_coach(code="C9", seat_capacity=10)
    dep = create_departure(tp["id"], guaranteed_min_pax=5, start_date="2026-11-01",
                           end_date="2026-11-02")  # never published -> PLANNING
    fx.assign_resource(dep["id"], "COACH", coach["id"])
    bk = fx.create_booking(dep["id"], pax_count=2, rooms_requested=0)
    fx.add_passenger(bk["id"], full_name="L1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="L2")
    fx.pay(bk["id"], "DEPOSIT", bk["deposit_due_cents"])
    return dep, bk


def test_valid_confirm_rejected_while_departure_planning(api, sales_headers):
    """PRD §3.7: "The departure must be OPEN or GUARANTEED; if it is in any other status
    the confirm is rejected with ERR_DEPARTURE_NOT_OPEN."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_depends_on_departure_open
    """
    _, bk = _valid_confirm_on_planning_setup(api)
    resp = api.confirm_booking(bk["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_OPEN.value)


def test_confirm_rejected_while_planning_leaves_booking_draft(api, sales_headers):
    """PRD §3.7: "The departure must be OPEN or GUARANTEED; if it is in any other status
    the confirm is rejected with ERR_DEPARTURE_NOT_OPEN."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_depends_on_departure_open
    """
    _, bk = _valid_confirm_on_planning_setup(api)
    api.confirm_booking(bk["id"], sales_headers)
    data = validate_success(api.get_booking(bk["id"], sales_headers))
    assert data["reservation_status"] == "DRAFT", \
        f"rejected confirm must leave booking DRAFT, got {data['reservation_status']}"


# ---------------------------------------------------------------------------
# Confirm: state check (ERR_DEPARTURE_NOT_OPEN) precedes fiscal (ERR_DEPOSIT_UNPAID)
# ---------------------------------------------------------------------------

def test_confirm_on_planning_departure_reports_not_open_over_deposit(api, sales_headers):
    """PRD §3.7: "The departure must be OPEN or GUARANTEED; if it is in any other status
    the confirm is rejected with ERR_DEPARTURE_NOT_OPEN."
    PRD §3.7: "Finally, the deposit must be paid — the booking's payment_status must be
    DEPOSIT_PAID or PAID_IN_FULL, otherwise the confirm is rejected with ERR_DEPOSIT_UNPAID."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal_departure_not_open_vs_deposit_unpaid
    """
    tp = create_tour_product(base_price_per_person_cents=100000, deposit_per_person_cents=20000)
    dep = create_departure(tp["id"], guaranteed_min_pax=5, start_date="2026-10-01",
                           end_date="2026-10-02")  # left in PLANNING (never published)
    bk = fx.create_booking(dep["id"], pax_count=2, rooms_requested=0)
    fx.add_passenger(bk["id"], full_name="J1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="J2")
    # No deposit paid: both the state guard and the fiscal guard would fail.
    resp = api.confirm_booking(bk["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_OPEN.value)


def test_confirm_on_planning_departure_leaves_booking_draft(api, sales_headers):
    """PRD §3.7: "The departure must be OPEN or GUARANTEED; if it is in any other status
    the confirm is rejected with ERR_DEPARTURE_NOT_OPEN."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal_departure_not_open_vs_deposit_unpaid
    """
    tp = create_tour_product(base_price_per_person_cents=100000, deposit_per_person_cents=20000)
    dep = create_departure(tp["id"], guaranteed_min_pax=5, start_date="2026-10-01",
                           end_date="2026-10-02")
    bk = fx.create_booking(dep["id"], pax_count=2, rooms_requested=0)
    fx.add_passenger(bk["id"], full_name="J1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="J2")
    api.confirm_booking(bk["id"], sales_headers)
    data = validate_success(api.get_booking(bk["id"], sales_headers))
    assert data["reservation_status"] == "DRAFT", \
        f"rejected confirm must leave booking DRAFT, got {data['reservation_status']}"


# ---------------------------------------------------------------------------
# Assign driver: safety (ERR_DOT_HOURS_EXCEEDED) precedes temporal (ERR_DRIVER_OVERLAP)
# ---------------------------------------------------------------------------

def _dot_beats_overlap_setup(api):
    """Driver assigned to Dep1 [10-05,10-07]; Dep2 [10-06,10-08] both overlaps AND has an
    11h itinerary day. Returns (dep2_id, driver_id)."""
    tp = create_tour_product(duration_days=3, base_price_per_person_cents=100000,
                             deposit_per_person_cents=20000)
    driver = create_driver(name="Dana", license_no="CDL9")
    dep1 = create_departure(tp["id"], name="Dep1", start_date="2026-10-05", end_date="2026-10-07",
                            guaranteed_min_pax=5, itinerary_days=f.itinerary(8, service_date="2026-10-05"))
    fx.assign_resource(dep1["id"], "DRIVER", driver["id"])
    dep2 = create_departure(tp["id"], name="Dep2", start_date="2026-10-06", end_date="2026-10-08",
                            guaranteed_min_pax=5, itinerary_days=f.itinerary(11, service_date="2026-10-06"))
    return dep2["id"], driver["id"]


def test_assign_driver_reports_dot_over_overlap(api, ops_headers):
    """PRD §2.10: "For a driver, the system first enforces federal hours-of-service limits:
    no single itinerary day may schedule more than ten planned driving hours. If any
    itinerary day's planned_drive_hours exceeds ten, the assignment is rejected with
    ERR_DOT_HOURS_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/assign_driver_safety_beats_temporal_dot_vs_driver_overlap
    """
    dep2_id, driver_id = _dot_beats_overlap_setup(api)
    version = current_version(dep2_id)
    resp = api.assign_departure(dep2_id, {
        "resource_kind": "DRIVER", "driver_id": driver_id,
        "expected_departure_version": version,
    }, ops_headers)
    validate_error(resp, ApiErrorId.ERR_DOT_HOURS_EXCEEDED.value)


def test_assign_driver_dot_failure_leaves_dep_unassigned(api, ops_headers):
    """PRD §2.10: "If any itinerary day's planned_drive_hours exceeds ten, the assignment
    is rejected with ERR_DOT_HOURS_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/assign_driver_safety_beats_temporal_dot_vs_driver_overlap
    """
    dep2_id, driver_id = _dot_beats_overlap_setup(api)
    version = current_version(dep2_id)
    api.assign_departure(dep2_id, {
        "resource_kind": "DRIVER", "driver_id": driver_id,
        "expected_departure_version": version,
    }, ops_headers)
    dep2 = get_departure(dep2_id)
    assert dep2["driver_id"] is None, \
        f"rejected assign must leave driver_id null, got {dep2['driver_id']}"
