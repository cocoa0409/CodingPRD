"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Organizer --------------------------------------------------------
    def create_organizer(self, payload, headers):
        return self._request("POST", "/api/organizers", payload, headers=headers)

    def get_organizer(self, organizer_id, headers):
        return self._request("GET", f"/api/organizers/{organizer_id}", headers=headers)

    def get_organizer_reliability(self, organizer_id, headers, params=None):
        return self._request("GET", f"/api/organizers/{organizer_id}/reliability",
                             headers=headers, params=params)

    # ---- Venue ------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/api/venues", payload, headers=headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/api/venues/{venue_id}", headers=headers)

    # ---- Buyer ------------------------------------------------------------
    def create_buyer(self, payload, headers):
        return self._request("POST", "/api/buyers", payload, headers=headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/api/buyers/{buyer_id}", headers=headers)

    # ---- Event ------------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers=headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/publish", {}, headers=headers)

    def pause_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/pause", {}, headers=headers)

    def resume_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/resume", {}, headers=headers)

    def close_event_sales(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/close-sales", {}, headers=headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/complete", {}, headers=headers)

    def cancel_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/api/events/{event_id}/cancel",
                             payload if payload is not None else {}, headers=headers)

    def get_event_report(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}/report", headers=headers)

    # ---- TicketType -------------------------------------------------------
    def create_ticket_type(self, payload, headers):
        return self._request("POST", "/api/ticket-types", payload, headers=headers)

    def get_ticket_type(self, ticket_type_id, headers):
        return self._request("GET", f"/api/ticket-types/{ticket_type_id}", headers=headers)

    def list_ticket_types(self, headers, params=None):
        return self._request("GET", "/api/ticket-types", headers=headers, params=params)

    def update_ticket_type(self, ticket_type_id, payload, headers):
        return self._request("PATCH", f"/api/ticket-types/{ticket_type_id}", payload,
                             headers=headers)

    def waitlist_sweep(self, ticket_type_id, headers):
        return self._request("POST", f"/api/ticket-types/{ticket_type_id}/waitlist-sweep",
                             {}, headers=headers)

    # ---- SeatBlock --------------------------------------------------------
    def create_seat_block(self, payload, headers):
        return self._request("POST", "/api/seat-blocks", payload, headers=headers)

    def get_seat_block(self, seat_block_id, headers):
        return self._request("GET", f"/api/seat-blocks/{seat_block_id}", headers=headers)

    def list_seat_blocks(self, headers, params=None):
        return self._request("GET", "/api/seat-blocks", headers=headers, params=params)

    # ---- PromoCode --------------------------------------------------------
    def create_promo_code(self, payload, headers):
        return self._request("POST", "/api/promo-codes", payload, headers=headers)

    def get_promo_code(self, promo_code_id, headers):
        return self._request("GET", f"/api/promo-codes/{promo_code_id}", headers=headers)

    def list_promo_codes(self, headers, params=None):
        return self._request("GET", "/api/promo-codes", headers=headers, params=params)

    # ---- Order ------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers=headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/pay", {}, headers=headers)

    def release_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/release", {}, headers=headers)

    # ---- OrderItem --------------------------------------------------------
    def get_order_item(self, order_item_id, headers):
        return self._request("GET", f"/api/order-items/{order_item_id}", headers=headers)

    def list_order_items(self, headers, params=None):
        return self._request("GET", "/api/order-items", headers=headers, params=params)

    # ---- Attendee ---------------------------------------------------------
    def get_attendee(self, attendee_id, headers):
        return self._request("GET", f"/api/attendees/{attendee_id}", headers=headers)

    def list_attendees(self, headers, params=None):
        return self._request("GET", "/api/attendees", headers=headers, params=params)

    def void_attendee(self, attendee_id, headers, payload=None):
        return self._request("POST", f"/api/attendees/{attendee_id}/void",
                             payload if payload is not None else {}, headers=headers)

    def undo_check_in(self, attendee_id, headers):
        return self._request("POST", f"/api/attendees/{attendee_id}/undo-check-in",
                             {}, headers=headers)

    # ---- ScanRecord -------------------------------------------------------
    def create_scan(self, payload, headers):
        return self._request("POST", "/api/scans", payload, headers=headers)

    def get_scan(self, scan_id, headers):
        return self._request("GET", f"/api/scans/{scan_id}", headers=headers)

    def list_scans(self, headers, params=None):
        return self._request("GET", "/api/scans", headers=headers, params=params)

    # ---- RefundRequest ----------------------------------------------------
    def create_refund_request(self, payload, headers):
        return self._request("POST", "/api/refund-requests", payload, headers=headers)

    def get_refund_request(self, refund_request_id, headers):
        return self._request("GET", f"/api/refund-requests/{refund_request_id}",
                             headers=headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/api/refund-requests", headers=headers, params=params)

    def approve_refund_request(self, refund_request_id, headers):
        return self._request("POST", f"/api/refund-requests/{refund_request_id}/approve",
                             {}, headers=headers)

    def reject_refund_request(self, refund_request_id, headers, payload=None):
        return self._request("POST", f"/api/refund-requests/{refund_request_id}/reject",
                             payload if payload is not None else {}, headers=headers)

    def settle_refund_request(self, refund_request_id, headers):
        return self._request("POST", f"/api/refund-requests/{refund_request_id}/settle",
                             {}, headers=headers)

    # ---- TransferRequest --------------------------------------------------
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/api/transfer-requests", payload, headers=headers)

    def get_transfer_request(self, transfer_request_id, headers):
        return self._request("GET", f"/api/transfer-requests/{transfer_request_id}",
                             headers=headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/api/transfer-requests", headers=headers, params=params)

    def send_transfer_request(self, transfer_request_id, headers):
        return self._request("POST", f"/api/transfer-requests/{transfer_request_id}/send",
                             {}, headers=headers)

    def accept_transfer_request(self, transfer_request_id, payload, headers):
        return self._request("POST", f"/api/transfer-requests/{transfer_request_id}/accept",
                             payload, headers=headers)

    def decline_transfer_request(self, transfer_request_id, payload, headers):
        return self._request("POST", f"/api/transfer-requests/{transfer_request_id}/decline",
                             payload, headers=headers)

    # ---- WaitlistEntry ----------------------------------------------------
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/api/waitlist-entries", payload, headers=headers)

    def get_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("GET", f"/api/waitlist-entries/{waitlist_entry_id}",
                             headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/api/waitlist-entries", headers=headers, params=params)

    def claim_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{waitlist_entry_id}/claim",
                             {}, headers=headers)

    def requeue_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{waitlist_entry_id}/requeue",
                             {}, headers=headers)

    # ---- Payout -----------------------------------------------------------
    def create_payout(self, payload, headers):
        return self._request("POST", "/api/payouts", payload, headers=headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/api/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/api/payouts", headers=headers, params=params)

    def mark_payout_eligible(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/mark-eligible",
                             {}, headers=headers)

    def hold_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/api/payouts/{payout_id}/hold",
                             payload if payload is not None else {}, headers=headers)

    def resume_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/resume", {}, headers=headers)

    def approve_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/approve", {}, headers=headers)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/release", {}, headers=headers)

    def release_payout_reserve(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/release-reserve",
                             {}, headers=headers)


api_client = ApiClient()
