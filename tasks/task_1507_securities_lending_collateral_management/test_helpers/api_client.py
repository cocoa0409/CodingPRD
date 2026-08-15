"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Securities ---
    def create_security(self, payload, headers):
        return self._request("POST", "/api/securities", payload, headers)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/api/securities/{security_id}",
                             headers=headers)

    def list_securities(self, headers, params=None):
        return self._request("GET", "/api/securities",
                             headers=headers, params=params)

    def halt_security(self, security_id, headers):
        return self._request("POST", f"/api/securities/{security_id}/halt",
                             {}, headers)

    def resume_security(self, security_id, headers):
        return self._request("POST", f"/api/securities/{security_id}/resume",
                             {}, headers)

    def mark_security_price(self, security_id, payload, headers):
        return self._request("POST", f"/api/securities/{security_id}/price",
                             payload, headers)

    # --- Beneficial owners ---
    def create_beneficial_owner(self, payload, headers):
        return self._request("POST", "/api/beneficial-owners", payload,
                             headers)

    def get_beneficial_owner(self, owner_id, headers):
        return self._request("GET", f"/api/beneficial-owners/{owner_id}",
                             headers=headers)

    def list_beneficial_owners(self, headers, params=None):
        return self._request("GET", "/api/beneficial-owners",
                             headers=headers, params=params)

    def suspend_beneficial_owner(self, owner_id, headers):
        return self._request(
            "POST", f"/api/beneficial-owners/{owner_id}/suspend", {}, headers)

    def resume_beneficial_owner(self, owner_id, headers):
        return self._request(
            "POST", f"/api/beneficial-owners/{owner_id}/resume", {}, headers)

    def offboard_beneficial_owner(self, owner_id, headers):
        return self._request(
            "POST", f"/api/beneficial-owners/{owner_id}/offboard", {},
            headers)

    # --- Borrowers ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/api/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/api/borrowers/{borrower_id}",
                             headers=headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", "/api/borrowers",
                             headers=headers, params=params)

    def suspend_borrower(self, borrower_id, headers):
        return self._request("POST", f"/api/borrowers/{borrower_id}/suspend",
                             {}, headers)

    def resume_borrower(self, borrower_id, headers):
        return self._request("POST", f"/api/borrowers/{borrower_id}/resume",
                             {}, headers)

    def default_borrower(self, borrower_id, headers):
        return self._request("POST", f"/api/borrowers/{borrower_id}/default",
                             {}, headers)

    # --- Limit overrides ---
    def create_limit_override(self, borrower_id, payload, headers):
        return self._request(
            "POST", f"/api/borrowers/{borrower_id}/limit-overrides", payload,
            headers)

    def get_limit_override(self, override_id, headers):
        return self._request("GET", f"/api/limit-overrides/{override_id}",
                             headers=headers)

    def list_limit_overrides(self, headers, params=None):
        return self._request("GET", "/api/limit-overrides",
                             headers=headers, params=params)

    def approve_limit_override(self, override_id, headers):
        return self._request(
            "POST", f"/api/limit-overrides/{override_id}/approve", {},
            headers)

    def reject_limit_override(self, override_id, headers):
        return self._request(
            "POST", f"/api/limit-overrides/{override_id}/reject", {}, headers)

    # --- Lendable positions ---
    def create_lendable_position(self, payload, headers):
        return self._request("POST", "/api/lendable-positions", payload,
                             headers)

    def get_lendable_position(self, position_id, headers):
        return self._request("GET", f"/api/lendable-positions/{position_id}",
                             headers=headers)

    def list_lendable_positions(self, headers, params=None):
        return self._request("GET", "/api/lendable-positions",
                             headers=headers, params=params)

    def suspend_lendable_position(self, position_id, headers):
        return self._request(
            "POST", f"/api/lendable-positions/{position_id}/suspend", {},
            headers)

    def resume_lendable_position(self, position_id, headers):
        return self._request(
            "POST", f"/api/lendable-positions/{position_id}/resume", {},
            headers)

    # --- Borrow requests ---
    def create_borrow_request(self, payload, headers):
        return self._request("POST", "/api/borrow-requests", payload, headers)

    def get_borrow_request(self, request_id, headers):
        return self._request("GET", f"/api/borrow-requests/{request_id}",
                             headers=headers)

    def list_borrow_requests(self, headers, params=None):
        return self._request("GET", "/api/borrow-requests",
                             headers=headers, params=params)

    def cancel_borrow_request(self, request_id, headers):
        return self._request(
            "POST", f"/api/borrow-requests/{request_id}/cancel", {}, headers)

    def match_borrow_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/borrow-requests/{request_id}/match", payload,
            headers)

    # --- Loans ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/api/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/api/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/api/loans", headers=headers,
                             params=params)

    def counter_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/api/loans/{loan_id}/counter", payload,
                             headers)

    def accept_loan(self, loan_id, headers):
        return self._request("POST", f"/api/loans/{loan_id}/accept", {},
                             headers)

    def confirm_loan(self, loan_id, headers):
        return self._request("POST", f"/api/loans/{loan_id}/confirm", {},
                             headers)

    def cancel_loan(self, loan_id, headers):
        return self._request("POST", f"/api/loans/{loan_id}/cancel", {},
                             headers)

    def amend_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/api/loans/{loan_id}/amendments",
                             payload, headers)

    def return_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/api/loans/{loan_id}/returns", payload,
                             headers)

    # --- Collateral pledges ---
    def create_pledge(self, loan_id, payload, headers):
        return self._request("POST", f"/api/loans/{loan_id}/pledges", payload,
                             headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/api/pledges/{pledge_id}",
                             headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/api/pledges", headers=headers,
                             params=params)

    def substitute_pledge(self, loan_id, pledge_id, payload, headers):
        return self._request(
            "POST", f"/api/loans/{loan_id}/pledges/{pledge_id}/substitute",
            payload, headers)

    def release_pledge(self, pledge_id, headers):
        return self._request("POST", f"/api/pledges/{pledge_id}/release", {},
                             headers)

    # --- Margin calls ---
    def get_margin_call(self, call_id, headers):
        return self._request("GET", f"/api/margin-calls/{call_id}",
                             headers=headers)

    def list_margin_calls(self, headers, params=None):
        return self._request("GET", "/api/margin-calls", headers=headers,
                             params=params)

    def declare_margin_call_default(self, call_id, headers):
        return self._request(
            "POST", f"/api/margin-calls/{call_id}/declare-default", {},
            headers)

    # --- Recalls ---
    def create_recall(self, loan_id, payload, headers):
        return self._request("POST", f"/api/loans/{loan_id}/recalls", payload,
                             headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/api/recalls/{recall_id}",
                             headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/api/recalls", headers=headers,
                             params=params)

    def extend_recall(self, recall_id, payload, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/extend",
                             payload, headers)

    def cancel_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/cancel", {},
                             headers)

    def buy_in_recall(self, recall_id, payload, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/buy-in",
                             payload, headers)

    # --- Cash collateral reinvestment ---
    def create_reinvestment(self, loan_id, payload, headers):
        return self._request("POST", f"/api/loans/{loan_id}/reinvestments",
                             payload, headers)

    def get_reinvestment(self, tranche_id, headers):
        return self._request("GET", f"/api/reinvestments/{tranche_id}",
                             headers=headers)

    def list_reinvestments(self, headers, params=None):
        return self._request("GET", "/api/reinvestments", headers=headers,
                             params=params)

    def mark_reinvestment(self, tranche_id, payload, headers):
        return self._request("POST", f"/api/reinvestments/{tranche_id}/mark",
                             payload, headers)

    def unwind_reinvestment(self, tranche_id, headers):
        return self._request(
            "POST", f"/api/reinvestments/{tranche_id}/unwind", {}, headers)

    # --- Ledger ---
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{entry_id}",
                             headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers,
                             params=params)

    # --- Ops runs, period close, clock ---
    def run_mark_to_market(self, headers):
        return self._request("POST", "/api/ops/mark-to-market", {}, headers)

    def run_month_end_close(self, payload, headers):
        return self._request("POST", "/api/ops/month-end-close", payload,
                             headers)

    def get_period_close(self, period_id, headers):
        return self._request("GET", f"/api/period-closes/{period_id}",
                             headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload,
                             headers)

    # --- Regulatory reports ---
    def create_regulatory_report(self, payload, headers):
        return self._request("POST", "/api/regulatory-reports", payload,
                             headers)

    def get_regulatory_report(self, report_id, headers):
        return self._request("GET", f"/api/regulatory-reports/{report_id}",
                             headers=headers)

    def list_regulatory_reports(self, headers, params=None):
        return self._request("GET", "/api/regulatory-reports",
                             headers=headers, params=params)

    def finalize_regulatory_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/regulatory-reports/{report_id}/finalize", {},
            headers)

    def reopen_regulatory_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/regulatory-reports/{report_id}/reopen", {},
            headers)

    def file_regulatory_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/regulatory-reports/{report_id}/file", {}, headers)


api_client = ApiClient()
