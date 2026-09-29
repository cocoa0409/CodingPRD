"""One method per endpoint of the Consulting Engagement API (PRD section 4)."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

Headers = Dict[str, str]
Payload = Optional[Dict[str, Any]]


class ConsultingApiClient(GenericApiClient):
    """Thin transport wrapper: every method returns the raw response."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    def create_client(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/clients", payload, headers)

    def get_client(self, client_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/clients/{client_id}", None, headers)

    def list_clients(self, headers: Headers, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/clients", params, headers)

    def set_client_status(
        self, client_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/clients/{client_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Consultants
    # ------------------------------------------------------------------

    def create_consultant(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/consultants", payload, headers)

    def get_consultant(self, consultant_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/consultants/{consultant_id}", None, headers
        )

    def list_consultants(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/consultants", params, headers)

    # ------------------------------------------------------------------
    # Opportunities
    # ------------------------------------------------------------------

    def create_opportunity(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/opportunities", payload, headers)

    def get_opportunity(self, opportunity_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/opportunities/{opportunity_id}", None, headers
        )

    def list_opportunities(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/opportunities", params, headers)

    def conflict_check(
        self, opportunity_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/opportunities/{opportunity_id}/conflict-check",
            payload,
            headers,
        )

    def verify_budget(
        self, opportunity_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/opportunities/{opportunity_id}/verify-budget",
            payload,
            headers,
        )

    def qualify(
        self, opportunity_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/opportunities/{opportunity_id}/qualify",
            payload if payload is not None else {},
            headers,
        )

    def patch_scope(
        self, opportunity_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/opportunities/{opportunity_id}/scope",
            payload,
            headers,
        )

    def baseline_scope(
        self, opportunity_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/opportunities/{opportunity_id}/baseline-scope",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Deliverables
    # ------------------------------------------------------------------

    def create_deliverable(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/deliverables", payload, headers)

    def get_deliverable(self, deliverable_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/deliverables/{deliverable_id}", None, headers
        )

    def list_deliverables(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/deliverables", params, headers)

    def patch_deliverable(
        self, deliverable_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/deliverables/{deliverable_id}", payload, headers
        )

    def assign_lead(
        self, deliverable_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/deliverables/{deliverable_id}/assign-lead",
            payload,
            headers,
        )

    def set_deliverable_status(
        self, deliverable_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/deliverables/{deliverable_id}/status",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Statements of work
    # ------------------------------------------------------------------

    def create_sow(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sows", payload, headers)

    def get_sow(self, sow_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sows/{sow_id}", None, headers)

    def list_sows(self, headers: Headers, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sows", params, headers)

    def submit_sow_internal(
        self, sow_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sows/{sow_id}/submit-internal",
            payload if payload is not None else {},
            headers,
        )

    def sow_internal_decision(
        self, sow_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sows/{sow_id}/internal-decision", payload, headers
        )

    def sow_client_decision(
        self, sow_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sows/{sow_id}/client-decision", payload, headers
        )

    def revise_sow(
        self, sow_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sows/{sow_id}/revise",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Engagements
    # ------------------------------------------------------------------

    def get_engagement(self, engagement_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/engagements/{engagement_id}", None, headers
        )

    def list_engagements(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/engagements", params, headers)

    def mobilize(
        self, engagement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/engagements/{engagement_id}/mobilize", payload, headers
        )

    def get_economics(self, engagement_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/engagements/{engagement_id}/economics", None, headers
        )

    def begin_closing(
        self, engagement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/begin-closing",
            payload if payload is not None else {},
            headers,
        )

    def close_engagement(
        self, engagement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Timesheet lines
    # ------------------------------------------------------------------

    def create_time_entry(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/time-entries/{time_entry_id}", None, headers
        )

    def list_time_entries(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/time-entries", params, headers)

    def time_entry_decision(
        self, time_entry_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/time-entries/{time_entry_id}/decision",
            payload,
            headers,
        )

    def reverse_time_entry(
        self, time_entry_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/time-entries/{time_entry_id}/reverse",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Change requests
    # ------------------------------------------------------------------

    def create_change_request(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/change-requests", payload, headers)

    def get_change_request(
        self, change_request_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/change-requests/{change_request_id}", None, headers
        )

    def list_change_requests(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/change-requests", params, headers)

    def assess_impact(
        self, change_request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/change-requests/{change_request_id}/assess-impact",
            payload if payload is not None else {},
            headers,
        )

    def change_request_leadership_decision(
        self, change_request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/change-requests/{change_request_id}/leadership-decision",
            payload,
            headers,
        )

    def change_request_client_decision(
        self, change_request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/change-requests/{change_request_id}/client-decision",
            payload,
            headers,
        )

    def rescind_change_request(
        self, change_request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/change-requests/{change_request_id}/rescind",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Quality checkpoints
    # ------------------------------------------------------------------

    def create_quality_review(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/quality-reviews", payload, headers)

    def get_quality_review(self, review_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/quality-reviews/{review_id}", None, headers
        )

    def list_quality_reviews(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/quality-reviews", params, headers)

    def record_outcome(
        self, review_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/quality-reviews/{review_id}/record-outcome",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Risk escalations
    # ------------------------------------------------------------------

    def get_risk_escalation(
        self, escalation_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/risk-escalations/{escalation_id}", None, headers
        )

    def list_risk_escalations(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/risk-escalations", params, headers)

    def leadership_response(
        self, escalation_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/risk-escalations/{escalation_id}/leadership-response",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Satisfaction assessments
    # ------------------------------------------------------------------

    def create_satisfaction_assessment(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/satisfaction-assessments", payload, headers
        )

    def get_satisfaction_assessment(
        self, assessment_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/satisfaction-assessments/{assessment_id}",
            None,
            headers,
        )

    def list_satisfaction_assessments(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/satisfaction-assessments", params, headers
        )
