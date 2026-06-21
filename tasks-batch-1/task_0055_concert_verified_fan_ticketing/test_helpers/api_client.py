"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Fan ----
    def create_fan(self, payload, headers):
        return self._request("POST", "/fans", payload, headers)

    def verify_fan(self, fan_id, headers, payload=None):
        return self._request("POST", f"/fans/{fan_id}/verify", payload or {}, headers)

    def get_fan(self, fan_id, headers):
        return self._request("GET", f"/fans/{fan_id}", headers=headers)

    def list_fans(self, headers, params=None):
        return self._request("GET", "/fans", headers=headers, params=params)

    # ---- Event ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def open_presale(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/open-presale", payload, headers)

    def open_general(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/open-general", payload, headers)

    def close_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/close", payload, headers)

    def advance_queue(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/advance-queue", payload, headers)

    # ---- PriceTier ----
    def create_price_tier(self, payload, headers):
        return self._request("POST", "/price-tiers", payload, headers)

    def get_price_tier(self, tier_id, headers):
        return self._request("GET", f"/price-tiers/{tier_id}", headers=headers)

    def list_price_tiers(self, headers, params=None):
        return self._request("GET", "/price-tiers", headers=headers, params=params)

    # ---- QueueEntry ----
    def create_queue_entry(self, payload, headers):
        return self._request("POST", "/queue-entries", payload, headers)

    def get_queue_entry(self, entry_id, headers):
        return self._request("GET", f"/queue-entries/{entry_id}", headers=headers)

    def list_queue_entries(self, headers, params=None):
        return self._request("GET", "/queue-entries", headers=headers, params=params)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/cancel", payload or {}, headers)

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/refund", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    # ---- Ticket ----
    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def scan_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/scan", payload, headers)

    # ---- Transfer ----
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfers", payload, headers)

    def accept_transfer(self, transfer_id, headers, payload=None):
        return self._request("POST", f"/transfers/{transfer_id}/accept", payload or {}, headers)

    def decline_transfer(self, transfer_id, headers, payload=None):
        return self._request("POST", f"/transfers/{transfer_id}/decline", payload or {}, headers)

    def cancel_transfer(self, transfer_id, headers, payload=None):
        return self._request("POST", f"/transfers/{transfer_id}/cancel", payload or {}, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    # ---- ResaleListing ----
    def create_resale_listing(self, payload, headers):
        return self._request("POST", "/resale-listings", payload, headers)

    def buy_resale_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/resale-listings/{listing_id}/buy", payload, headers)

    def cancel_resale_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/resale-listings/{listing_id}/cancel", payload or {}, headers)

    def get_resale_listing(self, listing_id, headers):
        return self._request("GET", f"/resale-listings/{listing_id}", headers=headers)

    def list_resale_listings(self, headers, params=None):
        return self._request("GET", "/resale-listings", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
