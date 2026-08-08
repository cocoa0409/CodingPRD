"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- BrokerUser ---
    def create_broker_user(self, payload, headers):
        return self._request("POST", "/broker-users", payload, headers=headers)

    def get_broker_user(self, broker_user_id, headers):
        return self._request("GET", f"/broker-users/{broker_user_id}", headers=headers)

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers=headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def set_supplier_status(self, supplier_id, payload, headers):
        return self._request("POST", f"/suppliers/{supplier_id}/set-status", payload, headers=headers)

    # --- UtilityAccount ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers=headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def verify_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/verify", {}, headers=headers)

    # --- Authorization ---
    def create_authorization(self, payload, headers):
        return self._request("POST", "/authorizations", payload, headers=headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def sign_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/sign", {}, headers=headers)

    def revoke_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/revoke", {}, headers=headers)

    # --- UsageRecord ---
    def create_usage_record(self, payload, headers):
        return self._request("POST", "/usage-records", payload, headers=headers)

    def get_usage_record(self, usage_record_id, headers):
        return self._request("GET", f"/usage-records/{usage_record_id}", headers=headers)

    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/usage-records", headers=headers, params=params)

    # --- Rfp ---
    def create_rfp(self, payload, headers):
        return self._request("POST", "/rfps", payload, headers=headers)

    def get_rfp(self, rfp_id, headers):
        return self._request("GET", f"/rfps/{rfp_id}", headers=headers)

    def list_rfps(self, headers, params=None):
        return self._request("GET", "/rfps", headers=headers, params=params)

    def transition_rfp(self, rfp_id, payload, headers):
        return self._request("POST", f"/rfps/{rfp_id}/transition", payload, headers=headers)

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers=headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def shortlist_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/shortlist", {}, headers=headers)

    def withdraw_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/withdraw", {}, headers=headers)

    # --- Contract ---
    def award_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers=headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def customer_decision(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/customer-decision", payload, headers=headers)

    def approve_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/approve", {}, headers=headers)

    def submit_enrollment(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/submit-enrollment", {}, headers=headers)

    def enrollment_result(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/enrollment-result", payload, headers=headers)

    def add_rec_rider(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/add-rec-rider", payload, headers=headers)

    def renew_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/renew", payload, headers=headers)

    # --- CommissionStatement ---
    def get_commission_statement(self, statement_id, headers):
        return self._request("GET", f"/commission-statements/{statement_id}", headers=headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/commission-statements", headers=headers, params=params)

    def approve_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/approve", {}, headers=headers)

    def true_up_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/true-up", {}, headers=headers)

    # --- DemandResponseEnrollment ---
    def create_dr_enrollment(self, payload, headers):
        return self._request("POST", "/dr-enrollments", payload, headers=headers)

    def get_dr_enrollment(self, dr_id, headers):
        return self._request("GET", f"/dr-enrollments/{dr_id}", headers=headers)

    def list_dr_enrollments(self, headers, params=None):
        return self._request("GET", "/dr-enrollments", headers=headers, params=params)

    def activate_dr(self, dr_id, headers):
        return self._request("POST", f"/dr-enrollments/{dr_id}/activate", {}, headers=headers)

    def record_dr_performance(self, dr_id, payload, headers):
        return self._request("POST", f"/dr-enrollments/{dr_id}/record-performance", payload, headers=headers)

    def settle_dr(self, dr_id, headers):
        return self._request("POST", f"/dr-enrollments/{dr_id}/settle", {}, headers=headers)

    def withdraw_dr(self, dr_id, headers):
        return self._request("POST", f"/dr-enrollments/{dr_id}/withdraw", {}, headers=headers)

    # --- Reporting & operations ---
    def commission_summary(self, headers, params=None):
        return self._request("GET", "/reports/commission-summary", headers=headers, params=params)

    def record_market_rate(self, payload, headers):
        return self._request("POST", "/operations/record-market-rate", payload, headers=headers)

    def run_scheduled(self, headers):
        return self._request("POST", "/operations/run-scheduled", {}, headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
