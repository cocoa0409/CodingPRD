"""Estimate pricing: rounding order, tier evaluation order, spoilage
compounding, enum validity, and immediate consistency of computed fields."""
from test_helpers import (
    ApiErrorId,
    assert_estimate,
    create_customer,
    create_estimate,
    create_stock,
    signature_payload,
    standard_signatures,
    validate_error,
    validate_success,
)


class TestPerSignatureRoundingOrder:
    def test_running_cost_rounds_per_signature_then_sums(self, api):
        """PRD §3.2: "Running cost is computed per signature as the signature's
        impressions multiplied by its `rate_per_thousand_cents` and divided by
        1000, with the division rounded half-up to a whole cent per signature;
        only after each per-signature running cost has been rounded are they
        summed into `running_cost_cents` — rounding the sum of unrounded
        values is forbidden."

        5001 impressions x 37250/1000 = 186287.25 -> 186287 per signature;
        summed: 372574 (sum-then-round would give 372575).

        Design: Difficulty/combinatorial_formula/per_signature_rounding_order
        """
        cust = create_customer(name="R Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        est = create_estimate(
            cust["id"],
            standard_signatures(stock["id"]),
            quantity_ordered=10002,
            press_spoilage_pct=3,
            bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"],
            job_name="Round",
        )
        assert_estimate(est)
        assert est["impressions_per_signature"] == [5001, 5001]
        assert est["running_cost_cents"] == 372574, (
            f"per-signature round-then-sum must give 372574, got {est['running_cost_cents']}"
        )

    def test_full_provisional_pipeline_on_two_signature_estimate(self, api):
        """PRD §3.2: "The `subtotal_cents` is the sum of
        `make_ready_total_cents`, `running_cost_cents`, `paper_cost_cents`,
        and `finishing_cost_cents`." plus the tiered discount: "a subtotal at
        or above 500000 but strictly below 2000000 cents earns 3" and "The
        `total_price_cents` is the subtotal multiplied by one minus
        `discount_pct` hundredths, rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/per_signature_rounding_order
        """
        cust = create_customer(name="R2 Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        est = create_estimate(
            cust["id"],
            standard_signatures(stock["id"]),
            quantity_ordered=10002,
            press_spoilage_pct=3,
            bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"],
            job_name="Round2",
        )
        assert est["paper_sheets_total"] == 10512
        assert est["paper_cost_cents"] == 94608
        assert est["make_ready_total_cents"] == 300000
        assert est["finishing_cost_cents"] == 30000
        assert est["subtotal_cents"] == 797182
        assert est["discount_pct"] == 3
        assert est["total_price_cents"] == 773267


class TestTieredDiscountEvaluationOrder:
    def test_tier_keyed_on_pre_discount_subtotal_at_boundary(self, api):
        """PRD §3.2: "A volume discount is then applied as a tiered percentage
        keyed on the pre-discount subtotal: a subtotal below 500000 cents
        earns `discount_pct` of 0, a subtotal at or above 500000 but strictly
        below 2000000 cents earns 3." At subtotal exactly 500000 the tier is
        3 and total = 485000 — if the tier were keyed post-discount the total
        would self-contradict.

        Design: Difficulty/combinatorial_formula/tiered_discount_evaluation_order
        """
        cust = create_customer(name="T Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        sig = signature_payload(stock["id"], name="A", pages=16, up_count=2,
                                make_ready_cents=388582, rate_per_thousand_cents=37250)
        est = create_estimate(
            cust["id"], [sig], quantity_ordered=4000,
            press_spoilage_pct=3, bindery_spoilage_pct=2,
            finishing_options=["PERF"], job_name="Tier",
        )
        assert est["running_cost_cents"] == 74500
        assert est["paper_sheets_total"] == 2102
        assert est["paper_cost_cents"] == 18918
        assert est["subtotal_cents"] == 500000
        assert est["discount_pct"] == 3, (
            f"500000 satisfies 'at or above 500000' -> 3, got {est['discount_pct']}"
        )
        assert est["total_price_cents"] == 485000

    def test_tier_zero_below_first_threshold(self, api):
        """PRD §3.2: "a subtotal below 500000 cents earns `discount_pct` of 0."

        Design: Difficulty/combinatorial_formula/tiered_discount_evaluation_order
        """
        cust = create_customer(name="T0 Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=5)
        sig = signature_payload(stock["id"], name="A", pages=8, up_count=1,
                                make_ready_cents=50000, rate_per_thousand_cents=30000)
        est = create_estimate(cust["id"], [sig], quantity_ordered=1000, job_name="T0")
        assert est["subtotal_cents"] == 85000 < 500000
        assert est["discount_pct"] == 0
        assert est["total_price_cents"] == 85000


class TestSpoilageCompounding:
    def test_spoilage_compounding_beats_single_stage(self, api):
        """PRD §3.2: "The compounding order — ceiling after the press stage,
        then ceiling after the bindery stage — is pinned, and a single
        combined multiplier is forbidden."
        ceil(ceil(5001 x 1.03) x 1.02) = 5256, not ceil(5001 x 1.05) = 5252.

        Design: Corner/calculations/spoilage_compounding_beats_single_stage
        """
        cust = create_customer(name="S Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        sig = signature_payload(stock["id"], name="A", pages=16, up_count=2,
                                make_ready_cents=0, rate_per_thousand_cents=0)
        est = create_estimate(
            cust["id"], [sig], quantity_ordered=10002,
            press_spoilage_pct=3, bindery_spoilage_pct=2, job_name="Sp",
        )
        assert est["paper_sheets_total"] == 5256, (
            f"compounded per-stage ceilings must give 5256, got {est['paper_sheets_total']}"
        )


class TestEstimateValidation:
    def test_estimate_invalid_enum_rejected(self, api, estimator_headers):
        """PRD §3.2 requires "a `press_type` of either `WEB` or `SHEETFED`" —
        OFFSET is outside the enum; PRD §2.7: "Finally, generic field-level
        request validity — missing required fields, bad enums, out-of-range
        numerics, malformed payloads — is enforced with `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/entities/estimate_invalid_enum_rejected
        """
        cust = create_customer(name="E Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        payload = {
            "customer_id": cust["id"],
            "job_name": "Bad",
            "quantity_ordered": 100,
            "press_type": "OFFSET",
            "binding_method": "SADDLE_STITCH",
            "fulfillment_type": "SHIP",
            "signatures": [signature_payload(stock["id"], make_ready_cents=1000,
                                             rate_per_thousand_cents=1000)],
            "press_spoilage_pct": 0,
            "bindery_spoilage_pct": 0,
            "due_date": "2026-08-20T00:00:00Z",
        }
        resp = api.create_estimate(payload, estimator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestImmediateConsistency:
    def test_immediate_consistency_on_estimate_create(self, api, estimator_headers):
        """PRD §3.2: "From these inputs the server derives the full pricing
        immediately, on both create and revise." The 201 create response body
        itself carries every computed field.

        Design: Corner/consistency_model/immediate_consistency_on_estimate_create
        """
        cust = create_customer(name="IC Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        payload = {
            "customer_id": cust["id"],
            "job_name": "IC",
            "quantity_ordered": 100,
            "press_type": "WEB",
            "binding_method": "SADDLE_STITCH",
            "fulfillment_type": "SHIP",
            "signatures": [signature_payload(stock["id"], make_ready_cents=1000,
                                             rate_per_thousand_cents=1000)],
            "press_spoilage_pct": 0,
            "bindery_spoilage_pct": 0,
            "due_date": "2026-08-20T00:00:00Z",
        }
        resp = api.create_estimate(payload, estimator_headers)
        data = validate_success(resp, 201)
        assert data["subtotal_cents"] == 1600, (
            f"subtotal 1000 make-ready + 100 running + 500 paper = 1600, got {data['subtotal_cents']}"
        )
        assert data["total_price_cents"] == 1600
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["impressions_per_signature"] == [100]
        assert data["running_cost_cents"] == 100
        assert data["paper_sheets_total"] == 100
        assert data["paper_cost_cents"] == 500
