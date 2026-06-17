"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() method is inherited. Paths are
mounted at the API root (no prefix).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Farm ------------------------------------------------------------
    def create_farm(self, payload, headers):
        return self._request("POST", "/farms", payload, headers)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"/farms/{farm_id}", headers=headers)

    # --- WeatherEvent ----------------------------------------------------
    def create_weather_event(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/weather-events", payload, headers)

    def list_weather_events(self, farm_id, headers, params=None):
        return self._request("GET", f"/farms/{farm_id}/weather-events", headers=headers, params=params)

    # --- PricingPolicy ---------------------------------------------------
    def create_pricing_policy(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/pricing-policies", payload, headers)

    def activate_pricing_policy(self, policy_id, headers):
        return self._request("POST", f"/pricing-policies/{policy_id}/activate", headers=headers)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    def list_pricing_policies(self, farm_id, headers, params=None):
        return self._request("GET", f"/farms/{farm_id}/pricing-policies", headers=headers, params=params)

    # --- AdmissionWindow -------------------------------------------------
    def create_admission_window(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/admission-windows", payload, headers)

    def get_admission_window(self, window_id, headers):
        return self._request("GET", f"/admission-windows/{window_id}", headers=headers)

    def list_admission_windows(self, farm_id, headers, params=None):
        return self._request("GET", f"/farms/{farm_id}/admission-windows", headers=headers, params=params)

    def mark_no_shows(self, window_id, headers):
        return self._request("POST", f"/admission-windows/{window_id}/mark-no-shows", headers=headers)

    def list_window_reservations(self, window_id, headers, params=None):
        return self._request("GET", f"/admission-windows/{window_id}/reservations", headers=headers, params=params)

    def list_window_group_bookings(self, window_id, headers, params=None):
        return self._request("GET", f"/admission-windows/{window_id}/group-bookings", headers=headers, params=params)

    # --- Visitor ---------------------------------------------------------
    def create_visitor(self, payload, headers):
        return self._request("POST", "/visitors", payload, headers)

    def get_visitor(self, visitor_id, headers):
        return self._request("GET", f"/visitors/{visitor_id}", headers=headers)

    def list_visitor_season_passes(self, visitor_id, headers, params=None):
        return self._request("GET", f"/visitors/{visitor_id}/season-passes", headers=headers, params=params)

    def list_visitor_group_bookings(self, visitor_id, headers, params=None):
        return self._request("GET", f"/visitors/{visitor_id}/group-bookings", headers=headers, params=params)

    def list_visitor_reservations(self, visitor_id, headers, params=None):
        return self._request("GET", f"/visitors/{visitor_id}/reservations", headers=headers, params=params)

    # --- SeasonPass ------------------------------------------------------
    def create_season_pass(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/season-passes", payload, headers)

    def get_season_pass(self, pass_id, headers):
        return self._request("GET", f"/season-passes/{pass_id}", headers=headers)

    def list_farm_season_passes(self, farm_id, headers, params=None):
        return self._request("GET", f"/farms/{farm_id}/season-passes", headers=headers, params=params)

    def revoke_season_pass(self, pass_id, headers):
        return self._request("POST", f"/season-passes/{pass_id}/revoke", headers=headers)

    def list_season_pass_reservations(self, pass_id, headers, params=None):
        return self._request("GET", f"/season-passes/{pass_id}/reservations", headers=headers, params=params)

    # --- Reservation -----------------------------------------------------
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def get_reservation_total(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}/total", headers=headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", headers=headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", headers=headers)

    def settle_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/settle", headers=headers)

    def list_group_reservations(self, group_id, headers, params=None):
        return self._request("GET", f"/group-bookings/{group_id}/reservations", headers=headers, params=params)

    # --- ActivityPass ----------------------------------------------------
    def create_activity_pass(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/activity-passes", payload, headers)

    def list_activity_passes(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/activity-passes", headers=headers, params=params)

    # --- Waiver ----------------------------------------------------------
    def create_waiver(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/waivers", payload, headers)

    def list_waivers(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/waivers", headers=headers, params=params)

    # --- PumpkinPurchase -------------------------------------------------
    def create_pumpkin_purchase(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/pumpkin-purchases", payload, headers)

    def weigh_out_pumpkin(self, pumpkin_id, payload, headers):
        return self._request("POST", f"/pumpkin-purchases/{pumpkin_id}/weigh-out", payload, headers)

    def list_pumpkin_purchases(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/pumpkin-purchases", headers=headers, params=params)

    # --- ConcessionOrder -------------------------------------------------
    def create_concession_order(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/concession-orders", payload, headers)

    def list_concession_orders(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/concession-orders", headers=headers, params=params)

    # --- GroupBooking ----------------------------------------------------
    def create_group_booking(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/group-bookings", payload, headers)

    def get_group_booking(self, group_id, headers):
        return self._request("GET", f"/group-bookings/{group_id}", headers=headers)

    def list_farm_group_bookings(self, farm_id, headers, params=None):
        return self._request("GET", f"/farms/{farm_id}/group-bookings", headers=headers, params=params)

    def list_sub_groups(self, group_id, headers, params=None):
        return self._request("GET", f"/group-bookings/{group_id}/sub-groups", headers=headers, params=params)

    def edit_group_booking(self, group_id, payload, headers):
        return self._request("PATCH", f"/group-bookings/{group_id}", payload, headers)

    def revise_group_booking(self, group_id, headers):
        return self._request("POST", f"/group-bookings/{group_id}/revise", headers=headers)

    def requote_group_booking(self, group_id, headers):
        return self._request("POST", f"/group-bookings/{group_id}/requote", headers=headers)

    def confirm_group_booking(self, group_id, payload, headers):
        return self._request("POST", f"/group-bookings/{group_id}/confirm", payload, headers)

    def cancel_group_booking(self, group_id, headers):
        return self._request("POST", f"/group-bookings/{group_id}/cancel", headers=headers)

    # --- Test-driving clock ----------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
