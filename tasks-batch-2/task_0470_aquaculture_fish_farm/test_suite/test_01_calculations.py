"""Calculation correctness: biomass growth model, FCR provisional vs final,
processing yield estimate vs actual, and the pinned per-line order-total
rounding. Each numeric expected value is copied verbatim from the design index.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    set_clock,
    create_species,
    create_tank,
    create_cohort,
    feed_cohort,
    create_product_lot,
    create_sales_order,
    add_line,
    get_lot,
    create_harvest_order,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
HO = TEST_USERS["harvest_operator_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# Rule 1 — dual_variant_calc :: fcr_provisional_vs_final_diverges_on_cohort
# ===========================================================================
def _setup_fcr_cohort():
    """Species SALM (growth 5.0), Cohort 1000 fish @ 50g stocked 2026-01-01,
    one 300kg feed at 2026-01-15, clock then advanced to 2026-02-01, and a
    harvest order scheduled + started ready to complete."""
    species = create_species(base_daily_growth_g=5.0, target_market_weight_g=5000,
                             default_processing_yield_pct=0.62)
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000,
                           stocked_avg_weight_g=50, stocked_at="2026-01-01T00:00:00Z")
    set_clock("2026-01-15T00:00:00Z")
    feed_cohort(cohort["id"], fed_at="2026-01-15T00:00:00Z", amount_kg=300,
                feed_type="grower")
    set_clock("2026-02-01T00:00:00Z")
    ho = create_harvest_order(cohort["id"], planned_fish_count=1000,
                              scheduled_at="2026-02-01T00:00:00Z")
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    get_success_data(api_client.start_harvest_order(ho["id"], HO))
    return cohort, ho


def test_provisional_fcr_uses_growth_estimate_before_harvest():
    """PRD §3.3: "The provisional ratio uses the growth-model estimate for the
    gain: the provisional biomass gain is the cohort's estimated_biomass_kg minus
    the stocked biomass, where stocked biomass is the cohort's current fish_count
    multiplied by stocked_avg_weight_g divided by 1000."
    PRD §3.3: "The provisional_fcr is then the cumulative_feed_kg divided by that
    gain - but to avoid division by a vanishing or negative gain, the divisor
    used is the larger of the computed gain and a floor of 0.01 kilograms."

    Design: Difficulty/dual_variant_calc/fcr_provisional_vs_final_diverges_on_cohort
    """
    cohort, _ho = _setup_fcr_cohort()
    summary = validate_success(api_client.get_cohort_summary(cohort["id"], FT))
    assert summary["provisional_fcr"] == pytest.approx(1.98, abs=0.01), \
        f"expected provisional_fcr 1.98, got {summary['provisional_fcr']}"


# NOTE: test_final_fcr_uses_actual_landed_weight_and_diverges_from_provisional
# was DELETED (PRD-First contract, STEP 1b COMPUTED-FIELD SILENCE). It asserted
# completed.get("final_fcr") == 2.31 on the harvest-order completion response,
# but the PRD only says "Completion also fixes the final feed conversion ratio"
# (§3.8) — it never names a response-visible field `final_fcr` and the harvest
# order's declared schema (§3.8) lists no such attribute. A faithful PRD-only
# implementer could correctly compute the final ratio without surfacing it on
# the response, so the asserted outcome is not uniquely derivable from the PRD.


# ===========================================================================
# Rule 1 — dual_variant_calc :: processing_yield_estimate_vs_actual_diverges_on_batch
# ===========================================================================
def _setup_processing_batch(harvested_live_weight_kg=200.0):
    species = create_species(default_processing_yield_pct=0.62)
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    ho = create_harvest_order(cohort["id"], planned_fish_count=500,
                              scheduled_at="2026-01-01T00:00:00Z")
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    get_success_data(api_client.start_harvest_order(ho["id"], HO))
    get_success_data(
        api_client.complete_harvest_order(
            ho["id"],
            {"harvested_fish_count": 500,
             "harvested_live_weight_kg": harvested_live_weight_kg},
            HO,
        )
    )
    pb = get_success_data(api_client.create_processing_batch({"harvest_order_id": ho["id"]}, HO))
    return species, cohort, pb


def test_processing_estimated_yield_applies_species_default_pct():
    """PRD §3.9: "Starting processing (DRAFT -> PROCESSING) requires the linked
    harvest order to be COMPLETED and computes the forward-looking yield estimate:
    the estimated_yield_kg is the batch's input_live_weight_kg multiplied by the
    species' default_processing_yield_pct, rounded to 2 decimal places."

    Design: Difficulty/dual_variant_calc/processing_yield_estimate_vs_actual_diverges_on_batch
    """
    _species, _cohort, pb = _setup_processing_batch(harvested_live_weight_kg=200.0)
    started = validate_success(api_client.start_processing_batch(pb["id"], HO))
    # round(200.0 * 0.62, 2) == 124.00
    assert started["estimated_yield_kg"] == pytest.approx(124.00, abs=0.01), \
        f"expected estimated_yield_kg 124.00, got {started['estimated_yield_kg']}"


def test_processing_actual_lot_weight_diverges_from_estimate():
    """PRD §3.9: "On completion the batch stores its actual_processed_weight_kg
    and creates exactly one ProductLot."
    PRD §3.10: "records a total_weight_kg equal to the batch's
    actual_processed_weight_kg - a figure immutable after creation."

    Design: Difficulty/dual_variant_calc/processing_yield_estimate_vs_actual_diverges_on_batch
    """
    _species, _cohort, pb = _setup_processing_batch(harvested_live_weight_kg=200.0)
    started = validate_success(api_client.start_processing_batch(pb["id"], HO))
    estimated = started["estimated_yield_kg"]
    get_success_data(
        api_client.complete_processing_batch(
            pb["id"],
            {"actual_processed_weight_kg": 130.0, "price_per_kg": 12.50},
            HO,
        )
    )
    lots, _meta = _list_lots_for_batch(pb["id"])
    assert lots, "completed batch must create a product lot"
    lot = lots[0]
    assert lot["total_weight_kg"] == pytest.approx(130.00, abs=0.01), \
        f"expected ProductLot.total_weight_kg 130.00, got {lot['total_weight_kg']}"
    assert lot["total_weight_kg"] != pytest.approx(estimated, abs=0.001), \
        "actual lot weight must diverge from the forward estimate"


def _list_lots_for_batch(batch_id):
    from test_helpers import validate_paginated
    return validate_paginated(
        api_client.list_product_lots(HO, params={"processing_batch_id": batch_id})
    )


# ===========================================================================
# Rule 2 — combinatorial_formula :: biomass_growth_tiered_nonlinear_mode_a
# ===========================================================================
def test_biomass_growth_tiered_nonlinear_at_31_days():
    """PRD §3.2: "The estimated average individual weight in grams is the
    stocked_avg_weight_g plus the product of the elapsed days, the species'
    base_daily_growth_g, and the applicable tier factor; this estimate is then
    capped so that it never exceeds the species' target_market_weight_g."
    PRD §3.2: "the estimated_biomass_kg is the cohort's current fish_count
    multiplied by the estimated average weight in grams, multiplied by the
    survival fraction, divided by 1000 to convert grams to kilograms, and rounded
    to 2 decimal places."

    Design: Difficulty/combinatorial_formula/biomass_growth_tiered_nonlinear_mode_a
    """
    species = create_species(base_daily_growth_g=5.0, target_market_weight_g=5000)
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000,
                           stocked_avg_weight_g=50, stocked_at="2026-01-01T00:00:00Z")
    set_clock("2026-02-01T00:00:00Z")
    summary = validate_success(api_client.get_cohort_summary(cohort["id"], FT))
    # round(1000 * (50 + 31*5.0*1.00) * max(0.80, 1-0.0005*31) / 1000, 2)
    assert summary["estimated_biomass_kg"] == pytest.approx(201.82, abs=0.01), \
        f"expected estimated_biomass_kg 201.82, got {summary['estimated_biomass_kg']}"


def test_biomass_summary_reports_days_elapsed():
    """PRD §3.3: "The cohort summary endpoint is a read-only computation that
    returns, for the cohort, its cohort_id, the recomputed estimated_biomass_kg,
    the provisional feed conversion ratio provisional_fcr, the cumulative_feed_kg,
    and the days_elapsed since stocking."
    PRD §3.2: "The model first determines the number of whole days elapsed since
    stocking: the difference between the current clock and stocked_at, taken as a
    whole number of days by discarding any fractional day."

    Design: Difficulty/combinatorial_formula/biomass_growth_tiered_nonlinear_mode_a
    """
    species = create_species(base_daily_growth_g=5.0, target_market_weight_g=5000)
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000,
                           stocked_avg_weight_g=50, stocked_at="2026-01-01T00:00:00Z")
    set_clock("2026-02-01T00:00:00Z")
    summary = validate_success(api_client.get_cohort_summary(cohort["id"], FT))
    assert summary["days_elapsed"] == 31, \
        f"expected days_elapsed 31, got {summary['days_elapsed']}"


# ===========================================================================
# Rule 2 — combinatorial_formula :: order_total_per_line_round_then_sum_mode_b
# ===========================================================================
def _setup_two_lot_silver_order():
    """LotA price 12.50 (100kg), LotB price 9.99 (50kg); SILVER order with lines
    LotA weight 3.333 and LotB weight 2.5."""
    species = create_species()
    tank = create_tank(volume_liters=200000, max_biomass_kg=200000)
    lot_a, _s, _t = create_product_lot(100.0, price_per_kg=12.50, species=species,
                                       tank=tank, cohort_label="CA",
                                       harvested_live_weight_kg=300.0)
    lot_b, _s2, _t2 = create_product_lot(50.0, price_per_kg=9.99, species=species,
                                         tank=tank, cohort_label="CB",
                                         harvested_live_weight_kg=200.0)
    order = create_sales_order(customer_name="Acme", discount_tier="SILVER")
    add_line(order["id"], lot_a["id"], 3.333)
    add_line(order["id"], lot_b["id"], 2.5)
    return order, lot_a, lot_b


def test_order_total_per_line_round_then_sum_then_discount():
    """PRD §3.10: "first each line's subtotal is computed as its weight_kg times
    its lot's price_per_kg rounded to 2 decimal places; then those already-rounded
    line subtotals are summed; then the volume discount for the order's
    discount_tier is applied ... by multiplying the sum by one minus the tier
    fraction; and finally the discounted figure is rounded to 2 decimal places."
    PRD §3.10: "Per-line rounding strictly precedes summation, and the discount is
    applied after summation and before the final rounding."

    Design: Difficulty/combinatorial_formula/order_total_per_line_round_then_sum_mode_b
    """
    order, lot_a, _lot_b = _setup_two_lot_silver_order()
    lot_a_now = get_lot(lot_a["id"])
    confirmed = validate_success(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_a_now["version"]}, SA
        )
    )
    # round((round(3.333*12.50,2) + round(2.5*9.99,2)) * 0.90, 2)
    #   = round((41.66 + 24.98) * 0.90, 2) == 59.98  (sum-then-round 59.97 is wrong)
    assert confirmed["order_total"] == pytest.approx(59.98, abs=0.01), \
        f"expected order_total 59.98 (pinned per-line rounding), got {confirmed['order_total']}"


def test_order_line_subtotals_rounded_per_line():
    """PRD §3.10: "Each line_subtotal is its weight_kg multiplied by the
    referenced lot's price_per_kg, rounded to 2 decimal places."

    Design: Difficulty/combinatorial_formula/order_total_per_line_round_then_sum_mode_b
    """
    from test_helpers import validate_paginated
    order, lot_a, lot_b = _setup_two_lot_silver_order()
    lines, _meta = validate_paginated(
        api_client.list_sales_order_lines(SA, params={"sales_order_id": order["id"]})
    )
    by_lot = {ln["product_lot_id"]: ln for ln in lines}
    assert by_lot[lot_a["id"]]["line_subtotal"] == pytest.approx(41.66, abs=0.01), \
        "LotA line_subtotal must be round(3.333*12.50, 2) == 41.66"
    assert by_lot[lot_b["id"]]["line_subtotal"] == pytest.approx(24.98, abs=0.01), \
        "LotB line_subtotal must be round(2.5*9.99, 2) == 24.98"
