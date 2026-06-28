"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock + test-driving seeders (PRD §3.12) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    def inject_monthly_wd_count(self, atm_id, monthly_wd_count, headers):
        return self._request("POST", "/_inject/atm_monthly_wd_count",
                             {"atm_id": atm_id, "monthly_wd_count": monthly_wd_count},
                             headers=headers)

    # --- Site merchants (PRD §3.1) ---
    def create_site_merchant(self, payload, headers):
        return self._request("POST", "/site-merchants", payload, headers=headers)

    def get_site_merchant(self, merchant_id, headers):
        return self._request("GET", f"/site-merchants/{merchant_id}", headers=headers)

    def suspend_site_merchant(self, merchant_id, headers):
        return self._request("POST", f"/site-merchants/{merchant_id}/suspend", headers=headers)

    # --- Vaults (PRD §3.1) ---
    def create_vault(self, payload, headers):
        return self._request("POST", "/vaults", payload, headers=headers)

    def get_vault(self, vault_id, headers):
        return self._request("GET", f"/vaults/{vault_id}", headers=headers)

    # --- Routes (PRD §3.1) ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers=headers)

    def pause_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/pause", headers=headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    # --- Locations (PRD §3.1) ---
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers=headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    # --- ATMs (PRD §3.2, §3.3) ---
    def create_atm(self, payload, headers):
        return self._request("POST", "/atms", payload, headers=headers)

    def get_atm(self, atm_id, headers):
        return self._request("GET", f"/atms/{atm_id}", headers=headers)

    def list_atms(self, headers, params=None):
        return self._request("GET", "/atms", headers=headers, params=params)

    def get_forecast(self, atm_id, headers, params=None):
        return self._request("GET", f"/atms/{atm_id}/forecast", headers=headers, params=params)

    # --- Cassettes (PRD §3.2) ---
    def create_cassette(self, atm_id, payload, headers):
        return self._request("POST", f"/atms/{atm_id}/cassettes", payload, headers=headers)

    def list_cassettes(self, atm_id, headers, params=None):
        return self._request("GET", f"/atms/{atm_id}/cassettes", headers=headers, params=params)

    # --- Transactions (PRD §3.6) ---
    def create_transaction(self, atm_id, payload, headers):
        return self._request("POST", f"/atms/{atm_id}/transactions", payload, headers=headers)

    def list_atm_transactions(self, atm_id, headers, params=None):
        return self._request("GET", f"/atms/{atm_id}/transactions", headers=headers, params=params)

    def get_transaction(self, txn_id, headers):
        return self._request("GET", f"/transactions/{txn_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    # --- Replenishment orders (PRD §3.4, §3.6, §3.7) ---
    def create_replenishment_order(self, payload, headers):
        return self._request("POST", "/replenishment-orders", payload, headers=headers)

    def get_replenishment_order(self, order_id, headers):
        return self._request("GET", f"/replenishment-orders/{order_id}", headers=headers)

    def list_replenishment_orders(self, headers, params=None):
        return self._request("GET", "/replenishment-orders", headers=headers, params=params)

    def dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/replenishment-orders/{order_id}/dispatch",
                             payload, headers=headers)

    def confirm_load(self, order_id, headers, payload=None):
        return self._request("POST", f"/replenishment-orders/{order_id}/confirm-load",
                             payload, headers=headers)

    def recall_order(self, order_id, headers):
        return self._request("POST", f"/replenishment-orders/{order_id}/recall", headers=headers)

    # --- Cash counts / reconciliation (PRD §3.6) ---
    def create_cash_count(self, atm_id, payload, headers):
        return self._request("POST", f"/atms/{atm_id}/cash-counts", payload, headers=headers)

    def list_cash_counts(self, atm_id, headers, params=None):
        return self._request("GET", f"/atms/{atm_id}/cash-counts", headers=headers, params=params)

    def close_out_cash_count(self, atm_id, cc_id, headers):
        return self._request("POST", f"/atms/{atm_id}/cash-counts/{cc_id}/close-out",
                             headers=headers)

    # --- Service tickets (PRD §3.8) ---
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers=headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def acknowledge_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/acknowledge", headers=headers)

    def resolve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/resolve", headers=headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/reopen", headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/cancel", headers=headers)

    # --- Fee disclosures (PRD §3.9) ---
    def create_fee_disclosure(self, atm_id, payload, headers):
        return self._request("POST", f"/atms/{atm_id}/fee-disclosures", payload, headers=headers)

    def list_fee_disclosures(self, atm_id, headers, params=None):
        return self._request("GET", f"/atms/{atm_id}/fee-disclosures", headers=headers, params=params)

    def approve_fee_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/fee-disclosures/{disclosure_id}/approve", headers=headers)

    def reject_fee_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/fee-disclosures/{disclosure_id}/reject", headers=headers)

    # --- Settlement runs (PRD §3.10) ---
    def create_settlement_run(self, payload, headers):
        return self._request("POST", "/settlement-runs", payload, headers=headers)

    def get_settlement_run(self, run_id, headers):
        return self._request("GET", f"/settlement-runs/{run_id}", headers=headers)

    def list_settlement_runs(self, headers, params=None):
        return self._request("GET", "/settlement-runs", headers=headers, params=params)

    def settle_run(self, run_id, headers):
        return self._request("POST", f"/settlement-runs/{run_id}/settle", headers=headers)

    # --- Commission statements (PRD §3.11) ---
    def get_commission_statement(self, statement_id, headers):
        return self._request("GET", f"/commission-statements/{statement_id}", headers=headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/commission-statements", headers=headers, params=params)

    def pay_commission_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/pay", headers=headers)

    def void_commission_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/void", headers=headers)


api_client = ApiClient()
