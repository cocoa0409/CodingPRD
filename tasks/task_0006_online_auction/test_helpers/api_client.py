"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sellers ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    # --- Bidders ---
    def create_bidder(self, payload, headers):
        return self._request("POST", "/bidders", payload, headers)

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def credit_wallet(self, bidder_id, payload, headers):
        return self._request("POST", f"/bidders/{bidder_id}/wallet/credit", payload, headers)

    def restrict_bidder(self, bidder_id, headers):
        return self._request("POST", f"/bidders/{bidder_id}/restrict", payload=None, headers=headers)

    def suspend_bidder(self, bidder_id, headers):
        return self._request("POST", f"/bidders/{bidder_id}/suspend", payload=None, headers=headers)

    def reinstate_bidder(self, bidder_id, headers):
        return self._request("POST", f"/bidders/{bidder_id}/reinstate", payload=None, headers=headers)

    # --- Lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def publish_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/publish", payload=None, headers=headers)

    def cancel_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/cancel", payload=None, headers=headers)

    # --- Bids ---
    def place_bid(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/bids", payload, headers)

    def list_bids(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/bids", headers=headers, params=params)

    # --- AutoBid Proxies ---
    def create_auto_bid_proxy(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/auto-bid-proxies", payload, headers)

    def get_auto_bid_proxy(self, lot_id, proxy_id, headers):
        return self._request("GET", f"/lots/{lot_id}/auto-bid-proxies/{proxy_id}", headers=headers)

    def cancel_auto_bid_proxy(self, lot_id, proxy_id, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/auto-bid-proxies/{proxy_id}/cancel", payload=None, headers=headers
        )

    # --- Lot lifecycle / settlement ---
    def default_winner(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/winner/default", payload=None, headers=headers)

    def runner_up_accept(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/runner-up/accept", payload=None, headers=headers)

    def runner_up_decline(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/runner-up/decline", payload=None, headers=headers)

    # --- Invoices ---
    def get_invoice(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}/invoice", headers=headers)

    # --- Disputes ---
    def file_dispute(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/disputes", payload, headers)

    def start_dispute_review(self, lot_id, dispute_id, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/disputes/{dispute_id}/start-review", payload=None, headers=headers
        )

    def resolve_dispute(self, lot_id, dispute_id, payload, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/disputes/{dispute_id}/resolve", payload, headers
        )

    # --- Test-driving / event ingestion ---
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def event_payment_confirmed(self, payload, headers):
        return self._request("POST", "/_events/payment-confirmed", payload, headers)

    def event_identity_verified(self, payload, headers):
        return self._request("POST", "/_events/identity-verified", payload, headers)

    def event_logistics_delivered(self, payload, headers):
        return self._request("POST", "/_events/logistics-delivered", payload, headers)

    def event_account_takeover_alert(self, payload, headers):
        return self._request("POST", "/_events/account-takeover-alert", payload, headers)

    def sweep_risk_monitor(self, headers):
        return self._request("POST", "/_sweep/risk-monitor", payload=None, headers=headers)


api_client = ApiClient()
