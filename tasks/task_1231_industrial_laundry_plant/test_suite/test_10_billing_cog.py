"""COG billing: actual vs estimated variant divergence and the pinned
per-category rounding order under the volume discount."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_invoice, assert_invoice_total_invariants,
    setup_finished_load, stage_wash_load, generate_invoice, get_invoice,
    billing_preview, setup_stop_received, create_batch_posted,
    create_linen_category, drive_load_to_finished,
)

CLERK = TEST_USERS["billing_clerk_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]

PERIOD = {"billing_period_start": "2026-05-01", "billing_period_end": "2026-06-01"}


class TestActualVsEstimatedDivergence:
    def _setup_finished_plus_staged(self, api):
        """One FINISHED load and one STAGED load, each 100 pieces * 0.5 lb of
        a 120 c/lb COG category. The logical clock is untouched, so the unload
        stamps 2026-05-01T00:00:00Z (PRD §2.5), inside the May period."""
        ctx = setup_finished_load(
            pieces=100,
            category_overrides={"piece_weight_lb": 0.5,
                                "cog_wash_rate_cents_per_lb": 120},
            stop_overrides={"declared_soiled_weight_lb": 50.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 50.0}],
            load_overrides={
                "machine_id": "M1",
                "scheduled_start": "2026-05-02T08:00:00Z",
                "scheduled_end": "2026-05-02T09:00:00Z",
            },
        )
        assert ctx["load"]["status"] == "FINISHED"
        staged = stage_wash_load(
            ctx["batch"]["id"], ctx["category"]["id"],
            machine_id="M1",
            scheduled_start="2026-05-02T10:00:00Z",
            scheduled_end="2026-05-02T11:00:00Z",
        )
        ctx["staged_load"] = staged
        return ctx

    def test_preview_counts_staged_load_with_projected_weight(self, api):
        """PRD §3.8: "For a `COG` customer the preview runs the estimated variant: in addition to `FINISHED` loads it counts loads still in `STAGED`, `RUNNING`, `AWAITING_TEST`, `TESTED_PASS`, or `REWASH_PENDING`, using a projected clean weight of accepted pieces times `piece_weight_lb`, so the preview total is always at least the actual total."
        PRD §3.8: "at least 20000 pounds earns 7 percent; failing that, at least 5000 pounds earns 3 percent; below that the discount is zero"

        Design: Difficulty/dual_variant_calc/cog_actual_vs_estimated_billing_diverge
        """
        ctx = self._setup_finished_plus_staged(api)
        preview = billing_preview(ctx["customer"]["id"], "2026-05-01", "2026-06-01")
        # FINISHED 50 lb (6000) + STAGED projected 50 lb (6000); volume
        # 100 lb earns no volume discount.
        assert preview["linen_charges_cents"] == 12000, (
            f"preview must include the STAGED load's projected weight, "
            f"got {preview['linen_charges_cents']}"
        )

    def test_generated_invoice_counts_only_finished_loads(self, api):
        """PRD §3.8: "For a `COG` customer, each linen category contributes the pounds actually washed: the sum of `clean_weight_lb` over the customer's `FINISHED` wash loads of that category whose unload timestamp falls within the billing period, start inclusive and end exclusive, multiplied by the category's `cog_wash_rate_cents_per_lb` and rounded half-up to whole cents as the category gross."

        Design: Difficulty/dual_variant_calc/cog_actual_vs_estimated_billing_diverge
        """
        ctx = self._setup_finished_plus_staged(api)
        invoice = generate_invoice(ctx["customer"]["id"], **PERIOD)
        assert_invoice(invoice)
        assert invoice["linen_charges_cents"] == 6000, (
            f"the actual variant counts only FINISHED loads, "
            f"got {invoice['linen_charges_cents']}"
        )
        preview = billing_preview(ctx["customer"]["id"], "2026-05-01", "2026-06-01")
        assert preview["linen_charges_cents"] != invoice["linen_charges_cents"], (
            "estimated (preview) and actual (invoice) variants must diverge here"
        )
        assert_invoice_total_invariants(invoice)


class TestCogRoundingOrder:
    def _setup_two_category_loads(self, api, with_bulk=True):
        """CAT_ODD (10.005 lb/piece) 1 piece; CAT_BULK (100 lb/piece) 50
        pieces, when with_bulk. Both loads FINISHED."""
        ctx = setup_stop_received(
            category_overrides={
                "code": "CAT_ODD", "piece_weight_lb": 10.005,
                "cog_wash_rate_cents_per_lb": 100, "replacement_cost_cents": 1000,
            },
            stop_overrides={"declared_soiled_weight_lb": 5010.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 5010.0}],
        )
        cat_odd = ctx["category"]
        items = [{"category_id": cat_odd["id"], "pieces": 1}]
        if with_bulk:
            cat_bulk = create_linen_category(
                ctx["plant"]["id"],
                code="CAT_BULK", piece_weight_lb=100.0,
                cog_wash_rate_cents_per_lb=100, replacement_cost_cents=1000,
            )
            ctx["category_bulk"] = cat_bulk
            items.append({"category_id": cat_bulk["id"], "pieces": 50})
        ctx["batch"] = create_batch_posted(ctx["stop"]["id"], items)

        load_odd = stage_wash_load(
            ctx["batch"]["id"], cat_odd["id"], machine_id="M1",
            scheduled_start="2026-05-02T08:00:00Z",
            scheduled_end="2026-05-02T09:00:00Z",
        )
        ctx["load_odd"] = drive_load_to_finished(load_odd["id"])
        if with_bulk:
            load_bulk = stage_wash_load(
                ctx["batch"]["id"], ctx["category_bulk"]["id"], machine_id="M1",
                scheduled_start="2026-05-02T10:00:00Z",
                scheduled_end="2026-05-02T11:00:00Z",
            )
            ctx["load_bulk"] = drive_load_to_finished(load_bulk["id"])
        return ctx

    def test_per_category_rounding_then_discount(self, api):
        """PRD §3.8: "The rounding order is pinned and not negotiable: the discount is applied per category on the already-rounded category gross — the gross multiplied by one hundred minus the discount percent, divided by one hundred, and rounded half-up to whole cents — and the per-category nets are then summed into `linen_charges_cents`. Summing first and discounting once is forbidden."
        PRD §3.8: "The customer's total washed volume across all categories then sets a volume discount: at least 20000 pounds earns 7 percent; failing that, at least 5000 pounds earns 3 percent; below that the discount is zero."

        Design: Difficulty/combinatorial_formula/cog_rounding_order_per_category_then_discount_mode_b
        """
        ctx = self._setup_two_category_loads(api, with_bulk=True)
        invoice = generate_invoice(ctx["customer"]["id"], **PERIOD)
        # CAT_ODD: gross round(10.005*100)=1001, net round(1001*0.97)=971.
        # CAT_BULK: gross 500000, net 485000. Total volume 5010.005 lb -> 3%.
        assert invoice["linen_charges_cents"] == 485971, (
            "pinned rounding order yields 485971 (the forbidden "
            f"discount-before-rounding order yields 485970); "
            f"got {invoice['linen_charges_cents']}"
        )
        assert_invoice_total_invariants(invoice)

    def test_below_tier_volume_earns_no_discount(self, api):
        """PRD §3.8: "The customer's total washed volume across all categories then sets a volume discount: at least 20000 pounds earns 7 percent; failing that, at least 5000 pounds earns 3 percent; below that the discount is zero."
        PRD §3.8: "For a `COG` customer, each linen category contributes the pounds actually washed: the sum of `clean_weight_lb` over the customer's `FINISHED` wash loads of that category whose unload timestamp falls within the billing period, start inclusive and end exclusive, multiplied by the category's `cog_wash_rate_cents_per_lb` and rounded half-up to whole cents as the category gross."

        Design: Difficulty/combinatorial_formula/cog_rounding_order_per_category_then_discount_mode_b
        """
        ctx = self._setup_two_category_loads(api, with_bulk=False)
        invoice = generate_invoice(ctx["customer"]["id"], **PERIOD)
        # 10.005 lb < 5000 lb -> 0% discount; gross rounds half-up to 1001.
        assert invoice["linen_charges_cents"] == 1001, (
            f"below the 5000 lb tier there is no discount; expected 1001, "
            f"got {invoice['linen_charges_cents']}"
        )
        assert_invoice_total_invariants(invoice)
