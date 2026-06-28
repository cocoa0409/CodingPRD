"""Order pricing: provisional vs final totals, price-match divergence, loyalty
rounding, team bulk discount, and license-fee tiering.

Difficulty queue: dual_variant_calc, combinatorial_formula.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_customer_headers,
    setup_base_scenario,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    build_order_with_lines,
    setup_placed_order,
    setup_ready_order,
    setup_fulfilled_order,
    place_order,
    ready_order,
    fulfill_order,
    submit_price_match_claim,
    approve_price_match_claim,
    raise_customer_to_silver,
    issue_fishing_license,
    setup_submitted_team_order,
    approve_team_order,
    get_order,
    get_customer,
)


# ===========================================================================
# dual_variant_calc / order_provisional_vs_final_pricematch_divergence
# ===========================================================================
def test_provisional_diverges_from_final_with_approved_price_match(api):
    """PRD §3.6: "The provisional pass uses the markdown picture as of placement
    and deliberately ignores price-match claims, which may still be unresolved at
    that moment."
    PRD §3.6: "First, for any line that has an `APPROVED` price-match claim, the
    effective unit price is the claim's `approved_unit_price_cents` rather than the
    markdown-derived price."

    Two lines: A (base 8000, qty 2) and B (base 5000, qty 1). Provisional total is
    8000*2 + 5000 = 21000. After an APPROVED price-match dropping line A to 6000,
    final total is 6000*2 + 5000 = 17000, so provisional != final.

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_pricematch_divergence
    """
    store = create_store(state_code="CA")
    sku_a = create_sku(sport="HOCKEY", name="Stick A", base_price_cents=8000, size_label="NA")
    sku_b = create_sku(sport="HOCKEY", name="Puck B", base_price_cents=5000, size_label="NA")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku_a["id"], 10)
    stock_sku(store["id"], sku_b["id"], 10)

    placed, lines = setup_placed_order(
        customer["id"], store["id"],
        [{"sku_id": sku_a["id"], "quantity": 2}, {"sku_id": sku_b["id"], "quantity": 1}],
    )
    assert placed["provisional_total_cents"] == 21000

    line_a = lines[0]
    claim = submit_price_match_claim(placed["id"], line_a["id"], customer["id"], 6000)
    approve_price_match_claim(claim["id"])

    ready_order(placed["id"])
    fulfilled = fulfill_order(placed["id"])

    assert fulfilled["provisional_total_cents"] == 21000
    assert fulfilled["final_total_cents"] == 17000
    assert fulfilled["provisional_total_cents"] != fulfilled["final_total_cents"]


def test_approved_price_match_only_applied_at_fulfillment(api):
    """PRD §3.7: "The approved price changes nothing immediately; it is applied to
    the line only when the order is fulfilled, through the final-total computation
    of §3.6."

    Provisional total is fixed at placement (21000); the approved price-match does
    not alter provisional_total_cents and only manifests in final_total_cents.

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_pricematch_divergence
    """
    store = create_store(state_code="CA")
    sku_a = create_sku(sport="HOCKEY", name="Stick A", base_price_cents=8000, size_label="NA")
    sku_b = create_sku(sport="HOCKEY", name="Puck B", base_price_cents=5000, size_label="NA")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku_a["id"], 10)
    stock_sku(store["id"], sku_b["id"], 10)

    placed, lines = setup_placed_order(
        customer["id"], store["id"],
        [{"sku_id": sku_a["id"], "quantity": 2}, {"sku_id": sku_b["id"], "quantity": 1}],
    )
    claim = submit_price_match_claim(placed["id"], lines[0]["id"], customer["id"], 6000)
    approve_price_match_claim(claim["id"])

    # Before fulfillment, provisional is unchanged and final is still null.
    mid = get_order(placed["id"])
    assert mid["provisional_total_cents"] == 21000
    assert mid["final_total_cents"] is None

    ready_order(placed["id"])
    fulfilled = fulfill_order(placed["id"])
    assert fulfilled["final_total_cents"] == 17000


# ===========================================================================
# dual_variant_calc / loyalty_tier_vs_license_fee_distinct_domains
# ===========================================================================
def test_resident_vs_nonresident_license_fee_distinct_from_loyalty(api):
    """PRD §3.4: "the license is `RESIDENT` when the customer's `home_state_code`
    equals the issuing store's `state_code`, and `NONRESIDENT` otherwise. The
    `fee_cents` follows from residency — a resident license costs 2500 cents and a
    nonresident license costs 6500 cents."

    The same customer (home CA) gets a RESIDENT 2500 license at a CA store and a
    NONRESIDENT 6500 license at an NV store.

    Design: Difficulty/dual_variant_calc/loyalty_tier_vs_license_fee_distinct_domains
    """
    ca_store = create_store(name="CA Store", state_code="CA")
    nv_store = create_store(name="NV Store", state_code="NV")
    customer = create_customer(home_state_code="CA")

    res_license = issue_fishing_license(customer["id"], ca_store["id"])
    assert res_license["residency"] == "RESIDENT"
    assert res_license["fee_cents"] == 2500

    non_license = issue_fishing_license(customer["id"], nv_store["id"])
    assert non_license["residency"] == "NONRESIDENT"
    assert non_license["fee_cents"] == 6500


def test_loyalty_tier_bronze_unrelated_to_license_fee(api):
    """PRD §3.1: "Every customer starts with `loyalty_points` of 0 and
    `loyalty_tier` of `BRONZE`."

    Loyalty tiering derives from loyalty_points on the Customer domain and is
    independent of any fishing-license fee: a fresh customer who has only been
    issued licenses is still BRONZE with 0 points.

    Design: Difficulty/dual_variant_calc/loyalty_tier_vs_license_fee_distinct_domains
    """
    ca_store = create_store(name="CA Store", state_code="CA")
    customer = create_customer(home_state_code="CA")
    issue_fishing_license(customer["id"], ca_store["id"])

    refreshed = get_customer(customer["id"])
    assert refreshed["loyalty_points"] == 0
    assert refreshed["loyalty_tier"] == "BRONZE"


# ===========================================================================
# combinatorial_formula / team_bulk_discount_then_loyalty_pinned_order
# ===========================================================================
def test_team_bulk_discount_six_percent_at_twenty_units(api):
    """PRD §3.11: "The bulk percent is 20 when `total_units` is at least 100,
    otherwise 12 when `total_units` is at least 50, otherwise 6 when `total_units`
    is at least 20, otherwise 0."
    PRD §3.11: "The spawned `provisional_total_cents` is the merchandise subtotal
    minus the bulk discount minus the loyalty discount."

    20 jerseys at base 3000 with the mandatory 500/unit embroidery surcharge:
    subtotal = (3000 + 500) * 20 = 70000. Bulk 6% = 4200. BRONZE loyalty 0.
    Spawned provisional = 70000 - 4200 = 65800.

    Design: Difficulty/combinatorial_formula/team_bulk_discount_then_loyalty_pinned_order
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="TEAMWEAR", name="Jersey", base_price_cents=3000,
                     size_label="L", embroiderable=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 30)

    submitted, _ = setup_submitted_team_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 20}],
        team_name="Eagles",
    )
    assert submitted["total_units"] == 20

    approved = approve_team_order(submitted["id"])
    spawned = get_order(approved["spawned_order_id"])
    assert spawned["provisional_total_cents"] == 65800


def test_team_total_units_summed_before_bulk_tier(api):
    """PRD §3.10: "on success the server recomputes `total_units` as the sum of
    `quantity` across all team lines and increments the team order's `version` by
    one."

    total_units is recomputed on submit (20 here), which is the input that selects
    the bulk-discount tier in §3.11.

    Design: Difficulty/combinatorial_formula/team_bulk_discount_then_loyalty_pinned_order
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="TEAMWEAR", name="Jersey", base_price_cents=3000,
                     size_label="L", embroiderable=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 30)

    submitted, _ = setup_submitted_team_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 20}],
        team_name="Eagles",
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["total_units"] == 20


# ===========================================================================
# combinatorial_formula / loyalty_discount_round_once_on_subtotal_not_per_line
# ===========================================================================
def test_loyalty_discount_rounded_once_on_subtotal(api):
    """PRD §3.6: "After all lines are summed, the loyalty discount (§3.5) is
    computed once on the merchandise subtotal, and `provisional_total_cents` is the
    merchandise subtotal minus that loyalty discount."
    PRD §3.5: "the subtotal in cents is multiplied by the tier's percent, divided
    by 100, and rounded half up once to whole cents — applied to the whole
    subtotal, not per line."

    SILVER customer, two lines (13000 qty 1, 8000 qty 1), subtotal 21000.
    5% loyalty applied once = round_half_up(21000 * 5 / 100) = 1050.
    Provisional = 21000 - 1050 = 19950.

    Design: Difficulty/combinatorial_formula/loyalty_discount_round_once_on_subtotal_not_per_line
    """
    store = create_store(state_code="CA")
    customer, _ = raise_customer_to_silver(store)
    assert customer["loyalty_tier"] == "SILVER"

    sku_x = create_sku(sport="APPAREL", name="Pants", base_price_cents=13000, size_label="M")
    sku_y = create_sku(sport="APPAREL", name="Shirt", base_price_cents=8000, size_label="M")
    stock_sku(store["id"], sku_x["id"], 5)
    stock_sku(store["id"], sku_y["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"],
        [{"sku_id": sku_x["id"], "quantity": 1}, {"sku_id": sku_y["id"], "quantity": 1}],
    )
    assert placed["provisional_total_cents"] == 19950


def test_customer_reaches_silver_via_prior_fulfilled_order(api):
    """PRD §3.5: "The thresholds are inclusive lower bounds, so exactly 500 points
    yields `SILVER` while 499 yields `BRONZE`."

    A fulfilled 50000-cent order accrues floor(50000/100) = 500 points, lifting the
    customer to SILVER — the precondition the loyalty-rounding test relies on.

    Design: Difficulty/combinatorial_formula/loyalty_discount_round_once_on_subtotal_not_per_line
    """
    store = create_store(state_code="CA")
    customer, _ = raise_customer_to_silver(store)
    assert customer["loyalty_points"] == 500
    assert customer["loyalty_tier"] == "SILVER"
