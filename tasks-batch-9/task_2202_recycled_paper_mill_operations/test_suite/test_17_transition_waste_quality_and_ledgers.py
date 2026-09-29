"""Numbers struck at the turn of the machine: transition waste and its clamp, the two
quality indexes off one set of reels, the order allocation ledger, and the strike ladder.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    declare_fiber_grade, declare_paper_grade_spec, declare_tl_140, declare_tis_16,
    publish_quote, register_supplier, register_machine, register_permit,
    register_customer, create_confirmed_po, record_receipt, disposition, sublot,
    setup_available_lot, setup_approved_batch, schedule_run, start_run,
    complete_run_payload, reel_reading, ON_SPEC_REELS_TL_140, machine_version,
    wind_roll_set, wrap_roll_set, submit_order, schedule_order, allocate_roll_set,
    set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
DIRTY_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 5.00)]
THREE_REELS = [reel_reading(1, 2.000, 141.0, 7.50, 2.60),
               reel_reading(2, 11.000, 140.0, 7.50, 2.60),
               reel_reading(3, 2.000, 140.6, 8.06, 2.60)]


def _two_scheduled_runs(machine, from_product, to_product, second_start, second_end):
    """One outgoing run over 06:00-14:00 and one incoming run in the named window."""
    first = setup_approved_batch(target_product_code=from_product, tons_charged=20.000,
                                measured_reject_tons=2.000, declare_spec=False)
    second = setup_approved_batch(
        target_product_code=to_product, tons_charged=20.000,
        measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=setup_available_lot(declare_grades=False, publish_index=False,
                                       supplier_name="Cypress Fiber Yard"))
    run_a = schedule_run(machine["id"], from_product, first["batch"]["id"],
                         window_start="2026-09-01T06:00:00Z",
                         window_end="2026-09-01T14:00:00Z", pulp_draw_tons=5.000)
    run_b = schedule_run(machine["id"], to_product, second["batch"]["id"],
                         window_start=second_start, window_end=second_end,
                         pulp_draw_tons=5.000)
    return run_a, run_b


def _scheduled_tl_140_run():
    """PM1 holding a SCHEDULED run — the only run state onto which PRD §3.6 lets an
    order be sequenced."""
    register_permit()
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(tons_charged=20.000, measured_reject_tons=2.000,
                                 declare_spec=False)
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z", pulp_draw_tons=15.000)
    return machine, run


def _running_tl_140_run():
    machine, run = _scheduled_tl_140_run()
    start_run(machine["id"], run["id"])
    return machine, run


def test_turning_the_machine_back_down_the_sequence_costs_fifteen_percent_more():
    """PRD §3.4: "That delta selects a base waste tier: a delta of 10.0 grams per square
    metre or less costs 0.800 tons, a delta above 10.0 but no more than 40.0 costs 2.500
    tons, and a delta above 40.0 costs 5.000 tons."
    PRD §3.4: "Fourth, a **direction multiplier** of 1.15 applies when the incoming spec's
    `rank_order` is strictly lower than the outgoing spec's — running the sequence backwards
    costs an extra fifteen percent — and 1.00 otherwise, which is why the same pair of
    products produces different waste in the two directions."
    PRD §3.4: "Finally, `transition_minutes` is the waste tonnage divided by the machine's
    `max_tons_per_hour` and multiplied by 60, rounded **up** to the next whole minute, plus
    the machine's `changeover_buffer_minutes` — the ceiling is applied after the tonnage has
    been rounded to three decimal places, not before."
    PRD §3.4: "Planning a grade change bumps the machine's `version` by one."

    Design: Corner/calculations/up_sequence_grade_change_costs_fifteen_percent_more_than_its_mirror
    """
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    declare_paper_grade_spec(product_code="TL_150", family="CONTAINERBOARD",
                             basis_weight_gsm=150.0, target_moisture_pct=7.50,
                             moisture_tolerance_pct=0.50, min_sct_kn_m=2.70,
                             requires_deink_pulp=False, rank_order=11)
    machine = register_machine(**PM1)
    run_a, run_b = _two_scheduled_runs(machine, "TL_150", "TL_140",
                                       "2026-09-01T15:00:00Z", "2026-09-01T18:00:00Z")
    version_before = machine_version(machine["id"])

    change = validate_success(api_client.create_grade_change(
        machine["id"], {"from_run_id": run_a["id"], "to_run_id": run_b["id"],
                        "expected_machine_version": version_before}, PLANNER), 201)

    assert change["status"] == "PLANNED"
    assert change["from_product_code"] == "TL_150"
    assert change["to_product_code"] == "TL_140"
    assert change["transition_waste_tons"] == pytest.approx(0.920, abs=1e-6), \
        "a 10.0 gsm delta sits in the cheapest tier, then pays the backward premium"
    assert change["transition_minutes"] == 33
    assert machine_version(machine["id"]) == version_before + 1


def test_the_waste_ceiling_bites_before_the_changeover_clock_is_derived():
    """PRD §3.4: "Second, a **brightness penalty** of 1.500 tons is added when the incoming
    spec has a `min_brightness_iso` that is not null and either the outgoing spec has no
    brightness requirement at all or the incoming requirement is strictly higher than the
    outgoing one; otherwise the penalty is 0.000 tons."
    PRD §3.4: "Third, a **family multiplier** of 1.00 applies when both specs share the same
    `family`, and 2.20 applies when the transition crosses between `CONTAINERBOARD` and
    `TISSUE`."
    PRD §3.4: "The sum of the base tier and the brightness penalty is then multiplied by the
    family multiplier and by the direction multiplier, the product is capped at a ceiling of
    12.000 tons, and the result rounded half up to three decimal places becomes
    `transition_waste_tons`."
    PRD §3.4: "Finally, `transition_minutes` is the waste tonnage divided by the machine's
    `max_tons_per_hour` and multiplied by 60, rounded **up** to the next whole minute, plus
    the machine's `changeover_buffer_minutes` — the ceiling is applied after the tonnage has
    been rounded to three decimal places, not before."

    Design: Corner/calculations/transition_waste_is_capped_before_transition_minutes_are_derived
    """
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    declare_tis_16(min_brightness_iso=85.0, requires_deink_pulp=False, rank_order=12)
    machine = register_machine(**PM1)
    run_a, run_b = _two_scheduled_runs(machine, "TL_140", "TIS_16",
                                       "2026-09-01T15:30:00Z", "2026-09-01T20:00:00Z")

    change = validate_success(api_client.create_grade_change(
        machine["id"], {"from_run_id": run_a["id"], "to_run_id": run_b["id"],
                        "expected_machine_version": machine_version(machine["id"])},
        PLANNER), 201)

    assert change["transition_waste_tons"] == pytest.approx(12.000, abs=1e-6), \
        "6.500 tons across the family boundary would be 14.300 uncapped"
    assert change["transition_minutes"] == 66, \
        "the clock is derived from the clamped tonnage, not the uncapped product"
    assert change["status"] == "PLANNED"


def test_each_reel_is_rounded_before_the_two_end_reels_are_averaged():
    """PRD §3.5: "The reel's score is 100.00 minus the three penalties, floored at 0.00 and
    **rounded half up to two decimal places before it is used for anything else**."
    PRD §3.5: "The **provisional quality index**, stored as `provisional_quality_index`, is
    the plain arithmetic mean of exactly two reel scores — the reel with the smallest
    `reel_no` and the reel with the largest `reel_no` — rounded half up to two decimal
    places, regardless of how many reels the run actually produced."
    PRD §3.5: "Alongside it, `off_spec_reel_count` is the number of reel readings that breach
    any spec limit, where a reel is off-spec when its basis-weight deviation percentage is
    strictly greater than 5.00, or its moisture deviation is strictly greater than the spec's
    `moisture_tolerance_pct`, or its `sct_kn_m` is strictly below the spec's `min_sct_kn_m`."

    Design: Corner/calculations/per_reel_scores_are_rounded_before_the_provisional_average_is_taken
    """
    machine, run = _running_tl_140_run()

    completed = validate_success(api_client.complete_run(
        machine["id"], run["id"],
        complete_run_payload(reel_readings=THREE_REELS, broke_tons=0.000), OPERATOR))

    assert completed["run_status"] == "COMPLETED"
    assert completed["quality_status"] == "PROVISIONAL"
    assert completed["provisional_quality_index"] == pytest.approx(97.36, abs=1e-6), \
        "97.14 and 97.57 average to a true tie that rounds upward"
    assert completed["off_spec_reel_count"] == 1
    assert completed["certified_quality_index"] is None


def test_the_certified_index_weighs_the_big_middle_reel_at_its_tonnage():
    """PRD §3.5: "The **certified quality index** is the tonnage-weighted mean of **every**
    reel: the sum over all reel readings of `reel_tons` multiplied by that reel's
    already-rounded score, divided by the sum of all `reel_tons`, the quotient rounded half
    up to two decimal places."
    PRD §3.5: "Reel order is irrelevant to a weighted mean, but the per-reel rounding is not
    — each score is rounded to two decimal places before it is weighted."
    PRD §3.5: "The two indexes are stored side by side and are never reconciled: a run whose
    first and last reels are on-spec but whose middle reels are not can carry a provisional
    index of 85.00 or above while its certified index falls below 85.00, which is precisely
    the case the certification gate exists to catch."

    Design: Corner/calculations/certified_index_is_tonnage_weighted_over_all_reels_not_the_endpoint_pair
    """
    machine, run = _running_tl_140_run()
    validate_success(api_client.complete_run(
        machine["id"], run["id"],
        complete_run_payload(reel_readings=THREE_REELS, broke_tons=0.000), OPERATOR))

    held = validate_success(api_client.hold_run(machine["id"], run["id"], CERTIFIER))

    assert held["quality_status"] == "HELD"
    assert held["certified_quality_index"] == pytest.approx(99.29, abs=1e-6), \
        "eleven on-spec tons dominate the two off-square end reels"
    assert held["provisional_quality_index"] == pytest.approx(97.36, abs=1e-6)
    assert held["off_spec_reel_count"] == 1
    assert held["run_status"] == "COMPLETED"


def test_over_covering_an_order_floors_the_shortfall_and_skips_the_unwrapped_set():
    """PRD §3.6: "The order's ledger is recomputed from the roll sets rather than
    accumulated: `allocated_tons` is the sum of `net_tons` over roll sets whose
    `allocated_order_id` is this order and whose status is `ALLOCATED` or `SHIPPED`, rounded
    to three decimal places; `shipped_tons` is the same sum restricted to sets in `SHIPPED`;
    and `shortfall_tons` is `ordered_tons` minus `allocated_tons`, floored at zero and
    rounded to three decimal places."
    PRD §3.6: "Sets in `QUARANTINED`, `REWOUND`, `WOUND`, `WRAPPED` or `SCRAPPED` contribute
    nothing."
    PRD §3.6: "A new set opens in `WOUND` with `rewind_count` of 0, `quarantine_reason` null,
    and `allocated_order_id` null, and its creation recomputes the run's `produced_tons`."

    Design: Corner/calculations/allocation_ledger_floors_the_shortfall_and_ignores_unwrapped_rolls
    """
    machine, run = _scheduled_tl_140_run()
    customer = register_customer(name="Gulf Coast Box Co", allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=10.00, roll_width_mm=2400,
                         roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY")
    # PRD §3.6: sequencing an order "requires the target run's `run_status` to be
    # `SCHEDULED`", and PRD §3.5 advances the order to IN_PRODUCTION on run start —
    # the status PRD §3.6 requires before a wrapped set may be allocated to it.
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    sets = [wind_roll_set(run["id"], slit_width_mm=2400, diameter_mm=1400,
                          roll_count=4, net_tons=tons)
            for tons in (6.000, 6.000, 3.000)]
    validate_success(api_client.complete_run(
        machine["id"], run["id"],
        complete_run_payload(reel_readings=ON_SPEC_REELS_TL_140), OPERATOR))
    wrap_roll_set(sets[0]["id"], "KRAFT_ONLY")
    wrap_roll_set(sets[1]["id"], "KRAFT_ONLY")
    validate_success(api_client.certify_run(machine["id"], run["id"], CERTIFIER))
    partial = allocate_roll_set(sets[0]["id"], order["id"])
    assert partial["status"] == "ALLOCATED"
    interim = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert interim["status"] == "PARTIALLY_ALLOCATED"
    assert interim["shortfall_tons"] == pytest.approx(4.000, abs=1e-6)

    second = allocate_roll_set(sets[1]["id"], order["id"])

    assert second["status"] == "ALLOCATED"
    assert second["allocated_order_id"] == order["id"]
    filled = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert filled["status"] == "ALLOCATED"
    assert filled["allocated_tons"] == pytest.approx(12.000, abs=1e-6)
    assert filled["shipped_tons"] == pytest.approx(0.000, abs=1e-6)
    assert filled["shortfall_tons"] == pytest.approx(0.000, abs=1e-6)
    produced = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert produced["produced_tons"] == pytest.approx(15.000, abs=1e-6)
    left_wound = get_success_data(api_client.get_roll_set(sets[2]["id"], PLANNER))
    assert left_wound["status"] == "WOUND"
    assert left_wound["allocated_order_id"] is None
    booked = api_client.list_roll_sets(
        PLANNER, {"allocated_order_id": order["id"]}).json()
    assert booked["meta"]["total_count"] == 2


def test_a_sweep_rejection_earns_no_strike_so_the_supplier_lands_on_probation():
    """PRD §3.2: "Hop one increments `contamination_strike_count` by one and re-derives
    `qualification_status` from the strike count, where the count is the number of fiber
    receipts of this supplier, across every purchase order, whose status is `DOWNGRADED` or
    `REJECTED` **and** whose `dispositioned_by_user_id` is set."
    PRD §3.2: "Receipts flipped to `REJECTED` by a purchase-order cancellation sweep carry no
    dispositioning operator and are therefore excluded from the count."
    PRD §3.2: "Four or more strikes makes the supplier `SUSPENDED`; two or three strikes
    makes it `PROBATION`; anything below two leaves it `QUALIFIED`."
    PRD §3.2: "When the value first becomes `PROBATION`, `probation_entered_at` is stamped
    with the current logical-clock instant and is then left alone for as long as the posture
    stays `PROBATION`; returning to `QUALIFIED` clears `probation_entered_at` to null."

    Design: Corner/calculations/strike_count_ignores_cancel_cascade_rejections_and_lands_exactly_on_probation
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    kept = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                               negotiated_delta_per_ton=5.00)
    first = record_receipt(kept["id"], DIRTY_TRUCK, truck_reference="TRK-0001",
                           sampler_headers=SAMPLER)
    second = record_receipt(kept["id"], DIRTY_TRUCK, truck_reference="TRK-0002",
                            sampler_headers=SAMPLER)
    swept_po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=100.00,
                                   negotiated_delta_per_ton=5.00)
    swept = record_receipt(swept_po["id"], DIRTY_TRUCK, truck_reference="TRK-0003",
                           sampler_headers=SAMPLER)
    validate_success(api_client.cancel_purchase_order(swept_po["id"], BUYER))
    disposition(first["id"], "REJECT", headers=DISPOSER)

    rejected = validate_success(api_client.disposition_receipt(
        second["id"], {"disposition": "REJECT"}, CERTIFIER))

    assert rejected["status"] == "REJECTED"
    assert rejected["accepted_grade_code"] is None
    assert rejected["dispositioned_by_user_id"] == "ql_cert"
    assert rejected["weighted_contamination_pct"] == pytest.approx(5.00, abs=1e-6)

    posture = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert posture["contamination_strike_count"] == 2, \
        "the administratively swept truck is not a quality judgement"
    assert posture["qualification_status"] == "PROBATION"
    assert posture["probation_entered_at"].startswith("2026-08-01T00:00:00"), \
        "the stamp is the logical-clock instant, not wall time"

    all_rejected = api_client.list_receipts(
        BUYER, {"supplier_id": supplier["id"], "status": "REJECTED"}).json()
    assert all_rejected["meta"]["total_count"] == 3
    swept_now = get_success_data(api_client.get_receipt(swept["id"], BUYER))
    assert swept_now["status"] == "REJECTED"
    assert swept_now["dispositioned_by_user_id"] is None
    kept_now = get_success_data(api_client.get_purchase_order(kept["id"], BUYER))
    assert kept_now["received_net_tons"] == pytest.approx(0.00, abs=1e-6)
    assert kept_now["status"] == "CONFIRMED"
