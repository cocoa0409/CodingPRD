"""Paying maintenance fees, surcharge math, and lapse cascade.

Covers PRD §3.5 in full.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    MAINTENANCE_FEE_TABLE_CENTS,
    MAINTENANCE_SURCHARGE_CENTS,
    advance_clock_to,
    get_application,
    get_maintenance_fee,
    list_audit_events,
    list_maintenance_fees,
    maintenance_fee_cents,
    make_applicant_headers,
    pay_fee,
    pay_maintenance_and_settle,
    setup_granted_utility_at_calendar_anchor,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Maintenance fee math (PRD §3.5)
# ===========================================================================
class TestMaintenanceFeeMath:

    @pytest.mark.parametrize(
        "stage,entity_size,expected_no_surcharge",
        [
            ("STAGE_3_5", "LARGE", 160000),
            ("STAGE_3_5", "SMALL", 80000),
            ("STAGE_3_5", "MICRO", 40000),
            ("STAGE_7_5", "LARGE", 360000),
            ("STAGE_7_5", "SMALL", 180000),
            ("STAGE_7_5", "MICRO", 90000),
            ("STAGE_11_5", "LARGE", 740000),
            ("STAGE_11_5", "SMALL", 370000),
            ("STAGE_11_5", "MICRO", 185000),
        ],
    )
    def test_maintenance_fee_no_surcharge_matrix(
        self, stage, entity_size, expected_no_surcharge,
    ):
        """PRD §3.5: "The base fee table is 160000 cents for STAGE_3_5,
        360000 cents for STAGE_7_5, and 740000 cents for STAGE_11_5"
        and PRD §2.7 multipliers 1.00/0.50/0.25.

        Claim: round-half-up(base * multiplier) yields the expected
        timely-window amount; the test_helpers.maintenance_fee_cents
        reference implements the PRD-pinned formula.
        """
        assert (
            maintenance_fee_cents(stage, entity_size, in_grace=False)
            == expected_no_surcharge
        )

    def test_micro_grace_surcharge_is_flat_not_multiplied(self):
        """PRD §3.5: "first multiply the base fee by the applicant's
        entity multiplier from §2.7 and round half-up to integer cents;
        then add the flat surcharge if the grace condition is met. The
        surcharge itself is not subject to the entity multiplier".

        Claim: MICRO STAGE_3_5 in grace = round(160000*0.25)+16000 =
        40000+16000 = 56000c. The wrong-order alternative (multiplier
        applied to base+surcharge) would give round((160000+16000)*0.25)
        = round(44000) = 44000c.
        """
        timely = maintenance_fee_cents("STAGE_3_5", "MICRO", in_grace=False)
        grace = maintenance_fee_cents("STAGE_3_5", "MICRO", in_grace=True)
        assert timely == 40000
        assert grace == 56000, (
            "PRD §3.5: MICRO grace must be 40000+16000=56000c (flat surcharge added AFTER rounding)"
        )

    def test_timely_payment_succeeds(self, api):
        """PRD §3.5: "When the payment lands in the timely portion (the
        clock is at or after window_open_at and at or before due_at),
        no surcharge applies."
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        # Move clock to the window_open_at boundary (inclusive).
        win = datetime.fromisoformat(s35["window_open_at"].replace("Z", "+00:00"))
        advance_clock_to(win)
        # Pay timely amount and settle.
        amount = maintenance_fee_cents("STAGE_3_5", "SMALL", in_grace=False)
        paid = pay_maintenance_and_settle(a, granted, s35, in_grace=False)
        assert paid["status"] == "PAID"

    def test_grace_payment_requires_surcharge(self, api):
        """PRD §3.5: "A flat surcharge of 16000 cents applies whenever
        the current clock is strictly after due_at and at or before
        grace_period_end_at — that is, when the payment lands in the
        late-but-still-curable grace portion of the window."

        Claim: paying timely amount (no surcharge) in the grace band is
        rejected; paying timely+16000 is accepted.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        due = datetime.fromisoformat(s35["due_at"].replace("Z", "+00:00"))
        # 30 days past due_at — within grace window.
        advance_clock_to(due + timedelta(days=30))
        timely = maintenance_fee_cents("STAGE_3_5", "SMALL", in_grace=False)
        # Wrong: paying without surcharge.
        bad = api.create_fee_transaction(
            granted["id"],
            {"fee_category": "MAINTENANCE", "amount_cents": timely,
             "maintenance_fee_id": s35["id"]},
            make_applicant_headers(a["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
        # Right: paying timely + surcharge.
        grace_amt = maintenance_fee_cents("STAGE_3_5", "SMALL", in_grace=True)
        assert grace_amt == timely + MAINTENANCE_SURCHARGE_CENTS
        good = api.create_fee_transaction(
            granted["id"],
            {"fee_category": "MAINTENANCE", "amount_cents": grace_amt,
             "maintenance_fee_id": s35["id"]},
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)


# ===========================================================================
# Maintenance window precondition (PRD §3.5)
# ===========================================================================
class TestMaintenanceWindow:

    def test_payment_before_window_rejected(self, api):
        """PRD §3.5: "the transition requires ... SystemClock.now is at
        or after window_open_at and at or before grace_period_end_at ...
        A payment that falls outside the maintenance window is rejected
        with ERR_MAINTENANCE_WINDOW_CLOSED."
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        win = datetime.fromisoformat(s35["window_open_at"].replace("Z", "+00:00"))
        # One second before window_open_at.
        advance_clock_to(win - timedelta(seconds=1))
        timely = maintenance_fee_cents("STAGE_3_5", "SMALL", in_grace=False)
        # Pay the FeeTransaction first (this may pass fee math), then
        # /pay should be rejected because window is closed.
        pay_fee(a, granted, "MAINTENANCE", timely, maintenance_fee_id=s35["id"])
        res = api.pay_maintenance_fee(s35["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_WINDOW_CLOSED.value)

    def test_payment_after_grace_rejected(self, api):
        """PRD §3.5: "SystemClock.now is at or before grace_period_end_at
        ... A payment that falls outside the maintenance window is
        rejected with ERR_MAINTENANCE_WINDOW_CLOSED."

        PRD §2.8 also says that when the clock advances past
        grace_period_end_at the sweep flips the MaintenanceFee row to
        LAPSED. Under §2.11 priority the state check (priority 6) runs
        before the temporal check (priority 11), so a post-sweep /pay
        may reasonably return ERR_INVALID_STATE instead of
        ERR_MAINTENANCE_WINDOW_CLOSED. Both readings are PRD-faithful;
        the test accepts either.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        grace = datetime.fromisoformat(
            s35["grace_period_end_at"].replace("Z", "+00:00"),
        )
        # 1 second past grace_period_end_at — sweep will lapse the row
        # synchronously per PRD §2.8.
        advance_clock_to(grace + timedelta(seconds=1))
        res = api.pay_maintenance_fee(s35["id"], make_applicant_headers(a["id"]))
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_MAINTENANCE_WINDOW_CLOSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# ===========================================================================
# Lapse cascade (PRD §3.5 + §2.8)
# ===========================================================================
class TestMaintenanceLapseCascade:

    def test_clock_past_grace_lapses_maintenance_and_expires_application(self, api):
        """PRD §3.5: "When the clock advances past a MaintenanceFee's
        grace_period_end_at while that row is still SCHEDULED and no
        qualifying MAINTENANCE-category fee transaction tied to it has
        been recorded, the deadline sweep in §2.8 deterministically
        flips the row's status to LAPSED and writes a
        MAINTENANCE_FEE_LAPSED audit row. A lapsed maintenance fee in
        turn drives the owning application to EXPIRED via the same
        sweep, which writes an APPLICATION_EXPIRED audit row."
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        grace = datetime.fromisoformat(
            s35["grace_period_end_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(grace + timedelta(seconds=1))
        # MaintenanceFee should now be LAPSED.
        s35_after = get_maintenance_fee(s35["id"])
        assert s35_after["status"] == "LAPSED", (
            "PRD §3.5: clock past grace_period_end_at must flip MaintenanceFee.status to LAPSED"
        )
        # Application should now be EXPIRED.
        app_after = get_application(granted["id"])
        assert app_after["status"] == "EXPIRED", (
            "PRD §3.5: lapsed maintenance must drive the owning application to EXPIRED"
        )
        # Audit chain contains both events.
        events = list_audit_events(granted["id"])
        actions = [e["action"] for e in events]
        assert "MAINTENANCE_FEE_LAPSED" in actions, (
            "PRD §3.5: audit must include MAINTENANCE_FEE_LAPSED"
        )
        assert "APPLICATION_EXPIRED" in actions, (
            "PRD §3.5: audit must include APPLICATION_EXPIRED"
        )
