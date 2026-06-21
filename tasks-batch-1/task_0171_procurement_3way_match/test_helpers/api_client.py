"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------
    # Test clock (PRD §2.4)
    # ---------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/procurement/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---------------------------------------------------------------
    # SpendCategory
    # ---------------------------------------------------------------
    def create_spend_category(self, payload, headers):
        return self._request("POST", "/procurement/spend-categories", payload, headers)

    def get_spend_category(self, category_id, headers):
        return self._request("GET", f"/procurement/spend-categories/{category_id}", headers=headers)

    def list_spend_categories(self, headers, params=None):
        return self._request("GET", "/procurement/spend-categories", headers=headers, params=params)

    def archive_spend_category(self, category_id, headers):
        return self._request("POST", f"/procurement/spend-categories/{category_id}/archive", headers=headers)

    # ---------------------------------------------------------------
    # Vendor
    # ---------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/procurement/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/procurement/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/procurement/vendors", headers=headers, params=params)

    def block_vendor(self, vendor_id, headers):
        return self._request("POST", f"/procurement/vendors/{vendor_id}/block", headers=headers)

    # ---------------------------------------------------------------
    # Requisition
    # ---------------------------------------------------------------
    def create_requisition(self, payload, headers):
        return self._request("POST", "/procurement/requisitions", payload, headers)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/procurement/requisitions/{requisition_id}", headers=headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/procurement/requisitions", headers=headers, params=params)

    def submit_requisition(self, requisition_id, headers):
        return self._request("POST", f"/procurement/requisitions/{requisition_id}/submit", {}, headers)

    def approve_requisition(self, requisition_id, payload, headers):
        return self._request("POST", f"/procurement/requisitions/{requisition_id}/approve", payload, headers)

    def reject_requisition(self, requisition_id, headers):
        return self._request("POST", f"/procurement/requisitions/{requisition_id}/reject", {}, headers)

    def revise_requisition(self, requisition_id, headers):
        return self._request("POST", f"/procurement/requisitions/{requisition_id}/revise", {}, headers)

    def cancel_requisition(self, requisition_id, headers):
        return self._request("POST", f"/procurement/requisitions/{requisition_id}/cancel", {}, headers)

    # ---------------------------------------------------------------
    # ApprovalStep
    # ---------------------------------------------------------------
    def get_approval_step(self, step_id, headers):
        return self._request("GET", f"/procurement/approval-steps/{step_id}", headers=headers)

    def list_approval_steps(self, headers, params=None):
        return self._request("GET", "/procurement/approval-steps", headers=headers, params=params)

    # ---------------------------------------------------------------
    # RFQ
    # ---------------------------------------------------------------
    def create_rfq(self, payload, headers):
        return self._request("POST", "/procurement/rfqs", payload, headers)

    def get_rfq(self, rfq_id, headers):
        return self._request("GET", f"/procurement/rfqs/{rfq_id}", headers=headers)

    def list_rfqs(self, headers, params=None):
        return self._request("GET", "/procurement/rfqs", headers=headers, params=params)

    def award_rfq(self, rfq_id, payload, headers):
        return self._request("POST", f"/procurement/rfqs/{rfq_id}/award", payload, headers)

    def cancel_rfq(self, rfq_id, headers):
        return self._request("POST", f"/procurement/rfqs/{rfq_id}/cancel", {}, headers)

    def close_no_award_rfq(self, rfq_id, headers):
        return self._request("POST", f"/procurement/rfqs/{rfq_id}/close_no_award", {}, headers)

    # ---------------------------------------------------------------
    # Quote
    # ---------------------------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", "/procurement/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/procurement/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/procurement/quotes", headers=headers, params=params)

    # ---------------------------------------------------------------
    # PurchaseOrder
    # ---------------------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/procurement/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/procurement/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/procurement/purchase-orders", headers=headers, params=params)

    def close_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/procurement/purchase-orders/{po_id}/close", payload, headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/procurement/purchase-orders/{po_id}/cancel", {}, headers)

    # ---------------------------------------------------------------
    # ReleaseOrder
    # ---------------------------------------------------------------
    def create_release_order(self, payload, headers):
        return self._request("POST", "/procurement/release-orders", payload, headers)

    def get_release_order(self, release_id, headers):
        return self._request("GET", f"/procurement/release-orders/{release_id}", headers=headers)

    def list_release_orders(self, headers, params=None):
        return self._request("GET", "/procurement/release-orders", headers=headers, params=params)

    def cancel_release_order(self, release_id, headers):
        return self._request("POST", f"/procurement/release-orders/{release_id}/cancel", {}, headers)

    # ---------------------------------------------------------------
    # GoodsReceipt
    # ---------------------------------------------------------------
    def create_goods_receipt(self, payload, headers):
        return self._request("POST", "/procurement/goods-receipts", payload, headers)

    def get_goods_receipt(self, receipt_id, headers):
        return self._request("GET", f"/procurement/goods-receipts/{receipt_id}", headers=headers)

    def list_goods_receipts(self, headers, params=None):
        return self._request("GET", "/procurement/goods-receipts", headers=headers, params=params)

    def reverse_goods_receipt(self, receipt_id, headers):
        return self._request("POST", f"/procurement/goods-receipts/{receipt_id}/reverse", {}, headers)

    # ---------------------------------------------------------------
    # Invoice
    # ---------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/procurement/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/procurement/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/procurement/invoices", headers=headers, params=params)

    def match_invoice(self, invoice_id, headers):
        return self._request("POST", f"/procurement/invoices/{invoice_id}/match", {}, headers)

    def approve_payment(self, invoice_id, headers):
        return self._request("POST", f"/procurement/invoices/{invoice_id}/approve-payment", {}, headers)

    def reject_payment(self, invoice_id, headers):
        return self._request("POST", f"/procurement/invoices/{invoice_id}/reject-payment", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/procurement/invoices/{invoice_id}/pay", {}, headers)

    # ---------------------------------------------------------------
    # MatchException
    # ---------------------------------------------------------------
    def get_match_exception(self, exc_id, headers):
        return self._request("GET", f"/procurement/match-exceptions/{exc_id}", headers=headers)

    def list_match_exceptions(self, headers, params=None):
        return self._request("GET", "/procurement/match-exceptions", headers=headers, params=params)

    def resolve_match_exception(self, exc_id, headers):
        return self._request("POST", f"/procurement/match-exceptions/{exc_id}/resolve", {}, headers)

    def waive_match_exception(self, exc_id, headers):
        return self._request("POST", f"/procurement/match-exceptions/{exc_id}/waive", {}, headers)

    # ---------------------------------------------------------------
    # VendorScorecard
    # ---------------------------------------------------------------
    def create_vendor_scorecard(self, payload, headers):
        return self._request("POST", "/procurement/vendor-scorecards", payload, headers)

    def get_vendor_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/procurement/vendor-scorecards/{scorecard_id}", headers=headers)

    def list_vendor_scorecards(self, headers, params=None):
        return self._request("GET", "/procurement/vendor-scorecards", headers=headers, params=params)


api_client = ApiClient()
