"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def run_billing_cycle(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/billing-cycles", {}, headers)

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # --- Tenant ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # --- Lease ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_ledger_balance(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}/ledger-balance", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", {}, headers)

    def close_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/close", {}, headers)

    # --- Invoice ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def waive_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/waive", {}, headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # --- LedgerEntry ---
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # --- InsurancePolicy ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("DELETE", f"/insurance-policies/{policy_id}", headers=headers)

    # --- AuctionProceeding ---
    def create_auction_proceeding(self, payload, headers):
        return self._request("POST", "/auction-proceedings", payload, headers)

    def get_auction_proceeding(self, auction_id, headers):
        return self._request("GET", f"/auction-proceedings/{auction_id}", headers=headers)

    def list_auction_proceedings(self, headers, params=None):
        return self._request("GET", "/auction-proceedings", headers=headers, params=params)

    def file_lien(self, auction_id, headers):
        return self._request("POST", f"/auction-proceedings/{auction_id}/file-lien", {}, headers)

    def schedule_auction(self, auction_id, payload, headers):
        return self._request("POST", f"/auction-proceedings/{auction_id}/schedule", payload, headers)

    def complete_sale(self, auction_id, payload, headers):
        return self._request("POST", f"/auction-proceedings/{auction_id}/complete-sale", payload, headers)

    def redeem_auction(self, auction_id, headers):
        return self._request("POST", f"/auction-proceedings/{auction_id}/redeem", {}, headers)

    def cancel_auction(self, auction_id, headers):
        return self._request("POST", f"/auction-proceedings/{auction_id}/cancel", {}, headers)

    # --- TransferOrder ---
    def create_transfer_order(self, payload, headers):
        return self._request("POST", "/transfer-orders", payload, headers)

    def get_transfer_order(self, transfer_order_id, headers):
        return self._request("GET", f"/transfer-orders/{transfer_order_id}", headers=headers)

    def list_transfer_orders(self, headers, params=None):
        return self._request("GET", "/transfer-orders", headers=headers, params=params)

    def complete_transfer(self, transfer_order_id, headers):
        return self._request("POST", f"/transfer-orders/{transfer_order_id}/complete", {}, headers)

    def cancel_transfer(self, transfer_order_id, headers):
        return self._request("POST", f"/transfer-orders/{transfer_order_id}/cancel", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
