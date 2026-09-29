"""Three places where the mill must read exactly the right number: the hold cascade that
reaches no order, the pulp gate that consults the weighed variant, and the strike ladder
that flips posture only at the declared counts.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, publish_quote, register_supplier,
    register_customer, register_machine, register_permit, create_confirmed_po,
    record_receipt, disposition, lots_of_receipt, setup_available_lot,
    setup_approved_batch, schedule_run, start_run, complete_run, wind_roll_set,
    wrap_roll_set, submit_order, schedule_order, order_version, reel_reading,
    sublot, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
CLEAN_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
DIRTY_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 5.00)]
ONE_WET_REEL_IN_THE_MIDDLE = [reel_reading(1, 5.000, 140.0, 7.50, 2.60),
                              reel_reading(2, 5.000, 140.0, 9.00, 2.60),
                              reel_reading(3, 5.000, 140.0, 7.50, 2.60)]


def _twenty_ton_batch_at_two_percent():
    return setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000,
        lot_bundle=setup_available_lot(sublots_list=CLEAN_TRUCK))


def test_holding_the_run_quarantines_the_wrapped_roll_and_leaves_the_order_alone():
    """PRD §3.5: "Hop one flips every roll set of the run whose status is `WOUND`, `WRAPPED`
    or `ALLOCATED` to `QUARANTINED`, setting `quarantine_reason` to `RUN_HELD` and clearing
    `allocated_order_id`. Hop two makes each customer order that lost rolls in hop one
    recompute its `allocated_tons` and `shortfall_tons`. Hop three drops each such order that
    had reached `ALLOCATED` and whose recomputed `allocated_tons` is now below its
    `ordered_tons` back to `PARTIALLY_ALLOCATED`, incrementing that order's `version`."
    PRD §3.5: "It also computes and stores `certified_quality_index` — the number is struck
    whichever way the verdict goes."
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

    Design: Corner/cross_cutting_complexity_layers/a_quality_hold_quarantines_wrapped_rolls_but_reaches_no_order
    """
    set_clock("2026-08-01T00:00:00Z")
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = _twenty_ton_batch_at_two_percent()
    customer = register_customer(name="Great Lakes Converting",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=6.00, roll_width_mm=2200,
                         roll_diameter_mm=1300, wrap_spec="KRAFT_ONLY")
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z", pulp_draw_tons=15.000)
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1200,
                             roll_count=8, net_tons=6.000)
    complete_run(machine["id"], run["id"], ONE_WET_REEL_IN_THE_MIDDLE, 0.000)
    wrap_roll_set(roll_set["id"], "KRAFT_ONLY")

    held = validate_success(api_client.hold_run(machine["id"], run["id"], CERTIFIER))

    assert held["quality_status"] == "HELD"
    assert held["off_spec_reel_count"] == 1
    assert held["certified_quality_index"] is not None
    assert held["run_status"] == "COMPLETED", "the two axes move independently"
    quarantined = get_success_data(api_client.get_roll_set(roll_set["id"], CERTIFIER))
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_reason"] == "RUN_HELD"
    assert quarantined["allocated_order_id"] is None
    untouched = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert untouched["status"] == "IN_PRODUCTION", \
        "no order ever held these rolls, so hops two and three find nothing"
    assert untouched["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert untouched["shortfall_tons"] == pytest.approx(6.000, abs=1e-6)

    response = api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": order_version(order["id"])},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_ROLL_SET_INVALID_STATE.value, 409)


def test_the_pulp_draw_gate_reads_the_weighed_tonnage_not_the_book_projection():
    """PRD §3.5: "Fourth, the pulp must actually be there: the referenced batch must be in
    `APPROVED` and its `available_tons` must be at least the run's `pulp_draw_tons`, with the
    boundary inclusive, and a shortfall or an unapproved batch is rejected with
    `ERR_INSUFFICIENT_PULP` (HTTP 409)."
    PRD §3.3: "`available_tons` is `final_accepted_tons` minus `consumed_tons` rounded to
    three decimal places while the batch is `APPROVED`, and reads 0.000 in every other status;
    at the instant of approval `consumed_tons` is still 0.000, so `available_tons` opens equal
    to `final_accepted_tons`."
    PRD §3.3: "The two yield figures are deliberately kept side by side: the provisional
    number is a projection from grade book yields discounted for contamination, the final
    number is physical weight subtraction, they differ for identical furnish, and nothing in
    this system ever reconciles them back together."
    PRD §3.5: "The run's `pulp_draw_tons` is added into the batch's `consumed_tons` and the
    batch's `available_tons` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/the_pulp_draw_gate_reads_the_final_variant_not_the_book_projection
    """
    set_clock("2026-08-01T00:00:00Z")
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    spare = register_machine(name="PM3", wire_width_mm=5600, max_tons_per_hour=20.00,
                             changeover_buffer_minutes=30, steam_tph_per_ton=2.500)
    bundle = _twenty_ton_batch_at_two_percent()
    batch_id = bundle["batch"]["id"]
    before = get_success_data(api_client.get_pulp_batch(batch_id, OPERATOR))
    assert before["provisional_accepted_tons"] == pytest.approx(16.880, abs=1e-6)
    assert before["final_accepted_tons"] == pytest.approx(18.000, abs=1e-6)
    assert before["yield_variance_tons"] == pytest.approx(1.120, abs=1e-6)
    assert before["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert before["available_tons"] == pytest.approx(18.000, abs=1e-6)
    run = schedule_run(machine["id"], "TL_140", batch_id,
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z", pulp_draw_tons=17.500)
    sibling = schedule_run(spare["id"], "TL_140", batch_id,
                           window_start="2026-09-01T06:00:00Z",
                           window_end="2026-09-01T14:00:00Z", pulp_draw_tons=0.600)

    started = validate_success(api_client.start_run(machine["id"], run["id"], OPERATOR))

    assert started["run_status"] == "RUNNING", \
        "17.500 tons sits above the book projection but inside the weighed tonnage"
    drawn = get_success_data(api_client.get_pulp_batch(batch_id, OPERATOR))
    assert drawn["consumed_tons"] == pytest.approx(17.500, abs=1e-6)
    assert drawn["available_tons"] == pytest.approx(0.500, abs=1e-6)
    assert drawn["provisional_accepted_tons"] == pytest.approx(16.880, abs=1e-6), \
        "the projection is never reconciled against the draw"

    response = api_client.start_run(spare["id"], sibling["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PULP.value, 409)

    assert get_success_data(api_client.get_run(
        sibling["id"], PLANNER))["run_status"] == "SCHEDULED"
    assert get_success_data(api_client.get_pulp_batch(
        batch_id, OPERATOR))["consumed_tons"] == pytest.approx(17.500, abs=1e-6)


def test_the_strike_ladder_flips_posture_only_at_two_and_at_four():
    """PRD §3.2: "Four or more strikes makes the supplier `SUSPENDED`; two or three strikes
    makes it `PROBATION`; anything below two leaves it `QUALIFIED`."
    PRD §3.2: "Hop one increments `contamination_strike_count` by one and re-derives
    `qualification_status` from the strike count, where the count is the number of fiber
    receipts of this supplier, across every purchase order, whose status is `DOWNGRADED` or
    `REJECTED` **and** whose `dispositioned_by_user_id` is set."
    PRD §3.2: "Acceptance sets `accepted_grade_code` equal to `declared_grade_code` and
    creates exactly one fiber inventory lot whose `grade_code` is that accepted grade, whose
    `tons_received` is the receipt's `net_tons`, whose `contamination_pct` is copied from the
    receipt's `weighted_contamination_pct`, and whose lot `status` is `AVAILABLE`."
    PRD §3.2: "The supplier's `contamination_strike_count` is left untouched — a clean truck
    costs the supplier nothing."

    Design: Corner/cross_cutting_complexity_layers/the_strike_ladder_flips_posture_only_at_the_declared_counts
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, downgrade_target_grade_code=None,
                        rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             negotiated_delta_per_ton=5.00)
    ladder = {1: "QUALIFIED", 2: "PROBATION", 3: "PROBATION", 4: "SUSPENDED"}
    for strike in (1, 2, 3, 4):
        truck = record_receipt(po["id"], DIRTY_TRUCK,
                               truck_reference="TRK-000%d" % strike,
                               sampler_headers=SAMPLER)

        rejected = disposition(truck["id"], "REJECT", headers=DISPOSER)

        assert rejected["status"] == "REJECTED"
        rung = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
        assert rung["contamination_strike_count"] == strike
        assert rung["qualification_status"] == ladder[strike], \
            "the posture may only change at the declared counts"

    clean = record_receipt(po["id"], CLEAN_TRUCK, truck_reference="TRK-0005",
                           sampler_headers=SAMPLER)
    accepted = disposition(clean["id"], "ACCEPT", headers=DISPOSER)

    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_grade_code"] == "OCC_11"
    lots = lots_of_receipt(clean["id"])
    assert len(lots) == 1
    assert lots[0]["status"] == "AVAILABLE", \
        "the quarantine sweep fires on the transition into suspension, not forever after"
    assert lots[0]["tons_available"] == pytest.approx(22.000, abs=1e-6)
    unchanged = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert unchanged["contamination_strike_count"] == 4, "the counter never decays"
    assert unchanged["qualification_status"] == "SUSPENDED"
