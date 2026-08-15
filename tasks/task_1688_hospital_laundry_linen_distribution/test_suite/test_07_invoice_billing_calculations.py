"""Invoice billing calculations: provisional weight-based vs final
piece-count billing, pinned rounding order, and the credit evaluation order
(PRD 2.6, 3.6, 3.7)."""
import pytest
from test_helpers import (
    LM,
    LM2,
    VENDOR,
    api_client,
    base_scenario,
    collect_soiled,
    create_complaint,
    create_gown_stock,
    create_invoice,
    create_manifest,
    create_par,
    create_towel_stock,
    fill_unit_to_par,
    finalize_invoice,
    read_invoice,
    reconcile_manifest,
    return_manifest,
    setup_finalized_invoice,
    setup_reconciled_manifest,
    validate_success,
)


def _setup_two_stock_reconciled_manifest():
    """Facility + ICU unit + sheet stock + isolation gown stock; a collection
    of 8 sheets and 10 gowns is manifested (16.00 lbs + 5.00 lbs isolation),
    returned (7 sheets, 10 gowns), and reconciled."""
    ctx = base_scenario()
    gown = create_gown_stock(ctx["facility"]["id"])
    create_par(ctx["unit"]["id"], gown["id"], 30, "DAILY")
    ctx["gown"] = gown
    ctx["fill_run"] = fill_unit_to_par(ctx)
    ctx["collect_run"] = collect_soiled(
        ctx,
        [
            {"stock_id": ctx["stock"]["id"], "pieces": 8},
            {"stock_id": gown["id"], "pieces": 10},
        ],
    )
    manifest = create_manifest(
        ctx["facility"]["id"],
        [ctx["collect_run"]["id"]],
        [
            {"stock_id": ctx["stock"]["id"], "weight_lbs": 16.00,
             "isolation_flag": False},
            {"stock_id": gown["id"], "weight_lbs": 5.00,
             "isolation_flag": True},
        ],
        isolation_protocol_ack=True,
    )
    ctx["manifest"] = reconcile_manifest(
        return_manifest(
            manifest["id"],
            [
                {"stock_id": ctx["stock"]["id"], "pieces": 7,
                 "condemned_pieces": 0},
                {"stock_id": gown["id"], "pieces": 10, "condemned_pieces": 0},
            ],
        )["id"]
    )
    return ctx


class TestProvisionalVsFinal:
    """The same manifest prices at 890 cents by weight and 810 cents by
    returned piece count (PRD 3.6)."""

    def test_provisional_total_is_weight_based(self, api):
        """PRD 3.6: "Each line's amount is its `weight_lbs` multiplied by the
        facility's `rate_per_lb_cents`, rounded half up to a whole cent; when
        the line's `isolation_flag` is true, a surcharge equal to that rounded
        line amount multiplied by the facility's `isolation_surcharge_pct`,
        itself rounded half up to a whole cent, is added."
        PRD 3.6: "The provisional total is the sum of these per-line amounts —
        per-line rounding always happens before summation."

        Design: Difficulty/dual_variant_calc/vendor_invoice_provisional_vs_final_weight_vs_pieces
        """
        ctx = _setup_two_stock_reconciled_manifest()
        invoice = create_invoice(ctx["facility"]["id"], [ctx["manifest"]["id"]])
        # 16.00*40 = 640; 5.00*40 = 200 + round(200*0.25) = 50 -> 890.
        assert invoice["provisional_total_cents"] == 890, (
            f"weight-based provisional must be 640 + 200 + 50 = 890, got "
            f"{invoice['provisional_total_cents']}"
        )
        assert invoice["status"] == "PROVISIONAL"
        assert invoice["final_total_cents"] is None

        finalized = finalize_invoice(invoice["id"])
        assert finalized["provisional_total_cents"] == 890
        assert finalized["final_total_cents"] != finalized["provisional_total_cents"]

    def test_final_total_is_piece_count_reconciled(self, api):
        """PRD 3.6: "second, `final_total_cents` is computed as the sum over
        every returned line of the line's returned `pieces` multiplied by its
        stock's per-piece rate, with an isolation surcharge — the line amount
        multiplied by `isolation_surcharge_pct`, rounded half up to a whole
        cent — added whenever the corresponding manifest line was
        isolation-flagged; third, `credit_total_cents` is taken from the
        verified complaints routed to this invoice; fourth,
        `billed_total_cents` is the final total minus the credit total, and
        it is recomputed on every later credit change."
        PRD 3.6: "`cost_per_apd_cents` is `billed_total_cents` divided by
        `period_adjusted_patient_days`, rounded half up to two decimal
        places."

        Design: Difficulty/dual_variant_calc/vendor_invoice_provisional_vs_final_weight_vs_pieces
        """
        ctx = _setup_two_stock_reconciled_manifest()
        invoice = create_invoice(ctx["facility"]["id"], [ctx["manifest"]["id"]])
        finalized = finalize_invoice(invoice["id"])

        # per-piece rates: 2.00*40 = 80 c, 0.50*40 = 20 c.
        # 7*80 = 560; 10*20 = 200 + round(200*0.25) = 50 -> 810.
        assert finalized["final_total_cents"] == 810, (
            f"piece-count final must be 560 + 200 + 50 = 810, got "
            f"{finalized['final_total_cents']}"
        )
        assert finalized["credit_total_cents"] == 0
        assert finalized["billed_total_cents"] == 810
        assert finalized["cost_per_apd_cents"] == pytest.approx(16.20, abs=0.001)
        assert finalized["finalized_by_user_id"] == "lm-2"


class TestProvisionalRoundingOrder:
    """Per-line rounding before summation is pinned; the two-line 0.0125 lb
    case yields 2 cents where sum-then-round would yield 1."""

    def _tiny_line_manifest(self, ctx, stocks_weights):
        lines = [
            {"stock_id": sid, "weight_lbs": w, "isolation_flag": False}
            for sid, w in stocks_weights
        ]
        manifest = create_manifest(ctx["facility"]["id"], [], lines)
        # Zero-piece returns satisfy the RETURNED precondition for invoicing
        # without disturbing the weight-based provisional total.
        return_manifest(
            manifest["id"],
            [{"stock_id": sid, "pieces": 0, "condemned_pieces": 0}
             for sid, _ in stocks_weights],
        )
        return manifest

    def test_two_half_cent_lines_round_then_sum(self, api):
        """PRD 3.6: "The provisional total is the sum of these per-line
        amounts — per-line rounding always happens before summation."
        PRD 2.6: "Two rounding disciplines are pinned and may not be
        reordered: per-line invoice amounts are rounded before any summation
        takes place, and a stock's per-piece wash rate — its
        `piece_weight_lbs` multiplied by the facility's `rate_per_lb_cents`,
        rounded half up to a whole cent — is computed once per stock and then
        reused wherever a per-piece rate is needed."

        Design: Difficulty/combinatorial_formula/provisional_total_rounds_per_line_then_sums
        """
        ctx = base_scenario()
        towel = create_towel_stock(ctx["facility"]["id"])
        manifest = self._tiny_line_manifest(
            ctx, [(ctx["stock"]["id"], 0.0125), (towel["id"], 0.0125)]
        )
        invoice = create_invoice(
            ctx["facility"]["id"], [manifest["id"]], period_adjusted_patient_days=10
        )
        # round_half_up(0.0125*40) = round_half_up(0.5) = 1 per line -> 2.
        assert invoice["provisional_total_cents"] == 2, (
            f"per-line rounding must give 1 + 1 = 2 cents, got "
            f"{invoice['provisional_total_cents']}"
        )

    def test_three_half_cent_lines_diverge_further(self, api):
        """PRD 3.6: "Each line's amount is its `weight_lbs` multiplied by the
        facility's `rate_per_lb_cents`, rounded half up to a whole cent; when
        the line's `isolation_flag` is true, a surcharge equal to that rounded
        line amount multiplied by the facility's `isolation_surcharge_pct`,
        itself rounded half up to a whole cent, is added."
        PRD 3.6: "The provisional total is the sum of these per-line amounts —
        per-line rounding always happens before summation."

        Design: Difficulty/combinatorial_formula/provisional_total_rounds_per_line_then_sums
        """
        ctx = base_scenario()
        towel = create_towel_stock(ctx["facility"]["id"])
        gown = create_gown_stock(ctx["facility"]["id"])
        manifest = self._tiny_line_manifest(
            ctx,
            [
                (ctx["stock"]["id"], 0.0125),
                (towel["id"], 0.0125),
                (gown["id"], 0.0125),
            ],
        )
        invoice = create_invoice(
            ctx["facility"]["id"], [manifest["id"]], period_adjusted_patient_days=10
        )
        # 1 + 1 + 1 = 3; summing raw line amounts first would give
        # round_half_up(1.5) = 2.
        assert invoice["provisional_total_cents"] == 3, (
            f"per-line rounding must give 3 cents, got "
            f"{invoice['provisional_total_cents']}"
        )


class TestCreditEvaluationOrder:
    """Credits are computed independently of totals and applied exactly once
    across a dispute/re-finalize cycle (PRD 3.6, 3.7)."""

    def _setup_with_verified_complaint(self):
        ctx = setup_finalized_invoice()  # final 560, billed 560
        complaint = create_complaint(
            ctx["unit"]["id"], ctx["manifest"]["id"], ctx["stock"]["id"],
            complaint_type="STAINS", pieces_affected=2,
        )
        ctx["complaint"] = validate_success(
            api_client_verify(complaint["id"]), 200
        )
        return ctx

    def test_verify_routes_credit_to_finalized_invoice(self, api):
        """PRD 3.7: "Verification moves an `OPEN` complaint to `VERIFIED` and
        prices its credit: `credit_cents` is `pieces_affected` multiplied by
        the stock's per-piece rate computed from the facility's current
        contracted `rate_per_lb_cents` at verify time — deliberately
        independent of any invoice's computed totals, which breaks any
        circularity between credits and billing."
        PRD 3.7: "When the referenced manifest sits on an invoice that is
        `FINALIZED` or `DISPUTED`, the invoice's `credit_total_cents`
        increases by the credit and its `billed_total_cents` decreases by the
        same amount."

        Design: Difficulty/combinatorial_formula/billed_total_credit_evaluation_order_pinned
        """
        ctx = self._setup_with_verified_complaint()
        complaint = ctx["complaint"]
        assert complaint["credit_cents"] == 160, (
            f"2 pieces x 80 cents per-piece rate = 160, got {complaint['credit_cents']}"
        )
        assert complaint["routed_invoice_id"] == ctx["invoice"]["id"]

        invoice = read_invoice(ctx["invoice"]["id"])
        assert invoice["credit_total_cents"] == 160
        assert invoice["billed_total_cents"] == 400, (
            f"560 - 160 = 400, got {invoice['billed_total_cents']}"
        )

    def test_refinalize_after_dispute_applies_credit_exactly_once(self, api):
        """PRD 3.6: "The evaluation order is pinned to break any apparent
        cycle between credits and totals: first the per-piece rate is computed
        once per stock — `piece_weight_lbs` multiplied by `rate_per_lb_cents`,
        rounded half up to a whole cent; second, `final_total_cents` is
        computed as the sum over every returned line of the line's returned
        `pieces` multiplied by its stock's per-piece rate, with an isolation
        surcharge — the line amount multiplied by `isolation_surcharge_pct`,
        rounded half up to a whole cent — added whenever the corresponding
        manifest line was isolation-flagged; third, `credit_total_cents` is
        taken from the verified complaints routed to this invoice; fourth,
        `billed_total_cents` is the final total minus the credit total, and
        it is recomputed on every later credit change."
        PRD 3.6: "Re-finalization after a dispute recomputes all three
        derived figures fresh."

        Design: Difficulty/combinatorial_formula/billed_total_credit_evaluation_order_pinned
        """
        ctx = self._setup_with_verified_complaint()
        validate_success(api.dispute_invoice(ctx["invoice"]["id"], {}, VENDOR), 200)

        refinalized = validate_success(
            api.finalize_invoice(ctx["invoice"]["id"], LM2), 200
        )
        assert refinalized["status"] == "FINALIZED"
        assert refinalized["final_total_cents"] == 560
        assert refinalized["credit_total_cents"] == 160, (
            "the verified credit must be applied exactly once, not "
            f"recomputed from the new total; got {refinalized['credit_total_cents']}"
        )
        assert refinalized["billed_total_cents"] == 400


def api_client_verify(complaint_id: str):
    """Verify a complaint as lm-1 (raw response for validate_success)."""
    return api_client.verify_complaint(complaint_id, LM)


class TestFinalizeDisputeRefinalizeCycle:
    """FINALIZED -> DISPUTED -> FINALIZED is a valid cycle on invoices."""

    def test_status_sequence_cycles(self, api):
        """PRD 3.6: "It is permitted from `PROVISIONAL` and again from
        `DISPUTED`, but three guards apply first: segregation of duties
        requires the finalizing user's `X-User-ID` to differ from
        `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); every linked
        manifest must be `RECONCILED` (`ERR_MANIFEST_NOT_RECONCILED`); and
        when the facility's `monthly_cap_cents` is set, the computed final
        total must not exceed it (`ERR_CONTRACT_CAP_EXCEEDED`)."
        PRD 3.6: "From `FINALIZED`, a `LaundryVendor` may dispute the invoice
        — moving it to `DISPUTED` with an optional `reason` — and a
        `LinenManager` may record payment, moving it to `SETTLED`, which is
        terminal."

        Design: Difficulty/non_linear_state_machine/invoice_finalize_dispute_refinalize_cycle
        """
        ctx = setup_reconciled_manifest()
        invoice = create_invoice(ctx["facility"]["id"], [ctx["manifest"]["id"]])

        finalized = finalize_invoice(invoice["id"])
        assert finalized["status"] == "FINALIZED"

        disputed = validate_success(
            api.dispute_invoice(invoice["id"], {}, VENDOR), 200
        )
        assert disputed["status"] == "DISPUTED"

        refinalized = validate_success(
            api.finalize_invoice(invoice["id"], LM2), 200
        )
        assert refinalized["status"] == "FINALIZED"

    def test_refinalize_recomputes_identical_totals(self, api):
        """PRD 3.6: "Re-finalization after a dispute recomputes all three
        derived figures fresh."
        PRD 3.6: "Because the provisional pass uses vendor-scale weights while
        the final pass uses returned piece counts, the two totals legitimately
        diverge for identical manifests; the provisional figure is a billing
        estimate, never a liability floor."

        Design: Difficulty/non_linear_state_machine/invoice_finalize_dispute_refinalize_cycle
        """
        ctx = setup_reconciled_manifest()
        invoice = create_invoice(ctx["facility"]["id"], [ctx["manifest"]["id"]])

        first = finalize_invoice(invoice["id"])
        validate_success(api.dispute_invoice(invoice["id"], {}, VENDOR), 200)
        second = validate_success(api.finalize_invoice(invoice["id"], LM2), 200)

        assert first["final_total_cents"] == 560
        assert second["final_total_cents"] == 560, (
            "unchanged inputs must recompute the identical final total, "
            f"got {second['final_total_cents']}"
        )
        assert second["billed_total_cents"] == 560
