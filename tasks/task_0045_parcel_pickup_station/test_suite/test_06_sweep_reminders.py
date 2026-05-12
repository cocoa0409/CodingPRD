"""Reminder cadence and the overtime + long-stay sweep.

PRD §3.5 (Reminder Cadence and the Sweep), §2.9 (Idempotency and
Sweep Safety).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    advance_clock_hours,
    drive_parcel_to_awaiting_return,
    drive_parcel_to_overtime,
    ESCALATION_HOURS,
    find_audit_entries,
    find_reminders,
    is_iso8601_timestamp,
    LONG_STAY_HOURS,
    list_all_reminders,
    list_audit_events,
    register_shelved_parcel,
    run_sweep,
    setup_station_with_staff,
    TEST_USERS,
    validate_success,
)


class TestOvertimeSweep:
    def test_sweep_advances_shelved_to_overtime_past_deadline(self, api):
        """PRD §3.5: "for each parcel still in SHELVED where the
        current server time is at or after its free_storage_deadline
        and no T2_FOLLOWUP reminder has yet been recorded for that
        parcel, a reminder is emitted at tier T2_FOLLOWUP over SMS with
        triggered_by OVERTIME_SWEEP; the parcel is advanced from
        SHELVED to OVERTIME."

        Claim: after advancing the clock past the deadline and calling
        /_sweep/run, the parcel is OVERTIME and a T2_FOLLOWUP-over-SMS
        reminder triggered_by OVERTIME_SWEEP exists.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_overtime(ctx, parcel)
        assert parcel["status"] == "OVERTIME"
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t2 = find_reminders(reminders, tier="T2_FOLLOWUP")
        assert len(t2) == 1
        assert t2[0]["channel"] == "SMS"
        assert t2[0]["triggered_by"] == "OVERTIME_SWEEP"

    def test_overtime_flagged_audit_event_appended(self, api):
        """PRD §3.5: "Each SHELVED → OVERTIME transition appends an AuditEvent of action OVERTIME_FLAGGED; each OVERTIME → AWAITING_RETURN transition appends LONG_STAY_FLAGGED."

        Claim: GET /audit-events filtered to the parcel shows one
        action=OVERTIME_FLAGGED row.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        drive_parcel_to_overtime(ctx, parcel)
        rows = list_audit_events(
            TEST_USERS["platform_admin_headers"],
            subject_kind="Parcel", subject_id=parcel["id"],
        )
        match = find_audit_entries(rows, action="OVERTIME_FLAGGED")
        assert len(match) == 1


class TestEscalationSweep:
    def test_sweep_emits_t3_escalation_over_im(self, api):
        """PRD §3.5: "for each parcel currently in OVERTIME where the
        current server time is at or after free_storage_deadline plus
        24 hours and no T3_ESCALATION reminder has yet been recorded
        for that parcel, a reminder is emitted at tier T3_ESCALATION
        over IM with triggered_by OVERTIME_SWEEP."

        Claim: after advancing the clock to deadline + 24h, the next
        sweep emits exactly one T3_ESCALATION reminder over IM
        triggered_by OVERTIME_SWEEP.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_overtime(ctx, parcel)
        # Now advance an additional ESCALATION_HOURS (24h).
        advance_clock_hours(ESCALATION_HOURS)
        run_sweep()
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t3 = find_reminders(reminders, tier="T3_ESCALATION")
        assert len(t3) == 1
        assert t3[0]["channel"] == "IM"
        assert t3[0]["triggered_by"] == "OVERTIME_SWEEP"


class TestLongStaySweep:
    def test_sweep_advances_overtime_to_awaiting_return(self, api):
        """PRD §3.5: "for each parcel currently in OVERTIME where the
        current server time is at or after shelved_at plus 168 hours,
        the parcel is advanced from OVERTIME to AWAITING_RETURN,
        long_stay_flagged_at is stamped to the current time, and a
        reminder is emitted at tier T4_RETURN_CONFIRM over IM with
        triggered_by LONG_STAY_SWEEP."

        Claim: after crossing shelved_at + 168h, sweep emits one
        T4_RETURN_CONFIRM over IM with triggered_by LONG_STAY_SWEEP and
        the parcel reaches AWAITING_RETURN with a stamped
        long_stay_flagged_at.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        assert parcel["status"] == "AWAITING_RETURN"
        assert is_iso8601_timestamp(parcel["long_stay_flagged_at"])
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t4 = find_reminders(reminders, tier="T4_RETURN_CONFIRM")
        assert len(t4) == 1
        assert t4[0]["channel"] == "IM"
        assert t4[0]["triggered_by"] == "LONG_STAY_SWEEP"


class TestSweepIdempotency:
    def test_two_back_to_back_sweeps_do_not_duplicate_reminder(self, api):
        """PRD §3.5: "The sweep is idempotent: it never emits a
        duplicate ReminderRecord for the same tier on the same parcel,
        so multiple back-to-back sweep calls are safe."

        Claim: after one OVERTIME_SWEEP that emitted T2_FOLLOWUP, a
        second sweep does NOT emit another T2_FOLLOWUP for the same
        parcel.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        drive_parcel_to_overtime(ctx, parcel)
        run_sweep()  # second invocation
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t2 = find_reminders(reminders, tier="T2_FOLLOWUP")
        assert len(t2) == 1

    def test_sweep_with_no_qualifying_parcels_is_no_op(self, api):
        """PRD §3.5: "a sweep where no parcel qualifies returns at HTTP
        200 with an empty emission list."

        Claim: /_sweep/run called on a station with only a SHELVED
        parcel still inside its free storage window returns HTTP 200
        with an empty reminders list.
        """
        ctx = setup_station_with_staff()
        register_shelved_parcel(ctx)
        # No clock advance -> still well inside the free window.
        resp = api.run_sweep(TEST_USERS["platform_admin_headers"])
        data = validate_success(resp, expected_status=200)
        # The PRD doesn't pin the exact response key shape so we accept
        # any of these reasonable representations of "no emissions."
        emitted = (
            data.get("reminders_emitted")
            or data.get("emissions")
            or data.get("emitted")
            or []
        )
        # An empty list (or 0 count) satisfies the no-op claim.
        if isinstance(emitted, list):
            assert emitted == []
        else:
            assert emitted == 0 or emitted is None
