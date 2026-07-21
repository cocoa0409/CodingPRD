"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def list_customer_licenses(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/licenses", headers=headers, params=params)

    def list_customer_service_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/service-orders", headers=headers, params=params)

    def list_customer_sales(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/sales", headers=headers, params=params)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    # --- Fishing licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def void_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/void", headers=headers)

    # --- Bait tanks ---
    def create_bait_tank(self, payload, headers):
        return self._request("POST", "/bait-tanks", payload, headers)

    def get_bait_tank(self, tank_id, headers):
        return self._request("GET", f"/bait-tanks/{tank_id}", headers=headers)

    def list_bait_tanks(self, headers, params=None):
        return self._request("GET", "/bait-tanks", headers=headers, params=params)

    def deliver_batch(self, tank_id, payload, headers):
        return self._request("POST", f"/bait-tanks/{tank_id}/batches", payload, headers)

    def dispense_bait(self, tank_id, payload, headers):
        return self._request("POST", f"/bait-tanks/{tank_id}/dispense", payload, headers)

    def return_bait(self, tank_id, payload, headers):
        return self._request("POST", f"/bait-tanks/{tank_id}/returns", payload, headers)

    # --- Guides ---
    def create_guide(self, payload, headers):
        return self._request("POST", "/guides", payload, headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/guides/{guide_id}", headers=headers)

    def list_guides(self, headers, params=None):
        return self._request("GET", "/guides", headers=headers, params=params)

    def update_guide(self, guide_id, payload, headers):
        return self._request("PATCH", f"/guides/{guide_id}", payload, headers)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    # --- Charter bookings ---
    def create_charter_booking(self, payload, headers):
        return self._request("POST", "/charter-bookings", payload, headers)

    def get_charter_booking(self, booking_id, headers):
        return self._request("GET", f"/charter-bookings/{booking_id}", headers=headers)

    def list_charter_bookings(self, headers, params=None):
        return self._request("GET", "/charter-bookings", headers=headers, params=params)

    def transition_charter_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/charter-bookings/{booking_id}/transition", payload, headers)

    # --- Tournaments ---
    def create_tournament(self, payload, headers):
        return self._request("POST", "/tournaments", payload, headers)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/tournaments/{tournament_id}", headers=headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/tournaments", headers=headers, params=params)

    def transition_tournament(self, tournament_id, payload, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/transition", payload, headers)

    def create_tournament_entry(self, tournament_id, payload, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/entries", payload, headers)

    # --- Tournament entries ---
    def get_tournament_entry(self, entry_id, headers):
        return self._request("GET", f"/tournament-entries/{entry_id}", headers=headers)

    def list_tournament_entries(self, headers, params=None):
        return self._request("GET", "/tournament-entries", headers=headers, params=params)

    def create_weigh_in(self, entry_id, payload, headers):
        return self._request("POST", f"/tournament-entries/{entry_id}/weigh-ins", payload, headers)

    # --- Service orders ---
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def transition_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/transition", payload, headers)

    # --- Special orders ---
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def transition_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/transition", payload, headers)

    # --- Sales ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def add_sale_line(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/lines", payload, headers)

    def transition_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/transition", payload, headers)


api_client = ApiClient()
