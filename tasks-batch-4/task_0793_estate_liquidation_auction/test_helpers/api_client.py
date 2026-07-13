"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Estate ----
    def create_estate(self, payload, headers):
        return self._request("POST", "/estates", payload, headers)

    def get_estate(self, estate_id, headers):
        return self._request("GET", f"/estates/{estate_id}", headers=headers)

    def list_estate_lots(self, estate_id, headers, params=None):
        return self._request("GET", f"/estates/{estate_id}/lots",
                             headers=headers, params=params)

    def list_estate_pickup_windows(self, estate_id, headers, params=None):
        return self._request("GET", f"/estates/{estate_id}/pickup-windows",
                             headers=headers, params=params)

    def open_estate(self, estate_id, headers):
        return self._request("POST", f"/estates/{estate_id}/open", {}, headers)

    def close_estate(self, estate_id, headers):
        return self._request("POST", f"/estates/{estate_id}/close", {}, headers)

    def settle_estate(self, estate_id, headers):
        return self._request("POST", f"/estates/{estate_id}/settle", {}, headers)

    def cleanout_estate(self, estate_id, headers):
        return self._request("POST", f"/estates/{estate_id}/cleanout", {}, headers)

    # ---- Lot ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lot_photos(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/photos",
                             headers=headers, params=params)

    def update_lot(self, lot_id, payload, headers):
        return self._request("PATCH", f"/lots/{lot_id}", payload, headers)

    # ---- Photo ----
    def create_photo(self, payload, headers):
        return self._request("POST", "/photos", payload, headers)

    # ---- Buyer ----
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def verify_buyer(self, buyer_id, headers):
        return self._request("POST", f"/buyers/{buyer_id}/verify", {}, headers)

    # ---- Bid ----
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    # ---- Order ----
    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/payments",
                             headers=headers, params=params)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def schedule_pickup(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/schedule-pickup",
                             payload, headers)

    def cancel_pickup(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel-pickup", {}, headers)

    def complete_pickup(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/complete-pickup",
                             payload, headers)

    # ---- PickupWindow ----
    def create_pickup_window(self, payload, headers):
        return self._request("POST", "/pickup-windows", payload, headers)

    # ---- Dispute ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def update_dispute(self, dispute_id, payload, headers):
        return self._request("PATCH", f"/disputes/{dispute_id}", payload, headers)

    # ---- Donation ----
    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)


api_client = ApiClient()
