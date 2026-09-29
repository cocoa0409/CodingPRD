"""
Typed HTTP client for the Bridge Inspection & Load Rating Program API.

One method per endpoint of PRD §4, in the order the table lists them. Every
method returns the raw `requests.Response` so that the caller decides whether
to run it through `validate_success`, `validate_error` or `validate_paginated`.

All paths are absolute and carry no version prefix, exactly as PRD §4 states:
"All paths are absolute and are not nested under a version prefix."
"""

from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class BridgeProgramClient(GenericApiClient):
    """Thin, endpoint-per-method wrapper over the framework's HTTP client."""

    # ─── Logical clock (PRD §2.4, §4) ──────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc — accepts `to_iso8601`, answers `current_utc`."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Personnel roster (PRD §3.1) ───────────────────────────────────────
    def create_personnel(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /personnel"""
        return self._request("POST", "/personnel", payload, headers)

    def get_personnel(
        self, personnel_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /personnel/{id}"""
        return self._request("GET", f"/personnel/{personnel_id}", None, headers)

    def list_personnel(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /personnel"""
        return self._request("GET", "/personnel", None, headers, params)

    # ─── Structure inventory (PRD §3.1) ────────────────────────────────────
    def create_bridge(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /bridges"""
        return self._request("POST", "/bridges", payload, headers)

    def get_bridge(self, bridge_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /bridges/{id}"""
        return self._request("GET", f"/bridges/{bridge_id}", None, headers)

    def list_bridges(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /bridges"""
        return self._request("GET", "/bridges", None, headers, params)

    def patch_bridge(
        self, bridge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /bridges/{id} — no version field (PRD §2.9)."""
        return self._request("PATCH", f"/bridges/{bridge_id}", payload, headers)

    def get_compliance_summary(
        self, bridge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /bridges/{id}/compliance-summary"""
        return self._request(
            "GET", f"/bridges/{bridge_id}/compliance-summary", None, headers
        )

    # ─── Inspections (PRD §3.2, §3.3) ──────────────────────────────────────
    def create_inspection(
        self, bridge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /bridges/{id}/inspections"""
        return self._request(
            "POST", f"/bridges/{bridge_id}/inspections", payload, headers
        )

    def get_inspection(
        self, inspection_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /inspections/{id}"""
        return self._request("GET", f"/inspections/{inspection_id}", None, headers)

    def list_inspections(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /inspections"""
        return self._request("GET", "/inspections", None, headers, params)

    def submit_inspection(
        self,
        inspection_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        """POST /inspections/{id}/submit"""
        return self._request(
            "POST", f"/inspections/{inspection_id}/submit", payload, headers
        )

    def qa_claim_inspection(
        self,
        inspection_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /inspections/{id}/qa-claim"""
        return self._request(
            "POST", f"/inspections/{inspection_id}/qa-claim", payload or {}, headers
        )

    def qa_decision_inspection(
        self,
        inspection_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        """POST /inspections/{id}/qa-decision — `decision` is RETURN or ACCEPT."""
        return self._request(
            "POST", f"/inspections/{inspection_id}/qa-decision", payload, headers
        )

    def void_inspection(
        self,
        inspection_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /inspections/{id}/void"""
        return self._request(
            "POST", f"/inspections/{inspection_id}/void", payload or {}, headers
        )

    # ─── Element conditions (PRD §3.2) ─────────────────────────────────────
    def create_element_condition(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /inspections/{id}/element-conditions"""
        return self._request(
            "POST",
            f"/inspections/{inspection_id}/element-conditions",
            payload,
            headers,
        )

    def get_element_condition(
        self, element_condition_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /element-conditions/{id}"""
        return self._request(
            "GET", f"/element-conditions/{element_condition_id}", None, headers
        )

    def list_element_conditions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /element-conditions"""
        return self._request("GET", "/element-conditions", None, headers, params)

    def update_element_condition(
        self,
        element_condition_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        """PUT /element-conditions/{id}"""
        return self._request(
            "PUT", f"/element-conditions/{element_condition_id}", payload, headers
        )

    def delete_element_condition(
        self, element_condition_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """DELETE /element-conditions/{id} — 204 with an empty data object."""
        return self._request(
            "DELETE", f"/element-conditions/{element_condition_id}", None, headers
        )

    # ─── Critical findings (PRD §3.5) ──────────────────────────────────────
    def create_critical_finding(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /critical-findings"""
        return self._request("POST", "/critical-findings", payload, headers)

    def get_critical_finding(
        self, finding_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /critical-findings/{id}"""
        return self._request("GET", f"/critical-findings/{finding_id}", None, headers)

    def list_critical_findings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /critical-findings"""
        return self._request("GET", "/critical-findings", None, headers, params)

    def impose_restriction(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /critical-findings/{id}/impose-restriction"""
        return self._request(
            "POST",
            f"/critical-findings/{finding_id}/impose-restriction",
            payload,
            headers,
        )

    def notify_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /critical-findings/{id}/notify"""
        return self._request(
            "POST", f"/critical-findings/{finding_id}/notify", payload, headers
        )

    def mitigate_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /critical-findings/{id}/mitigate"""
        return self._request(
            "POST", f"/critical-findings/{finding_id}/mitigate", payload, headers
        )

    def resolve_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /critical-findings/{id}/resolve"""
        return self._request(
            "POST", f"/critical-findings/{finding_id}/resolve", payload, headers
        )

    # ─── Notification logs (PRD §3.5) ──────────────────────────────────────
    def get_notification_log(
        self, log_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /notification-logs/{id}"""
        return self._request("GET", f"/notification-logs/{log_id}", None, headers)

    def list_notification_logs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /notification-logs"""
        return self._request("GET", "/notification-logs", None, headers, params)

    # ─── Load ratings (PRD §3.4) ───────────────────────────────────────────
    def create_load_rating(
        self, bridge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /bridges/{id}/load-ratings — requires `expected_bridge_version`."""
        return self._request(
            "POST", f"/bridges/{bridge_id}/load-ratings", payload, headers
        )

    def get_load_rating(
        self, rating_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /load-ratings/{id}"""
        return self._request("GET", f"/load-ratings/{rating_id}", None, headers)

    def list_load_ratings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /load-ratings"""
        return self._request("GET", "/load-ratings", None, headers, params)

    def seal_load_rating(
        self, rating_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /load-ratings/{id}/seal"""
        return self._request(
            "POST", f"/load-ratings/{rating_id}/seal", payload, headers
        )

    def approve_load_rating(
        self, rating_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /load-ratings/{id}/approve"""
        return self._request(
            "POST", f"/load-ratings/{rating_id}/approve", payload, headers
        )

    def reject_load_rating(
        self, rating_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /load-ratings/{id}/reject"""
        return self._request(
            "POST", f"/load-ratings/{rating_id}/reject", payload, headers
        )

    # ─── Permit applications (PRD §3.7) ────────────────────────────────────
    def create_permit_application(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /permit-applications"""
        return self._request("POST", "/permit-applications", payload, headers)

    def get_permit_application(
        self, permit_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /permit-applications/{id}"""
        return self._request("GET", f"/permit-applications/{permit_id}", None, headers)

    def list_permit_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /permit-applications"""
        return self._request("GET", "/permit-applications", None, headers, params)

    def analyze_permit_application(
        self,
        permit_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /permit-applications/{id}/analyze"""
        return self._request(
            "POST", f"/permit-applications/{permit_id}/analyze", payload or {}, headers
        )

    def decide_permit_application(
        self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /permit-applications/{id}/decide"""
        return self._request(
            "POST", f"/permit-applications/{permit_id}/decide", payload, headers
        )

    def get_permit_bridge_analysis(
        self, analysis_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /permit-bridge-analyses/{id}"""
        return self._request(
            "GET", f"/permit-bridge-analyses/{analysis_id}", None, headers
        )

    def list_permit_bridge_analyses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /permit-bridge-analyses — the only discovery channel for the rows."""
        return self._request("GET", "/permit-bridge-analyses", None, headers, params)

    # ─── Scour evaluations (PRD §3.6) ──────────────────────────────────────
    def create_scour_evaluation(
        self, bridge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /bridges/{id}/scour-evaluations"""
        return self._request(
            "POST", f"/bridges/{bridge_id}/scour-evaluations", payload, headers
        )

    def get_scour_evaluation(
        self, evaluation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /scour-evaluations/{id}"""
        return self._request(
            "GET", f"/scour-evaluations/{evaluation_id}", None, headers
        )

    def list_scour_evaluations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /scour-evaluations"""
        return self._request("GET", "/scour-evaluations", None, headers, params)

    def finalize_scour_evaluation(
        self,
        evaluation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /scour-evaluations/{id}/finalize"""
        return self._request(
            "POST",
            f"/scour-evaluations/{evaluation_id}/finalize",
            payload or {},
            headers,
        )

    # ─── Plans of action (PRD §3.6) ────────────────────────────────────────
    def get_plan_of_action(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /plans-of-action/{id}"""
        return self._request("GET", f"/plans-of-action/{plan_id}", None, headers)

    def list_plans_of_action(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /plans-of-action — the only discovery channel for cascade-made plans."""
        return self._request("GET", "/plans-of-action", None, headers, params)

    def update_plan_of_action(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PUT /plans-of-action/{id}"""
        return self._request("PUT", f"/plans-of-action/{plan_id}", payload, headers)

    def submit_plan_of_action(
        self,
        plan_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /plans-of-action/{id}/submit"""
        return self._request(
            "POST", f"/plans-of-action/{plan_id}/submit", payload or {}, headers
        )

    def decide_plan_of_action(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /plans-of-action/{id}/decision — `decision` is APPROVE or RETURN."""
        return self._request(
            "POST", f"/plans-of-action/{plan_id}/decision", payload, headers
        )

    # ─── Program cycles (PRD §3.8) ─────────────────────────────────────────
    def create_program_cycle(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /program-cycles"""
        return self._request("POST", "/program-cycles", payload, headers)

    def get_program_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /program-cycles/{id}"""
        return self._request("GET", f"/program-cycles/{cycle_id}", None, headers)

    def list_program_cycles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /program-cycles"""
        return self._request("GET", "/program-cycles", None, headers, params)

    def get_allocation_summary(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /program-cycles/{id}/allocation-summary"""
        return self._request(
            "GET", f"/program-cycles/{cycle_id}/allocation-summary", None, headers
        )

    def create_project_candidate(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /program-cycles/{id}/candidates — needs `expected_program_cycle_version`."""
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/candidates", payload, headers
        )

    def get_project_candidate(
        self, candidate_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /project-candidates/{id}"""
        return self._request("GET", f"/project-candidates/{candidate_id}", None, headers)

    def list_project_candidates(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /project-candidates — the only channel for cascade-made candidates."""
        return self._request("GET", "/project-candidates", None, headers, params)

    def program_candidate(
        self,
        candidate_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /project-candidates/{id}/program"""
        return self._request(
            "POST", f"/project-candidates/{candidate_id}/program", payload or {}, headers
        )

    def withdraw_candidate(
        self,
        candidate_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /project-candidates/{id}/withdraw"""
        return self._request(
            "POST",
            f"/project-candidates/{candidate_id}/withdraw",
            payload or {},
            headers,
        )

    def defer_candidate(
        self,
        candidate_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /project-candidates/{id}/defer"""
        return self._request(
            "POST", f"/project-candidates/{candidate_id}/defer", payload or {}, headers
        )

    def lock_program_cycle(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /program-cycles/{id}/lock"""
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/lock", payload or {}, headers
        )

    def reopen_program_cycle(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /program-cycles/{id}/reopen"""
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/reopen", payload or {}, headers
        )

    # ─── Federal submissions (PRD §3.9) ────────────────────────────────────
    def create_federal_submission(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /program-cycles/{id}/federal-submissions"""
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/federal-submissions", payload, headers
        )

    def get_federal_submission(
        self, submission_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /federal-submissions/{id}"""
        return self._request(
            "GET", f"/federal-submissions/{submission_id}", None, headers
        )

    def list_federal_submissions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /federal-submissions"""
        return self._request("GET", "/federal-submissions", None, headers, params)

    def submit_federal_submission(
        self,
        submission_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /federal-submissions/{id}/submit"""
        return self._request(
            "POST",
            f"/federal-submissions/{submission_id}/submit",
            payload or {},
            headers,
        )

    def review_federal_submission(
        self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /federal-submissions/{id}/review — `decision` is ACCEPT or REJECT."""
        return self._request(
            "POST", f"/federal-submissions/{submission_id}/review", payload, headers
        )

    # ─── Raw escape hatch ──────────────────────────────────────────────────
    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Escape hatch for header-level tests that must send a malformed request."""
        return self._request(method, path, payload, headers, params)


__all__: List[str] = ["BridgeProgramClient"]
