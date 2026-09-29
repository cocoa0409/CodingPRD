"""API client: one method per endpoint defined in the PRD (§4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/accreditation"


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Hospital Accreditation Survey
    Readiness API. Every method returns the raw response so tests can assert
    status codes and error envelopes."""

    # ------------------------------------------------------------------
    # Chapters and standards
    # ------------------------------------------------------------------
    def create_chapter(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/chapters", payload, headers)

    def get_chapter(self, chapter_id: str, headers=None):
        return self._request("GET", f"{BASE}/chapters/{chapter_id}", headers=headers)

    def create_standard(self, chapter_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/chapters/{chapter_id}/standards", payload, headers
        )

    def list_chapter_standards(self, chapter_id: str, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/chapters/{chapter_id}/standards", headers=headers, params=params
        )

    def get_standard(self, standard_id: str, headers=None):
        return self._request("GET", f"{BASE}/standards/{standard_id}", headers=headers)

    # ------------------------------------------------------------------
    # Owner assignments
    # ------------------------------------------------------------------
    def create_owner_assignment(self, standard_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/standards/{standard_id}/owner-assignments", payload, headers
        )

    def list_owner_assignments(self, standard_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/standards/{standard_id}/owner-assignments",
            headers=headers,
            params=params,
        )

    def revoke_owner_assignment(self, assignment_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/owner-assignments/{assignment_id}/revoke", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Evidence repository
    # ------------------------------------------------------------------
    def create_evidence_item(self, standard_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/standards/{standard_id}/evidence-items", payload, headers
        )

    def list_evidence_items(self, standard_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/standards/{standard_id}/evidence-items",
            headers=headers,
            params=params,
        )

    def get_evidence_item(self, evidence_id: str, headers=None):
        return self._request("GET", f"{BASE}/evidence-items/{evidence_id}", headers=headers)

    def transition_evidence_item(self, evidence_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/evidence-items/{evidence_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Hospital units and readiness
    # ------------------------------------------------------------------
    def create_unit(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/units", payload, headers)

    def get_unit(self, unit_id: str, headers=None):
        return self._request("GET", f"{BASE}/units/{unit_id}", headers=headers)

    def get_unit_readiness(self, unit_id: str, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/units/{unit_id}/readiness", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Mock tracers and observations
    # ------------------------------------------------------------------
    def create_mock_tracer(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/mock-tracers", payload, headers)

    def get_mock_tracer(self, tracer_id: str, headers=None):
        return self._request("GET", f"{BASE}/mock-tracers/{tracer_id}", headers=headers)

    def list_mock_tracers(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/mock-tracers", headers=headers, params=params)

    def transition_mock_tracer(self, tracer_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/mock-tracers/{tracer_id}/transition", payload, headers
        )

    def create_tracer_observation(self, tracer_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/mock-tracers/{tracer_id}/observations", payload, headers
        )

    def list_tracer_observations(self, tracer_id: str, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/mock-tracers/{tracer_id}/observations", headers=headers, params=params
        )

    def list_standard_tracer_observations(self, standard_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/standards/{standard_id}/tracer-observations",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Rounding sessions and deficiency tickets
    # ------------------------------------------------------------------
    def create_rounding_session(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/rounding-sessions", payload, headers)

    def get_rounding_session(self, session_id: str, headers=None):
        return self._request("GET", f"{BASE}/rounding-sessions/{session_id}", headers=headers)

    def list_rounding_sessions(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/rounding-sessions", headers=headers, params=params)

    def create_deficiency(self, session_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/rounding-sessions/{session_id}/deficiencies", payload, headers
        )

    def close_rounding_session(self, session_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/rounding-sessions/{session_id}/close", payload or {}, headers
        )

    def get_deficiency_ticket(self, ticket_id: str, headers=None):
        return self._request("GET", f"{BASE}/deficiency-tickets/{ticket_id}", headers=headers)

    def list_deficiency_tickets(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/deficiency-tickets", headers=headers, params=params)

    def transition_deficiency_ticket(self, ticket_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/deficiency-tickets/{ticket_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Survey windows
    # ------------------------------------------------------------------
    def create_survey_window(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/survey-windows", payload, headers)

    def get_survey_window(self, window_id: str, headers=None):
        return self._request("GET", f"{BASE}/survey-windows/{window_id}", headers=headers)

    def transition_survey_window(self, window_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/survey-windows/{window_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Survey findings and evidence of standards compliance
    # ------------------------------------------------------------------
    def create_finding(self, window_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/survey-windows/{window_id}/findings", payload, headers
        )

    def get_finding(self, finding_id: str, headers=None):
        return self._request("GET", f"{BASE}/survey-findings/{finding_id}", headers=headers)

    def list_findings(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/survey-findings", headers=headers, params=params)

    def escalate_finding(self, finding_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/survey-findings/{finding_id}/escalate", payload, headers
        )

    def create_esc_submission(self, finding_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/survey-findings/{finding_id}/esc-submissions", payload, headers
        )

    def list_esc_submissions(self, finding_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/survey-findings/{finding_id}/esc-submissions",
            headers=headers,
            params=params,
        )

    def esc_review(self, finding_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/survey-findings/{finding_id}/esc-review", payload, headers
        )

    # ------------------------------------------------------------------
    # Periodic performance review self-assessments
    # ------------------------------------------------------------------
    def create_ppr_self_assessment(self, chapter_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/chapters/{chapter_id}/ppr-self-assessments", payload, headers
        )

    def list_ppr_self_assessments(self, chapter_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/chapters/{chapter_id}/ppr-self-assessments",
            headers=headers,
            params=params,
        )

    def revise_ppr_self_assessment(self, ppr_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/ppr-self-assessments/{ppr_id}/revise", payload, headers
        )

    def attest_ppr_self_assessment(self, ppr_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/ppr-self-assessments/{ppr_id}/attest", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch — lets a test send arbitrary or partial headers
    # (for example a request that omits X-User-ID entirely).
    # ------------------------------------------------------------------
    def raw_request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
