"""Trip creation gates: load state, tractor availability, safety floor
boundary, HOS feasibility clauses, and the home-time ceiling (PRD §3.3, §3.4,
§2.9)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_driver,
    create_tractor,
    get_driver,
    get_load,
    make_dispatcher_headers,
    make_load_planner_headers,
    plan_trip,
    record_safety_event,
    setup_accepted_load,
    setup_planned_trip,
    setup_refdata,
    tender_load,
    validate_error,
    validate_success,
)

DISPATCHER = make_dispatcher_headers()
LOAD_PLANNER = make_load_planner_headers()


def _accept_second_load(ctx, **overrides):
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"], **overrides)
    validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    return validate_success(api_client.accept_load(load["id"], LOAD_PLANNER))


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / trip_create_gated_by_load_state
# ---------------------------------------------------------------------------

def test_trip_create_rejected_for_screened_load(api):
    """PRD §3.3: "Creation is gated, and the gates run in the pipeline order of
    §2.9: the load must be `ACCEPTED` (any other status draws
    `ERR_LOAD_NOT_ASSIGNABLE`), the tractor must be `AVAILABLE` (otherwise
    `ERR_TRACTOR_NOT_AVAILABLE`)".

    Design: Difficulty/cross_entity_state_dependency/trip_create_gated_by_load_state
    """
    ctx = setup_refdata()
    driver = create_driver(cdl_number="CDL-14")
    tractor = create_tractor(unit_number="T-16")
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    resp = api_client.create_trip(
        {"load_id": load["id"], "driver_id": driver["id"],
         "tractor_id": tractor["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-02T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_ASSIGNABLE)


def test_trip_create_succeeds_once_load_accepted(api):
    """PRD §3.3: "the load must be `ACCEPTED` (any other status draws
    `ERR_LOAD_NOT_ASSIGNABLE`)".
    PRD §3.3: "Creation ripples outward per §2.7: the load moves from
    `ACCEPTED` to `ASSIGNED` with its `version` incremented, the tractor moves
    from `AVAILABLE` to `ASSIGNED`, and the driver's provisional pay for the
    trip is computed immediately into `provisional_pay_cents`."

    Design: Difficulty/cross_entity_state_dependency/trip_create_gated_by_load_state
    """
    ctx = setup_accepted_load()
    driver = create_driver(cdl_number="CDL-14")
    tractor = create_tractor(unit_number="T-16")
    trip = validate_success(api_client.create_trip(
        {"load_id": ctx["load"]["id"], "driver_id": driver["id"],
         "tractor_id": tractor["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-02T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER), expected_status=201)
    assert trip["status"] == "PLANNED"
    assert get_load(ctx["load"]["id"])["status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / safety_floor_score_exactly_60
# ---------------------------------------------------------------------------

def test_safety_score_exactly_60_is_assignable(api):
    """PRD §3.3: "the driver's `safety_score` must be at least 60 (a score of
    exactly 60 passes; below it the create is rejected with
    `ERR_DRIVER_SAFETY_BELOW_FLOOR`)".

    Design: Difficulty/boundary_precision_check/safety_floor_score_exactly_60
    """
    ctx = setup_accepted_load()
    driver = create_driver(cdl_number="CDL-12A")
    record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                        severity_points=40, occurred_at="2026-07-01T00:00:00Z")
    assert get_driver(driver["id"])["safety_score"] == 60
    tractor = create_tractor(unit_number="T-13")
    trip = plan_trip(ctx["load"]["id"], driver["id"], tractor["id"])
    assert trip["status"] == "PLANNED"


def test_safety_score_59_rejected_below_floor(api):
    """PRD §3.3: "the driver's `safety_score` must be at least 60 (a score of
    exactly 60 passes; below it the create is rejected with
    `ERR_DRIVER_SAFETY_BELOW_FLOOR`)".
    PRD §3.8: "The score gates dispatch: at trip creation and replan, a driver
    whose score has fallen below 60 is rejected with
    `ERR_DRIVER_SAFETY_BELOW_FLOOR`, while a score of exactly 60 passes."

    Design: Difficulty/boundary_precision_check/safety_floor_score_exactly_60
    """
    ctx = setup_accepted_load()
    driver = create_driver(cdl_number="CDL-12B")
    record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                        severity_points=41, occurred_at="2026-07-01T00:00:00Z")
    assert get_driver(driver["id"])["safety_score"] == 59
    tractor = create_tractor(unit_number="T-14")
    resp = api_client.create_trip(
        {"load_id": ctx["load"]["id"], "driver_id": driver["id"],
         "tractor_id": tractor["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-02T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DRIVER_SAFETY_BELOW_FLOOR)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / state_beats_safety_on_trip_create
# ---------------------------------------------------------------------------

def test_state_error_beats_safety_floor_on_trip_create(api):
    """PRD §2.9: "Every request is evaluated against a fixed, ordered pipeline
    of checks, and a failure at any stage short-circuits the stages after it.
    The order matters because it determines which error a doubly-invalid
    request produces." (State admissibility is stage 6; the safety floor is
    stage 8.)

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_trip_create
    """
    ctx = setup_refdata()
    driver = create_driver(cdl_number="CDL-9")
    record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                        severity_points=60, occurred_at="2026-07-01T00:00:00Z")
    assert get_driver(driver["id"])["safety_score"] == 40
    tractor = create_tractor(unit_number="T-9")
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])  # TENDERED
    resp = api_client.create_trip(
        {"load_id": load["id"], "driver_id": driver["id"],
         "tractor_id": tractor["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-02T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_ASSIGNABLE)


def test_safety_floor_fires_in_isolation(api):
    """PRD §3.3: "the driver's `safety_score` must be at least 60 (a score of
    exactly 60 passes; below it the create is rejected with
    `ERR_DRIVER_SAFETY_BELOW_FLOOR`)" — with the load properly ACCEPTED, the
    safety gate is the only failing check and surfaces its own error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_trip_create
    """
    ctx = setup_accepted_load()
    driver = create_driver(cdl_number="CDL-9")
    record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                        severity_points=60, occurred_at="2026-07-01T00:00:00Z")
    tractor = create_tractor(unit_number="T-9")
    resp = api_client.create_trip(
        {"load_id": ctx["load"]["id"], "driver_id": driver["id"],
         "tractor_id": tractor["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-02T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DRIVER_SAFETY_BELOW_FLOOR)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / hos_feasibility_multi_clause_gate
# ---------------------------------------------------------------------------

def test_hos_horizon_clause_rejects_tight_delivery(api):
    """PRD §3.4: "660 minutes, multiplied by one plus the number of whole
    1440-minute days between the logical now and the load's `delivery_appt_at`
    (the quotient rounded down), must be at least the required drive time —
    each full day of runway adds another full driving shift of capacity."
    PRD §3.4: "If any clause fails, the create or replan is rejected with
    `ERR_HOS_INSUFFICIENT` (HTTP 422)."
    (1224 required minutes vs 660 * (1 + floor(1320/1440)) = 660 of horizon.)

    Design: Difficulty/combinatorial_formula/hos_feasibility_multi_clause_gate
    """
    ctx = setup_accepted_load(load_overrides={
        "pickup_appt_at": "2026-08-01T08:00:00Z",
        "delivery_appt_at": "2026-08-02T04:00:00Z"})
    driver = create_driver(cdl_number="CDL-3")
    tractor = create_tractor(unit_number="T-3")
    resp = api_client.create_trip(
        {"load_id": ctx["load"]["id"], "driver_id": driver["id"],
         "tractor_id": tractor["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-01T07:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_HOS_INSUFFICIENT)


def test_hos_roomy_delivery_accepted_at_clause1_equality(api):
    """PRD §3.4: "The driver's `drive_11h_remaining_minutes` must be at least
    the smaller of the required drive time and 660 minutes."
    PRD §3.3: "For a `MILEAGE` driver, the provisional figure is the planned
    total miles — the lane's `loaded_miles` plus the trip's
    `planned_deadhead_miles` — multiplied by the driver's
    `pay_rate_cents_per_mile`."
    (Fresh driver: 660 >= min(1224, 660) holds at equality; provisional pay
    1020 * 62 = 63240.)

    Design: Difficulty/combinatorial_formula/hos_feasibility_multi_clause_gate
    """
    ctx = setup_accepted_load()
    driver = create_driver(cdl_number="CDL-3")
    tractor = create_tractor(unit_number="T-3")
    trip = plan_trip(ctx["load"]["id"], driver["id"], tractor["id"])
    assert trip["status"] == "PLANNED"
    assert trip["provisional_pay_cents"] == 63240


def test_home_time_exactly_14_days_boundary(api):
    """PRD §3.4: "Home time is checked separately, after the HOS clauses: the
    number of whole 24-hour days between the driver's `last_home_at` and the
    load's `delivery_appt_at`, rounded down, must be at most 14 — a projection
    of exactly 14 days passes — and a longer projection is rejected with
    `ERR_HOME_TIME_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/home_time_exactly_14_days
    """
    ctx = setup_accepted_load()
    load2 = _accept_second_load(ctx)
    drv1 = create_driver(cdl_number="CDL-C37A",
                         last_home_at="2026-07-20T18:00:00Z")
    drv2 = create_driver(cdl_number="CDL-C37B",
                         last_home_at="2026-07-19T17:00:00Z")
    tr1 = create_tractor(unit_number="T-C37A")
    tr2 = create_tractor(unit_number="T-C37B")

    trip1 = plan_trip(ctx["load"]["id"], drv1["id"], tr1["id"])
    assert trip1["status"] == "PLANNED", "exactly 14 days out must pass"

    resp = api_client.create_trip(
        {"load_id": load2["id"], "driver_id": drv2["id"],
         "tractor_id": tr2["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-02T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_HOME_TIME_EXCEEDED)


def test_assigned_tractor_blocks_new_trip(api):
    """PRD §3.3: "the load must be `ACCEPTED` (any other status draws
    `ERR_LOAD_NOT_ASSIGNABLE`), the tractor must be `AVAILABLE` (otherwise
    `ERR_TRACTOR_NOT_AVAILABLE`), and then the safety and regulatory screen of
    §3.4 applies".

    Design: Corner/errors/tractor_assigned_blocks_new_trip
    """
    ctx = setup_planned_trip(cdl_number="CDL-R5A", unit_number="T-R5")
    load2 = _accept_second_load(ctx, delivery_appt_at="2026-08-05T18:00:00Z",
                                pickup_appt_at="2026-08-04T08:00:00Z")
    drv2 = create_driver(cdl_number="CDL-R5B")
    resp = api_client.create_trip(
        {"load_id": load2["id"], "driver_id": drv2["id"],
         "tractor_id": ctx["tractor"]["id"], "planned_deadhead_miles": 120,
         "planned_start_at": "2026-08-04T06:00:00Z",
         "route_states": [{"state_code": "TX", "miles": 1020}]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRACTOR_NOT_AVAILABLE)
