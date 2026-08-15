"""Blender scheduling, batch lifecycle, and the completion cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, CREDIT, PLANT, ADMIN,
    grower_headers, create_batch_payload,
    published_price_sheet, create_blend_order, book_order,
    setup_order_pipeline, setup_booked_order, setup_batch_in_progress,
    complete_order_batch, order_line_ids)

UREA_SPEC = {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}
DAP_SPEC = {"name": "DAP 18-46-0", "analysis_n_pct": 18, "analysis_p2o5_pct": 46, "analysis_k2o_pct": 0}
MOP_SPEC = {"name": "MOP 0-0-60", "analysis_n_pct": 0, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 60}
UREA_LINE = [{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}]
FULL_PIPS = dict(
    products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
    lots={"UREA 46-0-0": 20}, with_blender=True)


class TestBlenderWindowBuffer:
    def _two_booked_orders(self, api):
        ctx = setup_order_pipeline(
            legal_name="Buffer Farms",
            lines=UREA_LINE,
            **FULL_PIPS)
        book_order(ctx["order"]["id"], ctx["grower"])
        order2 = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": ctx["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 100.0}])
        book_order(order2["id"], ctx["grower"])
        get_success_data(api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T08:00:00Z",
                                 scheduled_end="2026-08-05T10:00:00Z"),
            PLANT))
        return ctx, order2

    def test_adjacent_start_rejected_buffer_boundary_admitted(self, api):
        """PRD 3.5: "The consequence at the boundary: a new batch starting exactly at
        an existing batch's end is rejected because the buffer is not honored, while
        a new batch starting exactly thirty minutes after the existing batch's end is
        admitted."

        Design: Difficulty/resource_temporal_overlap/blender_batch_cleanup_buffer_semantics
        """
        ctx, order2 = self._two_booked_orders(api)

        resp = api.create_batch(
            order2["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T10:00:00Z",
                                 scheduled_end="2026-08-05T11:00:00Z"),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_BLENDER_WINDOW_CONFLICT)

        batch2 = get_success_data(api.create_batch(
            order2["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T10:30:00Z",
                                 scheduled_end="2026-08-05T11:30:00Z"),
            PLANT))
        assert batch2["status"] == "SCHEDULED"
        readback = get_success_data(api.get_blend_order(order2["id"], CREDIT))
        assert readback["fulfillment_status"] == "SCHEDULED"

    def test_adjacency_rejected_because_buffer_not_honored(self, api):
        """PRD 3.5: "A new batch is rejected when its own buffered window intersects
        any non-`VOIDED` batch's buffered window on the same blender — concretely,
        when the new start minus the buffer falls before the existing end plus the
        buffer while the new end plus the buffer falls after the existing start minus
        the buffer."

        Design: Difficulty/resource_temporal_overlap/blender_batch_cleanup_buffer_semantics
        """
        ctx, order2 = self._two_booked_orders(api)
        # new.start (10:00) - 30min = 09:30 < existing.end (10:00) + 30min = 10:30 -> conflict
        resp = api.create_batch(
            order2["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T10:00:00Z",
                                 scheduled_end="2026-08-05T10:45:00Z"),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_BLENDER_WINDOW_CONFLICT)


class TestBatchCreateEquipmentGates:
    def test_blender_form_mismatch_rejected(self, api):
        """PRD 3.5: "the blender's `form_supported` must cover every line product's
        `form` (`BOTH` covers all) — otherwise `ERR_BLENDER_FORM_MISMATCH`."

        Design: Corner/errors/error_blender_form_mismatch_trigger
        """
        uan_spec = {"name": "UAN 32-0-0", "analysis_n_pct": 32, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0, "form": "LIQUID"}
        ctx = setup_order_pipeline(
            legal_name="Liquid Farms",
            products=[uan_spec],
            prices={"UAN 32-0-0": 35000},
            lots={"UAN 32-0-0": 10},
            with_blender=True,
            blender_form="DRY",
            lines=[{"product_id": "UAN 32-0-0", "target_rate_lbs_per_acre": 100.0}])
        book_order(ctx["order"]["id"], ctx["grower"])
        resp = api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"]),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_BLENDER_FORM_MISMATCH)

    def test_blender_out_of_service_rejected(self, api):
        """PRD 3.5: "the blender must be `ACTIVE` — otherwise
        `ERR_BLENDER_OUT_OF_SERVICE`."

        Design: Corner/errors/error_blender_out_of_service_trigger
        """
        ctx = setup_booked_order(lines=UREA_LINE, **FULL_PIPS)
        get_success_data(api.blender_out_of_service(ctx["blender"]["id"], PLANT))
        resp = api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"]),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_BLENDER_OUT_OF_SERVICE)


class TestParallelDimensions:
    def test_fulfillment_and_payment_dims_move_independently(self, api):
        """PRD 3.5: "in the combined initial state `fulfillment_status` of `QUOTED`
        and `payment_status` of `UNPAID` — two independent state dimensions that
        evolve in parallel."
        PRD 3.5: "The gates, in §2.7's order: the order must be `BOOKED` and, as a
        cross-dimension rule, its `payment_status` must be `PREPAY_APPLIED` or
        `CREDIT_APPROVED` — otherwise `ERR_INVALID_TRANSITION`."
        PRD 3.6: "A batch may instead be voided from `SCHEDULED` — manually by the
        operator with an optional `reason`, or by the permit-revoke and order-cancel
        cascades — which releases the blender window and returns the order from
        `SCHEDULED` to `BOOKED`, incrementing both resources' versions."

        Design: Difficulty/non_linear_state_machine/blend_order_parallel_payment_fulfillment_dims
        """
        ctx = setup_order_pipeline(lines=UREA_LINE, **FULL_PIPS)
        order_id = ctx["order"]["id"]
        gh = grower_headers(ctx["grower"])

        s1 = get_success_data(api.book_blend_order(order_id, gh))
        assert s1["fulfillment_status"] == "BOOKED" and s1["payment_status"] == "CREDIT_APPROVED"

        s2 = get_success_data(api.requote_blend_order(order_id, gh))
        assert s2["fulfillment_status"] == "QUOTED" and s2["payment_status"] == "UNPAID", \
            "requote reverts both dims"

        # cross-dimension gate: QUOTED/UNPAID cannot accept a batch
        resp = api.create_batch(order_id, create_batch_payload(blender_id=ctx["blender"]["id"]), PLANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

        s3 = get_success_data(api.book_blend_order(order_id, gh))
        assert s3["fulfillment_status"] == "BOOKED" and s3["payment_status"] == "CREDIT_APPROVED"

        batch = get_success_data(api.create_batch(order_id, create_batch_payload(blender_id=ctx["blender"]["id"]), PLANT))
        get_success_data(api.void_batch(batch["id"], PLANT, payload={"reason": "weather window"}))

        s4 = get_success_data(api.get_blend_order(order_id, CREDIT))
        assert s4["fulfillment_status"] == "BOOKED", "batch void reverts the fulfillment dim"
        assert s4["payment_status"] == "CREDIT_APPROVED", "payment dim untouched"

    def test_batch_create_requires_booked_and_payment_posture(self, api):
        """PRD 3.5: "the order must be `BOOKED` and, as a cross-dimension rule, its
        `payment_status` must be `PREPAY_APPLIED` or `CREDIT_APPROVED` — otherwise
        `ERR_INVALID_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/blend_order_parallel_payment_fulfillment_dims
        """
        ctx = setup_order_pipeline(lines=UREA_LINE, **FULL_PIPS)
        # Order still QUOTED/UNPAID — batch create must reject
        resp = api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"]),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


class TestBatchCompletionCascade:
    def _completed_urea_ctx(self, api, **overrides):
        kwargs = dict(FULL_PIPS)
        kwargs.update(overrides)
        ctx = setup_batch_in_progress(lines=UREA_LINE, **kwargs)
        get_success_data(complete_order_batch(ctx))
        return ctx

    def test_completion_cascade_three_hops(self, api):
        """PRD 3.6: "Hop one writes the lines: each line's `actual_rate_lbs_per_acre`
        from the posted actuals; `actual_quantity_tons` as the actual rate multiplied
        by the order's `acres` divided by 2000, rounded half-up to three decimals;
        `final_unit_price_cents` as the contract's `unit_price_cents` for a
        `PRICE_LOCKED` contract-product line, else the `PUBLISHED` sheet price
        containing the completion instant; and `line_final_cents` as the
        `actual_quantity_tons` multiplied by the `final_unit_price_cents`, rounded
        half-up to whole cents."
        PRD 3.6: "When the order is `CREDIT_APPROVED`, the full `final_total_cents`
        is invoiced. An `INVOICE_POSTED` ledger entry posts for the invoiced amount
        and a `REBATE_CREDIT` entry for the negative of the rebate; `credit_used_cents`
        and `prepay_balance_cents` are recomputed."

        Design: Difficulty/transitive_cascade/batch_completion_pricing_credit_cascade
        """
        ctx = self._completed_urea_ctx(api)
        order_id = ctx["order"]["id"]
        ln_urea = ctx["line_ids"][0]

        # hop 1: line actuals written
        line = get_success_data(api.get_blend_line(ln_urea, PLANT))
        assert line["actual_quantity_tons"] == pytest.approx(8.703, abs=1e-9)
        assert line["line_final_cents"] == 452556  # round_half_up(8.703 x 52000)

        # hop 2: order aggregated and invoiced
        order = get_success_data(api.get_blend_order(order_id, CREDIT))
        assert order["fulfillment_status"] == "BATCHED"
        assert order["payment_status"] == "INVOICED"
        assert order["final_total_cents"] == 452556
        assert order["rebate_cents"] == 0, "50t tier not reached"

        # hop 3: grower credit ledger
        grower = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert grower["credit_used_cents"] == 452556
        ledger, meta = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        assert meta["total_count"] == 1, "rebate 0 -> exactly one ledger entry"
        assert ledger[0]["entry_type"] == "INVOICE_POSTED"
        assert ledger[0]["amount_cents"] == 452556

    def test_completion_writes_actuals_and_final_price_on_line(self, api):
        """PRD 3.6: "Hop one writes the lines: each line's `actual_rate_lbs_per_acre`
        from the posted actuals; `actual_quantity_tons` as the actual rate multiplied
        by the order's `acres` divided by 2000, rounded half-up to three decimals;
        `final_unit_price_cents` as the contract's `unit_price_cents` for a
        `PRICE_LOCKED` contract-product line, else the `PUBLISHED` sheet price
        containing the completion instant; and `line_final_cents` as the
        `actual_quantity_tons` multiplied by the `final_unit_price_cents`, rounded
        half-up to whole cents."

        Design: Difficulty/transitive_cascade/batch_completion_pricing_credit_cascade
        """
        ctx = self._completed_urea_ctx(api)
        line = get_success_data(api.get_blend_line(ctx["line_ids"][0], PLANT))
        assert line["actual_rate_lbs_per_acre"] == pytest.approx(348.1, abs=1e-9)
        assert line["final_unit_price_cents"] == 52000
        assert line["actual_quantity_tons"] == pytest.approx(8.703, abs=1e-9)
        assert line["line_final_cents"] == 452556


class TestProvisionalVsFinalPricing:
    def _repriced_ctx(self, api):
        """FLOATING order with DAP/MOP/UREA lines; MOP sheet re-priced before completion."""
        ctx = setup_batch_in_progress(
            legal_name="Cedar Ridge Ag",
            field_name="Home Farm",
            products=[UREA_SPEC, DAP_SPEC, MOP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000, "MOP 0-0-60": 44500},
            lots={"UREA 46-0-0": 20, "DAP 18-46-0": 20, "MOP 0-0-60": 20},
            lines=[
                {"product_id": "DAP 18-46-0", "target_rate_lbs_per_acre": 332.6},
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 365.0},
                {"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1},
            ],
            batch_start="2026-08-05T08:00:00Z", batch_end="2026-08-05T10:00:00Z")
        # Expire the MOP sheet and republish at a higher price before completion
        sheets, _ = validate_paginated(api.list_product_price_sheets(ctx["products"]["MOP 0-0-60"]["id"], ADMIN))
        old_sheet = sheets[0]
        get_success_data(api.expire_price_sheet(old_sheet["id"], ADMIN))
        published_price_sheet(ctx["products"]["MOP 0-0-60"]["id"], 46000)
        return ctx

    def test_provisional_vs_final_pricing_diverge(self, api):
        """PRD 3.5: "Provisional unit pricing resolves per line: when the order is
        `PRICE_LOCKED` and the line's product is the contract's product,
        `unit_price_cents` is the contract's `unit_price_cents`; otherwise it is the
        current `PUBLISHED` sheet's `price_per_ton_cents` at quote time."
        PRD 3.6: "`final_unit_price_cents` as the contract's `unit_price_cents` for a
        `PRICE_LOCKED` contract-product line, else the `PUBLISHED` sheet price
        containing the completion instant."

        Design: Difficulty/dual_variant_calc/blend_order_provisional_vs_final_pricing
        """
        ctx = self._repriced_ctx(api)
        order_id = ctx["order"]["id"]
        assert ctx["order"]["provisional_total_cents"] == 1365834, \
            "quote-time: DAP 507215 + MOP 406063 + UREA 452556"

        get_success_data(complete_order_batch(ctx))
        order = get_success_data(api.get_blend_order(order_id, CREDIT))
        # completion-time: DAP 507215 + MOP 419750 + UREA 452556
        assert order["final_total_cents"] == 1379521
        assert order["final_total_cents"] != order["provisional_total_cents"], \
            "PROVISIONAL and FINAL variants diverge despite identical quantities"
        assert order["payment_status"] == "INVOICED"
        assert order["fulfillment_status"] == "BATCHED"

        lines, _ = validate_paginated(api.list_order_lines(order_id, PLANT))
        mop_line = next(ln for ln in lines if ln["product_id"] == ctx["products"]["MOP 0-0-60"]["id"])
        assert mop_line["unit_price_cents"] == 44500, "quote-time price retained on the line"
        assert mop_line["final_unit_price_cents"] == 46000, "completion-time price"
        assert mop_line["line_final_cents"] == 419750

    def test_final_pricing_uses_completion_instant_sheet(self, api):
        """PRD 3.6: "`final_unit_price_cents` as the contract's `unit_price_cents`
        for a `PRICE_LOCKED` contract-product line, else the `PUBLISHED` sheet price
        containing the completion instant."

        Design: Difficulty/dual_variant_calc/blend_order_provisional_vs_final_pricing
        """
        ctx = self._repriced_ctx(api)
        get_success_data(complete_order_batch(ctx))
        lines, _ = validate_paginated(api.list_order_lines(ctx["order"]["id"], PLANT))
        mop_line = next(ln for ln in lines if ln["product_id"] == ctx["products"]["MOP 0-0-60"]["id"])
        assert mop_line["final_unit_price_cents"] == 46000, \
            "FLOATING line re-priced at completion-time sheet"


class TestBatchVarianceBoundary:
    def _two_in_progress_batches(self, api):
        ctx = setup_order_pipeline(
            legal_name="Variance Farms",
            n_cap_lbs_per_acre=400,
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 400.0}],
            **FULL_PIPS)
        ctx["lots"] = None
        # The default 20 t lot is enough for two 10 t orders
        book_order(ctx["order"]["id"], ctx["grower"])
        order2 = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": ctx["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 400.0}])
        book_order(order2["id"], ctx["grower"])
        ba1 = get_success_data(api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T08:00:00Z",
                                 scheduled_end="2026-08-05T09:00:00Z"),
            PLANT))
        ba2 = get_success_data(api.create_batch(
            order2["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T09:30:00Z",
                                 scheduled_end="2026-08-05T10:00:00Z"),
            PLANT))
        get_success_data(api.start_batch(ba1["id"], PLANT))
        get_success_data(api.start_batch(ba2["id"], PLANT))
        ln1 = order_line_ids(ctx["order"]["id"])[0]
        ln2 = order_line_ids(order2["id"])[0]
        return ctx, ba1, ba2, ln1, ln2

    def test_variance_boundary_inclusive(self, api):
        """PRD 3.6: "Each line's actual rate must sit within five percent of its
        target, inclusive at the boundary: the absolute difference between actual and
        target, divided by the target, must not exceed the tolerance of five percent,
        or completion fails with `ERR_BATCH_VARIANCE_EXCEEDED`. A line exactly at the
        tolerance boundary is admitted, and its `variance_flag` is true only when the
        ratio strictly exceeds the tolerance."

        Design: Corner/errors/error_batch_variance_boundary
        """
        ctx, ba1, ba2, ln1, ln2 = self._two_in_progress_batches(api)

        # 420.0 vs 400.0 is exactly +5% -> admitted
        r1 = get_success_data(api.complete_batch(ba1["id"], {
            "actuals": [{"blend_line_id": ln1, "actual_rate_lbs_per_acre": 420.0}],
        }, PLANT))
        assert r1["status"] == "COMPLETED"
        line1 = get_success_data(api.get_blend_line(ln1, PLANT))
        assert line1["variance_flag"] is False

        # 421.0 vs 400.0 is +5.25% -> rejected
        resp = api.complete_batch(ba2["id"], {
            "actuals": [{"blend_line_id": ln2, "actual_rate_lbs_per_acre": 421.0}],
        }, PLANT)
        validate_error(resp, ApiErrorId.ERR_BATCH_VARIANCE_EXCEEDED)
        batch2 = get_success_data(api.get_batch(ba2["id"], PLANT))
        assert batch2["status"] == "IN_PROGRESS", "rejected completion left no side effects"


class TestRebateTiers:
    def _completed_ctx_with_tons(self, api, field_acres, rate, n_cap, lot_tons):
        ctx = setup_batch_in_progress(
            legal_name="Rebate Farms",
            field_acres=field_acres,
            n_cap_lbs_per_acre=n_cap,
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": lot_tons}, with_blender=True,
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": rate}])
        get_success_data(complete_order_batch(ctx))
        return ctx

    def test_rebate_at_tier_boundary(self, api):
        """PRD 3.6: "The tier rate is zero when the base is below 50 tons; two
        percent when the base is at least 50 tons and below 150 tons — a base of
        exactly 50.000 tons qualifies for this tier; and three and a half percent
        when the base is at least 150 tons. The rebate is the `final_total_cents`
        multiplied by the tier rate, rounded half-up to whole cents. The
        `final_total_cents` is not reduced by the rebate; the rebate posts as a
        separate `REBATE_CREDIT` ledger entry and never feeds back into the tier
        base."

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_evaluation_order
        """
        ctx = self._completed_ctx_with_tons(api, field_acres=125, rate=800.0, n_cap=400, lot_tons=60)
        order = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert order["tons_total"] == pytest.approx(50.000, abs=1e-9)
        assert order["final_total_cents"] == 2600000  # 50.000 t x 52000
        assert order["rebate_cents"] == 52000, "tier base 50.000 >= 50 -> 2% of 2600000"
        # final_total stays intact — rebate does NOT reduce the invoice total
        grower = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert grower["credit_used_cents"] == 2600000 - 52000

    def test_rebate_evaluation_order_pinned(self, api):
        """PRD 3.6: "The rebate breaks its apparent tier-versus-total circle with a
        pinned evaluation order. The tier base tonnage is the grower's
        `season_closed_tons` — closed orders only — plus this order's final actual
        `tons_total`."

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_evaluation_order
        """
        ctx = self._completed_ctx_with_tons(api, field_acres=125, rate=800.0, n_cap=400, lot_tons=60)
        order = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        # rebate computed FROM final_total, posted separately; final_total unchanged
        assert order["final_total_cents"] == 2600000
        assert order["rebate_cents"] == 52000
        ledger, _ = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        types = {e["entry_type"]: e["amount_cents"] for e in ledger}
        assert types["REBATE_CREDIT"] == -52000, "rebate posts as a separate ledger credit"

    def test_rebate_below_tier_boundary_zero(self, api):
        """PRD 3.6: "The tier rate is zero when the base is below 50 tons."

        Design: Corner/calculations/rebate_below_tier_boundary_zero
        """
        ctx = self._completed_ctx_with_tons(api, field_acres=125, rate=400.0, n_cap=300, lot_tons=30)
        order = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert order["final_total_cents"] == 1300000  # 25.000 t x 52000
        assert order["rebate_cents"] == 0, "25.000 < 50 tier threshold"


class TestPaymentWaterfallConservation:
    def test_invoice_then_payment_conserves_credit(self, api):
        """PRD 2.10: "The grower's `credit_used_cents` is the sum of `INVOICE_POSTED`
        amounts minus the absolute amounts of `PAYMENT_RECEIVED` and `REBATE_CREDIT`
        entries."
        PRD 3.1: "Each fully covered order moves `payment_status` from `INVOICED` to
        `PAID`."

        Design: Difficulty/compensating_invariant/credit_invoice_payment_conservation
        """
        ctx = setup_batch_in_progress(lines=UREA_LINE, **FULL_PIPS)
        get_success_data(complete_order_batch(ctx))

        mid = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert mid["credit_used_cents"] == 452556, "forward action: invoice posted"

        pay = get_success_data(api.post_payment(ctx["grower"]["id"], {"amount_cents": 452556}, CREDIT))
        assert pay["entry_type"] == "PAYMENT_RECEIVED"
        assert pay["resulting_credit_used_cents"] == 0

        post = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert post["credit_used_cents"] == 0, "round-trip leaves the conserved quantity unchanged"

        order = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert order["payment_status"] == "PAID", "waterfall covered the single invoice fully"

    def test_payment_posts_single_negative_ledger_entry(self, api):
        """PRD 3.1: "A single `PAYMENT_RECEIVED` ledger entry is appended with the
        negative of the payment amount, `credit_used_cents` is recomputed, and the
        grower's `version` increments."

        Design: Difficulty/compensating_invariant/credit_invoice_payment_conservation
        """
        ctx = setup_batch_in_progress(lines=UREA_LINE, **FULL_PIPS)
        get_success_data(complete_order_batch(ctx))
        pay = get_success_data(api.post_payment(ctx["grower"]["id"], {"amount_cents": 452556}, CREDIT))
        assert pay["entry_type"] == "PAYMENT_RECEIVED"
        assert pay["amount_cents"] == -452556
        ledger, meta = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        assert meta["total_count"] == 2
        assert ledger[-1]["entry_type"] == "PAYMENT_RECEIVED"
