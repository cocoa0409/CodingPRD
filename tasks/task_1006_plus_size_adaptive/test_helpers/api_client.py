"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Customer ----
    def register_customer(self, payload, headers):
        return self._request("POST", "/customers/register", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/status", payload, headers)

    def adjust_customer_wallet(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/wallet-adjustments", payload, headers
        )

    def adjust_customer_loyalty(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/loyalty-adjustments", payload, headers
        )

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_variant(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/variants", payload, headers)

    def list_product_variants(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/variants", headers=headers, params=params
        )

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/variants/{variant_id}", headers=headers)

    def restock_variant(self, variant_id, payload, headers):
        return self._request("POST", f"/variants/{variant_id}/restock", payload, headers)

    def list_variant_order_lines(self, variant_id, headers, params=None):
        return self._request(
            "GET", f"/variants/{variant_id}/order-lines", headers=headers, params=params
        )

    # ---- FitSpecialist ----
    def create_specialist(self, payload, headers):
        return self._request("POST", "/specialists", payload, headers)

    def get_specialist(self, specialist_id, headers):
        return self._request("GET", f"/specialists/{specialist_id}", headers=headers)

    def set_specialist_status(self, specialist_id, payload, headers):
        return self._request(
            "POST", f"/specialists/{specialist_id}/status", payload, headers
        )

    # ---- StylingAppointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def transition_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/transition", payload, headers
        )

    # ---- Order ----
    def create_order(self, headers, payload=None):
        return self._request("POST", "/orders", payload or {}, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/lines", headers=headers, params=params
        )

    def checkout_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/checkout", payload, headers)

    def transition_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/transition", payload, headers)

    # ---- ReturnRequest ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def transition_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/transition", payload, headers)

    # ---- BoxSubscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/box-subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/box-subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/box-subscriptions", headers=headers, params=params)

    def set_subscription_status(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/box-subscriptions/{subscription_id}/status", payload, headers
        )

    def create_shipment(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/box-subscriptions/{subscription_id}/shipments", payload, headers
        )

    def list_subscription_shipments(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/box-subscriptions/{subscription_id}/shipments",
            headers=headers,
            params=params,
        )

    # ---- BoxShipment ----
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/box-shipments/{shipment_id}", headers=headers)

    def ship_shipment(self, shipment_id, headers):
        return self._request("POST", f"/box-shipments/{shipment_id}/ship", {}, headers)

    def keep_decisions(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/box-shipments/{shipment_id}/keep-decisions", payload, headers
        )

    def settle_shipment(self, shipment_id, headers):
        return self._request("POST", f"/box-shipments/{shipment_id}/settle", {}, headers)


api_client = ApiClient()
