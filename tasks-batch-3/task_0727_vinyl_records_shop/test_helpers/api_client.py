"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers -------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/shop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/shop/customers/{customer_id}", headers=headers)

    def credit_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/shop/customers/{customer_id}/credit-adjustments", payload, headers)

    # ---- Products / catalog ---------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/shop/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/shop/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/shop/products", headers=headers, params=params)

    def list_product(self, product_id, headers):
        return self._request("POST", f"/shop/products/{product_id}/list", headers=headers)

    def open_preorders(self, product_id, headers):
        return self._request("POST", f"/shop/products/{product_id}/open-preorders", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/shop/products/{product_id}/discontinue", headers=headers)

    # ---- Allocations ----------------------------------------------
    def create_allocation(self, product_id, payload, headers):
        return self._request("POST", f"/shop/products/{product_id}/allocations", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/shop/allocations/{allocation_id}", headers=headers)

    def list_product_allocations(self, product_id, headers):
        return self._request("GET", f"/shop/products/{product_id}/allocations", headers=headers)

    # ---- Inventory items ------------------------------------------
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/shop/inventory-items", payload, headers)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/shop/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/shop/inventory-items", headers=headers, params=params)

    # ---- Orders ---------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/shop/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/shop/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/shop/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/shop/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers):
        return self._request("GET", f"/shop/orders/{order_id}/lines", headers=headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/shop/order-lines/{line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/shop/order-lines", headers=headers, params=params)

    def authorize_payment(self, order_id, headers):
        return self._request("POST", f"/shop/orders/{order_id}/authorize-payment", headers=headers)

    def capture_payment(self, order_id, payload, headers):
        return self._request("POST", f"/shop/orders/{order_id}/capture-payment", payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/shop/orders/{order_id}/ship", headers=headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/shop/orders/{order_id}/fulfill", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/shop/orders/{order_id}/cancel", headers=headers)

    # ---- Trade-ins ------------------------------------------------
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/shop/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/shop/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/shop/trade-ins", headers=headers, params=params)

    def add_trade_in_line(self, trade_in_id, payload, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/lines", payload, headers)

    def list_trade_in_lines(self, trade_in_id, headers):
        return self._request("GET", f"/shop/trade-ins/{trade_in_id}/lines", headers=headers)

    def submit_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/submit", headers=headers)

    def start_inspection(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/start-inspection", headers=headers)

    def set_inspected_grade(self, line_id, payload, headers):
        return self._request("PATCH", f"/shop/trade-in-lines/{line_id}", payload, headers)

    def approve_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/approve", headers=headers)

    def reject_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/reject", headers=headers)

    def reverse_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/reverse", headers=headers)

    # ---- Pre-orders -----------------------------------------------
    def create_preorder(self, payload, headers):
        return self._request("POST", "/shop/pre-orders", payload, headers)

    def get_preorder(self, preorder_id, headers):
        return self._request("GET", f"/shop/pre-orders/{preorder_id}", headers=headers)

    def list_preorders(self, headers, params=None):
        return self._request("GET", "/shop/pre-orders", headers=headers, params=params)

    def ready_preorder(self, preorder_id, headers):
        return self._request("POST", f"/shop/pre-orders/{preorder_id}/ready", headers=headers)

    def fulfill_preorder(self, preorder_id, headers):
        return self._request("POST", f"/shop/pre-orders/{preorder_id}/fulfill", headers=headers)

    def cancel_preorder(self, preorder_id, headers):
        return self._request("POST", f"/shop/pre-orders/{preorder_id}/cancel", headers=headers)

    # ---- Display slots & consignments -----------------------------
    def create_display_slot(self, payload, headers):
        return self._request("POST", "/shop/display-slots", payload, headers)

    def get_display_slot(self, slot_id, headers):
        return self._request("GET", f"/shop/display-slots/{slot_id}", headers=headers)

    def create_consignment(self, payload, headers):
        return self._request("POST", "/shop/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/shop/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/shop/consignments", headers=headers, params=params)

    def activate_consignment(self, consignment_id, headers):
        return self._request("POST", f"/shop/consignments/{consignment_id}/activate", headers=headers)

    def markdown_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/shop/consignments/{consignment_id}/markdown", payload, headers)

    def withdraw_consignment(self, consignment_id, headers):
        return self._request("POST", f"/shop/consignments/{consignment_id}/withdraw", headers=headers)

    # ---- Grading disputes -----------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/shop/grading-disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/shop/grading-disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/shop/grading-disputes", headers=headers, params=params)

    def start_review(self, dispute_id, headers):
        return self._request("POST", f"/shop/grading-disputes/{dispute_id}/start-review", headers=headers)

    def request_info(self, dispute_id, headers):
        return self._request("POST", f"/shop/grading-disputes/{dispute_id}/request-info", headers=headers)

    def provide_info(self, dispute_id, headers):
        return self._request("POST", f"/shop/grading-disputes/{dispute_id}/provide-info", headers=headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/shop/grading-disputes/{dispute_id}/escalate", headers=headers)

    def resolve_regrade(self, dispute_id, payload, headers):
        return self._request("POST", f"/shop/grading-disputes/{dispute_id}/resolve-regrade", payload, headers)

    def resolve_uphold(self, dispute_id, headers):
        return self._request("POST", f"/shop/grading-disputes/{dispute_id}/resolve-uphold", headers=headers)

    # ---- Special orders -------------------------------------------
    def create_special_order(self, payload, headers):
        return self._request("POST", "/shop/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/shop/special-orders/{special_order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/shop/special-orders", headers=headers, params=params)

    def start_sourcing(self, special_order_id, headers):
        return self._request("POST", f"/shop/special-orders/{special_order_id}/start-sourcing", headers=headers)

    def mark_arrived(self, special_order_id, headers):
        return self._request("POST", f"/shop/special-orders/{special_order_id}/mark-arrived", headers=headers)

    def fulfill_special_order(self, special_order_id, headers):
        return self._request("POST", f"/shop/special-orders/{special_order_id}/fulfill", headers=headers)

    def cancel_special_order(self, special_order_id, headers):
        return self._request("POST", f"/shop/special-orders/{special_order_id}/cancel", headers=headers)

    # ---- Test-driving ---------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/shop/_clock/set_current_utc", payload, headers)

    def adjust_points(self, payload, headers):
        return self._request("POST", "/shop/_loyalty/adjust-points", payload, headers)


api_client = ApiClient()
