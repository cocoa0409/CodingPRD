"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/ap/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/ap/vendors/{vendor_id}", headers=headers)

    def hold_vendor(self, vendor_id, payload, headers):
        return self._request("POST", f"/ap/vendors/{vendor_id}/hold", payload, headers)

    # ---- GLAccount ----
    def create_gl_account(self, payload, headers):
        return self._request("POST", "/ap/gl-accounts", payload, headers)

    # ---- PurchaseOrder ----
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/ap/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/ap/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/ap/purchase-orders", headers=headers, params=params)

    def list_po_goods_receipts(self, po_id, headers, params=None):
        return self._request("GET", f"/ap/purchase-orders/{po_id}/goods-receipts", headers=headers, params=params)

    def list_po_accruals(self, po_id, headers, params=None):
        return self._request("GET", f"/ap/purchase-orders/{po_id}/accruals", headers=headers, params=params)

    def list_po_invoices(self, po_id, headers, params=None):
        return self._request("GET", f"/ap/purchase-orders/{po_id}/invoices", headers=headers, params=params)

    # ---- GoodsReceipt ----
    def create_goods_receipt(self, payload, headers):
        return self._request("POST", "/ap/goods-receipts", payload, headers)

    def post_goods_receipt(self, gr_id, headers):
        return self._request("POST", f"/ap/goods-receipts/{gr_id}/post", {}, headers)

    def get_goods_receipt(self, gr_id, headers):
        return self._request("GET", f"/ap/goods-receipts/{gr_id}", headers=headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/ap/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ap/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/ap/invoices", headers=headers, params=params)

    def add_invoice_line(self, invoice_id, payload, headers):
        return self._request("POST", f"/ap/invoices/{invoice_id}/lines", payload, headers)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request("GET", f"/ap/invoices/{invoice_id}/lines", headers=headers, params=params)

    def code_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ap/invoices/{invoice_id}/code", {}, headers)

    def submit_invoice_for_approval(self, invoice_id, headers):
        return self._request("POST", f"/ap/invoices/{invoice_id}/submit-approval", {}, headers)

    def reject_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ap/invoices/{invoice_id}/reject", {}, headers)

    def list_invoice_audit_events(self, invoice_id, headers, params=None):
        return self._request("GET", f"/ap/invoices/{invoice_id}/audit-events", headers=headers, params=params)

    def list_invoice_match_exceptions(self, invoice_id, headers, params=None):
        return self._request("GET", f"/ap/invoices/{invoice_id}/match-exceptions", headers=headers, params=params)

    def list_invoice_approval_steps(self, invoice_id, headers, params=None):
        return self._request("GET", f"/ap/invoices/{invoice_id}/approval-steps", headers=headers, params=params)

    # ---- MatchException ----
    def get_match_exception(self, exc_id, headers):
        return self._request("GET", f"/ap/match-exceptions/{exc_id}", headers=headers)

    def resolve_match_exception(self, exc_id, headers):
        return self._request("POST", f"/ap/match-exceptions/{exc_id}/resolve", {}, headers)

    def write_off_match_exception(self, exc_id, headers):
        return self._request("POST", f"/ap/match-exceptions/{exc_id}/write-off", {}, headers)

    def escalate_match_exception(self, exc_id, headers):
        return self._request("POST", f"/ap/match-exceptions/{exc_id}/escalate", {}, headers)

    # ---- ApprovalRoute / ApprovalStep ----
    def create_approval_route(self, payload, headers):
        return self._request("POST", "/ap/approval-routes", payload, headers)

    def get_approval_step(self, step_id, headers):
        return self._request("GET", f"/ap/approval-steps/{step_id}", headers=headers)

    def approve_step(self, step_id, headers):
        return self._request("POST", f"/ap/approval-steps/{step_id}/approve", {}, headers)

    def reject_step(self, step_id, headers):
        return self._request("POST", f"/ap/approval-steps/{step_id}/reject", {}, headers)

    # ---- PaymentBatch / Payment ----
    def create_payment_batch(self, payload, headers):
        return self._request("POST", "/ap/payment-batches", payload, headers)

    def get_payment_batch(self, batch_id, headers):
        return self._request("GET", f"/ap/payment-batches/{batch_id}", headers=headers)

    def add_payment(self, batch_id, payload, headers):
        return self._request("POST", f"/ap/payment-batches/{batch_id}/payments", payload, headers)

    def list_batch_payments(self, batch_id, headers, params=None):
        return self._request("GET", f"/ap/payment-batches/{batch_id}/payments", headers=headers, params=params)

    def release_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/ap/payment-batches/{batch_id}/release", payload, headers)

    def settle_batch(self, batch_id, headers):
        return self._request("POST", f"/ap/payment-batches/{batch_id}/settle", {}, headers)

    def void_batch(self, batch_id, headers):
        return self._request("POST", f"/ap/payment-batches/{batch_id}/void", {}, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/ap/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/ap/payments", headers=headers, params=params)

    def delete_payment(self, payment_id, headers):
        return self._request("DELETE", f"/ap/payments/{payment_id}", headers=headers)

    def return_payment(self, payment_id, headers):
        return self._request("POST", f"/ap/payments/{payment_id}/return", {}, headers)

    # ---- Accrual ----
    def create_accrual(self, payload, headers):
        return self._request("POST", "/ap/accruals", payload, headers)

    def get_accrual(self, accrual_id, headers):
        return self._request("GET", f"/ap/accruals/{accrual_id}", headers=headers)

    def reverse_accrual(self, accrual_id, headers):
        return self._request("POST", f"/ap/accruals/{accrual_id}/reverse", {}, headers)


api_client = ApiClient()
