"""API client: one method per endpoint defined in the Art Auction
Consignment PRD (§4). The base _request() method is inherited from the
framework's GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- premium schedules ----
    def create_premium_schedule(self, payload, headers):
        return self._request("POST", "/premium-schedules", payload, headers)

    def get_premium_schedule(self, schedule_id, headers):
        return self._request("GET", f"/premium-schedules/{schedule_id}", headers=headers)

    # ---- sellers ----
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    # ---- bidders ----
    def create_bidder(self, payload, headers):
        return self._request("POST", "/bidders", payload, headers)

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def patch_bidder(self, bidder_id, payload, headers):
        return self._request("PATCH", f"/bidders/{bidder_id}", payload, headers)

    def list_bidder_invoices(self, bidder_id, headers, params=None):
        return self._request("GET", f"/bidders/{bidder_id}/invoices", headers=headers, params=params)

    def list_bidder_paddle_registrations(self, bidder_id, headers, params=None):
        return self._request("GET", f"/bidders/{bidder_id}/paddle-registrations", headers=headers, params=params)

    # ---- consignments ----
    def create_consignment(self, payload, headers):
        return self._request("POST", "/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/consignments", headers=headers, params=params)

    def activate_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/activate", payload, headers)

    def revert_consignment_to_draft(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/revert-to-draft", payload, headers)

    def terminate_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/terminate", payload, headers)

    def list_consignment_seller_statements(self, consignment_id, headers, params=None):
        return self._request("GET", f"/consignments/{consignment_id}/seller-statements", headers=headers, params=params)

    # ---- auction sales ----
    def create_auction_sale(self, payload, headers):
        return self._request("POST", "/auction-sales", payload, headers)

    def get_auction_sale(self, sale_id, headers):
        return self._request("GET", f"/auction-sales/{sale_id}", headers=headers)

    def list_auction_sales(self, headers, params=None):
        return self._request("GET", "/auction-sales", headers=headers, params=params)

    def publish_auction_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/auction-sales/{sale_id}/publish", payload, headers)

    def open_bidding(self, sale_id, payload, headers):
        return self._request("POST", f"/auction-sales/{sale_id}/open-bidding", payload, headers)

    def close_auction_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/auction-sales/{sale_id}/close", payload, headers)

    # ---- lots ----
    def create_lot(self, sale_id, payload, headers):
        return self._request("POST", f"/auction-sales/{sale_id}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_sale_lots(self, sale_id, headers, params=None):
        return self._request("GET", f"/auction-sales/{sale_id}/lots", headers=headers, params=params)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def withdraw_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/withdraw", payload, headers)

    def open_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/open", payload, headers)

    def knock_down_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/knock-down", payload, headers)

    def buy_in_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/buy-in", payload, headers)

    def reverse_sale(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/reverse-sale", payload, headers)

    # ---- bids ----
    def create_bid(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_lot_bids(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/bids", headers=headers, params=params)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def retract_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/bids/{bid_id}/retract", payload, headers)

    # ---- paddle registrations ----
    def create_paddle_registration(self, payload, headers):
        return self._request("POST", "/paddle-registrations", payload, headers)

    def get_paddle_registration(self, registration_id, headers):
        return self._request("GET", f"/paddle-registrations/{registration_id}", headers=headers)

    def list_sale_paddle_registrations(self, sale_id, headers, params=None):
        return self._request("GET", f"/auction-sales/{sale_id}/paddle-registrations", headers=headers, params=params)

    def revoke_paddle_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/paddle-registrations/{registration_id}/revoke", payload, headers)

    # ---- settlement: invoice / payment / statement / payout ----
    def invoice_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/invoice", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_lot_invoices(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/invoices", headers=headers, params=params)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def statement_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/statement", payload, headers)

    def get_seller_statement(self, statement_id, headers):
        return self._request("GET", f"/seller-statements/{statement_id}", headers=headers)

    def list_lot_seller_statements(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/seller-statements", headers=headers, params=params)

    def disburse_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/seller-statements/{statement_id}/disburse", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_statement_payouts(self, statement_id, headers, params=None):
        return self._request("GET", f"/seller-statements/{statement_id}/payouts", headers=headers, params=params)

    # ---- resale royalties ----
    def list_lot_resale_royalties(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/resale-royalties", headers=headers, params=params)

    def get_resale_royalty(self, royalty_id, headers):
        return self._request("GET", f"/resale-royalties/{royalty_id}", headers=headers)


api_client = ApiClient()
