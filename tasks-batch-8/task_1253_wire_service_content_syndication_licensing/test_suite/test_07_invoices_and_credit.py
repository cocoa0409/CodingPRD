"""Billing: draft-invoice overage aggregation, the issue-time member credit
waterfall, dismissal refunds, conservation of the member credit balance, and
invoice terminal states."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_invoice,
    create_draft_invoice,
    create_published_article,
    get_subscriber,
    issue_invoice,
    publish_contributing_article,
    record_publication,
    setup_active_subscription,
    setup_subscription_with_entitlement,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["salesops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
BILLING = TEST_USERS["billing_headers"]


class TestInvoiceAggregationAndIssue:
    def _setup_four_publications_scenario(self):
        """Package base 50000, tier multiplier 10000 bp (1.0x), quota 2,
        overage 250, no member discount; non-member subscriber; four published
        articles each republished once in May. Publications 1-2 are within
        quota (billed 0); publications 3-4 are billed 250 each."""
        ctx = setup_subscription_with_entitlement(
            package_overrides={
                "code": "P2",
                "media_rights": "TEXT_ONLY",
                "base_monthly_fee_cents": 50000,
            },
            tier_overrides={
                "code": "T2",
                "min_audience": 1,
                "max_audience": 10000,
                "circulation_multiplier_basis_points": 10000,
                "monthly_republish_quota": 2,
                "overage_per_article_cents": 250,
                "member_discount_pct": 0,
            },
            subscriber_overrides={"declared_audience": 5000, "is_member": False},
            feed_overrides={"code": "F2", "topic": "SPORTS", "embargo_window_minutes": 0},
            start_at="2026-05-01T00:00:00Z",
        )
        pubs = []
        for i in range(4):
            art = create_published_article(
                ctx["feed"]["id"], article_overrides={"headline": f"A{i+1}"}
            )
            pubs.append(
                record_publication(
                    ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
                )
            )
        ctx["publications"] = pubs
        return ctx

    def test_draft_invoice_aggregates_overage_from_publications(self, api):
        """PRD §3.7: "`overage_cents` is the sum of `billed_amount_cents`
        across every publication of this subscription whose `republished_at`
        falls inside the billing month — the month boundary is inclusive at the
        first instant of the named month and exclusive at the first instant of
        the following month — and whose `status` is `RECORDED` or
        `AUDIT_FLAGGED`; `DISMISSED` rows are excluded from the sum."
        PRD §3.7: "`base_fee_cents` is the subscription's
        `monthly_price_cents`, snapshotted as it stands at generation time."

        The overage is the sum of the per-publication billed amounts fixed at
        republication time (250 + 250 = 500), not a figure recomputed at
        invoice time.

        Design: Difficulty/combinatorial_formula/invoice_aggregation_rounding_order_mode_b
        """
        ctx = self._setup_four_publications_scenario()
        assert ctx["subscription"]["monthly_price_cents"] == 50000
        assert [p["billed_amount_cents"] for p in ctx["publications"]] == [0, 0, 250, 250]

        inv = create_draft_invoice(ctx["subscription"]["id"], "2026-05")
        assert_invoice(inv)
        assert inv["status"] == "DRAFT"
        assert inv["base_fee_cents"] == 50000
        assert inv["overage_cents"] == 500

    def test_issue_applies_credit_waterfall_after_overage_summed(self, api):
        """PRD §3.7: "The gross due is `base_fee_cents` plus `overage_cents`.
        The credit applied is the lesser of the subscriber's
        `member_credit_balance_cents` at issue time and that gross due; it is
        recorded as `member_credit_applied_cents`, and the subscriber's
        `member_credit_balance_cents` is decremented by the same amount.
        `total_due_cents` is the gross due minus the applied credit, and it can
        never fall below zero."

        The subscriber is not a member and holds no credit, so the applied
        credit is 0 and total_due_cents = 50000 + 500 - 0 = 50500.

        Design: Difficulty/combinatorial_formula/invoice_aggregation_rounding_order_mode_b
        """
        ctx = self._setup_four_publications_scenario()
        draft = create_draft_invoice(ctx["subscription"]["id"], "2026-05")
        issued = issue_invoice(draft["id"])
        assert issued["status"] == "ISSUED"
        assert issued["base_fee_cents"] == 50000
        assert issued["overage_cents"] == 500
        assert issued["member_credit_applied_cents"] == 0
        assert issued["total_due_cents"] == 50500
        assert (
            get_subscriber(ctx["subscriber"]["id"])["member_credit_balance_cents"] == 0
        )


class TestMemberCreditConservation:
    def _setup_credit_scenario(self):
        """Member subscriber with 5000 cents of contribution credit (one
        500-word contributing article, no assets). Subscription quota is 1, so
        the second republication is billed 250 and then flagged for audit.

        Returns (ctx, pub1, pub2, invoice) where the invoice has been ISSUED:
        gross due = base 10000 + overage 250 = 10250; credit applied = min(
        5000, 10250) = 5000; balance drops to 0."""
        ctx = setup_subscription_with_entitlement(
            package_overrides={
                "code": "P13",
                "media_rights": "TEXT_AND_PHOTO",
                "base_monthly_fee_cents": 10000,
            },
            tier_overrides={
                "code": "T13",
                "min_audience": 1,
                "max_audience": 10000,
                "circulation_multiplier_basis_points": 10000,
                "monthly_republish_quota": 1,
                "overage_per_article_cents": 250,
                "member_discount_pct": 0,
            },
            subscriber_overrides={"declared_audience": 5000, "is_member": True},
            feed_overrides={"code": "F13", "topic": "FEATURES", "embargo_window_minutes": 0},
        )
        sub_id = ctx["subscriber"]["id"]
        # Grant 5000 cents of member credit (500 words -> base bracket 5000).
        grant_art = publish_contributing_article(
            ctx["feed"]["id"], sub_id, body_word_count=500
        )
        assert grant_art["member_credit_cents"] == 5000
        assert get_subscriber(sub_id)["member_credit_balance_cents"] == 5000

        # First republication (within the quota of 1) reuses the grant article.
        pub1 = record_publication(ctx["subscription"]["id"], grant_art["id"], sub_id)
        assert pub1["within_quota"] is True
        assert pub1["billed_amount_cents"] == 0

        # Second republication crosses the quota and is billed 250.
        art2 = create_published_article(
            ctx["feed"]["id"], article_overrides={"headline": "B", "body_word_count": 100}
        )
        pub2 = record_publication(ctx["subscription"]["id"], art2["id"], sub_id)
        assert pub2["within_quota"] is False
        assert pub2["billed_amount_cents"] == 250

        return ctx, pub1, pub2

    def test_issue_consumes_credit_and_dismiss_refunds_billed_amount(self, api):
        """PRD §3.7: "The gross due is `base_fee_cents` plus `overage_cents`.
        The credit applied is the lesser of the subscriber's
        `member_credit_balance_cents` at issue time and that gross due; it is
        recorded as `member_credit_applied_cents`, and the subscriber's
        `member_credit_balance_cents` is decremented by the same amount.
        `total_due_cents` is the gross due minus the applied credit, and it can
        never fall below zero."
        PRD §3.6: "Dismissal carries a refund: if the publication's
        `billed_amount_cents` is greater than zero, that amount is credited
        back to the subscriber's `member_credit_balance_cents`."

        Credit is conserved: pre-issue balance 5000 = applied 5000 + balance 0;
        the dismissal then refunds exactly the flagged publication's billed
        250, taking the balance to 250.

        Design: Difficulty/compensating_invariant/member_credit_balance_conserved_through_invoice_issue_and_dismiss
        """
        ctx, pub1, pub2 = self._setup_credit_scenario()
        sub_id = ctx["subscriber"]["id"]

        # Flag the billed publication; AUDIT_FLAGGED rows still count toward
        # the invoice overage sum.
        flagged = validate_success(api.flag_publication(pub2["id"], AUDITOR), 200)
        assert flagged["status"] == "AUDIT_FLAGGED"

        draft = create_draft_invoice(ctx["subscription"]["id"], "2026-05")
        assert draft["overage_cents"] == 250
        issued = issue_invoice(draft["id"])
        assert issued["member_credit_applied_cents"] == 5000
        assert issued["total_due_cents"] == 10250 - 5000
        assert get_subscriber(sub_id)["member_credit_balance_cents"] == 0

        dismissed = validate_success(api.dismiss_publication(pub2["id"], AUDITOR), 200)
        assert dismissed["status"] == "DISMISSED"
        assert get_subscriber(sub_id)["member_credit_balance_cents"] == 250

    def test_dismiss_without_billed_amount_grants_no_refund(self, api):
        """PRD §3.6: "Dismissal carries a refund: if the publication's
        `billed_amount_cents` is greater than zero, that amount is credited
        back to the subscriber's `member_credit_balance_cents`."

        The flagged publication was within quota (billed_amount_cents == 0),
        so dismissal moves it to DISMISSED without changing the subscriber's
        credit balance.

        Design: Difficulty/compensating_invariant/member_credit_balance_conserved_through_invoice_issue_and_dismiss
        """
        ctx, pub1, pub2 = self._setup_credit_scenario()
        sub_id = ctx["subscriber"]["id"]

        flagged = validate_success(api.flag_publication(pub1["id"], AUDITOR), 200)
        assert flagged["status"] == "AUDIT_FLAGGED"
        dismissed = validate_success(api.dismiss_publication(pub1["id"], AUDITOR), 200)
        assert dismissed["status"] == "DISMISSED"
        # No invoice was issued and the dismissed row was unbilled: the
        # balance is untouched at the granted 5000.
        assert get_subscriber(sub_id)["member_credit_balance_cents"] == 5000


class TestInvoiceTerminalState:
    def test_invoice_terminal_paid_cannot_be_voided(self, api):
        """PRD §3.7: "Paying moves an `ISSUED` invoice to `PAID`. Voiding moves
        a `DRAFT` invoice to `VOIDED` — the same destination the
        subscriber-termination cascade forces on every outstanding `DRAFT`
        invoice. Both `PAID` and `VOIDED` are terminal."
        PRD §2.8: "the target resource is in the exact from-state the
        transition requires (for example, an article must be `DRAFT` before
        publishing, a subscription must be `DRAFT` before activation); failure
        yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/invoice_terminal_paid_cannot_be_voided
        """
        ctx = setup_active_subscription(
            package_overrides={"media_rights": "TEXT_ONLY", "base_monthly_fee_cents": 10000},
            tier_overrides={
                "min_audience": 1,
                "max_audience": 10000,
                "circulation_multiplier_basis_points": 10000,
                "monthly_republish_quota": 5,
                "overage_per_article_cents": 100,
            },
        )
        draft = create_draft_invoice(ctx["subscription"]["id"], "2026-05")
        issued = issue_invoice(draft["id"])
        assert issued["status"] == "ISSUED"
        paid = validate_success(api.pay_invoice(draft["id"], BILLING), 200)
        assert paid["status"] == "PAID"

        res = api.void_invoice(draft["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
