"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Buyers ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def list_buyer_queue_tokens(self, buyer_id, headers, params=None):
        return self._request("GET", f"/buyers/{buyer_id}/queue-tokens", headers=headers, params=params)

    def list_buyer_transfers(self, buyer_id, headers, params=None):
        return self._request("GET", f"/buyers/{buyer_id}/transfers", headers=headers, params=params)

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def set_event_status(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/status", payload, headers)

    def create_price_level(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/price-levels", payload, headers)

    def list_price_levels(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/price-levels", headers=headers, params=params)

    def create_seat(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/seats", payload, headers)

    def create_queue_token(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/queue-tokens", payload, headers)

    def list_event_queue_tokens(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/queue-tokens", headers=headers, params=params)

    def create_hold(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/holds", payload, headers)

    def sweep_holds(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/sweep-holds", {}, headers)

    def finalize_settlement(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/settlement/finalize", {}, headers)

    def get_settlement(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/settlement", headers=headers, params=params)

    # --- Seats ---
    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/seats", headers=headers, params=params)

    # --- Queue tokens ---
    def admit_queue_token(self, token_id, headers):
        return self._request("POST", f"/queue-tokens/{token_id}/admit", {}, headers)

    # --- Holds ---
    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/holds", headers=headers, params=params)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/holds/{hold_id}/release", {}, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def create_refund_request(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/refund-requests", payload, headers)

    def list_order_refund_requests(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/refund-requests", headers=headers, params=params)

    # --- Refund requests ---
    def approve_refund_request(self, refund_id, headers):
        return self._request("POST", f"/refund-requests/{refund_id}/approve", {}, headers)

    def reject_refund_request(self, refund_id, headers):
        return self._request("POST", f"/refund-requests/{refund_id}/reject", {}, headers)

    # --- Tickets ---
    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def list_ticket_transfers(self, ticket_id, headers, params=None):
        return self._request("GET", f"/tickets/{ticket_id}/transfers", headers=headers, params=params)

    def deliver_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/deliver", {}, headers)

    def scan_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/scan", {}, headers)

    # --- Transfers ---
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfers", payload, headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/accept", {}, headers)

    def decline_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/decline", {}, headers)


api_client = ApiClient()
