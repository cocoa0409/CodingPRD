"""Typed HTTP client for the Event Security & Crowd Management API.

One method per declared endpoint. Every method returns the raw
``requests.Response`` so that tests can assert on status codes before handing
the body to a validator.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Endpoint surface of the API under test."""

    # ─── Venues ───────────────────────────────────────

    def create_venue(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/venues", payload, headers)

    def get_venue(self, venue_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues/{venue_id}", None, headers)

    # ─── Venue zones ──────────────────────────────────

    def create_zone(
        self, venue_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/venues/{venue_id}/zones", payload, headers)

    def list_venue_zones(
        self, venue_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues/{venue_id}/zones", params, headers)

    # ─── Security events ──────────────────────────────

    def create_event(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/security-events", payload, headers)

    def get_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/security-events/{event_id}", None, headers)

    def list_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/security-events", params, headers)

    def update_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{API_PREFIX}/security-events/{event_id}", payload, headers)

    def event_lifecycle(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/security-events/{event_id}/lifecycle", payload, headers
        )

    # ─── Risk assessments ─────────────────────────────

    def create_risk_assessment(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/security-events/{event_id}/risk-assessments", payload, headers
        )

    def list_event_risk_assessments(
        self, event_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/security-events/{event_id}/risk-assessments", params, headers
        )

    def get_risk_assessment(
        self, assessment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/risk-assessments/{assessment_id}", None, headers
        )

    def risk_assessment_decision(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/risk-assessments/{assessment_id}/decision", payload, headers
        )

    # ─── Staffing plans ───────────────────────────────

    def create_staffing_plan(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/security-events/{event_id}/staffing-plans", payload, headers
        )

    def get_staffing_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/staffing-plans/{plan_id}", None, headers)

    def list_staffing_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/staffing-plans", params, headers)

    def staffing_plan_lifecycle(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/staffing-plans/{plan_id}/lifecycle", payload, headers
        )

    def get_coverage_summary(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/staffing-plans/{plan_id}/coverage-summary", None, headers
        )

    # ─── Posts ────────────────────────────────────────

    def create_post(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/staffing-plans/{plan_id}/posts", payload, headers
        )

    def get_post(self, post_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/posts/{post_id}", None, headers)

    def list_posts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/posts", params, headers)

    def update_post(
        self, post_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{API_PREFIX}/posts/{post_id}", payload, headers)

    # ─── Subcontractors ───────────────────────────────

    def create_subcontractor(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/subcontractors", payload, headers)

    def get_subcontractor(
        self, subcontractor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/subcontractors/{subcontractor_id}", None, headers
        )

    def subcontractor_decision(
        self, subcontractor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/subcontractors/{subcontractor_id}/decision", payload, headers
        )

    # ─── Guards ───────────────────────────────────────

    def create_guard(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/guards", payload, headers)

    def get_guard(self, guard_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/guards/{guard_id}", None, headers)

    def list_guards(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/guards", params, headers)

    def guard_credential_verification(
        self, guard_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/guards/{guard_id}/credential-verification", payload, headers
        )

    # ─── Post assignments ─────────────────────────────

    def create_post_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/post-assignments", payload, headers)

    def get_post_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/post-assignments/{assignment_id}", None, headers
        )

    def list_post_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/post-assignments", params, headers)

    def post_assignment_duty_event(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/post-assignments/{assignment_id}/duty-events", payload, headers
        )

    # ─── Screening lanes ──────────────────────────────

    def create_screening_lane(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/security-events/{event_id}/screening-lanes", payload, headers
        )

    def get_screening_lane(self, lane_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/screening-lanes/{lane_id}", None, headers)

    def list_screening_lanes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/screening-lanes", params, headers)

    def screening_lane_status(
        self, lane_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/screening-lanes/{lane_id}/status", payload, headers
        )

    # ─── Density readings ─────────────────────────────

    def create_density_reading(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/security-events/{event_id}/density-readings", payload, headers
        )

    def get_density_reading(self, reading_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/density-readings/{reading_id}", None, headers)

    def list_density_readings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/density-readings", params, headers)

    # ─── Incidents ────────────────────────────────────

    def create_incident(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/security-events/{event_id}/incidents", payload, headers
        )

    def get_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/incidents/{incident_id}", None, headers)

    def list_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/incidents", params, headers)

    def incident_action(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/actions", payload, headers
        )

    # ─── After-action reviews ─────────────────────────

    def create_after_action_review(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/security-events/{event_id}/after-action-reviews",
            payload,
            headers,
        )

    def list_event_after_action_reviews(
        self, event_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/security-events/{event_id}/after-action-reviews", params, headers
        )

    def after_action_review_decision(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/after-action-reviews/{review_id}/decision", payload, headers
        )

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)
