"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock ────────────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Customers ────────────────────────────────────────────────────────
    def register_customer(self, payload, headers):
        return self._request("POST", "/customers/register", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ─── ID scans ─────────────────────────────────────────────────────────
    def create_id_scan(self, payload, headers):
        return self._request("POST", "/id-scans", payload, headers)

    def get_id_scan(self, scan_id, headers):
        return self._request("GET", f"/id-scans/{scan_id}", headers=headers)

    def list_customer_id_scans(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/id-scans",
                             headers=headers, params=params)

    def verify_id_scan(self, scan_id, headers):
        return self._request("POST", f"/id-scans/{scan_id}/verify", {}, headers)

    def reject_id_scan(self, scan_id, payload, headers):
        return self._request("POST", f"/id-scans/{scan_id}/reject", payload, headers)

    # ─── Catalog: Products / Vintages / Lots ──────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def create_vintage(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/vintages", payload, headers)

    def get_vintage(self, vintage_id, headers):
        return self._request("GET", f"/vintages/{vintage_id}", headers=headers)

    def list_product_vintages(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/vintages",
                             headers=headers, params=params)

    def release_vintage(self, vintage_id, headers):
        return self._request("POST", f"/vintages/{vintage_id}/release", {}, headers)

    def open_allocation(self, vintage_id, headers):
        return self._request("POST", f"/vintages/{vintage_id}/open-allocation", {}, headers)

    def delist_vintage(self, vintage_id, headers):
        return self._request("POST", f"/vintages/{vintage_id}/delist", {}, headers)

    def create_lot(self, vintage_id, payload, headers):
        return self._request("POST", f"/vintages/{vintage_id}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_vintage_lots(self, vintage_id, headers, params=None):
        return self._request("GET", f"/vintages/{vintage_id}/lots",
                             headers=headers, params=params)

    # ─── State rules ──────────────────────────────────────────────────────
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/state-rules", payload, headers)

    def get_state_rule(self, rule_id, headers):
        return self._request("GET", f"/state-rules/{rule_id}", headers=headers)

    def list_state_rules(self, headers, params=None):
        return self._request("GET", "/state-rules", headers=headers, params=params)

    # ─── Orders ───────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines",
                             headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines_filtered(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def delete_order_line(self, line_id, headers):
        return self._request("DELETE", f"/order-lines/{line_id}", headers=headers)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/submit", payload, headers)

    def authorize_payment(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/authorize-payment", {}, headers)

    def capture_payment(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/capture-payment", {}, headers)

    def mark_ready(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/mark-ready", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/complete", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/refund", {}, headers)

    def list_customer_compliance_windows(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/compliance-windows",
                             headers=headers, params=params)

    def list_order_compliance_windows(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/compliance-windows",
                             headers=headers, params=params)

    # ─── Shipments ────────────────────────────────────────────────────────
    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/shipments",
                             headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers)

    def confirm_delivery(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/confirm-delivery",
                             payload, headers)

    def return_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/return", {}, headers)

    # ─── Club memberships ─────────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/club-memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/club-memberships/{membership_id}", headers=headers)

    def list_customer_memberships(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/club-memberships",
                             headers=headers, params=params)

    def suspend_membership(self, membership_id, headers):
        return self._request("POST", f"/club-memberships/{membership_id}/suspend", {}, headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST", f"/club-memberships/{membership_id}/reinstate", {}, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/club-memberships/{membership_id}/cancel", {}, headers)

    # ─── Special orders ───────────────────────────────────────────────────
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, so_id, headers):
        return self._request("GET", f"/special-orders/{so_id}", headers=headers)

    def list_customer_special_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/special-orders",
                             headers=headers, params=params)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def quote_special_order(self, so_id, payload, headers):
        return self._request("POST", f"/special-orders/{so_id}/quote", payload, headers)

    def counter_special_order(self, so_id, payload, headers):
        return self._request("POST", f"/special-orders/{so_id}/counter", payload, headers)

    def accept_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/accept", {}, headers)

    def decline_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/decline", {}, headers)

    def convert_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/convert", {}, headers)


api_client = ApiClient()
