"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Carrier ----
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def activate_carrier(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/activate", payload, headers)

    def suspend_carrier(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/suspend", payload, headers)

    def terminate_carrier(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/terminate", payload, headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---- Producer ----
    def create_producer(self, payload, headers):
        return self._request("POST", "/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/producers/{producer_id}", headers=headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", "/producers", headers=headers, params=params)

    def deactivate_producer(self, producer_id, payload, headers):
        return self._request("POST", f"/producers/{producer_id}/deactivate", payload, headers)

    # ---- License ----
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def approve_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/approve", payload, headers)

    def activate_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/activate", payload, headers)

    def terminate_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/terminate", payload, headers)

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # ---- Policy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def bind_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/bind", payload, headers)

    def activate_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/activate", payload, headers)

    def cancel_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", payload, headers)

    def reinstate_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/reinstate", payload, headers)

    def expire_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/expire", payload, headers)

    def non_renew_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/non-renew", payload, headers)

    # ---- CommissionSplit ----
    def create_commission_split(self, payload, headers):
        return self._request("POST", "/commission-splits", payload, headers)

    def get_commission_split(self, split_id, headers):
        return self._request("GET", f"/commission-splits/{split_id}", headers=headers)

    def list_commission_splits(self, headers, params=None):
        return self._request("GET", "/commission-splits", headers=headers, params=params)

    # ---- TrustAccount + ledger ----
    def create_trust_account(self, payload, headers):
        return self._request("POST", "/trust-accounts", payload, headers)

    def get_trust_account(self, trust_account_id, headers):
        return self._request("GET", f"/trust-accounts/{trust_account_id}", headers=headers)

    def list_trust_accounts(self, headers, params=None):
        return self._request("GET", "/trust-accounts", headers=headers, params=params)

    def create_ledger_entry(self, trust_account_id, payload, headers):
        return self._request(
            "POST", f"/trust-accounts/{trust_account_id}/entries", payload, headers
        )

    def list_trust_account_entries(self, trust_account_id, headers, params=None):
        return self._request(
            "GET", f"/trust-accounts/{trust_account_id}/entries", headers=headers, params=params
        )

    def list_trust_ledger_entries(self, headers, params=None):
        return self._request("GET", "/trust-ledger-entries", headers=headers, params=params)

    def get_trust_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/trust-ledger-entries/{entry_id}", headers=headers)

    # ---- CommissionStatement ----
    def create_commission_statement(self, payload, headers):
        return self._request("POST", "/commission-statements", payload, headers)

    def get_commission_statement(self, statement_id, headers):
        return self._request("GET", f"/commission-statements/{statement_id}", headers=headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/commission-statements", headers=headers, params=params)

    def finalize_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/finalize", payload, headers
        )

    def reopen_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/reopen", payload, headers
        )

    def pay_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/pay", payload, headers
        )

    # ---- RenewalTask ----
    def create_renewal_task(self, payload, headers):
        return self._request("POST", "/renewal-tasks", payload, headers)

    def get_renewal_task(self, task_id, headers):
        return self._request("GET", f"/renewal-tasks/{task_id}", headers=headers)

    def list_renewal_tasks(self, headers, params=None):
        return self._request("GET", "/renewal-tasks", headers=headers, params=params)

    def advance_renewal_task(self, task_id, payload, headers):
        return self._request("POST", f"/renewal-tasks/{task_id}/advance", payload, headers)

    def requote_renewal_task(self, task_id, payload, headers):
        return self._request("POST", f"/renewal-tasks/{task_id}/requote", payload, headers)

    def complete_renewal_task(self, task_id, payload, headers):
        return self._request("POST", f"/renewal-tasks/{task_id}/complete", payload, headers)

    def lose_renewal_task(self, task_id, payload, headers):
        return self._request("POST", f"/renewal-tasks/{task_id}/lose", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
