"""Quote pricing: dual-variant LOCKED vs SPOT, pinned rounding order, freight
surcharge tiers, market-regime classification, and quote-create rejections.

Covers PRD §3.3 (indices, regimes, freight lanes) and §3.5 (quote pricing).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_buyer,
    create_draft_quote,
    create_freight_lane,
    create_market_index,
    issue_quote,
    make_buyer_headers,
    setup_pricing_bed,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# dual_variant_calc / locked_vs_spot_quote_pricing
# ===========================================================================

class TestLockedVsSpotQuotePricing:
    def _setup_locked_then_spot(self):
        """idx1 @20000 -> q1 ISSUED (pins idx1) -> idx2 @23200 (DROUGHT) -> q2 DRAFT.

        idx2's effective date stays inside the 30-day regime lookback of
        idx1's 2026-05-01 (PRD §3.3: "strictly earlier than the new index's
        date but no more than 30 days before it"), so the +16% move is
        actually classified against idx1.
        """
        idx1, lane = setup_pricing_bed(index_price=20000)
        buyer = create_buyer(credit_limit_cents=10000000)
        q1 = create_draft_quote(
            buyer["id"], quality_tier="PREMIUM", tons=12.0,
        )
        q1_issued = issue_quote(q1["id"], buyer["id"])
        idx2 = create_market_index(effective_date="2026-05-20",
                                   price_per_ton_cents=23200)
        q2 = create_draft_quote(
            buyer["id"], quality_tier="PREMIUM", tons=12.0,
        )
        return idx1, idx2, buyer, q1_issued, q2

    def test_locked_quote_keeps_pinned_index_and_total(self, api):
        """PRD §3.5: "Issue runs the **locked variant** of pricing: the system pins
        `pinned_market_index_id` to the latest market index for the origin region
        and forage type effective on or before the current clock date, recomputes
        and freezes `unit_price_cents`, `commodity_cents`, `freight_cents`, and
        `total_cents`".

        q1 pins idx1 @20000: unit round(20000 x 1.15) = 23000; freight on the
        420-mile lane is 163170 (base 147000 + 11% surcharge 16170); total
        23000 x 12 + 163170 = 439170.

        Design: Difficulty/dual_variant_calc/locked_vs_spot_quote_pricing
        """
        idx1, _idx2, buyer, q1_issued, _q2 = self._setup_locked_then_spot()
        assert q1_issued["pinned_market_index_id"] == idx1["id"]
        assert q1_issued["unit_price_cents"] == 23000
        assert q1_issued["total_cents"] == 439170

    def test_spot_quote_reprices_off_newer_drought_index(self, api):
        """PRD §3.5: "identical quote inputs yield different totals once a newer
        index posts, because a re-issued quote pins afresh while an untouched
        issued quote keeps its frozen numbers." PRD §3.3: "An increase of at
        least 15 percent — exactly plus 15 percent qualifies — classifies the
        new index as `DROUGHT`."

        idx2 = 23200 vs 20000 is +16% -> DROUGHT, so SPOT pricing adds the 5%
        surcharge: unit round(23200 x 1.15 x 1.05) = 28014; q2 total
        28014 x 12 + 163170 = 499338, diverging from q1's frozen 439170.

        Design: Difficulty/dual_variant_calc/locked_vs_spot_quote_pricing
        """
        _idx1, idx2, buyer, q1_issued, q2 = self._setup_locked_then_spot()
        assert idx2["drought_regime"] == "DROUGHT"
        assert q2["unit_price_cents"] == 28014
        assert q2["total_cents"] == 499338
        assert q2["total_cents"] != q1_issued["total_cents"]


# ===========================================================================
# combinatorial_formula / quote_unit_rounding_order_pinned
# ===========================================================================

class TestQuoteUnitRoundingOrderPinned:
    def _create_rounding_probe_quote(self):
        """idx @20050 STABLE; lane 80mi min 90000; DRAFT PREMIUM 10.0t quote."""
        create_market_index(price_per_ton_cents=20050)
        create_freight_lane(distance_miles=80)
        buyer = create_buyer(credit_limit_cents=5000000)
        return create_draft_quote(buyer["id"], quality_tier="PREMIUM", tons=10.0)

    def test_unit_price_rounded_before_tonnage_multiplication(self, api):
        """PRD §3.5: "the per-ton result is rounded half-up to whole cents *first*,
        yielding `unit_price_cents`, and only then multiplied by `tons` to give
        `commodity_cents` in integer math."

        20050 x 1.15 = 23057.5 rounds to 23058 BEFORE multiplication, so
        commodity is 23058 x 10 = 230580 (the multiply-then-round order would
        give 230575 — that order is non-conformant per PRD §2.8).

        Design: Difficulty/combinatorial_formula/quote_unit_rounding_order_pinned
        """
        quote = self._create_rounding_probe_quote()
        assert quote["unit_price_cents"] == 23058
        assert quote["commodity_cents"] == 230580

    def test_freight_min_charge_floor_and_total(self, api):
        """PRD §3.3: "the base charge is the lane's `min_charge_cents` or the
        per-mile rate multiplied by the distance rounded half-up to whole cents,
        whichever is greater."

        80mi x 350c = 28000 < 90000 minimum -> base floors at 90000; under 100
        miles pays no fuel surcharge, so freight_cents == 90000 and total_cents
        == 230580 + 90000 = 320580.

        Design: Difficulty/combinatorial_formula/quote_unit_rounding_order_pinned
        """
        quote = self._create_rounding_probe_quote()
        assert quote["freight_cents"] == 90000
        assert quote["total_cents"] == 320580


# ===========================================================================
# Corner/calculations / freight_surcharge_tier_boundaries_299_300
# ===========================================================================

def test_freight_surcharge_tier_flips_at_300_miles(api):
    """PRD §3.3: "A fuel surcharge then applies by distance tier: no surcharge
    under 100 miles; 6 percent of the base when the distance is at least 100
    but under 300 miles — the entire range 100 through 299 miles pays 6
    percent; and 11 percent of the base at 300 miles or more."

    Two otherwise-identical 1.0t GOOD quotes: the 299-mile lane computes base
    104650 + 6% (6279) = 110929 freight (total 130929); the 300-mile lane
    computes base 105000 + 11% (11550) = 116550 freight (total 136550).

    Design: Corner/calculations/freight_surcharge_tier_boundaries_299_300
    """
    create_market_index()
    create_freight_lane(distance_miles=299)
    create_freight_lane(dest_region_code="CA-CENTRAL", distance_miles=300)
    buyer = create_buyer(credit_limit_cents=5000000)

    q299 = create_draft_quote(buyer["id"], quality_tier="GOOD", tons=1.0)
    assert q299["freight_cents"] == 110929
    assert q299["total_cents"] == 130929

    q300 = create_draft_quote(
        buyer["id"], quality_tier="GOOD", tons=1.0,
        dest_region_code="CA-CENTRAL",
    )
    assert q300["freight_cents"] == 116550
    assert q300["total_cents"] == 136550


# ===========================================================================
# Corner/calculations / market_regime_boundary_classifications
# ===========================================================================

def test_market_regime_boundary_classifications(api):
    """PRD §3.3: "An increase of at least 15 percent — exactly plus 15 percent
    qualifies — classifies the new index as `DROUGHT`. Failing that, a move of
    at least 8 percent in either direction — exactly plus or minus 8 percent
    qualifies — classifies it as `VOLATILE`. Anything smaller is `STABLE`."
    PRD §3.3: "When no such prior index exists in that 30-day lookback, the
    new index's `drought_regime` is `STABLE`."

    Base postings at 20000 classify STABLE; +15.0% (23000) classifies DROUGHT;
    +14.5% (22900) classifies VOLATILE.

    Design: Corner/calculations/market_regime_boundary_classifications
    """
    base_a = create_market_index()
    base_g = create_market_index(forage_type="GRASS")
    assert base_a["drought_regime"] == "STABLE"
    assert base_g["drought_regime"] == "STABLE"

    drought = create_market_index(effective_date="2026-05-20",
                                  price_per_ton_cents=23000)
    volatile = create_market_index(forage_type="GRASS",
                                   effective_date="2026-05-20",
                                   price_per_ton_cents=22900)
    assert drought["drought_regime"] == "DROUGHT"
    assert volatile["drought_regime"] == "VOLATILE"


# ===========================================================================
# Corner/validations / quote-create rejections
# ===========================================================================

def test_ungraded_tier_quote_rejected(api):
    """PRD §3.5: "the value `UNGRADED` passes schema validation as a member of
    the enumeration but is rejected by the business rule with
    `ERR_UNGRADED_TIER`, since ungraded hay cannot be quoted."

    Design: Corner/validations/ungraded_tier_quote_rejected
    """
    setup_pricing_bed()
    buyer = create_buyer()
    resp = api_client.create_quote(
        {
            "buyer_id": buyer["id"], "forage_type": "ALFALFA",
            "quality_tier": "UNGRADED", "tons": 5.0,
            "origin_region_code": "OR-WILLAMETTE",
            "dest_region_code": "CA-NORTH",
            "requested_delivery_by": "2026-08-20",
        },
        make_buyer_headers(buyer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNGRADED_TIER)


def test_quote_without_market_index_rejected(api):
    """PRD §3.5: "a market index effective on or before the pricing date must
    exist for the quote's origin region and forage type, otherwise
    `ERR_NO_MARKET_INDEX`".

    Design: Corner/validations/quote_without_market_index_rejected
    """
    create_freight_lane()
    buyer = create_buyer()
    quote = create_quote_for_error(buyer["id"])
    validate_error(quote, ApiErrorId.ERR_NO_MARKET_INDEX)


def test_quote_without_freight_lane_rejected(api):
    """PRD §3.5: "and a freight lane must exist for the origin-destination
    pair, otherwise `ERR_NO_FREIGHT_LANE`."

    Design: Corner/validations/quote_without_freight_lane_rejected
    """
    create_market_index()
    buyer = create_buyer()
    quote = create_quote_for_error(buyer["id"])
    validate_error(quote, ApiErrorId.ERR_NO_FREIGHT_LANE)


def create_quote_for_error(buyer_id):
    """POST a syntactically valid GOOD quote as the buyer and return the raw
    response (expected to be a pricing-lookup error)."""
    return api_client.create_quote(
        {
            "buyer_id": buyer_id, "forage_type": "ALFALFA",
            "quality_tier": "GOOD", "tons": 5.0,
            "origin_region_code": "OR-WILLAMETTE",
            "dest_region_code": "CA-NORTH",
            "requested_delivery_by": "2026-08-20",
        },
        make_buyer_headers(buyer_id),
    )
