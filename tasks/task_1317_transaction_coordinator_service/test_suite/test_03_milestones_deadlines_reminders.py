"""Milestone, deadline, and reminder state machines, including clock-sweep effects."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    make_active_listing_file, get_milestone_by_name, get_deadline_by_kind,
    list_reminders_for_deadline,
)


class TestMilestoneTransitions:
    def test_milestone_complete_before_start_rejected(self):
        """PRD §3.5: "Completing requires `IN_PROGRESS` or `OVERDUE`
        (`ERR_MILESTONE_INVALID_STATE`); it stamps `completed_at` and sets
        `late_completion` to true exactly when the milestone was completed from
        `OVERDUE`."

        Design: Corner/state_machines/milestone_complete_before_start_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        ms = get_milestone_by_name(coord_h, file_id, "Listing Paperwork")
        assert ms["status"] == "PENDING"
        resp = api_client.complete_milestone(ms["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_INVALID_STATE)
        after = validate_success(api_client.get_milestone(ms["id"], coord_h))
        assert after["status"] == "PENDING", "a failed complete must leave the milestone PENDING"

    def test_milestone_overdue_then_late_completion(self):
        """PRD §3.5: "When the logical clock advances past a milestone's `due_date`
        while it is still `PENDING` or `IN_PROGRESS`, the system moves it to
        `OVERDUE`."
        PRD §3.5: "Completing requires `IN_PROGRESS` or `OVERDUE`
        (`ERR_MILESTONE_INVALID_STATE`); it stamps `completed_at` and sets
        `late_completion` to true exactly when the milestone was completed from
        `OVERDUE`."

        Design: Corner/state_machines/milestone_overdue_then_late_completion
        """
        # Cash file (inspection 14 / appraisal 21) so no deadline expires at the
        # sweep instant; the milestone is due 2026-08-03 + 5 = 2026-08-08.
        scen = make_active_listing_file(file_overrides={
            "inspection_offset_days": 14, "appraisal_offset_days": 21,
        })
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        ms = get_milestone_by_name(coord_h, file_id, "Listing Paperwork")
        assert ms["due_date"] == "2026-08-08"
        validate_success(api_client.set_clock({"to_iso8601": "2026-08-09T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))
        overdue = validate_success(api_client.get_milestone(ms["id"], coord_h))
        assert overdue["status"] == "OVERDUE", \
            "the clock sweep past due_date must move the milestone to OVERDUE"
        completed = validate_success(api_client.complete_milestone(ms["id"], coord_h))
        assert completed["status"] == "COMPLETED"
        assert completed["late_completion"] is True, \
            "completing from OVERDUE must flag late_completion"
        assert completed["completed_at"] is not None

    def test_mandatory_milestone_waive_rejected(self):
        """PRD §3.5: "Waiving requires `PENDING`, `IN_PROGRESS`, or `OVERDUE` and that
        `mandatory` be false — waiving a mandatory milestone is
        `ERR_MILESTONE_MANDATORY`."

        Design: Corner/state_machines/mandatory_milestone_waive_rejected
        """
        scen = make_active_listing_file(template_overrides={
            "milestone_defs": [
                {"name": "Earnest Money", "offset_days": 3, "mandatory": True},
                {"name": "Listing Paperwork", "offset_days": 5, "mandatory": False},
            ],
        })
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        ms = get_milestone_by_name(coord_h, file_id, "Earnest Money")
        assert ms["mandatory"] is True
        resp = api_client.waive_milestone(ms["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_MANDATORY)
        after = validate_success(api_client.get_milestone(ms["id"], coord_h))
        assert after["status"] == "PENDING", "a failed waive must leave the milestone PENDING"

    def test_optional_milestone_waive_succeeds(self):
        """PRD §3.5: "Waiving requires `PENDING`, `IN_PROGRESS`, or `OVERDUE` and that
        `mandatory` be false — waiving a mandatory milestone is
        `ERR_MILESTONE_MANDATORY`."

        Design: Corner/state_machines/optional_milestone_waive_succeeds
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        ms = get_milestone_by_name(coord_h, file_id, "Listing Paperwork")
        assert ms["mandatory"] is False
        waived = validate_success(api_client.waive_milestone(ms["id"], coord_h))
        assert waived["status"] == "WAIVED"


class TestDeadlineAndReminderEffects:
    def test_deadline_mark_met_cancels_queued_reminders(self):
        """PRD §3.5: "Marking met requires the deadline `PENDING`
        (`ERR_DEADLINE_INVALID_STATE`) and the owning file in `ACTIVE` or
        `PENDING_CLOSE` (`ERR_FILE_NOT_ACTIVE`); it stamps `met_at` and cancels all of
        the deadline's `QUEUED` reminders."

        Design: Corner/state_machines/deadline_mark_met_cancels_queued_reminders
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        insp = get_deadline_by_kind(coord_h, file_id, "INSPECTION")
        appr = get_deadline_by_kind(coord_h, file_id, "APPRAISAL")
        assert len(list_reminders_for_deadline(coord_h, insp["id"], status="QUEUED")) == 3
        met = validate_success(api_client.mark_deadline_met(insp["id"], coord_h))
        assert met["status"] == "MET"
        assert met["met_at"] is not None
        assert list_reminders_for_deadline(coord_h, insp["id"], status="QUEUED") == [], \
            "mark-met must cancel every QUEUED reminder of the deadline"
        cancelled = list_reminders_for_deadline(coord_h, insp["id"], status="CANCELLED")
        assert len(cancelled) == 3
        # Other deadlines are untouched.
        appr_after = validate_success(api_client.get_deadline(appr["id"], coord_h))
        assert appr_after["status"] == "PENDING"
        assert len(list_reminders_for_deadline(coord_h, appr["id"], status="QUEUED")) == 3

    def test_deadline_expiry_fires_escalation_cascade(self):
        """PRD §3.5: "When the clock advances past a `PENDING` deadline's `due_date`,
        the system moves it to `EXPIRED`: `QUEUED` reminders are cancelled, an
        escalation communication entry is created on the file with `entry_kind`
        `ESCALATION`, `party` `SYSTEM`, `direction` `SYSTEM`, and `status`
        `ESCALATED` — and that creation itself increments the file's
        `open_escalation_count` by 1 — and the deadline's `escalated` flag is set
        true."
        PRD §3.10: "The sweep response reports `reminders_sent`, `deadlines_expired`,
        `milestones_marked_overdue`, and `communications_escalated` counts."

        Design: Corner/state_machines/deadline_expiry_fires_escalation_cascade
        """
        # Milestone due 2026-09-02 (offset 30) stays PENDING through the sweep.
        scen = make_active_listing_file(template_overrides={
            "milestone_defs": [{"name": "Listing Paperwork", "offset_days": 30, "mandatory": False}],
        })
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        insp = get_deadline_by_kind(coord_h, file_id, "INSPECTION")
        assert insp["due_date"] == "2026-08-10"
        sweep = validate_success(api_client.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"},
                                                      TEST_USERS["admin_headers"]))
        assert sweep["reminders_sent"] == 3
        assert sweep["deadlines_expired"] == 1
        assert sweep["milestones_marked_overdue"] == 0
        assert sweep["communications_escalated"] == 0

        dl_after = validate_success(api_client.get_deadline(insp["id"], coord_h))
        assert dl_after["status"] == "EXPIRED"
        assert dl_after["escalated"] is True

        all_comms = get_success_data(api_client.list_communications(coord_h, params={"limit": 100}))
        escalations = [c for c in all_comms if c["status"] == "ESCALATED"]
        assert len(escalations) == 1, "expiry must mint exactly one escalation entry"
        esc = escalations[0]
        assert esc["entry_kind"] == "ESCALATION"
        assert esc["party"] == "SYSTEM"
        assert esc["direction"] == "SYSTEM"

        f_after = validate_success(api_client.get_file(file_id, coord_h))
        assert f_after["open_escalation_count"] == 1

        # The clock jumped past every scheduled time while the deadline was still
        # PENDING, so all three reminders were sent (none remained QUEUED to cancel).
        sent = list_reminders_for_deadline(coord_h, insp["id"], status="SENT")
        assert len(sent) == 3
        assert all(r["sent_at"] is not None for r in sent)
        assert list_reminders_for_deadline(coord_h, insp["id"], status="QUEUED") == []

    def test_reminder_sent_by_clock_sweep(self):
        """PRD §3.5: "Reminders themselves live in `QUEUED → SENT` (system-driven,
        when clock time reaches `scheduled_at` and the owning deadline is still
        `PENDING`, stamping `sent_at`) or `QUEUED → CANCELLED` when their deadline
        goes terminal or is rescheduled."
        PRD §3.4: "Each deadline then generates its reminder schedule: candidate
        reminders sit at 5 days before, 2 days before, and on the due date itself,
        each at 09:00:00 UTC; only candidates whose `scheduled_at` is strictly after
        the current clock time are actually created, and created reminders are
        numbered `sequence_no` 1, 2, 3 in ascending `scheduled_at` order."

        Design: Corner/state_machines/reminder_sent_by_clock_sweep
        """
        scen = make_active_listing_file(template_overrides={
            "milestone_defs": [{"name": "Listing Paperwork", "offset_days": 30, "mandatory": False}],
        })
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        insp = get_deadline_by_kind(coord_h, file_id, "INSPECTION")
        assert insp["due_date"] == "2026-08-10"
        sweep = validate_success(api_client.set_clock({"to_iso8601": "2026-08-05T10:00:00Z"},
                                                      TEST_USERS["admin_headers"]))
        assert sweep["reminders_sent"] == 1, "only the 2026-08-05T09:00Z reminder is due"
        assert sweep["deadlines_expired"] == 0

        sent = list_reminders_for_deadline(coord_h, insp["id"], status="SENT")
        assert len(sent) == 1
        assert sent[0]["scheduled_at"].startswith("2026-08-05T09:00:00")
        assert sent[0]["sequence_no"] == 1
        assert sent[0]["sent_at"] is not None

        queued = list_reminders_for_deadline(coord_h, insp["id"], status="QUEUED")
        assert len(queued) == 2
        queued_times = sorted(r["scheduled_at"] for r in queued)
        assert queued_times[0].startswith("2026-08-08T09:00:00")
        assert queued_times[1].startswith("2026-08-10T09:00:00")
