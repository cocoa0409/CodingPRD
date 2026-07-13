"""Bale valuation: combinatorial formula, provisional vs final, freight, rounding."""
from test_helpers import validate_success, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_municipality, create_mill, create_sort_line, create_load,
    audit_load, close_load, create_and_publish_index, create_bale, create_shipment,
    assign_bale, ship_shipment, settle_shipment, setup_audited_load,
    setup_shipped_single_bale, setup_two_window_shipped_bale,
)

SORT = TEST_USERS["sort_manager_headers"]
TRADER = TEST_USERS["commodity_trader_headers"]


# --- Difficulty: combinatorial bale value (grade x moisture, non-linear) -----

def test_provisional_bale_value_grade_c_moisture(api):
    """PRD §3.6: "The provisional value is then computed by the bale valuation
    formula: first compute effective tonnage as `net_tons` multiplied by the
    quantity one minus `moisture_pct` divided by 100; multiply by the grade
    multiplier, which is 1.00 for grade `A`, 0.90 for grade `B`, and 0.75 for grade
    `C`; and round that product, taken against `index_price_snapshot_cents`, half up
    to whole cents."

    Design: Difficulty/combinatorial_formula/bale_value_multi_input_grade_moisture_nonlinear
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    create_and_publish_index(api, "OCC", 8000)
    ctx = setup_audited_load(api, revenue_share_pct=0.50, gross_tons=30, tare_tons=0)
    bale = create_bale(api, ctx["load_id"], "OCC", net_tons=10, moisture_pct=20,
                       quality_grade="C")
    assert bale["provisional_value_cents"] == 48000


def test_bale_captures_index_price_snapshot(api):
    """PRD §3.6: "The `index_price_snapshot_cents` is the `price_cents_per_ton` of
    the index in force for the bale's commodity at the bale's creation instant (per
    §2.9)."

    Design: Difficulty/combinatorial_formula/bale_value_multi_input_grade_moisture_nonlinear
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    create_and_publish_index(api, "OCC", 8000)
    ctx = setup_audited_load(api, revenue_share_pct=0.50, gross_tons=30, tare_tons=0)
    bale = create_bale(api, ctx["load_id"], "OCC", net_tons=10, moisture_pct=20,
                       quality_grade="C")
    assert bale["index_price_snapshot_cents"] == 8000


# --- Difficulty: dual bale value (provisional snapshot vs final at settle) ----

def test_provisional_bale_value_uses_snapshot_index(api):
    """PRD §3.6: "In the provisional variant there is no freight deduction, so
    `provisional_value_cents` is exactly that rounded gross value."

    Design: Difficulty/dual_variant_calc/dual_bale_value_provisional_vs_final
    """
    ctx = setup_two_window_shipped_bale(api, revenue_share_pct=0.60,
                                        freight_cost_cents=5000)
    assert ctx["bale"]["provisional_value_cents"] == 76000


def test_final_bale_value_uses_settle_index_minus_freight(api):
    """PRD §3.7: "Then the bale's `final_value_cents` is computed by the final
    variant of the bale valuation: the same effective-tonnage-times-grade-multiplier
    product as before, but priced at the `price_cents_per_ton` of the index in force
    at the settle-time clock (which may differ from the snapshot taken at baling),
    rounded once to whole cents, and then reduced by that bale's `freight_share_cents`."

    Design: Difficulty/dual_variant_calc/dual_bale_value_provisional_vs_final
    """
    ctx = setup_two_window_shipped_bale(api, revenue_share_pct=0.60,
                                        freight_cost_cents=5000)
    settle_shipment(api, ctx["ship_id"])
    bale = validate_success(api.get_bale(ctx["bale_id"], TRADER))
    assert bale["final_value_cents"] == 80500
    assert bale["final_value_cents"] != bale["provisional_value_cents"]


# --- Difficulty: shipment settlement rounds per bale then sums ---------------

def _setup_two_grade_b_bales_shipped(api):
    set_clock(api, "2026-03-10T00:00:00Z")
    muni = create_municipality(api, revenue_share_pct=0.50)
    mill = create_mill(api, "OCC")
    create_and_publish_index(api, "OCC", 8005)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=5, tare_tons=0)
    audit_load(api, load["id"], 3.0, [{"commodity": "OCC", "pct": 99}])
    b1 = create_bale(api, load["id"], "OCC", net_tons=1, moisture_pct=0, quality_grade="B")
    b2 = create_bale(api, load["id"], "OCC", net_tons=1, moisture_pct=0, quality_grade="B")
    close_load(api, load["id"], residual_tons=0)
    ship = create_shipment(api, mill["id"], "OCC", freight_cost_cents=0)
    assign_bale(api, ship["id"], b1["id"])
    assign_bale(api, ship["id"], b2["id"])
    ship = ship_shipment(api, ship["id"])
    return ship["id"], b1["id"], b2["id"]


def test_each_bale_rounds_independently(api):
    """PRD §3.7: "Then the bale's `final_value_cents` is computed by the final
    variant of the bale valuation: the same effective-tonnage-times-grade-multiplier
    product as before, but priced at the `price_cents_per_ton` of the index in force
    at the settle-time clock (which may differ from the snapshot taken at baling),
    rounded once to whole cents, and then reduced by that bale's `freight_share_cents`."

    Design: Difficulty/combinatorial_formula/shipment_settlement_round_per_bale_then_sum
    """
    ship_id, b1, b2 = _setup_two_grade_b_bales_shipped(api)
    settle_shipment(api, ship_id)
    bale1 = validate_success(api.get_bale(b1, TRADER))
    bale2 = validate_success(api.get_bale(b2, TRADER))
    assert bale1["final_value_cents"] == 7205
    assert bale2["final_value_cents"] == 7205


def test_gross_settlement_is_sum_of_rounded_bales(api):
    """PRD §3.7: "The shipment's `gross_settlement_cents` is the sum of the per-bale
    `final_value_cents` values — and because each `final_value_cents` is already an
    integer number of cents, the total is the sum of those per-bale integers (round
    each bale first, then add), never a single rounding of summed real values; the
    two orders can differ by up to one cent per additional bale."

    Design: Difficulty/combinatorial_formula/shipment_settlement_round_per_bale_then_sum
    """
    ship_id, b1, b2 = _setup_two_grade_b_bales_shipped(api)
    ship = settle_shipment(api, ship_id)
    assert ship["gross_settlement_cents"] == 14410


# --- Corner: freight allocation by tonnage ----------------------------------

def test_freight_allocated_by_tonnage(api):
    """PRD §3.7: "each bale's `freight_share_cents` is the shipment's
    `freight_cost_cents` multiplied by that bale's `net_tons` divided by the
    shipment's `total_net_tons`, rounded half up to whole cents."

    Design: Corner/calculations/corner_freight_allocation_by_tonnage
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    muni = create_municipality(api, revenue_share_pct=0.50)
    mill = create_mill(api, "OCC", freight_rate_cents_per_ton=500)
    create_and_publish_index(api, "OCC", 10000)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=6, tare_tons=0)
    audit_load(api, load["id"], 3.0, [{"commodity": "OCC", "pct": 99}])
    b2 = create_bale(api, load["id"], "OCC", net_tons=2, moisture_pct=0, quality_grade="A")
    b4 = create_bale(api, load["id"], "OCC", net_tons=4, moisture_pct=0, quality_grade="A")
    close_load(api, load["id"], residual_tons=0)
    ship = create_shipment(api, mill["id"], "OCC", freight_cost_cents=3000)
    assign_bale(api, ship["id"], b2["id"])
    assign_bale(api, ship["id"], b4["id"])
    ship_shipment(api, ship["id"])
    settle_shipment(api, ship["id"])
    bale2 = validate_success(api.get_bale(b2["id"], TRADER))
    bale4 = validate_success(api.get_bale(b4["id"], TRADER))
    assert bale2["freight_share_cents"] == 1000
    assert bale4["freight_share_cents"] == 2000


# --- Corner: settle response reflects updated fields immediately -------------

def test_settle_response_immediately_reflects_settlement(api):
    """PRD §3.7: "Each settled bale moves from `SHIPPED` to `SETTLED`."
    PRD §2.2: "operations that create or modify a resource will return the created
    or updated resource object in the data field."

    Design: Corner/consistency_model/corner_settle_response_reflects_updated_fields_immediately
    """
    ctx = setup_shipped_single_bale(api, index_price_cents_per_ton=8000,
                                    revenue_share_pct=0.50, bale_net_tons=10,
                                    moisture_pct=0, quality_grade="A",
                                    freight_cost_cents=0)
    ship = settle_shipment(api, ctx["ship_id"])
    assert ship["status"] == "SETTLED"
    assert ship["gross_settlement_cents"] == 80000
