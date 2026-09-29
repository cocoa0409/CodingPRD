"""Requests that break two rules at once, where only the higher-ranked rule may be
reported: safety over fiscal, state over safety, referential over state, and the
concurrency token over physical spec.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, declare_standard_grades, declare_tl_140, publish_quote,
    register_customer, register_machine, register_permit, setup_approved_batch,
    schedule_run, start_run, complete_run, submit_order, schedule_order,
    wind_roll_set, wrap_roll_set, log_reading, order_version,
    reel_reading, ON_SPEC_REELS_TL_140, TEST_USERS, make_customer_headers,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
ENV = TEST_USERS["env_officer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 4200, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.400}
MILL_PERMIT = {"permit_number": "MILL-NPDES-01", "bod_limit_kg_per_day": 100.00,
               "tss_limit_kg_per_day": 200.00, "flow_limit_m3_per_day": 5000.00,
               "rolling_window_days": 7}
JULY_READINGS = [("2026-07-28", 90.00, 100.00), ("2026-07-29", 110.00, 120.00),
                 ("2026-07-30", 130.00, 100.00)]


def _drive_permit_over_the_bod_limit(permit_id):
    for date, bod, tss in JULY_READINGS:
        log_reading(permit_id, reading_date=date, flow_m3=4000.00,
                    bod_kg=bod, tss_kg=tss)
    return get_success_data(api_client.get_effluent_permit(permit_id, ENV))


def test_permit_exceedance_outranks_the_pulp_shortfall_on_a_run_start():
    """PRD §3.5: "Second comes the environmental gate: the mill's effluent permit
    must have a `compliance_posture` of `COMPLIANT` or `WATCH`, and a posture of
    `EXCEEDANCE` blocks every run start with `ERR_PERMIT_EXCEEDANCE_BLOCK` (HTTP 409)
    — this gate is evaluated **before** the pulp checks, so a run that is both
    environmentally blocked and short of pulp reports the permit exceedance, while a
    run that is not in `SCHEDULED` reports the run-state failure ahead of the permit."

    Design: Difficulty/priority_pair_validation_conflict/safety_exceedance_beats_fiscal_pulp_shortfall_on_run_start
    """
    permit = register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = setup_approved_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-07T00:00:00Z",
                       window_end="2026-08-07T06:00:00Z", pulp_draw_tons=30.000)
    posture = _drive_permit_over_the_bod_limit(permit["id"])
    assert posture["compliance_posture"] == "EXCEEDANCE"
    assert posture["rolling_bod_kg_per_day"] == pytest.approx(110.000, abs=1e-6)
    batch = get_success_data(api_client.get_pulp_batch(bundle["batch"]["id"], OPERATOR))
    assert batch["available_tons"] == pytest.approx(25.500, abs=1e-6), \
        "the 30.000-ton draw is also arithmetically impossible"

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_PERMIT_EXCEEDANCE_BLOCK.value, 409)

    unchanged = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert unchanged["run_status"] == "SCHEDULED"
    after = get_success_data(api_client.get_pulp_batch(bundle["batch"]["id"], OPERATOR))
    assert after["consumed_tons"] == pytest.approx(0.000, abs=1e-6)


def test_run_state_failure_outranks_the_permit_gate_on_a_second_start():
    """PRD §2.8: "The global ordering is: authentication and role checks first
    (missing headers, unknown role, unresolvable entity-backed identity, role not
    permitted, resource ownership), then path existence resolved left to right, then
    pagination and request-shape validation, then body-reference resolution, then
    optimistic-concurrency version checks, then state-machine from-state checks, then
    segregation-of-duties checks, then the domain's business rules — safety and
    environmental gates, then constraint and capacity gates, then temporal gates, then
    the fiscal and ledger gates."
    PRD §3.5: "Conversely, a request that targets the run axis from the wrong state —
    starting a run that is not `SCHEDULED`, completing or aborting a run that is not
    `RUNNING` — is rejected with `ERR_RUN_INVALID_STATE` (HTTP 409), which is also the
    code returned when the parent machine's `status` is `DOWN` at start time."

    Design: Difficulty/priority_pair_validation_conflict/state_axis_mismatch_beats_safety_exceedance_on_second_run_start
    """
    permit = register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = setup_approved_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-07T00:00:00Z",
                       window_end="2026-08-07T06:00:00Z", pulp_draw_tons=20.000)
    start_run(machine["id"], run["id"])
    posture = _drive_permit_over_the_bod_limit(permit["id"])
    assert posture["compliance_posture"] == "EXCEEDANCE"

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_RUN_INVALID_STATE.value, 409)

    still_running = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert still_running["run_status"] == "RUNNING"
    batch = get_success_data(api_client.get_pulp_batch(bundle["batch"]["id"], OPERATOR))
    assert batch["consumed_tons"] == pytest.approx(20.000, abs=1e-6), \
        "the refused second start must not double the draw"


def test_unresolvable_run_link_outranks_the_cancelled_order_state():
    """PRD §2.7: "Identifiers arriving in the request *body* rather than the path
    have their own codes: an unresolvable `fiber_grade_code`, `target_product_code` or
    `product_code` yields `ERR_GRADE_CODE_NOT_FOUND`; an unresolvable `supplier_id` or
    `customer_id` yields `ERR_PARTY_NOT_FOUND`; an unresolvable `pulp_batch_id` or a
    furnish line whose `inventory_lot_id` does not resolve yields
    `ERR_FURNISH_REFERENCE_NOT_FOUND`; an unresolvable `run_id`, `from_run_id`,
    `to_run_id` or `order_id`, or one that resolves to a row of the wrong type, yields
    `ERR_LINK_TARGET_NOT_FOUND`; and an entry of `reject_stream_ids` that does not
    resolve — or that resolves to a compensating reversal row — yields
    `ERR_REJECT_STREAM_REFERENCE_INVALID` (HTTP 404)."
    PRD §2.8: "The global ordering is: authentication and role checks first (missing
    headers, unknown role, unresolvable entity-backed identity, role not permitted,
    resource ownership), then path existence resolved left to right, then pagination
    and request-shape validation, then body-reference resolution, then
    optimistic-concurrency version checks, then state-machine from-state checks, then
    segregation-of-duties checks, then the domain's business rules — safety and
    environmental gates, then constraint and capacity gates, then temporal gates, then
    the fiscal and ledger gates."

    Design: Difficulty/priority_pair_validation_conflict/referential_link_target_beats_state_on_cancelled_order_schedule
    """
    declare_tl_140()
    customer = register_customer(name="Boxworks Packaging",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1500, max_roll_width_mm=2200,
                                 wrap_spec="POLY_COATED")
    order = submit_order(customer, "TL_140", ordered_tons=15.00,
                         requested_ship_date="2026-08-20", roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="POLY_COATED")
    cancelled = validate_success(api_client.cancel_customer_order(
        order["id"], make_customer_headers(customer["id"])))
    assert cancelled["status"] == "CANCELLED"

    response = api_client.schedule_customer_order(
        order["id"],
        {"run_id": NON_EXISTENT_UUID, "expected_order_version": cancelled["version"]},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_LINK_TARGET_NOT_FOUND.value, 404)

    after = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert after["status"] == "CANCELLED"
    assert after["scheduled_run_id"] is None
    assert after["version"] == cancelled["version"], "the refused call changed nothing"


def test_stale_order_version_outranks_the_roll_width_mismatch():
    """PRD §3.6: "Its checks run in this order: the set must be in `WRAPPED`, or
    `ERR_ROLL_SET_INVALID_STATE` (HTTP 409); the producing run's `quality_status` must
    be `CERTIFIED`, or `ERR_RUN_NOT_CERTIFIED`; the target order's `status` must be
    `IN_PRODUCTION` or `PARTIALLY_ALLOCATED`, or `ERR_ORDER_INVALID_STATE`; the order's
    `product_code` must equal the producing run's `product_code`, or
    `ERR_PRODUCT_MISMATCH`; `expected_order_version` must match the order's current
    `version`, or `ERR_STALE_ORDER_VERSION` (HTTP 412); and the geometry must fit the
    order exactly — the set's `slit_width_mm` must **equal** the order's
    `roll_width_mm`, the set's `diameter_mm` must be no greater than the order's
    `roll_diameter_mm`, and the set's `wrap_spec` must equal the order's `wrap_spec` —
    with any deviation rejected as `ERR_ROLL_SPEC_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_order_version_beats_roll_spec_mismatch_on_allocate
    """
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = setup_approved_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-08T00:00:00Z",
                       window_end="2026-08-08T06:00:00Z", pulp_draw_tons=20.000)
    customer = register_customer(name="Boxworks Packaging",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1500, max_roll_width_mm=2200,
                                 wrap_spec="POLY_COATED")
    order = submit_order(customer, "TL_140", ordered_tons=15.00,
                         requested_ship_date="2026-08-20", roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="POLY_COATED")
    version_at_creation = order["version"]
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=1800, diameter_mm=1200,
                             roll_count=3, net_tons=6.000)
    complete_run(machine["id"], run["id"], ON_SPEC_REELS_TL_140)
    wrap_roll_set(roll_set["id"], "POLY_COATED")
    validate_success(api_client.certify_run(machine["id"], run["id"], CERTIFIER))
    assert order_version(order["id"]) > version_at_creation, \
        "scheduling and the run start already invalidated the captured token"

    response = api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": version_at_creation},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)

    rs = get_success_data(api_client.get_roll_set(roll_set["id"], OPERATOR))
    assert rs["status"] == "WRAPPED"
    assert rs["allocated_order_id"] is None
    ord_after = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert ord_after["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert ord_after["status"] == "IN_PRODUCTION"


def test_the_width_mismatch_surfaces_once_the_version_token_is_current():
    """PRD §3.6: "Its checks run in this order: the set must be in `WRAPPED`, or
    `ERR_ROLL_SET_INVALID_STATE` (HTTP 409); the producing run's `quality_status` must
    be `CERTIFIED`, or `ERR_RUN_NOT_CERTIFIED`; the target order's `status` must be
    `IN_PRODUCTION` or `PARTIALLY_ALLOCATED`, or `ERR_ORDER_INVALID_STATE`; the order's
    `product_code` must equal the producing run's `product_code`, or
    `ERR_PRODUCT_MISMATCH`; `expected_order_version` must match the order's current
    `version`, or `ERR_STALE_ORDER_VERSION` (HTTP 412); and the geometry must fit the
    order exactly — the set's `slit_width_mm` must **equal** the order's
    `roll_width_mm`, the set's `diameter_mm` must be no greater than the order's
    `roll_diameter_mm`, and the set's `wrap_spec` must equal the order's `wrap_spec` —
    with any deviation rejected as `ERR_ROLL_SPEC_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_order_version_beats_roll_spec_mismatch_on_allocate
    """
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = setup_approved_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-08T00:00:00Z",
                       window_end="2026-08-08T06:00:00Z", pulp_draw_tons=20.000)
    customer = register_customer(name="Boxworks Packaging",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1500, max_roll_width_mm=2200,
                                 wrap_spec="POLY_COATED")
    order = submit_order(customer, "TL_140", ordered_tons=15.00,
                         requested_ship_date="2026-08-20", roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="POLY_COATED")
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=1800, diameter_mm=1200,
                             roll_count=3, net_tons=6.000)
    complete_run(machine["id"], run["id"], ON_SPEC_REELS_TL_140)
    wrap_roll_set(roll_set["id"], "POLY_COATED")
    api_client.certify_run(machine["id"], run["id"], CERTIFIER)

    response = api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": order_version(order["id"])},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_ROLL_SPEC_MISMATCH.value, 409)

    rs = get_success_data(api_client.get_roll_set(roll_set["id"], OPERATOR))
    assert rs["status"] == "WRAPPED", "1800 mm of roll cannot fill a 2000 mm order"
