"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (admin-only test-driving capability)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Retailers
    # ------------------------------------------------------------------
    def create_retailer(self, payload, headers):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/retailers/{retailer_id}", headers=headers)

    def get_credit_summary(self, retailer_id, headers):
        return self._request("GET", f"/retailers/{retailer_id}/credit-summary", headers=headers)

    def update_retailer(self, retailer_id, payload, headers):
        return self._request("PATCH", f"/retailers/{retailer_id}", payload, headers)

    def set_credit_hold(self, retailer_id, payload, headers):
        return self._request("POST", f"/retailers/{retailer_id}/credit-hold", payload, headers)

    def list_retailer_order_guides(self, retailer_id, headers, params=None):
        return self._request("GET", f"/retailers/{retailer_id}/order-guides", headers=headers, params=params)

    def list_retailer_retail_prices(self, retailer_id, headers, params=None):
        return self._request("GET", f"/retailers/{retailer_id}/retail-prices", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ------------------------------------------------------------------
    # Order guides
    # ------------------------------------------------------------------
    def create_order_guide(self, payload, headers):
        return self._request("POST", "/order-guides", payload, headers)

    def get_order_guide(self, guide_id, headers):
        return self._request("GET", f"/order-guides/{guide_id}", headers=headers)

    # ------------------------------------------------------------------
    # Promo events
    # ------------------------------------------------------------------
    def create_promo_event(self, payload, headers):
        return self._request("POST", "/promo-events", payload, headers)

    def list_promo_events(self, headers, params=None):
        return self._request("GET", "/promo-events", headers=headers, params=params)

    def get_promo_event(self, promo_id, headers):
        return self._request("GET", f"/promo-events/{promo_id}", headers=headers)

    # ------------------------------------------------------------------
    # Retail price records
    # ------------------------------------------------------------------
    def create_retail_price_record(self, payload, headers):
        return self._request("POST", "/retail-price-records", payload, headers)

    def list_retail_price_records(self, headers, params=None):
        return self._request("GET", "/retail-price-records", headers=headers, params=params)

    def get_retail_price_record(self, record_id, headers):
        return self._request("GET", f"/retail-price-records/{record_id}", headers=headers)

    # ------------------------------------------------------------------
    # Delivery windows
    # ------------------------------------------------------------------
    def create_delivery_window(self, payload, headers):
        return self._request("POST", "/delivery-windows", payload, headers)

    def list_delivery_windows(self, headers, params=None):
        return self._request("GET", "/delivery-windows", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fuel surcharge rates
    # ------------------------------------------------------------------
    def create_fuel_surcharge_rate(self, payload, headers):
        return self._request("POST", "/fuel-surcharge-rates", payload, headers)

    def list_fuel_surcharge_rates(self, headers, params=None):
        return self._request("GET", "/fuel-surcharge-rates", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Tax stamp supplies
    # ------------------------------------------------------------------
    def create_tax_stamp_supply(self, payload, headers):
        return self._request("POST", "/tax-stamp-supplies", payload, headers)

    def list_tax_stamp_supplies(self, headers, params=None):
        return self._request("GET", "/tax-stamp-supplies", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Delivery manifests
    # ------------------------------------------------------------------
    def create_delivery_manifest(self, payload, headers):
        return self._request("POST", "/delivery-manifests", payload, headers)

    def list_delivery_manifests(self, headers, params=None):
        return self._request("GET", "/delivery-manifests", headers=headers, params=params)

    def get_delivery_manifest(self, manifest_id, headers):
        return self._request("GET", f"/delivery-manifests/{manifest_id}", headers=headers)

    def begin_loading(self, manifest_id, headers):
        return self._request("POST", f"/delivery-manifests/{manifest_id}/begin-loading", {}, headers)

    def assign_order(self, manifest_id, payload, headers):
        return self._request("POST", f"/delivery-manifests/{manifest_id}/assign-order", payload, headers)

    def close_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"/delivery-manifests/{manifest_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Delivery exceptions
    # ------------------------------------------------------------------
    def create_delivery_exception(self, manifest_id, payload, headers):
        return self._request("POST", f"/delivery-manifests/{manifest_id}/delivery-exceptions", payload, headers)

    def list_delivery_exceptions(self, headers, params=None):
        return self._request("GET", "/delivery-exceptions", headers=headers, params=params)

    def get_delivery_exception(self, exception_id, headers):
        return self._request("GET", f"/delivery-exceptions/{exception_id}", headers=headers)

    # ------------------------------------------------------------------
    # Purchase orders
    # ------------------------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/purchase-orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/purchase-orders/{order_id}/lines", headers=headers, params=params)

    def list_order_lines_filtered(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/submit", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/cancel", {}, headers)

    def confirm_delivery(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/confirm-delivery", {}, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def apply_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Credit memos
    # ------------------------------------------------------------------
    def create_credit_memo(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/credit-memos", payload, headers)

    def list_invoice_credit_memos(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/credit-memos", headers=headers, params=params)

    def list_credit_memos(self, headers, params=None):
        return self._request("GET", "/credit-memos", headers=headers, params=params)

    def get_credit_memo(self, memo_id, headers):
        return self._request("GET", f"/credit-memos/{memo_id}", headers=headers)

    def post_credit_memo(self, memo_id, headers):
        return self._request("POST", f"/credit-memos/{memo_id}/post", {}, headers)

    def void_credit_memo(self, memo_id, headers):
        return self._request("POST", f"/credit-memos/{memo_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # ------------------------------------------------------------------
    # New item requests
    # ------------------------------------------------------------------
    def create_new_item_request(self, payload, headers):
        return self._request("POST", "/new-item-requests", payload, headers)

    def list_new_item_requests(self, headers, params=None):
        return self._request("GET", "/new-item-requests", headers=headers, params=params)

    def get_new_item_request(self, request_id, headers):
        return self._request("GET", f"/new-item-requests/{request_id}", headers=headers)

    def start_review(self, request_id, headers):
        return self._request("POST", f"/new-item-requests/{request_id}/start-review", {}, headers)

    def request_revision(self, request_id, payload, headers):
        return self._request("POST", f"/new-item-requests/{request_id}/request-revision", payload, headers)

    def resubmit(self, request_id, payload, headers):
        return self._request("POST", f"/new-item-requests/{request_id}/resubmit", payload, headers)

    def authorize_request(self, request_id, headers):
        return self._request("POST", f"/new-item-requests/{request_id}/authorize", {}, headers)

    def reject_request(self, request_id, headers):
        return self._request("POST", f"/new-item-requests/{request_id}/reject", {}, headers)


api_client = ApiClient()
