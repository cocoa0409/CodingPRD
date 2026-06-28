"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Locations --------------------------------------------------------
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def close_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/close", {}, headers)

    # ---- Flexologists -----------------------------------------------------
    def create_flexologist(self, payload, headers):
        return self._request("POST", "/flexologists", payload, headers)

    def list_flexologists(self, headers, params=None):
        return self._request("GET", "/flexologists", headers=headers, params=params)

    def get_flexologist(self, flexologist_id, headers):
        return self._request("GET", f"/flexologists/{flexologist_id}", headers=headers)

    def deactivate_flexologist(self, flexologist_id, headers):
        return self._request("POST", f"/flexologists/{flexologist_id}/deactivate", {}, headers)

    # ---- Tables -----------------------------------------------------------
    def create_table(self, payload, headers):
        return self._request("POST", "/tables", payload, headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/tables", headers=headers, params=params)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/tables/{table_id}", headers=headers)

    def take_table_out_of_service(self, table_id, headers):
        return self._request("POST", f"/tables/{table_id}/take-out-of-service", {}, headers)

    # ---- Services ---------------------------------------------------------
    def create_service(self, payload, headers):
        return self._request("POST", "/services", payload, headers)

    def list_services(self, headers, params=None):
        return self._request("GET", "/services", headers=headers, params=params)

    def get_service(self, service_id, headers):
        return self._request("GET", f"/services/{service_id}", headers=headers)

    def retire_service(self, service_id, headers):
        return self._request("POST", f"/services/{service_id}/retire", {}, headers)

    # ---- Members ----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    def list_member_no_show_events(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/no-show-events", headers=headers, params=params)

    # ---- Memberships ------------------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def freeze_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/freeze", payload, headers)

    def unfreeze_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/unfreeze", payload, headers)

    def cancel_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", payload, headers)

    def renew_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/renew", {}, headers)

    # ---- Credit packs -----------------------------------------------------
    def create_credit_pack(self, payload, headers):
        return self._request("POST", "/credit-packs", payload, headers)

    def list_credit_packs(self, headers, params=None):
        return self._request("GET", "/credit-packs", headers=headers, params=params)

    def get_credit_pack(self, credit_pack_id, headers):
        return self._request("GET", f"/credit-packs/{credit_pack_id}", headers=headers)

    # ---- Bookings ---------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def complete_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/bookings/{booking_id}/complete", payload or {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule", payload, headers)

    def add_addon(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/add-ons", payload, headers)

    def list_addons(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/add-ons", headers=headers, params=params)

    def list_booking_no_show_events(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/no-show-events", headers=headers, params=params)

    # ---- Recurring series -------------------------------------------------
    def create_recurring_series(self, payload, headers):
        return self._request("POST", "/recurring-series", payload, headers)

    def list_recurring_series(self, headers, params=None):
        return self._request("GET", "/recurring-series", headers=headers, params=params)

    def get_recurring_series(self, series_id, headers):
        return self._request("GET", f"/recurring-series/{series_id}", headers=headers)

    def activate_recurring_series(self, series_id, headers):
        return self._request("POST", f"/recurring-series/{series_id}/activate", {}, headers)

    def cancel_recurring_series(self, series_id, headers):
        return self._request("POST", f"/recurring-series/{series_id}/cancel", {}, headers)

    # ---- Ops / test-driving ----------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def no_show_sweep(self, headers, payload=None):
        return self._request("POST", "/_ops/no_show_sweep", payload or {}, headers)


api_client = ApiClient()
