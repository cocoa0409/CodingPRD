"""API client: one method per endpoint defined in the Auction House PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Salerooms ─────────────────────────────────────────────────────
    def create_saleroom(self, payload, headers):
        return self._request("POST", "/salerooms", payload, headers)

    # ─── Consignors ────────────────────────────────────────────────────
    def create_consignor(self, payload, headers):
        return self._request("POST", "/consignors", payload, headers)

    # ─── Bidders ───────────────────────────────────────────────────────
    def create_bidder(self, payload, headers):
        return self._request("POST", "/bidders", payload, headers)

    def suspend_bidder(self, bidder_id, headers):
        return self._request("POST", f"/bidders/{bidder_id}/suspend", {}, headers)

    # ─── Auctions ──────────────────────────────────────────────────────
    def create_auction(self, payload, headers):
        return self._request("POST", "/auctions", payload, headers)

    def open_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/open", {}, headers)

    def close_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/close", {}, headers)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"/auctions/{auction_id}", headers=headers)

    def list_auctions(self, headers, params=None):
        return self._request("GET", "/auctions", headers=headers, params=params)

    # ─── Consignments ──────────────────────────────────────────────────
    def create_consignment(self, payload, headers):
        return self._request("POST", "/consignments", payload, headers)

    def appraise_consignment(self, consignment_id, payload, headers):
        return self._request(
            "POST", f"/consignments/{consignment_id}/appraise", payload, headers
        )

    def decide_consignment(self, consignment_id, payload, headers):
        return self._request(
            "POST", f"/consignments/{consignment_id}/decision", payload, headers
        )

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/consignments", headers=headers, params=params)

    def create_settlement(self, consignment_id, headers):
        return self._request(
            "POST", f"/consignments/{consignment_id}/settlement", {}, headers
        )

    # ─── Lots ──────────────────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def open_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/open", {}, headers)

    def hammer_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/hammer", {}, headers)

    def pass_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/pass", {}, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # ─── Bids ──────────────────────────────────────────────────────────
    def place_bid(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/bids", payload, headers)

    def retract_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/retract", {}, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    # ─── Invoices ──────────────────────────────────────────────────────
    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/payments", payload, headers
        )

    def ready_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/ready", payload, headers)

    def fulfill_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/fulfill", {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    # ─── Invoice lines ─────────────────────────────────────────────────
    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    # ─── Settlements ───────────────────────────────────────────────────
    def approve_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/approve", {}, headers
        )

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/pay", {}, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    # ─── Disputes ──────────────────────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", {}, headers)

    def request_info_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/request-info", payload, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)


api_client = ApiClient()
