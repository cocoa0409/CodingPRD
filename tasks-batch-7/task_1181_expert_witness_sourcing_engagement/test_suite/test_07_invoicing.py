"""Invoicing: per-line rounding, tiered caps, dispute/resubmit cycle, RBAC, segregation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_invoice, ApiErrorId,
    submit_invoice, approve_invoice,
    setup_active_engagement,
    TEST_USERS, make_expert_headers, make_billing_reviewer_headers, make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
BILLING = TEST_USERS["billing_reviewer_headers"]


class TestTieredCaps:

    def test_multipliers_and_expense_cap_compose(self, api):
        """PRD §3.7: "Each line's charge is the line's `hours` multiplied by the
        engagement's `hourly_rate_cents`, multiplied by the kind multiplier: 1.00 for
        `PREP`, 1.25 for `TESTIMONY`, 0.50 for `TRAVEL_TIME`." and "The travel allowance is
        the lesser of the claimed `travel_expense_cents` and the remaining expense room —
        the engagement's `expense_cap_cents` minus its `expenses_approved_cents`, floored at
        zero".

        Design: Difficulty/combinatorial_formula/invoice_allowed_amount_tiered_caps
        """
        sc = setup_active_engagement(engagement_overrides={"expense_cap_cents": 40_000})
        invoice = submit_invoice(
            sc["engagement"]["id"], sc["expert"]["id"],
            [{"kind": "PREP", "hours": 10}, {"kind": "TESTIMONY", "hours": 4},
             {"kind": "TRAVEL_TIME", "hours": 2}],
            680_000, travel_expense_cents=50_000)
        assert_invoice(invoice)
        # service: 10*40000*1.00 + 4*40000*1.25 + 2*40000*0.50 = 640000; expense min(50000, 40000) = 40000
        assert invoice["computed_total_cents"] == 680_000

    def test_expense_room_depleted_by_prior_approval(self, api):
        """PRD §3.7: "the remaining expense room — the engagement's `expense_cap_cents`
        minus its `expenses_approved_cents`, floored at zero, where the approved figure
        accumulates only the allowed expense portions of invoices in `APPROVED` or `PAID`."
        and "The `computed_total_cents` is the service total plus the allowance."

        Design: Difficulty/combinatorial_formula/invoice_allowed_amount_tiered_caps
        """
        sc = setup_active_engagement(engagement_overrides={"expense_cap_cents": 40_000})
        eid = sc["expert"]["id"]
        gid = sc["engagement"]["id"]

        first = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 10}], 440_000,
                               travel_expense_cents=50_000)
        assert first["computed_total_cents"] == 440_000, "cap 40000 binds on the first invoice"
        approve_invoice(first["id"])

        second = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 1}], 40_000,
                                travel_expense_cents=50_000,
                                period_start="2026-05-11T00:00:00Z",
                                period_end="2026-05-15T00:00:00Z")
        assert second["computed_total_cents"] == 40_000, (
            "expense room is 40000 - 40000 = 0 after the first approval")


class TestPerLineRoundingPinned:

    def test_per_line_round_then_sum_total_accepted(self, api):
        """PRD §3.7: "Every line amount is rounded half-up to the nearest whole cent first,
        and only then summed into the service total; the alternative order — summing the raw
        unrounded line values and rounding once at the end — is explicitly not used and
        produces different cents (at a rate of 10001 cents per hour, two one-hour
        `TRAVEL_TIME` lines total 10002 cents under the pinned per-line order versus 10001
        under the counterfactual)."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_pinned
        """
        sc = setup_active_engagement(engagement_overrides={"hourly_rate_cents": 10_001})
        invoice = submit_invoice(
            sc["engagement"]["id"], sc["expert"]["id"],
            [{"kind": "TRAVEL_TIME", "hours": 1}, {"kind": "TRAVEL_TIME", "hours": 1}],
            10_002)
        assert invoice["computed_total_cents"] == 10_002, (
            "per-line round_half_up: 5001 + 5001")

    def test_sum_then_round_total_rejected(self, api):
        """PRD §3.7: "A declared `total_cents` that differs from the recomputation — by even
        one cent — is rejected with `ERR_INVOICE_AMOUNT_MISMATCH`" and "the alternative
        order — summing the raw unrounded line values and rounding once at the end — is
        explicitly not used and produces different cents (at a rate of 10001 cents per hour,
        two one-hour `TRAVEL_TIME` lines total 10002 cents under the pinned per-line order
        versus 10001 under the counterfactual)."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_pinned
        """
        sc = setup_active_engagement(engagement_overrides={"hourly_rate_cents": 10_001})
        res = api.create_invoice(
            sc["engagement"]["id"],
            {"period_start": "2026-05-04T00:00:00Z", "period_end": "2026-05-08T00:00:00Z",
             "line_items": [{"kind": "TRAVEL_TIME", "hours": 1}, {"kind": "TRAVEL_TIME", "hours": 1}],
             "travel_expense_cents": 0, "total_cents": 10_001},
            make_expert_headers(sc["expert"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVOICE_AMOUNT_MISMATCH)


class TestRetainerDrawdownOrder:

    def _setup_two_invoice_scenario(self, api):
        """ACTIVE engagement: rate 40000, retainer 300000 funded, cap 40000; invoice A
        (20000) already approved (drawn 20000, remaining 280000); invoice B (680000)
        SUBMITTED."""
        sc = setup_active_engagement(
            case_overrides={"budget_cents": 2_000_000},
            engagement_overrides={"retainer_cents": 300_000, "expense_cap_cents": 40_000})
        eid = sc["expert"]["id"]
        gid = sc["engagement"]["id"]
        inv_a = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 0.5}], 20_000)
        approve_invoice(inv_a["id"])
        inv_b = submit_invoice(gid, eid,
                               [{"kind": "PREP", "hours": 10}, {"kind": "TESTIMONY", "hours": 4},
                                {"kind": "TRAVEL_TIME", "hours": 2}],
                               680_000, travel_expense_cents=50_000,
                               period_start="2026-05-11T00:00:00Z",
                               period_end="2026-05-15T00:00:00Z")
        return sc, inv_b

    def test_draw_reads_pre_mutation_remaining(self, api):
        """PRD §2.8: "first the invoice's `computed_total_cents` is computed from the
        current rate card, before any balance moves; the budget gate then reads the case's
        paid actuals and approved-outstanding amounts as of the pre-approval state; the draw
        is then taken as the lesser of the approved total and the retainer remaining as it
        stood before this draw; only after that is the draw added to `retainer_drawn_cents`"
        and "the draw — the lesser of the approved total and the remaining retainer — is
        recorded as the invoice's `retainer_draw_cents`, the remainder of the total becomes
        its `billed_to_client_cents`".

        Design: Difficulty/combinatorial_formula/retainer_drawdown_evaluation_order
        """
        sc, inv_b = self._setup_two_invoice_scenario(api)
        approved = validate_success(api.approve_invoice(inv_b["id"], BILLING), 200)
        assert approved["status"] == "APPROVED"
        assert approved["retainer_draw_cents"] == 280_000, "draw reads pre-mutation remaining, not 300000"
        assert approved["billed_to_client_cents"] == 400_000

    def test_ledger_after_second_approval(self, api):
        """PRD §2.8: "the engagement's `retainer_drawn_cents` grows by the draw" and "One
        conservation invariant holds at all times: the funded amount always equals the sum
        of the drawn, refunded, and remaining amounts, and the remaining amount never goes
        negative."

        Design: Difficulty/combinatorial_formula/retainer_drawdown_evaluation_order
        """
        sc, inv_b = self._setup_two_invoice_scenario(api)
        validate_success(api.approve_invoice(inv_b["id"], BILLING), 200)

        engagement = validate_success(api.get_engagement(sc["engagement"]["id"], CM), 200)
        assert engagement["retainer_drawn_cents"] == 300_000
        assert engagement["retainer_remaining_cents"] == 0
        assert engagement["retainer_funded_cents"] == 300_000
        assert engagement["retainer_funded_cents"] == (
            engagement["retainer_drawn_cents"] + engagement["retainer_refunded_cents"]
            + engagement["retainer_remaining_cents"])


class TestDisputeResubmitCycle:

    def _setup_disputed(self, api):
        sc = setup_active_engagement()
        inv = submit_invoice(sc["engagement"]["id"], sc["expert"]["id"],
                             [{"kind": "PREP", "hours": 0.5}], 20_000)
        disputed = validate_success(api.dispute_invoice(
            inv["id"], {"reason": "hours too high"}, BILLING), 200)
        return sc, disputed

    def test_resubmit_recomputes_totals_and_preserves_dispute_count(self, api):
        """PRD §3.7: "The engaged expert resubmits with replacement `line_items`,
        `travel_expense_cents`, and `total_cents` (`DISPUTED` → `SUBMITTED`); the interval
        rule fires first and the server recomputation second, in the same pinned order as
        the original submission, with any divergence rejected as
        `ERR_INVOICE_AMOUNT_MISMATCH`, and `dispute_count` is left unchanged by
        resubmission."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
        """
        sc, disputed = self._setup_disputed(api)
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_count"] == 1

        resubmitted = validate_success(api.resubmit_invoice(
            disputed["id"],
            {"line_items": [{"kind": "PREP", "hours": 0.25}],
             "travel_expense_cents": 0, "total_cents": 10_000},
            make_expert_headers(sc["expert"]["id"])), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["computed_total_cents"] == 10_000, "totals recomputed on resubmit, not the original 20000"
        assert resubmitted["dispute_count"] == 1

    def test_cycle_completes_to_approved(self, api):
        """PRD §3.7: "Disputes cycle without losing history. A `BillingReviewer` disputes a
        submitted invoice with a `reason` (`SUBMITTED` → `DISPUTED`), incrementing
        `dispute_count` by one." and "Approval additionally requires the invoice to be
        `SUBMITTED`, the engagement to be `ACTIVE`, and the case not to be `CLOSED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
        """
        sc, disputed = self._setup_disputed(api)
        validate_success(api.resubmit_invoice(
            disputed["id"],
            {"line_items": [{"kind": "PREP", "hours": 0.25}],
             "travel_expense_cents": 0, "total_cents": 10_000},
            make_expert_headers(sc["expert"]["id"])), 200)

        approved = validate_success(api.approve_invoice(disputed["id"], BILLING), 200)
        assert approved["status"] == "APPROVED"
        assert approved["dispute_count"] == 1, "dispute history survives the cycle"
        assert approved["computed_total_cents"] == 10_000


class TestInvoiceRbac:

    def test_expert_cannot_approve_invoice(self, api):
        """PRD §2.1: "an attempt to perform an action outside the caller's designated role
        — including action-level rules such as the conflict-waiver reservation or the
        expert-ownership rules — is rejected with `ERR_FORBIDDEN` (HTTP 403)." and "A
        `BillingReviewer` approves, disputes, and settles invoices against the matter
        budget".

        Design: Corner/roles/expert_cannot_approve_invoice_forbidden
        """
        sc = setup_active_engagement()
        inv = submit_invoice(sc["engagement"]["id"], sc["expert"]["id"],
                             [{"kind": "PREP", "hours": 1}], 40_000)

        res = api.approve_invoice(inv["id"], make_expert_headers(sc["expert"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_segregation_of_duties_blocks_creator_approval(self, api):
        """PRD §3.7: "segregation of duties first — the approver's `X-User-ID` must differ
        from the engagement's `created_by_user_id`, so the case manager who created the
        engagement cannot approve its invoices, with violations rejected as
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/roles/segregation_of_duties_blocks_creator_approval
        """
        # Build the whole scenario under creator identity cm-9.
        sc = setup_active_engagement(cm_user_id="cm-9")
        cm9_headers = make_case_manager_headers("cm-9")
        inv = submit_invoice(sc["engagement"]["id"], sc["expert"]["id"],
                             [{"kind": "PREP", "hours": 1}], 40_000)
        assert sc["engagement"]["created_by_user_id"] == "cm-9"

        res = api.approve_invoice(inv["id"], make_billing_reviewer_headers("cm-9"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        approved = validate_success(api.approve_invoice(
            inv["id"], make_billing_reviewer_headers("br-2")), 200)
        assert approved["status"] == "APPROVED", "a different BillingReviewer may approve"
