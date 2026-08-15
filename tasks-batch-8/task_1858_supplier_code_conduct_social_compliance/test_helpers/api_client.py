"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Code versions ---
    def create_code_version(self, payload, headers):
        return self._request("POST", "/code-versions", payload, headers)

    def get_code_version(self, code_version_id, headers):
        return self._request("GET", f"/code-versions/{code_version_id}", headers=headers)

    def transition_code_version(self, code_version_id, payload, headers):
        return self._request(
            "POST", f"/code-versions/{code_version_id}/transition", payload, headers
        )

    # --- Suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def terminate_supplier(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/terminate", payload, headers
        )

    def get_supplier_scorecard(self, supplier_id, headers):
        return self._request(
            "GET", f"/suppliers/{supplier_id}/scorecard", headers=headers
        )

    # --- Code acknowledgments ---
    def create_code_acknowledgment(self, payload, headers):
        return self._request("POST", "/code-acknowledgments", payload, headers)

    def list_code_acknowledgments(self, headers, params=None):
        return self._request(
            "GET", "/code-acknowledgments", headers=headers, params=params
        )

    def get_code_acknowledgment(self, acknowledgment_id, headers):
        return self._request(
            "GET", f"/code-acknowledgments/{acknowledgment_id}", headers=headers
        )

    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def exit_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/exit", payload, headers)

    def get_facility_scoping(self, facility_id, headers):
        return self._request(
            "GET", f"/facilities/{facility_id}/scoping", headers=headers
        )

    # --- Auditors ---
    def create_auditor(self, payload, headers):
        return self._request("POST", "/auditors", payload, headers)

    def get_auditor(self, auditor_id, headers):
        return self._request("GET", f"/auditors/{auditor_id}", headers=headers)

    def deactivate_auditor(self, auditor_id, headers):
        return self._request("POST", f"/auditors/{auditor_id}/deactivate", {}, headers)

    # --- Audits ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/start", {}, headers)

    def submit_audit_report(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/submit-report", {}, headers)

    def decide_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/decide", payload, headers)

    def cancel_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/cancel", payload, headers)

    # --- Findings ---
    def create_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/findings", payload, headers)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request(
            "GET", f"/audits/{audit_id}/findings", headers=headers, params=params
        )

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def void_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/void", payload, headers)

    # --- Corrective action plans ---
    def create_corrective_action_plan(self, payload, headers):
        return self._request("POST", "/corrective-action-plans", payload, headers)

    def list_corrective_action_plans(self, headers, params=None):
        return self._request(
            "GET", "/corrective-action-plans", headers=headers, params=params
        )

    def get_corrective_action_plan(self, cap_id, headers):
        return self._request(
            "GET", f"/corrective-action-plans/{cap_id}", headers=headers
        )

    def review_corrective_action_plan(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/review", payload, headers
        )

    def resubmit_corrective_action_plan(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/resubmit", payload, headers
        )

    def request_cap_verification(self, cap_id, headers):
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/request-verification", {}, headers
        )

    def verify_corrective_action_plan(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/verify", payload, headers
        )

    # --- Grievances ---
    def create_grievance(self, payload, headers):
        return self._request("POST", "/grievances", payload, headers)

    def list_grievances(self, headers, params=None):
        return self._request("GET", "/grievances", headers=headers, params=params)

    def get_grievance(self, grievance_id, headers):
        return self._request("GET", f"/grievances/{grievance_id}", headers=headers)

    def triage_grievance(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"/grievances/{grievance_id}/triage", payload, headers
        )

    def list_grievance_fee_reviews(self, grievance_id, headers):
        return self._request(
            "GET",
            f"/grievances/{grievance_id}/recruitment-fee-reviews",
            headers=headers,
        )

    # --- Worker interviews ---
    def create_worker_interview_record(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/audits/{audit_id}/worker-interviews", payload, headers
        )

    def list_worker_interview_records(self, audit_id, headers):
        return self._request(
            "GET", f"/audits/{audit_id}/worker-interviews", headers=headers
        )

    # --- Recruitment fee reviews & reimbursements ---
    def create_recruitment_fee_review(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/audits/{audit_id}/recruitment-fee-reviews", payload, headers
        )

    def list_audit_fee_reviews(self, audit_id, headers):
        return self._request(
            "GET", f"/audits/{audit_id}/recruitment-fee-reviews", headers=headers
        )

    def get_recruitment_fee_review(self, review_id, headers):
        return self._request(
            "GET", f"/recruitment-fee-reviews/{review_id}", headers=headers
        )

    def confirm_fee_violation(self, review_id, headers):
        return self._request(
            "POST", f"/recruitment-fee-reviews/{review_id}/confirm-violation", {}, headers
        )

    def create_reimbursement(self, review_id, payload, headers):
        return self._request(
            "POST",
            f"/recruitment-fee-reviews/{review_id}/reimbursements",
            payload,
            headers,
        )

    def list_reimbursements(self, review_id, headers, params=None):
        return self._request(
            "GET",
            f"/recruitment-fee-reviews/{review_id}/reimbursements",
            headers=headers,
            params=params,
        )

    def reverse_reimbursement(self, reimbursement_id, headers):
        return self._request(
            "POST", f"/reimbursements/{reimbursement_id}/reverse", {}, headers
        )

    # --- Mutual recognition ---
    def create_mutual_recognition_claim(self, payload, headers):
        return self._request("POST", "/mutual-recognition-claims", payload, headers)

    def list_mutual_recognition_claims(self, headers, params=None):
        return self._request(
            "GET", "/mutual-recognition-claims", headers=headers, params=params
        )

    def get_mutual_recognition_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/mutual-recognition-claims/{claim_id}", headers=headers
        )

    def decide_mutual_recognition_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/mutual-recognition-claims/{claim_id}/decide", payload, headers
        )


api_client = ApiClient()
