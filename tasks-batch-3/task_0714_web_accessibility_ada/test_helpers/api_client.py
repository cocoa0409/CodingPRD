"""API client: one method per endpoint defined in the PRD. All paths under /compliance."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/compliance"


class ApiClient(GenericApiClient):
    # ─── Organizations ────────────────────────────────────────────────
    def create_organization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"{PREFIX}/organizations/{org_id}", headers=headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations", headers=headers, params=params)

    # ─── Subscriptions ────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"{PREFIX}/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subscriptions", headers=headers, params=params)

    def activate_subscription(self, sub_id, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions/{sub_id}/activate", payload, headers)

    def mark_past_due_subscription(self, sub_id, headers):
        return self._request("POST", f"{PREFIX}/subscriptions/{sub_id}/mark-past-due", headers=headers)

    def suspend_subscription(self, sub_id, headers):
        return self._request("POST", f"{PREFIX}/subscriptions/{sub_id}/suspend", headers=headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"{PREFIX}/subscriptions/{sub_id}/cancel", headers=headers)

    # ─── Sites ────────────────────────────────────────────────────────
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site_risk_projection(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}/risk-projection", headers=headers)

    # ─── Scans ────────────────────────────────────────────────────────
    def create_scan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/scans", payload, headers)

    def get_scan(self, scan_id, headers):
        return self._request("GET", f"{PREFIX}/scans/{scan_id}", headers=headers)

    def list_scans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/scans", headers=headers, params=params)

    def start_scan(self, scan_id, headers):
        return self._request("POST", f"{PREFIX}/scans/{scan_id}/start", headers=headers)

    def complete_scan(self, scan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/scans/{scan_id}/complete", payload, headers)

    def fail_scan(self, scan_id, headers):
        return self._request("POST", f"{PREFIX}/scans/{scan_id}/fail", headers=headers)

    def cancel_scan(self, scan_id, headers):
        return self._request("POST", f"{PREFIX}/scans/{scan_id}/cancel", headers=headers)

    # ─── Findings ─────────────────────────────────────────────────────
    def get_finding(self, finding_id, headers):
        return self._request("GET", f"{PREFIX}/findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/findings", headers=headers, params=params)

    def accept_risk_finding(self, finding_id, headers):
        return self._request("POST", f"{PREFIX}/findings/{finding_id}/accept-risk", headers=headers)

    # ─── Remediation tasks ────────────────────────────────────────────
    def create_remediation_task(self, payload, headers):
        return self._request("POST", f"{PREFIX}/remediation-tasks", payload, headers)

    def get_remediation_task(self, task_id, headers):
        return self._request("GET", f"{PREFIX}/remediation-tasks/{task_id}", headers=headers)

    def list_remediation_tasks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/remediation-tasks", headers=headers, params=params)

    def begin_remediation_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/remediation-tasks/{task_id}/begin", headers=headers)

    def submit_remediation_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/remediation-tasks/{task_id}/submit", headers=headers)

    # ─── Retest runs ──────────────────────────────────────────────────
    def create_retest_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retest-runs", payload, headers)

    def get_retest_run(self, retest_id, headers):
        return self._request("GET", f"{PREFIX}/retest-runs/{retest_id}", headers=headers)

    def list_retest_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/retest-runs", headers=headers, params=params)

    # ─── VPAT reports ─────────────────────────────────────────────────
    def create_vpat_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vpat-reports", payload, headers)

    def get_vpat_report(self, vpat_id, headers):
        return self._request("GET", f"{PREFIX}/vpat-reports/{vpat_id}", headers=headers)

    def list_vpat_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vpat-reports", headers=headers, params=params)

    def issue_vpat_report(self, vpat_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vpat-reports/{vpat_id}/issue", payload, headers)

    def revoke_vpat_report(self, vpat_id, headers):
        return self._request("POST", f"{PREFIX}/vpat-reports/{vpat_id}/revoke", headers=headers)

    # ─── Legal demands ────────────────────────────────────────────────
    def create_legal_demand(self, payload, headers):
        return self._request("POST", f"{PREFIX}/legal-demands", payload, headers)

    def get_legal_demand(self, ld_id, headers):
        return self._request("GET", f"{PREFIX}/legal-demands/{ld_id}", headers=headers)

    def list_legal_demands(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/legal-demands", headers=headers, params=params)

    def respond_legal_demand(self, ld_id, headers):
        return self._request("POST", f"{PREFIX}/legal-demands/{ld_id}/respond", headers=headers)

    def escalate_legal_demand(self, ld_id, headers):
        return self._request("POST", f"{PREFIX}/legal-demands/{ld_id}/escalate", headers=headers)

    def resolve_legal_demand(self, ld_id, headers):
        return self._request("POST", f"{PREFIX}/legal-demands/{ld_id}/resolve", headers=headers)

    def dismiss_legal_demand(self, ld_id, headers):
        return self._request("POST", f"{PREFIX}/legal-demands/{ld_id}/dismiss", headers=headers)

    # ─── Monitoring ───────────────────────────────────────────────────
    def create_monitoring_check(self, payload, headers):
        return self._request("POST", f"{PREFIX}/monitoring-checks", payload, headers)

    def get_monitoring_check(self, mc_id, headers):
        return self._request("GET", f"{PREFIX}/monitoring-checks/{mc_id}", headers=headers)

    def list_monitoring_checks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/monitoring-checks", headers=headers, params=params)

    # ─── Training ─────────────────────────────────────────────────────
    def create_training_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-enrollments", payload, headers)

    def get_training_enrollment(self, enr_id, headers):
        return self._request("GET", f"{PREFIX}/training-enrollments/{enr_id}", headers=headers)

    def list_training_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/training-enrollments", headers=headers, params=params)

    def start_training_enrollment(self, enr_id, headers):
        return self._request("POST", f"{PREFIX}/training-enrollments/{enr_id}/start", headers=headers)

    def complete_training_enrollment(self, enr_id, payload, headers):
        return self._request("POST", f"{PREFIX}/training-enrollments/{enr_id}/complete", payload, headers)

    def expire_training_enrollment(self, enr_id, headers):
        return self._request("POST", f"{PREFIX}/training-enrollments/{enr_id}/expire", headers=headers)

    # ─── Certifications ───────────────────────────────────────────────
    def create_certification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"{PREFIX}/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/certifications", headers=headers, params=params)

    def revoke_certification(self, cert_id, headers):
        return self._request("POST", f"{PREFIX}/certifications/{cert_id}/revoke", headers=headers)

    def expire_certification(self, cert_id, headers):
        return self._request("POST", f"{PREFIX}/certifications/{cert_id}/expire", headers=headers)

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", f"{PREFIX}/_clock/now", headers=headers)


api_client = ApiClient()
