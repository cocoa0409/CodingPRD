"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ─────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Customer ──────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/status", payload, headers,
        )

    def adjust_loyalty(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/loyalty-adjustments", payload, headers,
        )

    # ─── Product ───────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    def restock_product(self, product_id, payload, headers):
        return self._request(
            "POST", f"/api/products/{product_id}/restock", payload, headers,
        )

    # ─── LicenseType ───────────────────────────────────────────
    def create_license_type(self, payload, headers):
        return self._request("POST", "/api/license-types", payload, headers)

    def get_license_type(self, license_type_id, headers):
        return self._request("GET", f"/api/license-types/{license_type_id}", headers=headers)

    # ─── LicenseSale ───────────────────────────────────────────
    def create_license_sale(self, payload, headers):
        return self._request("POST", "/api/license-sales", payload, headers)

    def get_license_sale(self, sale_id, headers):
        return self._request("GET", f"/api/license-sales/{sale_id}", headers=headers)

    def list_license_sales(self, headers, params=None):
        return self._request("GET", "/api/license-sales", headers=headers, params=params)

    def void_license_sale(self, sale_id, headers):
        return self._request("POST", f"/api/license-sales/{sale_id}/void", {}, headers)

    # ─── Guide ─────────────────────────────────────────────────
    def create_guide(self, payload, headers):
        return self._request("POST", "/api/guides", payload, headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/api/guides/{guide_id}", headers=headers)

    def set_guide_status(self, guide_id, payload, headers):
        return self._request("POST", f"/api/guides/{guide_id}/status", payload, headers)

    # ─── Charter ───────────────────────────────────────────────
    def create_charter(self, payload, headers):
        return self._request("POST", "/api/charters", payload, headers)

    def get_charter(self, charter_id, headers):
        return self._request("GET", f"/api/charters/{charter_id}", headers=headers)

    def list_charters(self, headers, params=None):
        return self._request("GET", "/api/charters", headers=headers, params=params)

    def reschedule_charter(self, charter_id, payload, headers):
        return self._request("PUT", f"/api/charters/{charter_id}", payload, headers)

    def cancel_charter(self, charter_id, headers):
        return self._request("POST", f"/api/charters/{charter_id}/cancel", {}, headers)

    # ─── CharterBooking ────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/api/charter-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/api/charter-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/api/charter-bookings", headers=headers, params=params)

    def pay_booking(self, booking_id, headers):
        return self._request("POST", f"/api/charter-bookings/{booking_id}/pay", {}, headers)

    def checkin_booking(self, booking_id, headers):
        return self._request("POST", f"/api/charter-bookings/{booking_id}/check-in", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/api/charter-bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/api/charter-bookings/{booking_id}/cancel", {}, headers)

    # ─── Tournament ────────────────────────────────────────────
    def create_tournament(self, payload, headers):
        return self._request("POST", "/api/tournaments", payload, headers)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/api/tournaments/{tournament_id}", headers=headers)

    def set_tournament_status(self, tournament_id, payload, headers):
        return self._request(
            "POST", f"/api/tournaments/{tournament_id}/status", payload, headers,
        )

    # ─── TournamentEntry ───────────────────────────────────────
    def create_entry(self, payload, headers):
        return self._request("POST", "/api/tournament-entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/api/tournament-entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/api/tournament-entries", headers=headers, params=params)

    def set_entry_status(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/api/tournament-entries/{entry_id}/status", payload, headers,
        )

    def weigh_in(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/api/tournament-entries/{entry_id}/weigh-in", payload, headers,
        )

    # ─── ServiceOrder ──────────────────────────────────────────
    def create_service_order(self, payload, headers):
        return self._request("POST", "/api/service-orders", payload, headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/api/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/api/service-orders", headers=headers, params=params)

    def transition_service_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/service-orders/{order_id}/transition", payload, headers,
        )


api_client = ApiClient()
