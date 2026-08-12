"""Payment lifecycle, ledger compensation, and fiscal caps.

Covers the cyclic payment machine (REQUESTED -> ... -> CLEARED -> RETURNED ->
REQUESTED), the conserved invoice balance across clear/return/re-clear/settle,
the deductible and customer-balance fiscal caps, and the payable-state gate
outranking fiscal failures.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_claim_ctx, transition_claim, setup_submitted_estimate,
    setup_in_progress_claim, setup_invoiced_claim, read_claim,
    list_claim_payments, find_payment, drive_payment_to_cleared,
    create_payment_payload, make_customer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

# 500,000c single-line FIRE claim, FLAT deductible 50,000, no depreciation.
_FIRE_ENTRY = ({"category_code": "GEN-1", "trade": "GENERAL", "kind": "LABOR",
                "unit": "EA", "unit_price_cents": 200,
                "default_depreciation_pct": 0},)
_FIRE_POLICY = {"coverage_a_limit_cents": 5000000, "flat_deductible_cents": 50000}


def _fire_invoiced_ctx(api, **kwargs):
    return setup_invoiced_claim(
        cause_of_loss="FIRE", carrier_overrides={"name": "ZeroTax Mutual",
                                                 "tax_rate": 0},
        policy_overrides=_FIRE_POLICY, entry_specs=_FIRE_ENTRY,
        line_specs=[(0, 2500)], **kwargs)


class TestPaymentReturnRequeueCycle:
    def test_payment_return_requeue_cycle(self, api):
        """PRD §3.9: "A bounced or clawed-back payment moves `ISSUED → RETURNED` or
        `CLEARED → RETURNED`: a payment that had been cleared is excluded as the
        paid counters, invoice `applied_cents`, and posture are recomputed."
        PRD §3.9: "A `RETURNED` payment may be re-presented, moving back to
        `REQUESTED`."
        PRD §3.9: "`DEPRECIATION_PENDING` while an active invoice is `ISSUED` but
        unsettled"

        Design: Difficulty/non_linear_state_machine/payment_return_requeue_cycle
        """
        ctx = _fire_invoiced_ctx(api, direct_pay=True, clear_advance=True)
        claim_id = ctx["claim"]["id"]
        advance = ctx["advance"]
        assert advance["amount_cents"] == 450000, "acv 500,000 - deductible 50,000"
        # clawback edge from CLEARED
        returned = validate_success(api.return_payment(advance["id"], ADMIN), 200)
        assert returned["status"] == "RETURNED"
        claim = read_claim(claim_id)
        assert claim["carrier_paid_cents"] == 0, \
            "compensation: ledger excludes the returned payment"
        assert claim["payment_posture"] == "DEPRECIATION_PENDING", \
            "invoice still ISSUED and unsettled"
        # requeue completes the cycle RETURNED -> REQUESTED
        requeued = validate_success(api.requeue_payment(advance["id"], ADMIN), 200)
        assert requeued["status"] == "REQUESTED"
        final = drive_payment_to_cleared(advance["id"], "CARRIER_TO_CONTRACTOR")
        assert final["status"] == "CLEARED"
        assert read_claim(claim_id)["carrier_paid_cents"] == 450000, \
            "full loop: 450,000 -> 0 -> 450,000, no drift"

    def test_payment_bounce_from_issued_then_represented(self, api):
        """PRD §3.9: "A bounced or clawed-back payment moves `ISSUED → RETURNED` or
        `CLEARED → RETURNED`: a payment that had been cleared is excluded as the
        paid counters, invoice `applied_cents`, and posture are recomputed."
        PRD §3.9: "A `RETURNED` payment may be re-presented, moving back to
        `REQUESTED`."

        Design: Difficulty/non_linear_state_machine/payment_return_requeue_cycle
        """
        ctx = setup_in_progress_claim(
            cause_of_loss="FIRE", carrier_overrides={"name": "ZeroTax Mutual",
                                                     "tax_rate": 0},
            policy_overrides=_FIRE_POLICY, entry_specs=_FIRE_ENTRY,
            line_specs=[(0, 2500)], direct_pay=True, clear_advance=False)
        claim_id = ctx["claim"]["id"]
        advance = ctx["advance"]
        # bounce edge: ISSUED -> RETURNED before any clearing
        validate_success(api.approve_payment(advance["id"], ADJUSTER), 200)
        validate_success(api.issue_payment(advance["id"], ADJUSTER), 200)
        returned = validate_success(api.return_payment(advance["id"], ADMIN), 200)
        assert returned["status"] == "RETURNED"
        assert read_claim(claim_id)["carrier_paid_cents"] == 0, \
            "never cleared: counter stays 0"
        requeued = validate_success(api.requeue_payment(advance["id"], ADMIN), 200)
        assert requeued["status"] == "REQUESTED"
        final = drive_payment_to_cleared(advance["id"], "CARRIER_TO_CONTRACTOR")
        assert final["status"] == "CLEARED"
        assert read_claim(claim_id)["carrier_paid_cents"] == 450000


class TestInvoiceBalanceInvariant:
    def test_clear_and_return_preserve_invoice_balance(self, api):
        """PRD §3.9: "The conserved quantity throughout: an invoice's `total_cents`
        always equals its `outstanding_cents` plus the cleared payments applied to
        it."
        PRD §3.9: "When a clearing makes `applied_cents` reach `total_cents`, the
        invoice settles to `SETTLED`, the claim moves `INVOICED → CLOSED`, and its
        `payment_posture` becomes `PAID_IN_FULL`."

        Design: Difficulty/compensating_invariant/payment_clear_and_return_preserve_invoice_balance
        """
        ctx = _fire_invoiced_ctx(api, direct_pay=True, clear_advance=True)
        claim_id = ctx["claim"]["id"]
        invoice_id = ctx["invoice"]["id"]
        advance_id = ctx["advance"]["id"]

        def invoice_outstanding():
            return validate_success(api.get_invoice(invoice_id, ADMIN), 200)

        # at issue: 500,000 = 50,000 outstanding + 450,000 cleared advance
        assert invoice_outstanding()["outstanding_cents"] == 50000
        # clawback: cleared sum back to 0 -> outstanding restored to full
        validate_success(api.return_payment(advance_id, ADMIN), 200)
        inv = invoice_outstanding()
        assert inv["outstanding_cents"] == 500000
        assert inv["total_cents"] == inv["outstanding_cents"] + 0
        # re-present and re-clear: 500,000 = 50,000 + 450,000
        validate_success(api.requeue_payment(advance_id, ADMIN), 200)
        drive_payment_to_cleared(advance_id, "CARRIER_TO_CONTRACTOR")
        assert invoice_outstanding()["outstanding_cents"] == 50000
        # deductible collection at exactly the cap settles the invoice
        ded = validate_success(api.create_payment(
            claim_id, create_payment_payload("DEDUCTIBLE", 50000),
            make_customer_headers(ctx["customer"]["id"])), 201)
        drive_payment_to_cleared(ded["id"], "CUSTOMER_TO_CONTRACTOR")
        inv = invoice_outstanding()
        assert inv["status"] == "SETTLED" and inv["outstanding_cents"] == 0
        claim = read_claim(claim_id)
        assert claim["status"] == "CLOSED"
        assert claim["payment_posture"] == "PAID_IN_FULL"
        assert claim["deductible_collected_cents"] == 50000, \
            "exactly the deductible; auto-close bubble-up"

    def test_partial_clearing_preserves_invoice_balance(self, api):
        """PRD §3.9: "The conserved quantity throughout: an invoice's `total_cents`
        always equals its `outstanding_cents` plus the cleared payments applied to
        it."
        PRD §3.9: "When a clearing makes `applied_cents` reach `total_cents`, the
        invoice settles to `SETTLED`, the claim moves `INVOICED → CLOSED`, and its
        `payment_posture` becomes `PAID_IN_FULL`."

        Design: Difficulty/compensating_invariant/payment_clear_and_return_preserve_invoice_balance
        """
        ctx = _fire_invoiced_ctx(api, direct_pay=True, clear_advance=True)
        claim_id = ctx["claim"]["id"]
        invoice_id = ctx["invoice"]["id"]
        # partial customer payment: 500,000 = 20,000 + (450,000 + 30,000)
        cb = validate_success(api.create_payment(
            claim_id, create_payment_payload("CUSTOMER_BALANCE", 30000), ADMIN), 201)
        drive_payment_to_cleared(cb["id"], "CUSTOMER_TO_CONTRACTOR")
        inv = validate_success(api.get_invoice(invoice_id, ADMIN), 200)
        assert inv["outstanding_cents"] == 20000
        assert inv["total_cents"] == inv["outstanding_cents"] + 480000
        # final 20,000 clears the balance
        cb2 = validate_success(api.create_payment(
            claim_id, create_payment_payload("CUSTOMER_BALANCE", 20000), ADMIN), 201)
        drive_payment_to_cleared(cb2["id"], "CUSTOMER_TO_CONTRACTOR")
        inv = validate_success(api.get_invoice(invoice_id, ADMIN), 200)
        assert inv["status"] == "SETTLED" and inv["outstanding_cents"] == 0
        assert read_claim(claim_id)["status"] == "CLOSED"


class TestFiscalCaps:
    def test_deductible_overpayment_boundary(self, api):
        """PRD §3.9: "a `DEDUCTIBLE` payment may not push the running total of
        deductible payments in `CLEARED`, `ISSUED`, `APPROVED`, or `REQUESTED`
        status plus the new amount above the claim's `deductible_cents` — exactly
        equal is allowed — else `ERR_DEDUCTIBLE_OVERPAID` (HTTP 422)."

        Design: Corner/validations/deductible_overpayment_boundary
        """
        ctx = setup_in_progress_claim(
            cause_of_loss="FIRE", carrier_overrides={"name": "ZeroTax Mutual",
                                                     "tax_rate": 0},
            policy_overrides=_FIRE_POLICY, entry_specs=_FIRE_ENTRY,
            line_specs=[(0, 100)], direct_pay=False)
        claim_id = ctx["claim"]["id"]
        customer = make_customer_headers(ctx["customer"]["id"])
        # 50,001 > 50,000 cap
        res = api.create_payment(claim_id,
                                 create_payment_payload("DEDUCTIBLE", 50001), customer)
        validate_error(res, ApiErrorId.ERR_DEDUCTIBLE_OVERPAID)
        # exactly-at-cap is allowed (<= boundary)
        ok = validate_success(api.create_payment(
            claim_id, create_payment_payload("DEDUCTIBLE", 50000), customer), 201)
        assert ok["status"] == "REQUESTED"

    def test_customer_balance_over_outstanding_rejected(self, api):
        """PRD §3.9: "a `CUSTOMER_BALANCE` payment may not exceed the active
        invoice's `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`,
        HTTP 422)"

        Design: Corner/validations/customer_balance_over_outstanding_rejected
        """
        ctx = _fire_invoiced_ctx(api, direct_pay=False)
        claim_id = ctx["claim"]["id"]
        # no direct pay: outstanding is the full 500,000
        res = api.create_payment(claim_id,
                                 create_payment_payload("CUSTOMER_BALANCE", 500001),
                                 ADMIN)
        validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)
        ok = validate_success(api.create_payment(
            claim_id, create_payment_payload("CUSTOMER_BALANCE", 100000), ADMIN), 201)
        assert ok["status"] == "REQUESTED"


class TestPayableStateBeatsFiscal:
    def test_claim_state_beats_payment_fiscal(self, api):
        """PRD §3.9: "The claim must be in a payable state — `AUTHORIZED`,
        `IN_PROGRESS`, `ON_HOLD`, `COMPLETE`, or `INVOICED` — else
        `ERR_CLAIM_NOT_PAYABLE` (HTTP 409)."
        PRD §2.7: "and temporal or fiscal failures surface only after every earlier
        tier has passed."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_payment_fiscal
        """
        # claim driven to DENIED: submitted INITIAL estimate denied by the adjuster
        ctx = setup_submitted_estimate(
            cause_of_loss="WATER",
            carrier_overrides={"name": "Acme Mutual", "tax_rate": 0.07},
            policy_overrides={"coverage_a_limit_cents": 100000000,
                              "flat_deductible_cents": 100000},
            line_specs=[(0, 100)])
        validate_success(api.deny_estimate(ctx["estimate"]["id"], ADJUSTER), 200)
        assert read_claim(ctx["claim"]["id"])["status"] == "DENIED"
        # 999,999c also exceeds the 0 outstanding balance; state (p6) wins
        res = api.create_payment(ctx["claim"]["id"],
                                 create_payment_payload("CUSTOMER_BALANCE", 999999),
                                 ADMIN)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)

    def test_withdrawn_claim_rejects_payment_before_fiscal_check(self, api):
        """PRD §3.9: "The claim must be in a payable state — `AUTHORIZED`,
        `IN_PROGRESS`, `ON_HOLD`, `COMPLETE`, or `INVOICED` — else
        `ERR_CLAIM_NOT_PAYABLE` (HTTP 409)."
        PRD §2.7: "and temporal or fiscal failures surface only after every earlier
        tier has passed."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_payment_fiscal
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides={"name": "Acme Mutual",
                                                "tax_rate": 0.07},
                             policy_overrides={"coverage_a_limit_cents": 100000000,
                                               "flat_deductible_cents": 100000})
        transition_claim(ctx["claim"]["id"], "WITHDRAWN")
        # amount also breaches the 100,000 deductible cap; state still wins
        res = api.create_payment(
            ctx["claim"]["id"], create_payment_payload("DEDUCTIBLE", 999999),
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)
