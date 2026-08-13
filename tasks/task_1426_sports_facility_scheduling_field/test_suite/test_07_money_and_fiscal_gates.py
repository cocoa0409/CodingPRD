"""Money movement: cancellation penalty tiers, the deposit-disposition
waterfall, invoice money conservation, refund approval thresholds, and the
fiscal gates on payments, refunds, voids, and adjustments."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_deposit_waterfall_conservation,
    assert_invoice_money_identity,
    cancel_permit_as_owner,
    create_adjustment_payload,
    create_payment_payload,
    create_refund_payload,
    get_invoice,
    issue_invoice,
    make_athletics_admin_headers,
    make_finance_clerk_headers,
    pay_invoice,
    set_clock,
    setup_awarded_permit,
    setup_confirmed_permit,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["finance_clerk_headers"]
ADMIN = TEST_USERS["athletics_admin_headers"]


class TestCancelPenaltyWaterfall:
    """CONFIRMED permit 2026-08-10 18:00-20:00 with lights (quoted total 9600,
    deposit 5000 paid), cancelled at 2026-08-09T12:00 — 30 hours of notice."""

    def test_penalty_computed_from_pre_cancel_total_at_30pct(self, api):
        """PRD §3.8: "From `CONFIRMED`, cancellation must precede the slot start —
        cancelling at or after the start fails with `ERR_INVALID_PERMIT_STATE` — and
        the notice period, measured as the whole hours between the logical clock and
        the slot start with fractional hours discarded, sets the tier: at least 168
        hours (seven days) of notice costs nothing; at least 48 hours costs 15
        percent; at least 24 hours costs 30 percent; anything shorter costs 50
        percent. The penalty is the permit's pre-cancel `quoted_total_cents`
        multiplied by the tier percent, divided by 100, and rounded half-up. The
        evaluation order is pinned: the penalty is computed against the pre-cancel
        quoted total; then the invoice's `total_cents` is replaced by `penalty_cents`;
        and only then does the deposit waterfall run — never the reverse."

        30 hours of notice lands in the 30% tier: round_half_up(9600 x 30 / 100) =
        2880, computed against the pre-cancel 9600; then total_cents is replaced.

        Design: Difficulty/combinatorial_formula/cancel_penalty_pre_cancel_base_then_waterfall
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        assert ctx["permit"]["quoted_total_cents"] == 9600
        set_clock("2026-08-09T12:00:00Z")  # 30 whole hours before the 18:00 start
        cancelled = validate_success(cancel_permit_as_owner(
            ctx["permit"]["id"], ctx["organization"]["id"]), 200)
        assert cancelled["status"] == "CANCELLED"

        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["penalty_cents"] == 2880
        assert invoice["total_cents"] == 2880, \
            "the invoice total is REPLACED by the penalty after penalty computation"

    def test_waterfall_buckets_and_conservation(self, api):
        """PRD §3.8: "First, the deposit held is the smaller of the net payments
        (`paid_cents` minus `refunded_cents`) and the invoice's `deposit_cents`. That
        held amount then drains through three buckets in order. Bucket one,
        `deposit_penalty_applied_cents`, absorbs as much of the held deposit as the
        invoice's `penalty_cents` allows. Bucket two, `deposit_balance_applied_cents`,
        absorbs from what remains an amount up to the non-penalty balance still owed —
        the larger of zero and `total_cents` minus `penalty_cents`. Bucket three,
        `deposit_refunded_cents`, receives whatever is left. Money is conserved: at
        every closeout the three buckets sum exactly to the deposit held. A positive
        refund bucket creates a `REFUND` Payment of exactly that amount, subject to
        the 10,000-cent approval threshold described above."

        Held 5000 drains: 2880 to the penalty, 0 to the (replaced) balance, 2120 to
        an auto-cleared refund; the invoice settles to balance 0.

        Design: Difficulty/combinatorial_formula/cancel_penalty_pre_cancel_base_then_waterfall
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        set_clock("2026-08-09T12:00:00Z")
        validate_success(cancel_permit_as_owner(
            ctx["permit"]["id"], ctx["organization"]["id"]), 200)

        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["deposit_penalty_applied_cents"] == 2880
        assert invoice["deposit_balance_applied_cents"] == 0
        assert invoice["deposit_refunded_cents"] == 2120
        assert_deposit_waterfall_conservation(invoice)  # 5000 == 2880 + 0 + 2120
        assert invoice["refunded_cents"] == 2120
        assert invoice["balance_due_cents"] == 0
        assert_invoice_money_identity(invoice)


class TestInvoiceMoneyConservation:
    """Conserved quantity: money. 2-hour lights permit, total 9600, deposit 5000."""

    def test_payment_side_of_the_identity(self, api):
        """PRD §3.8: "The `deposit_cents` snapshots the permit's
        `deposit_required_cents` at invoice creation; `paid_cents` sums the cleared
        `PAYMENT` rows and `refunded_cents` the cleared `REFUND` rows; and
        `balance_due_cents` is the total minus net payments, where net means paid
        minus refunded."
        PRD §3.8: "Cleared payments recompute `paid_cents` and `balance_due_cents` and
        advance the invoice on their own: `ISSUED` → `PARTIALLY_PAID` while a balance
        remains, and on to `PAID` once the balance reaches 0."

        After a 5000 payment: 9600 == (5000 - 0) + 4600, status PARTIALLY_PAID.

        Design: Difficulty/compensating_invariant/invoice_money_conservation_payment_refund
        """
        ctx = setup_awarded_permit(app_overrides={"wants_lights": True})
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        pay_invoice(invoice_id, 5000)
        invoice = get_invoice(invoice_id)
        assert invoice["total_cents"] == 9600
        assert invoice["paid_cents"] == 5000
        assert invoice["refunded_cents"] == 0
        assert invoice["balance_due_cents"] == 4600
        assert_invoice_money_identity(invoice)
        assert invoice["status"] == "PARTIALLY_PAID"

    def test_payment_and_partial_refund_leave_identity_exact(self, api):
        """PRD §3.8: "The `deposit_cents` snapshots the permit's
        `deposit_required_cents` at invoice creation; `paid_cents` sums the cleared
        `PAYMENT` rows and `refunded_cents` the cleared `REFUND` rows; and
        `balance_due_cents` is the total minus net payments, where net means paid
        minus refunded."
        PRD §3.8: "A refund of 10,000 cents or less is created directly in `CLEARED`
        status; a larger one starts `PENDING_APPROVAL` and moves money only after an
        administrator approves it."

        Payment 5000 then refund 2000 (auto-cleared): 9600 == (5000 - 2000) + 6600
        exactly, and the invoice stays PARTIALLY_PAID — a partial refund does not
        change the payment status.

        Design: Difficulty/compensating_invariant/invoice_money_conservation_payment_refund
        """
        ctx = setup_awarded_permit(app_overrides={"wants_lights": True})
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        pay_invoice(invoice_id, 5000)

        refund = validate_success(api.create_refund(
            invoice_id, create_refund_payload(2000, "Partial goodwill"), CLERK), 201)
        assert refund["status"] == "CLEARED", "2000 <= 10000 auto-approves"
        assert refund["kind"] == "REFUND"

        invoice = get_invoice(invoice_id)
        assert invoice["total_cents"] == 9600
        assert invoice["paid_cents"] == 5000
        assert invoice["refunded_cents"] == 2000
        assert invoice["balance_due_cents"] == 6600
        assert_invoice_money_identity(invoice)
        assert invoice["status"] == "PARTIALLY_PAID"


class TestRefundApprovalThreshold:
    """COMMERCIAL 480-minute slot: field 40000 + 25% surcharge 10000 = 50000,
    deposit 12500; invoice paid in full (50000)."""

    def _setup_paid_commercial_invoice(self, api):
        ctx = setup_awarded_permit(
            app_overrides={"start_minute": 360, "end_minute": 840,  # 06:00-14:00
                           "headcount": 100},
            org_overrides={"name": "Acme Corp Games", "classification": "COMMERCIAL",
                           "org_type": "CORPORATE", "prior_seasons_active": 0})
        assert ctx["permit"]["quoted_total_cents"] == 50000
        assert ctx["permit"]["deposit_required_cents"] == 12500, \
            "25% of 50000 is above the 5000 floor"
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        pay_invoice(invoice_id, 50000, method="CARD", clerk_id="clerk-1")
        invoice = get_invoice(invoice_id)
        assert invoice["status"] == "PAID"
        return ctx, invoice_id

    def test_refund_at_threshold_auto_clears(self, api):
        """PRD §3.8: "A refund of 10,000 cents or less is created directly in
        `CLEARED` status; a larger one starts `PENDING_APPROVAL` and moves money only
        after an administrator approves it."

        Exactly 10000 clears immediately and counts in refunded_cents at once.

        Design: Difficulty/boundary_precision_check/refund_auto_approve_threshold_boundary
        """
        ctx, invoice_id = self._setup_paid_commercial_invoice(api)
        refund = validate_success(api.create_refund(
            invoice_id, create_refund_payload(10000, "Goodwill partial"),
            make_finance_clerk_headers("clerk-1")), 201)
        assert refund["status"] == "CLEARED", "exactly at the threshold auto-approves"
        invoice = get_invoice(invoice_id)
        assert invoice["refunded_cents"] == 10000
        assert_invoice_money_identity(invoice)

    def test_refund_over_threshold_pends_then_approves(self, api):
        """PRD §3.8: "A refund of 10,000 cents or less is created directly in
        `CLEARED` status; a larger one starts `PENDING_APPROVAL` and moves money only
        after an administrator approves it. Approval requires the payment to still be
        `PENDING_APPROVAL`, else `ERR_INVALID_PAYMENT_STATE`, and segregation of
        duties applies: an approver whose `X-User-ID` equals the row's `initiated_by`
        is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval stamps `approved_by`,
        adds the amount to the invoice's `refunded_cents`, recomputes
        `balance_due_cents`, and — when cleared refunds fully cover the net paid
        amount with the invoice total at 0 — settles the invoice to `REFUNDED` from
        either `PAID` or `PARTIALLY_PAID`."
        PRD §3.8: "The `deposit_cents` snapshots the permit's
        `deposit_required_cents` at invoice creation; `paid_cents` sums the cleared
        `PAYMENT` rows and `refunded_cents` the cleared `REFUND` rows; and
        `balance_due_cents` is the total minus net payments, where net means paid
        minus refunded."

        10001 (one cent over) starts PENDING_APPROVAL and does not count until
        approved by a different operator; then refunded_cents reaches 20001 and the
        balance recomputes to 20001.

        Design: Difficulty/boundary_precision_check/refund_auto_approve_threshold_boundary
        """
        ctx, invoice_id = self._setup_paid_commercial_invoice(api)
        clerk = make_finance_clerk_headers("clerk-1")
        first = validate_success(api.create_refund(
            invoice_id, create_refund_payload(10000, "Goodwill partial"), clerk), 201)
        assert first["status"] == "CLEARED"

        pending = validate_success(api.create_refund(
            invoice_id, create_refund_payload(10001, "Larger partial"), clerk), 201)
        assert pending["status"] == "PENDING_APPROVAL", "one cent over the threshold"
        invoice = get_invoice(invoice_id)
        assert invoice["refunded_cents"] == 10000, \
            "a pending refund does not count toward refunded_cents"

        approved = validate_success(api.approve_payment(
            pending["id"], make_athletics_admin_headers("admin-9")), 200)
        assert approved["status"] == "CLEARED"
        assert approved["approved_by"] == "admin-9"

        invoice = get_invoice(invoice_id)
        assert invoice["refunded_cents"] == 20001
        assert invoice["balance_due_cents"] == 20001, \
            "50000 total minus net payments (50000 - 20001)"
        assert_invoice_money_identity(invoice)


class TestFiscalGates:
    def test_payment_above_balance_rejected(self, api):
        """PRD §3.8: "The amount may not exceed the invoice's `balance_due_cents`,
        else `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Paying 4001 against a 4000-balance invoice is impossible.

        Design: Corner/errors/payment_above_balance_rejected
        """
        ctx = setup_awarded_permit()  # 2h no lights: total 4000
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        res = api.record_payment(invoice_id, create_payment_payload(4001), CLERK)
        validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
        invoice = get_invoice(invoice_id)
        assert invoice["paid_cents"] == 0
        assert invoice["balance_due_cents"] == 4000

    def test_refund_above_net_paid_rejected(self, api):
        """PRD §3.8: "A clerk initiates one with an `amount_cents` and a `reason`,
        capped at the net paid amount — `paid_cents` minus `refunded_cents` — else
        `ERR_REFUND_EXCEEDS_PAID`."

        Refunding 4001 when net paid is 4000 fails and moves nothing.

        Design: Corner/errors/refund_above_net_paid_rejected
        """
        ctx = setup_awarded_permit()
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        pay_invoice(invoice_id, 4000)
        assert get_invoice(invoice_id)["status"] == "PAID"

        res = api.create_refund(invoice_id, create_refund_payload(4001, "Too much"),
                                CLERK)
        validate_error(res, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)
        invoice = get_invoice(invoice_id)
        assert invoice["refunded_cents"] == 0
        assert invoice["balance_due_cents"] == 0

    def test_void_partially_paid_invoice_rejected(self, api):
        """PRD §3.8: "Voiding requires zero cleared payments: a `DRAFT` or `ISSUED`
        invoice with `paid_cents` at 0 becomes `VOID`, while any invoice holding
        payments fails with `ERR_INVOICE_HAS_PAYMENTS` — which means the
        `PARTIALLY_PAID` → `VOID` path always fails fiscally, existing only to keep
        that error reachable."

        Design: Corner/state_machines/void_partially_paid_invoice_rejected
        """
        ctx = setup_awarded_permit(app_overrides={"wants_lights": True})  # total 9600
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        pay_invoice(invoice_id, 5000)
        assert get_invoice(invoice_id)["status"] == "PARTIALLY_PAID"

        res = api.void_invoice(invoice_id, CLERK)
        validate_error(res, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)
        assert get_invoice(invoice_id)["status"] == "PARTIALLY_PAID"

    def test_payment_approve_cleared_payment_rejected(self, api):
        """PRD §3.8: "Recording a payment takes an `amount_cents` of at least 1 and a
        `method` of `CHECK`, `CARD`, `CASH`, or `CREDIT`, and creates a Payment row of
        `kind` `PAYMENT` directly in `CLEARED` status."
        PRD §3.8: "Approval requires the payment to still be `PENDING_APPROVAL`, else
        `ERR_INVALID_PAYMENT_STATE`, and segregation of duties applies: an approver
        whose `X-User-ID` equals the row's `initiated_by` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Approving a kind=PAYMENT row (born CLEARED) is rejected.

        Design: Corner/state_machines/payment_approve_cleared_payment_rejected
        """
        ctx = setup_awarded_permit()
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        payment = pay_invoice(invoice_id, 4000, clerk_id="clerk-1")
        assert payment["status"] == "CLEARED"

        res = api.approve_payment(payment["id"], make_athletics_admin_headers("admin-9"))
        validate_error(res, ApiErrorId.ERR_INVALID_PAYMENT_STATE)


class TestInvoiceAdjustmentOcc:
    def test_occ_invoice_adjustment_stale_version_rejected(self, api):
        """PRD §3.8: "Clerks may also post a signed manual `delta_cents` with an
        explanatory `note` against an invoice in `ISSUED` or `PARTIALLY_PAID` status;
        any other invoice state fails with `ERR_INVALID_INVOICE_STATE`. The operation
        is OCC-guarded per §2.7 through `expected_invoice_version`. The delta
        accumulates into `adjustment_cents`, and `total_cents` and `balance_due_cents`
        recompute."
        PRD §2.7: "When the supplied value does not match the entity's current
        `version`, because another write has advanced that version since the client's
        last read, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        +500 posts (total 10100); replaying the same version is stale; the fresh
        version posts +300 (total 10400, adjustment_cents 800).

        Design: Corner/complexity_layers/occ_invoice_adjustment_stale_version_rejected
        """
        ctx = setup_awarded_permit(app_overrides={"wants_lights": True})  # total 9600
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        observed = get_invoice(invoice_id)["version"]

        first = validate_success(api.post_adjustment(
            invoice_id,
            create_adjustment_payload(500, "Chalk line repair", observed),
            CLERK), 200)
        assert first["total_cents"] == 10100, "9600 + 500"
        fresh = first["version"]

        replay = api.post_adjustment(
            invoice_id,
            create_adjustment_payload(300, "Key replacement", observed),
            CLERK)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        second = validate_success(api.post_adjustment(
            invoice_id,
            create_adjustment_payload(300, "Key replacement", fresh),
            CLERK), 200)
        assert second["total_cents"] == 10400
        assert second["adjustment_cents"] == 800, "deltas accumulate: 500 + 300"
