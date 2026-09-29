"""Refusals along the fiber road: an implausible reject weight, a pulp shortfall, a run
booked for the wrong product, a lot already spent, and a disposition the assay forbids.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, declare_tis_16, publish_quote,
    register_supplier, register_machine, register_permit, create_confirmed_po,
    record_receipt, setup_available_lot, setup_approved_batch, queue_batch,
    furnish_line, schedule_run, sublot, solids_rows, machine_version, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
DIRTY_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 5.00)]


def _lot_of_twenty_two_tons():
    return setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT)


def _approved_twenty_ton_batch():
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    return setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=_lot_of_twenty_two_tons())


def test_a_reject_weight_half_the_charge_is_read_as_an_instrument_fault():
    """PRD §3.3: "Cleaning, `SCREENED → CLEANED`, requires the batch to be in `SCREENED` and
    carries the operator's `measured_reject_tons` — the dry tonnage of screening and cleaning
    rejects weighed at the reject press, at three decimal places and never negative."
    PRD §3.3: "A weight above 40 percent of the batch's `charged_tons` is treated as an
    instrument fault rather than a production result and is rejected with
    `ERR_REJECT_TONS_IMPLAUSIBLE` (HTTP 422); the permitted ceiling is `charged_tons`
    multiplied by 0.40 and the boundary is inclusive, so a weight exactly equal to that
    product is accepted."
    PRD §3.3: "Cleaning stores the value and appends one row to the solids ledger with
    `source_kind` of `PULP_REJECT`, `source_ref_id` pointing at this batch,
    `dry_solids_tons` equal to `measured_reject_tons`, and `disposition` of `PENDING`."

    Design: Corner/errors/a_reject_weight_above_forty_percent_of_the_charge_is_implausible
    """
    declare_tl_140()
    bundle = _lot_of_twenty_two_tons()
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 1.000)])
    validate_success(api_client.start_pulp_batch(batch["id"], OPERATOR))
    validate_success(api_client.screen_pulp_batch(batch["id"], OPERATOR))

    response = api_client.clean_pulp_batch(
        batch["id"], {"measured_reject_tons": 0.500}, OPERATOR)
    validate_error(response, ApiErrorId.ERR_REJECT_TONS_IMPLAUSIBLE.value, 422)

    unfinished = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert unfinished["status"] == "SCREENED"
    assert unfinished["charged_tons"] == pytest.approx(1.000, abs=1e-6)
    assert unfinished["final_accepted_tons"] is None
    assert unfinished["yield_variance_tons"] is None
    assert solids_rows(source_ref_id=batch["id"]) == [], \
        "a refused weighing appends nothing to the solids ledger"


def test_a_healthy_permit_lets_the_pulp_shortfall_speak_for_itself():
    """PRD §3.5: "Fourth, the pulp must actually be there: the referenced batch must be in
    `APPROVED` and its `available_tons` must be at least the run's `pulp_draw_tons`, with the
    boundary inclusive, and a shortfall or an unapproved batch is rejected with
    `ERR_INSUFFICIENT_PULP` (HTTP 409)."
    PRD §3.5: "Second comes the environmental gate: the mill's effluent permit must have a
    `compliance_posture` of `COMPLIANT` or `WATCH`, and a posture of `EXCEEDANCE` blocks every
    run start with `ERR_PERMIT_EXCEEDANCE_BLOCK` (HTTP 409) — this gate is evaluated **before**
    the pulp checks, so a run that is both environmentally blocked and short of pulp reports
    the permit exceedance, while a run that is not in `SCHEDULED` reports the run-state failure
    ahead of the permit."

    Design: Corner/errors/drawing_more_pulp_than_the_batch_holds_is_refused_at_start
    """
    permit = register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = _approved_twenty_ton_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=20.000)

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PULP.value, 409)

    assert get_success_data(api_client.get_effluent_permit(
        permit["id"], OPERATOR))["compliance_posture"] == "COMPLIANT"
    batch = get_success_data(api_client.get_pulp_batch(
        bundle["batch"]["id"], OPERATOR))
    assert batch["available_tons"] == pytest.approx(18.000, abs=1e-6)
    assert batch["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert batch["status"] == "APPROVED"
    assert get_success_data(api_client.get_run(run["id"], PLANNER))["run_status"] \
        == "SCHEDULED"


def test_a_run_cannot_be_booked_for_a_product_the_furnish_was_never_blended_for():
    """PRD §3.4: "The batch's `target_product_code` must equal the run's `product_code`, and a
    mismatch is rejected with `ERR_PRODUCT_MISMATCH` (HTTP 409)."
    PRD §3.4: "Scheduling a run is a planner act that creates the run in `run_status` of
    `SCHEDULED` and `quality_status` of `PENDING`."
    PRD §3.4: "`current_product_code` always names the product of the most recently completed
    run on that machine, and is null while no run has completed there."

    Design: Corner/errors/scheduling_a_run_for_a_product_the_furnish_was_not_blended_for_fails
    """
    declare_tis_16()
    bundle = _approved_twenty_ton_batch()
    machine = register_machine(**PM1)
    version_before = machine_version(machine["id"])

    response = api_client.create_run(
        machine["id"], {"product_code": "TIS_16",
                        "pulp_batch_id": bundle["batch"]["id"],
                        "window_start": "2026-09-01T06:00:00Z",
                        "window_end": "2026-09-01T14:00:00Z",
                        "pulp_draw_tons": 5.000,
                        "expected_machine_version": version_before}, PLANNER)
    validate_error(response, ApiErrorId.ERR_PRODUCT_MISMATCH.value, 409)

    idle = get_success_data(api_client.get_paper_machine(machine["id"], PLANNER))
    assert idle["version"] == version_before, "no run was created, so nothing mutated"
    assert idle["current_product_code"] is None
    assert api_client.list_machine_runs(
        machine["id"], PLANNER).json()["meta"]["total_count"] == 0


def test_a_lot_charged_down_to_nothing_cannot_feed_the_next_pulper_charge():
    """PRD §3.2: "A lot reads `AVAILABLE` while tonnage remains, flips to `DEPLETED` the moment
    `tons_available` reaches exactly 0.000, and reads `QUARANTINED` when the
    supplier-suspension cascade has seized it."
    PRD §3.3: "Every furnish line's lot must resolve — an unresolvable `inventory_lot_id` is
    `ERR_FURNISH_REFERENCE_NOT_FOUND` — and must currently read `AVAILABLE`; a `QUARANTINED` or
    `DEPLETED` lot is rejected with `ERR_LOT_NOT_AVAILABLE` (HTTP 409)."
    PRD §3.3: "As side effects of the charge, each furnish line's `tons_charged` is added into
    its lot's `tons_consumed`, each affected lot's `tons_available` is recomputed, and any lot
    whose recomputed `tons_available` lands on exactly 0.000 flips from `AVAILABLE` to
    `DEPLETED`."

    Design: Corner/errors/a_depleted_lot_cannot_be_charged_into_a_new_furnish
    """
    declare_tl_140()
    bundle = _lot_of_twenty_two_tons()
    lot_id = bundle["lot"]["id"]
    whole_lot = queue_batch("TL_140", [furnish_line(lot_id, 22.000)])
    leftovers = queue_batch("TL_140", [furnish_line(lot_id, 0.500)])
    validate_success(api_client.start_pulp_batch(whole_lot["id"], OPERATOR))
    spent = get_success_data(api_client.get_inventory_lot(lot_id, OPERATOR))
    assert spent["status"] == "DEPLETED"
    assert spent["tons_available"] == pytest.approx(0.000, abs=1e-6)

    response = api_client.start_pulp_batch(leftovers["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_LOT_NOT_AVAILABLE.value, 409)

    stuck = get_success_data(api_client.get_pulp_batch(leftovers["id"], OPERATOR))
    assert stuck["status"] == "QUEUED"
    assert stuck["provisional_accepted_tons"] is None, \
        "the availability gate fires before any tonnage arithmetic"


def test_a_truck_measured_above_its_grade_ceiling_may_not_be_accepted():
    """PRD §3.2: "**Accepting** is permitted only when `weighted_contamination_pct` is no
    greater than the declared grade's `max_contamination_pct` — the boundary is inclusive, so a
    truck exactly at the limit is clean enough — and only when the parent purchase order is in
    `CONFIRMED` or `PARTIALLY_RECEIVED`."
    PRD §3.2: "A requested disposition that contradicts the measured results is rejected with
    `ERR_DISPOSITION_NOT_PERMITTED` (HTTP 409)."
    PRD §3.2: "The supplier's `contamination_strike_count` is left untouched — a clean truck
    costs the supplier nothing."

    Design: Corner/errors/accepting_a_truck_above_its_grade_ceiling_is_not_a_permitted_disposition
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             negotiated_delta_per_ton=5.00)
    receipt = record_receipt(po["id"], DIRTY_TRUCK, truck_reference="TRK-0001",
                             sampler_headers=SAMPLER)

    response = api_client.disposition_receipt(
        receipt["id"], {"disposition": "ACCEPT"}, DISPOSER)
    validate_error(response, ApiErrorId.ERR_DISPOSITION_NOT_PERMITTED.value, 409)

    undecided = get_success_data(api_client.get_receipt(receipt["id"], DISPOSER))
    assert undecided["status"] == "SAMPLED"
    assert undecided["weighted_contamination_pct"] == pytest.approx(5.00, abs=1e-6)
    assert undecided["dispositioned_by_user_id"] is None
    unblemished = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert unblemished["contamination_strike_count"] == 0
    assert unblemished["qualification_status"] == "QUALIFIED"
    unfilled = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert unfilled["received_net_tons"] == pytest.approx(0.00, abs=1e-6)
    assert unfilled["status"] == "CONFIRMED"
