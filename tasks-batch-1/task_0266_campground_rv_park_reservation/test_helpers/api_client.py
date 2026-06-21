"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Clock -------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set", {"current_utc": current_utc}, headers)

    # ----- Park --------------------------------------------------------------
    def create_park(self, payload, headers):
        return self._request("POST", "/parks", payload, headers)

    def get_park(self, park_id, headers):
        return self._request("GET", f"/parks/{park_id}", headers=headers)

    def update_park(self, park_id, payload, headers):
        return self._request("PATCH", f"/parks/{park_id}", payload, headers)

    # ----- RatePlan ----------------------------------------------------------
    def create_rate_plan(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/rate-plans", payload, headers)

    def list_park_rate_plans(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/rate-plans", headers=headers, params=params)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/rate-plans/{rate_plan_id}", headers=headers)

    # ----- Season ------------------------------------------------------------
    def create_season(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/seasons", payload, headers)

    def list_park_seasons(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/seasons", headers=headers, params=params)

    # ----- CancellationPolicy ------------------------------------------------
    def create_cancellation_policy(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/cancellation-policies", payload, headers)

    def list_park_cancellation_policies(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/cancellation-policies", headers=headers, params=params)

    # ----- Site --------------------------------------------------------------
    def create_site(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def list_park_sites(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/sites", headers=headers, params=params)

    def maintenance_site(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/maintenance", payload, headers)

    def reactivate_site(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/reactivate", payload, headers)

    def retire_site(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/retire", payload, headers)

    # ----- MaintenanceHold ---------------------------------------------------
    def create_maintenance_hold(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/maintenance-holds", payload, headers)

    def list_maintenance_holds(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/maintenance-holds", headers=headers, params=params)

    def clear_maintenance_hold(self, hold_id, headers):
        return self._request("POST", f"/maintenance-holds/{hold_id}/clear", {}, headers)

    # ----- Guest -------------------------------------------------------------
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def list_guest_reservations(self, guest_id, headers, params=None):
        return self._request("GET", f"/guests/{guest_id}/reservations", headers=headers, params=params)

    # ----- Reservation -------------------------------------------------------
    def create_reservation(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_site_reservations(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", {}, headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", {}, headers)

    def check_out_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-out", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    # ----- AddOn -------------------------------------------------------------
    def create_add_on(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/add-ons", payload, headers)

    def list_add_ons(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/add-ons", headers=headers, params=params)

    def remove_add_on(self, add_on_id, headers):
        return self._request("POST", f"/add-ons/{add_on_id}/remove", {}, headers)

    # ----- Payment -----------------------------------------------------------
    def create_payment(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/payments", payload, headers)

    def list_payments(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/payments", headers=headers, params=params)


api_client = ApiClient()
