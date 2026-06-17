"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_account_feedback(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/feedback", headers=headers, params=params)

    def list_account_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/invoices", headers=headers, params=params)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # ---- Listings ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/publish", {}, headers)

    def cancel_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/cancel", {}, headers)

    def buy_now(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/buy-now", payload, headers)

    # ---- Bids ----
    def create_bid(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def retract_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/retract", {}, headers)

    # ---- Watches ----
    def create_watch(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/watch", payload, headers)

    def get_watch(self, watch_id, headers):
        return self._request("GET", f"/watches/{watch_id}", headers=headers)

    def delete_watch(self, watch_id, headers):
        return self._request("DELETE", f"/watches/{watch_id}", headers=headers)

    def list_watches(self, headers, params=None):
        return self._request("GET", "/watches", headers=headers, params=params)

    # ---- Offers ----
    def create_offer(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/counter", payload, headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", {}, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/withdraw", {}, headers)

    # ---- Orders ----
    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def complete_return(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/complete-return", {}, headers)

    def get_order_invoice(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/invoice", headers=headers)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/payments", headers=headers, params=params)

    # ---- Seller Fee Invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/seller-fee-invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/seller-fee-invoices", headers=headers, params=params)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"/seller-fee-invoices/{invoice_id}/settle", {}, headers)

    # ---- Feedback ----
    def create_feedback(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/feedback", payload, headers)

    def list_order_feedback(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/feedback-entries", headers=headers, params=params)

    def get_feedback(self, feedback_id, headers):
        return self._request("GET", f"/feedback/{feedback_id}", headers=headers)

    def list_feedback(self, headers, params=None):
        return self._request("GET", "/feedback", headers=headers, params=params)

    # ---- Disputes ----
    def create_dispute(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def respond_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/respond", payload, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/escalate", {}, headers)

    def close_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/close", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # ---- Test-driving clock ----
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
