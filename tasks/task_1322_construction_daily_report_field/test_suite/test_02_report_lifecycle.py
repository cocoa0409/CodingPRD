"""Daily report lifecycle: posture gating, terminal lockdown, revision cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_entry,
    add_incident,
    get_report,
    make_locked_report,
    make_submitted_report,
    make_under_review_report,
    set_clock,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_SO = TEST_USERS["safety_officer_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


class TestTerminalLockdown:
    def test_locked_report_rejects_every_transition(self, api):
        """PRD section 3.9: "a `SystemAdmin` moves an `APPROVED` report to the
        terminal `LOCKED`" and "Every one of these transitions requires its
        stated source status; a mismatched status fails with
        `ERR_REPORT_INVALID_TRANSITION`".

        Design: Corner/state_machines/report_terminal_lockdown_rejects_all_transitions
        """
        ctx = make_locked_report()
        rid = ctx["report"]["id"]

        attempts = [
            api.submit_report(rid, _SUPT),
            api.start_review_report(rid, _PM),
            api.approve_report(rid, _PM),
            api.request_revision_report(rid, {"reason": "again"}, _PM),
            api.return_to_draft_report(rid, _SUPT),
            api.recall_report(rid, _SUPT),
            api.reopen_report(rid, {"reason": "try"}, _PM),
            api.lock_report(rid, _ADMIN),
        ]
        for resp in attempts:
            validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_TRANSITION)
            assert resp.status_code == 409

        after = get_report(rid)
        assert after["status"] == "LOCKED"


class TestContentPostureGate:
    def test_child_create_on_sealed_report_rejected(self, api):
        """PRD section 2.6: "While a report is `SEALED`, the server rejects, with
        `ERR_REPORT_NOT_EDITABLE` (HTTP 409), every one of the following:
        creating crew entries, equipment entries, weather observations, delay
        events, safety observations, media attachments, material deliveries,
        quantity entries, and T&M tickets".

        Design: Corner/state_machines/child_create_on_sealed_report_rejected
        """
        ctx = make_submitted_report()
        report = ctx["report"]
        assert report["status"] == "SUBMITTED"
        assert report["content_posture"] == "SEALED"
        workers_before = report["total_workers"]

        resp = api.create_crew_entry(
            {"report_id": report["id"], "work_area_id": ctx["area"]["id"],
             "subcontractor": "S", "trade": "T", "worker_count": 1,
             "hours_per_worker": 8, "work_performed": "late"},
            _SUPT)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_EDITABLE)
        assert resp.status_code == 409

        after = get_report(report["id"])
        assert after["total_workers"] == workers_before, \
            "sealed report must not accept new crew lines"

    def test_incident_create_on_locked_report_rejected(self, api):
        """PRD section 2.6: "Against a `LOCKED` report, both are rejected with
        `ERR_INCIDENT_ON_LOCKED_REPORT` (HTTP 409)." — the incident carve-out
        that permits capture on sealed reports stops at LOCKED.

        Design: Corner/state_machines/incident_create_on_locked_report_rejected
        """
        ctx = make_locked_report()

        resp = api.create_incident(
            {"report_id": ctx["report"]["id"], "work_area_id": ctx["area"]["id"],
             "occurred_at": "2026-08-05T10:00:00Z", "severity": "FIRST_AID",
             "narrative": "Late discovery"},
            _SO)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_ON_LOCKED_REPORT)
        assert resp.status_code == 409


class TestRevisionCycle:
    def test_revision_loop_reopens_editing_and_resubmit(self, api):
        """PRD section 3.9: "Requesting revision moves `UNDER_REVIEW` to
        `REVISION_REQUESTED`, capturing a `reason`, incrementing `revision_count`
        by one, and returning the posture to `EDITABLE`; the superintendent then
        works the report and either resubmits or uses return-to-draft to move
        `REVISION_REQUESTED` back to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/daily_report_revision_cycle
        """
        ctx = make_under_review_report()
        report = ctx["report"]

        revised = validate_success(api.request_revision_report(
            report["id"], {"reason": "Fix manpower"}, _PM))
        assert revised["status"] == "REVISION_REQUESTED"
        assert revised["revision_count"] == 1
        assert revised["content_posture"] == "EDITABLE"

        # The reopened posture re-admits child writes mid-cycle.
        entry = add_crew_entry(report["id"], ctx["area"]["id"],
                               trade="Electric", worker_count=1,
                               hours_per_worker=4, work_performed="temp power")
        assert entry["id"]

        draft = validate_success(api.return_to_draft_report(report["id"], _SUPT))
        assert draft["status"] == "DRAFT"

        resubmitted = validate_success(api.submit_report(report["id"], _SUPT))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1, \
            "resubmission must not re-increment revision_count"

    def test_revision_count_accumulates_across_cycles(self, api):
        """PRD section 3.9: "Requesting revision moves `UNDER_REVIEW` to
        `REVISION_REQUESTED`, capturing a `reason`, incrementing `revision_count`
        by one, and returning the posture to `EDITABLE`" — each pass through the
        loop adds exactly one.

        Design: Difficulty/non_linear_state_machine/daily_report_revision_cycle
        """
        ctx = make_submitted_report()
        rid = ctx["report"]["id"]

        for expected_count in (1, 2):
            validate_success(api.start_review_report(rid, _PM))
            revised = validate_success(api.request_revision_report(
                rid, {"reason": f"cycle {expected_count}"}, _PM))
            assert revised["status"] == "REVISION_REQUESTED"
            assert revised["revision_count"] == expected_count
            assert revised["content_posture"] == "EDITABLE"
            draft = validate_success(api.return_to_draft_report(rid, _SUPT))
            assert draft["status"] == "DRAFT"
            resubmitted = validate_success(api.submit_report(rid, _SUPT))
            assert resubmitted["status"] == "SUBMITTED"

        final = get_report(rid)
        assert final["revision_count"] == 2
        assert final["content_posture"] == "SEALED"
