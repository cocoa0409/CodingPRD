"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clients ──────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def advance_period(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/advance-period", {}, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    # ─── Retainer ledgers ─────────────────────────────────────────────────
    def list_retainer_ledgers(self, headers, params=None):
        return self._request("GET", "/retainer-ledgers", headers=headers, params=params)

    def get_retainer_ledger(self, ledger_id, headers):
        return self._request("GET", f"/retainer-ledgers/{ledger_id}", headers=headers)

    # ─── Assets ───────────────────────────────────────────────────────────
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def decommission_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/decommission", {}, headers)

    # ─── Engagements ──────────────────────────────────────────────────────
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def authorize_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/authorize", {}, headers)

    def start_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/start", {}, headers)

    def complete_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/complete", {}, headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/cancel", {}, headers)

    # ─── Scans ────────────────────────────────────────────────────────────
    def create_scan(self, payload, headers):
        return self._request("POST", "/scans", payload, headers)

    def list_scans(self, headers, params=None):
        return self._request("GET", "/scans", headers=headers, params=params)

    def get_scan(self, scan_id, headers):
        return self._request("GET", f"/scans/{scan_id}", headers=headers)

    def start_scan(self, scan_id, headers):
        return self._request("POST", f"/scans/{scan_id}/start", {}, headers)

    def complete_scan(self, scan_id, payload, headers):
        return self._request("POST", f"/scans/{scan_id}/complete", payload, headers)

    def abort_scan(self, scan_id, headers):
        return self._request("POST", f"/scans/{scan_id}/abort", {}, headers)

    # ─── Findings ─────────────────────────────────────────────────────────
    def create_finding(self, payload, headers):
        return self._request("POST", "/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def start_remediation(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/start-remediation", {}, headers)

    def submit_remediation(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/submit-remediation", {}, headers)

    def retest_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/retest", payload, headers)

    def accept_risk(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/accept-risk", {}, headers)

    def mark_false_positive(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/mark-false-positive", {}, headers)

    # ─── Alerts ───────────────────────────────────────────────────────────
    def create_alert(self, payload, headers):
        return self._request("POST", "/alerts", payload, headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    def triage_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/triage", {}, headers)

    def dismiss_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/dismiss", {}, headers)

    def promote_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/promote", {}, headers)

    # ─── Incidents ────────────────────────────────────────────────────────
    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def acknowledge_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/acknowledge", {}, headers)

    def contain_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/incidents/{incident_id}/contain", payload or {}, headers)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/escalate", {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/resolve", payload, headers)

    def reopen_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/reopen", {}, headers)

    # ─── Compliance audits ────────────────────────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def begin_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/begin-fieldwork", {}, headers)

    def mark_ready(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/mark-ready", {}, headers)

    def attest_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/attest", {}, headers)

    def fail_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/fail", {}, headers)

    def reopen_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/reopen-fieldwork", {}, headers)

    # ─── Audit evidence ───────────────────────────────────────────────────
    def create_evidence(self, payload, headers):
        return self._request("POST", "/evidence", payload, headers)

    def list_evidence(self, headers, params=None):
        return self._request("GET", "/evidence", headers=headers, params=params)

    def get_evidence(self, evidence_id, headers):
        return self._request("GET", f"/evidence/{evidence_id}", headers=headers)

    def approve_evidence(self, evidence_id, headers):
        return self._request("POST", f"/evidence/{evidence_id}/approve", {}, headers)

    def reject_evidence(self, evidence_id, headers):
        return self._request("POST", f"/evidence/{evidence_id}/reject", {}, headers)

    # ─── Reports ──────────────────────────────────────────────────────────
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def publish_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/publish", {}, headers)

    def retract_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/retract", {}, headers)

    # ─── Audit log (tamper-evident read) ──────────────────────────────────
    def list_audit_log(self, headers, params=None):
        return self._request("GET", "/audit-log", headers=headers, params=params)

    def get_audit_log_entry(self, entry_id, headers):
        return self._request("GET", f"/audit-log/{entry_id}", headers=headers)

    # ─── Logical clock (admin test-driving) ───────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
