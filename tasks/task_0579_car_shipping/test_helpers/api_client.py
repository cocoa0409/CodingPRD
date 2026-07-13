"""API client: one method per endpoint defined in the Car Shipping PRD.

Subclasses the framework GenericApiClient; the base _request() handles the
HTTP envelope. Every method returns the raw requests.Response so tests can
assert status codes and error envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Shippers ────────────────────────────────────────────────────
    def create_shipper(self, payload, headers):
        return self._request("POST", "/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/shippers/{shipper_id}", headers=headers)

    # ── Terminals ───────────────────────────────────────────────────
    def create_terminal(self, payload, headers):
        return self._request("POST", "/terminals", payload, headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/terminals", headers=headers, params=params)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/terminals/{terminal_id}", headers=headers)

    # ── Carriers ────────────────────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/suspend", {}, headers)

    # ── Shipment Orders ─────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/shipment-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/shipment-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/shipment-orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/cancel", {}, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/close", {}, headers)

    # ── Vehicles ────────────────────────────────────────────────────
    def create_vehicle(self, order_id, payload, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    # ── Quotes ──────────────────────────────────────────────────────
    def create_quote(self, order_id, payload, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def accept_quote(self, order_id, quote_id, headers):
        return self._request(
            "POST", f"/shipment-orders/{order_id}/quotes/{quote_id}/accept", {}, headers
        )

    # ── Ledger Entries ──────────────────────────────────────────────
    def create_ledger_entry(self, order_id, payload, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/ledger-entries", payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}", headers=headers)

    def void_ledger_entry(self, ledger_entry_id, headers):
        return self._request("POST", f"/ledger-entries/{ledger_entry_id}/void", {}, headers)

    # ── Load Listings ───────────────────────────────────────────────
    def create_listing(self, order_id, payload, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    # ── Dispatch Offers ─────────────────────────────────────────────
    def create_offer(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def counter_offer(self, listing_id, offer_id, payload, headers):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/counter", payload, headers
        )

    def reoffer_offer(self, listing_id, offer_id, payload, headers):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/reoffer", payload, headers
        )

    def withdraw_offer(self, listing_id, offer_id, headers):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/withdraw", {}, headers
        )

    def accept_offer(self, listing_id, offer_id, headers):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/accept", {}, headers
        )

    # ── Assignments ─────────────────────────────────────────────────
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def revoke_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/revoke", {}, headers)

    # ── Inspections ─────────────────────────────────────────────────
    def create_inspection(self, order_id, payload, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    # ── Claims ──────────────────────────────────────────────────────
    def create_claim(self, order_id, payload, headers):
        return self._request("POST", f"/shipment-orders/{order_id}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def return_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/return", {}, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", {}, headers)

    # ── Logical clock (test-driving) ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
