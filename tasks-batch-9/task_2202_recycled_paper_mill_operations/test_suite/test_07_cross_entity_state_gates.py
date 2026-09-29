"""Requests whose every local predicate holds, refused because a derived posture or
a second status axis on a different entity says no — then admitted unchanged once
that other entity moves.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    declare_standard_grades, declare_fiber_grade, declare_tl_140, publish_quote,
    register_supplier, register_customer, register_machine, register_permit,
    create_confirmed_po, create_priced_po, record_receipt, disposition, sublot,
    setup_available_lot, setup_approved_batch, queue_batch, furnish_line,
    drive_batch_to_cleaned, schedule_run, start_run, complete_run,
    submit_order, schedule_order, wind_roll_set, wrap_roll_set, order_version,
    log_reading, solids_rows, ON_SPEC_REELS_TL_140, TEST_USERS,
    make_supplier_headers,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_LOGGER = TEST_USERS["env_logger_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 4200, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.400}
MILL_PERMIT = {"permit_number": "MILL-NPDES-01", "bod_limit_kg_per_day": 100.00,
               "tss_limit_kg_per_day": 200.00, "flow_limit_m3_per_day": 5000.00,
               "rolling_window_days": 7}
RISING_BOD = [("2026-07-28", 90.00, 100.00), ("2026-07-29", 110.00, 120.00),
              ("2026-07-30", 130.00, 100.00)]


def _permit_in_exceedance():
    """Three readings averaging 110.000 kg BOD against a 100.00 limit. Returns the
    permit and the newest reading, whose void re-anchors the window on 2026-07-29."""
    permit = register_permit(**MILL_PERMIT)
    newest = None
    for date, bod, tss in RISING_BOD:
        newest = log_reading(permit["id"], reading_date=date, flow_m3=4000.00,
                             bod_kg=bod, tss_kg=tss)
    posture = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert posture["compliance_posture"] == "EXCEEDANCE"
    assert posture["rolling_bod_kg_per_day"] == pytest.approx(110.000, abs=1e-6)
    return permit, newest


def _run_with_ample_pulp_behind_a_blocked_permit():
    machine = register_machine(**PM1)
    bundle = setup_approved_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-10T00:00:00Z",
                       window_end="2026-08-10T06:00:00Z", pulp_draw_tons=20.000)
    permit, newest = _permit_in_exceedance()
    return {"machine": machine, "batch": bundle["batch"], "run": run,
            "permit": permit, "newest_reading": newest}


def test_a_fully_stocked_run_is_still_blocked_by_another_entitys_posture():
    """PRD §3.5: "Second comes the environmental gate: the mill's effluent permit must
    have a `compliance_posture` of `COMPLIANT` or `WATCH`, and a posture of
    `EXCEEDANCE` blocks every run start with `ERR_PERMIT_EXCEEDANCE_BLOCK` (HTTP 409)
    — this gate is evaluated **before** the pulp checks, so a run that is both
    environmentally blocked and short of pulp reports the permit exceedance, while a
    run that is not in `SCHEDULED` reports the run-state failure ahead of the permit."

    Design: Difficulty/cross_entity_state_dependency/run_start_gated_by_effluent_permit_posture_and_released_by_void
    """
    world = _run_with_ample_pulp_behind_a_blocked_permit()
    stocked = get_success_data(api_client.get_pulp_batch(world["batch"]["id"], OPERATOR))
    assert stocked["available_tons"] == pytest.approx(25.500, abs=1e-6), \
        "25.500 available comfortably covers the 20.000-ton draw"

    response = api_client.start_run(world["machine"]["id"], world["run"]["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_PERMIT_EXCEEDANCE_BLOCK.value, 409)

    run = get_success_data(api_client.get_run(world["run"]["id"], PLANNER))
    assert run["run_status"] == "SCHEDULED"
    assert run["quality_status"] == "PENDING"
    untouched = get_success_data(api_client.get_pulp_batch(world["batch"]["id"], OPERATOR))
    assert untouched["consumed_tons"] == pytest.approx(0.000, abs=1e-6)


def test_voiding_the_newest_reading_re_anchors_the_window_and_releases_the_run():
    """PRD §3.7: "Because voiding the newest reading moves the anchor, a void can
    shrink the window and change every one of these figures." PRD §3.5: "The run's
    `pulp_draw_tons` is added into the batch's `consumed_tons` and the batch's
    `available_tons` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/run_start_gated_by_effluent_permit_posture_and_released_by_void
    """
    world = _run_with_ample_pulp_behind_a_blocked_permit()
    blocked = api_client.start_run(world["machine"]["id"], world["run"]["id"], OPERATOR)
    validate_error(blocked, ApiErrorId.ERR_PERMIT_EXCEEDANCE_BLOCK.value, 409)

    voided = get_success_data(api_client.void_effluent_reading(
        world["newest_reading"]["id"], ENV_LOGGER))
    assert voided["voided"] is True
    recovered = get_success_data(api_client.get_effluent_permit(world["permit"]["id"], ENV))
    assert recovered["rolling_bod_kg_per_day"] == pytest.approx(100.000, abs=1e-6)
    assert recovered["compliance_posture"] == "WATCH"

    response = api_client.start_run(world["machine"]["id"], world["run"]["id"], OPERATOR)
    validate_success(response)
    assert get_success_data(response)["run_status"] == "RUNNING"
    drawn = get_success_data(api_client.get_pulp_batch(world["batch"]["id"], OPERATOR))
    assert drawn["consumed_tons"] == pytest.approx(20.000, abs=1e-6)
    assert drawn["available_tons"] == pytest.approx(5.500, abs=1e-6)


def _wrapped_set_matching_an_order_on_an_uncertified_run():
    register_permit()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-11T00:00:00Z",
                       window_end="2026-08-11T06:00:00Z", pulp_draw_tons=20.000)
    customer = register_customer(name="Boxworks Packaging",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1500, max_roll_width_mm=2200,
                                 wrap_spec="POLY_COATED")
    order = submit_order(customer, "TL_140", ordered_tons=15.00, roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="POLY_COATED")
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2000, diameter_mm=1200,
                             roll_count=3, net_tons=6.000)
    completed = complete_run(machine["id"], run["id"], ON_SPEC_REELS_TL_140)
    roll_set = wrap_roll_set(roll_set["id"], "POLY_COATED")
    return {"machine": machine, "run": completed, "order_id": order["id"],
            "roll_set": roll_set}


def test_a_spec_matched_wrapped_roll_waits_on_the_runs_second_status_axis():
    """PRD §3.6: "Its checks run in this order: the set must be in `WRAPPED`, or
    `ERR_ROLL_SET_INVALID_STATE` (HTTP 409); the producing run's `quality_status` must
    be `CERTIFIED`, or `ERR_RUN_NOT_CERTIFIED`; the target order's `status` must be
    `IN_PRODUCTION` or `PARTIALLY_ALLOCATED`, or `ERR_ORDER_INVALID_STATE`; the
    order's `product_code` must equal the producing run's `product_code`, or
    `ERR_PRODUCT_MISMATCH`; `expected_order_version` must match the order's current
    `version`, or `ERR_STALE_ORDER_VERSION` (HTTP 412); and the geometry must fit the
    order exactly — the set's `slit_width_mm` must **equal** the order's
    `roll_width_mm`, the set's `diameter_mm` must be no greater than the order's
    `roll_diameter_mm`, and the set's `wrap_spec` must equal the order's `wrap_spec` —
    with any deviation rejected as `ERR_ROLL_SPEC_MISMATCH` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/roll_allocation_gated_by_producing_run_quality_axis
    """
    world = _wrapped_set_matching_an_order_on_an_uncertified_run()
    assert world["run"]["quality_status"] == "PROVISIONAL"
    assert world["roll_set"]["status"] == "WRAPPED"

    response = api_client.allocate_roll_set(
        world["roll_set"]["id"],
        {"order_id": world["order_id"],
         "expected_order_version": order_version(world["order_id"])}, PLANNER)
    validate_error(response, ApiErrorId.ERR_RUN_NOT_CERTIFIED.value, 409)

    order = get_success_data(api_client.get_customer_order(world["order_id"], PLANNER))
    assert order["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert order["status"] == "IN_PRODUCTION"


def test_certifying_the_run_alone_turns_the_identical_allocation_into_a_booking():
    """PRD §3.6: "`allocated_tons` is the sum of `net_tons` over roll sets whose
    `allocated_order_id` is this order and whose status is `ALLOCATED` or `SHIPPED`,
    rounded to three decimal places; `shipped_tons` is the same sum restricted to sets
    in `SHIPPED`; and `shortfall_tons` is `ordered_tons` minus `allocated_tons`,
    floored at zero and rounded to three decimal places."

    Design: Difficulty/cross_entity_state_dependency/roll_allocation_gated_by_producing_run_quality_axis
    """
    world = _wrapped_set_matching_an_order_on_an_uncertified_run()
    refused = api_client.allocate_roll_set(
        world["roll_set"]["id"],
        {"order_id": world["order_id"],
         "expected_order_version": order_version(world["order_id"])}, PLANNER)
    validate_error(refused, ApiErrorId.ERR_RUN_NOT_CERTIFIED.value, 409)

    certified = get_success_data(api_client.certify_run(
        world["machine"]["id"], world["run"]["id"], CERTIFIER))
    assert certified["quality_status"] == "CERTIFIED"
    assert certified["certified_quality_index"] == pytest.approx(100.00, abs=1e-6)

    response = api_client.allocate_roll_set(
        world["roll_set"]["id"],
        {"order_id": world["order_id"],
         "expected_order_version": order_version(world["order_id"])}, PLANNER)
    validate_success(response)
    allocated = get_success_data(response)
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_order_id"] == world["order_id"]

    order = get_success_data(api_client.get_customer_order(world["order_id"], PLANNER))
    assert order["allocated_tons"] == pytest.approx(6.000, abs=1e-6)
    assert order["shortfall_tons"] == pytest.approx(9.000, abs=1e-6)
    assert order["status"] == "PARTIALLY_ALLOCATED"


def _supplier_on_probation_with_two_priced_orders():
    """Two rejected DLK_37 trucks put Northgate on PROBATION; two OCC_11 orders are
    then priced, one for exactly 500.00 tons and one for 500.01."""
    declare_standard_grades()
    declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                        max_contamination_pct=2.00, max_moisture_pct=10.00,
                        nominal_yield_pct=72.00, deink_required=True,
                        downgrade_target_grade_code=None, rank_order=3)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    publish_quote(index_symbol="PPI_DLK", effective_month="2026-07",
                  published_price_per_ton=150.00)
    supplier = register_supplier(name="Northgate Recovered", freight_per_ton=18.00)
    dlk = create_confirmed_po(supplier["id"], "DLK_37", contracted_tons=150.00,
                              index_basis="PRIOR_MONTH", priced_for_month="2026-08")
    for reference in ("TRK-P-001", "TRK-P-002"):
        receipt = record_receipt(dlk["id"], [sublot(1, 6.000, 1.000, 8.00, 4.00)],
                                 truck_reference=reference)
        disposition(receipt["id"], "REJECT")
    orders = [create_priced_po(supplier["id"], "OCC_11", contracted_tons=tons,
                              index_basis="PRIOR_MONTH", priced_for_month="2026-08")
              for tons in (500.00, 500.01)]
    return supplier, orders[0], orders[1]


def test_exactly_five_hundred_tons_confirms_while_the_supplier_is_on_probation():
    """PRD §3.1: "Taking an order `PRICED → CONFIRMED` requires the order to be in
    `PRICED`, requires the acting `X-User-ID` to equal the order's `supplier_id`
    (otherwise `ERR_NOT_RESOURCE_OWNER`), and requires the supplier to be commercially
    fit: either `qualification_status` reads `QUALIFIED`, or it reads `PROBATION` and
    `contracted_tons` is no greater than 500.00."

    Design: Difficulty/cross_entity_state_dependency/purchase_order_confirmation_gated_by_supplier_probation_tonnage_cap
    """
    supplier, at_the_cap, _over = _supplier_on_probation_with_two_priced_orders()

    posture = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert posture["contamination_strike_count"] == 2
    assert posture["qualification_status"] == "PROBATION"

    response = api_client.confirm_purchase_order(
        at_the_cap["id"], make_supplier_headers(supplier["id"]))
    validate_success(response)
    confirmed = get_success_data(response)
    assert confirmed["contracted_tons"] == pytest.approx(500.00, abs=1e-6)
    assert confirmed["status"] == "CONFIRMED"


def test_one_hundredth_of_a_ton_over_the_probation_cap_is_refused():
    """PRD §3.1: "A supplier on probation attempting to confirm a contract above
    500.00 tons is rejected with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/purchase_order_confirmation_gated_by_supplier_probation_tonnage_cap
    """
    supplier, at_the_cap, over_the_cap = _supplier_on_probation_with_two_priced_orders()
    validate_success(api_client.confirm_purchase_order(
        at_the_cap["id"], make_supplier_headers(supplier["id"])))

    response = api_client.confirm_purchase_order(
        over_the_cap["id"], make_supplier_headers(supplier["id"]))
    validate_error(response, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED.value, 409)

    stalled = get_success_data(api_client.get_purchase_order(over_the_cap["id"], BUYER))
    assert stalled["contracted_tons"] == pytest.approx(500.01, abs=1e-6)
    assert stalled["status"] == "PRICED", \
        "pricing was allowed; only the confirmation meets the probation cap"
    assert stalled["received_net_tons"] == pytest.approx(0.00, abs=1e-6)


LAND_APPLICATION_MANIFEST = {"manifest_number": "MAN-LA-001",
                             "destination": "LAND_APPLICATION"}


def _pending_pulp_reject_row_behind_a_blocked_permit():
    declare_tl_140()
    bundle = setup_available_lot()
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 30.000)])
    drive_batch_to_cleaned(batch["id"], 4.500)
    rows = solids_rows(source_ref_id=batch["id"], source_kind="PULP_REJECT")
    assert len(rows) == 1, "the clean step leaves exactly one PULP_REJECT row"
    permit, newest = _permit_in_exceedance()
    return {"permit": permit, "newest_reading": newest, "row": rows[0]}


def test_a_valid_land_application_manifest_is_barred_by_the_permit_posture():
    """PRD §3.7: "Preparing a `LAND_APPLICATION` manifest while the permit posture is
    `EXCEEDANCE` is rejected with `ERR_LAND_APPLICATION_BARRED` (HTTP 409), and so is
    signing one."

    Design: Difficulty/cross_entity_state_dependency/land_application_manifest_gated_by_permit_posture_at_creation
    """
    world = _pending_pulp_reject_row_behind_a_blocked_permit()
    assert world["row"]["dry_solids_tons"] == pytest.approx(4.500, abs=1e-6)
    assert world["row"]["disposition"] == "PENDING"

    payload = dict(LAND_APPLICATION_MANIFEST, reject_stream_ids=[world["row"]["id"]])
    response = api_client.create_sludge_manifest(payload, ENV_PREPARER)
    validate_error(response, ApiErrorId.ERR_LAND_APPLICATION_BARRED.value, 409)

    unmoved = get_success_data(api_client.get_reject_stream(world["row"]["id"], ENV))
    assert unmoved["disposition"] == "PENDING"
    assert unmoved["manifest_id"] is None


def test_the_barred_manifest_number_is_still_free_once_the_posture_recovers():
    """PRD §3.7: "Preparation records the acting officer as `prepared_by_user_id`,
    computes `total_dry_solids_tons` as the sum of `dry_solids_tons` across the claimed
    rows rounded to three decimal places, opens the manifest in `DRAFT`, and leaves the
    claimed rows in `PENDING` — nothing moves until the manifest is signed."

    Design: Difficulty/cross_entity_state_dependency/land_application_manifest_gated_by_permit_posture_at_creation
    """
    world = _pending_pulp_reject_row_behind_a_blocked_permit()
    payload = dict(LAND_APPLICATION_MANIFEST, reject_stream_ids=[world["row"]["id"]])
    validate_error(api_client.create_sludge_manifest(payload, ENV_PREPARER),
                   ApiErrorId.ERR_LAND_APPLICATION_BARRED.value, 409)

    get_success_data(api_client.void_effluent_reading(
        world["newest_reading"]["id"], ENV_LOGGER))
    recovered = get_success_data(api_client.get_effluent_permit(world["permit"]["id"], ENV))
    assert recovered["compliance_posture"] == "WATCH"

    response = api_client.create_sludge_manifest(payload, ENV_PREPARER)
    validate_success(response, expected_status=201)
    manifest = get_success_data(response)
    assert manifest["manifest_number"] == "MAN-LA-001", \
        "the blocked attempt reserved nothing, so the number is still available"
    assert manifest["destination"] == "LAND_APPLICATION"
    assert manifest["status"] == "DRAFT"
    assert manifest["total_dry_solids_tons"] == pytest.approx(4.500, abs=1e-6)
    assert manifest["prepared_by_user_id"] == "eo_prep"
