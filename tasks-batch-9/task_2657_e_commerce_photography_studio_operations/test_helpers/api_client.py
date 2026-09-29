"""HTTP client for the Studio Operations API.

One method per row of the PRD §4 endpoint table. Every path is mounted under
the `/studio` prefix and every resource is addressed flatly by its own
identifier (§2.10) — there is no URL nesting anywhere in this client.

All methods return the raw `requests.Response` so that tests can assert on the
status code as well as the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for `/studio`."""

    # ─── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/studio/_clock/set_current_utc", payload, headers
        )

    # ─── Vendors ───────────────────────────────────────────────────────────

    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio/vendors/{vendor_id}", None, headers)

    # ─── Asset profiles ────────────────────────────────────────────────────

    def create_asset_profile(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/asset-profiles", payload, headers)

    def get_asset_profile(self, profile_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/asset-profiles/{profile_id}", None, headers
        )

    # ─── Stations ──────────────────────────────────────────────────────────

    def create_station(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/stations", payload, headers)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio/stations/{station_id}", None, headers)

    # ─── Talent profiles ───────────────────────────────────────────────────

    def create_talent_profile(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/talent-profiles", payload, headers)

    def get_talent_profile(self, talent_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/talent-profiles/{talent_id}", None, headers
        )

    # ─── Studio providers ──────────────────────────────────────────────────

    def create_studio_provider(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/studio-providers", payload, headers)

    def get_studio_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/studio-providers/{provider_id}", None, headers
        )

    # ─── Styles ────────────────────────────────────────────────────────────

    def create_style(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/styles", payload, headers)

    def get_style(self, style_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio/styles/{style_id}", None, headers)

    def list_styles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/studio/styles", params, headers)

    def get_cost_summary(self, style_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/styles/{style_id}/cost-summary", None, headers
        )

    # ─── Samples ───────────────────────────────────────────────────────────

    def create_sample(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/samples", payload, headers)

    def get_sample(self, sample_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio/samples/{sample_id}", None, headers)

    def list_samples(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/studio/samples", params, headers)

    def receive_sample(
        self,
        sample_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/samples/{sample_id}/receive", payload or {}, headers
        )

    def match_sample(
        self, sample_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/studio/samples/{sample_id}/match", payload, headers
        )

    def custody_move_sample(
        self, sample_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/studio/samples/{sample_id}/custody-move", payload, headers
        )

    def return_sample(
        self,
        sample_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/samples/{sample_id}/return", payload or {}, headers
        )

    def report_lost_sample(
        self,
        sample_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/samples/{sample_id}/report-lost", payload or {}, headers
        )

    # ─── Release documents ─────────────────────────────────────────────────

    def create_release_document(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/release-documents", payload, headers)

    def get_release_document(self, release_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/release-documents/{release_id}", None, headers
        )

    def list_release_documents(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/studio/release-documents", params, headers)

    def sign_release_document(
        self,
        release_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/studio/release-documents/{release_id}/sign",
            payload or {},
            headers,
        )

    # ─── Shoot sessions ────────────────────────────────────────────────────

    def create_shoot_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/shoot-sessions", payload, headers)

    def get_shoot_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/shoot-sessions/{session_id}", None, headers
        )

    def list_shoot_sessions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/studio/shoot-sessions", params, headers)

    def lock_session(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/shoot-sessions/{session_id}/lock", payload or {}, headers
        )

    def unlock_session(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/studio/shoot-sessions/{session_id}/unlock",
            payload or {},
            headers,
        )

    def cancel_session(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/studio/shoot-sessions/{session_id}/cancel",
            payload or {},
            headers,
        )

    def start_session(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/shoot-sessions/{session_id}/start", payload or {}, headers
        )

    def submit_color_measurement(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/studio/shoot-sessions/{session_id}/color-measurement",
            payload,
            headers,
        )

    def wrap_session(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/shoot-sessions/{session_id}/wrap", payload or {}, headers
        )

    # ─── Talent bookings ───────────────────────────────────────────────────

    def create_talent_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/talent-bookings", payload, headers)

    def get_talent_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/talent-bookings/{booking_id}", None, headers
        )

    def list_talent_bookings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/studio/talent-bookings", params, headers)

    def confirm_booking(
        self,
        booking_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/studio/talent-bookings/{booking_id}/confirm",
            payload or {},
            headers,
        )

    def cancel_booking(
        self,
        booking_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/studio/talent-bookings/{booking_id}/cancel",
            payload or {},
            headers,
        )

    # ─── Shot-list items ───────────────────────────────────────────────────

    def create_shot_list_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/shot-list-items", payload, headers)

    def get_shot_list_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/studio/shot-list-items/{item_id}", None, headers
        )

    def list_shot_list_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/studio/shot-list-items", params, headers)

    def assign_shot_list_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/studio/shot-list-items/{item_id}/assign", payload, headers
        )

    def waive_shot_list_item(
        self,
        item_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/shot-list-items/{item_id}/waive", payload or {}, headers
        )

    # ─── Assets ────────────────────────────────────────────────────────────

    def create_asset(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/assets", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio/assets/{asset_id}", None, headers)

    def list_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/studio/assets", params, headers)

    def deliver_asset(
        self,
        asset_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/assets/{asset_id}/deliver", payload or {}, headers
        )

    # ─── Retouch tasks ─────────────────────────────────────────────────────

    def create_retouch_task(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/studio/retouch-tasks", payload, headers)

    def get_retouch_task(self, task_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio/retouch-tasks/{task_id}", None, headers)

    def list_retouch_tasks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/studio/retouch-tasks", params, headers)

    def claim_next_retouch_task(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", "/studio/retouch-tasks/claim-next", payload or {}, headers
        )

    def submit_retouch_task(
        self,
        task_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/studio/retouch-tasks/{task_id}/submit", payload or {}, headers
        )

    def qc_decision(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/studio/retouch-tasks/{task_id}/qc-decision", payload, headers
        )
