"""Guards that count: the same hands may not judge their own work, and the price and
schedule loops both terminate rather than spinning forever.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    build_user_headers, TEST_USERS, declare_fiber_grade, declare_tl_140,
    publish_quote, register_supplier, register_machine, register_permit,
    register_customer, create_draft_po, setup_available_lot, setup_approved_batch,
    schedule_run, start_run, submit_order, schedule_order, complete_run,
    prepare_manifest, solids_rows, solids_summary, log_reading, po_version,
    order_version, reel_reading, sublot, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
LAB = TEST_USERS["lab_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]
LAB_AS_OPERATOR = build_user_headers("ql_1", "MachineOperator")

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
THREE_PERFECT_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.50),
                       reel_reading(2, 5.000, 140.0, 7.50, 2.50),
                       reel_reading(3, 5.000, 140.0, 7.50, 2.50)]


def _approved_twenty_ton_batch():
    declare_tl_140()
    return setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))


def _scheduled_run(**run_overrides):
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = _approved_twenty_ton_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=15.000, **run_overrides)
    return machine, bundle, run


def test_the_hands_that_ran_the_machine_cannot_sign_off_its_quality():
    """PRD §3.5: "Certification, `PROVISIONAL → CERTIFIED`, is a `QualityLab` act with four
    requirements evaluated in this order: the quality axis must read `PROVISIONAL`; the acting
    `X-User-ID` must differ from the run's `started_by_user_id`, and an operator certifying
    their own run is rejected with `ERR_SOD_SAME_OPERATOR` (HTTP 409); `off_spec_reel_count`
    must be exactly 0; and the certified quality index must be at least 85.00."
    PRD §3.5: "Certification stores `certified_quality_index`, records the acting identifier as
    `certified_by_user_id`, and makes every `WRAPPED` roll set of the run eligible for
    allocation."

    Design: Corner/errors/the_identity_that_started_the_run_cannot_certify_it_even_wearing_the_lab_role
    """
    machine, bundle, run = _scheduled_run()
    start_run(machine["id"], run["id"], LAB_AS_OPERATOR)
    completed = complete_run(machine["id"], run["id"], THREE_PERFECT_REELS,
                             headers=LAB_AS_OPERATOR)
    assert completed["off_spec_reel_count"] == 0
    assert completed["provisional_quality_index"] == pytest.approx(100.00, abs=1e-6)

    response = api_client.certify_run(machine["id"], run["id"], LAB)
    validate_error(response, ApiErrorId.ERR_SOD_SAME_OPERATOR.value, 409)

    uncertified = get_success_data(api_client.get_run(run["id"], LAB))
    assert uncertified["quality_status"] == "PROVISIONAL"
    assert uncertified["certified_by_user_id"] is None
    assert uncertified["certified_quality_index"] is None
    assert uncertified["started_by_user_id"] == "ql_1", \
        "one opaque identity wore both roles, and the guard is on the identity"


def test_the_officer_who_wrote_the_manifest_cannot_countersign_it():
    """PRD §3.7: "It then requires that the acting `X-User-ID` differ from the manifest's
    `prepared_by_user_id` **and** that the acting `X-User-ID` is not the `logged_by_user_id` of
    any non-voided reading inside the permit's current rolling window; a violation of either
    half is rejected with `ERR_SOD_SAME_ENV_OFFICER` (HTTP 409)."
    PRD §3.7: "Preparation records the acting officer as `prepared_by_user_id`, computes
    `total_dry_solids_tons` as the sum of `dry_solids_tons` across the claimed rows rounded to
    three decimal places, opens the manifest in `DRAFT`, and leaves the claimed rows in
    `PENDING` — nothing moves until the manifest is signed."

    Design: Corner/errors/the_officer_who_prepared_a_manifest_cannot_sign_it
    """
    register_permit(**MILL_PERMIT)
    bundle = _approved_twenty_ton_batch()
    row = solids_rows(source_ref_id=bundle["batch"]["id"],
                      source_kind="PULP_REJECT")[0]
    draft = prepare_manifest([row["id"]], manifest_number="MAN-0001",
                             destination="LANDFILL")

    response = api_client.sign_sludge_manifest(draft["id"], ENV_PREPARER)
    validate_error(response, ApiErrorId.ERR_SOD_SAME_ENV_OFFICER.value, 409)

    unsigned = get_success_data(api_client.get_sludge_manifest(draft["id"], ENV))
    assert unsigned["status"] == "DRAFT"
    assert unsigned["signed_by_user_id"] is None
    assert unsigned["prepared_by_user_id"] == "eo_prep"
    assert unsigned["total_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    still_pending = get_success_data(api_client.get_reject_stream(row["id"], ENV))
    assert still_pending["disposition"] == "PENDING"
    assert still_pending["manifest_id"] is None
    summary = solids_summary()
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)


def test_sludge_cannot_go_to_the_fields_while_the_outfall_is_in_exceedance():
    """PRD §3.7: "Preparing a `LAND_APPLICATION` manifest while the permit posture is
    `EXCEEDANCE` is rejected with `ERR_LAND_APPLICATION_BARRED` (HTTP 409), and so is signing
    one."
    PRD §3.7: "The posture is `EXCEEDANCE` when either ratio is strictly greater than 1.00, or
    when `exceedance_day_count` is 2 or more."
    PRD §3.7: "`exceedance_day_count` is the number of readings inside the window whose
    `flow_m3` is strictly greater than the permit's `flow_limit_m3_per_day`."

    Design: Corner/errors/land_application_is_barred_while_the_permit_is_in_exceedance
    """
    set_clock("2026-08-01T00:00:00Z")
    permit = register_permit(**MILL_PERMIT)
    bundle = _approved_twenty_ton_batch()
    row = solids_rows(source_ref_id=bundle["batch"]["id"],
                      source_kind="PULP_REJECT")[0]
    for date in ("2026-07-30", "2026-07-31"):
        log_reading(permit["id"], headers=ENV, reading_date=date, flow_m3=9500.00,
                    bod_kg=100.00, tss_kg=50.00)

    response = api_client.create_sludge_manifest(
        {"manifest_number": "MAN-0003", "destination": "LAND_APPLICATION",
         "reject_stream_ids": [row["id"]]}, ENV_PREPARER)
    validate_error(response, ApiErrorId.ERR_LAND_APPLICATION_BARRED.value, 409)

    posture = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert posture["compliance_posture"] == "EXCEEDANCE"
    assert posture["exceedance_day_count"] == 2, \
        "both days ran above the flow limit, and two such days are an exceedance"
    unclaimed = get_success_data(api_client.get_reject_stream(row["id"], ENV))
    assert unclaimed["disposition"] == "PENDING"
    assert unclaimed["manifest_id"] is None


def test_the_third_withdrawal_of_a_price_is_refused_and_the_number_survives():
    """PRD §3.1: "Withdrawal requires the order to be in `PRICED` and requires
    `pricing_revision_count` to be below 2; it increments `pricing_revision_count` by one,
    clears `quoted_unit_price_per_ton`, `fuel_surcharge_per_ton`, `extended_contract_value` and
    `index_quote_month_used` back to null, and bumps `version` by one."
    PRD §3.1: "Because the counter starts at 0, this yields exactly two legitimate reprice
    loops; the third withdrawal attempt — the one made when `pricing_revision_count` already
    reads 2 — is rejected with `ERR_REPRICE_LIMIT_REACHED` (HTTP 409)."
    PRD §3.1: "Fifth, the `quoted_unit_price_per_ton` is the base price multiplied by one minus
    the selected discount, plus the supplier's `freight_per_ton`, plus the
    `fuel_surcharge_per_ton` just computed, the whole rounded half up to two decimal places;
    and `extended_contract_value` is that unit price multiplied by `contracted_tons`, rounded
    half up to two decimal places."

    Design: Corner/errors/a_third_withdrawal_of_pricing_hits_the_reprice_ceiling
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_draft_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                        index_basis="CURRENT_MONTH", priced_for_month="2026-08",
                        negotiated_delta_per_ton=5.00)
    for _ in range(2):
        validate_success(api_client.price_purchase_order(
            po["id"], {"expected_purchase_order_version": po_version(po["id"])}, BUYER))
        validate_success(api_client.withdraw_purchase_order_pricing(
            po["id"], {"expected_purchase_order_version": po_version(po["id"])}, BUYER))
    priced = validate_success(api_client.price_purchase_order(
        po["id"], {"expected_purchase_order_version": po_version(po["id"])}, BUYER))
    assert priced["pricing_revision_count"] == 2
    version_before = priced["version"]

    response = api_client.withdraw_purchase_order_pricing(
        po["id"], {"expected_purchase_order_version": version_before}, BUYER)
    validate_error(response, ApiErrorId.ERR_REPRICE_LIMIT_REACHED.value, 409)

    intact = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert intact["status"] == "PRICED"
    assert intact["pricing_revision_count"] == 2
    assert intact["quoted_unit_price_per_ton"] == pytest.approx(199.81, abs=1e-6), \
        "185.00 of base plus 12.50 of freight plus a 2.31 surcharge"
    assert intact["index_quote_month_used"] == "2026-08"
    assert intact["version"] == version_before


def test_the_fourth_deschedule_of_one_order_is_refused():
    """PRD §3.6: "Descheduling, `SCHEDULED → SUBMITTED`, returns the order to the unscheduled
    pool."
    PRD §3.6: "It requires the order to be in `SCHEDULED` and requires `deschedule_count` to be
    below 3; it clears `scheduled_run_id`, increments `deschedule_count` by one and bumps
    `version`."
    PRD §3.6: "Three deschedules are therefore permitted, and the fourth attempt — made when
    `deschedule_count` already reads 3 — is rejected with `ERR_DESCHEDULE_LIMIT` (HTTP 409)."

    Design: Corner/errors/a_fourth_deschedule_of_the_same_order_is_refused
    """
    machine, bundle, run = _scheduled_run()
    customer = register_customer(name="Great Lakes Converting",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=6.00, roll_width_mm=2400,
                         roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY")
    for _ in range(3):
        schedule_order(order["id"], run["id"])
        validate_success(api_client.deschedule_customer_order(order["id"], PLANNER))
    schedule_order(order["id"], run["id"])
    spent = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert spent["deschedule_count"] == 3
    assert spent["status"] == "SCHEDULED"

    response = api_client.deschedule_customer_order(order["id"], PLANNER)
    validate_error(response, ApiErrorId.ERR_DESCHEDULE_LIMIT.value, 409)

    stuck = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert stuck["status"] == "SCHEDULED"
    assert stuck["deschedule_count"] == 3
    assert stuck["scheduled_run_id"] == run["id"], \
        "the loop terminates on the run it was last sequenced onto"
