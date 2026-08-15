"""API client: one method per endpoint declared in PRD section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Karting League & Race Series Management API."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        # Per-test-server isolation restarts the API server before every test
        # on the same port. A pooled keep-alive connection can then point at
        # the killed server instance, and writing to it fails with
        # RemoteDisconnected / ConnectionResetError (requests' default
        # adapter applies no retries, and POST/PATCH are never retried).
        # Forcing Connection: close hands every request a fresh TCP
        # connection to the live server, eliminating the stale-pool race
        # without any retry-double-apply risk.
        hdrs = dict(headers or {})
        hdrs["Connection"] = "close"
        return super()._request(method, path, payload, headers=hdrs, params=params)

    # --- Seasons ---
    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/karting/seasons", payload, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/seasons/{season_id}", headers=headers)

    def activate_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/seasons/{season_id}/activate", {}, headers)

    def finalize_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/seasons/{season_id}/finalize", {}, headers)

    def conclude_awards(self, season_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/seasons/{season_id}/conclude-awards", {}, headers
        )

    def get_standings(
        self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/karting/seasons/{season_id}/standings", headers=headers, params=params
        )

    # --- Classes ---
    def create_class(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/karting/seasons/{season_id}/classes", payload, headers)

    def list_classes(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/seasons/{season_id}/classes", headers=headers)

    def get_class(self, class_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/classes/{class_id}", headers=headers)

    # --- Drivers ---
    def create_driver(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/karting/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/drivers/{driver_id}", headers=headers)

    def update_driver(self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/karting/drivers/{driver_id}", payload, headers)

    # --- Rental karts ---
    def create_kart(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/karting/karts", payload, headers)

    def get_kart(self, kart_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/karts/{kart_id}", headers=headers)

    def list_karts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/karting/karts", headers=headers, params=params)

    def update_kart(self, kart_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/karting/karts/{kart_id}", payload, headers)

    # --- Events ---
    def create_event(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/karting/seasons/{season_id}/events", payload, headers)

    def list_events(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/seasons/{season_id}/events", headers=headers)

    def get_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/events/{event_id}", headers=headers)

    def open_registration(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/events/{event_id}/open-registration", {}, headers
        )

    def start_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/start", {}, headers)

    def complete_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/complete", {}, headers)

    def finalize_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/finalize", {}, headers)

    def cancel_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/cancel", {}, headers)

    def lock_grid(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/lock-grid", {}, headers)

    # --- Entries ---
    def create_entry(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/entries", payload, headers)

    def list_event_entries(
        self, event_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/karting/events/{event_id}/entries", headers=headers, params=params
        )

    def get_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/entries/{entry_id}", headers=headers)

    def list_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/karting/entries", headers=headers, params=params)

    def pay_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/entries/{entry_id}/pay", {}, headers)

    def withdraw_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/entries/{entry_id}/withdraw", {}, headers)

    # --- Technical inspections ---
    def create_inspection(self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/entries/{entry_id}/inspections", payload, headers
        )

    def list_inspections(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/entries/{entry_id}/inspections", headers=headers)

    # --- Sessions & results ---
    def create_session(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/sessions", payload, headers)

    def list_sessions(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/events/{event_id}/sessions", headers=headers)

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/sessions/{session_id}", headers=headers)

    def update_session(self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/karting/sessions/{session_id}", payload, headers)

    def submit_results(self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/sessions/{session_id}/results", payload, headers
        )

    def score_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/sessions/{session_id}/score", {}, headers)

    def list_session_results(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/sessions/{session_id}/results", headers=headers)

    def list_entry_results(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/entries/{entry_id}/results", headers=headers)

    # --- Incidents ---
    def create_incident(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/karting/events/{event_id}/incidents", payload, headers)

    def list_event_incidents(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/events/{event_id}/incidents", headers=headers)

    def get_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/karting/incidents", headers=headers, params=params)

    def open_incident_review(self, incident_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/incidents/{incident_id}/open-review", {}, headers
        )

    def adjudicate_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/karting/incidents/{incident_id}/adjudicate", payload, headers
        )

    def appeal_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/karting/incidents/{incident_id}/appeal", {}, headers)

    # --- Practice bookings ---
    def create_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/karting/practice-bookings", payload, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/karting/practice-bookings", headers=headers, params=params)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/karting/practice-bookings/{booking_id}", headers=headers)

    def check_in_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/practice-bookings/{booking_id}/check-in", {}, headers
        )

    def check_out_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/practice-bookings/{booking_id}/check-out", {}, headers
        )

    def cancel_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/karting/practice-bookings/{booking_id}/cancel", {}, headers
        )


api_client = ApiClient()
