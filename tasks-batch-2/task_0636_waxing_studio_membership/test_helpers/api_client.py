"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Locations ----
    def create_location(self, payload, headers):
        return self._request("POST", "/studio/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/studio/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/studio/locations", headers=headers, params=params)

    # ---- ServiceTypes ----
    def create_service_type(self, payload, headers):
        return self._request("POST", "/studio/service-types", payload, headers)

    def get_service_type(self, service_type_id, headers):
        return self._request("GET", f"/studio/service-types/{service_type_id}", headers=headers)

    def list_service_types(self, headers, params=None):
        return self._request("GET", "/studio/service-types", headers=headers, params=params)

    def update_service_type(self, service_type_id, payload, headers):
        return self._request("PATCH", f"/studio/service-types/{service_type_id}", payload, headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/studio/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/studio/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/studio/products", headers=headers, params=params)

    # ---- Rooms ----
    def create_room(self, payload, headers):
        return self._request("POST", "/studio/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/studio/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/studio/rooms", headers=headers, params=params)

    # ---- Technicians ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/studio/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/studio/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/studio/technicians", headers=headers, params=params)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/studio/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/studio/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/studio/members", headers=headers, params=params)

    # ---- Memberships ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/studio/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/studio/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/studio/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"/studio/memberships/{membership_id}/activate", {}, headers)

    def freeze_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/studio/memberships/{membership_id}/freeze", payload, headers)

    def unfreeze_membership(self, membership_id, headers):
        return self._request("POST", f"/studio/memberships/{membership_id}/unfreeze", {}, headers)

    def renew_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/studio/memberships/{membership_id}/renew", payload, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/studio/memberships/{membership_id}/cancel", {}, headers)

    def list_membership_ledger(self, membership_id, headers, params=None):
        return self._request("GET", f"/studio/memberships/{membership_id}/ledger", headers=headers, params=params)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/studio/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/studio/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/studio/reservations", headers=headers, params=params)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio/reservations/{reservation_id}/check-in", {}, headers)

    def complete_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio/reservations/{reservation_id}/complete", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio/reservations/{reservation_id}/cancel", {}, headers)

    def mark_no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio/reservations/{reservation_id}/mark-no-show", {}, headers)

    # ---- Retail sales ----
    def create_retail_sale(self, payload, headers):
        return self._request("POST", "/studio/retail-sales", payload, headers)

    def get_retail_sale(self, sale_id, headers):
        return self._request("GET", f"/studio/retail-sales/{sale_id}", headers=headers)

    def list_retail_sales(self, headers, params=None):
        return self._request("GET", "/studio/retail-sales", headers=headers, params=params)

    def confirm_retail_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/studio/retail-sales/{sale_id}/confirm", payload, headers)

    def void_retail_sale(self, sale_id, headers):
        return self._request("POST", f"/studio/retail-sales/{sale_id}/void", {}, headers)

    # ---- No-show strikes ----
    def get_no_show_strike(self, strike_id, headers):
        return self._request("GET", f"/studio/no-show-strikes/{strike_id}", headers=headers)

    def list_no_show_strikes(self, headers, params=None):
        return self._request("GET", "/studio/no-show-strikes", headers=headers, params=params)

    def waive_no_show_strike(self, strike_id, headers):
        return self._request("POST", f"/studio/no-show-strikes/{strike_id}/waive", {}, headers)

    # ---- Logical clock + sweeps ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/studio/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_sweeps(self, headers):
        return self._request("POST", "/studio/_clock/run_sweeps", {}, headers)


api_client = ApiClient()
