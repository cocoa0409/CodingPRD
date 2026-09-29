"""
Domain API client: one method per endpoint in PRD section 4.

All resources are addressed from the root of the service; there is no URL
prefix in front of the collection names.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json


class ApiClient(GenericApiClient):
    """Thin typed wrapper over the HTTP surface described in PRD section 4."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Venues
    # ------------------------------------------------------------------
    def create_venue(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/venues/{venue_id}", None, headers)

    def list_venue_installations(
        self, venue_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/venues/{venue_id}/installations", None, headers, params=params
        )

    # ------------------------------------------------------------------
    # Tracking installations
    # ------------------------------------------------------------------
    def create_installation(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/installations", payload, headers)

    def get_installation(self, installation_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/installations/{installation_id}", None, headers)

    def create_calibration_run(
        self, installation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/installations/{installation_id}/calibration-runs", payload, headers
        )

    def list_calibration_runs(
        self, installation_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/installations/{installation_id}/calibration-runs",
            None,
            headers,
            params=params,
        )

    def certify_installation(self, installation_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/installations/{installation_id}/certify", {}, headers
        )

    def flag_drift(self, installation_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/installations/{installation_id}/flag-drift", {}, headers
        )

    def retire_installation(self, installation_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/installations/{installation_id}/retire", {}, headers
        )

    # ------------------------------------------------------------------
    # Clubs and players
    # ------------------------------------------------------------------
    def create_club(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/clubs", payload, headers)

    def get_club(self, club_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/clubs/{club_id}", None, headers)

    def create_player(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/players/{player_id}", None, headers)

    def list_players(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/players", None, headers, params=params)

    # ------------------------------------------------------------------
    # Consent records
    # ------------------------------------------------------------------
    def create_consent_record(
        self, player_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/players/{player_id}/consent-records", payload, headers
        )

    def list_consent_records(
        self, player_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/players/{player_id}/consent-records", None, headers, params=params
        )

    def ratify_consent_record(self, record_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/consent-records/{record_id}/ratify", {}, headers
        )

    def withdraw_consent_record(self, record_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/consent-records/{record_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Games
    # ------------------------------------------------------------------
    def create_game(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/games", payload, headers)

    def get_game(self, game_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/games/{game_id}", None, headers)

    def list_games(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/games", None, headers, params=params)

    def open_collection(self, game_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/games/{game_id}/open-collection", {}, headers)

    def close_collection(self, game_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/games/{game_id}/close-collection", {}, headers)

    def resume_collection(self, game_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/games/{game_id}/resume-collection", {}, headers)

    def certify_game(self, game_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/games/{game_id}/certify", {}, headers)

    # ------------------------------------------------------------------
    # Event tags
    # ------------------------------------------------------------------
    def create_event_tag(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/event-tags", payload, headers)

    def get_event_tag(self, tag_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/event-tags/{tag_id}", None, headers)

    def list_event_tags(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/event-tags", None, headers, params=params)

    def submit_event_tag(self, tag_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/event-tags/{tag_id}/submit", {}, headers)

    def accept_event_tag(self, tag_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/event-tags/{tag_id}/accept", {}, headers)

    # ------------------------------------------------------------------
    # Correction requests
    # ------------------------------------------------------------------
    def create_correction_request(
        self, tag_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/event-tags/{tag_id}/correction-requests", payload, headers
        )

    def list_correction_requests(
        self, tag_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/event-tags/{tag_id}/correction-requests", None, headers, params=params
        )

    def approve_correction(self, correction_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/correction-requests/{correction_id}/approve", {}, headers
        )

    def reject_correction(self, correction_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/correction-requests/{correction_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Rights windows
    # ------------------------------------------------------------------
    def create_rights_window(
        self, game_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/games/{game_id}/rights-windows", payload, headers
        )

    def list_rights_windows(
        self, game_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/games/{game_id}/rights-windows", None, headers, params=params
        )

    def revoke_rights_window(self, window_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/rights-windows/{window_id}/revoke", {}, headers
        )

    # ------------------------------------------------------------------
    # Licensees
    # ------------------------------------------------------------------
    def create_licensee(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/licensees", payload, headers)

    def get_licensee(self, licensee_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/licensees/{licensee_id}", None, headers)

    def list_licensee_usage_records(
        self, licensee_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/licensees/{licensee_id}/usage-records", None, headers, params=params
        )

    # ------------------------------------------------------------------
    # Feed sessions
    # ------------------------------------------------------------------
    def create_feed_session(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/feed-sessions", payload, headers)

    def get_feed_session(self, session_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/feed-sessions/{session_id}", None, headers)

    def list_feed_sessions(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/feed-sessions", None, headers, params=params)

    def create_usage_record(
        self, session_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/feed-sessions/{session_id}/usage-records", payload, headers
        )

    def list_usage_records(
        self, session_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/feed-sessions/{session_id}/usage-records", None, headers, params=params
        )

    def terminate_feed_session(self, session_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/feed-sessions/{session_id}/terminate", {}, headers
        )

    # ------------------------------------------------------------------
    # Normalization runs
    # ------------------------------------------------------------------
    def create_normalization_run(
        self, game_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/games/{game_id}/normalization-runs", payload, headers
        )

    def list_normalization_runs(
        self, game_id: str, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/games/{game_id}/normalization-runs", None, headers, params=params
        )
