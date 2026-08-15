"""Custodian acknowledgment SLA variants, reminder sweeps, and the notice trail."""
from test_helpers import (
    TEST_USERS,
    acknowledge_assignment,
    read_hold_version,
    release_hold,
    run_reminder_sweep,
    set_clock,
    setup_issued_hold,
    validate_paginated,
    validate_success,
)

RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]
AUD = TEST_USERS["auditor_headers"]

_ACK_SLA_PROGRAM = {
    "ack_deadline_days": 14,
    "reminder_interval_days": 7,
    "max_reminders_before_escalation": 3,
}


class TestAckSlaVariants:
    def test_strict_mode_ack_after_due_is_late(self, api):
        """PRD §3.6: "Under `STRICT`, the acknowledgment is late exactly when
        `acknowledged_at` is strictly after the original `ack_due_date` — an
        acknowledgment exactly at the deadline is on time."
        PRD §3.6: "When `was_late` is true, the hold's `late_ack_count` is
        incremented by 1."

        Design: Difficulty/dual_variant_calc/ack_sla_strict_vs_reminder_adjusted
        """
        scen = setup_issued_hold(
            program_overrides={**_ACK_SLA_PROGRAM, "ack_sla_mode": "STRICT"},
            matter_ref="M-A")
        hold = scen["hold"]
        assignment = scen["assignments"][0]
        custodian = scen["custodians"][0]
        # Issued at the default clock 2026-08-01 -> ack_due 2026-08-15.
        assert assignment["ack_due_date"] is not None

        set_clock("2026-08-16T00:00:00Z")
        sweep = run_reminder_sweep(scen["ctx"]["program"]["id"])
        assert sweep["reminders_sent"] == 1, "one past-due assignment reminded"
        assert sweep["escalations_raised"] == 0

        set_clock("2026-08-21T00:00:00Z")
        acked = acknowledge_assignment(assignment["id"], custodian["id"])
        assert acked["was_late"] is True, "STRICT: 2026-08-21 > 2026-08-15"
        hold_after = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert hold_after["late_ack_count"] == 1

    def test_reminder_adjusted_mode_extends_deadline(self, api):
        """PRD §3.6: "Under `REMINDER_ADJUSTED`, the effective deadline is the
        original `ack_due_date` plus one `reminder_interval_days` per reminder
        already sent on the assignment (the `reminder_count` at the moment of
        acknowledgment), and the acknowledgment is late exactly when
        `acknowledged_at` is strictly after that effective deadline; identical
        timestamps can therefore flip `was_late` between the two variants."

        Design: Difficulty/dual_variant_calc/ack_sla_strict_vs_reminder_adjusted
        """
        scen = setup_issued_hold(
            program_overrides={**_ACK_SLA_PROGRAM,
                               "ack_sla_mode": "REMINDER_ADJUSTED"},
            matter_ref="M-B")
        hold = scen["hold"]
        assignment = scen["assignments"][0]
        custodian = scen["custodians"][0]

        set_clock("2026-08-16T00:00:00Z")
        sweep = run_reminder_sweep(scen["ctx"]["program"]["id"])
        assert sweep["reminders_sent"] == 1

        set_clock("2026-08-21T00:00:00Z")
        acked = acknowledge_assignment(assignment["id"], custodian["id"])
        assert acked["was_late"] is False, (
            "REMINDER_ADJUSTED: effective due 2026-08-15 + 1 x 7d = 2026-08-22; "
            "2026-08-21 is not strictly after it"
        )
        hold_after = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert hold_after["late_ack_count"] == 0


class TestEscalationBoundary:
    def _setup_fast_program(self):
        return setup_issued_hold(
            program_overrides={
                "ack_deadline_days": 1,
                "reminder_interval_days": 7,
                "max_reminders_before_escalation": 3,
            },
            matter_ref="M-ESC")

    def test_reminders_sent_below_max_without_escalation(self, api):
        """PRD §3.6: "The sweep visits every assignment in `PENDING` whose
        `ack_due_date` is strictly before the current logical time. If the
        assignment's `reminder_count` is still below the program's
        `max_reminders_before_escalation`, the sweep sends a reminder:
        `reminder_count` is incremented by 1, `last_reminder_at` is set to now"

        Design: Difficulty/boundary_precision_check/escalation_at_exact_max_reminders
        """
        scen = self._setup_fast_program()
        assignment = scen["assignments"][0]
        program_id = scen["ctx"]["program"]["id"]
        # Issued at the default clock 2026-08-01 -> ack_due 2026-08-02.

        for day in ("2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z",
                    "2026-08-05T00:00:00Z"):
            set_clock(day)
            sweep = run_reminder_sweep(program_id)
            assert sweep["reminders_sent"] == 1
            assert sweep["escalations_raised"] == 0, (
                "the count reaching max during a sweep does not escalate in it"
            )

        after = validate_success(api.get_hold_custodian(assignment["id"], RM), 200)
        assert after["status"] == "PENDING"
        assert after["reminder_count"] == 3

    def test_escalation_fires_once_count_reaches_max(self, api):
        """PRD §3.6: "If instead the assignment's `reminder_count` has already
        reached `max_reminders_before_escalation` (inclusive boundary), the
        assignment escalates: its status becomes `ESCALATED`, `escalated_at` is
        set to now, and a `ReminderLog` entry of kind `ESCALATION` is written
        with `reminder_seq` equal to the current `reminder_count`."

        Design: Difficulty/boundary_precision_check/escalation_at_exact_max_reminders
        """
        scen = self._setup_fast_program()
        assignment = scen["assignments"][0]
        program_id = scen["ctx"]["program"]["id"]

        for day in ("2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z",
                    "2026-08-05T00:00:00Z"):
            set_clock(day)
            run_reminder_sweep(program_id)

        set_clock("2026-08-06T00:00:00Z")
        sweep = run_reminder_sweep(program_id)
        assert sweep["reminders_sent"] == 0, (
            "reminder_count 3 >= max 3: no further reminder"
        )
        assert sweep["escalations_raised"] == 1

        after = validate_success(api.get_hold_custodian(assignment["id"], RM), 200)
        assert after["status"] == "ESCALATED"
        assert after["reminder_count"] == 3


class TestReminderLogTrail:
    def test_reminder_log_records_full_hold_notice_trail(self, api):
        """PRD §3.10: "Every custodian-facing notice is captured in the
        append-only `ReminderLog`. Each entry carries `program_id`, `hold_id`,
        `hold_custodian_id`, `custodian_id`, a `kind` drawn from
        `ISSUED_NOTICE`, `REMINDER`, `ESCALATION`, `RELEASE_NOTICE`, and
        `CANCEL_NOTICE`, the `sent_at` timestamp on the logical clock, and a
        `reminder_seq` equal to the assignment's `reminder_count` after the
        entry — which is 0 for every kind except `REMINDER`."
        PRD §3.10: "The log is the evidentiary trail that a custodian was
        notified, reminded, escalated, released, or cancelled, and is queryable
        by program, hold, assignment, custodian, and kind."
        PRD §2.3: "List results are sorted by `created_at` ascending (oldest
        first)."

        Design: Corner/endpoints/reminder_log_records_full_hold_notice_trail
        """
        scen = setup_issued_hold(
            program_overrides={"ack_deadline_days": 1}, matter_ref="M-LOG")
        hold = scen["hold"]
        assignment = scen["assignments"][0]
        custodian = scen["custodians"][0]
        # Issued at the default clock 2026-08-01 -> ack_due 2026-08-02.

        set_clock("2026-08-03T00:00:00Z")
        sweep = run_reminder_sweep(scen["ctx"]["program"]["id"])
        assert sweep["reminders_sent"] == 1

        # Advance once more so every notice kind carries a distinct timestamp
        # and the created_at-ascending trail order is fully determined.
        set_clock("2026-08-04T00:00:00Z")
        acknowledge_assignment(assignment["id"], custodian["id"])
        released = release_hold(hold["id"], read_hold_version(hold["id"]))
        assert validate_success(released, 200)["status"] == "RELEASED"

        trail, meta = validate_paginated(
            api.list_reminder_logs(AUD, params={"hold_id": hold["id"]}))
        assert meta["total_count"] == 3, (
            "ISSUED_NOTICE + REMINDER + RELEASE_NOTICE for the single custodian"
        )
        assert trail[0]["kind"] == "ISSUED_NOTICE", "oldest first"
        assert [e["kind"] for e in trail] == [
            "ISSUED_NOTICE", "REMINDER", "RELEASE_NOTICE"]
        for entry in trail:
            assert entry["hold_custodian_id"] == assignment["id"]
            assert entry["custodian_id"] == custodian["id"]

        reminders, rem_meta = validate_paginated(
            api.list_reminder_logs(AUD, params={"hold_id": hold["id"],
                                                "kind": "REMINDER"}))
        assert rem_meta["total_count"] == 1
        assert reminders[0]["reminder_seq"] == 1, (
            "reminder_seq equals the assignment's reminder_count after the entry"
        )
        assert reminders[0]["custodian_id"] == custodian["id"]
