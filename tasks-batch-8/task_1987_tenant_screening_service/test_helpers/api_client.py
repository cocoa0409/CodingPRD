"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Landlords ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/api/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/api/landlords/{landlord_id}", headers=headers)

    def suspend_landlord(self, landlord_id, headers):
        return self._request("POST", f"/api/landlords/{landlord_id}/suspend", {}, headers=headers)

    # --- Jurisdiction rules ---
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/api/jurisdiction-rules", payload, headers)

    def list_jurisdiction_rules(self, headers, params=None):
        return self._request("GET", "/api/jurisdiction-rules", headers=headers, params=params)

    # --- Criteria ---
    def create_criteria(self, payload, headers):
        return self._request("POST", "/api/criteria", payload, headers)

    def list_criteria(self, headers, params=None):
        return self._request("GET", "/api/criteria", headers=headers, params=params)

    def get_criteria(self, criteria_id, headers):
        return self._request("GET", f"/api/criteria/{criteria_id}", headers=headers)

    def publish_criteria(self, criteria_id, payload, headers):
        return self._request("POST", f"/api/criteria/{criteria_id}/publish", payload, headers)

    def archive_criteria(self, criteria_id, headers):
        return self._request("POST", f"/api/criteria/{criteria_id}/archive", {}, headers=headers)

    # --- Applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/api/applicants", payload, headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/api/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/api/applications/{application_id}", headers=headers)

    def consent_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/consent", {}, headers=headers)

    def verify_identity(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/verify-identity", payload, headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/submit", {}, headers=headers)

    def record_searches(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/record-searches", payload, headers)

    def withdraw_application(self, application_id, headers, reason=None):
        payload = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"/api/applications/{application_id}/withdraw", payload, headers=headers)

    def score_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/score", {}, headers=headers)

    def decide_application(self, application_id, decision, headers):
        return self._request("POST", f"/api/applications/{application_id}/decide", {"decision": decision}, headers=headers)

    # --- Guarantors ---
    def create_guarantor(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/guarantors", payload, headers)

    def list_guarantors(self, headers, params=None):
        return self._request("GET", "/api/guarantors", headers=headers, params=params)

    def get_guarantor(self, guarantor_id, headers):
        return self._request("GET", f"/api/guarantors/{guarantor_id}", headers=headers)

    def evaluate_guarantor(self, guarantor_id, payload, headers):
        return self._request("POST", f"/api/guarantors/{guarantor_id}/evaluate", payload, headers=headers)

    # --- Income verifications ---
    def create_income_verification(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/income-verifications", payload, headers)

    def list_income_verifications(self, headers, params=None):
        return self._request("GET", "/api/income-verifications", headers=headers, params=params)

    def get_income_verification(self, verification_id, headers):
        return self._request("GET", f"/api/income-verifications/{verification_id}", headers=headers)

    def resolve_income_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/api/income-verifications/{verification_id}/resolve", payload, headers=headers)

    def retry_income_verification(self, verification_id, headers):
        return self._request("POST", f"/api/income-verifications/{verification_id}/retry", {}, headers=headers)

    # --- Reports and records ---
    def list_reports(self, headers, params=None):
        return self._request("GET", "/api/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/api/reports/{report_id}", headers=headers)

    def deliver_report(self, report_id, headers):
        return self._request("POST", f"/api/reports/{report_id}/deliver", {}, headers=headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/api/records", headers=headers, params=params)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/api/records/{record_id}", headers=headers)

    # --- Disputes ---
    def file_dispute(self, report_id, payload, headers):
        return self._request("POST", f"/api/reports/{report_id}/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/api/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/api/disputes/{dispute_id}", headers=headers)

    def start_reinvestigation(self, dispute_id, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/start-reinvestigation", {}, headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/resolve", payload, headers=headers)

    # --- Adverse action notices ---
    def list_notices(self, headers, params=None):
        return self._request("GET", "/api/adverse-action-notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/api/adverse-action-notices/{notice_id}", headers=headers)

    def issue_notice(self, notice_id, headers, reason_codes=None):
        payload = {}
        if reason_codes is not None:
            payload["reason_codes"] = reason_codes
        return self._request("POST", f"/api/adverse-action-notices/{notice_id}/issue", payload, headers=headers)

    def rescind_notice(self, notice_id, headers):
        return self._request("POST", f"/api/adverse-action-notices/{notice_id}/rescind", {}, headers=headers)

    # --- Consistency audits ---
    def run_consistency_audit(self, landlord_id, headers):
        return self._request("POST", f"/api/landlords/{landlord_id}/consistency-audits", {}, headers=headers)

    def list_consistency_audits(self, landlord_id, headers):
        return self._request("GET", f"/api/landlords/{landlord_id}/consistency-audits", headers=headers)


api_client = ApiClient()
