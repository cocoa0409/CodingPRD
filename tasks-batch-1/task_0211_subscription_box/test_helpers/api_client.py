"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles envelope/session.
All list methods accept an optional `params` dict for pagination/filters.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Plans ────────────────────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/retire", {}, headers)

    # ─── Products ─────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def restock_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/restock", payload, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers)

    # ─── Subscribers / wallet ─────────────────────────────────────────────
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def list_wallet_entries(self, subscriber_id, headers, params=None):
        return self._request("GET", f"/subscribers/{subscriber_id}/wallet-entries",
                             headers=headers, params=params)

    def create_wallet_entry(self, subscriber_id, payload, headers):
        return self._request("POST", f"/subscribers/{subscriber_id}/wallet-entries",
                             payload, headers)

    # ─── Subscriptions ────────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", payload, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", payload, headers)

    def winback_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/winback", {}, headers)

    def prepay_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/prepay", payload, headers)

    def retry_charge(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/retry-charge", payload, headers)

    # ─── Box selections ───────────────────────────────────────────────────
    def create_box_selection(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/box-selections",
                             payload, headers)

    def get_box_selection(self, box_id, headers):
        return self._request("GET", f"/box-selections/{box_id}", headers=headers)

    def list_box_selections(self, headers, params=None):
        return self._request("GET", "/box-selections", headers=headers, params=params)

    def swap_box_selection(self, box_id, payload, headers):
        return self._request("PATCH", f"/box-selections/{box_id}", payload, headers)

    # ─── Shipping waves ───────────────────────────────────────────────────
    def create_wave(self, payload, headers):
        return self._request("POST", "/waves", payload, headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/waves", headers=headers, params=params)

    def lock_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/lock", {}, headers)

    def ship_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/ship", {}, headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/cancel", {}, headers)

    # ─── Allocations ──────────────────────────────────────────────────────
    def create_allocation(self, payload, headers):
        return self._request("POST", "/allocations", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/release", {}, headers)

    # ─── Shipments ────────────────────────────────────────────────────────
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    # ─── Billing cycles ───────────────────────────────────────────────────
    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/billing-cycles", headers=headers, params=params)

    # ─── Invoices ─────────────────────────────────────────────────────────
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    # ─── Gift grants ──────────────────────────────────────────────────────
    def create_gift_grant(self, payload, headers):
        return self._request("POST", "/gift-grants", payload, headers)

    def get_gift_grant(self, gift_id, headers):
        return self._request("GET", f"/gift-grants/{gift_id}", headers=headers)

    def list_gift_grants(self, headers, params=None):
        return self._request("GET", "/gift-grants", headers=headers, params=params)

    def redeem_gift_grant(self, payload, headers):
        return self._request("POST", "/gift-grants/redeem", payload, headers)

    def revoke_gift_grant(self, gift_id, headers):
        return self._request("POST", f"/gift-grants/{gift_id}/revoke", {}, headers)

    # ─── Test-driving clock + renewal run ─────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_renewal(self, payload, headers):
        return self._request("POST", "/_renewal/run", payload, headers)


api_client = ApiClient()
