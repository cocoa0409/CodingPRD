"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- System clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/lease-admin/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/lease-admin/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/lease-admin/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/lease-admin/properties", headers=headers, params=params)

    def get_occupancy_report(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/properties/{property_id}/occupancy-report",
            headers=headers, params=params,
        )

    # --- Lease ---
    def create_lease(self, property_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/properties/{property_id}/leases", payload, headers,
        )

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/lease-admin/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/lease-admin/leases", headers=headers, params=params)

    def list_property_leases(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/properties/{property_id}/leases",
            headers=headers, params=params,
        )

    def abstract_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/abstract", {}, headers,
        )

    def certify_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/certify", {}, headers,
        )

    def reopen_abstraction(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/reopen-abstraction", payload, headers,
        )

    def activate_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/activate", {}, headers,
        )

    def terminate_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/terminate", {}, headers,
        )

    def get_rent_roll(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/rent-roll",
            headers=headers, params=params,
        )

    # --- RentScheduleLine ---
    def create_rent_schedule_line(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/rent-schedule-lines", payload, headers,
        )

    def list_rent_schedule_lines(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/rent-schedule-lines",
            headers=headers, params=params,
        )

    def get_rent_schedule_line(self, line_id, headers):
        return self._request(
            "GET", f"/lease-admin/rent-schedule-lines/{line_id}", headers=headers,
        )

    def list_all_rent_schedule_lines(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/rent-schedule-lines", headers=headers, params=params,
        )

    # --- EscalationStep ---
    def create_escalation_step(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/escalation-steps", payload, headers,
        )

    def list_escalation_steps(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/escalation-steps",
            headers=headers, params=params,
        )

    def get_escalation_step(self, step_id, headers):
        return self._request(
            "GET", f"/lease-admin/escalation-steps/{step_id}", headers=headers,
        )

    def list_all_escalation_steps(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/escalation-steps", headers=headers, params=params,
        )

    # --- RecoveryPool ---
    def create_recovery_pool(self, property_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/properties/{property_id}/recovery-pools",
            payload, headers,
        )

    def record_pool_actuals(self, pool_id, payload, headers):
        return self._request(
            "PUT", f"/lease-admin/recovery-pools/{pool_id}/actuals", payload, headers,
        )

    def list_recovery_pools(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/properties/{property_id}/recovery-pools",
            headers=headers, params=params,
        )

    def get_recovery_pool(self, pool_id, headers):
        return self._request("GET", f"/lease-admin/recovery-pools/{pool_id}", headers=headers)

    def list_all_recovery_pools(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/recovery-pools", headers=headers, params=params,
        )

    # --- RecoveryBilling ---
    def create_recovery_billing(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/recovery-billings", payload, headers,
        )

    def list_recovery_billings(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/recovery-billings",
            headers=headers, params=params,
        )

    def get_recovery_billing(self, billing_id, headers):
        return self._request(
            "GET", f"/lease-admin/recovery-billings/{billing_id}", headers=headers,
        )

    def issue_recovery_billing(self, billing_id, headers):
        return self._request(
            "POST", f"/lease-admin/recovery-billings/{billing_id}/issue", {}, headers,
        )

    def mark_recovery_billing_paid(self, billing_id, headers):
        return self._request(
            "POST", f"/lease-admin/recovery-billings/{billing_id}/mark-paid", {}, headers,
        )

    def void_recovery_billing(self, billing_id, headers):
        return self._request(
            "POST", f"/lease-admin/recovery-billings/{billing_id}/void", {}, headers,
        )

    def list_all_recovery_billings(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/recovery-billings", headers=headers, params=params,
        )

    # --- Reconciliation ---
    def create_reconciliation(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/reconciliations", payload, headers,
        )

    def list_reconciliations(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/reconciliations",
            headers=headers, params=params,
        )

    def get_reconciliation(self, recon_id, headers):
        return self._request(
            "GET", f"/lease-admin/reconciliations/{recon_id}", headers=headers,
        )

    def post_reconciliation(self, recon_id, headers):
        return self._request(
            "POST", f"/lease-admin/reconciliations/{recon_id}/post", {}, headers,
        )

    def approve_reconciliation(self, recon_id, headers):
        return self._request(
            "POST", f"/lease-admin/reconciliations/{recon_id}/approve", {}, headers,
        )

    def close_reconciliation(self, recon_id, headers):
        return self._request(
            "POST", f"/lease-admin/reconciliations/{recon_id}/close", {}, headers,
        )

    def list_all_reconciliations(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/reconciliations", headers=headers, params=params,
        )

    # --- CriticalDate ---
    def create_critical_date(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/critical-dates", payload, headers,
        )

    def list_critical_dates(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/critical-dates",
            headers=headers, params=params,
        )

    def get_critical_date(self, cd_id, headers):
        return self._request("GET", f"/lease-admin/critical-dates/{cd_id}", headers=headers)

    def notify_critical_date(self, cd_id, headers):
        return self._request(
            "POST", f"/lease-admin/critical-dates/{cd_id}/notify", {}, headers,
        )

    def exercise_critical_date(self, cd_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/critical-dates/{cd_id}/exercise", payload, headers,
        )

    def lapse_critical_date(self, cd_id, headers):
        return self._request(
            "POST", f"/lease-admin/critical-dates/{cd_id}/lapse", {}, headers,
        )

    def waive_critical_date(self, cd_id, headers):
        return self._request(
            "POST", f"/lease-admin/critical-dates/{cd_id}/waive", {}, headers,
        )

    def list_all_critical_dates(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/critical-dates", headers=headers, params=params,
        )

    # --- ComplianceDoc ---
    def create_compliance_doc(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/compliance-docs", payload, headers,
        )

    def list_compliance_docs(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/compliance-docs",
            headers=headers, params=params,
        )

    def get_compliance_doc(self, doc_id, headers):
        return self._request("GET", f"/lease-admin/compliance-docs/{doc_id}", headers=headers)

    def start_compliance_doc_review(self, doc_id, headers):
        return self._request(
            "POST", f"/lease-admin/compliance-docs/{doc_id}/start-review", {}, headers,
        )

    def accept_compliance_doc(self, doc_id, headers):
        return self._request(
            "POST", f"/lease-admin/compliance-docs/{doc_id}/accept", {}, headers,
        )

    def reject_compliance_doc(self, doc_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/compliance-docs/{doc_id}/reject", payload, headers,
        )

    def list_all_compliance_docs(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/compliance-docs", headers=headers, params=params,
        )

    # --- Amendment ---
    def create_amendment(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/amendments", payload, headers,
        )

    def list_amendments(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/amendments",
            headers=headers, params=params,
        )

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/lease-admin/amendments/{amendment_id}", headers=headers)

    def approve_amendment(self, amendment_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/amendments/{amendment_id}/approve", payload, headers,
        )

    def apply_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/lease-admin/amendments/{amendment_id}/apply", {}, headers,
        )

    def reject_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/lease-admin/amendments/{amendment_id}/reject", {}, headers,
        )

    def list_all_amendments(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/amendments", headers=headers, params=params,
        )

    # --- TenantChallenge ---
    def create_tenant_challenge(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/tenant-challenges", payload, headers,
        )

    def list_tenant_challenges(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/tenant-challenges",
            headers=headers, params=params,
        )

    def get_tenant_challenge(self, challenge_id, headers):
        return self._request(
            "GET", f"/lease-admin/tenant-challenges/{challenge_id}", headers=headers,
        )

    def start_challenge_review(self, challenge_id, headers):
        return self._request(
            "POST", f"/lease-admin/tenant-challenges/{challenge_id}/start-review",
            {}, headers,
        )

    def reopen_challenge(self, challenge_id, headers):
        return self._request(
            "POST", f"/lease-admin/tenant-challenges/{challenge_id}/reopen", {}, headers,
        )

    def resolve_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/tenant-challenges/{challenge_id}/resolve",
            payload, headers,
        )

    def escalate_challenge(self, challenge_id, headers):
        return self._request(
            "POST", f"/lease-admin/tenant-challenges/{challenge_id}/escalate", {}, headers,
        )

    def withdraw_challenge(self, challenge_id, headers):
        return self._request(
            "POST", f"/lease-admin/tenant-challenges/{challenge_id}/withdraw", {}, headers,
        )

    def list_all_tenant_challenges(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/tenant-challenges", headers=headers, params=params,
        )

    # --- AuditRight ---
    def create_audit_right(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/leases/{lease_id}/audit-rights", payload, headers,
        )

    def list_audit_rights(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"/lease-admin/leases/{lease_id}/audit-rights",
            headers=headers, params=params,
        )

    def get_audit_right(self, audit_id, headers):
        return self._request("GET", f"/lease-admin/audit-rights/{audit_id}", headers=headers)

    def start_audit_fieldwork(self, audit_id, headers):
        return self._request(
            "POST", f"/lease-admin/audit-rights/{audit_id}/start-fieldwork", {}, headers,
        )

    def issue_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/lease-admin/audit-rights/{audit_id}/issue-findings",
            payload, headers,
        )

    def settle_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/lease-admin/audit-rights/{audit_id}/settle", {}, headers,
        )

    def list_all_audit_rights(self, headers, params=None):
        return self._request(
            "GET", "/lease-admin/audit-rights", headers=headers, params=params,
        )


api_client = ApiClient()
