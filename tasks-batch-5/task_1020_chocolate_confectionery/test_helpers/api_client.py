"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Products & bundles ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    def add_bundle_component(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/bundle-components", payload, headers
        )

    def get_bundle_component(self, bc_id, headers):
        return self._request("GET", f"/bundle-components/{bc_id}", headers=headers)

    def list_bundle_components(self, headers, params=None):
        return self._request("GET", "/bundle-components", headers=headers, params=params)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    def adjust_wallet(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/wallet/adjust", payload, headers
        )

    # --- Molds & tempering lines ---
    def create_mold(self, payload, headers):
        return self._request("POST", "/molds", payload, headers)

    def get_mold(self, mold_id, headers):
        return self._request("GET", f"/molds/{mold_id}", headers=headers)

    def list_molds(self, headers, params=None):
        return self._request("GET", "/molds", headers=headers, params=params)

    def set_mold_status(self, mold_id, payload, headers):
        return self._request("POST", f"/molds/{mold_id}/set-status", payload, headers)

    def get_mold_booking(self, booking_id, headers):
        return self._request("GET", f"/mold-bookings/{booking_id}", headers=headers)

    def list_mold_bookings(self, headers, params=None):
        return self._request("GET", "/mold-bookings", headers=headers, params=params)

    def create_tempering_line(self, payload, headers):
        return self._request("POST", "/tempering-lines", payload, headers)

    def get_tempering_line(self, line_id, headers):
        return self._request("GET", f"/tempering-lines/{line_id}", headers=headers)

    def list_tempering_lines(self, headers, params=None):
        return self._request("GET", "/tempering-lines", headers=headers, params=params)

    # --- Batches (inventory lots) ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def start_tempering(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/batches/{batch_id}/start-tempering", payload, headers
        )

    def complete_tempering(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/batches/{batch_id}/complete-tempering", payload or {}, headers
        )

    def reseed_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/batches/{batch_id}/reseed", payload or {}, headers)

    def release_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/batches/{batch_id}/release", payload or {}, headers)

    def quarantine_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/batches/{batch_id}/quarantine", payload or {}, headers
        )

    def clear_quarantine(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/batches/{batch_id}/clear-quarantine", payload or {}, headers
        )

    def discard_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/batches/{batch_id}/discard", payload or {}, headers)

    def create_reservation(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/batches/{batch_id}/reservations", payload, headers
        )

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def confirm_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/confirm", payload or {}, headers)

    def allocate_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/allocate", payload or {}, headers)

    def fulfill_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/fulfill", payload or {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/cancel", payload or {}, headers)

    # --- Custom / corporate orders ---
    def create_custom_order(self, payload, headers):
        return self._request("POST", "/custom-orders", payload, headers)

    def get_custom_order(self, co_id, headers):
        return self._request("GET", f"/custom-orders/{co_id}", headers=headers)

    def list_custom_orders(self, headers, params=None):
        return self._request("GET", "/custom-orders", headers=headers, params=params)

    def quote_custom_order(self, co_id, headers, payload=None):
        return self._request(
            "POST", f"/custom-orders/{co_id}/quote", payload or {}, headers
        )

    def request_revision(self, co_id, headers, payload=None):
        return self._request(
            "POST", f"/custom-orders/{co_id}/request-revision", payload or {}, headers
        )

    def accept_custom_order(self, co_id, payload, headers):
        return self._request("POST", f"/custom-orders/{co_id}/accept", payload, headers)

    def reject_custom_order(self, co_id, headers, payload=None):
        return self._request(
            "POST", f"/custom-orders/{co_id}/reject", payload or {}, headers
        )

    def start_production(self, co_id, headers, payload=None):
        return self._request(
            "POST", f"/custom-orders/{co_id}/start-production", payload or {}, headers
        )

    def fulfill_custom_order(self, co_id, payload, headers):
        return self._request("POST", f"/custom-orders/{co_id}/fulfill", payload, headers)

    def cancel_custom_order(self, co_id, headers, payload=None):
        return self._request(
            "POST", f"/custom-orders/{co_id}/cancel", payload or {}, headers
        )

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pause_subscription(self, sub_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/pause", payload or {}, headers
        )

    def resume_subscription(self, sub_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/resume", payload or {}, headers
        )

    def cancel_subscription(self, sub_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/cancel", payload or {}, headers
        )

    def advance_subscription(self, sub_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/advance", payload or {}, headers
        )

    def get_shipment(self, shipment_id, headers):
        return self._request(
            "GET", f"/subscription-shipments/{shipment_id}", headers=headers
        )

    def list_shipments(self, headers, params=None):
        return self._request(
            "GET", "/subscription-shipments", headers=headers, params=params
        )

    def ship_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"/subscription-shipments/{shipment_id}/ship", payload or {}, headers
        )

    # --- System / test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def sweep_expired(self, headers, payload=None):
        return self._request("POST", "/_inventory/sweep-expired", payload or {}, headers)


api_client = ApiClient()
