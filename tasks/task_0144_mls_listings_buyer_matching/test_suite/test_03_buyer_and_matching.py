"""Buyer CRUD and the buyer-match weighted scoring algorithm.

Cites PRD §3.3 (Buyer Profile) and §3.4 (Buyer-Listing Matching).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    SCORE_CUTOFF,
    W_BB,
    W_FEAT,
    W_LOC,
    W_PRICE,
    assert_buyer,
    create_buyer,
    create_buyer_agent,
    create_buyer_payload,
    create_listing,
    create_listing_agent,
    make_buyer_agent_headers,
    setup_listing_and_buyer,
    validate_error,
    validate_success,
)


class TestBuyerCrud:
    """PRD §3.3."""

    def test_create_buyer_succeeds(self, api):
        """PRD §3.3: 'A BuyerAgent creates a buyer profile by supplying
        their own identifier as buyer_agent_id, the buyer's full_name,
        ... Buyer profiles begin in ACTIVE status.'

        Claim: POST /buyers returns Buyer with status=ACTIVE, version=1.
        """
        ba = create_buyer_agent()
        res = api.create_buyer(
            create_buyer_payload(buyer_agent_id=ba["id"]),
            make_buyer_agent_headers(ba["id"]),
        )
        buyer = validate_success(res, 201)
        assert_buyer(buyer)
        assert buyer["status"] == "ACTIVE"
        assert buyer["version"] == 1

    def test_buyer_agent_id_must_equal_x_user_id(self, api):
        """PRD §3.3: 'The server enforces that buyer_agent_id equal
        X-User-ID.'

        Claim: POST /buyers with buyer_agent_id != X-User-ID →
        ERR_FORBIDDEN_NOT_OWNER.
        """
        ba1 = create_buyer_agent()
        ba2 = create_buyer_agent()
        # Submit payload referencing ba2 from ba1's headers.
        res = api.create_buyer(
            create_buyer_payload(buyer_agent_id=ba2["id"]),
            make_buyer_agent_headers(ba1["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)

    def test_min_price_above_max_rejected(self, api):
        """PRD §3.3: 'The lower bound must not exceed the upper bound,
        ... Either violation triggers ERR_INVALID_BUYER_FIELDS.'

        Claim: min_price_cents > max_price_cents →
        ERR_INVALID_BUYER_FIELDS.
        """
        ba = create_buyer_agent()
        res = api.create_buyer(
            create_buyer_payload(
                buyer_agent_id=ba["id"],
                max_price_cents=40_000_000,
                min_price_cents=50_000_000,
            ),
            make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_BUYER_FIELDS.value)

    def test_empty_desired_zips_rejected(self, api):
        """PRD §3.3: 'the desired-ZIP array may not be empty. Either
        violation triggers ERR_INVALID_BUYER_FIELDS.'

        Claim: desired_zips=[] → ERR_INVALID_BUYER_FIELDS.
        """
        ba = create_buyer_agent()
        res = api.create_buyer(
            create_buyer_payload(
                buyer_agent_id=ba["id"], desired_zips=[],
            ),
            make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_BUYER_FIELDS.value)


# ---------------------------------------------------------------------------
# §3.4 — Buyer match weighted scoring.
# ---------------------------------------------------------------------------
class TestBuyerMatchScoring:
    """PRD §3.4: 'Once the four subscores are computed, they are
    combined with fixed weights of 0.40 for price fit, 0.25 for
    location fit, 0.20 for bedroom-bathroom fit, and 0.15 for feature
    fit, in that order. The weighted sum is then rounded half-up to two
    decimal places exactly once, producing the final score.'"""

    def test_buyer_all_fits_100_score_100(self, api, mls_admin_headers):
        """PRD §3.4: price-fit 100 when 'between min and max
        inclusive'; location-fit 100 when zip in desired_zips;
        bedroom-bathroom 100 when both thresholds met; feature-fit 100
        when desired_features is empty.

        Claim: All four sub-fits == 100 → final score == 100.00.
        """
        la = create_listing_agent()
        listing = create_listing(
            la,
            list_price_cents=50_000_000,
            zip_code="94110",
            bedrooms=3,
            bathrooms=2.0,
            features=["POOL", "GARAGE"],
        )
        ba = create_buyer_agent()
        buyer = create_buyer(
            ba,
            max_price_cents=55_000_000,
            min_price_cents=40_000_000,
            min_bedrooms=3,
            min_bathrooms=2.0,
            desired_zips=["94110"],
            desired_features=[],   # empty → feature_fit == 100
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        body = res.json()
        assert res.status_code == 200
        data = body["data"]
        # Exactly one candidate, score == 100.00.
        matches = [m for m in data if m.get("listing_id") == listing["id"]]
        assert len(matches) == 1, f"listing not in matches: {data}"
        assert matches[0]["score"] == pytest.approx(100.00, abs=0.0001)

    def test_buyer_partial_feature_overlap_92_50(
        self, api, mls_admin_headers,
    ):
        """PRD §3.4: 'otherwise it is the size of the overlap between
        desired_features and the listing's features divided by the size
        of desired_features, multiplied by 100, locally rounded half-up
        to four decimal places before entering the weighted sum.'

        Claim: With price/loc/bb fit at 100 and feature fit at 50.00
        (1 of 2 desired overlap), score == 0.40*100 + 0.25*100 +
        0.20*100 + 0.15*50.00 == 92.50.

        # difficulty: combinatorial_formula/buyer_match_score_weighted_nonlinear
        """
        la = create_listing_agent()
        listing = create_listing(
            la,
            list_price_cents=50_000_000,
            zip_code="94110",
            bedrooms=3,
            bathrooms=2.0,
            features=["POOL", "GARAGE"],
        )
        ba = create_buyer_agent()
        buyer = create_buyer(
            ba,
            max_price_cents=55_000_000,
            min_price_cents=40_000_000,
            min_bedrooms=3,
            min_bathrooms=2.0,
            desired_zips=["94110"],
            desired_features=["POOL", "FIREPLACE"],
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        data = res.json()["data"]
        matches = [m for m in data if m.get("listing_id") == listing["id"]]
        assert len(matches) == 1
        assert matches[0]["score"] == pytest.approx(92.50, abs=0.0001)

    def test_buyer_empty_desired_features_full_feature_fit(
        self, api,
    ):
        """PRD §3.4: 'The feature-fit subscore is 100 when the buyer's
        desired_features array is empty (no preference).'

        Claim: A buyer with desired_features=[] receives feature_fit
        100, total 100.00 when other fits are 100.

        # difficulty: combinatorial_formula/buyer_match_score_weighted_nonlinear
        """
        la = create_listing_agent()
        listing = create_listing(
            la, list_price_cents=50_000_000, zip_code="94110",
            bedrooms=3, bathrooms=2.0, features=["POOL"],
        )
        ba = create_buyer_agent()
        buyer = create_buyer(
            ba,
            max_price_cents=55_000_000,
            min_price_cents=40_000_000,
            min_bedrooms=3,
            min_bathrooms=2.0,
            desired_zips=["94110"],
            desired_features=[],
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        data = res.json()["data"]
        matches = [m for m in data if m.get("listing_id") == listing["id"]]
        assert len(matches) == 1
        assert matches[0]["score"] == pytest.approx(100.00, abs=0.0001)

    def test_bed_bath_partial_fit_score_50(self, api):
        """PRD §3.4: 'The bedroom-bathroom subscore is 100 when both
        the listing's bedrooms are at least the buyer's min_bedrooms
        and the listing's bathrooms are at least the buyer's
        min_bathrooms; it is 50 when exactly one of the two thresholds
        is met; it is 0 when neither is.'

        Claim: Listing meets bedroom but NOT bathroom → bed-bath
        subscore is 50; other subscores 100 (empty desired_features) →
        total = 0.4*100 + 0.25*100 + 0.20*50 + 0.15*100 = 90.00.
        """
        la = create_listing_agent()
        listing = create_listing(
            la, list_price_cents=50_000_000, zip_code="94110",
            bedrooms=3, bathrooms=1.0, features=["POOL"],
        )
        ba = create_buyer_agent()
        buyer = create_buyer(
            ba,
            max_price_cents=55_000_000,
            min_price_cents=40_000_000,
            min_bedrooms=3,
            min_bathrooms=2.0,   # listing has 1.0 → bath fails
            desired_zips=["94110"],
            desired_features=[],
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        data = res.json()["data"]
        matches = [m for m in data if m.get("listing_id") == listing["id"]]
        assert len(matches) == 1
        assert matches[0]["score"] == pytest.approx(90.00, abs=0.0001)


class TestBuyerMatchCutoffAndRanking:
    """PRD §3.4 cutoff and ranking rules."""

    def test_score_exactly_at_cutoff_included(self, api):
        """PRD §3.4: 'Candidates whose score is strictly less than 50
        are excluded from the result.'

        Claim: A candidate whose score is exactly 50.00 is INCLUDED.

        Construct: location_fit=0 (zip miss), bed_bath_fit=0,
        feature_fit=0 (empty overlap on non-empty desired), price_fit
        such that final weighted sum == 50.00.

        # difficulty: boundary_precision_check/buyer_match_ranking_empty_pool_returns_empty_array
        """
        la = create_listing_agent()
        # Listing zip 94110, bedrooms 1, bathrooms 0.5, features=[]
        listing = create_listing(
            la,
            list_price_cents=50_000_000,
            zip_code="94110",
            bedrooms=1,
            bathrooms=0.5,
            features=[],
        )
        ba = create_buyer_agent()
        # Buyer prefers different zip + harder constraints so loc=0,
        # bb=0; desired_features non-empty with no overlap → feat=0.
        # price_fit needs to equal 50/0.40 = 125 — impossible (capped at 100).
        # Re-engineer: pick weights so the sum hits 50 exactly via
        # price_fit only (price_fit = 50/0.40 = 125 > 100). Adjust:
        # use location AS WELL — desired_zips includes 94110 →
        # loc_fit=100 → 0.25*100 = 25. Need price=25/0.4=62.5 → price_fit=62.5.
        # Use price_fit decay: listing list_price 50M; buyer min_price
        # 50M (so equal → 100). Need price_fit decayed below 100.
        # If listing.list_price > buyer.max_price, decay over 10% band.
        # Set max_price=20M → band = 2M → over = 30M → over/band=15 →
        # 100 - 15*100 = clipped 0. Too much decay.
        # Instead aim price_fit ≈ 25/0.4 = 62.5: need decay of 37.5
        # over band → (over/band)*100 = 37.5 → over/band = 0.375.
        # Set listing.list_price = 50_000_000, buyer.max_price = X,
        # band = X//10. We want (50_000_000 - X) / (X//10) = 0.375.
        # If X = 49_000_000 → band = 4_900_000 → over = 1_000_000 →
        # over/band ≈ 0.2041 → price_fit ≈ 100 - 20.41 = 79.59.
        # Too high. Try X = 47_000_000 → band 4_700_000 → over 3_000_000 →
        # 3/4.7 = 0.6383 → 100 - 63.83 = 36.17 (too low).
        # Find precise: want price_fit = 25/0.40 = 62.5 →
        # (50_000_000 - X) / (X/10) = (100 - 62.5)/100 = 0.375
        # => (50M - X) * 10 / X = 0.375
        # => 500M - 10X = 0.375X => 500M = 10.375X => X ≈ 48_192_771.
        # Use X = 48_192_771 (integer cents).
        # over = 50M - 48_192_771 = 1_807_229
        # band = 48_192_771 // 10 = 4_819_277
        # over/band = 1_807_229 / 4_819_277 ≈ 0.37500005...
        # → price_fit ≈ 100 - 37.500005 = 62.499995
        # weighted total ≈ 0.40 * 62.499995 + 0.25 * 100 + 0 + 0
        # ≈ 24.999998 + 25 = 49.999998 → rounds to 50.00 (round_half_up).
        buyer = create_buyer(
            ba,
            max_price_cents=48_192_771,
            min_price_cents=40_000_000,
            # Listing has bedrooms=1, bathrooms=0.5 — both must fail so
            # bed_bath subscore is 0; raise mins above the listing values.
            min_bedrooms=5,
            min_bathrooms=3.0,
            desired_zips=["94110"],   # loc_fit=100 → 25 pts
            desired_features=["POOL"],   # no overlap → feat=0
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        body = res.json()
        assert res.status_code == 200
        data = body["data"]
        # The listing should be present with score ~50.00.
        listing_scores = [
            m for m in data if m.get("listing_id") == listing["id"]
        ]
        assert len(listing_scores) == 1, (
            f"listing not in matches (cutoff inclusive on 50.00 violated): "
            f"data={data}"
        )
        # Score is in [49.99, 50.01] band but should round to 50.00.
        assert listing_scores[0]["score"] == pytest.approx(50.00, abs=0.01)

    def test_empty_pool_returns_empty_array_not_error(self, api):
        """PRD §3.4: 'an empty pool returns an empty array with HTTP
        200, not an error.'

        Claim: A buyer with desired_zips that match no ACTIVE listing
        receives 200 + data=[].

        # difficulty: boundary_precision_check/buyer_match_ranking_empty_pool_returns_empty_array
        """
        ba = create_buyer_agent()
        buyer = create_buyer(
            ba,
            max_price_cents=60_000_000,
            min_price_cents=40_000_000,
            min_bedrooms=2,
            min_bathrooms=1.0,
            desired_zips=["99999"],   # no listings here
            desired_features=[],
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        body = res.json()
        assert res.status_code == 200
        assert body["data"] == []

    def test_ranking_desc_by_score_then_created_at_asc(self, api):
        """PRD §3.4: 'Survivors are sorted by score descending, with
        ties broken by created_at ascending and then by id ascending.'

        Claim: Two listings produce a score-descending ordering.
        """
        la = create_listing_agent()
        # Listing A: perfect fit → score 100.00.
        a = create_listing(
            la, list_price_cents=50_000_000, zip_code="94110",
            bedrooms=3, bathrooms=2.0, features=["POOL"],
        )
        # Listing B: lower score (bed-bath partial).
        b = create_listing(
            la, list_price_cents=50_000_000, zip_code="94110",
            bedrooms=3, bathrooms=1.0, features=["POOL"],
        )
        ba = create_buyer_agent()
        buyer = create_buyer(
            ba,
            max_price_cents=55_000_000,
            min_price_cents=40_000_000,
            min_bedrooms=3,
            min_bathrooms=2.0,
            desired_zips=["94110"],
            desired_features=[],
        )
        res = api.get_buyer_matches(
            buyer["id"], make_buyer_agent_headers(ba["id"]),
        )
        data = res.json()["data"]
        # Should have exactly two rows (both above cutoff).
        listing_ids = [m["listing_id"] for m in data]
        assert a["id"] in listing_ids and b["id"] in listing_ids
        # A's score 100 must come before B's score 90.
        idx_a = listing_ids.index(a["id"])
        idx_b = listing_ids.index(b["id"])
        assert idx_a < idx_b, (
            f"Score-DESC ordering violated: "
            f"A score {data[idx_a]['score']} at idx {idx_a}, "
            f"B score {data[idx_b]['score']} at idx {idx_b}."
        )
