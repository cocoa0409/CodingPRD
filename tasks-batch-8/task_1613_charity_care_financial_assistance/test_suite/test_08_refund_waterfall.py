"""Retroactive refund waterfall: evaluation order, newest-first consumption
with created_at tie-break, the 240-day window boundary, and refund durability
under determination reversal."""
from test_helpers import (
    COMPLIANCE,
    assert_ledger_invariants,
    build_verified_application,
    create_active_policy,
    create_determination,
    create_patient,
    create_account,
    finalize_determination,
    get_account,
    issue_first_statement,
    list_determination_adjustments,
    list_payments,
    post_adjustment,
    post_payment,
    reverse_determination,
    set_clock,
)


def _waterfall_scenario():
    """Account resp 1000000; FIRST_STATEMENT 2026-01-01; payments 300000
    (paid 02-10), 500000 (paid 03-10), 250000 (paid 04-10); STANDARD
    application submitted 2026-05-01 with a 75.00% FINAL determination covering
    the account. Returns (account, payments, determination)."""
    set_clock("2026-01-01T00:00:00Z")
    create_active_policy()
    patient = create_patient(
        full_name="Wanda Waterfall", date_of_birth="1978-07-07",
        ssn_last4="7777", mrn="MRN-WF-1",
    )
    account = create_account(
        patient["id"], total_charges_cents=1000000, insurance_paid_cents=0,
        encounter_date="2025-12-20",
    )
    issue_first_statement(account["id"])
    p1 = post_payment(account["id"], 300000, paid_at="2026-02-10T00:00:00Z", method="CARD")
    p2 = post_payment(account["id"], 500000, paid_at="2026-03-10T00:00:00Z", method="ACH")
    p3 = post_payment(account["id"], 250000, paid_at="2026-04-10T00:00:00Z", method="CHECK")
    set_clock("2026-05-01T00:00:00Z")
    ctx = build_verified_application(
        patient=patient, reported_income=3750000,
        members=(("SELF", 47),), tax_return_amount=3750000,
    )
    det = create_determination(
        ctx["application"]["id"], "VERIFIED_APPLICATION", [account["id"]]
    )
    det = finalize_determination(det["id"])
    return account, (p1, p2, p3), det


class TestRefundEvaluationOrder:
    def test_waterfall_refunds_newest_first(self, api):
        """PRD §3.10: "When a refund is due, the waterfall consumes payments
        newest-first: the account's payments are walked in descending `paid_at`
        order with ties broken by ascending `created_at`; each visited payment
        yields room equal to its `amount_cents` minus its `refunded_cents` (a
        `FULLY_REFUNDED` payment therefore yields zero room); the grant for
        each payment is the smaller of its room and the remaining refund due;
        the grant is added to `refunded_cents`; the payment's status becomes
        `FULLY_REFUNDED` when `refunded_cents` reaches `amount_cents` and
        `PARTIALLY_REFUNDED` otherwise; and a `REFUND` `AccountAdjustment` is
        created recording the grant amount, the `payment_id` it drew from, and
        the determination."

        Design: Difficulty/combinatorial_formula/refund_due_mode_c_evaluation_order_pinned
        """
        account, (p1, p2, p3), det = _waterfall_scenario()
        post_adjustment(account["id"], det["id"])
        payments = {p["id"]: p for p in list_payments(account["id"])}
        # write-off 750000 -> adjusted 250000; effective 1050000 -> refund 800000
        assert payments[p3["id"]]["refunded_cents"] == 250000
        assert payments[p3["id"]]["status"] == "FULLY_REFUNDED"
        assert payments[p2["id"]]["refunded_cents"] == 500000
        assert payments[p2["id"]]["status"] == "FULLY_REFUNDED"
        assert payments[p1["id"]]["refunded_cents"] == 50000, (
            "the oldest payment is touched last and only partially"
        )
        assert payments[p1["id"]]["status"] == "PARTIALLY_REFUNDED"
        spawned = list_determination_adjustments(det["id"])
        refunds = [
            a for a in spawned
            if a["adjustment_type"] == "REFUND" and a["status"] == "POSTED"
        ]
        assert sum(a["amount_cents"] for a in refunds) == 800000
        by_payment = {a["payment_id"]: a["amount_cents"] for a in refunds}
        assert by_payment[p3["id"]] == 250000
        assert by_payment[p2["id"]] == 500000
        assert by_payment[p1["id"]] == 50000

    def test_waterfall_account_outcome(self, api):
        """PRD §2.12: "Refunds mutate `refunded_cents` and therefore shift
        `effective_payments_cents`, but they never change
        `adjusted_balance_cents`, so evaluating the four quantities in this
        order terminates in a single pass. An account whose
        `amount_outstanding_cents` is zero holds the collection posture
        `RESOLVED`."
        PRD §3.10: "After both legs, the account's posture resolves: if
        `amount_outstanding_cents` is now zero, an account in `ASSISTANCE_HOLD`
        moves to `RESOLVED` and every `INITIATED` collection action on it is
        halted with `halt_reason` `ACCOUNT_RESOLVED`; if a balance remains, the
        account moves from `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`."

        Design: Difficulty/combinatorial_formula/refund_due_mode_c_evaluation_order_pinned
        """
        account, _payments, det = _waterfall_scenario()
        post_adjustment(account["id"], det["id"])
        account = get_account(account["id"])
        assert account["adjusted_balance_cents"] == 250000
        assert account["effective_payments_cents"] == 250000, (
            "1050000 collected minus 800000 refunded"
        )
        assert account["amount_outstanding_cents"] == 0
        assert account["collection_posture"] == "RESOLVED"
        assert_ledger_invariants(account)


def _retro_window_scenario(*, submit_at, name, mrn, ssn):
    """Account resp 1000000, FIRST_STATEMENT 2026-01-01, one payment 1000000
    (paid 2026-02-01); TIER_FULL application submitted at submit_at; adjustment
    posted at the same clock. Returns (account, determination)."""
    set_clock("2026-01-01T00:00:00Z")
    create_active_policy()
    patient = create_patient(
        full_name=name, date_of_birth="1981-01-01", ssn_last4=ssn, mrn=mrn,
    )
    account = create_account(
        patient["id"], total_charges_cents=1000000, insurance_paid_cents=0,
        encounter_date="2025-12-20",
    )
    issue_first_statement(account["id"])
    post_payment(account["id"], 1000000, paid_at="2026-02-01T00:00:00Z", method="CARD")
    set_clock(submit_at)
    ctx = build_verified_application(
        patient=patient, reported_income=2000000,
        members=(("SELF", 45),), tax_return_amount=2000000,
    )
    det = create_determination(
        ctx["application"]["id"], "VERIFIED_APPLICATION", [account["id"]]
    )
    det = finalize_determination(det["id"])
    return account, det


class TestRetroactiveWindowBoundary:
    def test_submit_exactly_240_days_after_statement_is_refunded(self, api):
        """PRD §3.10: "An account is retro-eligible when the application's
        `submitted_at` is at or before the account's `first_statement_at` plus
        the pinned policy's `retroactive_window_days`; if `first_statement_at`
        is still null the window has not started and the account is always
        eligible."

        Design: Difficulty/boundary_precision_check/retroactive_window_240_day_boundary_refund_eligibility
        """
        # 2026-01-01 + 240 days == 2026-08-29 — at-or-before is inclusive
        account, det = _retro_window_scenario(
            submit_at="2026-08-29T00:00:00Z", name="Retro In",
            mrn="MRN-RET-IN", ssn="1112",
        )
        post_adjustment(account["id"], det["id"])
        account = get_account(account["id"])
        assert account["adjusted_balance_cents"] == 0
        assert account["effective_payments_cents"] == 0, (
            "the full 1000000 overpayment is refunded inside the window"
        )
        payments = list_payments(account["id"])
        assert len(payments) == 1
        assert payments[0]["status"] == "FULLY_REFUNDED"
        assert payments[0]["refunded_cents"] == 1000000
        spawned = list_determination_adjustments(det["id"])
        refunds = [a for a in spawned if a["adjustment_type"] == "REFUND"]
        assert sum(a["amount_cents"] for a in refunds) == 1000000

    def test_submit_241_days_after_statement_keeps_payments(self, api):
        """PRD §3.10: "An account is retro-eligible when the application's
        `submitted_at` is at or before the account's `first_statement_at` plus
        the pinned policy's `retroactive_window_days`; if `first_statement_at`
        is still null the window has not started and the account is always
        eligible. The refund due is the account's post-write-off
        `overpayment_cents` computed per §2.12 — for a non-eligible account the
        refund due is zero, though the write-off still applies to the balance."

        Design: Difficulty/boundary_precision_check/retroactive_window_240_day_boundary_refund_eligibility
        """
        # 2026-08-30 is 241 days after 2026-01-01 — outside the 240-day window
        account, det = _retro_window_scenario(
            submit_at="2026-08-30T00:00:00Z", name="Retro Out",
            mrn="MRN-RET-OUT", ssn="1113",
        )
        post_adjustment(account["id"], det["id"])
        account = get_account(account["id"])
        assert account["adjusted_balance_cents"] == 0, (
            "the write-off still applies to the balance outside the window"
        )
        assert account["effective_payments_cents"] == 1000000, (
            "no refund posts — the payments are kept"
        )
        payments = list_payments(account["id"])
        assert payments[0]["status"] == "POSTED"
        assert payments[0]["refunded_cents"] == 0
        spawned = list_determination_adjustments(det["id"])
        refunds = [a for a in spawned if a["adjustment_type"] == "REFUND"]
        assert refunds == [], "no REFUND adjustment may exist outside the window"


class TestWaterfallTieBreak:
    def test_tied_paid_at_consumed_in_created_order(self, api):
        """PRD §3.10: "When a refund is due, the waterfall consumes payments
        newest-first: the account's payments are walked in descending `paid_at`
        order with ties broken by ascending `created_at`; each visited payment
        yields room equal to its `amount_cents` minus its `refunded_cents` (a
        `FULLY_REFUNDED` payment therefore yields zero room); the grant for
        each payment is the smaller of its room and the remaining refund due;
        the grant is added to `refunded_cents`; the payment's status becomes
        `FULLY_REFUNDED` when `refunded_cents` reaches `amount_cents` and
        `PARTIALLY_REFUNDED` otherwise; and a `REFUND` `AccountAdjustment` is
        created recording the grant amount, the `payment_id` it drew from, and
        the determination."

        Design: Corner/calculations/refund_waterfall_tiebreak_created_at_asc
        """
        set_clock("2026-01-01T00:00:00Z")
        create_active_policy()
        patient = create_patient(
            full_name="Tiebreak Tom", date_of_birth="1990-10-01",
            ssn_last4="0025", mrn="MRN-TIE-1",
        )
        account = create_account(
            patient["id"], total_charges_cents=1000000, insurance_paid_cents=0,
            encounter_date="2025-12-20",
        )
        issue_first_statement(account["id"])
        # identical paid_at; the earlier-created of the tied pair refunds first
        pay_early = post_payment(
            account["id"], 200000, paid_at="2026-02-10T00:00:00Z", method="CARD"
        )
        pay_late = post_payment(
            account["id"], 200000, paid_at="2026-02-10T00:00:00Z", method="CARD"
        )
        set_clock("2026-03-01T00:00:00Z")
        ctx = build_verified_application(
            patient=patient, reported_income=3750000,
            members=(("SELF", 36),), tax_return_amount=3750000,
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION", [account["id"]]
        )
        det = finalize_determination(det["id"])
        post_adjustment(account["id"], det["id"])
        # write-off 750000 -> adjusted 250000; effective 400000 -> refund 150000
        payments = {p["id"]: p for p in list_payments(account["id"])}
        assert payments[pay_early["id"]]["refunded_cents"] == 150000
        assert payments[pay_early["id"]]["status"] == "PARTIALLY_REFUNDED"
        assert payments[pay_late["id"]]["refunded_cents"] == 0, (
            "ascending created_at tie-break touches the earlier-created payment first"
        )
        assert payments[pay_late["id"]]["status"] == "POSTED"


class TestRefundDurabilityUnderReversal:
    def _refund_then_reverse(self):
        """TIER_FULL write-off with a 500000 payment inside the retro window
        (REFUND 500000 posts), then the determination is reversed."""
        set_clock("2026-01-01T00:00:00Z")
        create_active_policy()
        patient = create_patient(
            full_name="Refund Rev", date_of_birth="1990-01-01",
            ssn_last4="0049", mrn="MRN-RREV-1",
        )
        account = create_account(
            patient["id"], total_charges_cents=1000000, insurance_paid_cents=0,
            encounter_date="2025-12-20",
        )
        issue_first_statement(account["id"])
        payment = post_payment(
            account["id"], 500000, paid_at="2026-02-01T00:00:00Z", method="CARD"
        )
        ctx = build_verified_application(
            patient=patient, reported_income=2000000,
            members=(("SELF", 40),), tax_return_amount=2000000,
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION", [account["id"]]
        )
        det = finalize_determination(det["id"])
        post_adjustment(account["id"], det["id"])
        return account, payment, det

    def test_reversal_keeps_refunds_posted(self, api):
        """PRD §3.8: "First, every `POSTED` write-off adjustment of this
        determination moves to `REVERSED` with `reversed_at` stamped; refund
        adjustments are left `POSTED`."
        PRD §3.10: "a `REFUND` adjustment is never reversible, and any reversal
        attempt against one is rejected with `ERR_REFUND_NOT_REVERSIBLE`
        (HTTP 409)."

        Design: Corner/errors/refund_adjustment_reversal_rejected
        """
        account, payment, det = self._refund_then_reverse()
        reverse_determination(det["id"], headers=COMPLIANCE, reason="audit")
        spawned = list_determination_adjustments(det["id"], headers=COMPLIANCE)
        write_offs = [a for a in spawned if a["adjustment_type"] == "WRITE_OFF"]
        refunds = [a for a in spawned if a["adjustment_type"] == "REFUND"]
        assert len(write_offs) == 1 and write_offs[0]["status"] == "REVERSED"
        assert len(refunds) == 1 and refunds[0]["status"] == "POSTED", (
            "refunded money stays refunded when the determination is reversed"
        )
        payments = list_payments(account["id"])
        assert payments[0]["id"] == payment["id"]
        assert payments[0]["refunded_cents"] == 500000

    def test_reversal_restores_balance_after_refund(self, api):
        """PRD §3.8: "Second, each affected account recomputes its
        `adjusted_balance_cents`, and any account that had been `RESOLVED` but
        now shows `amount_outstanding_cents` greater than zero transitions back
        to `NOTICE_PERIOD`."

        Design: Corner/errors/refund_adjustment_reversal_rejected
        """
        account, _payment, det = self._refund_then_reverse()
        reverse_determination(det["id"], headers=COMPLIANCE, reason="audit")
        account = get_account(account["id"])
        assert account["adjusted_balance_cents"] == 1000000, (
            "the reversed write-off no longer reduces the balance"
        )
        # effective payments stay 0 (refund durable), so outstanding is the
        # floored difference: 1000000 - 0
        assert account["amount_outstanding_cents"] == 1000000
        assert_ledger_invariants(account)
