"""HTTP client for the Studio Production Pipeline API.

One method per endpoint of the API contract.  Every method returns the raw
response object produced by the underlying generic client so that callers can
assert on both HTTP status and the response envelope.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

JsonDict = Dict[str, Any]


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper over the studio API surface."""

    # ------------------------------------------------------------------
    # Logical studio clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Optional[JsonDict] = None):
        return self.post("/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Productions
    # ------------------------------------------------------------------
    def create_production(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/productions", payload, headers)

    def list_productions(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/productions", None, headers, params)

    def get_production(self, production_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/productions/{production_id}", None, headers)

    def advance_production_phase(
        self, production_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/productions/{production_id}/advance-phase", payload, headers
        )

    # ------------------------------------------------------------------
    # Pre-production gates
    # ------------------------------------------------------------------
    def list_gates(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/pre-production-gates", None, headers, params)

    def get_gate(self, gate_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/pre-production-gates/{gate_id}", None, headers)

    def submit_gate(
        self, gate_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/pre-production-gates/{gate_id}/submit", payload, headers
        )

    def decide_gate(
        self, gate_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/pre-production-gates/{gate_id}/review-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------
    def create_asset(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/assets", payload, headers)

    def list_assets(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/assets", None, headers, params)

    def get_asset(self, asset_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/assets/{asset_id}", None, headers)

    def advance_asset_build(
        self, asset_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/assets/{asset_id}/advance-build", payload, headers)

    def library_submit_asset(
        self, asset_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/assets/{asset_id}/library-submit", payload, headers)

    def library_decide_asset(
        self, asset_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/assets/{asset_id}/library-decision", payload, headers)

    def relink_asset_source(
        self, asset_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/assets/{asset_id}/relink-source", payload, headers)

    # ------------------------------------------------------------------
    # Shots and stage tasks
    # ------------------------------------------------------------------
    def create_shot(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/shots", payload, headers)

    def list_shots(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/shots", None, headers, params)

    def get_shot(self, shot_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/shots/{shot_id}", None, headers)

    def get_shot_earned_value(
        self,
        shot_id: str,
        headers: Optional[JsonDict] = None,
        params: Optional[JsonDict] = None,
    ):
        return self._request(
            "GET", f"/studio/shots/{shot_id}/earned-value", None, headers, params
        )

    def list_stage_tasks(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/stage-tasks", None, headers, params)

    def get_stage_task(self, task_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/stage-tasks/{task_id}", None, headers)

    def assign_stage_task(
        self, task_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/stage-tasks/{task_id}/assign", payload, headers)

    def log_hours(
        self, task_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/stage-tasks/{task_id}/log-hours", payload, headers)

    def submit_stage_task(
        self, task_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/stage-tasks/{task_id}/submit", payload, headers)

    def decide_stage_task(
        self, task_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/stage-tasks/{task_id}/review-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Screening rooms
    # ------------------------------------------------------------------
    def create_screening_room(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/screening-rooms", payload, headers)

    def list_screening_rooms(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/screening-rooms", None, headers, params)

    def get_screening_room(self, room_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/screening-rooms/{room_id}", None, headers)

    def calibrate_screening_room(
        self, room_id: str, payload: Optional[JsonDict] = None, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/screening-rooms/{room_id}/calibrate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Review sessions
    # ------------------------------------------------------------------
    def create_review_session(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/review-sessions", payload, headers)

    def list_review_sessions(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/review-sessions", None, headers, params)

    def get_review_session(self, session_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/review-sessions/{session_id}", None, headers)

    def start_review_session(
        self,
        session_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/review-sessions/{session_id}/start", payload or {}, headers
        )

    def close_review_session(
        self,
        session_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/review-sessions/{session_id}/close", payload or {}, headers
        )

    def cancel_review_session(
        self,
        session_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/review-sessions/{session_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Director notes
    # ------------------------------------------------------------------
    def create_director_note(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/director-notes", payload, headers)

    def list_director_notes(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/director-notes", None, headers, params)

    def get_director_note(self, note_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/director-notes/{note_id}", None, headers)

    def resolve_director_note(
        self, note_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/director-notes/{note_id}/resolution", payload, headers)

    # ------------------------------------------------------------------
    # Render pools and jobs
    # ------------------------------------------------------------------
    def create_render_pool(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/render-pools", payload, headers)

    def list_render_pools(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/render-pools", None, headers, params)

    def get_render_pool(self, pool_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/render-pools/{pool_id}", None, headers)

    def create_render_job(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/render-jobs", payload, headers)

    def list_render_jobs(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/render-jobs", None, headers, params)

    def get_render_job(self, job_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/render-jobs/{job_id}", None, headers)

    def complete_render_job(
        self, job_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(f"/studio/render-jobs/{job_id}/complete", payload, headers)

    def cancel_render_job(
        self,
        job_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(f"/studio/render-jobs/{job_id}/cancel", payload or {}, headers)

    # ------------------------------------------------------------------
    # Outsourcing partners and packages
    # ------------------------------------------------------------------
    def create_outsource_partner(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/outsource-partners", payload, headers)

    def list_outsource_partners(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/outsource-partners", None, headers, params)

    def get_outsource_partner(self, partner_id: str, headers: Optional[JsonDict] = None):
        return self._request(
            "GET", f"/studio/outsource-partners/{partner_id}", None, headers
        )

    def set_partner_status(
        self, partner_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/outsource-partners/{partner_id}/status", payload, headers
        )

    def create_outsource_package(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/outsource-packages", payload, headers)

    def list_outsource_packages(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/outsource-packages", None, headers, params)

    def get_outsource_package(self, package_id: str, headers: Optional[JsonDict] = None):
        return self._request(
            "GET", f"/studio/outsource-packages/{package_id}", None, headers
        )

    def issue_package(
        self,
        package_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/outsource-packages/{package_id}/issue", payload or {}, headers
        )

    def accept_package(
        self,
        package_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/outsource-packages/{package_id}/accept", payload or {}, headers
        )

    def deliver_package(
        self,
        package_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/outsource-packages/{package_id}/deliver", payload or {}, headers
        )

    def qc_decide_package(
        self, package_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/outsource-packages/{package_id}/qc-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Deliverables
    # ------------------------------------------------------------------
    def create_deliverable(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        return self.post("/studio/deliverables", payload, headers)

    def list_deliverables(
        self, headers: Optional[JsonDict] = None, params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/studio/deliverables", None, headers, params)

    def get_deliverable(self, deliverable_id: str, headers: Optional[JsonDict] = None):
        return self._request("GET", f"/studio/deliverables/{deliverable_id}", None, headers)

    def submit_deliverable(
        self,
        deliverable_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/deliverables/{deliverable_id}/submit", payload or {}, headers
        )

    def qc_decide_deliverable(
        self, deliverable_id: str, payload: JsonDict, headers: Optional[JsonDict] = None
    ):
        return self.post(
            f"/studio/deliverables/{deliverable_id}/qc-decision", payload, headers
        )

    def deliver_deliverable(
        self,
        deliverable_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[JsonDict] = None,
    ):
        return self.post(
            f"/studio/deliverables/{deliverable_id}/deliver", payload or {}, headers
        )
