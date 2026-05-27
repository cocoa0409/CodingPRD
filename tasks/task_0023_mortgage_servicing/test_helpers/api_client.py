"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Borrowers ───────────────────────────────────────────────────
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def list_borrower_loans(self, borrower_id, headers, params=None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/loans",
            headers=headers, params=params,
        )

    # ── Loans ───────────────────────────────────────────────────────
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def post_payment(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/payments", payload, headers,
        )

    def list_loan_payments(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/payments",
            headers=headers, params=params,
        )

    def file_foreclosure(self, loan_id, expected_loan_version, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/foreclosure",
            {"expected_loan_version": expected_loan_version},
            headers,
        )

    def list_loan_foreclosure_cases(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/foreclosure-cases",
            headers=headers, params=params,
        )

    # ── Forbearance plans ───────────────────────────────────────────
    def create_forbearance_plan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/forbearance-plans", payload, headers,
        )

    def list_loan_forbearance_plans(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/forbearance-plans",
            headers=headers, params=params,
        )

    def activate_forbearance_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/forbearance-plans/{plan_id}/activate", {}, headers,
        )

    def complete_forbearance_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/forbearance-plans/{plan_id}/complete", {}, headers,
        )

    def terminate_forbearance_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/forbearance-plans/{plan_id}/terminate", {}, headers,
        )

    def get_forbearance_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/forbearance-plans/{plan_id}", headers=headers,
        )

    # ── Escrow accounts & disbursements ─────────────────────────────
    def create_escrow_account(self, payload, headers):
        return self._request("POST", "/escrow-accounts", payload, headers)

    def get_escrow_account(self, escrow_id, headers):
        return self._request(
            "GET", f"/escrow-accounts/{escrow_id}", headers=headers,
        )

    def list_escrow_accounts(self, headers, params=None):
        return self._request(
            "GET", "/escrow-accounts", headers=headers, params=params,
        )

    def create_disbursement(self, escrow_id, payload, headers):
        return self._request(
            "POST", f"/escrow-accounts/{escrow_id}/disbursements",
            payload, headers,
        )

    def list_escrow_disbursements(self, escrow_id, headers, params=None):
        return self._request(
            "GET", f"/escrow-accounts/{escrow_id}/disbursements",
            headers=headers, params=params,
        )

    def get_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/escrow-disbursements/{disbursement_id}", headers=headers,
        )

    def cancel_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/escrow-disbursements/{disbursement_id}/cancel",
            {}, headers,
        )

    def run_escrow_analysis(self, escrow_id, payload, headers):
        return self._request(
            "POST", f"/escrow-accounts/{escrow_id}/analyses",
            payload, headers,
        )

    def list_escrow_account_analyses(self, escrow_id, headers, params=None):
        return self._request(
            "GET", f"/escrow-accounts/{escrow_id}/analyses",
            headers=headers, params=params,
        )

    def list_escrow_analyses(self, headers, params=None):
        return self._request(
            "GET", "/escrow-analyses", headers=headers, params=params,
        )

    def get_escrow_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"/escrow-analyses/{analysis_id}", headers=headers,
        )

    # ── PMI removal ─────────────────────────────────────────────────
    def create_pmi_removal_request(self, payload, headers):
        return self._request("POST", "/pmi-removal-requests", payload, headers)

    def list_pmi_removal_requests(self, headers, params=None):
        return self._request(
            "GET", "/pmi-removal-requests", headers=headers, params=params,
        )

    def get_pmi_removal_request(self, request_id, headers):
        return self._request(
            "GET", f"/pmi-removal-requests/{request_id}", headers=headers,
        )

    def decide_pmi_removal_request(self, request_id, headers):
        return self._request(
            "POST", f"/pmi-removal-requests/{request_id}/decide", {}, headers,
        )

    # ── Foreclosure / mediation ─────────────────────────────────────
    def get_foreclosure_case(self, case_id, headers):
        return self._request(
            "GET", f"/foreclosure-cases/{case_id}", headers=headers,
        )

    def schedule_mediation_session(self, case_id, payload, headers):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/mediation-sessions",
            payload, headers,
        )

    def list_mediation_sessions(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/foreclosure-cases/{case_id}/mediation-sessions",
            headers=headers, params=params,
        )

    def get_mediation_session(self, session_id, headers):
        return self._request(
            "GET", f"/mediation-sessions/{session_id}", headers=headers,
        )

    def record_mediation_outcome(self, session_id, payload, headers):
        return self._request(
            "POST", f"/mediation-sessions/{session_id}/record-outcome",
            payload, headers,
        )

    def schedule_foreclosure_sale(self, case_id, payload, headers):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/schedule-sale",
            payload, headers,
        )

    def withdraw_foreclosure(self, case_id, headers):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/withdraw", {}, headers,
        )

    # ── Clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
