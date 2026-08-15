"""Invoicing, collections, commission settlement, and ledger conservation
(PRD §3.8, §3.9)."""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from test_helpers import (
    CO_USER_ID,
    FIN_USER_ID,
    FIN_USER_ID_2,
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    assert_invoice,
    assert_payout,
    create_dispute_payload,
    get_deal,
    get_deal_payout,
    make_active_deal,
    make_brand_headers,
    make_creator_headers,
    make_deal_with_verified_deliverable,
    make_draft_invoice,
    make_finance_headers,
    make_issued_invoice,
    make_paid_invoice_scenario,
    pay_invoice_in_full,
    plan_deliverable,
    publish_flow,
    set_clock,
    validate_error,
    validate_success,
    verify_flow,
)

BM = TEST_USERS["brand_manager_headers"]
FIN = TEST_USERS["finance_admin_headers"]  # X-User-ID == FIN_USER_ID


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class TestInvoiceRoundingOrder:
    def _setup_reduced_deal(self, api):
        """ACTIVE deal with fee_total pinned at 1,503,936 and an upheld
        2.5% fee-reduction dispute applied (deal back to ACTIVE).

        Two deliverables are planned and only one is verified, so the deal
        is still ACTIVE when the dispute is raised (PRD §3.4 bubble-up
        requires every deliverable VERIFIED)."""
        ns = make_active_deal(
            creator_overrides={
                "handle": "crb2", "niche": "TECH", "followers": 250000,
                "avg_views_30d": 80000, "engagement_rate_bps": 450,
            },
            brief_overrides={
                "niche": "TECH", "deliverables_per_slot": 3,
                "usage_rights_days": 120, "exclusivity_category": "SOFTWARE",
                "exclusivity_days": 30, "whitelisting_required": True,
            },
        )
        assert ns.deal["fee_total_cents"] == 1503936, "setup fee pin"
        d1 = plan_deliverable(ns.deal_id, platform="YOUTUBE",
                              scheduled_publish_date="2026-08-03T10:00:00Z")
        plan_deliverable(ns.deal_id, platform="TIKTOK",
                         due_date="2026-08-12T00:00:00Z",
                         scheduled_publish_date="2026-08-05T10:00:00Z")
        verify_flow(ns.deal_id, d1["id"], ns.creator["id"],
                    url="https://yt/red")
        assert get_deal(ns.deal_id)["status"] == "ACTIVE"
        dispute = validate_success(api.create_dispute(
            ns.deal_id,
            create_dispute_payload(reason="SCOPE_CREEP", note="reduce fee"),
            make_creator_headers(ns.creator["id"]),
        ), 201)
        validate_success(api.review_dispute(dispute["id"], BM))
        validate_success(api.resolve_dispute(
            dispute["id"],
            {"action": "UPHOLD", "remedy": "FEE_REDUCTION",
             "reduction_pct": 0.025, "resolution_note": "2.5% off"},
            BM,
        ))
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "ACTIVE", "lighter remedy resumes the deal"
        assert deal["reduction_pct"] == pytest.approx(0.025)
        return ns

    def test_invoice_lines_rounded_individually(self, api):
        """PRD §3.8: "The `fee_line_cents` is the deal's `fee_total_cents`
        multiplied by one minus the deal's `reduction_pct` — a figure that
        starts at zero and moves only through an upheld fee-reduction
        dispute — rounded half up. The `service_line_cents` is five percent
        of that same reduced fee — the deal's `fee_total_cents` multiplied by
        one minus `reduction_pct` and by 0.05 — rounded half up"
        PRD §3.9: "`FEE_REDUCTION` copies the dispute's `reduction_pct` ...
        onto the deal's `reduction_pct`, and every later invoice prices its
        fee and service lines against the reduced fee."

        round_half_up(1,503,936 x 0.975) = 1,466,338 and
        round_half_up(1,503,936 x 0.975 x 0.05) = 73,317.

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ns = self._setup_reduced_deal(api)
        invoice = validate_success(api.create_invoice(ns.deal_id, FIN), 201)
        assert_invoice(invoice)
        assert invoice["fee_line_cents"] == 1466338
        assert invoice["service_line_cents"] == 73317
        assert invoice["bonus_line_cents"] == 0

    def test_invoice_total_sums_rounded_lines(self, api):
        """PRD §3.8: "The invoice denormalizes its `brand_id` from the deal
        and computes its lines at creation, in a pinned order: each line is
        rounded half up to whole cents first, and the rounded lines are then
        summed — summing first and rounding once is forbidden."
        PRD §3.8: "The `total_cents` is the sum of the three rounded lines."

        Per-line rounding then sum yields 1,539,655; the forbidden
        sum-then-round order would yield 1,539,654.

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ns = self._setup_reduced_deal(api)
        invoice = validate_success(api.create_invoice(ns.deal_id, FIN), 201)
        assert invoice["total_cents"] == 1539655
        assert invoice["total_cents"] != 1539654, (
            "sum-then-round is explicitly forbidden and yields different cents"
        )
        assert invoice["total_cents"] == (
            invoice["fee_line_cents"]
            + invoice["service_line_cents"]
            + invoice["bonus_line_cents"]
        )
        assert invoice["status"] == "DRAFT"
        assert invoice["brand_id"] == ns.brand["id"]


class TestCommissionVariants:
    def _setup_macro_deal(self, api):
        """MACRO/FINANCE creator (flat 3,510,000) on a dps=2, 30-day-usage,
        no-exclusivity brief: fee_total 7,020,000. One VERIFIED deliverable
        (the deal stays ACTIVE), invoice ISSUED by fin-operator-1."""
        ns = make_deal_with_verified_deliverable(
            creator_overrides={
                "handle": "crm1", "niche": "FINANCE", "followers": 1500000,
                "avg_views_30d": 500000, "engagement_rate_bps": 600,
            },
            brief_overrides={
                "niche": "FINANCE", "deliverables_per_slot": 2,
                "usage_rights_days": 30,
            },
        )
        assert ns.deal["fee_total_cents"] == 7020000, "setup fee pin"
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        return ns, invoice

    def test_commission_estimated_at_issue(self, api):
        """PRD §3.8: "The rate is 2,000 basis points — twenty percent — while
        the creator's `lifetime_billed_cents` sits below 5,000,000 cents"
        PRD §3.8: "the ESTIMATED pinning at invoice issue reads
        `lifetime_billed_cents` excluding this invoice, which has not yet
        been paid"
        PRD §3.8: "The payout's `gross_cents` is the invoice's
        `fee_line_cents` plus its `bonus_line_cents` — creator earnings,
        excluding the service line"

        gross = 7,020,000; ESTIMATED rate 2,000bps -> commission 1,404,000,
        net 5,616,000.

        Design: Difficulty/dual_variant_calc/commission_estimated_vs_settlement_tier_crossing
        """
        ns, invoice = self._setup_macro_deal(api)
        assert invoice["total_cents"] == 7371000, (
            "fee 7,020,000 + 5% service 351,000"
        )
        payout = get_deal_payout(ns.deal_id)
        assert_payout(payout)
        assert payout["status"] == "ACCRUED"
        assert payout["gross_cents"] == 7020000
        assert payout["commission_rate_bps"] == 2000
        assert payout["commission_cents"] == 1404000
        assert payout["net_cents"] == 5616000

    def test_commission_settlement_repins_after_tier_crossing(self, api):
        """PRD §3.8: "the SETTLEMENT pinning at release reads it including
        this invoice's `fee_line_cents`, added at record-payment — so
        settlement can cross a tier boundary and land on a lower rate than
        the estimate. The re-pinned `commission_rate_bps`,
        `commission_cents`, and `net_cents` replace the estimated figures at
        release."
        PRD §3.8: "1,500 basis points while it sits below 20,000,000 cents"

        Payment lifts lifetime_billed to 7,020,000 (>= 5,000,000), so
        SETTLEMENT re-pins 1,500bps -> commission 1,053,000, net 5,967,000.

        Design: Difficulty/dual_variant_calc/commission_estimated_vs_settlement_tier_crossing
        """
        ns, invoice = self._setup_macro_deal(api)
        pay_invoice_in_full(invoice["id"], payer_user_id=FIN_USER_ID)
        set_clock("2026-08-08T00:00:00Z")  # payout_due_at boundary (paid + 7d)
        payout_id = get_deal_payout(ns.deal_id)["id"]
        released = validate_success(api.release_payout(
            payout_id, make_finance_headers(FIN_USER_ID_2)))
        assert released["status"] == "PAID"
        assert released["commission_rate_bps"] == 1500
        assert released["commission_cents"] == 1053000
        assert released["net_cents"] == 5967000
        creator = validate_success(api.get_creator(ns.creator["id"], FIN))
        assert creator["lifetime_billed_cents"] == 7020000


class TestPaymentCascade:
    def test_payment_flips_payout_payable_with_due_date(self, api):
        """PRD §3.8: "A recorded payment stamps `paid_at` from the logical
        clock, drops the brand's `outstanding_balance_cents` by `total_cents`,
        and fires two cascade links: the invoice's payout moves from
        `ACCRUED` to `PAYABLE` with `payout_due_at` set to exactly seven days
        after `paid_at`, and the creator's `lifetime_billed_cents` rises by
        the invoice's `fee_line_cents`"

        Paid at the default clock (2026-08-01), the payout falls due exactly
        2026-08-08T00:00:00Z.

        Design: Difficulty/transitive_cascade/invoice_payment_cascade_depth2
        """
        ns = make_deal_with_verified_deliverable()
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        payout_before = get_deal_payout(ns.deal_id)
        assert payout_before["status"] == "ACCRUED"

        paid = pay_invoice_in_full(invoice["id"], payer_user_id=FIN_USER_ID)
        assert paid["status"] == "PAID"
        assert_instant_equals(paid["paid_at"], "2026-08-01T00:00:00Z")
        payout = get_deal_payout(ns.deal_id)
        assert payout["status"] == "PAYABLE"
        assert_instant_equals(payout["payout_due_at"], "2026-08-08T00:00:00Z")

    def test_payment_credits_lifetime_billed(self, api):
        """PRD §3.8: "the creator's `lifetime_billed_cents` rises by the
        invoice's `fee_line_cents` — an increment that may push the creator
        across a commission tier boundary."
        PRD §3.1: "The `lifetime_billed_cents` counter, also initially zero,
        accumulates the `fee_line_cents` of every invoice on the creator's
        deals that reaches `PAID`"

        Design: Difficulty/transitive_cascade/invoice_payment_cascade_depth2
        """
        ns = make_deal_with_verified_deliverable()
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        creator_before = validate_success(
            api.get_creator(ns.creator["id"], FIN))
        assert creator_before["lifetime_billed_cents"] == 0
        pay_invoice_in_full(invoice["id"], payer_user_id=FIN_USER_ID)
        creator_after = validate_success(
            api.get_creator(ns.creator["id"], FIN))
        assert creator_after["lifetime_billed_cents"] == invoice[
            "fee_line_cents"], (
            "lifetime_billed rises by exactly the paid invoice's fee line"
        )
        brand = validate_success(api.get_brand(ns.brand["id"], BM))
        assert brand["outstanding_balance_cents"] == 0, (
            "payment drops the outstanding balance by total_cents"
        )


class TestPayoutReleaseGate:
    def test_release_while_accrued_rejected(self, api):
        """PRD §3.8: "A payout releases only from `PAYABLE`"
        PRD §2.9: "triggering one from a non-terminal state the transition
        does not allow is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Only the invoice's transition to PAID flips the payout to PAYABLE;
        while the invoice is merely ISSUED the release is a state error.

        Design: Difficulty/cross_entity_state_dependency/payout_release_gated_on_invoice_paid
        """
        ns = make_deal_with_verified_deliverable()
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        payout = get_deal_payout(ns.deal_id)
        assert payout["status"] == "ACCRUED"
        res = api.release_payout(payout["id"], make_finance_headers(FIN_USER_ID_2))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_payout(payout["id"], FIN))
        assert after["status"] == "ACCRUED"

    def test_release_at_exact_due_instant_allowed(self, api):
        """PRD §3.8: "the logical clock must read at or after `payout_due_at`
        — a reading exactly equal to the due instant is allowed — else
        `ERR_PAYOUT_NOT_DUE`."

        Paid at the default clock, released at exactly 2026-08-08T00:00:00Z.

        Design: Difficulty/cross_entity_state_dependency/payout_release_gated_on_invoice_paid
        """
        ns = make_paid_invoice_scenario()
        assert ns.payout["status"] == "PAYABLE"
        set_clock("2026-08-08T00:00:00Z")
        released = validate_success(api.release_payout(
            ns.payout["id"], make_finance_headers(FIN_USER_ID_2)))
        assert released["status"] == "PAID"


class TestOutstandingBalanceConservation:
    def test_issue_raises_outstanding_by_total(self, api):
        """PRD §3.8: "Issuing moves `DRAFT` → `ISSUED`: `issued_at` is
        stamped from the logical clock, `due_date` falls exactly thirty days
        after `issued_at`, `issued_by_user_id` records the issuing operator,
        and the brand's `outstanding_balance_cents` rises by `total_cents`."
        PRD §3.2: "it rises by an invoice's `total_cents` when the invoice is
        issued"

        Design: Difficulty/compensating_invariant/brand_outstanding_conserved_issue_void
        """
        ns = make_deal_with_verified_deliverable()
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        assert invoice["status"] == "ISSUED"
        assert_instant_equals(invoice["issued_at"], "2026-08-01T00:00:00Z")
        assert_instant_equals(invoice["due_date"], "2026-08-31T00:00:00Z")
        assert invoice["issued_by_user_id"] == FIN_USER_ID
        brand = validate_success(api.get_brand(ns.brand["id"], BM))
        assert brand["outstanding_balance_cents"] == invoice["total_cents"]

    def test_void_compensates_issue_to_zero(self, api):
        """PRD §3.8: "Voiding an `ISSUED` invoice posts the compensating
        entry: the brand's `outstanding_balance_cents` falls by `total_cents`,
        netting the issue to zero, and the invoice's payout moves from
        `ACCRUED` to `VOIDED`."
        PRD §3.8: "Voiding is the compensating path, takes a mandatory
        `void_reason`, and is allowed from `DRAFT` or `ISSUED`."

        Design: Difficulty/compensating_invariant/brand_outstanding_conserved_issue_void
        """
        ns = make_deal_with_verified_deliverable()
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        voided = validate_success(api.void_invoice(
            invoice["id"], {"void_reason": "issued in error"}, FIN))
        assert voided["status"] == "VOID"
        brand = validate_success(api.get_brand(ns.brand["id"], BM))
        assert brand["outstanding_balance_cents"] == 0, (
            "forward issue + compensating void conserve the zero invariant"
        )
        payout = get_deal_payout(ns.deal_id)
        assert payout["status"] == "VOIDED"


class TestLateFee:
    def test_late_fee_started_period_boundary(self, api):
        """PRD §3.8: "the days overdue are the elapsed seconds between
        `due_date` and the payment instant divided by 86,400 and rounded up
        to a whole day — zero when payment is not after the due date; the
        started periods are the days overdue divided by seven and rounded up,
        so one day overdue bills one period, exactly seven days still bills
        one, and eight days bills two; the `late_fee_cents` is then
        `total_cents` multiplied by 1.5 percent and by the number of started
        periods, rounded half up to whole cents."
        PRD §3.8: "Recording payment accepts an `amount_cents` and demands
        exactness: the amount must equal the invoice's `total_cents` plus its
        `late_fee_cents`, else `ERR_PAYMENT_AMOUNT_MISMATCH`."
        PRD §2.5: "every invoice still `ISSUED` whose `due_date` lies behind
        the new clock reading transitions to `OVERDUE`"

        Due 2026-08-31 (issue 2026-08-01 + 30 days); payment at 2026-09-07 is
        exactly 7 days overdue -> 1 started period -> late fee
        round_half_up(total x 0.015).

        Design: Corner/calculations/late_fee_started_period_boundary
        """
        ns = make_deal_with_verified_deliverable()
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        total = invoice["total_cents"]
        assert_instant_equals(invoice["due_date"], "2026-08-31T00:00:00Z")

        set_clock("2026-09-07T00:00:00Z")
        overdue = validate_success(api.get_invoice(invoice["id"], FIN))
        assert overdue["status"] == "OVERDUE", "clock sweep ISSUED -> OVERDUE"

        # Underpayment by exactly the late fee is rejected.
        res = api.record_payment(
            invoice["id"], {"amount_cents": total},
            make_finance_headers(FIN_USER_ID),
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, 422)

        # 7 days overdue -> ceil(7/7) = 1 started period.
        expected_late = _round_half_up(Decimal(total) * Decimal("0.015"))
        paid = validate_success(api.record_payment(
            invoice["id"], {"amount_cents": total + expected_late},
            make_finance_headers(FIN_USER_ID),
        ))
        assert paid["status"] == "PAID"
        assert paid["late_fee_cents"] == expected_late


class TestInvoiceUniqueness:
    def test_second_invoice_rejected(self, api):
        """PRD §3.8: "a deal may hold at most one non-`VOID` invoice at a
        time, so a second live invoice is rejected with
        `ERR_INVOICE_ALREADY_EXISTS`."

        Design: Corner/validations/second_invoice_rejected
        """
        ns = make_deal_with_verified_deliverable()
        make_draft_invoice(ns.deal_id)
        res = api.create_invoice(ns.deal_id, FIN)
        validate_error(res, ApiErrorId.ERR_INVOICE_ALREADY_EXISTS, 409)


class TestPayoutTimingGate:
    def test_payout_release_before_due_rejected(self, api):
        """PRD §3.8: "the logical clock must read at or after `payout_due_at`
        — a reading exactly equal to the due instant is allowed — else
        `ERR_PAYOUT_NOT_DUE`."
        PRD §3.8: "the invoice's payout moves from `ACCRUED` to `PAYABLE`
        with `payout_due_at` set to exactly seven days after `paid_at`"

        Paid at 2026-08-01 (due 2026-08-08); releasing at 2026-08-07 is one
        day early.

        Design: Corner/validations/payout_release_before_due_rejected
        """
        ns = make_paid_invoice_scenario()
        assert ns.payout["status"] == "PAYABLE"
        set_clock("2026-08-07T00:00:00Z")
        res = api.release_payout(
            ns.payout["id"], make_finance_headers(FIN_USER_ID_2))
        validate_error(res, ApiErrorId.ERR_PAYOUT_NOT_DUE, 422)
        after = validate_success(api.get_payout(ns.payout["id"], FIN))
        assert after["status"] == "PAYABLE"


class TestPayoutDisclosureGate:
    def test_payout_release_blocked_by_queued_disclosure(self, api):
        """PRD §3.8: "no disclosure check on any of the deal's deliverables
        may sit in `QUEUED` or `FAILED`, else `ERR_DISCLOSURE_NOT_PASSED`"

        The invoice is PAID, the payout is PAYABLE, and the due instant has
        passed — an unresolved QUEUED check on the deal's second deliverable
        still blocks the release.

        Design: Corner/validations/payout_release_blocked_by_queued_disclosure
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 2})
        d1 = plan_deliverable(ns.deal_id, platform="YOUTUBE",
                              scheduled_publish_date="2026-08-03T10:00:00Z")
        d2 = plan_deliverable(ns.deal_id, platform="TIKTOK",
                              due_date="2026-08-12T00:00:00Z",
                              scheduled_publish_date="2026-08-05T10:00:00Z")
        verify_flow(ns.deal_id, d1["id"], ns.creator["id"],
                    url="https://yt/f1")
        publish_flow(ns.deal_id, d2["id"], ns.creator["id"],
                     url="https://tt/f2")  # leaves a QUEUED check on D2
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        pay_invoice_in_full(invoice["id"], payer_user_id=FIN_USER_ID)
        payout = get_deal_payout(ns.deal_id)
        assert payout["status"] == "PAYABLE"
        set_clock("2026-08-08T00:00:00Z")
        res = api.release_payout(
            payout["id"], make_finance_headers(FIN_USER_ID_2))
        validate_error(res, ApiErrorId.ERR_DISCLOSURE_NOT_PASSED, 409)
        after = validate_success(api.get_payout(payout["id"], FIN))
        assert after["status"] == "PAYABLE"


class TestPayoutSegregation:
    def test_payout_release_rejected_same_user_as_issuer(self, api):
        """PRD §2.10: "The `FinanceAdmin` who releases a payout must not be
        the operator recorded as the funding invoice's `issued_by_user_id`.
        Both violations are rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403), and both compare the acting `X-User-ID` against the
        recorded actor stamp."
        PRD §3.8: "Release re-pins the commission with the SETTLEMENT
        variant, stamps `released_by_user_id` and `released_at`, and lands
        the payout in terminal `PAID`."

        Design: Corner/rbac/payout_release_rejected_same_user_as_issuer
        """
        ns = make_paid_invoice_scenario(issuer_user_id=FIN_USER_ID)
        set_clock("2026-08-08T00:00:00Z")
        res = api.release_payout(
            ns.payout["id"], make_finance_headers(FIN_USER_ID))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        released = validate_success(api.release_payout(
            ns.payout["id"], make_finance_headers(FIN_USER_ID_2)))
        assert released["status"] == "PAID", (
            "a different finance operator releases successfully"
        )
        assert released["released_by_user_id"] == FIN_USER_ID_2


class TestInvoiceImmediateConsistency:
    def test_invoice_create_returns_computed_lines_immediately(self, api):
        """PRD §3.8: "The invoice denormalizes its `brand_id` from the deal
        and computes its lines at creation, in a pinned order: each line is
        rounded half up to whole cents first, and the rounded lines are then
        summed"
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        The creation response itself carries the computed lines: for the
        standard rate card (flat 88,000; 45-day usage) fee_total is 96,800,
        so fee 96,800 + 5% service 4,840 + bonus 0 = total 101,640.

        Design: Corner/consistency_model/invoice_create_returns_computed_lines_immediately
        """
        ns = make_deal_with_verified_deliverable()
        invoice = validate_success(api.create_invoice(ns.deal_id, FIN), 201)
        assert_invoice(invoice)
        assert invoice["fee_line_cents"] == 96800
        assert invoice["service_line_cents"] == 4840
        assert invoice["bonus_line_cents"] == 0
        assert invoice["total_cents"] == 101640
        assert invoice["status"] == "DRAFT"


class TestDisputePayoutHoldCycle:
    def test_dispute_hold_and_resume_payout_cycle(self, api):
        """PRD §3.9: "Raising a dispute on an `ACTIVE` deal moves the deal to
        `IN_DISPUTE`; on a `COMPLETED` deal the deal stays `COMPLETED`.
        Either way, every payout of the deal in `ACCRUED` or `PAYABLE` is
        held automatically."
        PRD §3.9: "Dismissal, and upholding with one of the lighter remedies,
        returns an `IN_DISPUTE` deal to `ACTIVE` and unholds the payouts the
        dispute held — restoring each to `PAYABLE` when its `payout_due_at`
        is set and to `ACCRUED` otherwise."

        Design: Corner/state_machines/dispute_hold_and_resume_payout_cycle
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 2})
        d1 = plan_deliverable(ns.deal_id, platform="YOUTUBE",
                              scheduled_publish_date="2026-08-03T10:00:00Z")
        plan_deliverable(ns.deal_id, platform="TIKTOK",
                         due_date="2026-08-12T00:00:00Z",
                         scheduled_publish_date="2026-08-05T10:00:00Z")
        verify_flow(ns.deal_id, d1["id"], ns.creator["id"],
                    url="https://yt/c2")
        assert get_deal(ns.deal_id)["status"] == "ACTIVE"
        invoice = make_issued_invoice(ns.deal_id, issuer_user_id=FIN_USER_ID)
        pay_invoice_in_full(invoice["id"], payer_user_id=FIN_USER_ID)
        payout = get_deal_payout(ns.deal_id)
        assert payout["status"] == "PAYABLE"
        due_at = payout["payout_due_at"]

        dispute = validate_success(api.create_dispute(
            ns.deal_id,
            create_dispute_payload(reason="NON_PAYMENT", note="late"),
            make_brand_headers(ns.brand["id"]),
        ), 201)
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "IN_DISPUTE"
        held = validate_success(api.get_payout(payout["id"], FIN))
        assert held["status"] == "HELD", "dispute holds the PAYABLE payout"

        validate_success(api.review_dispute(dispute["id"], BM))
        resolved = validate_success(api.resolve_dispute(
            dispute["id"],
            {"action": "DISMISS", "resolution_note": "unfounded"},
            BM,
        ))
        assert resolved["status"] == "RESOLVED_DISMISSED"
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "ACTIVE"
        restored = validate_success(api.get_payout(payout["id"], FIN))
        assert restored["status"] == "PAYABLE", (
            "dismissal restores a paid invoice's payout to PAYABLE"
        )
        assert restored["payout_due_at"] == due_at, (
            "payout_due_at is preserved across the hold/unhold cycle"
        )
