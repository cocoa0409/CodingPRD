"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- Test-driving capabilities (PRD §2.5) --
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def sweep_season_end(self, season_year, headers):
        return self._request("POST", "/api/v1/_sweep/season_end",
                             {"season_year": season_year}, headers)

    # -- Customers --
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/v1/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/v1/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/v1/customers", headers=headers, params=params)

    def suspend_customer(self, customer_id, payload, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/suspend", payload, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/reinstate", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/close", {}, headers)

    def adjust_wallet(self, customer_id, payload, headers):
        return self._request("POST", f"/api/v1/customers/{customer_id}/wallet-adjustments",
                             payload, headers)

    # -- Products --
    def create_product(self, payload, headers):
        return self._request("POST", "/api/v1/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/v1/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/api/v1/products", headers=headers, params=params)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/api/v1/products/{product_id}", payload, headers)

    # -- Area restrictions --
    def create_area_restriction(self, payload, headers):
        return self._request("POST", "/api/v1/area-restrictions", payload, headers)

    def get_area_restriction(self, restriction_id, headers):
        return self._request("GET", f"/api/v1/area-restrictions/{restriction_id}", headers=headers)

    def list_area_restrictions(self, headers, params=None):
        return self._request("GET", "/api/v1/area-restrictions", headers=headers, params=params)

    # -- Subscriptions --
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/v1/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/v1/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/v1/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/v1/subscriptions/{subscription_id}/activate",
                             {}, headers)

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/api/v1/subscriptions/{subscription_id}/cancel",
                             payload, headers)

    # -- Delivery routes --
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/api/v1/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/api/v1/delivery-routes/{route_id}", headers=headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request("GET", "/api/v1/delivery-routes", headers=headers, params=params)

    # -- Delivery windows --
    def create_delivery_window(self, payload, headers):
        return self._request("POST", "/api/v1/delivery-windows", payload, headers)

    def get_delivery_window(self, window_id, headers):
        return self._request("GET", f"/api/v1/delivery-windows/{window_id}", headers=headers)

    def list_delivery_windows(self, headers, params=None):
        return self._request("GET", "/api/v1/delivery-windows", headers=headers, params=params)

    def close_delivery_window(self, window_id, headers):
        return self._request("POST", f"/api/v1/delivery-windows/{window_id}/close", {}, headers)

    def lock_delivery_window(self, window_id, headers):
        return self._request("POST", f"/api/v1/delivery-windows/{window_id}/lock", {}, headers)

    def cancel_delivery_window(self, window_id, payload, headers):
        return self._request("POST", f"/api/v1/delivery-windows/{window_id}/cancel",
                             payload, headers)

    # -- Orders --
    def create_order(self, payload, headers):
        return self._request("POST", "/api/v1/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/v1/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/v1/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{id}/lines".format(id=order_id),
                             payload, headers)

    def update_order_line(self, line_id, payload, headers):
        return self._request("PATCH", f"/api/v1/order-lines/{line_id}", payload, headers)

    def delete_order_line(self, line_id, headers):
        return self._request("DELETE", f"/api/v1/order-lines/{line_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/submit", {}, headers)

    def schedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/schedule", payload, headers)

    def dispatch_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/dispatch", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/deliver", {}, headers)

    def fail_delivery(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/fail-delivery",
                             payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/cancel", payload, headers)

    # -- Order lines (reads) --
    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/v1/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/api/v1/orders/{order_id}/lines",
                             headers=headers, params=params)

    def list_order_lines_cross(self, headers, params=None):
        return self._request("GET", "/api/v1/order-lines", headers=headers, params=params)

    # -- Moisture readings --
    def create_moisture_reading(self, line_id, payload, headers):
        return self._request("POST", f"/api/v1/order-lines/{line_id}/moisture-readings",
                             payload, headers)

    def list_moisture_readings(self, line_id, headers, params=None):
        return self._request("GET", f"/api/v1/order-lines/{line_id}/moisture-readings",
                             headers=headers, params=params)

    # -- Invoices --
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/v1/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/v1/invoices", headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/v1/invoices/{invoice_id}/void", {}, headers)

    # -- Payments --
    def post_payment(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/payments", payload, headers)

    def list_payment_events(self, invoice_id, headers, params=None):
        return self._request("GET", f"/api/v1/invoices/{invoice_id}/payment-events",
                             headers=headers, params=params)


api_client = ApiClient()
