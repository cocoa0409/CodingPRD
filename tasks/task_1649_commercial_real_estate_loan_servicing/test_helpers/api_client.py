"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical servicing clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Borrowers
    # ------------------------------------------------------------------
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def set_payment_status(self, loan_id, to_status, headers):
        return self._request("POST", f"/loans/{loan_id}/payment-status",
                             {"to_status": to_status}, headers)

    def reinstate_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/reinstate", {}, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/properties", payload, headers)

    def list_properties(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/properties",
                             headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def appraise_property(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/appraise",
                             payload, headers)

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------
    def create_statement(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/financial-statements",
                             payload, headers)

    def list_statements(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/financial-statements",
                             headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/financial-statements/{statement_id}",
                             headers=headers)

    def review_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/financial-statements/{statement_id}/review",
                             payload, headers)

    def list_statement_assessments(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/financial-statements/{statement_id}/covenant-assessments",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Covenant assessments
    # ------------------------------------------------------------------
    def list_loan_assessments(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/covenant-assessments",
                             headers=headers, params=params)

    def waive_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/covenant-assessments/{assessment_id}/waive",
                             payload, headers)

    # ------------------------------------------------------------------
    # Reserve accounts and deposits
    # ------------------------------------------------------------------
    def create_reserve_account(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/reserve-accounts",
                             payload, headers)

    def get_reserve_account(self, reserve_account_id, headers):
        return self._request("GET", f"/reserve-accounts/{reserve_account_id}",
                             headers=headers)

    def list_reserve_accounts(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/reserve-accounts",
                             headers=headers, params=params)

    def deposit_reserve(self, reserve_account_id, amount_cents, headers):
        return self._request("POST", f"/reserve-accounts/{reserve_account_id}/deposits",
                             {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Disbursement requests
    # ------------------------------------------------------------------
    def create_disbursement_request(self, reserve_account_id, payload, headers):
        return self._request(
            "POST", f"/reserve-accounts/{reserve_account_id}/disbursement-requests",
            payload, headers)

    def list_disbursement_requests(self, reserve_account_id, headers, params=None):
        return self._request(
            "GET", f"/reserve-accounts/{reserve_account_id}/disbursement-requests",
            headers=headers, params=params)

    def review_disbursement(self, request_id, decision, headers):
        return self._request("POST", f"/disbursement-requests/{request_id}/review",
                             {"decision": decision}, headers)

    def fund_disbursement(self, request_id, headers):
        return self._request("POST", f"/disbursement-requests/{request_id}/fund",
                             {}, headers)

    def cancel_disbursement(self, request_id, headers):
        return self._request("POST", f"/disbursement-requests/{request_id}/cancel",
                             {}, headers)

    def release_retainage(self, request_id, headers):
        return self._request(
            "POST", f"/disbursement-requests/{request_id}/release-retainage",
            {}, headers)

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------
    def create_lease(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/leases",
                             payload, headers)

    def list_leases(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/leases",
                             headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def submit_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/submit", {}, headers)

    def decide_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/decide", payload, headers)

    def revise_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/revise", payload, headers)

    # ------------------------------------------------------------------
    # Estoppel certificates
    # ------------------------------------------------------------------
    def request_estoppel(self, lease_id, due_date, headers):
        return self._request("POST", f"/leases/{lease_id}/estoppels",
                             {"due_date": due_date}, headers)

    def list_estoppels(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/estoppels",
                             headers=headers, params=params)

    def execute_estoppel(self, estoppel_id, headers):
        return self._request("POST", f"/estoppels/{estoppel_id}/execute", {}, headers)

    # ------------------------------------------------------------------
    # Inspectors and inspections
    # ------------------------------------------------------------------
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def list_inspector_inspections(self, inspector_id, headers, params=None):
        return self._request("GET", f"/inspectors/{inspector_id}/inspections",
                             headers=headers, params=params)

    def schedule_inspection(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/inspections",
                             payload, headers)

    def list_inspections(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/inspections",
                             headers=headers, params=params)

    def close_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/close",
                             payload, headers)

    # ------------------------------------------------------------------
    # Insurance policies
    # ------------------------------------------------------------------
    def create_insurance_policy(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/insurance-policies",
                             payload, headers)

    def list_insurance_policies(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/insurance-policies",
                             headers=headers, params=params)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/cancel",
                             {}, headers)

    def force_place_insurance(self, property_id, coverage_type, headers):
        return self._request("POST", f"/properties/{property_id}/force-place-insurance",
                             {"coverage_type": coverage_type}, headers)

    # ------------------------------------------------------------------
    # Assumption requests
    # ------------------------------------------------------------------
    def create_assumption_request(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/assumption-requests",
                             payload, headers)

    def list_assumption_requests(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/assumption-requests",
                             headers=headers, params=params)

    def start_assumption_review(self, request_id, headers):
        return self._request("POST", f"/assumption-requests/{request_id}/start-review",
                             {}, headers)

    def decide_assumption(self, request_id, payload, headers):
        return self._request("POST", f"/assumption-requests/{request_id}/decide",
                             payload, headers)

    def execute_assumption(self, request_id, headers):
        return self._request("POST", f"/assumption-requests/{request_id}/execute",
                             {}, headers)

    def withdraw_assumption(self, request_id, headers):
        return self._request("POST", f"/assumption-requests/{request_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Extension options
    # ------------------------------------------------------------------
    def create_extension_option(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/extension-options",
                             payload, headers)

    def list_extension_options(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/extension-options",
                             headers=headers, params=params)

    def exercise_extension_option(self, option_id, headers):
        return self._request("POST", f"/extension-options/{option_id}/exercise",
                             {}, headers)

    # ------------------------------------------------------------------
    # Watchlist entries
    # ------------------------------------------------------------------
    def list_watchlist_entries(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/watchlist-entries",
                             headers=headers, params=params)

    def resolve_watchlist_entry(self, entry_id, headers):
        return self._request("POST", f"/watchlist-entries/{entry_id}/resolve",
                             {}, headers)

    def escalate_watchlist_entry(self, entry_id, headers):
        return self._request("POST", f"/watchlist-entries/{entry_id}/escalate",
                             {}, headers)


api_client = ApiClient()
