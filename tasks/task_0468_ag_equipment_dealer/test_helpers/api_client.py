"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Units ───────────────────────────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def recondition_unit(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/recondition", {}, headers)

    def retire_unit(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/retire", {}, headers)

    # ─── Floor-plan notes ────────────────────────────────────────────────────
    def create_floor_plan_note(self, payload, headers):
        return self._request("POST", "/floor-plan-notes", payload, headers)

    def list_floor_plan_notes(self, headers, params=None):
        return self._request("GET", "/floor-plan-notes", headers=headers, params=params)

    def get_floor_plan_note(self, note_id, headers):
        return self._request("GET", f"/floor-plan-notes/{note_id}", headers=headers)

    def activate_floor_plan_note(self, note_id, headers):
        return self._request("POST", f"/floor-plan-notes/{note_id}/activate", {}, headers)

    def recompute_floor_plan_note(self, note_id, headers):
        return self._request("POST", f"/floor-plan-notes/{note_id}/recompute", {}, headers)

    def curtail_floor_plan_note(self, note_id, payload, headers):
        return self._request("POST", f"/floor-plan-notes/{note_id}/curtail", payload, headers)

    def default_floor_plan_note(self, note_id, headers):
        return self._request("POST", f"/floor-plan-notes/{note_id}/default", {}, headers)

    # ─── Customers ───────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Trade-ins ───────────────────────────────────────────────────────────
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def get_trade_in(self, tradein_id, headers):
        return self._request("GET", f"/trade-ins/{tradein_id}", headers=headers)

    def offer_trade_in(self, tradein_id, headers):
        return self._request("POST", f"/trade-ins/{tradein_id}/offer", {}, headers)

    def decline_trade_in(self, tradein_id, headers):
        return self._request("POST", f"/trade-ins/{tradein_id}/decline", {}, headers)

    # ─── Deals ───────────────────────────────────────────────────────────────
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def approve_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/approve", {}, headers)

    def fund_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/fund", payload, headers)

    def deliver_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/deliver", {}, headers)

    def unwind_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/unwind", payload, headers)

    # ─── Auction lots & bids ─────────────────────────────────────────────────
    def create_auction_lot(self, payload, headers):
        return self._request("POST", "/auction-lots", payload, headers)

    def list_auction_lots(self, headers, params=None):
        return self._request("GET", "/auction-lots", headers=headers, params=params)

    def get_auction_lot(self, lot_id, headers):
        return self._request("GET", f"/auction-lots/{lot_id}", headers=headers)

    def open_auction_lot(self, lot_id, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/open", {}, headers)

    def place_bid(self, lot_id, payload, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/bids", payload, headers)

    def list_lot_bids(self, lot_id, headers, params=None):
        return self._request("GET", f"/auction-lots/{lot_id}/bids", headers=headers, params=params)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def close_auction_lot(self, lot_id, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/close", {}, headers)

    def settle_auction_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/settle", payload, headers)

    # ─── Parts ───────────────────────────────────────────────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    # ─── Work orders & part lines ────────────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def add_part_line(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/part-lines", payload, headers)

    def list_wo_part_lines(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/part-lines", headers=headers, params=params)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", "/part-lines", headers=headers, params=params)

    def get_part_line(self, pl_id, headers):
        return self._request("GET", f"/part-lines/{pl_id}", headers=headers)

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/start", {}, headers)

    def hold_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/hold-for-parts", {}, headers)

    def resume_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/resume", {}, headers)

    def close_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/close", payload, headers)

    def void_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/void", {}, headers)

    # ─── Warranty claims ─────────────────────────────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def submit_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/submit", {}, headers)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def pay_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/pay", {}, headers)

    # ─── Whole-goods orders ──────────────────────────────────────────────────
    def create_whole_goods_order(self, payload, headers):
        return self._request("POST", "/whole-goods-orders", payload, headers)

    def list_whole_goods_orders(self, headers, params=None):
        return self._request("GET", "/whole-goods-orders", headers=headers, params=params)

    def get_whole_goods_order(self, order_id, headers):
        return self._request("GET", f"/whole-goods-orders/{order_id}", headers=headers)

    def confirm_whole_goods_order(self, order_id, headers):
        return self._request("POST", f"/whole-goods-orders/{order_id}/confirm", {}, headers)

    def allocate_whole_goods_order(self, order_id, payload, headers):
        return self._request("POST", f"/whole-goods-orders/{order_id}/allocate", payload, headers)

    def cancel_whole_goods_order(self, order_id, headers):
        return self._request("POST", f"/whole-goods-orders/{order_id}/cancel", {}, headers)

    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
