"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    def list_policy_mod_revisions(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}/mod-revisions",
                             headers=headers)

    # ------------------------------------------------------------------
    # Auditors
    # ------------------------------------------------------------------
    def create_auditor(self, payload, headers):
        return self._request("POST", "/auditors", payload, headers)

    def list_auditors(self, headers, params=None):
        return self._request("GET", "/auditors", headers=headers, params=params)

    def get_auditor(self, auditor_id, headers):
        return self._request("GET", f"/auditors/{auditor_id}", headers=headers)

    def list_auditor_appointments(self, auditor_id, headers):
        return self._request("GET", f"/auditors/{auditor_id}/appointments",
                             headers=headers)

    # ------------------------------------------------------------------
    # Classification codes
    # ------------------------------------------------------------------
    def create_classification_code(self, payload, headers):
        return self._request("POST", "/classification-codes", payload, headers)

    def list_classification_codes(self, headers, params=None):
        return self._request("GET", "/classification-codes",
                             headers=headers, params=params)

    def get_classification_code(self, code_id, headers):
        return self._request("GET", f"/classification-codes/{code_id}",
                             headers=headers)

    def list_class_code_payroll_allocations(self, code_id, headers):
        return self._request(
            "GET", f"/classification-codes/{code_id}/payroll-allocations",
            headers=headers)

    def list_class_code_subcontractor_exposures(self, code_id, headers):
        return self._request(
            "GET", f"/classification-codes/{code_id}/subcontractor-exposures",
            headers=headers)

    # ------------------------------------------------------------------
    # Audit selection
    # ------------------------------------------------------------------
    def run_audit_selection(self, headers):
        return self._request("POST", "/audit-selection-runs", {}, headers)

    # ------------------------------------------------------------------
    # Audit work orders
    # ------------------------------------------------------------------
    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/audit-work-orders",
                             headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/audit-work-orders/{work_order_id}",
                             headers=headers)

    def list_work_order_reaudits(self, work_order_id, headers):
        return self._request("GET", f"/audit-work-orders/{work_order_id}/reaudits",
                             headers=headers)

    def list_work_order_mod_revisions(self, work_order_id, headers):
        return self._request("GET",
                             f"/audit-work-orders/{work_order_id}/mod-revisions",
                             headers=headers)

    def list_work_order_records_requests(self, work_order_id, headers):
        return self._request(
            "GET", f"/audit-work-orders/{work_order_id}/records-requests",
            headers=headers)

    def list_work_order_appointments(self, work_order_id, headers):
        return self._request(
            "GET", f"/audit-work-orders/{work_order_id}/appointments",
            headers=headers)

    def list_work_order_payroll_allocations(self, work_order_id, headers):
        return self._request(
            "GET", f"/audit-work-orders/{work_order_id}/payroll-allocations",
            headers=headers)

    def list_work_order_subcontractor_exposures(self, work_order_id, headers):
        return self._request(
            "GET", f"/audit-work-orders/{work_order_id}/subcontractor-exposures",
            headers=headers)

    def get_work_order_result(self, work_order_id, headers):
        return self._request("GET", f"/audit-work-orders/{work_order_id}/result",
                             headers=headers)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/audit-work-orders/{work_order_id}/assign",
                             payload, headers)

    def create_records_request(self, work_order_id, payload, headers):
        return self._request("POST",
                             f"/audit-work-orders/{work_order_id}/records-requests",
                             payload, headers)

    def create_appointment(self, work_order_id, payload, headers):
        return self._request("POST",
                             f"/audit-work-orders/{work_order_id}/appointments",
                             payload, headers)

    def create_payroll_allocation(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/audit-work-orders/{work_order_id}/payroll-allocations",
            payload, headers)

    def create_subcontractor_exposure(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/audit-work-orders/{work_order_id}/subcontractor-exposures",
            payload, headers)

    def submit_draft(self, work_order_id, headers):
        return self._request("POST",
                             f"/audit-work-orders/{work_order_id}/submit-draft",
                             {}, headers)

    def issue_result(self, work_order_id, headers):
        return self._request("POST",
                             f"/audit-work-orders/{work_order_id}/issue-result",
                             {}, headers)

    def mark_noncompliant(self, work_order_id, headers):
        return self._request("POST",
                             f"/audit-work-orders/{work_order_id}/mark-noncompliant",
                             {}, headers)

    def approve_estimated(self, work_order_id, headers):
        return self._request("POST",
                             f"/audit-work-orders/{work_order_id}/approve-estimated",
                             {}, headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"/audit-work-orders/{work_order_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Records requests
    # ------------------------------------------------------------------
    def get_records_request(self, request_id, headers):
        return self._request("GET", f"/records-requests/{request_id}",
                             headers=headers)

    def receive_records_request(self, request_id, headers):
        return self._request("POST", f"/records-requests/{request_id}/receive",
                             {}, headers)

    def waive_records_request(self, request_id, headers):
        return self._request("POST", f"/records-requests/{request_id}/waive",
                             {}, headers)

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------
    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}",
                             headers=headers)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/confirm",
                             {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete",
                             {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show",
                             {}, headers)

    # ------------------------------------------------------------------
    # Payroll allocations
    # ------------------------------------------------------------------
    def get_payroll_allocation(self, allocation_id, headers):
        return self._request("GET", f"/payroll-allocations/{allocation_id}",
                             headers=headers)

    def verify_payroll_allocation(self, allocation_id, headers):
        return self._request("POST", f"/payroll-allocations/{allocation_id}/verify",
                             {}, headers)

    def reject_payroll_allocation(self, allocation_id, headers):
        return self._request("POST", f"/payroll-allocations/{allocation_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Subcontractor exposures and certificates
    # ------------------------------------------------------------------
    def get_subcontractor_exposure(self, exposure_id, headers):
        return self._request("GET", f"/subcontractor-exposures/{exposure_id}",
                             headers=headers)

    def submit_certificate(self, exposure_id, payload, headers):
        return self._request("POST",
                             f"/subcontractor-exposures/{exposure_id}/certificates",
                             payload, headers)

    def list_exposure_certificates(self, exposure_id, headers):
        return self._request("GET",
                             f"/subcontractor-exposures/{exposure_id}/certificates",
                             headers=headers)

    def verify_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/verify",
                             {}, headers)

    def reject_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/certificates/{certificate_id}/reject",
                             payload, headers)

    # ------------------------------------------------------------------
    # Audit results and disputes
    # ------------------------------------------------------------------
    def get_audit_result(self, result_id, headers):
        return self._request("GET", f"/audit-results/{result_id}", headers=headers)

    def file_dispute(self, result_id, payload, headers):
        return self._request("POST", f"/audit-results/{result_id}/disputes",
                             payload, headers)

    def list_result_disputes(self, result_id, headers):
        return self._request("GET", f"/audit-results/{result_id}/disputes",
                             headers=headers)

    def list_result_billing_transactions(self, result_id, headers):
        return self._request("GET",
                             f"/audit-results/{result_id}/billing-transactions",
                             headers=headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def start_review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/start-review",
                             {}, headers)

    def uphold_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/uphold", {}, headers)

    def overrule_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/overrule",
                             {}, headers)

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------
    def get_billing_transaction(self, billing_id, headers):
        return self._request("GET", f"/billing-transactions/{billing_id}",
                             headers=headers)

    def record_payment(self, billing_id, payload, headers):
        return self._request("POST",
                             f"/billing-transactions/{billing_id}/record-payment",
                             payload, headers)

    # ------------------------------------------------------------------
    # Mod revisions
    # ------------------------------------------------------------------
    def apply_mod_revision(self, revision_id, headers):
        return self._request("POST", f"/mod-revisions/{revision_id}/apply",
                             {}, headers)


api_client = ApiClient()
