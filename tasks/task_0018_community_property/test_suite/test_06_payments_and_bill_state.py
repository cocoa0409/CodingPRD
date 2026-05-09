"""Payments and the FeeBill state machine driven by reconciliation
(PRD §3.5, §3.6).

Covers:
- POST /payments core: status, amount validation → ERR_PAYMENT_AMOUNT_INVALID
- Idempotency on (channel, external_txn_id) → ERR_DUPLICATE_PAYMENT (difficulty-design
  instance business_constraint_vs_business_fiscal_on_payment).
- OPEN → PARTIALLY_PAID transition when 0<paid_amount<total_due and now()<=due_date.
- OPEN → PAID transition.
- OVERDUE → PARTIALLY_PAID and OVERDUE → PAID transitions.
- The four FeeBill branching paths from OPEN: PARTIALLY_PAID, PAID, WAIVED, OVERDUE
  (difficulty-design instance fee_bill_branching_payment_paths).
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_payment_record,
    create_payment_payload,
    fetch_bill,
    issue_single_bill_for_property,
    iso_utc,
    pay_bill,
    pay_bill_as_manager,
    setup_overdue_bill,
    setup_property_with_active_rule,
    setup_three_open_bills,
    TEST_USERS,
    validate_error,
    validate_success,
    waive_fee_bill_payload,
)


def _last_calendar_period():
    today = datetime.now(timezone.utc).date()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


class TestPaymentBasics:
    def test_successful_payment_creates_record(self, api):
        """PRD §3.6: "Payments arrive via the payment endpoint and persist as
        PaymentRecord rows ... New records start with reconciliation_status of
        PENDING and advance to RECONCILED once they have been credited to the bill."

        Claim: POST /payments returns a PaymentRecord whose reconciliation_status
        is PENDING or RECONCILED (PRD names both as legitimate states; the moment
        it reaches RECONCILED is implementation-internal).
        """
        owner, prop, _rule = setup_property_with_active_rule(area_sqm=80.00, rate=2.50)
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        # Pay full amount via owner.
        from test_helpers import make_owner_headers
        headers = make_owner_headers(owner["id"])
        payload = create_payment_payload(bill_id=bill["id"], amount=bill["total_due"])
        res = api.create_payment(payload, headers)
        data = validate_success(res, 201)
        assert_payment_record(data)
        assert data["reconciliation_status"] in ("PENDING", "RECONCILED")

    def test_zero_amount_rejected(self, api):
        """PRD §3.6: "The amount must be strictly greater than zero ... payments
        outside that range are rejected with ERR_PAYMENT_AMOUNT_INVALID."

        Claim: amount=0 → ERR_PAYMENT_AMOUNT_INVALID.
        """
        owner, prop, _rule = setup_property_with_active_rule()
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        from test_helpers import make_owner_headers
        headers = make_owner_headers(owner["id"])
        payload = create_payment_payload(bill_id=bill["id"], amount=0)
        res = api.create_payment(payload, headers)
        validate_error(res, "ERR_PAYMENT_AMOUNT_INVALID")

    def test_payment_exceeding_10x_total_due_rejected(self, api):
        """PRD §3.6: "no greater than ten times the bill's current total_due as a
        sanity bound; payments outside that range are rejected with
        ERR_PAYMENT_AMOUNT_INVALID."

        Claim: amount > 10 * total_due → ERR_PAYMENT_AMOUNT_INVALID.
        """
        owner, prop, _rule = setup_property_with_active_rule()
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        from test_helpers import make_owner_headers
        headers = make_owner_headers(owner["id"])
        too_big = bill["total_due"] * 11
        payload = create_payment_payload(bill_id=bill["id"], amount=too_big)
        res = api.create_payment(payload, headers)
        validate_error(res, "ERR_PAYMENT_AMOUNT_INVALID")


class TestPaymentIdempotency:
    """PRD §3.6: "The (channel, external_txn_id) pair is the idempotency key —
    two payments bearing the same pair are rejected with ERR_DUPLICATE_PAYMENT." """

    def test_duplicate_channel_external_txn_id_rejected(self, api):
        """PRD §3.6: "The (channel, external_txn_id) pair is the idempotency key —
        two payments bearing the same pair are rejected with ERR_DUPLICATE_PAYMENT."

        Claim: a second POST /payments with the same (channel, external_txn_id) →
        ERR_DUPLICATE_PAYMENT.
        """
        owner, prop, _rule = setup_property_with_active_rule()
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        from test_helpers import make_owner_headers
        headers = make_owner_headers(owner["id"])
        payload1 = create_payment_payload(
            bill_id=bill["id"],
            amount=10.00,
            channel="WECHAT",
            external_txn_id="DUP-TXN-X1",
        )
        validate_success(api.create_payment(payload1, headers), 201)
        # Same channel + external_txn_id, even with a different amount.
        payload2 = create_payment_payload(
            bill_id=bill["id"],
            amount=10.00,
            channel="WECHAT",
            external_txn_id="DUP-TXN-X1",
        )
        res = api.create_payment(payload2, headers)
        validate_error(res, "ERR_DUPLICATE_PAYMENT")


class TestDuplicatePaymentTakesPrecedenceOverInvalidAmount:
    """Difficulty-design instance: business_constraint_vs_business_fiscal_on_payment.
    PRD §2.6: business_constraint (priority 16) precedes business_fiscal (priority 17).
    PRD §3.6 names both errors. When the same payload is BOTH a duplicate AND has an
    invalid amount, ERR_DUPLICATE_PAYMENT must fire first."""

    def test_duplicate_payment_wins_over_zero_amount(self, api):
        """PRD §2.6: "after state checks, business-referential rules ... are
        evaluated, then business-temporal rules ... then business-safety ... and
        business-constraint rules (parking quota, parking kind, parking space taken,
        payment uniqueness, rule-code uniqueness, property uniqueness), and finally
        business-fiscal rules (payment amount sanity, satisfaction-score range).
        Within the same category the lower-priority-number rule fires first."

        PRD §3.6: "two payments bearing the same pair are rejected with
        ERR_DUPLICATE_PAYMENT."
        PRD §3.6: "The amount must be strictly greater than zero ... payments
        outside that range are rejected with ERR_PAYMENT_AMOUNT_INVALID."

        Claim: a payment whose (channel, external_txn_id) duplicates a prior
        successful payment AND whose amount is zero is rejected with
        ERR_DUPLICATE_PAYMENT (the business_constraint check), NOT
        ERR_PAYMENT_AMOUNT_INVALID (the business_fiscal check).

        # difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_payment
        """
        owner, prop, _rule = setup_property_with_active_rule()
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        from test_helpers import make_owner_headers
        headers = make_owner_headers(owner["id"])
        first = create_payment_payload(
            bill_id=bill["id"], amount=bill["total_due"], channel="WECHAT",
            external_txn_id="PAIR-CONFLICT-TXN",
        )
        validate_success(api.create_payment(first, headers), 201)
        conflict = create_payment_payload(
            bill_id=bill["id"], amount=0, channel="WECHAT",
            external_txn_id="PAIR-CONFLICT-TXN",
        )
        res = api.create_payment(conflict, headers)
        validate_error(res, "ERR_DUPLICATE_PAYMENT")

    def test_invalid_amount_alone_returns_amount_invalid(self, api):
        """PRD §3.6: "payments outside that range are rejected with
        ERR_PAYMENT_AMOUNT_INVALID."

        Claim: a payment with a unique (channel, external_txn_id) but invalid
        amount=0 returns ERR_PAYMENT_AMOUNT_INVALID — proving that the priority
        conflict in the previous test was genuine.

        # difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_payment
        """
        owner, prop, _rule = setup_property_with_active_rule()
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        from test_helpers import make_owner_headers
        headers = make_owner_headers(owner["id"])
        only_invalid = create_payment_payload(
            bill_id=bill["id"], amount=0, channel="WECHAT",
            external_txn_id="UNIQUE-ZERO-TXN-Z",
        )
        res = api.create_payment(only_invalid, headers)
        validate_error(res, "ERR_PAYMENT_AMOUNT_INVALID")


class TestBillStateTransitionsByPayment:
    def test_open_to_partially_paid_on_small_payment(self, api):
        """PRD §3.6: "While the bill is in OPEN and the cumulative paid_amount is
        strictly between zero and total_due, the bill transitions
        OPEN → PARTIALLY_PAID (only if now() is at or before due_date — partial
        payments arriving after the due date are recognized but the bill remains
        OVERDUE)."

        Claim: small payment well before due_date on OPEN bill → status=PARTIALLY_PAID.
        """
        owner, prop, _rule = setup_property_with_active_rule(area_sqm=80.00, rate=2.50)
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        # Pay 50 out of 200.
        pay_bill(bill, owner, amount=50.00)
        refreshed = fetch_bill(bill["id"])
        assert refreshed["status"] == "PARTIALLY_PAID"
        assert refreshed["paid_amount"] == pytest.approx(50.00, abs=0.001)

    def test_open_to_paid_on_full_payment(self, api):
        """PRD §3.6: "Once paid_amount is at or above total_due, the bill advances
        to PAID from whichever non-terminal state it currently occupies — OPEN → PAID."

        Claim: full payment on OPEN bill → status=PAID.
        """
        owner, prop, _rule = setup_property_with_active_rule()
        py, pm = _last_calendar_period()
        bill = issue_single_bill_for_property(prop, py, pm, rule_id=_rule["id"])
        pay_bill(bill, owner, amount=bill["total_due"])
        refreshed = fetch_bill(bill["id"])
        assert refreshed["status"] == "PAID"

    def test_overdue_to_paid_clears_dunning_and_voting_status(self, api):
        """PRD §3.6: "The PAID transition freezes late_fee_amount at its current
        value, resets dunning_stage to NONE, and recomputes the relevant owner's
        voting_status (which may flip back to ELIGIBLE if no other bills are overdue)."

        Claim: paying an OVERDUE bill in full → status=PAID, dunning_stage=NONE,
        owner.voting_status=ELIGIBLE.
        """
        owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=10)
        from test_helpers import fetch_owner
        # Read once to refresh total_due (it includes accrued late fee).
        refreshed_open = fetch_bill(bill["id"])
        pay_bill(bill, owner, amount=refreshed_open["total_due"])
        refreshed = fetch_bill(bill["id"])
        assert refreshed["status"] == "PAID"
        assert refreshed["dunning_stage"] == "NONE"
        owner_after = fetch_owner(owner["id"])
        assert owner_after["voting_status"] == "ELIGIBLE"


class TestBillBranchingFork:
    """Difficulty-design instance: fee_bill_branching_payment_paths.
    PRD §3.5/§3.6: from OPEN, four divergent next-states — PARTIALLY_PAID (small
    payment), PAID (full payment), WAIVED (manager action), OVERDUE (clock advance)."""

    def test_three_open_bills_take_three_different_paths(self, api, property_manager_headers):
        """PRD §3.6: "While the bill is in OPEN and the cumulative paid_amount is
        strictly between zero and total_due, the bill transitions OPEN → PARTIALLY_PAID."
        PRD §3.6: "Once paid_amount is at or above total_due, the bill advances to PAID."
        PRD §3.5: "A manager waiver is also possible from any non-terminal status:
        it requires a reason in the body, advances status to WAIVED."

        Claim: three OPEN bills processed via three different actions land in
        three different states — PARTIALLY_PAID, PAID, WAIVED.

        # difficulty: non_linear_state_machine/fee_bill_branching_payment_paths
        """
        owner, _props, _rule, bills = setup_three_open_bills(rate=2.50)
        # All three start OPEN — sanity.
        for b in bills:
            assert b["status"] == "OPEN", f"Setup expected OPEN, got {b['status']}"
        b1, b2, b3 = bills
        # Path A: small payment → PARTIALLY_PAID.
        pay_bill_as_manager(b1, amount=50.00, channel="WECHAT", external_txn_id="BR-PARTIAL")
        # Path B: full payment → PAID.
        pay_bill_as_manager(b2, amount=b2["total_due"], channel="ALIPAY", external_txn_id="BR-PAID")
        # Path C: waive → WAIVED.
        validate_success(
            api.waive_fee_bill(b3["id"], waive_fee_bill_payload(reason="goodwill"), property_manager_headers),
            200,
        )
        a = fetch_bill(b1["id"])
        b = fetch_bill(b2["id"])
        c = fetch_bill(b3["id"])
        assert a["status"] == "PARTIALLY_PAID"
        assert b["status"] == "PAID"
        assert c["status"] == "WAIVED"

    def test_open_to_overdue_branch(self, api):
        """PRD §3.5: "When the clock advances past due_date while the bill is still
        OPEN and paid_amount remains below total_due, the bill transitions
        OPEN → OVERDUE."

        Claim: a fourth OPEN bill, untouched and clock-advanced past due_date, lands
        in OVERDUE. This completes the four branches OPEN → {PARTIALLY_PAID, PAID,
        WAIVED, OVERDUE}.

        # difficulty: non_linear_state_machine/fee_bill_branching_payment_paths
        """
        _owner, _prop, _rule, overdue = setup_overdue_bill(days_past_due=20)
        assert overdue["status"] == "OVERDUE"
        assert overdue["dunning_stage"] == "REMINDED"
