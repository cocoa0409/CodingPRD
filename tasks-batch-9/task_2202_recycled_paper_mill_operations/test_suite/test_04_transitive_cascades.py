"""Cascades that reach three or four entity kinds away from the request: a truck
disposition that deschedules a customer order, a quality condemnation that lands in
the solids ledger, and a pulp diversion that frees machine time.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, ApiErrorId,
    declare_standard_grades, declare_fiber_grade, declare_tl_140, declare_tis_16,
    publish_quote, register_supplier, register_customer, register_machine,
    register_permit, create_confirmed_po, record_receipt, disposition,
    lots_of_receipt, queue_batch, schedule_run, start_run, complete_run,
    submit_order, schedule_order, wind_roll_set, wrap_roll_set, machine_version,
    setup_batch_at_deink_hold, setup_approved_batch, solids_rows, solids_summary,
    reel_reading, sublot, _paginated, TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
OPERATOR = TEST_USERS["operator_headers"]

MILL_PERMIT = {"permit_number": "MILL-NPDES-01", "bod_limit_kg_per_day": 100.00,
               "tss_limit_kg_per_day": 200.00, "flow_limit_m3_per_day": 5000.00,
               "rolling_window_days": 7}
PM1 = {"name": "PM1", "wire_width_mm": 4200, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.400}
OFF_SPEC_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.50),
                  reel_reading(2, 5.000, 155.0, 7.50, 2.50)]


def _supplier_three_strikes_with_scheduled_chain():
    """Riverbend on 3 strikes, holding an AVAILABLE OCC_11 lot that a QUEUED batch,
    a SCHEDULED run and a SCHEDULED order all depend on."""
    declare_standard_grades()
    declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                        max_contamination_pct=2.00, max_moisture_pct=10.00,
                        nominal_yield_pct=72.00, deink_required=True,
                        downgrade_target_grade_code=None, rank_order=3)
    declare_tl_140()
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    publish_quote(index_symbol="PPI_DLK", effective_month="2026-07",
                  published_price_per_ton=150.00)
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    customer = register_customer(name="Boxworks Packaging",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1500, max_roll_width_mm=2200,
                                 wrap_spec="POLY_COATED")
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=22.00)
    po_occ = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=300.00,
                                 index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                                 negotiated_delta_per_ton=0.00)
    po_dlk = create_confirmed_po(supplier["id"], "DLK_37", contracted_tons=300.00,
                                 index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                                 negotiated_delta_per_ton=0.00)
    clean = record_receipt(po_occ["id"], [sublot(1, 30.000, 2.000, 10.00, 2.50)],
                           "TRK-S-001")
    disposition(clean["id"], "ACCEPT")
    lot = lots_of_receipt(clean["id"])[0]
    for ref in ("TRK-S-002", "TRK-S-003", "TRK-S-004"):
        dirty = record_receipt(po_dlk["id"], [sublot(1, 6.000, 1.000, 8.00, 4.00)], ref)
        disposition(dirty["id"], "REJECT")
    batch = queue_batch("TL_140", [{"inventory_lot_id": lot["id"], "tons_charged": 20.000}])
    run = schedule_run(machine["id"], "TL_140", batch["id"],
                       window_start="2026-08-05T00:00:00Z",
                       window_end="2026-08-05T06:00:00Z", pulp_draw_tons=20.000)
    order = submit_order(customer, "TL_140", ordered_tons=15.00,
                         requested_ship_date="2026-08-20", roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="POLY_COATED")
    schedule_order(order["id"], run["id"])
    return {"supplier": supplier, "po_occ": po_occ, "lot": lot, "batch": batch,
            "run": run, "order": order, "machine": machine}


def test_fourth_strike_suspends_the_supplier_and_quarantines_all_its_lots():
    """PRD §3.2: "Four or more strikes makes the supplier `SUSPENDED`; two or three
    strikes makes it `PROBATION`; anything below two leaves it `QUALIFIED`."
    PRD §3.2: "Hop two fires only when hop one has just made the supplier
    `SUSPENDED`: every fiber inventory lot whose receipt chain resolves to this
    supplier and whose status is `AVAILABLE` flips to `QUARANTINED`, including the lot
    created moments earlier by a downgrade."

    Design: Difficulty/transitive_cascade/supplier_suspension_four_hop_cascade_via_downgrade_disposition
    """
    ctx = _supplier_three_strikes_with_scheduled_chain()
    before = get_success_data(api_client.get_supplier(ctx["supplier"]["id"], BUYER))
    assert before["contamination_strike_count"] == 3
    assert before["qualification_status"] == "PROBATION"

    fourth = record_receipt(ctx["po_occ"]["id"],
                            [sublot(1, 12.000, 2.000, 11.00, 4.50)], "TRK-S-005")
    downgraded = validate_success(api_client.disposition_receipt(
        fourth["id"], {"disposition": "DOWNGRADE"},
        TEST_USERS["lab_dispo_headers"]))

    assert downgraded["status"] == "DOWNGRADED"
    assert downgraded["net_tons"] == pytest.approx(10.00, abs=1e-6)
    assert downgraded["weighted_contamination_pct"] == pytest.approx(4.50, abs=1e-6)
    assert downgraded["accepted_grade_code"] == "MIX_54"

    sup = get_success_data(api_client.get_supplier(ctx["supplier"]["id"], BUYER))
    assert sup["contamination_strike_count"] == 4
    assert sup["qualification_status"] == "SUSPENDED"

    lot = get_success_data(api_client.get_inventory_lot(ctx["lot"]["id"], OPERATOR))
    assert lot["status"] == "QUARANTINED", "the pre-existing OCC_11 lot is seized"
    mix_lots, mix_meta = _paginated(api_client.list_inventory_lots(
        OPERATOR, {"grade_code": "MIX_54"}))
    assert mix_meta["total_count"] == 1
    assert mix_lots[0]["status"] == "QUARANTINED", \
        "the lot minted by this very disposition is caught too"
    _, avail_meta = _paginated(api_client.list_inventory_lots(
        OPERATOR, {"status": "AVAILABLE"}))
    assert avail_meta["total_count"] == 0


def test_suspension_cancels_the_queued_batch_and_deschedules_the_customer_order():
    """PRD §3.2: "Hop three follows from hop two: every pulp batch still in `QUEUED`
    that holds a furnish line pointing at any lot quarantined in hop two flips to
    `CANCELLED`, releasing its reservation so those lots' `tons_consumed` fall back."
    PRD §3.2: "Hop four follows from hop three: every production run whose
    `run_status` is `SCHEDULED` and whose `pulp_batch_id` is one of the batches
    cancelled in hop three has its `run_status` set to `ABORTED` and its
    `quality_status` set to `CONDEMNED`, and each customer order sequenced onto such a
    run returns from `SCHEDULED` to `SUBMITTED` with its `deschedule_count`
    incremented."

    Design: Difficulty/transitive_cascade/supplier_suspension_four_hop_cascade_via_downgrade_disposition
    """
    ctx = _supplier_three_strikes_with_scheduled_chain()
    fourth = record_receipt(ctx["po_occ"]["id"],
                            [sublot(1, 12.000, 2.000, 11.00, 4.50)], "TRK-S-005")
    disposition(fourth["id"], "DOWNGRADE")

    batch = get_success_data(api_client.get_pulp_batch(ctx["batch"]["id"], OPERATOR))
    assert batch["status"] == "CANCELLED"
    lot = get_success_data(api_client.get_inventory_lot(ctx["lot"]["id"], OPERATOR))
    assert lot["tons_consumed"] == pytest.approx(0.000, abs=1e-6), \
        "cancelling the batch releases its furnish reservation"
    assert lot["tons_available"] == pytest.approx(28.000, abs=1e-6)

    run = get_success_data(api_client.get_run(ctx["run"]["id"], PLANNER))
    assert run["run_status"] == "ABORTED"
    assert run["quality_status"] == "CONDEMNED"

    order = get_success_data(api_client.get_customer_order(ctx["order"]["id"], PLANNER))
    assert order["status"] == "SUBMITTED", \
        "a truck disposition reached the customer's order four hops away"
    assert order["scheduled_run_id"] is None
    assert order["deschedule_count"] == 1


def _held_run_with_two_wrapped_sets():
    bundle = setup_approved_batch()
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-08-02T00:00:00Z",
                       window_end="2026-08-02T06:00:00Z", pulp_draw_tons=20.000)
    start_run(machine["id"], run["id"])
    rs1 = wind_roll_set(run["id"], slit_width_mm=2000, diameter_mm=1200,
                        roll_count=3, net_tons=6.000)
    rs2 = wind_roll_set(run["id"], slit_width_mm=2000, diameter_mm=1200,
                        roll_count=2, net_tons=4.000)
    complete_run(machine["id"], run["id"], OFF_SPEC_REELS)
    wrap_roll_set(rs1["id"], "POLY_COATED")
    wrap_roll_set(rs2["id"], "POLY_COATED")
    held = validate_success(api_client.hold_run(machine["id"], run["id"], CERTIFIER))
    return {"machine": machine, "run": held, "rs1": rs1, "rs2": rs2,
            "batch": bundle["batch"]}


def test_quality_hold_quarantines_the_wrapped_sets_before_condemnation():
    """PRD §3.5: "Hop one flips every roll set of the run whose status is `WOUND`,
    `WRAPPED` or `ALLOCATED` to `QUARANTINED`, setting `quarantine_reason` to
    `RUN_HELD` and clearing `allocated_order_id`."

    Design: Difficulty/transitive_cascade/run_condemn_cascade_scraps_rolls_into_solids_ledger
    """
    ctx = _held_run_with_two_wrapped_sets()

    for key in ("rs1", "rs2"):
        rs = get_success_data(api_client.get_roll_set(ctx[key]["id"], OPERATOR))
        assert rs["status"] == "QUARANTINED"
        assert rs["quarantine_reason"] == "RUN_HELD"
    assert ctx["run"]["quality_status"] == "HELD"


def test_condemnation_scraps_every_set_into_machine_broke_solids_rows():
    """PRD §3.5: "Condemnation, `HELD → CONDEMNED`, also requires the quality axis to
    read `HELD`; it flips every roll set of the run in `QUARANTINED`, `REWOUND`,
    `WOUND` or `WRAPPED` to `SCRAPPED`, appending for each one a solids-ledger row
    with `source_kind` of `MACHINE_BROKE`, `source_ref_id` pointing at the run and
    `dry_solids_tons` equal to that set's `net_tons`, and it recomputes the run's
    `produced_tons` to 0.000."

    Design: Difficulty/transitive_cascade/run_condemn_cascade_scraps_rolls_into_solids_ledger
    """
    ctx = _held_run_with_two_wrapped_sets()

    condemned = validate_success(api_client.condemn_run(
        ctx["machine"]["id"], ctx["run"]["id"], PLANNER))

    assert condemned["quality_status"] == "CONDEMNED"
    assert condemned["run_status"] == "COMPLETED", "condemnation is a quality-axis act"
    assert condemned["produced_tons"] == pytest.approx(0.000, abs=1e-6)
    for key in ("rs1", "rs2"):
        rs = get_success_data(api_client.get_roll_set(ctx[key]["id"], OPERATOR))
        assert rs["status"] == "SCRAPPED"
    rows = solids_rows(source_ref_id=ctx["run"]["id"], source_kind="MACHINE_BROKE")
    assert sorted(r["dry_solids_tons"] for r in rows) == pytest.approx([4.000, 6.000], abs=1e-6), \
        f"one row per scrapped set at that set's net_tons, got {[r['dry_solids_tons'] for r in rows]}"


def test_condemned_tonnage_lands_unmanifested_in_the_mill_solids_summary():
    """PRD §2.9: "The solids ledger reports `gross_solids_tons` (the sum of
    `dry_solids_tons` over rows that are not reversals, to 3 decimal places),
    `reversed_solids_tons` (the same sum over rows that *are* reversals),
    `net_solids_tons` (gross minus reversed, to 3 decimal places), and three
    disposition splits over non-reversal rows: `manifested_dry_solids_tons` for rows
    whose disposition is `MANIFESTED`, `unmanifested_dry_solids_tons` for rows whose
    disposition is `PENDING`, and `repulped_dry_solids_tons` for rows whose
    disposition is `REPULPED`."

    Design: Difficulty/transitive_cascade/run_condemn_cascade_scraps_rolls_into_solids_ledger
    """
    ctx = _held_run_with_two_wrapped_sets()
    api_client.condemn_run(ctx["machine"]["id"], ctx["run"]["id"], PLANNER)

    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(14.500, abs=1e-6), \
        f"4.500 of pulp reject plus 6.000 and 4.000 of broke, got {summary['gross_solids_tons']}"
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(14.500, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(14.500, abs=1e-6)


def _deink_batch_with_scheduled_run_and_order():
    bundle = setup_batch_at_deink_hold(failing_brightness=70.0)
    machine = register_machine(name="PM2", wire_width_mm=2800,
                               max_tons_per_hour=12.00,
                               changeover_buffer_minutes=30,
                               steam_tph_per_ton=1.200)
    run = schedule_run(machine["id"], "TIS_16", bundle["batch"]["id"],
                       window_start="2026-08-06T00:00:00Z",
                       window_end="2026-08-06T06:00:00Z", pulp_draw_tons=10.000)
    customer = register_customer(name="Softline Tissue",
                                 allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2200,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TIS_16", ordered_tons=8.00,
                         requested_ship_date="2026-08-22", roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="KRAFT_ONLY")
    schedule_order(order["id"], run["id"])
    return {"batch": bundle["batch"], "machine": machine, "run": run, "order": order}


def test_diverting_a_held_batch_zeroes_it_and_deschedules_downstream_work():
    """PRD §3.3: "A batch that cannot be brought to brightness is written off
    instead: a `MillPlanner` diverts it, `DEINK_HOLD → DIVERTED`, which requires the
    batch to be in `DEINK_HOLD` and sets both `final_accepted_tons` and
    `available_tons` to 0.000."
    PRD §3.3: "Hop three recomputes each such order's `shortfall_tons` as its
    `ordered_tons` minus its `allocated_tons`, floored at zero and rounded to three
    decimal places, and releases the aborted run's window on the paper machine so the
    machine's occupancy interval no longer blocks new scheduling."

    Design: Difficulty/transitive_cascade/pulp_divert_cascade_frees_machine_window_through_order_deschedule
    """
    ctx = _deink_batch_with_scheduled_run_and_order()

    diverted = validate_success(api_client.divert_pulp_batch(ctx["batch"]["id"], PLANNER))

    assert diverted["status"] == "DIVERTED"
    assert diverted["final_accepted_tons"] == pytest.approx(0.000, abs=1e-6)
    assert diverted["available_tons"] == pytest.approx(0.000, abs=1e-6)

    run = get_success_data(api_client.get_run(ctx["run"]["id"], PLANNER))
    assert run["run_status"] == "ABORTED" and run["quality_status"] == "CONDEMNED"

    order = get_success_data(api_client.get_customer_order(ctx["order"]["id"], PLANNER))
    assert order["status"] == "SUBMITTED"
    assert order["scheduled_run_id"] is None
    assert order["deschedule_count"] == 1
    assert order["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert order["shortfall_tons"] == pytest.approx(8.00, abs=1e-6)


def test_the_aborted_run_no_longer_occupies_its_window_on_the_machine():
    """PRD §3.4: "The requested window, extended earlier by
    `changeover_buffer_minutes` and later by the same amount, must not intersect the
    unwidened closed window of any other run on the same machine whose `run_status` is
    `SCHEDULED` or `RUNNING`."
    PRD §3.3: "Hop three recomputes each such order's `shortfall_tons` as its
    `ordered_tons` minus its `allocated_tons`, floored at zero and rounded to three
    decimal places, and releases the aborted run's window on the paper machine so the
    machine's occupancy interval no longer blocks new scheduling."

    Design: Difficulty/transitive_cascade/pulp_divert_cascade_frees_machine_window_through_order_deschedule
    """
    ctx = _deink_batch_with_scheduled_run_and_order()
    api_client.divert_pulp_batch(ctx["batch"]["id"], PLANNER)

    replacement = validate_success(api_client.create_run(
        ctx["machine"]["id"],
        {"product_code": "TIS_16", "pulp_batch_id": ctx["batch"]["id"],
         "window_start": "2026-08-06T00:00:00Z",
         "window_end": "2026-08-06T06:00:00Z", "pulp_draw_tons": 10.000,
         "expected_machine_version": machine_version(ctx["machine"]["id"])},
        PLANNER), expected_status=201)

    assert replacement["run_status"] == "SCHEDULED", \
        "the byte-identical window is free again once the run is aborted"
    assert replacement["id"] != ctx["run"]["id"]
