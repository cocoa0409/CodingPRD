"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/etc/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/etc/accounts/{account_id}", headers=headers)

    def credit_account(self, account_id, payload, headers):
        return self._request("POST", f"/etc/accounts/{account_id}/credit", payload, headers)

    def suspend_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/etc/accounts/{account_id}/suspend", payload or {}, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/etc/accounts/{account_id}/reinstate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/etc/accounts/{account_id}/close", {}, headers)

    def list_account_ledger_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/etc/accounts/{account_id}/ledger-entries",
                             headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/etc/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/etc/ledger-entries", headers=headers, params=params)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/etc/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/etc/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/etc/vehicles", headers=headers, params=params)

    def lapse_vehicle_registration(self, vehicle_id, headers):
        return self._request("POST", f"/etc/vehicles/{vehicle_id}/lapse-registration", {}, headers)

    # --- Transponder ---
    def create_transponder(self, payload, headers):
        return self._request("POST", "/etc/transponders", payload, headers)

    def get_transponder(self, transponder_id, headers):
        return self._request("GET", f"/etc/transponders/{transponder_id}", headers=headers)

    def list_transponders(self, headers, params=None):
        return self._request("GET", "/etc/transponders", headers=headers, params=params)

    # --- TransponderBinding ---
    def create_transponder_binding(self, payload, headers):
        return self._request("POST", "/etc/transponder-bindings", payload, headers)

    def get_transponder_binding(self, binding_id, headers):
        return self._request("GET", f"/etc/transponder-bindings/{binding_id}", headers=headers)

    def list_transponder_bindings(self, headers, params=None):
        return self._request("GET", "/etc/transponder-bindings", headers=headers, params=params)

    def end_transponder_binding(self, binding_id, headers):
        return self._request("POST", f"/etc/transponder-bindings/{binding_id}/end", {}, headers)

    # --- HovWindow ---
    def create_hov_window(self, payload, headers):
        return self._request("POST", "/etc/hov-windows", payload, headers)

    def get_hov_window(self, window_id, headers):
        return self._request("GET", f"/etc/hov-windows/{window_id}", headers=headers)

    def list_hov_windows(self, headers, params=None):
        return self._request("GET", "/etc/hov-windows", headers=headers, params=params)

    def revoke_hov_window(self, window_id, headers):
        return self._request("POST", f"/etc/hov-windows/{window_id}/revoke", {}, headers)

    # --- Plaza ---
    def create_plaza(self, payload, headers):
        return self._request("POST", "/etc/plazas", payload, headers)

    def get_plaza(self, plaza_id, headers):
        return self._request("GET", f"/etc/plazas/{plaza_id}", headers=headers)

    def list_plaza_toll_transactions(self, plaza_id, headers, params=None):
        return self._request("GET", f"/etc/plazas/{plaza_id}/toll-transactions",
                             headers=headers, params=params)

    # --- TollTransaction ---
    def create_toll_transaction(self, payload, headers):
        return self._request("POST", "/etc/toll-transactions", payload, headers)

    def get_toll_transaction(self, txn_id, headers):
        return self._request("GET", f"/etc/toll-transactions/{txn_id}", headers=headers)

    def list_toll_transactions(self, headers, params=None):
        return self._request("GET", "/etc/toll-transactions", headers=headers, params=params)

    def price_toll_transaction(self, txn_id, headers):
        return self._request("POST", f"/etc/toll-transactions/{txn_id}/price", {}, headers)

    def reprice_toll_transaction(self, txn_id, payload, headers):
        return self._request("POST", f"/etc/toll-transactions/{txn_id}/reprice", payload, headers)

    def settle_toll_transaction(self, txn_id, headers):
        return self._request("POST", f"/etc/toll-transactions/{txn_id}/settle", {}, headers)

    def create_batch_trip(self, payload, headers):
        return self._request("POST", "/etc/toll-transactions/batch-trip", payload, headers)

    # --- Violation ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/etc/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/etc/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/etc/violations", headers=headers, params=params)

    def contest_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/etc/violations/{violation_id}/contest", payload, headers)

    def accept_dispute(self, violation_id, headers):
        return self._request("POST", f"/etc/violations/{violation_id}/accept-dispute", {}, headers)

    def reject_dispute(self, violation_id, headers):
        return self._request("POST", f"/etc/violations/{violation_id}/reject-dispute", {}, headers)

    def pay_violation(self, violation_id, headers):
        return self._request("POST", f"/etc/violations/{violation_id}/pay", {}, headers)

    # --- InteropAgency ---
    def create_interop_agency(self, payload, headers):
        return self._request("POST", "/etc/interop-agencies", payload, headers)

    def get_interop_agency(self, agency_id, headers):
        return self._request("GET", f"/etc/interop-agencies/{agency_id}", headers=headers)


api_client = ApiClient()
