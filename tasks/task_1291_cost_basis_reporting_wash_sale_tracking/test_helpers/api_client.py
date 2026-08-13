"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- BrokerageFirm ---
    def create_firm(self, payload, headers):
        return self._request("POST", "/firms", payload, headers)

    def get_firm(self, firm_id, headers):
        return self._request("GET", f"/firms/{firm_id}", headers=headers)

    # --- Customer ---
    def create_customer(self, firm_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/customers", payload, headers)

    def get_customer(self, firm_id, customer_id, headers):
        return self._request("GET", f"/firms/{firm_id}/customers/{customer_id}", headers=headers)

    def list_customers(self, firm_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/customers", headers=headers, params=params)

    def suspend_customer(self, firm_id, customer_id, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, firm_id, customer_id, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/reinstate", {}, headers)

    def close_customer(self, firm_id, customer_id, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/close", {}, headers)

    # --- Account ---
    def create_account(self, firm_id, customer_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/accounts", payload, headers)

    def get_account(self, firm_id, account_id, headers):
        return self._request("GET", f"/firms/{firm_id}/accounts/{account_id}", headers=headers)

    def list_accounts(self, firm_id, customer_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/customers/{customer_id}/accounts", headers=headers, params=params)

    def restrict_account(self, firm_id, account_id, headers):
        return self._request("POST", f"/firms/{firm_id}/accounts/{account_id}/restrict", {}, headers)

    def reopen_account(self, firm_id, account_id, headers):
        return self._request("POST", f"/firms/{firm_id}/accounts/{account_id}/reopen", {}, headers)

    def close_account(self, firm_id, account_id, headers):
        return self._request("POST", f"/firms/{firm_id}/accounts/{account_id}/close", {}, headers)

    # --- Security ---
    def create_security(self, firm_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/securities", payload, headers)

    def get_security(self, firm_id, security_id, headers):
        return self._request("GET", f"/firms/{firm_id}/securities/{security_id}", headers=headers)

    def list_securities(self, firm_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/securities", headers=headers, params=params)

    # --- TaxLot ---
    def create_tax_lot(self, firm_id, account_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/accounts/{account_id}/tax_lots", payload, headers)

    def get_tax_lot(self, firm_id, lot_id, headers):
        return self._request("GET", f"/firms/{firm_id}/tax_lots/{lot_id}", headers=headers)

    def list_tax_lots(self, firm_id, account_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/accounts/{account_id}/tax_lots", headers=headers, params=params)

    def list_tax_lots_flat(self, headers, params=None):
        return self._request("GET", "/firms/tax_lots", headers=headers, params=params)

    # --- Disposition ---
    def create_disposition(self, firm_id, account_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/accounts/{account_id}/dispositions", payload, headers)

    def get_disposition(self, firm_id, disposition_id, headers):
        return self._request("GET", f"/firms/{firm_id}/dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, firm_id, account_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/accounts/{account_id}/dispositions", headers=headers, params=params)

    def settle_disposition(self, firm_id, disposition_id, headers):
        return self._request("POST", f"/firms/{firm_id}/dispositions/{disposition_id}/settle", {}, headers)

    def void_disposition(self, firm_id, disposition_id, headers):
        return self._request("POST", f"/firms/{firm_id}/dispositions/{disposition_id}/void", {}, headers)

    def correct_disposition(self, firm_id, disposition_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/dispositions/{disposition_id}/correct", payload, headers)

    def preview_gain(self, firm_id, disposition_id, headers):
        return self._request("GET", f"/firms/{firm_id}/dispositions/{disposition_id}/preview_gain", headers=headers)

    def preview_wash_sale(self, firm_id, disposition_id, headers):
        return self._request("GET", f"/firms/{firm_id}/dispositions/{disposition_id}/preview_wash_sale", headers=headers)

    # --- CorporateAction ---
    def create_corporate_action(self, firm_id, security_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/securities/{security_id}/corporate_actions", payload, headers)

    def get_corporate_action(self, firm_id, action_id, headers):
        return self._request("GET", f"/firms/{firm_id}/corporate_actions/{action_id}", headers=headers)

    def list_corporate_actions(self, firm_id, security_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/securities/{security_id}/corporate_actions", headers=headers, params=params)

    def apply_corporate_action(self, firm_id, action_id, headers):
        return self._request("POST", f"/firms/{firm_id}/corporate_actions/{action_id}/apply", {}, headers)

    def cancel_corporate_action(self, firm_id, action_id, headers):
        return self._request("POST", f"/firms/{firm_id}/corporate_actions/{action_id}/cancel", {}, headers)

    # --- TransferStatement ---
    def create_transfer_statement(self, firm_id, account_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/accounts/{account_id}/transfer_statements", payload, headers)

    def get_transfer_statement(self, firm_id, stmt_id, headers):
        return self._request("GET", f"/firms/{firm_id}/transfer_statements/{stmt_id}", headers=headers)

    def list_transfer_statements(self, firm_id, account_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/accounts/{account_id}/transfer_statements", headers=headers, params=params)

    def deliver_transfer_statement(self, firm_id, stmt_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/transfer_statements/{stmt_id}/deliver", payload, headers)

    def accept_transfer_statement(self, firm_id, stmt_id, headers):
        return self._request("POST", f"/firms/{firm_id}/transfer_statements/{stmt_id}/accept", {}, headers)

    def reject_transfer_statement(self, firm_id, stmt_id, headers):
        return self._request("POST", f"/firms/{firm_id}/transfer_statements/{stmt_id}/reject", {}, headers)

    def redeliver_transfer_statement(self, firm_id, stmt_id, headers):
        return self._request("POST", f"/firms/{firm_id}/transfer_statements/{stmt_id}/redeliver", {}, headers)

    # --- WashSaleEvent ---
    def get_wash_sale_event(self, firm_id, event_id, headers):
        return self._request("GET", f"/firms/{firm_id}/wash_sale_events/{event_id}", headers=headers)

    def list_wash_sale_events(self, firm_id, disposition_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/dispositions/{disposition_id}/wash_sale_events", headers=headers, params=params)

    # --- TaxForm1099B ---
    def create_tax_form(self, firm_id, customer_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/tax_forms_1099b", payload, headers)

    def get_tax_form(self, firm_id, customer_id, form_id, headers):
        return self._request("GET", f"/firms/{firm_id}/customers/{customer_id}/tax_forms_1099b/{form_id}", headers=headers)

    def list_tax_forms(self, firm_id, customer_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/customers/{customer_id}/tax_forms_1099b", headers=headers, params=params)

    def generate_tax_form(self, firm_id, customer_id, form_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/tax_forms_1099b/{form_id}/generate", payload, headers)

    def file_tax_form(self, firm_id, customer_id, form_id, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/tax_forms_1099b/{form_id}/file", {}, headers)

    def refile_tax_form(self, firm_id, customer_id, form_id, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/tax_forms_1099b/{form_id}/refile", {}, headers)

    # --- BasisChangeRequest ---
    def create_basis_change_request(self, firm_id, customer_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/customers/{customer_id}/basis_change_requests", payload, headers)

    def get_basis_change_request(self, firm_id, req_id, headers):
        return self._request("GET", f"/firms/{firm_id}/basis_change_requests/{req_id}", headers=headers)

    def list_basis_change_requests(self, firm_id, customer_id, headers, params=None):
        return self._request("GET", f"/firms/{firm_id}/customers/{customer_id}/basis_change_requests", headers=headers, params=params)

    def start_review_basis_request(self, firm_id, req_id, headers):
        return self._request("POST", f"/firms/{firm_id}/basis_change_requests/{req_id}/start_review", {}, headers)

    def approve_basis_request(self, firm_id, req_id, headers):
        return self._request("POST", f"/firms/{firm_id}/basis_change_requests/{req_id}/approve", {}, headers)

    def apply_basis_request(self, firm_id, req_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/basis_change_requests/{req_id}/apply", payload, headers)

    def reject_basis_request(self, firm_id, req_id, headers):
        return self._request("POST", f"/firms/{firm_id}/basis_change_requests/{req_id}/reject", {}, headers)

    def resubmit_basis_request(self, firm_id, req_id, headers):
        return self._request("POST", f"/firms/{firm_id}/basis_change_requests/{req_id}/resubmit", {}, headers)

    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
