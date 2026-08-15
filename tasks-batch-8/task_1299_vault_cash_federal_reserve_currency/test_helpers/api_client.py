"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vault-cash/_clock/set_current_utc", payload, headers)

    # --- VaultSite ---
    def create_vault_site(self, payload, headers):
        return self._request("POST", "/vault-cash/vault-sites", payload, headers)

    def list_vault_sites(self, headers, params=None):
        return self._request("GET", "/vault-cash/vault-sites", headers=headers, params=params)

    def get_vault_site(self, site_id, headers):
        return self._request("GET", f"/vault-cash/vault-sites/{site_id}", headers=headers)

    def patch_vault_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/vault-cash/vault-sites/{site_id}", payload, headers)

    # --- StaffMember ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/vault-cash/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/vault-cash/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/vault-cash/staff-members/{staff_id}", headers=headers)

    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/vault-cash/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/vault-cash/carriers", headers=headers, params=params)

    def patch_carrier(self, carrier_id, payload, headers):
        return self._request("PATCH", f"/vault-cash/carriers/{carrier_id}", payload, headers)

    # --- AtmMachine ---
    def create_atm_machine(self, payload, headers):
        return self._request("POST", "/vault-cash/atm-machines", payload, headers)

    def list_atm_machines(self, headers, params=None):
        return self._request("GET", "/vault-cash/atm-machines", headers=headers, params=params)

    def get_atm_machine(self, atm_id, headers):
        return self._request("GET", f"/vault-cash/atm-machines/{atm_id}", headers=headers)

    def set_atm_service_status(self, atm_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/atm-machines/{atm_id}/set-service-status", payload, headers
        )

    # --- SeasonalWindow ---
    def create_seasonal_window(self, payload, headers):
        return self._request("POST", "/vault-cash/seasonal-windows", payload, headers)

    def list_seasonal_windows(self, headers, params=None):
        return self._request("GET", "/vault-cash/seasonal-windows", headers=headers, params=params)

    def get_seasonal_window(self, window_id, headers):
        return self._request("GET", f"/vault-cash/seasonal-windows/{window_id}", headers=headers)

    # --- FedOrder + DenominationLine ---
    def create_fed_order(self, payload, headers):
        return self._request("POST", "/vault-cash/fed-orders", payload, headers)

    def list_fed_orders(self, headers, params=None):
        return self._request("GET", "/vault-cash/fed-orders", headers=headers, params=params)

    def get_fed_order(self, order_id, headers):
        return self._request("GET", f"/vault-cash/fed-orders/{order_id}", headers=headers)

    def add_denomination_line(self, order_id, payload, headers):
        return self._request("POST", f"/vault-cash/fed-orders/{order_id}/lines", payload, headers)

    def list_denomination_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/vault-cash/fed-orders/{order_id}/lines", headers=headers, params=params
        )

    def submit_fed_order(self, order_id, headers):
        return self._request("POST", f"/vault-cash/fed-orders/{order_id}/submit", {}, headers)

    def recall_fed_order(self, order_id, headers):
        return self._request("POST", f"/vault-cash/fed-orders/{order_id}/recall", {}, headers)

    def acknowledge_fed_order(self, order_id, headers):
        return self._request("POST", f"/vault-cash/fed-orders/{order_id}/acknowledge", {}, headers)

    def cancel_fed_order(self, order_id, headers):
        return self._request("POST", f"/vault-cash/fed-orders/{order_id}/cancel", {}, headers)

    def record_fed_advice(self, order_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/fed-orders/{order_id}/record-fed-advice", payload, headers
        )

    # --- CashShipment ---
    def create_cash_shipment(self, payload, headers):
        return self._request("POST", "/vault-cash/cash-shipments", payload, headers)

    def list_cash_shipments(self, headers, params=None):
        return self._request("GET", "/vault-cash/cash-shipments", headers=headers, params=params)

    def get_cash_shipment(self, shipment_id, headers):
        return self._request("GET", f"/vault-cash/cash-shipments/{shipment_id}", headers=headers)

    def load_cash_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vault-cash/cash-shipments/{shipment_id}/load", {}, headers)

    def depart_cash_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vault-cash/cash-shipments/{shipment_id}/depart", {}, headers)

    def verify_cash_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/cash-shipments/{shipment_id}/verify", payload, headers
        )

    def cancel_cash_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vault-cash/cash-shipments/{shipment_id}/cancel", {}, headers)

    # --- FitnessBatch ---
    def create_fitness_batch(self, payload, headers):
        return self._request("POST", "/vault-cash/fitness-batches", payload, headers)

    def list_fitness_batches(self, headers, params=None):
        return self._request("GET", "/vault-cash/fitness-batches", headers=headers, params=params)

    def get_fitness_batch(self, batch_id, headers):
        return self._request("GET", f"/vault-cash/fitness-batches/{batch_id}", headers=headers)

    def record_sort_results(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/fitness-batches/{batch_id}/sort-results", payload, headers
        )

    def settle_fitness_batch(self, batch_id, headers):
        return self._request("POST", f"/vault-cash/fitness-batches/{batch_id}/settle", {}, headers)

    def reopen_fitness_batch(self, batch_id, headers):
        return self._request("POST", f"/vault-cash/fitness-batches/{batch_id}/reopen", {}, headers)

    # --- CounterfeitCase ---
    def create_counterfeit_case(self, payload, headers):
        return self._request("POST", "/vault-cash/counterfeit-cases", payload, headers)

    def list_counterfeit_cases(self, headers, params=None):
        return self._request("GET", "/vault-cash/counterfeit-cases", headers=headers, params=params)

    def get_counterfeit_case(self, case_id, headers):
        return self._request("GET", f"/vault-cash/counterfeit-cases/{case_id}", headers=headers)

    def seize_counterfeit_case(self, case_id, headers):
        return self._request("POST", f"/vault-cash/counterfeit-cases/{case_id}/seize", {}, headers)

    def report_counterfeit_case(self, case_id, headers):
        return self._request("POST", f"/vault-cash/counterfeit-cases/{case_id}/report", {}, headers)

    def release_counterfeit_case(self, case_id, headers):
        return self._request("POST", f"/vault-cash/counterfeit-cases/{case_id}/release", {}, headers)

    def settle_counterfeit_case(self, case_id, headers):
        return self._request("POST", f"/vault-cash/counterfeit-cases/{case_id}/settle", {}, headers)

    # --- CashLedgerEntry ---
    def create_cash_ledger_entry(self, payload, headers):
        return self._request("POST", "/vault-cash/cash-ledger-entries", payload, headers)

    def list_cash_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/vault-cash/cash-ledger-entries", headers=headers, params=params
        )

    def get_cash_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/vault-cash/cash-ledger-entries/{entry_id}", headers=headers)

    # --- Reconciliation ---
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/vault-cash/reconciliations", payload, headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/vault-cash/reconciliations", headers=headers, params=params)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/vault-cash/reconciliations/{recon_id}", headers=headers)

    def count_reconciliation(self, recon_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/reconciliations/{recon_id}/count", payload, headers
        )

    def escalate_reconciliation(self, recon_id, headers):
        return self._request(
            "POST", f"/vault-cash/reconciliations/{recon_id}/escalate", {}, headers
        )

    def approve_reconciliation(self, recon_id, headers):
        return self._request(
            "POST", f"/vault-cash/reconciliations/{recon_id}/approve", {}, headers
        )

    def lock_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/vault-cash/reconciliations/{recon_id}/lock", {}, headers)

    # --- AtmForecast ---
    def create_atm_forecast(self, payload, headers):
        return self._request("POST", "/vault-cash/atm-forecasts", payload, headers)

    def list_atm_forecasts(self, headers, params=None):
        return self._request("GET", "/vault-cash/atm-forecasts", headers=headers, params=params)

    def get_atm_forecast(self, forecast_id, headers):
        return self._request("GET", f"/vault-cash/atm-forecasts/{forecast_id}", headers=headers)

    def publish_atm_forecast(self, forecast_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/atm-forecasts/{forecast_id}/publish", payload, headers
        )

    def load_atm_forecast(self, forecast_id, headers):
        return self._request("POST", f"/vault-cash/atm-forecasts/{forecast_id}/load", {}, headers)

    def settle_atm_forecast(self, forecast_id, payload, headers):
        return self._request(
            "POST", f"/vault-cash/atm-forecasts/{forecast_id}/settle", payload, headers
        )


api_client = ApiClient()
