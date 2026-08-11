"""API client: one method per endpoint defined in PRD §4.

All resources are mounted under the /dispatch prefix (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Stations ---
    def create_station(self, payload, headers):
        return self._request("POST", "/dispatch/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/dispatch/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/dispatch/stations", headers=headers, params=params)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/dispatch/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/dispatch/aircraft/{aircraft_id}", headers=headers)

    # --- Dispatchers ---
    def create_dispatcher(self, payload, headers):
        return self._request("POST", "/dispatch/dispatchers", payload, headers)

    def get_dispatcher(self, dispatcher_id, headers):
        return self._request("GET", f"/dispatch/dispatchers/{dispatcher_id}", headers=headers)

    # --- Captains ---
    def create_captain(self, payload, headers):
        return self._request("POST", "/dispatch/captains", payload, headers)

    def get_captain(self, captain_id, headers):
        return self._request("GET", f"/dispatch/captains/{captain_id}", headers=headers)

    # --- Desks ---
    def create_desk(self, payload, headers):
        return self._request("POST", "/dispatch/desks", payload, headers)

    def get_desk(self, desk_id, headers):
        return self._request("GET", f"/dispatch/desks/{desk_id}", headers=headers)

    # --- Desk shifts ---
    def create_desk_shift(self, payload, headers):
        return self._request("POST", "/dispatch/desk-shifts", payload, headers)

    def get_desk_shift(self, shift_id, headers):
        return self._request("GET", f"/dispatch/desk-shifts/{shift_id}", headers=headers)

    def list_desk_shifts(self, headers, params=None):
        return self._request("GET", "/dispatch/desk-shifts", headers=headers, params=params)

    # --- Flight legs ---
    def create_leg(self, payload, headers):
        return self._request("POST", "/dispatch/legs", payload, headers)

    def get_leg(self, leg_id, headers):
        return self._request("GET", f"/dispatch/legs/{leg_id}", headers=headers)

    def list_legs(self, headers, params=None):
        return self._request("GET", "/dispatch/legs", headers=headers, params=params)

    def delay_leg(self, leg_id, payload, headers):
        return self._request("POST", f"/dispatch/legs/{leg_id}/delay", payload, headers)

    def cancel_leg(self, leg_id, payload, headers):
        return self._request("POST", f"/dispatch/legs/{leg_id}/cancel", payload, headers)

    def depart_leg(self, leg_id, headers):
        return self._request("POST", f"/dispatch/legs/{leg_id}/depart", {}, headers)

    def arrive_leg(self, leg_id, headers):
        return self._request("POST", f"/dispatch/legs/{leg_id}/arrive", {}, headers)

    def divert_leg(self, leg_id, payload, headers):
        return self._request("POST", f"/dispatch/legs/{leg_id}/divert", payload, headers)

    # --- Flight plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/dispatch/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/dispatch/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/dispatch/plans", headers=headers, params=params)

    def lock_plan(self, plan_id, headers):
        return self._request("POST", f"/dispatch/plans/{plan_id}/lock", {}, headers)

    def recompute_plan(self, plan_id, headers):
        return self._request("POST", f"/dispatch/plans/{plan_id}/recompute", {}, headers)

    # --- Payload manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/dispatch/manifests", payload, headers)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/dispatch/manifests/{manifest_id}", headers=headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/dispatch/manifests", headers=headers, params=params)

    def update_manifest(self, manifest_id, payload, headers):
        return self._request("PUT", f"/dispatch/manifests/{manifest_id}", payload, headers)

    # --- MEL / CDL ---
    def create_mel_item(self, payload, headers):
        return self._request("POST", "/dispatch/mel-items", payload, headers)

    def get_mel_item(self, item_id, headers):
        return self._request("GET", f"/dispatch/mel-items/{item_id}", headers=headers)

    def list_mel_items(self, headers, params=None):
        return self._request("GET", "/dispatch/mel-items", headers=headers, params=params)

    def clear_mel_item(self, item_id, headers):
        return self._request("POST", f"/dispatch/mel-items/{item_id}/clear", {}, headers)

    # --- Weather packages ---
    def create_weather_package(self, payload, headers):
        return self._request("POST", "/dispatch/weather-packages", payload, headers)

    def get_weather_package(self, package_id, headers):
        return self._request("GET", f"/dispatch/weather-packages/{package_id}", headers=headers)

    def list_weather_packages(self, headers, params=None):
        return self._request("GET", "/dispatch/weather-packages", headers=headers, params=params)

    def replace_weather_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/dispatch/weather-packages/{package_id}/replace", payload, headers
        )

    # --- Releases ---
    def create_release(self, payload, headers):
        return self._request("POST", "/dispatch/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/dispatch/releases/{release_id}", headers=headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/dispatch/releases", headers=headers, params=params)

    def submit_release(self, release_id, headers):
        return self._request("POST", f"/dispatch/releases/{release_id}/submit", {}, headers)

    def sign_release(self, release_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatch/releases/{release_id}/sign", payload or {}, headers
        )

    def recall_release(self, release_id, headers):
        return self._request("POST", f"/dispatch/releases/{release_id}/recall", {}, headers)

    def amend_release(self, release_id, headers):
        return self._request("POST", f"/dispatch/releases/{release_id}/amend", {}, headers)

    def list_release_signatures(self, release_id, headers, params=None):
        return self._request(
            "GET", f"/dispatch/releases/{release_id}/signatures", headers=headers, params=params
        )

    # --- En-route monitoring ---
    def create_monitoring_event(self, payload, headers):
        return self._request("POST", "/dispatch/monitoring-events", payload, headers)

    def get_monitoring_event(self, event_id, headers):
        return self._request("GET", f"/dispatch/monitoring-events/{event_id}", headers=headers)

    def list_monitoring_events(self, headers, params=None):
        return self._request("GET", "/dispatch/monitoring-events", headers=headers, params=params)

    def acknowledge_monitoring_event(self, event_id, headers):
        return self._request(
            "POST", f"/dispatch/monitoring-events/{event_id}/acknowledge", {}, headers
        )

    # --- Operational control records ---
    def list_control_records(self, leg_id, headers, params=None):
        return self._request(
            "GET", f"/dispatch/legs/{leg_id}/control-records", headers=headers, params=params
        )

    # --- Test-driving logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/dispatch/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
