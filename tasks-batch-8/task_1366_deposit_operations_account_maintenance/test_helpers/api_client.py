"""API client: one method per endpoint defined in the PRD (all under /bank)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- DepositAccount ---
    def create_account(self, payload, headers):
        return self._request("POST", "/bank/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/bank/accounts/{account_id}",
                             headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/bank/accounts", headers=headers,
                             params=params)

    def close_account(self, account_id, payload, headers):
        return self._request("POST", f"/bank/accounts/{account_id}/close",
                             payload, headers)

    # --- AccountTransaction ---
    def post_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/bank/accounts/{account_id}/transactions",
                             payload, headers)

    def list_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/bank/accounts/{account_id}/transactions",
                             headers=headers, params=params)

    # --- AuthorizedSigner ---
    def add_signer(self, account_id, payload, headers):
        return self._request("POST", f"/bank/accounts/{account_id}/signers",
                             payload, headers)

    def remove_signer(self, signer_id, headers):
        return self._request("POST", f"/bank/signers/{signer_id}/remove",
                             headers=headers)

    def list_signers(self, account_id, headers, params=None):
        return self._request("GET", f"/bank/accounts/{account_id}/signers",
                             headers=headers, params=params)

    # --- AccountDocument ---
    def submit_document(self, account_id, payload, headers):
        return self._request("POST", f"/bank/accounts/{account_id}/documents",
                             payload, headers)

    def review_document(self, document_id, payload, headers):
        return self._request("POST", f"/bank/documents/{document_id}/review",
                             payload, headers)

    def list_documents(self, account_id, headers, params=None):
        return self._request("GET", f"/bank/accounts/{account_id}/documents",
                             headers=headers, params=params)

    # --- TitleChangeRequest ---
    def file_title_change(self, account_id, payload, headers):
        return self._request("POST",
                             f"/bank/accounts/{account_id}/title-changes",
                             payload, headers)

    def approve_title_change(self, request_id, headers):
        return self._request("POST",
                             f"/bank/title-changes/{request_id}/approve",
                             headers=headers)

    def reject_title_change(self, request_id, payload, headers):
        return self._request("POST",
                             f"/bank/title-changes/{request_id}/reject",
                             payload, headers)

    def resubmit_title_change(self, request_id, headers):
        return self._request("POST",
                             f"/bank/title-changes/{request_id}/resubmit",
                             headers=headers)

    def list_title_changes(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/bank/accounts/{account_id}/title-changes",
                             headers=headers, params=params)

    # --- DeceasedCase ---
    def report_deceased_case(self, account_id, payload, headers):
        return self._request("POST",
                             f"/bank/accounts/{account_id}/deceased-cases",
                             payload, headers)

    def verify_deceased_case(self, case_id, headers):
        return self._request("POST",
                             f"/bank/deceased-cases/{case_id}/verify",
                             headers=headers)

    def initiate_release(self, case_id, payload, headers):
        return self._request("POST",
                             f"/bank/deceased-cases/{case_id}/initiate-release",
                             payload, headers)

    def approve_release(self, case_id, headers):
        return self._request("POST",
                             f"/bank/deceased-cases/{case_id}/approve-release",
                             headers=headers)

    def list_deceased_cases(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/bank/accounts/{account_id}/deceased-cases",
                             headers=headers, params=params)

    # --- GarnishmentOrder ---
    def register_garnishment(self, account_id, payload, headers):
        return self._request("POST",
                             f"/bank/accounts/{account_id}/garnishments",
                             payload, headers)

    def resolve_garnishment(self, order_id, payload, headers):
        return self._request("POST",
                             f"/bank/garnishments/{order_id}/resolve",
                             payload, headers)

    def list_garnishments(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/bank/accounts/{account_id}/garnishments",
                             headers=headers, params=params)

    # --- StatementCycle ---
    def schedule_statement_cycle(self, account_id, payload, headers):
        return self._request("POST",
                             f"/bank/accounts/{account_id}/statement-cycles",
                             payload, headers)

    def list_statement_cycles(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/bank/accounts/{account_id}/statement-cycles",
                             headers=headers, params=params)

    # --- ProductConversion ---
    def schedule_conversion(self, account_id, payload, headers):
        return self._request("POST",
                             f"/bank/accounts/{account_id}/conversions",
                             payload, headers)

    def execute_conversion(self, conversion_id, headers):
        return self._request("POST",
                             f"/bank/conversions/{conversion_id}/execute",
                             headers=headers)

    def list_conversions(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/bank/accounts/{account_id}/conversions",
                             headers=headers, params=params)

    # --- Ops run & logical clock ---
    def run_daily_sweep(self, headers):
        return self._request("POST", "/bank/ops/daily-sweep", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/bank/_clock/set_current_utc", payload,
                             headers)


api_client = ApiClient()
