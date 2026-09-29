"""Price index reporting: the two basis variants and the pinned rounding order.

Two design instances live here — the MATCHED_BASKET / IMPUTED_FULL_CATALOG
divergence on one identical basket, and the round-per-product-then-average
ordering that decides whether the index lands on 9743 or 9744.
"""
from test_helpers import (
    ANALYST,
    api_client,
    confirm_match,
    new_competitor,
    new_market,
    new_match,
    new_observation,
    new_product,
    market_version,
    read_market,
    read_match,
    set_clock,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
OBSERVED_AT = "2026-07-31T18:00:00Z"


def _coffee_product(market_id, sku, own_price_cents, unit_cost_cents, index_weight_bp):
    return new_product(
        market_id,
        sku=sku,
        category_code="COFFEE",
        brand="Roastly",
        own_price_cents=own_price_cents,
        unit_cost_cents=unit_cost_cents,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=index_weight_bp,
    )


def _confirmed_link_with_observation(product_id, competitor_id, identifier, observed_price_cents):
    """CONFIRMED match at 10000 bp carrying one fresh ACTIVE in-stock observation."""
    link = new_match(
        product_id,
        competitor_id,
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier=identifier,
    )
    confirm_match(link["id"])
    new_observation(
        link["id"],
        observed_price_cents=observed_price_cents,
        collection_method="ONLINE",
        observed_at=OBSERVED_AT,
        in_stock=True,
    )
    return link


def _three_product_basket():
    """COFFEE basket of three ACTIVE products; only P1 and P2 carry a benchmark.

    P1 own 24999 weight 10000 benchmarked at 25999 -> ratio 9615.
    P2 own  9999 weight  5000 benchmarked at  9999 -> ratio 10000.
    P3 own 19999 weight  5000 has no match at all.
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    p1 = _coffee_product(market["id"], "SKU-COFFEE-1", 24999, 15000, 10000)
    p2 = _coffee_product(market["id"], "SKU-COFFEE-2", 9999, 5000, 5000)
    p3 = _coffee_product(market["id"], "SKU-COFFEE-3", 19999, 12000, 5000)
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    l1 = _confirmed_link_with_observation(p1["id"], competitor["id"], "00712345678901", 25999)
    l2 = _confirmed_link_with_observation(p2["id"], competitor["id"], "00712345678902", 9999)
    return {
        "market": market,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "competitor": competitor,
        "l1": l1,
        "l2": l2,
    }


def _report(market_id, basis, expected_market_version, **extra):
    payload = {
        "market_id": market_id,
        "category_code": "COFFEE",
        "basis": basis,
        "expected_market_version": expected_market_version,
    }
    payload.update(extra)
    return validate_success(api_client.create_index_report(payload, ANALYST), 201)


def test_matched_basket_excludes_the_unmatched_candidate_from_the_index():
    """MATCHED_BASKET indexes only the two benchmarked products, landing on 9743 bp.

    PRD: "Under **`MATCHED_BASKET`**, the basket is exactly the matched products and `imputed_product_count` is 0; unmatched candidates are counted in `excluded_product_count` and have no effect whatsoever on `index_bp`."
    Design: Difficulty/dual_variant_calc/price_index_matched_basket_vs_imputed_full_catalog_divergence
    """
    scenario = _three_product_basket()
    market_id = scenario["market"]["id"]

    report = _report(market_id, "MATCHED_BASKET", market_version(market_id))

    assert report["index_bp"] == 9743, (
        f"MATCHED_BASKET over ratios 9615 (w 10000) and 10000 (w 5000) must be 9743, "
        f"got {report['index_bp']}"
    )
    assert report["candidate_product_count"] == 3
    assert report["matched_product_count"] == 2
    assert report["imputed_product_count"] == 0
    assert report["excluded_product_count"] == 1, (
        "the unmatched third product must be counted as excluded, got "
        f"{report['excluded_product_count']}"
    )
    assert report["positioning_gap_bp"] == -57, (
        f"9743 less the 9800 target is -57, got {report['positioning_gap_bp']}"
    )
    assert report["positioning_verdict"] == "ON_TARGET", (
        "abs(-57) is within the 150 bp tolerance, so ON_TARGET"
    )
    assert report["data_sufficiency"] == "SUFFICIENT"
    assert report["status"] == "DRAFT"


def test_imputed_full_catalog_pulls_the_unmatched_candidate_in_at_the_median_ratio():
    """IMPUTED_FULL_CATALOG imputes the 9808 bp median onto P3, landing on 9760 bp.

    PRD: "Every unmatched candidate then enters the basket carrying that single imputed ratio, and `imputed_product_count` is `candidate_product_count` less `matched_product_count`."
    Design: Difficulty/dual_variant_calc/price_index_matched_basket_vs_imputed_full_catalog_divergence
    """
    scenario = _three_product_basket()
    market_id = scenario["market"]["id"]

    report = _report(market_id, "IMPUTED_FULL_CATALOG", market_version(market_id))

    assert report["index_bp"] == 9760, (
        "the unmatched product enters at the 9808 bp median of ratios 9615 and 10000, "
        f"so the index must be 9760, got {report['index_bp']}"
    )
    assert report["candidate_product_count"] == 3
    assert report["matched_product_count"] == 2
    assert report["imputed_product_count"] == 1, (
        f"3 candidates less 2 matched is 1 imputed, got {report['imputed_product_count']}"
    )
    assert report["excluded_product_count"] == 0, (
        "nothing is left out under IMPUTED_FULL_CATALOG, got "
        f"{report['excluded_product_count']}"
    )
    assert report["positioning_gap_bp"] == -40, (
        f"9760 less the 9800 target is -40, got {report['positioning_gap_bp']}"
    )
    assert report["data_sufficiency"] == "SUFFICIENT"
    assert report["status"] == "DRAFT"


def test_the_two_index_bases_diverge_by_17_bp_on_one_identical_basket():
    """Both bases run over one basket: 9743 versus 9760, a 17 bp divergence.

    PRD: "The two variants genuinely differ on identical data: one fixture yields 9743 basis points under `MATCHED_BASKET` and 9760 basis points under `IMPUTED_FULL_CATALOG`."
    Design: Difficulty/dual_variant_calc/price_index_matched_basket_vs_imputed_full_catalog_divergence
    """
    scenario = _three_product_basket()
    market_id = scenario["market"]["id"]

    version_before_first = market_version(market_id)
    matched = _report(market_id, "MATCHED_BASKET", version_before_first)
    version_before_second = market_version(market_id)
    imputed = _report(market_id, "IMPUTED_FULL_CATALOG", version_before_second)

    assert matched["index_bp"] == 9743
    assert imputed["index_bp"] == 9760
    assert imputed["index_bp"] - matched["index_bp"] == 17, (
        "the two bases must differ by 17 bp on identical data, got "
        f"{imputed['index_bp'] - matched['index_bp']}"
    )
    assert version_before_second == version_before_first + 1, (
        "creating a report bumps the market version by exactly 1"
    )
    market = read_market(market_id)
    assert market["version"] == version_before_second + 1, (
        f"the second report creation must bump the market version again, got "
        f"{market['version']}"
    )
    assert market["observed_index_bp"] is None, (
        "neither report was published, so the market carries no observed index yet"
    )
    assert market["pricing_posture"] == "OPEN"


def _two_product_basket():
    """US-EAST COFFEE basket of exactly two benchmarked products.

    P1 own 24999 weight 10000 against 25999 -> unrounded ratio 9615.3675...
    P2 own  9999 weight  5000 against  9999 -> exactly 10000.
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-EAST",
        name="US East",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    p1 = _coffee_product(market["id"], "SKU-COFFEE-1", 24999, 15000, 10000)
    p2 = _coffee_product(market["id"], "SKU-COFFEE-2", 9999, 5000, 5000)
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    l1 = _confirmed_link_with_observation(p1["id"], competitor["id"], "00712345678901", 25999)
    l2 = _confirmed_link_with_observation(p2["id"], competitor["id"], "00712345678902", 9999)
    return {"market": market, "p1": p1, "p2": p2, "l1": l1, "l2": l2}


def test_each_product_ratio_is_rounded_before_the_weighted_average_is_taken():
    """Rounding per product first pins the index at 9743, not the 9744 of one round.

    PRD: "**The rounding order here is pinned and must not be rearranged:** each product's ratio is rounded to a whole basis point first, and the weighted average of those already-rounded ratios is rounded second."
    Design: Difficulty/combinatorial_formula/price_index_round_per_product_then_average_order
    """
    scenario = _two_product_basket()
    market_id = scenario["market"]["id"]

    report = _report(market_id, "MATCHED_BASKET", market_version(market_id))

    assert read_match(scenario["l1"]["id"])["gap_bp"] == 9615, (
        "24999 * 10000 / 25999 rounds half up to 9615 at the per-product step"
    )
    assert read_match(scenario["l2"]["id"])["gap_bp"] == 10000
    assert report["index_bp"] == 9743, (
        "(9615 * 10000 + 10000 * 5000) / 15000 rounds half up to 9743, got "
        f"{report['index_bp']}"
    )
    assert report["matched_product_count"] == 2
    assert report["excluded_product_count"] == 0


def test_averaging_the_unrounded_ratios_would_give_the_wrong_index():
    """The one-rounding-at-the-end algorithm yields 9744 and must not be used.

    PRD: "Averaging unrounded ratios and rounding once at the end is a different algorithm and is not what this service computes."
    Design: Difficulty/combinatorial_formula/price_index_round_per_product_then_average_order
    """
    scenario = _two_product_basket()
    market_id = scenario["market"]["id"]

    report = _report(market_id, "MATCHED_BASKET", market_version(market_id))

    assert report["index_bp"] != 9744, (
        "9744 is what averaging the unrounded ratios and rounding once produces; "
        "the service must round each product ratio first"
    )
    assert report["index_bp"] == 9743
    assert report["candidate_product_count"] == 2
    assert report["imputed_product_count"] == 0
    assert report["data_sufficiency"] == "SUFFICIENT"
    assert report["perception_survey_index_bp"] is None
    assert report["perception_validation"] == "INDETERMINATE", (
        "no perception survey accompanied the report, so validation is INDETERMINATE"
    )
