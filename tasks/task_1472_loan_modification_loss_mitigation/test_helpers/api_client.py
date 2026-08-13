"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- borrowers / loans ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    # --- applications ---
    def create_application(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_loan_applications(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/applications", headers=headers, params=params
        )

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def acknowledge_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/acknowledge", headers=headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", headers=headers
        )

    # --- documents ---
    def submit_document(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/documents", payload, headers
        )

    def list_documents(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/documents", headers=headers, params=params
        )

    def accept_document(self, document_id, headers):
        return self._request("POST", f"/documents/{document_id}/accept", headers=headers)

    def reject_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"/documents/{document_id}/reject", payload, headers
        )

    # --- program options ---
    def create_program_option(self, payload, headers):
        return self._request("POST", "/program-options", payload, headers)

    def list_program_options(self, headers, params=None):
        return self._request("GET", "/program-options", headers=headers, params=params)

    def get_program_option(self, program_id, headers):
        return self._request("GET", f"/program-options/{program_id}", headers=headers)

    def retire_program_option(self, program_id, headers):
        return self._request(
            "POST", f"/program-options/{program_id}/retire", headers=headers
        )

    # --- evaluations ---
    def run_evaluation(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/evaluations", payload, headers
        )

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/evaluations", headers=headers, params=params)

    def list_application_evaluations(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/evaluations", headers=headers, params=params
        )

    def list_evaluation_steps(self, evaluation_id, headers):
        return self._request(
            "GET", f"/evaluations/{evaluation_id}/steps", headers=headers
        )

    # --- trial plans & payments ---
    def accept_trial_plan(self, plan_id, headers):
        return self._request("POST", f"/trial-plans/{plan_id}/accept", headers=headers)

    def get_trial_plan(self, plan_id, headers):
        return self._request("GET", f"/trial-plans/{plan_id}", headers=headers)

    def list_trial_plans(self, headers, params=None):
        return self._request("GET", "/trial-plans", headers=headers, params=params)

    def list_trial_payments(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/trial-plans/{plan_id}/payments", headers=headers, params=params
        )

    def pay_trial_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/trial-payments/{payment_id}/pay", payload, headers
        )

    def finalize_trial_plan(self, plan_id, headers):
        return self._request("POST", f"/trial-plans/{plan_id}/finalize", headers=headers)

    # --- permanent modification ---
    def create_modification(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/modifications", payload, headers)

    def get_modification(self, modification_id, headers):
        return self._request("GET", f"/modifications/{modification_id}", headers=headers)

    def list_modifications(self, headers, params=None):
        return self._request("GET", "/modifications", headers=headers, params=params)

    def send_modification_docs(self, modification_id, headers):
        return self._request(
            "POST", f"/modifications/{modification_id}/send-docs", headers=headers
        )

    def sign_modification(self, modification_id, headers):
        return self._request("POST", f"/modifications/{modification_id}/sign", headers=headers)

    def record_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/modifications/{modification_id}/record", headers=headers
        )

    def rescind_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/modifications/{modification_id}/rescind", headers=headers
        )

    # --- denial notices & appeals ---
    def get_denial_notice(self, notice_id, headers):
        return self._request("GET", f"/denial-notices/{notice_id}", headers=headers)

    def list_denial_notices(self, headers, params=None):
        return self._request("GET", "/denial-notices", headers=headers, params=params)

    def list_application_denial_notices(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/denial-notices", headers=headers, params=params
        )

    def submit_appeal(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/denial-notices/{notice_id}/appeals", payload, headers
        )

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def list_notice_appeals(self, notice_id, headers, params=None):
        return self._request(
            "GET", f"/denial-notices/{notice_id}/appeals", headers=headers, params=params
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decision", payload, headers)

    # --- foreclosure cases ---
    def create_foreclosure_case(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/foreclosure-cases", payload, headers
        )

    def get_foreclosure_case(self, case_id, headers):
        return self._request("GET", f"/foreclosure-cases/{case_id}", headers=headers)

    def list_loan_foreclosure_cases(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/foreclosure-cases", headers=headers, params=params
        )

    def schedule_sale(self, case_id, payload, headers):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/schedule-sale", payload, headers
        )

    def cancel_foreclosure_case(self, case_id, headers):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/cancel", headers=headers
        )

    def complete_sale(self, case_id, headers):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/complete-sale", headers=headers
        )

    # --- escrow analyses ---
    def create_escrow_analysis(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/escrow-analyses", payload, headers
        )

    def get_escrow_analysis(self, analysis_id, headers):
        return self._request("GET", f"/escrow-analyses/{analysis_id}", headers=headers)

    def list_escrow_analyses(self, headers, params=None):
        return self._request("GET", "/escrow-analyses", headers=headers, params=params)

    def list_loan_escrow_analyses(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/escrow-analyses", headers=headers, params=params
        )

    def apply_escrow_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/escrow-analyses/{analysis_id}/apply", headers=headers
        )

    def void_escrow_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/escrow-analyses/{analysis_id}/void", headers=headers
        )

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
