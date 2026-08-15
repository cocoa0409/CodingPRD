"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- OverdraftProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/v1/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/resume", {}, headers)

    # --- DepositAccount ---
    def create_account(self, payload, headers):
        return self._request("POST", "/v1/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/v1/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/v1/accounts/{account_id}", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/v1/accounts/{account_id}/close", {}, headers)

    # --- OptInElection ---
    def create_opt_in_election(self, account_id, payload, headers):
        return self._request(
            "POST", f"/v1/accounts/{account_id}/opt-in-election", payload, headers)

    def list_opt_in_elections(self, headers, params=None):
        return self._request("GET", "/v1/opt-in-elections", headers=headers, params=params)

    def get_opt_in_election(self, election_id, headers):
        return self._request("GET", f"/v1/opt-in-elections/{election_id}", headers=headers)

    def revoke_opt_in_election(self, election_id, headers):
        return self._request(
            "POST", f"/v1/opt-in-elections/{election_id}/revoke", {}, headers)

    def reinstate_opt_in_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"/v1/opt-in-elections/{election_id}/reinstate", payload, headers)

    # --- AccountTransaction ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/v1/transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/v1/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/v1/transactions/{transaction_id}", headers=headers)

    def reverse_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"/v1/transactions/{transaction_id}/reverse", {}, headers)

    # --- PostingBatch ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/v1/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/v1/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/v1/batches/{batch_id}", headers=headers)

    def seal_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/seal", {}, headers)

    def settle_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/settle", {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/cancel", {}, headers)

    # --- OverdraftFee (read-only) ---
    def list_fees(self, headers, params=None):
        return self._request("GET", "/v1/fees", headers=headers, params=params)

    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/v1/fees/{fee_id}", headers=headers)

    # --- FeeWaiverRequest ---
    def create_fee_waiver_request(self, payload, headers):
        return self._request("POST", "/v1/fee-waiver-requests", payload, headers)

    def list_fee_waiver_requests(self, headers, params=None):
        return self._request(
            "GET", "/v1/fee-waiver-requests", headers=headers, params=params)

    def get_fee_waiver_request(self, request_id, headers):
        return self._request(
            "GET", f"/v1/fee-waiver-requests/{request_id}", headers=headers)

    def approve_fee_waiver_request(self, request_id, headers):
        return self._request(
            "POST", f"/v1/fee-waiver-requests/{request_id}/approve", {}, headers)

    def deny_fee_waiver_request(self, request_id, headers):
        return self._request(
            "POST", f"/v1/fee-waiver-requests/{request_id}/deny", {}, headers)

    def escalate_fee_waiver_request(self, request_id, headers):
        return self._request(
            "POST", f"/v1/fee-waiver-requests/{request_id}/escalate", {}, headers)

    def appeal_fee_waiver_request(self, request_id, headers):
        return self._request(
            "POST", f"/v1/fee-waiver-requests/{request_id}/appeal", {}, headers)

    # --- WaiverRequestItem (read-only) ---
    def list_waiver_items(self, headers, params=None):
        return self._request("GET", "/v1/waiver-items", headers=headers, params=params)

    def get_waiver_item(self, item_id, headers):
        return self._request("GET", f"/v1/waiver-items/{item_id}", headers=headers)

    # --- ProgramChangeNotice ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/v1/notices", payload, headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/v1/notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/v1/notices/{notice_id}", headers=headers)

    def issue_notice(self, notice_id, headers):
        return self._request("POST", f"/v1/notices/{notice_id}/issue", {}, headers)

    def activate_notice(self, notice_id, headers):
        return self._request("POST", f"/v1/notices/{notice_id}/activate", {}, headers)

    def withdraw_notice(self, notice_id, headers):
        return self._request("POST", f"/v1/notices/{notice_id}/withdraw", {}, headers)

    # --- EducationOffer ---
    def create_education_offer(self, payload, headers):
        return self._request("POST", "/v1/education-offers", payload, headers)

    def list_education_offers(self, headers, params=None):
        return self._request("GET", "/v1/education-offers", headers=headers, params=params)

    def get_education_offer(self, offer_id, headers):
        return self._request("GET", f"/v1/education-offers/{offer_id}", headers=headers)

    def accept_education_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/v1/education-offers/{offer_id}/accept", {}, headers)

    def decline_education_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/v1/education-offers/{offer_id}/decline", {}, headers)

    # --- RegulatoryReport ---
    def create_report(self, payload, headers):
        return self._request("POST", "/v1/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/v1/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/v1/reports/{report_id}", headers=headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST", f"/v1/reports/{report_id}/finalize", {}, headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/v1/reports/{report_id}/submit", {}, headers)


api_client = ApiClient()
