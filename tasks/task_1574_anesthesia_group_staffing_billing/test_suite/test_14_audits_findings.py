"""Audit lifecycle: close gating, finding ops on closed audits, scan
create-or-merge dedupe, and finding bucket migration (PRD §3.9)."""
from test_helpers import (
    AUDITOR,
    SCHED,
    ApiErrorId,
    get_success_data,
    list_audits,
    list_findings,
    set_clock,
    setup_credential_lapse_audit,
    validate_error,
    api_client,
)


class TestAuditCloseGating:
    def test_close_blocked_by_open_finding_then_succeeds(self, api):
        """PRD §3.9: "Once every finding on an audit is `RESOLVED` or
        `DISMISSED`, the auditor may close the audit, moving it from `OPEN` to
        the terminal `CLOSED` state; any lingering `OPEN` finding rejects the
        close with `ERR_UNRESOLVED_FINDINGS`."

        Design: Corner/state_machines/audit_close_with_open_findings_rejected
        """
        ctx = setup_credential_lapse_audit(num_cases=1)
        audit = ctx["audit"]
        findings = list_findings({"audit_id": audit["id"]})
        assert len(findings) == 1
        resp = api.close_audit(audit["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_FINDINGS)
        get_success_data(api.resolve_finding(
            findings[0]["id"], {"resolution_note": "CREDENTIALS_RENEWED"},
            AUDITOR))
        closed = get_success_data(api.close_audit(audit["id"], AUDITOR))
        assert closed["status"] == "CLOSED"


class TestFindingOpsOnClosedAudit:
    def test_resolve_and_dismiss_rejected_once_audit_closed(self, api):
        """PRD §3.9: "both actions require the parent audit to be `OPEN` (else
        `ERR_AUDIT_NOT_OPEN`)".

        Design: Corner/state_machines/finding_ops_on_closed_audit_rejected
        """
        ctx = setup_credential_lapse_audit(num_cases=1)
        audit = ctx["audit"]
        findings = list_findings({"audit_id": audit["id"]})
        finding_id = findings[0]["id"]
        get_success_data(api.resolve_finding(finding_id,
                                             {"resolution_note": "FIXED"}, AUDITOR))
        get_success_data(api.close_audit(audit["id"], AUDITOR))
        resp_resolve = api.resolve_finding(finding_id,
                                           {"resolution_note": "AGAIN"}, AUDITOR)
        validate_error(resp_resolve, ApiErrorId.ERR_AUDIT_NOT_OPEN)
        resp_dismiss = api.dismiss_finding(finding_id,
                                           {"dismissal_reason": "MOOT"}, AUDITOR)
        validate_error(resp_dismiss, ApiErrorId.ERR_AUDIT_NOT_OPEN)


class TestAuditScanCreateOrMerge:
    def test_repeated_scans_merge_and_dedupe(self, api):
        """PRD §3.9: "At most one `OPEN` audit exists per roster: if one is
        already open, the scan merges into it; otherwise a new `OPEN` audit is
        created. Merging dedupes — a candidate finding is skipped when an
        `OPEN` finding with the same `finding_type`, `case_id`, and
        `assignment_id` already exists in that audit."

        Design: Corner/calculations/audit_scan_dedupes_into_existing_open_audit
        """
        ctx = setup_credential_lapse_audit(num_cases=1)
        roster_id = ctx["roster"]["id"]
        existing = ctx["audit"]
        first = get_success_data(api.run_audit_scan({"roster_id": roster_id},
                                                    AUDITOR))
        second = get_success_data(api.run_audit_scan({"roster_id": roster_id},
                                                     AUDITOR))
        assert first["id"] == existing["id"] == second["id"], \
            "scans must merge into the existing OPEN audit"
        audits = list_audits({"roster_id": roster_id})
        assert len(audits) == 1
        findings = list_findings({"audit_id": existing["id"]})
        assert len(findings) == 1, "the duplicate candidate finding is skipped"
        assert first["realtime_score"] == 10


class TestFindingBucketMigration:
    def test_scores_migrate_when_cases_go_terminal(self, api):
        """PRD §3.9: "Because a finding migrates between the two scores when
        its case goes terminal, identical finding sets can yield different
        realtime and period pictures."
        PRD §3.9: "The `risk_band` derives from `period_score`: below 20 is
        `LOW`; at least 20 but below 50 is `ELEVATED`".

        Design: Corner/calculations/finding_bucket_migration_on_case_cancellation
        """
        ctx = setup_credential_lapse_audit(num_cases=2)
        audit = ctx["audit"]
        assert audit["realtime_score"] == 20
        assert audit["period_score"] == 0
        assert audit["risk_band"] == "LOW"
        # Cancel both cases on a prior-day clock (no standby: primaries are
        # PROPOSED at cancel).
        set_clock("2026-08-09T08:00:00Z")
        for case in ctx["cases"]:
            get_success_data(api.cancel_case(
                case["id"], {"cancellation_reason": "SCHEDULE_CHANGE"}, SCHED))
        after = get_success_data(api.get_audit(audit["id"], AUDITOR))
        assert after["realtime_score"] == 0, \
            "both bucket cases terminal -> realtime drains to 0"
        assert after["period_score"] == 20
        assert after["risk_band"] == "ELEVATED", \
            "exactly 20 lands ELEVATED (>= 20 boundary)"
