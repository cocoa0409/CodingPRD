"""Risk snapshots and the compliance report lifecycle (PRD §3.11)."""
from test_helpers import (
    ApiErrorId,
    assert_timestamp_eq,
    get_success_data,
    make_leak,
    make_snapshot,
    set_clock,
    setup_accepted_run,
    setup_draft_report,
    setup_pending_review_report,
    setup_submitted_report,
    validate_error,
    validate_success,
)


class TestReportLifecycle:
    def test_compliance_report_happy_path_to_accepted(self, api):
        """PRD §3.11: "on success it pins both snapshots — their status becomes
        `PINNED` and they are immutable thereafter"; "Filing with the regulator
        (`PENDING_REVIEW → SUBMITTED`) requires `PENDING_REVIEW` state
        (`ERR_REPORT_NOT_PENDING_REVIEW`), requires the officer's
        `jurisdiction_scope` to include the report's `regulator`
        (`ERR_OFFICER_OUT_OF_JURISDICTION`), and requires the logical clock to be
        no later than 60 days after `reporting_period_end` (`ERR_REPORT_PAST_DUE`);
        success stamps `submitted_at`"; "acceptance (`SUBMITTED → ACCEPTED`,
        terminal)".

        Design: Corner/state_machines/compliance_report_happy_path_to_accepted
        """
        ctx = setup_draft_report()
        report = ctx["report"]
        bound = get_success_data(api.bind_snapshots(
            report["id"],
            {
                "leak_section_snapshot_id": ctx["snap_leak"]["id"],
                "cp_section_snapshot_id": ctx["snap_cp"]["id"],
                "expected_report_version": report["version"],
            },
            ctx["co_h"],
        ))
        pending = validate_success(api.submit_for_review(
            report["id"], {"expected_report_version": bound["version"]}, ctx["co_h"],
        ))
        assert pending["status"] == "PENDING_REVIEW"
        pinned = get_success_data(api.get_risk_model_snapshot(ctx["snap_leak"]["id"], ctx["co_h"]))
        assert pinned["status"] == "PINNED"

        submitted = validate_success(api.submit_to_regulator(report["id"], ctx["co_h"]))
        assert submitted["status"] == "SUBMITTED"
        assert_timestamp_eq(submitted["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")

        accepted = validate_success(api.record_acceptance(report["id"], ctx["co_h"]))
        assert accepted["status"] == "ACCEPTED"

    def test_compliance_report_rejection_resubmission_cycle(self, api):
        """PRD §3.11: "Reopening the draft (`RESUBMISSION_REQUIRED → DRAFT`)
        requires `RESUBMISSION_REQUIRED` state
        (`ERR_REPORT_NOT_RESUBMISSION_REQUIRED`) and, on success, both pinned
        snapshots revert from `PINNED` to `STALE` — forcing fresh snapshots to be
        generated — while `leak_section_snapshot_id` and `cp_section_snapshot_id`
        are nulled out, ready for a new binding."

        Design: Corner/state_machines/compliance_report_rejection_resubmission_cycle
        """
        ctx = setup_submitted_report()
        report = ctx["report"]
        rejected = validate_success(api.record_rejection(report["id"], ctx["co_h"]))
        assert rejected["status"] == "REJECTED_BY_REGULATOR"
        resub = validate_success(api.request_resubmission(report["id"], ctx["co_h"]))
        assert resub["status"] == "RESUBMISSION_REQUIRED"
        reopened = validate_success(api.reopen_draft(report["id"], ctx["co_h"]))
        assert reopened["status"] == "DRAFT"
        assert reopened["leak_section_snapshot_id"] is None
        assert reopened["cp_section_snapshot_id"] is None
        snap = get_success_data(api.get_risk_model_snapshot(ctx["snap_leak"]["id"], ctx["co_h"]))
        assert snap["status"] == "STALE"


class TestReportStateGates:
    def test_report_submit_for_review_from_pending_rejected(self, api):
        """PRD §3.11: "it requires the report to be `DRAFT` (`ERR_REPORT_NOT_DRAFT`)"."

        Design: Corner/validations/report_submit_for_review_from_pending_rejected
        """
        ctx = setup_pending_review_report()
        report = ctx["report"]
        resp = api.submit_for_review(
            report["id"], {"expected_report_version": report["version"]}, ctx["co_h"],
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DRAFT)

    def test_report_submit_to_regulator_from_draft_rejected(self, api):
        """PRD §3.11: "Filing with the regulator (`PENDING_REVIEW → SUBMITTED`)
        requires `PENDING_REVIEW` state (`ERR_REPORT_NOT_PENDING_REVIEW`)."

        Design: Corner/validations/report_submit_to_regulator_from_draft_rejected
        """
        ctx = setup_draft_report()
        resp = api.submit_to_regulator(ctx["report"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_PENDING_REVIEW)

    def test_report_record_acceptance_from_draft_rejected(self, api):
        """PRD §3.11: "acceptance (`SUBMITTED → ACCEPTED`, terminal) or rejection
        (`SUBMITTED → REJECTED_BY_REGULATOR`), each requiring `SUBMITTED` state
        (`ERR_REPORT_NOT_SUBMITTED`)."

        Design: Corner/validations/report_record_acceptance_from_draft_rejected
        """
        ctx = setup_draft_report()
        resp = api.record_acceptance(ctx["report"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_SUBMITTED)

    def test_report_request_resubmission_from_submitted_rejected(self, api):
        """PRD §3.11: "Requesting resubmission
        (`REJECTED_BY_REGULATOR → RESUBMISSION_REQUIRED`) requires
        `REJECTED_BY_REGULATOR` state (`ERR_REPORT_NOT_REJECTED`)."

        Design: Corner/validations/report_request_resubmission_from_submitted_rejected
        """
        ctx = setup_submitted_report()
        resp = api.request_resubmission(ctx["report"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_REJECTED)

    def test_report_reopen_draft_from_draft_rejected(self, api):
        """PRD §3.11: "Reopening the draft (`RESUBMISSION_REQUIRED → DRAFT`)
        requires `RESUBMISSION_REQUIRED` state
        (`ERR_REPORT_NOT_RESUBMISSION_REQUIRED`)."

        Design: Corner/validations/report_reopen_draft_from_draft_rejected
        """
        ctx = setup_draft_report()
        resp = api.reopen_draft(ctx["report"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_RESUBMISSION_REQUIRED)


class TestReportBusinessRules:
    def test_officer_out_of_jurisdiction_on_submit(self, api):
        """PRD §3.11: "requires the officer's `jurisdiction_scope` to include the
        report's `regulator` (`ERR_OFFICER_OUT_OF_JURISDICTION`)"."

        Design: Corner/validations/officer_out_of_jurisdiction_on_submit
        """
        ctx = setup_pending_review_report(jurisdiction_scope=("STATE_PUC",))
        resp = api.submit_to_regulator(ctx["report"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_OFFICER_OUT_OF_JURISDICTION)

    def test_report_past_due_on_submit_to_regulator(self, api):
        """PRD §3.11: "requires the logical clock to be no later than 60 days
        after `reporting_period_end` (`ERR_REPORT_PAST_DUE`)" — period end
        2026-05-31T23:59:59Z makes the deadline 2026-07-30T23:59:59Z; the clock
        reads 2026-08-01.

        Design: Corner/validations/report_past_due_on_submit_to_regulator
        """
        ctx = setup_pending_review_report(
            period=("2026-01-01T00:00:00Z", "2026-05-31T23:59:59Z"),
        )
        resp = api.submit_to_regulator(ctx["report"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_REPORT_PAST_DUE)

    def test_bind_stale_snapshot_rejected(self, api):
        """PRD §3.11: "Binding is rejected with `ERR_SNAPSHOT_STALE` if either
        named snapshot is not `CURRENT`" and generation "marks any prior
        same-kind snapshots `STALE` so the new one is the sole `CURRENT` snapshot
        of its kind."

        Design: Corner/validations/bind_stale_snapshot_rejected
        """
        ctx = setup_draft_report()
        # Regenerating the LEAK_SECTION kind stales the originally bound candidate.
        stale_snapshot = ctx["snap_leak"]
        make_snapshot(ctx, "leak-section-2", "LEAK_SECTION")
        report = ctx["report"]
        resp = api.bind_snapshots(
            report["id"],
            {
                "leak_section_snapshot_id": stale_snapshot["id"],
                "cp_section_snapshot_id": ctx["snap_cp"]["id"],
                "expected_report_version": report["version"],
            },
            ctx["co_h"],
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_STALE)

    def test_occ_stale_report_version_on_bind_snapshots(self, api):
        """PRD §2.7: "binding risk-model snapshots onto a draft compliance report
        likewise requires `expected_report_version`, with the same
        `ERR_STALE_REPORT_VERSION` (HTTP 412) on mismatch."

        Design: Corner/cross_cutting/occ_stale_report_version_on_bind_snapshots
        """
        ctx = setup_draft_report()
        report = ctx["report"]
        payload = {
            "leak_section_snapshot_id": ctx["snap_leak"]["id"],
            "cp_section_snapshot_id": ctx["snap_cp"]["id"],
            "expected_report_version": report["version"],
        }
        get_success_data(api.bind_snapshots(report["id"], payload, ctx["co_h"]))
        # Replaying the same pre-bind version must now be stale.
        resp = api.bind_snapshots(report["id"], payload, ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_STALE_REPORT_VERSION)


class TestSnapshotStaling:
    def test_risk_snapshot_auto_stales_on_new_leak(self, api):
        """PRD §3.11: "snapshots also stale automatically the moment any
        underlying input changes — a new leak, a leak verified cleared, a
        cathodic anomaly opening, a segment posture shift."
        PRD §3.5: "marks any risk-model snapshot touching the segment as stale."

        Design: Corner/cross_cutting/risk_snapshot_auto_stales_on_new_leak
        """
        ctx = setup_accepted_run(route_code="R-SN")
        snapshot = make_snapshot(ctx, "pre-leak", "FULL")
        assert snapshot["status"] == "CURRENT"

        make_leak(ctx, ctx["segments"][0]["id"], ctx["run"]["id"])
        after = get_success_data(api.get_risk_model_snapshot(snapshot["id"], ctx["ia_h"]))
        assert after["status"] == "STALE"
