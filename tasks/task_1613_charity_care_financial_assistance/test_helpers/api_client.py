"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/charity-care/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/charity-care/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/charity-care/policies/{policy_id}", headers=headers)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/charity-care/policies/{policy_id}/activate", {}, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/charity-care/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/charity-care/patients/{patient_id}", headers=headers)

    def list_patient_accounts(self, patient_id, headers):
        return self._request("GET", f"/charity-care/patients/{patient_id}/accounts", headers=headers)

    def list_patient_applications(self, patient_id, headers):
        return self._request(
            "GET", f"/charity-care/patients/{patient_id}/applications", headers=headers
        )

    # ------------------------------------------------------------------
    # Accounts / ledger
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/charity-care/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/charity-care/accounts/{account_id}", headers=headers)

    def issue_statement(self, account_id, headers):
        return self._request("POST", f"/charity-care/accounts/{account_id}/statements", {}, headers)

    def post_payment(self, account_id, payload, headers):
        return self._request("POST", f"/charity-care/accounts/{account_id}/payments", payload, headers)

    def list_payments(self, account_id, headers):
        return self._request("GET", f"/charity-care/accounts/{account_id}/payments", headers=headers)

    def post_adjustment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/accounts/{account_id}/adjustments", payload, headers
        )

    def list_account_adjustments(self, account_id, headers):
        return self._request(
            "GET", f"/charity-care/accounts/{account_id}/adjustments", headers=headers
        )

    def issue_notice(self, account_id, payload, headers):
        return self._request("POST", f"/charity-care/accounts/{account_id}/notices", payload, headers)

    def list_account_notices(self, account_id, headers):
        return self._request("GET", f"/charity-care/accounts/{account_id}/notices", headers=headers)

    def create_collection_action(self, account_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/accounts/{account_id}/collection-actions", payload, headers
        )

    def list_collection_actions(self, account_id, headers):
        return self._request(
            "GET", f"/charity-care/accounts/{account_id}/collection-actions", headers=headers
        )

    def evaluate_posture(self, account_id, headers):
        return self._request(
            "POST", f"/charity-care/accounts/{account_id}/evaluate-posture", {}, headers
        )

    # ------------------------------------------------------------------
    # Collection actions
    # ------------------------------------------------------------------
    def halt_collection_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/collection-actions/{action_id}/halt", payload, headers
        )

    def complete_collection_action(self, action_id, headers):
        return self._request(
            "POST", f"/charity-care/collection-actions/{action_id}/complete", {}, headers
        )

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/charity-care/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/charity-care/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/charity-care/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/submit", {}, headers
        )

    def withdraw_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def begin_review(self, application_id, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/begin-review", {}, headers
        )

    def request_documents(self, application_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/request-documents",
            payload, headers,
        )

    def resume_review(self, application_id, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/resume-review", {}, headers
        )

    def expire_application(self, application_id, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/expire", {}, headers
        )

    def add_member(self, application_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/members", payload, headers
        )

    def list_members(self, application_id, headers):
        return self._request(
            "GET", f"/charity-care/applications/{application_id}/members", headers=headers
        )

    def upload_document(self, application_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/documents", payload, headers
        )

    def list_application_notices(self, application_id, headers):
        return self._request(
            "GET", f"/charity-care/applications/{application_id}/notices", headers=headers
        )

    def run_presumptive_screening(self, application_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/applications/{application_id}/presumptive-screening",
            payload, headers,
        )

    def get_presumptive_screening(self, application_id, headers):
        return self._request(
            "GET", f"/charity-care/applications/{application_id}/presumptive-screening",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def get_document(self, document_id, headers):
        return self._request("GET", f"/charity-care/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/charity-care/documents", headers=headers, params=params)

    def verify_document(self, document_id, headers):
        return self._request("POST", f"/charity-care/documents/{document_id}/verify", {}, headers)

    def reject_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"/charity-care/documents/{document_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Determinations
    # ------------------------------------------------------------------
    def create_determination(self, payload, headers):
        return self._request("POST", "/charity-care/determinations", payload, headers)

    def list_determinations(self, headers, params=None):
        return self._request("GET", "/charity-care/determinations", headers=headers, params=params)

    def get_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/charity-care/determinations/{determination_id}", headers=headers
        )

    def finalize_determination(self, determination_id, headers):
        return self._request(
            "POST", f"/charity-care/determinations/{determination_id}/finalize", {}, headers
        )

    def reverse_determination(self, determination_id, headers, payload=None):
        return self._request(
            "POST", f"/charity-care/determinations/{determination_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    def list_determination_adjustments(self, determination_id, headers):
        return self._request(
            "GET", f"/charity-care/determinations/{determination_id}/adjustments", headers=headers
        )

    # ------------------------------------------------------------------
    # Adjustments
    # ------------------------------------------------------------------
    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/charity-care/adjustments/{adjustment_id}", headers=headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/charity-care/adjustments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Community benefit reports
    # ------------------------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/charity-care/community-benefit-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request(
            "GET", f"/charity-care/community-benefit-reports/{report_id}", headers=headers
        )

    def file_report(self, report_id, headers):
        return self._request(
            "POST", f"/charity-care/community-benefit-reports/{report_id}/file", {}, headers
        )

    def reopen_report(self, report_id, headers):
        return self._request(
            "POST", f"/charity-care/community-benefit-reports/{report_id}/reopen", {}, headers
        )

    def recompute_report(self, report_id, headers):
        return self._request(
            "POST", f"/charity-care/community-benefit-reports/{report_id}/recompute", {}, headers
        )


api_client = ApiClient()
