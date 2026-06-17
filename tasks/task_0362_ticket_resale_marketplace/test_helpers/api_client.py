"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Simulated clock (PRD §2.10) ----
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ---- Section ----
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    # ---- Event ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def open_sales(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open-sales", {}, headers)

    def enter_last_minute(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/enter-last-minute", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    def postpone_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/postpone", {}, headers)

    # ---- Seller ----
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    def set_trust_tier(self, seller_id, payload, headers):
        return self._request("PATCH", f"/sellers/{seller_id}/trust-tier", payload, headers)

    # ---- Buyer ----
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    # ---- Listing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/activate", {}, headers)

    def delist_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/delist", {}, headers)

    # ---- Seat ----
    def create_seat(self, payload, headers):
        return self._request("POST", "/seats", payload, headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/seats", headers=headers, params=params)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def charge_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/charge", {}, headers)

    def cancel_reservation(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel-reservation", {}, headers)

    def confirm_delivery_window(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm-delivery-window", {}, headers)

    # ---- Transfer ----
    def initiate_transfer(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/transfers", {}, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def send_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/send", {}, headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/accept", {}, headers)

    def fail_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/fail", {}, headers)

    def recall_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/recall", {}, headers)

    # ---- Payout ----
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def pay_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/pay", payload, headers)

    # ---- GuaranteeClaim ----
    def create_guarantee_claim(self, payload, headers):
        return self._request("POST", "/guarantee-claims", payload, headers)

    def get_guarantee_claim(self, claim_id, headers):
        return self._request("GET", f"/guarantee-claims/{claim_id}", headers=headers)

    def list_guarantee_claims(self, headers, params=None):
        return self._request("GET", "/guarantee-claims", headers=headers, params=params)

    def investigate_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/investigate", {}, headers)

    def offer_replacement(self, claim_id, payload, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/offer-replacement", payload, headers)

    def reject_offer(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/reject-offer", {}, headers)

    def accept_offer(self, claim_id, payload, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/accept-offer", payload, headers)

    def refund_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/refund", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/deny", {}, headers)

    # ---- EventCredit ----
    def get_event_credit(self, credit_id, headers):
        return self._request("GET", f"/event-credits/{credit_id}", headers=headers)

    def list_event_credits(self, headers, params=None):
        return self._request("GET", "/event-credits", headers=headers, params=params)

    def revoke_credit(self, credit_id, headers):
        return self._request("POST", f"/event-credits/{credit_id}/revoke", {}, headers)

    # ---- FraudFlag ----
    def create_fraud_flag(self, payload, headers):
        return self._request("POST", "/fraud-flags", payload, headers)

    def get_fraud_flag(self, flag_id, headers):
        return self._request("GET", f"/fraud-flags/{flag_id}", headers=headers)

    def list_fraud_flags(self, headers, params=None):
        return self._request("GET", "/fraud-flags", headers=headers, params=params)

    def review_flag(self, flag_id, headers):
        return self._request("POST", f"/fraud-flags/{flag_id}/review", {}, headers)

    def confirm_flag(self, flag_id, headers):
        return self._request("POST", f"/fraud-flags/{flag_id}/confirm", {}, headers)

    def dismiss_flag(self, flag_id, headers):
        return self._request("POST", f"/fraud-flags/{flag_id}/dismiss", {}, headers)


api_client = ApiClient()
