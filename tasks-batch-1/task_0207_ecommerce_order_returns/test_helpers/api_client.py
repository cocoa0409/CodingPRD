"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Test-driving clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- Customers -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def get_customer_risk(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/risk",
                             headers=headers, params=params)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/orders",
                             headers=headers, params=params)

    def list_customer_credit_entries(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/credit-entries",
                             headers=headers, params=params)

    def list_customer_refunds(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/refunds",
                             headers=headers, params=params)

    def list_customer_returns(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/returns",
                             headers=headers, params=params)

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-adjustments",
                             payload, headers)

    # ----- Warehouses & inventory -----
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}", headers=headers)

    def list_warehouse_inventory(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/inventory",
                             headers=headers, params=params)

    def list_warehouse_shipments(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/shipments",
                             headers=headers, params=params)

    def list_warehouse_reservations(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/reservations",
                             headers=headers, params=params)

    # ----- Products & inventory items -----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_inventory(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/inventory",
                             headers=headers, params=params)

    def list_product_reservations(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/reservations",
                             headers=headers, params=params)

    def list_product_order_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/order-lines",
                             headers=headers, params=params)

    def list_product_return_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/return-lines",
                             headers=headers, params=params)

    def create_inventory(self, payload, headers):
        return self._request("POST", "/inventory", payload, headers)

    def get_inventory(self, inventory_id, headers):
        return self._request("GET", f"/inventory/{inventory_id}", headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservation_shipment_lines(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/shipment-lines",
                             headers=headers, params=params)

    # ----- Orders / cart -----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines",
                             headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_line_reservations(self, order_line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{order_line_id}/reservations",
                             headers=headers, params=params)

    def list_order_line_shipment_lines(self, order_line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{order_line_id}/shipment-lines",
                             headers=headers, params=params)

    def list_order_line_return_lines(self, order_line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{order_line_id}/return-lines",
                             headers=headers, params=params)

    def checkout_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/checkout", payload, headers)

    def capture_payment(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/capture-payment",
                             {}, headers)

    def void_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/void", {}, headers)

    def list_order_refunds(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/refunds",
                             headers=headers, params=params)

    # ----- Shipments -----
    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/shipments", payload, headers)

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/shipments",
                             headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipment_lines(self, shipment_id, headers, params=None):
        return self._request("GET", f"/shipments/{shipment_id}/lines",
                             headers=headers, params=params)

    def ship_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/ship", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers)

    # ----- Returns / RMA -----
    def open_return(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/returns", payload, headers)

    def list_order_returns(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/returns",
                             headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_return_lines(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/lines",
                             headers=headers, params=params)

    def list_return_refunds(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/refunds",
                             headers=headers, params=params)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refund_credit_entries(self, refund_id, headers, params=None):
        return self._request("GET", f"/refunds/{refund_id}/credit-entries",
                             headers=headers, params=params)

    def approve_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/approve", payload, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    def cancel_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/cancel", {}, headers)

    def settle_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/settle", {}, headers)

    def restock_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/restock", payload, headers)


api_client = ApiClient()
