"""API client: one method per endpoint defined in the PRD (mounted under /auction)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── AuctionSale ────────────────────────────────────────────────────
    def create_sale(self, payload, headers):
        return self._request("POST", "/auction/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/auction/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/auction/sales/{sale_id}", headers=headers)

    def open_sale(self, sale_id, headers):
        return self._request("POST", f"/auction/sales/{sale_id}/open", {}, headers)

    def start_sale(self, sale_id, headers):
        return self._request("POST", f"/auction/sales/{sale_id}/start", {}, headers)

    def close_sale(self, sale_id, headers):
        return self._request("POST", f"/auction/sales/{sale_id}/close", {}, headers)

    def settle_sale(self, sale_id, headers):
        return self._request("POST", f"/auction/sales/{sale_id}/settle", {}, headers)

    # ─── Lane ───────────────────────────────────────────────────────────
    def create_lane(self, payload, headers):
        return self._request("POST", "/auction/lanes", payload, headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/auction/lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/auction/lanes/{lane_id}", headers=headers)

    def archive_lane(self, lane_id, headers):
        return self._request("POST", f"/auction/lanes/{lane_id}/archive", {}, headers)

    # ─── Seller ─────────────────────────────────────────────────────────
    def create_seller(self, payload, headers):
        return self._request("POST", "/auction/sellers", payload, headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/auction/sellers", headers=headers, params=params)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/auction/sellers/{seller_id}", headers=headers)

    def suspend_seller(self, seller_id, headers):
        return self._request("POST", f"/auction/sellers/{seller_id}/suspend", {}, headers)

    def reinstate_seller(self, seller_id, headers):
        return self._request("POST", f"/auction/sellers/{seller_id}/reinstate", {}, headers)

    # ─── Buyer ──────────────────────────────────────────────────────────
    def create_buyer(self, payload, headers):
        return self._request("POST", "/auction/buyers", payload, headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/auction/buyers", headers=headers, params=params)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/auction/buyers/{buyer_id}", headers=headers)

    def suspend_buyer(self, buyer_id, headers):
        return self._request("POST", f"/auction/buyers/{buyer_id}/suspend", {}, headers)

    def reinstate_buyer(self, buyer_id, headers):
        return self._request("POST", f"/auction/buyers/{buyer_id}/reinstate", {}, headers)

    # ─── Consignment ────────────────────────────────────────────────────
    def create_consignment(self, payload, headers):
        return self._request("POST", "/auction/consignments", payload, headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/auction/consignments", headers=headers, params=params)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/auction/consignments/{consignment_id}", headers=headers)

    def catalog_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/auction/consignments/{consignment_id}/catalog", payload, headers)

    def withdraw_consignment(self, consignment_id, headers):
        return self._request("POST", f"/auction/consignments/{consignment_id}/withdraw", {}, headers)

    # ─── ConditionReport ────────────────────────────────────────────────
    def create_condition_report(self, payload, headers):
        return self._request("POST", "/auction/condition-reports", payload, headers)

    def list_condition_reports(self, headers, params=None):
        return self._request("GET", "/auction/condition-reports", headers=headers, params=params)

    def get_condition_report(self, condition_report_id, headers):
        return self._request("GET", f"/auction/condition-reports/{condition_report_id}", headers=headers)

    # ─── RunListEntry (Lot) ─────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", "/auction/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/auction/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/auction/lots/{lot_id}", headers=headers)

    def open_bidding(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/open-bidding", {}, headers)

    def close_bidding(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/close-bidding", {}, headers)

    def hammer_lot(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/hammer", {}, headers)

    def mark_if(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/mark-if", {}, headers)

    def pass_lot(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/pass", {}, headers)

    def relist_lot(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/relist", {}, headers)

    def withdraw_lot(self, lot_id, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/withdraw", {}, headers)

    # ─── Bid ────────────────────────────────────────────────────────────
    def place_bid(self, lot_id, payload, headers):
        return self._request("POST", f"/auction/lots/{lot_id}/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/auction/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/auction/bids/{bid_id}", headers=headers)

    # ─── ArbitrationClaim ───────────────────────────────────────────────
    def create_arbitration_claim(self, payload, headers):
        return self._request("POST", "/auction/arbitration-claims", payload, headers)

    def list_arbitration_claims(self, headers, params=None):
        return self._request("GET", "/auction/arbitration-claims", headers=headers, params=params)

    def get_arbitration_claim(self, claim_id, headers):
        return self._request("GET", f"/auction/arbitration-claims/{claim_id}", headers=headers)

    def rule_arbitration_claim(self, claim_id, headers):
        return self._request("POST", f"/auction/arbitration-claims/{claim_id}/rule", {}, headers)

    # ─── Settlement ─────────────────────────────────────────────────────
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/auction/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/auction/settlements/{settlement_id}", headers=headers)

    def record_payment(self, settlement_id, headers):
        return self._request("POST", f"/auction/settlements/{settlement_id}/record-payment", {}, headers)

    def record_title(self, settlement_id, headers):
        return self._request("POST", f"/auction/settlements/{settlement_id}/record-title", {}, headers)

    def write_off_settlement(self, settlement_id, headers):
        return self._request("POST", f"/auction/settlements/{settlement_id}/write-off", {}, headers)

    # ─── GatePass ───────────────────────────────────────────────────────
    def list_gate_passes(self, headers, params=None):
        return self._request("GET", "/auction/gate-passes", headers=headers, params=params)

    def get_gate_pass(self, gate_pass_id, headers):
        return self._request("GET", f"/auction/gate-passes/{gate_pass_id}", headers=headers)

    def redeem_gate_pass(self, gate_pass_id, headers):
        return self._request("POST", f"/auction/gate-passes/{gate_pass_id}/redeem", {}, headers)

    # ─── Carrier ────────────────────────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", "/auction/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/auction/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/auction/carriers/{carrier_id}", headers=headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/auction/carriers/{carrier_id}/suspend", {}, headers)

    # ─── TransportOrder ─────────────────────────────────────────────────
    def create_transport_order(self, payload, headers):
        return self._request("POST", "/auction/transport-orders", payload, headers)

    def list_transport_orders(self, headers, params=None):
        return self._request("GET", "/auction/transport-orders", headers=headers, params=params)

    def get_transport_order(self, transport_order_id, headers):
        return self._request("GET", f"/auction/transport-orders/{transport_order_id}", headers=headers)

    def dispatch_transport_order(self, transport_order_id, headers):
        return self._request("POST", f"/auction/transport-orders/{transport_order_id}/dispatch", {}, headers)

    def deliver_transport_order(self, transport_order_id, headers):
        return self._request("POST", f"/auction/transport-orders/{transport_order_id}/deliver", {}, headers)

    def cancel_transport_order(self, transport_order_id, headers):
        return self._request("POST", f"/auction/transport-orders/{transport_order_id}/cancel", {}, headers)


api_client = ApiClient()
