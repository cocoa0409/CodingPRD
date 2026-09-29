"""Calls that break several rules at once on the machine floor: which gate is allowed to
speak, and proof that the losing gates left nothing behind.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_tl_140, register_machine, register_permit, register_customer,
    setup_available_lot, setup_approved_batch, schedule_run, start_run, log_reading,
    submit_order, schedule_order, wind_roll_set, wrap_roll_set, complete_run,
    order_version, sublot, ON_SPEC_REELS_TL_140,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
ENV = TEST_USERS["env_officer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def _spine(pulp_draw_tons):
    """PM1 plus an APPROVED 18.000-ton batch and one SCHEDULED TL_140 run."""
    declare_tl_140()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z",
                       pulp_draw_tons=pulp_draw_tons)
    return machine, bundle["batch"], run


def _two_days_of_over_limit_flow(permit_id):
    log_reading(permit_id, headers=ENV, reading_date="2026-07-31", flow_m3=9500.00,
                bod_kg=100.00, tss_kg=50.00)
    log_reading(permit_id, headers=ENV, reading_date="2026-08-01", flow_m3=9600.00,
                bod_kg=100.00, tss_kg=50.00)


def _order_in_production_on_a_completed_run(roll_width_mm, slit_width_mm):
    machine, batch, run = _spine(15.000)
    customer = register_customer(name="Gulf Coast Box Co", allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=6.00,
                         roll_width_mm=roll_width_mm, roll_diameter_mm=1400,
                         wrap_spec="KRAFT_ONLY")
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=slit_width_mm, diameter_mm=1400,
                             roll_count=3, net_tons=6.000)
    complete_run(machine["id"], run["id"], ON_SPEC_REELS_TL_140)
    return machine, run, order, roll_set


def test_the_permit_speaks_first_when_the_pulp_is_also_short():
    """PRD §3.5: "Second comes the environmental gate: the mill's effluent permit must have a
    `compliance_posture` of `COMPLIANT` or `WATCH`, and a posture of `EXCEEDANCE` blocks every
    run start with `ERR_PERMIT_EXCEEDANCE_BLOCK` (HTTP 409) — this gate is evaluated
    **before** the pulp checks, so a run that is both environmentally blocked and short of
    pulp reports the permit exceedance, while a run that is not in `SCHEDULED` reports the
    run-state failure ahead of the permit."
    PRD §3.5: "Fourth, the pulp must actually be there: the referenced batch must be in
    `APPROVED` and its `available_tons` must be at least the run's `pulp_draw_tons`, with the
    boundary inclusive, and a shortfall or an unapproved batch is rejected with
    `ERR_INSUFFICIENT_PULP` (HTTP 409)."

    Design: Corner/validations/permit_exceedance_blocks_the_run_start_before_the_pulp_shortfall_is_noticed
    """
    permit = register_permit(**MILL_PERMIT)
    machine, batch, run = _spine(20.000)
    _two_days_of_over_limit_flow(permit["id"])

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_PERMIT_EXCEEDANCE_BLOCK.value, 409)

    posture = get_success_data(api_client.get_effluent_permit(permit["id"], OPERATOR))
    assert posture["compliance_posture"] == "EXCEEDANCE"
    assert posture["exceedance_day_count"] == 2
    assert posture["rolling_bod_kg_per_day"] == pytest.approx(100.000, abs=1e-6)

    unstarted = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert unstarted["run_status"] == "SCHEDULED"
    assert unstarted["quality_status"] == "PENDING"
    assert unstarted["started_by_user_id"] is None
    untouched = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert untouched["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert untouched["available_tons"] == pytest.approx(18.000, abs=1e-6), \
        "the 20.000-ton draw was impossible too, but the permit answered first"


def test_a_second_start_answers_on_the_run_axis_and_draws_no_more_pulp():
    """PRD §3.5: "Conversely, a request that targets the run axis from the wrong state —
    starting a run that is not `SCHEDULED`, completing or aborting a run that is not
    `RUNNING` — is rejected with `ERR_RUN_INVALID_STATE` (HTTP 409), which is also the code
    returned when the parent machine's `status` is `DOWN` at start time."
    PRD §2.8: "The global ordering is: authentication and role checks first (missing headers,
    unknown role, unresolvable entity-backed identity, role not permitted, resource
    ownership), then path existence resolved left to right, then pagination and request-shape
    validation, then body-reference resolution, then optimistic-concurrency version checks,
    then state-machine from-state checks, then segregation-of-duties checks, then the domain's
    business rules — safety and environmental gates, then constraint and capacity gates, then
    temporal gates, then the fiscal and ledger gates."
    PRD §3.5: "The run's `pulp_draw_tons` is added into the batch's `consumed_tons` and the
    batch's `available_tons` is recomputed."

    Design: Corner/validations/a_second_start_on_a_running_run_reports_run_state_not_the_permit_breach
    """
    permit = register_permit(**MILL_PERMIT)
    machine, batch, run = _spine(15.000)
    start_run(machine["id"], run["id"])
    _two_days_of_over_limit_flow(permit["id"])

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_RUN_INVALID_STATE.value, 409)

    running = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert running["run_status"] == "RUNNING"
    assert running["started_by_user_id"] == "mo_1"
    drawn = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert drawn["consumed_tons"] == pytest.approx(15.000, abs=1e-6), \
        "the refused second start must not draw the pulp twice"
    assert drawn["available_tons"] == pytest.approx(3.000, abs=1e-6)
    assert get_success_data(api_client.get_effluent_permit(
        permit["id"], OPERATOR))["compliance_posture"] == "EXCEEDANCE"


def test_an_unwrapped_roll_answers_on_its_own_state_not_the_missing_certificate():
    """PRD §3.6: "Its checks run in this order: the set must be in `WRAPPED`, or
    `ERR_ROLL_SET_INVALID_STATE` (HTTP 409); the producing run's `quality_status` must be
    `CERTIFIED`, or `ERR_RUN_NOT_CERTIFIED`; the target order's `status` must be
    `IN_PRODUCTION` or `PARTIALLY_ALLOCATED`, or `ERR_ORDER_INVALID_STATE`; the order's
    `product_code` must equal the producing run's `product_code`, or `ERR_PRODUCT_MISMATCH`;
    `expected_order_version` must match the order's current `version`, or
    `ERR_STALE_ORDER_VERSION` (HTTP 412); and the geometry must fit the order exactly — the
    set's `slit_width_mm` must **equal** the order's `roll_width_mm`, the set's `diameter_mm`
    must be no greater than the order's `roll_diameter_mm`, and the set's `wrap_spec` must
    equal the order's `wrap_spec` — with any deviation rejected as `ERR_ROLL_SPEC_MISMATCH`
    (HTTP 409)."
    PRD §3.6: "A new set opens in `WOUND` with `rewind_count` of 0, `quarantine_reason` null,
    and `allocated_order_id` null, and its creation recomputes the run's `produced_tons`."

    Design: Corner/validations/allocating_a_wound_roll_reports_roll_state_not_the_missing_certification
    """
    machine, run, order, roll_set = _order_in_production_on_a_completed_run(2400, 2400)

    response = api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": order_version(order["id"])},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_ROLL_SET_INVALID_STATE.value, 409)

    still_wound = get_success_data(api_client.get_roll_set(roll_set["id"], PLANNER))
    assert still_wound["status"] == "WOUND"
    assert still_wound["wrap_spec"] is None
    assert still_wound["allocated_order_id"] is None
    uncertified = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert uncertified["run_status"] == "COMPLETED"
    assert uncertified["quality_status"] == "PROVISIONAL"
    waiting = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert waiting["status"] == "IN_PRODUCTION"
    assert waiting["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert waiting["shortfall_tons"] == pytest.approx(6.000, abs=1e-6)


def test_the_concurrency_token_is_checked_before_the_rolls_are_measured():
    """PRD §2.5: "Version checks are evaluated after state-machine from-state checks and
    before any business rule."
    PRD §3.6: "Its checks run in this order: the set must be in `WRAPPED`, or
    `ERR_ROLL_SET_INVALID_STATE` (HTTP 409); the producing run's `quality_status` must be
    `CERTIFIED`, or `ERR_RUN_NOT_CERTIFIED`; the target order's `status` must be
    `IN_PRODUCTION` or `PARTIALLY_ALLOCATED`, or `ERR_ORDER_INVALID_STATE`; the order's
    `product_code` must equal the producing run's `product_code`, or `ERR_PRODUCT_MISMATCH`;
    `expected_order_version` must match the order's current `version`, or
    `ERR_STALE_ORDER_VERSION` (HTTP 412); and the geometry must fit the order exactly — the
    set's `slit_width_mm` must **equal** the order's `roll_width_mm`, the set's `diameter_mm`
    must be no greater than the order's `roll_diameter_mm`, and the set's `wrap_spec` must
    equal the order's `wrap_spec` — with any deviation rejected as `ERR_ROLL_SPEC_MISMATCH`
    (HTTP 409)."

    Design: Corner/validations/stale_order_version_outranks_the_roll_spec_mismatch_on_allocate
    """
    machine, run, order, roll_set = _order_in_production_on_a_completed_run(2000, 2200)
    wrap_roll_set(roll_set["id"], "KRAFT_ONLY")
    validate_success(api_client.certify_run(machine["id"], run["id"], CERTIFIER))
    current = order_version(order["id"])

    response = api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": current - 1}, PLANNER)
    validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)

    unallocated = get_success_data(api_client.get_roll_set(roll_set["id"], PLANNER))
    assert unallocated["status"] == "WRAPPED"
    assert unallocated["allocated_order_id"] is None
    order_after = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert order_after["version"] == current
    assert order_after["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert order_after["status"] == "IN_PRODUCTION"
    certified = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert certified["quality_status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "ql_cert"
