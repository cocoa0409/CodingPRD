"""Late-fee accrual, OPEN→OVERDUE auto-transitions, and dunning escalation
(PRD §3.5, §3.10).

Covers:
- Auto OPEN→OVERDUE on clock advance past due_date (PRD §3.5)
- Late fee accrual: principal * daily_rate * days_overdue (rounded half-up)
- Late fee cap: never exceeds principal * late_fee_cap_pct
- Dunning stages NONE → REMINDED → ESCALATED → LEGAL_NOTICE
- Owner.voting_status flips to INELIGIBLE_DELINQUENT on first OVERDUE bill
- Frozen variant on PAID: late_fee never moves after PAID (difficulty-design
  instance fee_late_charge_accrual_vs_frozen)
- Bill waiver from any non-terminal status (PRD §3.5)
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    create_payment_payload,
    fetch_bill,
    fetch_owner,
    iso_utc,
    list_audit_entries_for,
    pay_bill,
    setup_overdue_bill,
    setup_property_with_active_rule,
    issue_single_bill_for_property,
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


class TestOpenToOverdue:
    def test_clock_past_due_date_triggers_overdue(self, api):
        """PRD §3.5: "When the clock advances past due_date while the bill is still
        OPEN and paid_amount remains below total_due, the bill transitions
        OPEN → OVERDUE. That transition triggers the late-fee recompute described
        above, sets dunning_stage to REMINDED if it was previously NONE."

        Claim: clock-advance past due_date on an OPEN bill → status==OVERDUE,
        dunning_stage==REMINDED.
        """
        _owner, _prop, _rule, overdue = setup_overdue_bill(days_past_due=20)
        assert overdue["status"] == "OVERDUE"
        assert overdue["dunning_stage"] == "REMINDED"

    def test_overdue_recomputes_voting_status_to_delinquent(self, api):
        """PRD §3.5: "recomputes the relevant owner's voting_status — any owner with
        at least one fee bill in OVERDUE against any of their properties is set to
        INELIGIBLE_DELINQUENT."

        Claim: after a bill enters OVERDUE, the owner's voting_status is
        INELIGIBLE_DELINQUENT.
        """
        owner, _prop, _rule, _bill = setup_overdue_bill(days_past_due=5)
        refreshed_owner = fetch_owner(owner["id"])
        assert refreshed_owner["voting_status"] == "INELIGIBLE_DELINQUENT"


class TestLateFeeAccrual:
    """PRD §3.5 formula: late_fee_amount = min(round(principal*daily_rate*days_overdue, 2),
    round(principal*cap_pct, 2))."""

    def test_late_fee_at_5_days_matches_formula(self, api):
        """PRD §3.5: "The raw late charge is then the bill's principal_amount multiplied
        by the rule's late_fee_daily_rate multiplied by the days-overdue count, rounded
        half-up to two decimal places."

        Inputs: principal=200.00, daily_rate=0.0005, days_overdue=5 →
        round(200*0.0005*5, 2) = round(0.50, 2) = 0.50. Cap = 200*0.30 = 60.00,
        so min is 0.50. total_due = 200.00 + 0.50 = 200.50.

        Claim: late_fee_amount==0.50, total_due==200.50.
        """
        _owner, _prop, _rule, bill = setup_overdue_bill(
            area_sqm=80.00,
            rate=2.50,
            late_fee_daily_rate=0.0005,
            late_fee_cap_pct=0.30,
            days_past_due=5,
        )
        # PRD §3.5: read refreshes late_fee while non-terminal; this fetch returns the
        # current accrual.
        refreshed = fetch_bill(bill["id"])
        assert refreshed["late_fee_amount"] == pytest.approx(0.50, abs=0.001), (
            f"Expected late_fee=0.50 for 5d overdue; got {refreshed['late_fee_amount']}"
        )
        assert refreshed["total_due"] == pytest.approx(200.50, abs=0.001)

    def test_late_fee_capped_by_cap_pct(self, api):
        """PRD §3.5: "A cap is computed in parallel as the principal multiplied by the
        rule's late_fee_cap_pct ... The bill's late_fee_amount is the smaller of the
        raw charge and the cap."

        Inputs: principal=200.00, daily_rate=0.0005, cap_pct=0.10 (so cap=20.00),
        days_overdue=10000 → raw=1000.00 but capped at 20.00.

        Claim: late_fee_amount == 20.00 (the cap), even when raw greatly exceeds it.
        """
        # Use late_fee_cap_pct=0.10 to make cap obvious; days=400 to push raw past cap.
        _owner, _prop, _rule, bill = setup_overdue_bill(
            area_sqm=80.00,
            rate=2.50,
            late_fee_daily_rate=0.0005,
            late_fee_cap_pct=0.10,
            days_past_due=400,
        )
        refreshed = fetch_bill(bill["id"])
        assert refreshed["late_fee_amount"] == pytest.approx(20.00, abs=0.001), (
            f"Late fee must be capped at principal*cap_pct = 20.00; got {refreshed['late_fee_amount']}"
        )


class TestDunningEscalation:
    def test_dunning_advances_to_escalated_after_30_days(self, api):
        """PRD §3.5: "once the current time exceeds due_date plus thirty days and the
        current dunning_stage is REMINDED, the stage advances to ESCALATED."

        Claim: clock advance to due_date + 31d on a REMINDED OVERDUE bill →
        dunning_stage == ESCALATED.
        """
        _owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=5)
        assert bill["dunning_stage"] == "REMINDED"
        # Advance further to due_date + 31 days.
        due = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(due + timedelta(days=31)))
        refreshed = fetch_bill(bill["id"])
        assert refreshed["dunning_stage"] == "ESCALATED"

    def test_dunning_advances_to_legal_notice_after_60_days(self, api):
        """PRD §3.5: "once the current time exceeds due_date plus sixty days and the
        stage is ESCALATED, it advances to LEGAL_NOTICE."

        Claim: clock advance to due_date + 61d on an ESCALATED bill →
        dunning_stage == LEGAL_NOTICE.
        """
        _owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=5)
        due = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00"))
        # Walk through REMINDED → ESCALATED → LEGAL_NOTICE in sequence.
        advance_clock_to(iso_utc(due + timedelta(days=31)))
        advance_clock_to(iso_utc(due + timedelta(days=61)))
        refreshed = fetch_bill(bill["id"])
        assert refreshed["dunning_stage"] == "LEGAL_NOTICE"


class TestLateFeeFrozenAfterPayment:
    """Difficulty-design instance: fee_late_charge_accrual_vs_frozen.
    PRD §3.5: late fee never moves after PAID."""

    def test_late_fee_freezes_at_payment_and_does_not_grow(self, api):
        """PRD §3.5: "Once the bill is PAID or WAIVED the frozen variant of the
        formula applies and the read is a pure load."
        PRD §3.5: "The relevant evaluation instant is itself the smaller of the
        current time and the payment_freeze_at instant — the latter being the
        timestamp of the first reconciled payment that brings paid_amount up to
        or above total_due. Until that fully-reconciling payment lands, the
        days-overdue counter accrues against the present moment; once the bill
        reaches PAID or WAIVED, the counter is frozen at the freeze instant
        and the late fee never moves again."

        Setup: principal=200.00, daily_rate=0.0005, cap_pct=0.30, days_past_due=20.
        Late fee accrued = round(200*0.0005*20, 2) = 2.00, total_due = 202.00.
        Pay 202.00 → bill becomes PAID; late_fee frozen at 2.00.
        Advance clock another 30 days → the PAID bill's late_fee MUST still be 2.00.

        Claim: late_fee_amount stays at 2.00 after a 30-day post-payment clock advance.

        # difficulty: dual_variant_calc/fee_late_charge_accrual_vs_frozen
        """
        owner, prop, _rule, bill = setup_overdue_bill(
            area_sqm=80.00,
            rate=2.50,
            late_fee_daily_rate=0.0005,
            late_fee_cap_pct=0.30,
            days_past_due=20,
        )
        # Read once to see accrued late fee at 20d.
        refreshed = fetch_bill(bill["id"])
        assert refreshed["late_fee_amount"] == pytest.approx(2.00, abs=0.001), (
            f"Pre-payment expected late_fee=2.00 for 20d overdue; got {refreshed['late_fee_amount']}"
        )
        assert refreshed["total_due"] == pytest.approx(202.00, abs=0.001)
        # Pay total_due (=202.00) — PAID transition freezes late_fee at 2.00.
        pay_bill(bill, owner, amount=refreshed["total_due"])
        paid = fetch_bill(bill["id"])
        assert paid["status"] == "PAID"
        assert paid["late_fee_amount"] == pytest.approx(2.00, abs=0.001)
        # Advance the clock another 30 days. PAID is terminal — late_fee MUST not move.
        due = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(due + timedelta(days=50)))
        post = fetch_bill(bill["id"])
        assert post["status"] == "PAID"
        assert post["late_fee_amount"] == pytest.approx(2.00, abs=0.001), (
            f"Late fee must be frozen at 2.00 after PAID; got {post['late_fee_amount']}"
        )

    def test_unpaid_bill_late_fee_continues_to_accrue(self, api):
        """PRD §3.5: "Until that fully-reconciling payment lands, the days-overdue
        counter accrues against the present moment."

        Setup: same as the frozen case, but no payment is made. After the further
        30-day clock advance, late_fee MUST equal round(200*0.0005*50, 2) = 5.00,
        not the original 2.00 — proving the accrual_until_now variant.

        Claim: with no payment, late_fee grows from 2.00 (at 20d) to 5.00 (at 50d).

        # difficulty: dual_variant_calc/fee_late_charge_accrual_vs_frozen
        """
        _owner, _prop, _rule, bill = setup_overdue_bill(
            area_sqm=80.00,
            rate=2.50,
            late_fee_daily_rate=0.0005,
            late_fee_cap_pct=0.30,
            days_past_due=20,
        )
        first_read = fetch_bill(bill["id"])
        assert first_read["late_fee_amount"] == pytest.approx(2.00, abs=0.001)
        due = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00"))
        # Advance to 50 days past due_date.
        advance_clock_to(iso_utc(due + timedelta(days=50)))
        post = fetch_bill(bill["id"])
        assert post["status"] == "OVERDUE"
        assert post["late_fee_amount"] == pytest.approx(5.00, abs=0.001), (
            f"accrual_until_now: late_fee at 50d should be 5.00; got {post['late_fee_amount']}"
        )
        assert post["total_due"] == pytest.approx(205.00, abs=0.001)


class TestBillWaiver:
    def test_waive_overdue_bill_appends_audit_and_clears_delinquency(self, api, property_manager_headers):
        """PRD §3.5: "A manager waiver is also possible from any non-terminal status:
        it requires a reason in the body, advances status to WAIVED, appends an
        AuditEntry with action BILL_WAIVED, and recomputes the affected owner's
        voting_status (which may flip back to ELIGIBLE if no other bills are overdue)."

        Claim: waive on an OVERDUE bill → bill.status==WAIVED, audit entry with
        action=BILL_WAIVED appended, owner.voting_status flips to ELIGIBLE.
        """
        owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=10)
        res = api.waive_fee_bill(bill["id"], waive_fee_bill_payload(reason="hardship"), property_manager_headers)
        data = validate_success(res, 200)
        assert data["status"] == "WAIVED"
        # AuditEntry written.
        entries = list_audit_entries_for(subject_kind="FEE_BILL", subject_id=bill["id"])
        actions = [e.get("action") for e in entries]
        assert "BILL_WAIVED" in actions, f"Expected BILL_WAIVED audit; got {actions!r}"
        # Owner voting_status restored.
        refreshed_owner = fetch_owner(owner["id"])
        assert refreshed_owner["voting_status"] == "ELIGIBLE"

    def test_waive_requires_reason_in_body(self, api, property_manager_headers):
        """PRD §3.5: "A manager waiver is also possible from any non-terminal status:
        it requires a reason in the body."

        Claim: waive without a reason in the body is rejected (4xx).
        """
        _owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=10)
        # Send empty body — PRD does not name a specific error_id for missing reason.
        res = api.waive_fee_bill(bill["id"], {}, property_manager_headers)
        assert 400 <= res.status_code < 500, (
            f"waive without reason must be rejected; got HTTP {res.status_code}"
        )
