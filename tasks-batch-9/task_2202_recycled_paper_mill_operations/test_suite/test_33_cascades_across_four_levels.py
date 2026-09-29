"""Two long cascades fired by a single call: the fourth contamination strike unwinding
supplier, lot, batch, run and order; and an exceedance posture voiding the land
application manifest while leaving the landfill one alone.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, publish_quote, register_supplier,
    register_customer, register_machine, register_permit, create_confirmed_po,
    record_receipt, disposition, lots_of_receipt, queue_batch, furnish_line,
    setup_available_lot, setup_approved_batch, schedule_run, submit_order,
    schedule_order, order_version, log_reading, prepare_manifest, solids_rows,
    solids_summary, sublot, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_LOGGER = TEST_USERS["env_logger_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
CLEAN_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
DIRTY_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 5.00)]


def test_the_fourth_contamination_strike_unwinds_four_levels_of_commitment():
    """PRD §3.2: "Four or more strikes makes the supplier `SUSPENDED`; two or three strikes
    makes it `PROBATION`; anything below two leaves it `QUALIFIED`."
    PRD §3.2: "Hop two fires only when hop one has just made the supplier `SUSPENDED`: every
    fiber inventory lot whose receipt chain resolves to this supplier and whose status is
    `AVAILABLE` flips to `QUARANTINED`, including the lot created moments earlier by a
    downgrade. Hop three follows from hop two: every pulp batch still in `QUEUED` that holds
    a furnish line pointing at any lot quarantined in hop two flips to `CANCELLED`, releasing
    its reservation so those lots' `tons_consumed` fall back. Hop four follows from hop
    three: every production run whose `run_status` is `SCHEDULED` and whose `pulp_batch_id`
    is one of the batches cancelled in hop three has its `run_status` set to `ABORTED` and
    its `quality_status` set to `CONDEMNED`, and each customer order sequenced onto such a
    run returns from `SCHEDULED` to `SUBMITTED` with its `deschedule_count` incremented."
    PRD §3.2: "Every row touched by any hop of this cascade has its `updated_at` refreshed
    and its `version` bumped, so a client holding a pre-cascade read of a machine, an order,
    or a batch will find its version checks failing — which is the intended serialisation
    point."

    Design: Corner/cross_cutting_complexity_layers/the_fourth_contamination_strike_unwinds_four_levels_of_downstream_commitment
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_tl_140()
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, downgrade_target_grade_code=None,
                        rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             negotiated_delta_per_ton=5.00)
    clean = record_receipt(po["id"], CLEAN_TRUCK, truck_reference="TRK-0001")
    disposition(clean["id"], "ACCEPT")
    lot = lots_of_receipt(clean["id"])[0]
    for reference in ("TRK-0002", "TRK-0003", "TRK-0004"):
        struck = record_receipt(po["id"], DIRTY_TRUCK, truck_reference=reference)
        disposition(struck["id"], "REJECT")
    machine = register_machine(**PM1)
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 20.000)])
    run = schedule_run(machine["id"], "TL_140", batch["id"], pulp_draw_tons=15.000)
    customer = register_customer(name="Great Lakes Converting",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=6.00, roll_width_mm=2200,
                         roll_diameter_mm=1300, wrap_spec="KRAFT_ONLY")
    schedule_order(order["id"], run["id"])
    version_before_the_cascade = order_version(order["id"])
    on_probation = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert on_probation["contamination_strike_count"] == 3
    assert on_probation["qualification_status"] == "PROBATION", \
        "three strikes cascade nothing"
    assert get_success_data(api_client.get_inventory_lot(
        lot["id"], OPERATOR))["status"] == "AVAILABLE"
    assert get_success_data(api_client.get_pulp_batch(
        batch["id"], OPERATOR))["status"] == "QUEUED"
    assert get_success_data(api_client.get_run(run["id"], PLANNER))["run_status"] \
        == "SCHEDULED"
    last_straw = record_receipt(po["id"], DIRTY_TRUCK, truck_reference="TRK-0005")

    rejected = disposition(last_straw["id"], "REJECT")

    assert rejected["status"] == "REJECTED"
    assert rejected["accepted_grade_code"] is None
    suspended = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert suspended["contamination_strike_count"] == 4
    assert suspended["qualification_status"] == "SUSPENDED"
    quarantined = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["tons_consumed"] == pytest.approx(0.000, abs=1e-6)
    assert quarantined["tons_available"] == pytest.approx(22.000, abs=1e-6), \
        "the reservation was released, not stranded"
    assert get_success_data(api_client.get_pulp_batch(
        batch["id"], OPERATOR))["status"] == "CANCELLED"
    aborted = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert aborted["run_status"] == "ABORTED"
    assert aborted["quality_status"] == "CONDEMNED"
    unsequenced = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert unsequenced["status"] == "SUBMITTED"
    assert unsequenced["scheduled_run_id"] is None
    assert unsequenced["deschedule_count"] == 1
    assert unsequenced["version"] > version_before_the_cascade
    assert get_success_data(api_client.get_purchase_order(
        po["id"], BUYER))["received_net_tons"] == pytest.approx(22.00, abs=1e-6), \
        "a rejection adds no tonnage and the cascade removes none"


def test_one_bad_discharge_day_voids_the_land_application_claim_only():
    """PRD §3.7: "`WATCH → EXCEEDANCE` and `COMPLIANT → EXCEEDANCE` both fire when the
    recomputation yields `EXCEEDANCE` — a single bad reading can jump straight from
    `COMPLIANT` without resting in `WATCH` — and both carry the same three-hop cascade. Hop
    one voids every sludge manifest that is in `DRAFT` with a `destination` of
    `LAND_APPLICATION`, flipping it to `VOIDED`. Hop two clears `manifest_id` on every solids
    row whose `manifest_id` pointed at a manifest voided in hop one and returns that row's
    `disposition` to `PENDING`. Hop three puts those rows back into the unmanifested pool, so
    the mill-wide `unmanifested_dry_solids_tons` figure rises by exactly the total dry solids
    of the voided manifests."
    PRD §3.7: "Preparing a `LAND_APPLICATION` manifest while the permit posture is
    `EXCEEDANCE` is rejected with `ERR_LAND_APPLICATION_BARRED` (HTTP 409), and so is signing
    one."
    PRD §3.7: "`exceedance_day_count` is the number of readings inside the window whose
    `flow_m3` is strictly greater than the permit's `flow_limit_m3_per_day`."

    Design: Corner/cross_cutting_complexity_layers/an_exceedance_posture_voids_land_application_manifests_and_returns_their_solids
    """
    set_clock("2026-08-01T00:00:00Z")
    permit = register_permit(**MILL_PERMIT)
    big = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000,
        lot_bundle=setup_available_lot(sublots_list=CLEAN_TRUCK))
    small = setup_approved_batch(
        tons_charged=3.000, measured_reject_tons=0.300, declare_spec=False,
        lot_bundle=setup_available_lot(
            sublots_list=[sublot(1, 6.000, 2.000, 10.00, 2.00)], declare_grades=False,
            publish_index=False, supplier_name="Cypress Fiber Yard"))
    big_row = solids_rows(source_ref_id=big["batch"]["id"],
                          source_kind="PULP_REJECT")[0]
    small_row = solids_rows(source_ref_id=small["batch"]["id"],
                            source_kind="PULP_REJECT")[0]
    to_the_fields = prepare_manifest([big_row["id"]], manifest_number="MAN-LAND-1",
                                     destination="LAND_APPLICATION")
    to_the_landfill = prepare_manifest([small_row["id"]],
                                       manifest_number="MAN-FILL-1",
                                       destination="LANDFILL")

    validate_success(api_client.create_effluent_reading(
        permit["id"], {"reading_date": "2026-08-01", "flow_m3": 12000.00,
                       "bod_kg": 600.00, "tss_kg": 100.00}, ENV_LOGGER), 201)

    breached = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert breached["rolling_bod_kg_per_day"] == pytest.approx(600.000, abs=1e-6)
    assert breached["rolling_tss_kg_per_day"] == pytest.approx(100.000, abs=1e-6)
    assert breached["exceedance_day_count"] == 1
    assert breached["compliance_posture"] == "EXCEEDANCE", \
        "the BOD ratio alone jumps the posture without resting in WATCH"
    assert get_success_data(api_client.get_sludge_manifest(
        to_the_fields["id"], ENV))["status"] == "VOIDED"
    untouched = get_success_data(api_client.get_sludge_manifest(
        to_the_landfill["id"], ENV))
    assert untouched["status"] == "DRAFT", "hop one is conditional on the destination"
    assert untouched["total_dry_solids_tons"] == pytest.approx(0.300, abs=1e-6)
    returned = get_success_data(api_client.get_reject_stream(big_row["id"], ENV))
    assert returned["disposition"] == "PENDING"
    assert returned["manifest_id"] is None
    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(2.300, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(2.300, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(2.300, abs=1e-6)

    barred = api_client.create_sludge_manifest(
        {"manifest_number": "MAN-LAND-2", "destination": "LAND_APPLICATION",
         "reject_stream_ids": [big_row["id"]]}, ENV_PREPARER)
    validate_error(barred, ApiErrorId.ERR_LAND_APPLICATION_BARRED.value, 409)
