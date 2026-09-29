"""Match confidence scoring: the IDENTIFIER_ANCHORED / ATTRIBUTE_BLEND fork.

Every test here drives the identical agreement-score triple (identifier 92,
attribute 40, image 30) down both confidence variants and pins the divergence
the PRD declares for it.
"""
from test_helpers import (
    ANALYST,
    api_client,
    new_competitor,
    new_market,
    new_product,
    set_clock,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


def _two_competitor_fixture():
    """Clock + market US-WEST + one ACTIVE product + two ACTIVE PRIMARY banners."""
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    product = new_product(
        market["id"],
        sku="SKU-BLENDER-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=24999,
        unit_cost_cents=15000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    alpha = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    beta = new_competitor(
        market["id"],
        competitor_code="C-BETA",
        name="Beta Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    return market, product, alpha, beta


def _propose_anchored(product_id, competitor_id):
    """IDENTIFIER channel with identifier_score 92 -> IDENTIFIER_ANCHORED."""
    return validate_success(
        api_client.create_match(
            {
                "product_id": product_id,
                "competitor_id": competitor_id,
                "match_method": "IDENTIFIER",
                "identifier_score": 92,
                "attribute_score": 40,
                "image_score": 30,
                "competitor_identifier": "00712345678905",
            },
            ANALYST,
        ),
        201,
    )


def _propose_blend(product_id, competitor_id):
    """ATTRIBUTE channel with the same three scores -> ATTRIBUTE_BLEND."""
    return validate_success(
        api_client.create_match(
            {
                "product_id": product_id,
                "competitor_id": competitor_id,
                "match_method": "ATTRIBUTE",
                "identifier_score": 92,
                "attribute_score": 40,
                "image_score": 30,
            },
            ANALYST,
        ),
        201,
    )


def test_identifier_anchored_variant_anchors_confidence_at_9700_bp_exact():
    """An IDENTIFIER match scoring 92 anchors to 9700 bp and grades EXACT.

    PRD: "It computes an anchored figure by multiplying `identifier_score` by 100 and adding a 500-basis-point anchor bonus, takes whichever is larger of that anchored figure and the blend, and caps the result at 10000 basis points."
    Design: Difficulty/dual_variant_calc/confidence_variant_identifier_anchored_vs_attribute_blend
    """
    _market, product, alpha, _beta = _two_competitor_fixture()

    link = _propose_anchored(product["id"], alpha["id"])

    assert link["confidence_variant"] == "IDENTIFIER_ANCHORED", (
        "match_method IDENTIFIER with identifier_score 92 (>= 90) must take the "
        f"anchored variant, got {link['confidence_variant']}"
    )
    assert link["confidence_bp"] == 9700, (
        f"anchored confidence must be 9700 bp, got {link['confidence_bp']}"
    )
    assert link["match_grade"] == "EXACT", (
        f"9700 bp is at least 8500 so the grade must be EXACT, got {link['match_grade']}"
    )
    assert link["status"] == "PROPOSED"
    assert link["review_round"] == 0


def test_attribute_blend_variant_caps_the_same_scores_at_6000_bp_close():
    """The same score triple on the ATTRIBUTE channel is capped at 6000 bp / CLOSE.

    PRD: "It uses the plain blend, and it applies one penalty: when `image_score` is below 50, the result is capped at 6000 basis points; otherwise the result is simply capped at 10000."
    Design: Difficulty/dual_variant_calc/confidence_variant_identifier_anchored_vs_attribute_blend
    """
    _market, product, _alpha, beta = _two_competitor_fixture()

    link = _propose_blend(product["id"], beta["id"])

    assert link["confidence_variant"] == "ATTRIBUTE_BLEND", (
        "match_method ATTRIBUTE must take the blend variant, got "
        f"{link['confidence_variant']}"
    )
    assert link["confidence_bp"] == 6000, (
        f"the low-image ceiling must clamp the blend to 6000 bp, got {link['confidence_bp']}"
    )
    assert link["confidence_bp"] != 6710, (
        "6710 is the raw blend 55*92 + 30*40 + 15*30; image_score 30 is below 50 so "
        "the low-image ceiling must apply"
    )
    assert link["match_grade"] == "CLOSE", (
        f"6000 bp is at least 6000 but below 8500, so CLOSE, got {link['match_grade']}"
    )
    assert link["status"] == "PROPOSED"
    assert link["review_round"] == 0


def test_confidence_diverges_by_3700_bp_on_identical_agreement_scores():
    """Identical scores fork 3700 bp apart, driven only by match_method.

    PRD: "The difference is not cosmetic — scores of 92 on identifier, 40 on attribute and 30 on image yield 9700 basis points under `IDENTIFIER_ANCHORED` and 6000 basis points under `ATTRIBUTE_BLEND`."
    Design: Difficulty/dual_variant_calc/confidence_variant_identifier_anchored_vs_attribute_blend
    """
    _market, product, alpha, beta = _two_competitor_fixture()

    anchored = _propose_anchored(product["id"], alpha["id"])
    blended = _propose_blend(product["id"], beta["id"])

    for field in ("identifier_score", "attribute_score", "image_score"):
        assert anchored[field] == blended[field], (
            f"the two links must carry identical evidence on {field}"
        )
    assert anchored["confidence_bp"] == 9700
    assert blended["confidence_bp"] == 6000
    assert anchored["confidence_bp"] - blended["confidence_bp"] == 3700, (
        "the variant fork must move confidence by 3700 bp on identical scores, got "
        f"{anchored['confidence_bp'] - blended['confidence_bp']}"
    )
    assert anchored["match_grade"] == "EXACT"
    assert blended["match_grade"] == "CLOSE"
