"""Salvage bales: estimate vs settlement variants, seal gates, RBAC, pipeline."""
import pytest

from test_helpers import (
    ApiErrorId,
    MGR,
    create_cycle,
    create_recycle_bale,
    create_vendor,
    find_accumulating_bale,
    flat_rate_vendor,
    make_finance_clerk_headers,
    seal_bale,
    ship_bale,
    settle_bale,
    validate_error,
    validate_success,
)

TEXTILES_TIERED_RATES = [{
    "category": "TEXTILES",
    "brackets": [
        {"up_to_lbs": 500, "rate_cents_per_lb": 12},
        {"up_to_lbs": 2000, "rate_cents_per_lb": 10},
        {"up_to_lbs": None, "rate_cents_per_lb": 8},
    ],
}]


class TestBaleEstimateVsSettlement:
    def test_bale_estimate_vs_settlement(self, api):
        """PRD 3.5: "Estimate and settlement genuinely diverge by design: a TEXTILES
        bale at 2500 pounds under a 12/10/8 bracket sheet reads a post-seal estimate
        of 20000 cents but settles at 25000."

        Design: Difficulty/dual_variant_calc/bale_estimate_vs_settlement
        """
        vendor = create_vendor("Textile Co", TEXTILES_TIERED_RATES)
        bale, _donor, _batch, items = create_recycle_bale(
            "TEXTILES", "CLOTHING", [500.0, 500.0, 500.0, 500.0, 500.0]
        )
        assert bale["weight_lbs"] == pytest.approx(2500.0)

        sealed = seal_bale(bale["id"], vendor["id"])
        # Post-seal estimate: the bracket containing 2500 lbs (8c) x the whole weight.
        assert sealed["estimated_revenue_cents"] == 20000
        for item in items:
            after = validate_success(api.get_item(item["id"], MGR))
            assert after["status"] == "BALED", "seal cascades assigned items to BALED"

        ship_bale(bale["id"])
        cycle = create_cycle()
        settled = settle_bale(bale["id"], 2500.0)
        assert settled["status"] == "SETTLED"
        assert settled["weight_lbs"] == pytest.approx(2500.0)
        # Marginal walk: 500x12 + 1500x10 + 500x8 = 6000 + 15000 + 4000.
        assert settled["settled_revenue_cents"] == 25000
        assert settled["estimated_revenue_cents"] == 20000
        assert settled["settled_revenue_cents"] != settled["estimated_revenue_cents"]
        assert settled.get("settled_cycle_id") == cycle["id"]

    def test_flat_rate_estimate_matches_settlement(self, api):
        """PRD 3.5: "A successful seal records the vendor, sets `sealed_at`, and
        refreshes `estimated_revenue_cents` using the vendor's own sheet: the single
        bracket rate whose range contains the bale's total weight is applied to the
        whole weight, rounded half up."
        PRD 3.5: "Settlement revenue walks the vendor's brackets for the bale's
        category in ascending order: the pounds falling into each bracket are the
        smaller of the remaining weight and that bracket's width; each bracket's line
        amount is those pounds multiplied by the bracket's rate, rounded half up to
        whole cents before the next bracket is computed; and `settled_revenue_cents`
        is the sum of those per-bracket rounded lines."

        Design: Difficulty/dual_variant_calc/bale_estimate_vs_settlement
        """
        vendor = flat_rate_vendor("PAPER", 6, name="Paper Co")
        bale, _donor, _batch, _items = create_recycle_bale(
            "PAPER", "BOOKS_MEDIA", [120.0, 80.0]
        )
        assert bale["weight_lbs"] == pytest.approx(200.0)
        sealed = seal_bale(bale["id"], vendor["id"])
        assert sealed["estimated_revenue_cents"] == 1200, "200 x 6"

        ship_bale(bale["id"])
        cycle = create_cycle()
        settled = settle_bale(bale["id"], 200.0)
        assert settled["status"] == "SETTLED"
        # A single unbounded bracket makes the marginal walk agree with the estimate.
        assert settled["settled_revenue_cents"] == 1200
        assert settled.get("settled_cycle_id") == cycle["id"]


class TestSettlementPerBracketRounding:
    def test_bale_settlement_per_bracket_rounding(self, api):
        """PRD 3.5: "The alternative order — multiplying everything first and
        rounding once at the end — is rejected: an EWASTE bale at 101.0 actual pounds
        under rates of 3.353 then 2.30 cents per pound settles at 337 cents (335 from
        the first bracket line plus 2 from the second), not the 338 a single final
        rounding would produce."

        Design: Difficulty/combinatorial_formula/bale_settlement_per_bracket_rounding
        """
        vendor = create_vendor("EWaste Co", [{
            "category": "EWASTE",
            "brackets": [
                {"up_to_lbs": 100, "rate_cents_per_lb": 3.353},
                {"up_to_lbs": 500, "rate_cents_per_lb": 2.30},
                {"up_to_lbs": None, "rate_cents_per_lb": 1.10},
            ],
        }])
        bale, _donor, _batch, _items = create_recycle_bale(
            "EWASTE", "ELECTRONICS", [100.0, 1.0]
        )
        assert bale["weight_lbs"] == pytest.approx(101.0)

        sealed = seal_bale(bale["id"], vendor["id"])
        # Post-seal estimate: 101 lbs falls in the 2.30 bracket -> 232.3 -> 232.
        assert sealed["estimated_revenue_cents"] == 232

        ship_bale(bale["id"])
        create_cycle()
        settled = settle_bale(bale["id"], 101.0)
        assert settled["weight_lbs"] == pytest.approx(101.0)
        # round(100 x 3.353) + round(1 x 2.30) = 335 + 2 = 337.
        assert settled["settled_revenue_cents"] == 337

    def test_settlement_rounds_each_bracket_line_before_summing(self, api):
        """PRD 3.5: "Settlement revenue walks the vendor's brackets for the bale's
        category in ascending order: the pounds falling into each bracket are the
        smaller of the remaining weight and that bracket's width; each bracket's line
        amount is those pounds multiplied by the bracket's rate, rounded half up to
        whole cents before the next bracket is computed; and `settled_revenue_cents`
        is the sum of those per-bracket rounded lines."

        Design: Difficulty/combinatorial_formula/bale_settlement_per_bracket_rounding
        """
        vendor = create_vendor("EWaste Alt", [{
            "category": "EWASTE",
            "brackets": [
                {"up_to_lbs": 100, "rate_cents_per_lb": 3.353},
                {"up_to_lbs": None, "rate_cents_per_lb": 2.35},
            ],
        }])
        bale, _d, _b, _i = create_recycle_bale("EWASTE", "ELECTRONICS", [100.0, 1.0])
        seal_bale(bale["id"], vendor["id"])
        ship_bale(bale["id"])
        create_cycle()
        settled = settle_bale(bale["id"], 101.0)
        # Per-bracket: round(100 x 3.353)=335 + round(1 x 2.35)=2 -> 337.
        # Rounding once at the end would give round(335.3 + 2.35) = round(337.65) = 338.
        assert settled["settled_revenue_cents"] == 337


class TestBaleSealWeightBoundary:
    def test_bale_seal_weight_boundary(self, api):
        """PRD 3.5: "first the bale's `weight_lbs` must be at least 100.0 pounds,
        with exactly 100.0 allowed to seal, else the seal fails with
        `ERR_BALE_UNDERWEIGHT`"

        Design: Difficulty/boundary_precision_check/bale_seal_weight_boundary
        """
        vendor = create_vendor("Multi Co", [
            {"category": "TEXTILES",
             "brackets": [{"up_to_lbs": None, "rate_cents_per_lb": 12}]},
            {"category": "PAPER",
             "brackets": [{"up_to_lbs": None, "rate_cents_per_lb": 6}]},
        ])
        # TEXTILES bale at exactly the inclusive 100.0 minimum; PAPER bale at 99.9.
        textiles_bale, _d, _b, textiles_items = create_recycle_bale(
            "TEXTILES", "CLOTHING", [50.0, 50.0],
            conditions=["FAIR", "POOR"],
        )
        paper_bale, _d2, _b2, _paper_items = create_recycle_bale(
            "PAPER", "BOOKS_MEDIA", [99.9]
        )
        assert textiles_bale["weight_lbs"] == pytest.approx(100.0)
        assert paper_bale["weight_lbs"] == pytest.approx(99.9)

        sealed = seal_bale(textiles_bale["id"], vendor["id"])
        assert sealed["status"] == "SEALED", "100.0 lbs meets the inclusive minimum"
        for item in textiles_items:
            after = validate_success(api.get_item(item["id"], MGR))
            assert after["status"] == "BALED"

        resp = api.seal_bale(paper_bale["id"], {"vendor_id": vendor["id"]}, MGR)
        validate_error(resp, ApiErrorId.ERR_BALE_UNDERWEIGHT)
        bale_after = validate_success(api.get_bale(paper_bale["id"], MGR))
        assert bale_after["status"] == "ACCUMULATING"

    def test_bale_seal_above_minimum_records_vendor(self, api):
        """PRD 3.5: "A successful seal records the vendor, sets `sealed_at`, and
        refreshes `estimated_revenue_cents` using the vendor's own sheet: the single
        bracket rate whose range contains the bale's total weight is applied to the
        whole weight, rounded half up. The seal also cascades every assigned item in
        `RECYCLE` or `PULLED_TO_SALVAGE` — every item whose `bale_id` is this bale —
        to `BALED`."

        Design: Difficulty/boundary_precision_check/bale_seal_weight_boundary
        """
        vendor = flat_rate_vendor("TEXTILES", 12, name="T Co")
        bale, _d, _b, items = create_recycle_bale(
            "TEXTILES", "CLOTHING", [60.0, 40.1]
        )
        assert bale["weight_lbs"] == pytest.approx(100.1)

        sealed = seal_bale(bale["id"], vendor["id"])
        assert sealed["status"] == "SEALED"
        assert sealed.get("vendor_id") == vendor["id"]
        assert sealed.get("sealed_at"), "seal stamps the clock"
        # round_half_up(100.1 x 12) = round(1201.2) = 1201.
        assert sealed["estimated_revenue_cents"] == 1201
        for item in items:
            after = validate_success(api.get_item(item["id"], MGR))
            assert after["status"] == "BALED"


class TestSealGateOrdering:
    def test_underweight_seal_beats_missing_vendor_rates(self, api):
        """PRD 2.9: "Sealing an underweight bale reports `ERR_BALE_UNDERWEIGHT` even
        when the named vendor also declares no rates for the bale's category — the
        weight check is always evaluated before vendor checks."

        Design: Difficulty/priority_pair_validation_conflict/bale_constraint_beats_referential
        """
        vendor = create_vendor("Paper Only Co", [{
            "category": "PAPER",
            "brackets": [{"up_to_lbs": None, "rate_cents_per_lb": 6}],
        }])
        bale, _d, _b, items = create_recycle_bale("TEXTILES", "CLOTHING", [50.0],
                                                  conditions=["POOR"])
        assert bale["weight_lbs"] == pytest.approx(50.0)

        resp = api.seal_bale(bale["id"], {"vendor_id": vendor["id"]}, MGR)
        validate_error(resp, ApiErrorId.ERR_BALE_UNDERWEIGHT)
        bale_after = validate_success(api.get_bale(bale["id"], MGR))
        assert bale_after["status"] == "ACCUMULATING", "no seal side effects fired"
        item_after = validate_success(api.get_item(items[0]["id"], MGR))
        assert item_after["status"] == "RECYCLE", "no BALED cascade fired"

    def test_underweight_seal_with_rated_vendor(self, api):
        """PRD 3.5: "first the bale's `weight_lbs` must be at least 100.0 pounds,
        with exactly 100.0 allowed to seal, else the seal fails with
        `ERR_BALE_UNDERWEIGHT`"

        Design: Difficulty/priority_pair_validation_conflict/bale_constraint_beats_referential
        """
        vendor = flat_rate_vendor("TEXTILES", 12, name="T Co")
        bale, _d, _b, _items = create_recycle_bale("TEXTILES", "CLOTHING", [50.0])
        resp = api.seal_bale(bale["id"], {"vendor_id": vendor["id"]}, MGR)
        validate_error(resp, ApiErrorId.ERR_BALE_UNDERWEIGHT)
        bale_after = validate_success(api.get_bale(bale["id"], MGR))
        assert bale_after["status"] == "ACCUMULATING"


class TestSealReferentialAndRbac:
    def test_vendor_rate_missing_standalone(self, api):
        """PRD 3.5: "then the referenced vendor must exist and declare rates for the
        bale's category, else the seal fails with `ERR_VENDOR_RATE_MISSING`."

        Design: Corner/validations/vendor_rate_missing_standalone
        """
        vendor = flat_rate_vendor("TEXTILES", 12, name="Textile Only")
        bale, _d, _b, _items = create_recycle_bale("EWASTE", "ELECTRONICS", [100.0])
        assert bale["weight_lbs"] == pytest.approx(100.0)

        resp = api.seal_bale(bale["id"], {"vendor_id": vendor["id"]}, MGR)
        validate_error(resp, ApiErrorId.ERR_VENDOR_RATE_MISSING)
        bale_after = validate_success(api.get_bale(bale["id"], MGR))
        assert bale_after["status"] == "ACCUMULATING"

    def test_finance_clerk_cannot_seal_bale(self, api):
        """PRD 2.1: "A request whose role is not on the target endpoint's
        authorization list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 4: POST /api/salvage-bales/{bale_id}/seal is authorized for StoreManager
        only.

        Design: Corner/rbac/finance_clerk_cannot_seal_bale
        """
        vendor = flat_rate_vendor("TEXTILES", 12, name="T Co")
        bale, _d, _b, _items = create_recycle_bale("TEXTILES", "CLOTHING", [100.0])

        resp = api.seal_bale(bale["id"], {"vendor_id": vendor["id"]},
                             make_finance_clerk_headers("fin-rbac-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        bale_after = validate_success(api.get_bale(bale["id"], MGR))
        assert bale_after["status"] == "ACCUMULATING"


class TestBalePipelineStateMachine:
    def test_settle_before_ship_rejected(self, api):
        """PRD 3.5: "Sealing is a `StoreManager` action on an `ACCUMULATING` bale —
        sealing, shipping, or settling from any other from-state fails with
        `ERR_BALE_INVALID_STATE`"

        Design: Corner/state_machines/settle_before_ship_rejected
        """
        vendor = flat_rate_vendor("TEXTILES", 12, name="T Co")
        bale, _d, _b, _items = create_recycle_bale("TEXTILES", "CLOTHING", [100.0])
        seal_bale(bale["id"], vendor["id"])
        create_cycle()  # settle would need an OPEN cycle; the state gate fires first

        resp = api.settle_bale(bale["id"], {"actual_weight_lbs": 100.0},
                               make_finance_clerk_headers("fin-settle-1"))
        validate_error(resp, ApiErrorId.ERR_BALE_INVALID_STATE)
        bale_after = validate_success(api.get_bale(bale["id"], MGR))
        assert bale_after["status"] == "SEALED"
