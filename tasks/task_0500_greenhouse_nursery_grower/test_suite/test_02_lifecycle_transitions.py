"""State-machine transitions, terminal lockdown, and guarded preconditions.

Queue B (corner) — state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    TEST_USERS,
    set_clock, create_active_variety, create_zone, create_planned_batch,
    zone_version, record_grade, create_broker, issue_phyto,
    setup_growing_batch, setup_multi_line_order, create_shipment,
)

GM = TEST_USERS["grower_manager_headers"]
PT = TEST_USERS["production_tech_headers"]
SC = TEST_USERS["sales_coordinator_headers"]


def test_second_transplant_on_growing_batch_invalid_state(api):
    """PRD 2.8: "state legality is evaluated: the target resource must be in a state
    from which the requested transition is defined, failing which the request is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/transplant_from_growing_invalid_state
    """
    base = setup_growing_batch(api, sourced=10, capacity=100, cultivar_code="TGR1")
    zv = zone_version(api, base["zone"]["id"])
    resp = api.transplant_batch(base["batch"]["id"],
                                {"started_count": 10, "expected_zone_version": zv}, PT)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_activate_retired_variety_invalid_state(api):
    """PRD 3.1: "Retiring a variety — permitted from either `ACTIVE` or `SUSPENDED`
    — moves it to the terminal `RETIRED` state".

    Design: Corner/state_machines/retired_variety_terminal_lockdown
    """
    v = validate_success(api.create_variety(
        {"common_name": "Ret", "cultivar_code": "RETR1", "propagation_form": "PLUG",
         "grow_cycle_days": 5, "container_footprint_units": 1,
         "ship_ready_grade_min_height_cm": 8, "ship_ready_min_live_pct": 0.5}, GM),
        expected_status=201)
    validate_success(api.activate_variety(v["id"], GM))
    validate_success(api.retire_variety(v["id"], GM))
    validate_error(api.activate_variety(v["id"], GM), "ERR_INVALID_STATE", expected_status=409)


def test_retire_variety_backing_planned_batch_blocked(api):
    """PRD 3.1: "but only when no batch referencing the variety is in any of the
    states `PLANNED`, `GROWING`, `GRADING`, `SALEABLE`, or `HELD`; if such a batch
    exists, retirement is rejected with `ERR_VARIETY_IN_USE`."

    Design: Corner/state_machines/retire_variety_in_use_blocked
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="INUS1", propagation_form="PLUG")
    zone = create_zone(api, capacity_units=100)
    create_planned_batch(api, variety["id"], zone["id"], sourced_count=10)
    validate_error(api.retire_variety(variety["id"], GM), "ERR_VARIETY_IN_USE", expected_status=409)


def test_decommission_zone_with_reservation_blocked(api):
    """PRD 3.2: "both `occupied_units` and `reserved_units` must be exactly zero,
    failing which the request is rejected with `ERR_ZONE_NOT_EMPTY`."

    Design: Corner/state_machines/decommission_nonempty_zone_blocked
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="DECR1", propagation_form="PLUG")
    zone = create_zone(api, capacity_units=100)
    create_planned_batch(api, variety["id"], zone["id"], sourced_count=10)
    validate_error(api.decommission_zone(zone["id"], GM), "ERR_ZONE_NOT_EMPTY", expected_status=409)


def test_void_planned_batch_releases_reservation(api):
    """PRD 3.3: "Voiding releases the batch's reservation: the zone's
    `reserved_units` is reduced by this batch's reservation, its `free_units` and
    `fill_state` are recomputed, and the cascade onto the zone increments the zone's
    `version`."

    Design: Corner/state_machines/void_planned_batch_releases_reservation
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="VDR1", propagation_form="PLUG",
                                    container_footprint_units=1)
    zone = create_zone(api, capacity_units=100)
    batch = create_planned_batch(api, variety["id"], zone["id"], sourced_count=40)
    voided = validate_success(api.void_batch(batch["id"], GM))
    assert voided["status"] == "VOIDED"
    z = validate_success(api.get_zone(zone["id"], GM))
    assert z["reserved_units"] == 0
    assert z["free_units"] == 100


def test_cancel_confirmed_order_with_dispatched_shipment_blocked(api):
    """PRD 3.12: "Cancelling a `CONFIRMED` order is a full compensation of the
    confirm: it is permitted only when no shipment for this order is `DISPATCHED`,
    otherwise it is rejected with `ERR_ORDER_HAS_SHIPMENT`."

    Design: Corner/state_machines/cancel_confirmed_order_with_dispatched_shipment_blocked
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 100, "unit_price_cents": 300}],
        ship_to_state="OR", confirm=True, cultivar_code="CXR1")
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 2}])
    validate_success(api.dispatch_shipment(ship["id"], SC))
    resp = api.cancel_order(s["order"]["id"], SC)
    # The dispatch leaves the order FULFILLING; PRD names ERR_ORDER_HAS_SHIPMENT for
    # the cancel-with-shipment guard but does not commit to whether the FULFILLING
    # state pre-empts it, so either deterministic rejection is PRD-faithful.
    validate_error_is_one_of(resp, ["ERR_ORDER_HAS_SHIPMENT", "ERR_INVALID_STATE"])


def test_start_grading_before_grow_cycle_complete_rejected(api):
    """PRD 3.6: "This is permitted only after the grow cycle is complete — the
    current logical-clock instant must be at or after the batch's `target_ship_date`,
    otherwise the request is rejected with `ERR_GROW_CYCLE_INCOMPLETE`".

    Design: Corner/state_machines/start_grading_before_grow_cycle_complete
    """
    base = setup_growing_batch(api, sourced=10, capacity=100, grow_cycle_days=30,
                               cultivar_code="GCR1")
    record_grade(api, base["batch"]["id"], 10)  # measurement present; only cycle is incomplete
    validate_error(api.start_grading(base["batch"]["id"], PT),
                   "ERR_GROW_CYCLE_INCOMPLETE", expected_status=409)


def test_phyto_certificate_expires_on_ops_checkpoint(api):
    """PRD 3.15: "Running the checkpoint moves every `VALID` phytosanitary
    certificate whose `valid_until` is strictly before the current logical-clock
    instant to `EXPIRED`".

    Design: Corner/state_machines/phyto_expires_on_ops_checkpoint
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    broker = create_broker(api, ship_to_state="NY", credit_limit_cents=1000)
    cert = issue_phyto(api, broker["id"], certificate_number="PC-9",
                       valid_until="2026-02-05T00:00:00Z")
    set_clock(api, "2026-02-06T00:00:00Z")
    validate_success(api.run_ops(GM))
    data = validate_success(api.get_phyto_certificate(cert["id"], SC))
    assert data["status"] == "EXPIRED"
