"""Invoices, payments, payment voids, make-good credit lifecycle, receivable
and outstanding reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    create_active_contract,
    create_active_sponsor,
    create_countersigned_contract,
    create_venue,
    get_success_data,
    issue_invoice,
    list_contract_invoices,
    post_payment,
    setup_active_contract_scenario,
    setup_missed_deliverable_with_credit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    AM_SUBMITTER,
    FINANCE,
    am_headers,
)


SIGNING_COMPOUND_TOTAL = 12_363_600  # round_half_up(30,909,000 * 0.40)


def _setup_issued_signing(api, escalator_mode="COMPOUND", escalator_pct=0.03,
                          term_last=2028):
    """ACTIVE contract + ISSUED SIGNING invoice. Returns (scenario, invoice)."""
    s = setup_active_contract_scenario(
        base_fee_cents=10_000_000, escalator_pct=escalator_pct,
        escalator_mode=escalator_mode, term_first_season=2026,
        term_last_season=term_last, with_asset=False)
    invoice = list_contract_invoices(s["contract"]["id"])[0]
    issue_invoice(invoice["id"])
    return s, invoice


class TestPaymentExactBalanceBoundary:
    """Difficulty rule boundary_precision_check, money-cents metric."""

    def test_payment_one_cent_short_leaves_partially_paid(self, api):
        """PRD §3.7: "an `ISSUED` invoice becomes `PARTIALLY_PAID` when the
        paid and credited amounts are positive but short of the full
        `amount_cents`, or `PAID` when a single posting or redemption covers
        the full remaining balance"

        Design: Difficulty/boundary_precision_check/payment_exact_balance_marks_paid
        """
        _s, invoice = _setup_issued_signing(api)
        resp = validate_success(api.post_payment(
            invoice["id"],
            {"amount_cents": SIGNING_COMPOUND_TOTAL - 1, "method": "ACH"},
            FINANCE))
        assert resp["invoice_status"] == "PARTIALLY_PAID"
        assert resp["paid_cents_after"] == SIGNING_COMPOUND_TOTAL - 1

    def test_payment_at_exact_balance_marks_paid_and_overpay_rejected(self, api):
        """PRD §3.7: "an amount no greater than the invoice's remaining balance
        — its `amount_cents` minus `paid_cents` minus `credits_applied_cents`
        (`ERR_PAYMENT_EXCEEDS_BALANCE`)"
        PRD §3.7: "a `PARTIALLY_PAID` invoice becomes `PAID` when the running
        total completes the amount."

        Design: Difficulty/boundary_precision_check/payment_exact_balance_marks_paid
        """
        _s, invoice = _setup_issued_signing(api)
        post_payment(invoice["id"], SIGNING_COMPOUND_TOTAL - 1)

        # Remaining is exactly 1; paying 2 overpays by 1 cent.
        resp_over = api.post_payment(invoice["id"],
                                     {"amount_cents": 2, "method": "ACH"},
                                     FINANCE)
        validate_error(resp_over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
                       expected_status=422)

        # Paying the final 1 cent flips to PAID at exact equality.
        resp_paid = validate_success(api.post_payment(
            invoice["id"], {"amount_cents": 1, "method": "ACH"}, FINANCE))
        assert resp_paid["invoice_status"] == "PAID"
        assert resp_paid["paid_cents_after"] == SIGNING_COMPOUND_TOTAL


class TestPaymentPostThenVoidInvariant:
    """Difficulty rule compensating_invariant, receivable money."""

    def _setup_and_pay(self, api):
        s, invoice = _setup_issued_signing(api)
        before = validate_success(api.get_contract(s["contract"]["id"],
                                                   FINANCE))
        assert before["receivable_cents"] == SIGNING_COMPOUND_TOTAL
        return s, invoice, before["receivable_cents"]

    def test_payment_post_moves_receivable(self, api):
        """PRD §2.8: "`receivable_cents` is the sum, over the contract's
        invoices in `ISSUED`, `PARTIALLY_PAID`, `PAID`, or `WRITTEN_OFF`
        status, of each invoice's `amount_cents` minus its `paid_cents` minus
        its `credits_applied_cents`; invoices in `DRAFT` or `VOID` contribute
        nothing."

        Design: Difficulty/compensating_invariant/payment_post_then_void_restores_receivable
        """
        s, invoice, recv_before = self._setup_and_pay(api)
        posted = post_payment(invoice["id"], 5_000_000)
        assert posted["invoice_status"] == "PARTIALLY_PAID"
        assert posted["paid_cents_after"] == 5_000_000

        mid = validate_success(api.get_contract(s["contract"]["id"], FINANCE))
        assert mid["receivable_cents"] == recv_before - 5_000_000

    def test_payment_void_restores_receivable_exactly(self, api):
        """PRD §3.7: "Voiding a payment is the compensation path. The
        sub-record's `voided` flag flips to true, the invoice's `paid_cents`
        falls by the voided amount, and the status is re-derived in reverse: a
        `PAID` invoice falls back to `PARTIALLY_PAID` when some balance remains
        covered, or all the way to `ISSUED` when nothing remains paid or
        credited, and a `PARTIALLY_PAID` invoice likewise returns to `ISSUED`
        when both the paid total and the credited total reach zero."
        PRD §3.7: "Every posting and every void recomputes the contract's
        `receivable_cents`."

        Design: Difficulty/compensating_invariant/payment_post_then_void_restores_receivable
        """
        s, invoice, recv_before = self._setup_and_pay(api)
        posted = post_payment(invoice["id"], 5_000_000)

        voided = validate_success(api.void_payment(
            invoice["id"], posted["payment_id"], FINANCE))
        assert voided["voided"] is True
        assert voided["paid_cents_after"] == 0
        assert voided["invoice_status"] == "ISSUED"

        after = validate_success(api.get_contract(s["contract"]["id"], FINANCE))
        assert after["receivable_cents"] == recv_before, (
            "post+void must leave receivable unchanged")


class TestCreditApproveRedeemInvariant:
    """Difficulty rule compensating_invariant, make-good outstanding balance."""

    def _setup_missed_credit(self, api):
        """ACTIVE contract (base 10,000,000 SIMPLE 0, 2026-2026) + ISSUED
        SIGNING invoice + one deliverable with 7/10 approved, season closed so
        the deliverable is MISSED and the auto-credit is REQUESTED."""
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        invoice = list_contract_invoices(s["contract"]["id"])[0]
        issue_invoice(invoice["id"])
        deliverable, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=7)
        return s, invoice, deliverable, credit

    def test_credit_approve_raises_outstanding(self, api):
        """PRD §3.7: "approval stamps `approved_amount_cents` on the credit and
        adds it to the contract's `make_good_outstanding_cents`."
        PRD §2.8: "`make_good_outstanding_cents` is the sum of
        `approved_amount_cents` over the contract's make-good credits in
        `APPROVED` status only — requested, declined, redeemed, and voided
        credits are all excluded."

        Design: Difficulty/compensating_invariant/credit_approve_then_redeem_restores_outstanding
        """
        s, _invoice, _d, credit = self._setup_missed_credit(api)
        before = validate_success(api.get_contract(s["contract"]["id"],
                                                   FINANCE))
        assert before["make_good_outstanding_cents"] == 0

        approved = validate_success(api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 187_500}, FINANCE))
        assert approved["credit_status"] == "APPROVED"

        mid = validate_success(api.get_contract(s["contract"]["id"], FINANCE))
        assert mid["make_good_outstanding_cents"] == 187_500

    def test_credit_redeem_restores_outstanding_and_comps_deliverable(self, api):
        """PRD §3.7: "Redemption stamps `redeemed_against_invoice_id` with the
        target's id, adds the approved amount to that invoice's
        `credits_applied_cents` — flipping the invoice to `PAID` if its
        remaining balance reaches zero — subtracts the amount from the
        contract's `make_good_outstanding_cents`, recomputes
        `receivable_cents`, and, as the sponsor-facing payoff, flips the linked
        deliverable from `MISSED` to the terminal `COMPED` state."

        Design: Difficulty/compensating_invariant/credit_approve_then_redeem_restores_outstanding
        """
        s, invoice, deliverable, credit = self._setup_missed_credit(api)
        get_success_data(api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 187_500}, FINANCE))

        redeemed = validate_success(api.transition_credit(
            credit["id"], {"action": "REDEEM"}, FINANCE))
        assert redeemed["credit_status"] == "REDEEMED"
        assert redeemed["redeemed_against_invoice_id"] == invoice["id"]

        after = validate_success(api.get_contract(s["contract"]["id"], FINANCE))
        assert after["make_good_outstanding_cents"] == 0
        # SIGNING installment of 10,000,000 is 4,000,000; 4,000,000 - 187,500
        assert after["receivable_cents"] == 3_812_500

        got_invoice = validate_success(api.get_invoice(invoice["id"], FINANCE))
        assert got_invoice["credits_applied_cents"] == 187_500
        assert got_invoice["invoice_status"] == "PARTIALLY_PAID"

        got_d = validate_success(api.get_deliverable(deliverable["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert got_d["deliverable_status"] == "COMPED"


class TestCreditApproveStateBeatsFiscalCap:
    """Difficulty rule priority_pair_validation_conflict (state vs fiscal)."""

    def test_approve_declined_credit_with_over_cap_amount_returns_invalid_state(self, api):
        """PRD §2.12: "Every request is validated against the rule catalogue in
        a fixed priority order, and a failure at any tier masks everything
        below it." Tier 5 is "State-machine legality — the target entity's own
        lifecycle permits the requested action from its current state,
        including terminal-state lockdown and compound state preconditions
        expressed as `ERR_INVALID_STATE`." and tier 10 is "Fiscal checks —
        amount positivity, caps, and balances".

        Design: Difficulty/priority_pair_validation_conflict/credit_approve_state_beats_fiscal_cap
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=7)
        get_success_data(api.transition_credit(credit["id"],
                                               {"action": "DECLINE"}, FINANCE))

        resp = api.transition_credit(
            credit["id"],
            {"action": "APPROVE", "approved_amount_cents": 999_999_999},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_approve_declined_credit_leaves_status_unchanged(self, api):
        """PRD §3.7: "Declining (`DECLINE`) moves a `REQUESTED` credit to
        `DECLINED` with no ledger effect." and "`REDEEMED`, `DECLINED`, and
        `VOIDED` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/credit_approve_state_beats_fiscal_cap
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=7)
        get_success_data(api.transition_credit(credit["id"],
                                               {"action": "DECLINE"}, FINANCE))
        validate_error(api.transition_credit(
            credit["id"],
            {"action": "APPROVE", "approved_amount_cents": 187_500}, FINANCE),
            ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        got = validate_success(api.get_credit(credit["id"], FINANCE))
        assert got["credit_status"] == "DECLINED"


class TestInvoiceIssueRules:
    def test_invoice_double_issue_rejected(self, api):
        """PRD §3.7: "A `FinanceManager` issues (`ISSUE`) a `DRAFT` invoice"
        PRD §2.12: "**State-machine legality** — the target entity's own
        lifecycle permits the requested action from its current state,
        including terminal-state lockdown and compound state preconditions
        expressed as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invoice_double_issue_rejected
        """
        s, invoice = _setup_issued_signing(api)
        resp = api.transition_invoice(invoice["id"], {"action": "ISSUE"},
                                      FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        contract = validate_success(api.get_contract(s["contract"]["id"],
                                                     FINANCE))
        assert contract["receivable_cents"] == SIGNING_COMPOUND_TOTAL, (
            "rejected re-issue must not move the receivable")

    def test_receivable_counts_only_open_invoices(self, api):
        """PRD §2.8: "`receivable_cents` is the sum, over the contract's
        invoices in `ISSUED`, `PARTIALLY_PAID`, `PAID`, or `WRITTEN_OFF`
        status, of each invoice's `amount_cents` minus its `paid_cents` minus
        its `credits_applied_cents`; invoices in `DRAFT` or `VOID` contribute
        nothing."

        Design: Corner/calculations/receivable_counts_only_open_invoices
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_countersigned_contract(
            venue["id"], sponsor["id"], term_last_season=2028,
            escalator_pct=0.03, escalator_mode="COMPOUND")

        at_sign = validate_success(api.get_contract(contract["id"], FINANCE))
        assert at_sign["receivable_cents"] == 0, "DRAFT invoices excluded"

        activate_contract(contract["id"])
        invoices = list_contract_invoices(contract["id"])
        issue_invoice(invoices[0]["id"])
        # Void the still-DRAFT MID_SEASON invoice — must be a no-op for the
        # receivable.
        get_success_data(api.transition_invoice(invoices[1]["id"],
                                                {"action": "VOID"}, FINANCE))

        end = validate_success(api.get_contract(contract["id"], FINANCE))
        assert end["receivable_cents"] == SIGNING_COMPOUND_TOTAL


class TestPaymentGates:
    def test_payment_on_draft_invoice_rejected(self, api):
        """PRD §3.7: "Posting a payment requires the invoice to be `ISSUED` or
        `PARTIALLY_PAID` (`ERR_INVOICE_NOT_PAYABLE`)"

        Design: Corner/validations/payment_on_draft_invoice_rejected
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          term_last_season=2028,
                                          escalator_pct=0.03,
                                          escalator_mode="COMPOUND")
        invoice = list_contract_invoices(contract["id"])[0]
        assert invoice["invoice_status"] == "DRAFT"

        resp = api.post_payment(invoice["id"],
                                {"amount_cents": 1_000_000, "method": "ACH"},
                                FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE,
                       expected_status=409)

    def test_payment_zero_amount_rejected(self, api):
        """PRD §3.7: "an `amount_cents` that is a positive integer
        (`ERR_INVALID_AMOUNT`)"

        Design: Corner/validations/payment_zero_amount_rejected
        """
        _s, invoice = _setup_issued_signing(api)
        resp = api.post_payment(invoice["id"],
                                {"amount_cents": 0, "method": "ACH"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT, expected_status=422)


class TestCreditCapAndRedeemGates:
    def test_credit_approve_over_cap_rejected(self, api):
        """PRD §3.7: "Approval (`APPROVE`) of a `REQUESTED` credit requires an
        `approved_amount_cents` input that is a positive integer
        (`ERR_INVALID_AMOUNT`) and that does not exceed the make-good cap
        computed for the linked deliverable (`ERR_CREDIT_EXCEEDS_CAP`)"

        Design: Corner/validations/credit_approve_over_cap_rejected
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=7)
        # Cap: (10-7) * 50,000 * 1.25 = 187,500
        resp_over = api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 200_000}, FINANCE)
        validate_error(resp_over, ApiErrorId.ERR_CREDIT_EXCEEDS_CAP,
                       expected_status=422)

        ok = validate_success(api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 187_500}, FINANCE))
        assert ok["credit_status"] == "APPROVED", "cap boundary is inclusive"

    def test_credit_redeem_without_payable_invoice_rejected(self, api):
        """PRD §3.7: "the target is selected from the credit's contract's
        invoices in `ISSUED` or `PARTIALLY_PAID` status by lowest
        `installment_seq`, with ties broken by earliest `created_at`, and an
        empty pool is rejected with `ERR_NO_PAYABLE_INVOICE` (HTTP 409)."

        Design: Corner/validations/credit_redeem_without_payable_invoice_rejected
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=7)
        # Approve WITHOUT issuing any invoice — pool is empty.
        get_success_data(api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 187_500}, FINANCE))

        resp = api.transition_credit(credit["id"], {"action": "REDEEM"},
                                     FINANCE)
        validate_error(resp, ApiErrorId.ERR_NO_PAYABLE_INVOICE,
                       expected_status=409)
        got = validate_success(api.get_credit(credit["id"], FINANCE))
        assert got["credit_status"] == "APPROVED"

    def test_credit_redeem_exceeding_invoice_balance_rejected(self, api):
        """PRD §3.7: "The approved amount must not exceed the selected
        invoice's remaining balance (`ERR_CREDIT_EXCEEDS_INVOICE_BALANCE`)."

        Design: Corner/validations/credit_redeem_exceeding_invoice_balance_rejected
        """
        # Small contract: base 100,000 SIMPLE 0 -> SIGNING = 40,000.
        s = setup_active_contract_scenario(base_fee_cents=100_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        invoice = list_contract_invoices(s["contract"]["id"])[0]
        assert invoice["amount_cents"] == 40_000
        issue_invoice(invoice["id"])

        # Deliverable with zero approved units -> MISSED with pct 0 -> 1.50
        # tier: 10 * 50,000 * 1.50 = 750,000, capped at season fee 100,000.
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=0)
        assert credit["requested_amount_cents"] == 100_000
        get_success_data(api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 100_000}, FINANCE))

        resp = api.transition_credit(credit["id"], {"action": "REDEEM"},
                                     FINANCE)
        validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_INVOICE_BALANCE,
                       expected_status=422)
        got = validate_success(api.get_credit(credit["id"], FINANCE))
        assert got["credit_status"] == "APPROVED"


class TestMakeGoodLowestTier:
    def test_make_good_lowest_tier_uncapped(self, api):
        """PRD §3.5: "The multiplier is 1.00 when the fraction is at least
        0.90, 1.25 when the fraction is at least 0.70 but below 0.90, and 1.50
        when the fraction is below 0.70 — the tier boundaries are inclusive on
        the lower side, so a fraction of exactly 0.90 earns the 1.00 multiplier
        and a fraction of exactly 0.70 earns 1.25."
        PRD §3.5: "The make-good amount is the lesser of the raw credit and the
        cap."

        Design: Corner/calculations/make_good_lowest_tier_uncapped
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=6)
        # fraction 0.6 < 0.70 -> 1.50 tier: (10-6) * 50,000 * 1.50 = 300,000
        assert credit["requested_amount_cents"] == 300_000


class TestCreditApprovalRbac:
    def test_activation_manager_cannot_approve_credit(self, api):
        """PRD §4: POST /make-good-credits/{credit_id}/transition is authorized
        for FinanceManager only.
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        — or, for a sponsor contact, whose target lies outside their
        sponsorship scope — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/activation_manager_cannot_approve_credit
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        _d, credit = setup_missed_deliverable_with_credit(
            s["contract"], s["venue"]["id"], s["asset"]["id"],
            contracted_units=10, approved_units=7)

        resp = api.transition_credit(
            credit["id"], {"action": "APPROVE",
                           "approved_amount_cents": 187_500},
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        got = validate_success(api.get_credit(credit["id"], FINANCE))
        assert got["credit_status"] == "REQUESTED"
