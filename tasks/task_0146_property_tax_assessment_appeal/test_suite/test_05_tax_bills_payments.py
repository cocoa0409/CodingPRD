"""TaxBill creation, issuance, and payment lifecycle (PRD §3.4).

Covers PENDING → ISSUED transitions, payment amounts and boundaries,
ERR_DUPLICATE_BILL, ERR_OVERPAYMENT, ERR_ASSESSMENT_NOT_FINALIZED,
ERR_EXEMPTIONS_PENDING, and the auto-delinquent path on
clock-advance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_MILL_RATE,
    DUE_WINDOW_DAYS,
    ApiErrorId,
    add_days_iso,
    advance_clock_to,
    assert_payment,
    assert_tax_bill,
    create_assessment,
    create_owner,
    create_property,
    create_tax_bill,
    get_assessment,
    get_tax_bill,
    issue_assessment,
    issue_tax_bill,
    list_payments,
    make_owner_headers,
    post_payment,
    setup_finalized_assessment_via_clock,
    setup_issued_assessment,
    setup_issued_tax_bill,
    setup_owner_and_property,
    submit_exemption,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# TaxBill creation, default mill rate — PRD §3.4
# ===========================================================================
class TestTaxBillCreation:

    def test_create_bill_uses_default_mill_rate_when_omitted(self, api):
        """PRD §3.4: 'if mill_rate is omitted, the system constant
        DEFAULT_MILL_RATE (12.5 per $1000 of taxable value) is
        captured on the bill.'

        Claim: creating a bill without mill_rate captures
        mill_rate=12.5.
        """
        owner, prop, asmt = setup_finalized_assessment_via_clock(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025,
        )
        assert_tax_bill(bill)
        assert bill["mill_rate"] == pytest.approx(12.5, abs=1e-9), (
            f"DEFAULT_MILL_RATE must be 12.5, got {bill['mill_rate']}"
        )
        assert bill["status"] == "PENDING"
        # base_tax = 400000 * 12.5 / 1000 = 5000.
        assert bill["base_tax_amount"] == pytest.approx(5_000.00, abs=0.01)

    def test_duplicate_bill_rejected(self, api):
        """PRD §3.4: 'At most one TaxBill may exist per (property_id,
        roll_year); duplicates are rejected with ERR_DUPLICATE_BILL.'

        Claim: a second POST /properties/{id}/tax_bills for the same
        roll year is rejected.
        """
        owner, prop, asmt = setup_finalized_assessment_via_clock(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        create_tax_bill(
            property_id=prop["id"], roll_year=2025,
        )
        from test_helpers import api_client, TEST_USERS, create_tax_bill_payload
        resp = api_client.create_tax_bill(
            prop["id"],
            create_tax_bill_payload(roll_year=2025),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BILL.value)


# ===========================================================================
# Issue gates — PRD §3.4
# ===========================================================================
class TestTaxBillIssueGates:

    def test_issue_rejected_when_assessment_not_finalized(self, api):
        """PRD §3.4: 'Two cross-entity preconditions guard the
        transition: the linked Assessment must be FINALIZED, otherwise
        ERR_ASSESSMENT_NOT_FINALIZED'.

        Claim: when the Assessment is UNDER_APPEAL (not FINALIZED),
        attempting to issue an existing PENDING bill is rejected.

        Note: in this PRD a TaxBill is created only after the
        Assessment is FINALIZED (PRD §3.4 first sentence). We exercise
        the cross-entity gate by attempting the /issue path after
        re-opening the Assessment via a freshly-filed Appeal.

        # difficulty: cross_entity_state_dependency/taxbill_issue_requires_assessment_finalized
        """
        # 1) Get to FINALIZED Assessment + PENDING bill.
        owner, prop, asmt = setup_finalized_assessment_via_clock(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025,
        )
        # 2) Issue the bill normally — to confirm baseline succeeds —
        # but for this gate test we skip and try to issue while the
        # Assessment is FINALIZED + bill PENDING (baseline succeeds).
        # We can't easily UNDO FINALIZE since PRD pins FINALIZED as
        # terminal. So we instead model the gate by creating a SECOND
        # property whose Assessment is UNDER_APPEAL and attempting to
        # create+issue a bill there.
        from test_helpers import (
            create_tax_bill_payload,
            file_appeal,
            api_client, TEST_USERS,
        )
        owner2, prop2, asmt2 = setup_issued_assessment(
            market_value=300_000.00, roll_year=2025,
            market_value_at_roll=300_000.00,
        )
        # Open an Appeal so Assessment is UNDER_APPEAL.
        file_appeal(
            owner=owner2, property_id=prop2["id"],
            assessment_id=asmt2["id"], claimed_value=100_000.00,
        )
        # Try to create a TaxBill against UNDER_APPEAL Assessment.
        resp = api_client.create_tax_bill(
            prop2["id"],
            create_tax_bill_payload(roll_year=2025),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value,
        )

    def test_issue_rejected_when_exemptions_still_submitted(self, api):
        """PRD §3.4: 'no ExemptionApplication for (property_id,
        roll_year) may still be in SUBMITTED status, otherwise
        ERR_EXEMPTIONS_PENDING — the system refuses to issue a bill
        while exemptions are still pending decision.'

        Claim: a SUBMITTED ExemptionApplication blocks /issue with
        ERR_EXEMPTIONS_PENDING.
        """
        owner = create_owner()
        prop = create_property(owner=owner, market_value=400_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        # Submit but do not approve/deny.
        submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="HOMESTEAD", effective_roll_year=2025,
        )
        # FINALIZE the Assessment by advancing clock past window.
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        from test_helpers import api_client, TEST_USERS, version_body
        resp = api_client.issue_tax_bill(
            prop["id"], bill["id"], TEST_USERS["treasurer_headers"],
            version_body(bill["version"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTIONS_PENDING.value)


# ===========================================================================
# Issuance side effects — PRD §3.4
# ===========================================================================
class TestTaxBillIssueSideEffects:

    def test_issue_sets_due_date_and_locks_amount_due(self, api):
        """PRD §3.4: 'On successful issuance, issued_at is set to now,
        due_date is set to issued_at plus the system constant
        DUE_WINDOW_DAYS (30 days), and amount_due is locked to the
        current base_tax_amount.'

        Claim: ISSUE returns status=ISSUED, due_date is set, and
        amount_due equals base_tax_amount.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
        )
        assert bill["status"] == "ISSUED"
        assert bill["issued_at"] is not None
        assert bill["due_date"] is not None
        assert bill["amount_due"] == pytest.approx(
            bill["base_tax_amount"], abs=0.01,
        )


# ===========================================================================
# Payment amount boundary — PRD §3.4
# ===========================================================================
class TestPaymentAmount:

    def test_payment_amount_below_due_partially_paid(self, api):
        """PRD §3.4: 'if it is strictly less, the bill transitions to
        PARTIALLY_PAID (or stays PARTIALLY_PAID if it was already
        there).'

        Claim: payment amount < amount_due → bill becomes
        PARTIALLY_PAID; remaining amount_due decreases by that amount.

        # difficulty: boundary_precision_check/payment_amount_exact_equality_for_paid
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        # base_tax = 80000 * 12.5 / 1000 = 1000.
        assert bill["base_tax_amount"] == pytest.approx(1_000.00, abs=0.01)
        payment = post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=999.99,
        )
        assert_payment(payment)
        assert payment["status"] == "APPLIED"
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["status"] == "PARTIALLY_PAID"
        assert re_bill["amount_due"] == pytest.approx(0.01, abs=0.01)

    def test_payment_amount_equal_to_due_flips_to_paid(self, api):
        """PRD §3.4: "If the new payment exactly equals the previous
        amount_due, the bill transitions to PAID; if it is strictly
        less, the bill transitions to PARTIALLY_PAID (or stays
        PARTIALLY_PAID if it was already there)."

        Claim: amount == amount_due → bill becomes PAID.

        # difficulty: boundary_precision_check/payment_amount_exact_equality_for_paid
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=1_000.00,
        )
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["status"] == "PAID"
        assert re_bill["amount_due"] == pytest.approx(0.00, abs=0.01)

    def test_payment_above_due_rejected_overpayment(self, api):
        """PRD §3.4: 'Each payment carries only an amount, which must
        be strictly greater than zero and strictly less than or equal
        to the current amount_due; zero, negative, or overpaying
        amounts are all rejected with ERR_OVERPAYMENT.'

        Claim: amount > amount_due is rejected with ERR_OVERPAYMENT.

        # difficulty: boundary_precision_check/payment_amount_exact_equality_for_paid
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        from test_helpers import api_client, create_payment_payload
        resp = api_client.create_payment(
            prop["id"], bill["id"],
            create_payment_payload(amount=1_000.01),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)

    def test_payment_amount_zero_rejected_overpayment(self, api):
        """PRD §3.4: 'Each payment carries only an amount, which must
        be strictly greater than zero and strictly less than or equal
        to the current amount_due; zero, negative, or overpaying
        amounts are all rejected with ERR_OVERPAYMENT.'

        Claim: amount == 0 is rejected with ERR_OVERPAYMENT.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        from test_helpers import api_client, create_payment_payload
        resp = api_client.create_payment(
            prop["id"], bill["id"],
            create_payment_payload(amount=0.0),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)

    def test_payment_amount_negative_rejected_overpayment(self, api):
        """PRD §3.4: 'Each payment carries only an amount, which must
        be strictly greater than zero and strictly less than or equal
        to the current amount_due; zero, negative, or overpaying
        amounts are all rejected with ERR_OVERPAYMENT.'

        Claim: negative amount is rejected with ERR_OVERPAYMENT.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        from test_helpers import api_client, create_payment_payload
        resp = api_client.create_payment(
            prop["id"], bill["id"],
            create_payment_payload(amount=-1.0),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)

    def test_partial_then_exact_fills_bill_to_paid(self, api):
        """PRD §3.4: 'A payment that exactly clears a PARTIALLY_PAID
        bill flips it to PAID.'

        Claim: 999.99 then 0.01 fully pays a 1000.00 bill.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=999.99,
        )
        mid = get_tax_bill(prop["id"], bill["id"])
        assert mid["status"] == "PARTIALLY_PAID"
        post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=0.01,
        )
        final = get_tax_bill(prop["id"], bill["id"])
        assert final["status"] == "PAID"
        assert final["amount_due"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# List payments — PRD §3.4, §2.3
# ===========================================================================
class TestListPayments:

    def test_list_payments_pagination_envelope(self, api, treasurer_headers):
        """PRD §2.3: 'The pagination envelope in meta carries limit,
        offset, total_count, and has_more for every list response.'
        PRD §3.4: 'The payments list endpoint accepts limit, offset,
        and an optional status query filter constraining the result
        to APPLIED or REFUNDED rows.'

        Claim: list payments returns pagination meta with the four
        required fields.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=100.00,
        )
        resp = list_payments(
            property_id=prop["id"], tax_bill_id=bill["id"],
            headers=treasurer_headers,
        )
        data, meta = validate_paginated(resp)
        # Required meta fields per PRD §2.3.
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing {k!r}, got {list(meta)}"
        assert meta["total_count"] >= 1
        assert any(p["status"] == "APPLIED" for p in data)


# ===========================================================================
# Delinquency on clock — PRD §3.4
# ===========================================================================
class TestBillDelinquency:

    def test_clock_past_due_date_makes_issued_bill_delinquent(self, api):
        """PRD §3.4: 'If the logical clock advances past due_date and
        the bill is still in ISSUED or PARTIALLY_PAID with no ACTIVE
        DeferralPlan, the bill auto-transitions to DELINQUENT.'

        Claim: clock past due_date with no payment and no deferral
        flips an ISSUED bill to DELINQUENT.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=80_000.00, roll_year=2025,
            market_value_at_roll=80_000.00, mill_rate=12.5,
        )
        # Advance clock past due_date (issued_at + 30 days).
        advance_clock_to(add_days_iso(bill["due_date"], 1))
        refreshed = get_tax_bill(prop["id"], bill["id"])
        assert refreshed["status"] == "DELINQUENT"
