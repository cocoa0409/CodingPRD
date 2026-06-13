"""API client: one method per endpoint in the Print & Copy Shop Order API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Shops ────────────────────────────────────────────────────────────
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    # ─── Products ─────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    # ─── Pricing tiers ────────────────────────────────────────────────────
    def create_pricing_tier(self, payload, headers):
        return self._request("POST", "/pricing-tiers", payload, headers)

    def list_pricing_tiers(self, headers, params=None):
        return self._request("GET", "/pricing-tiers", headers=headers, params=params)

    def get_pricing_tier(self, pricing_tier_id, headers):
        return self._request("GET", f"/pricing-tiers/{pricing_tier_id}", headers=headers)

    # ─── Finishing options ────────────────────────────────────────────────
    def create_finishing_option(self, payload, headers):
        return self._request("POST", "/finishing-options", payload, headers)

    def list_finishing_options(self, headers, params=None):
        return self._request("GET", "/finishing-options", headers=headers, params=params)

    def get_finishing_option(self, finishing_option_id, headers):
        return self._request("GET", f"/finishing-options/{finishing_option_id}", headers=headers)

    # ─── Presses ──────────────────────────────────────────────────────────
    def create_press(self, payload, headers):
        return self._request("POST", "/presses", payload, headers)

    def list_presses(self, headers, params=None):
        return self._request("GET", "/presses", headers=headers, params=params)

    def get_press(self, press_id, headers):
        return self._request("GET", f"/presses/{press_id}", headers=headers)

    # ─── Customers ────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def get_loyalty_preview(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}/loyalty-preview", headers=headers)

    # ─── Orders ───────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def reorder(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reorder", payload, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def start_production(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/start-production", headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/invoice", headers=headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/refund", headers=headers)

    # ─── Order lines ──────────────────────────────────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def patch_order_line(self, order_line_id, payload, headers):
        return self._request("PATCH", f"/order-lines/{order_line_id}", payload, headers)

    def produce_order_line(self, order_line_id, headers):
        return self._request("POST", f"/order-lines/{order_line_id}/produce", headers=headers)

    # ─── Artworks ─────────────────────────────────────────────────────────
    def create_artwork(self, payload, headers):
        return self._request("POST", "/artworks", payload, headers)

    def list_artworks(self, headers, params=None):
        return self._request("GET", "/artworks", headers=headers, params=params)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}", headers=headers)

    def patch_artwork(self, artwork_id, payload, headers):
        return self._request("PATCH", f"/artworks/{artwork_id}", payload, headers)

    def run_preflight(self, artwork_id, headers):
        return self._request("POST", f"/artworks/{artwork_id}/preflight", headers=headers)

    # ─── Proofs ───────────────────────────────────────────────────────────
    def create_proof(self, payload, headers):
        return self._request("POST", "/proofs", payload, headers)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/proofs", headers=headers, params=params)

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", headers=headers)

    def request_changes(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/request-changes", payload, headers)

    # ─── Fulfillments ─────────────────────────────────────────────────────
    def create_fulfillment(self, payload, headers):
        return self._request("POST", "/fulfillments", payload, headers)

    def list_fulfillments(self, headers, params=None):
        return self._request("GET", "/fulfillments", headers=headers, params=params)

    def get_fulfillment(self, fulfillment_id, headers):
        return self._request("GET", f"/fulfillments/{fulfillment_id}", headers=headers)

    def hand_off(self, fulfillment_id, headers):
        return self._request("POST", f"/fulfillments/{fulfillment_id}/hand-off", headers=headers)

    # ─── Press bookings ───────────────────────────────────────────────────
    def create_press_booking(self, payload, headers):
        return self._request("POST", "/press-bookings", payload, headers)

    def list_press_bookings(self, headers, params=None):
        return self._request("GET", "/press-bookings", headers=headers, params=params)

    def get_press_booking(self, press_booking_id, headers):
        return self._request("GET", f"/press-bookings/{press_booking_id}", headers=headers)

    def release_press_booking(self, press_booking_id, headers):
        return self._request("POST", f"/press-bookings/{press_booking_id}/release", headers=headers)

    # ─── Capacity reservations ────────────────────────────────────────────
    def list_capacity_reservations(self, headers, params=None):
        return self._request("GET", "/capacity-reservations", headers=headers, params=params)

    def get_capacity_reservation(self, capacity_reservation_id, headers):
        return self._request("GET", f"/capacity-reservations/{capacity_reservation_id}", headers=headers)

    # ─── Test-driving hooks ───────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def inject_customer_loyalty(self, payload, headers):
        return self._request("POST", "/_inject/customer-loyalty", payload, headers)


api_client = ApiClient()
