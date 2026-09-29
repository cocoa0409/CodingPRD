"""Typed client covering every endpoint declared in PRD §4.

One method per row of the endpoint table, in table order. Each method takes the
caller's headers explicitly, because almost every rule in this API is scoped by
role or by ownership and a test must be able to vary the caller freely.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper over the Environmental Justice HTTP surface."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc"""
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ------------------------------------------------------------------
    # Screening areas and burden indicators
    # ------------------------------------------------------------------

    def create_screening_area(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/screening-areas"""
        return self.post("/ej/screening-areas", json=payload, headers=headers)

    def get_screening_area(
        self, area_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /ej/screening-areas/{id}"""
        return self.get(f"/ej/screening-areas/{area_id}", headers=headers)

    def create_burden_indicator(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/burden-indicators"""
        return self.post("/ej/burden-indicators", json=payload, headers=headers)

    def list_burden_indicators(
        self,
        area_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/screening-areas/{id}/burden-indicators"""
        return self.get(
            f"/ej/screening-areas/{area_id}/burden-indicators",
            headers=headers,
            params=params,
        )

    def recertify_screening_area(
        self,
        area_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/screening-areas/{id}/recertify"""
        return self.post(
            f"/ej/screening-areas/{area_id}/recertify",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------

    def create_facility(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/facilities"""
        return self.post("/ej/facilities", json=payload, headers=headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /ej/facilities/{id}"""
        return self.get(f"/ej/facilities/{facility_id}", headers=headers)

    def list_area_facilities(
        self,
        area_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/screening-areas/{id}/facilities"""
        return self.get(
            f"/ej/screening-areas/{area_id}/facilities", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Venues
    # ------------------------------------------------------------------

    def create_venue(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/venues"""
        return self.post("/ej/venues", json=payload, headers=headers)

    def get_venue(self, venue_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /ej/venues/{id}"""
        return self.get(f"/ej/venues/{venue_id}", headers=headers)

    def list_venue_meetings(
        self,
        venue_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/venues/{id}/meetings"""
        return self.get(f"/ej/venues/{venue_id}/meetings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Permit applications
    # ------------------------------------------------------------------

    def create_permit_application(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/permit-applications"""
        return self.post("/ej/permit-applications", json=payload, headers=headers)

    def get_permit_application(
        self, application_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}"""
        return self.get(f"/ej/permit-applications/{application_id}", headers=headers)

    def list_facility_applications(
        self,
        facility_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/facilities/{id}/permit-applications"""
        return self.get(
            f"/ej/facilities/{facility_id}/permit-applications",
            headers=headers,
            params=params,
        )

    def list_application_revisions(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}/revisions"""
        return self.get(
            f"/ej/permit-applications/{application_id}/revisions",
            headers=headers,
            params=params,
        )

    def submit_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/permit-applications/{id}/submit"""
        return self.post(
            f"/ej/permit-applications/{application_id}/submit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def screen_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/permit-applications/{id}/screen"""
        return self.post(
            f"/ej/permit-applications/{application_id}/screen",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def list_applicability_determinations(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}/applicability-determinations"""
        return self.get(
            f"/ej/permit-applications/{application_id}/applicability-determinations",
            headers=headers,
            params=params,
        )

    def advance_to_decision(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/permit-applications/{id}/advance-to-decision"""
        return self.post(
            f"/ej/permit-applications/{application_id}/advance-to-decision",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def return_for_revision(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/permit-applications/{id}/return-for-revision"""
        return self.post(
            f"/ej/permit-applications/{application_id}/return-for-revision",
            json=payload,
            headers=headers,
        )

    def resubmit_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/permit-applications/{id}/resubmit"""
        return self.post(
            f"/ej/permit-applications/{application_id}/resubmit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def withdraw_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/permit-applications/{id}/withdraw"""
        return self.post(
            f"/ej/permit-applications/{application_id}/withdraw",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Cumulative impact assessments
    # ------------------------------------------------------------------

    def create_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/cumulative-impact-assessments"""
        return self.post(
            "/ej/cumulative-impact-assessments", json=payload, headers=headers
        )

    def list_application_assessments(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}/assessments"""
        return self.get(
            f"/ej/permit-applications/{application_id}/assessments",
            headers=headers,
            params=params,
        )

    def submit_assessment_for_qa(
        self,
        assessment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/cumulative-impact-assessments/{id}/submit-qa"""
        return self.post(
            f"/ej/cumulative-impact-assessments/{assessment_id}/submit-qa",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def decide_assessment_qa(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/cumulative-impact-assessments/{id}/qa-decision"""
        return self.post(
            f"/ej/cumulative-impact-assessments/{assessment_id}/qa-decision",
            json=payload,
            headers=headers,
        )

    def revise_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/cumulative-impact-assessments/{id}/revise"""
        return self.post(
            f"/ej/cumulative-impact-assessments/{assessment_id}/revise",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Participation plans
    # ------------------------------------------------------------------

    def get_participation_plan(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /ej/participation-plans/{id}"""
        return self.get(f"/ej/participation-plans/{plan_id}", headers=headers)

    def list_application_plans(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}/participation-plans"""
        return self.get(
            f"/ej/permit-applications/{application_id}/participation-plans",
            headers=headers,
            params=params,
        )

    def update_participation_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /ej/participation-plans/{id}"""
        return self._request(
            "PATCH", f"/ej/participation-plans/{plan_id}", payload=payload, headers=headers
        )

    def open_comment_period(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/participation-plans/{id}/open"""
        return self.post(
            f"/ej/participation-plans/{plan_id}/open", json=payload, headers=headers
        )

    def extend_comment_period(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/participation-plans/{id}/extend"""
        return self.post(
            f"/ej/participation-plans/{plan_id}/extend", json=payload, headers=headers
        )

    def close_comment_period(
        self,
        plan_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /ej/participation-plans/{id}/close"""
        return self.post(
            f"/ej/participation-plans/{plan_id}/close",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Public meetings and comments
    # ------------------------------------------------------------------

    def create_public_meeting(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/public-meetings"""
        return self.post("/ej/public-meetings", json=payload, headers=headers)

    def list_plan_meetings(
        self,
        plan_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/participation-plans/{id}/meetings"""
        return self.get(
            f"/ej/participation-plans/{plan_id}/meetings", headers=headers, params=params
        )

    def cancel_public_meeting(
        self, meeting_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/public-meetings/{id}/cancel"""
        return self.post(
            f"/ej/public-meetings/{meeting_id}/cancel", json=payload, headers=headers
        )

    def create_public_comment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/public-comments"""
        return self.post("/ej/public-comments", json=payload, headers=headers)

    def list_plan_comments(
        self,
        plan_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/participation-plans/{id}/comments"""
        return self.get(
            f"/ej/participation-plans/{plan_id}/comments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Permit conditions
    # ------------------------------------------------------------------

    def create_permit_condition(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/permit-conditions"""
        return self.post("/ej/permit-conditions", json=payload, headers=headers)

    def list_application_conditions(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}/conditions"""
        return self.get(
            f"/ej/permit-applications/{application_id}/conditions",
            headers=headers,
            params=params,
        )

    def void_permit_condition(
        self, condition_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """DELETE /ej/permit-conditions/{id}"""
        return self.delete(f"/ej/permit-conditions/{condition_id}", headers=headers)

    # ------------------------------------------------------------------
    # Permit decisions
    # ------------------------------------------------------------------

    def create_permit_decision(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/permit-decisions"""
        return self.post("/ej/permit-decisions", json=payload, headers=headers)

    def list_application_decisions(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/permit-applications/{id}/decisions"""
        return self.get(
            f"/ej/permit-applications/{application_id}/decisions",
            headers=headers,
            params=params,
        )

    def rescind_permit_decision(
        self, decision_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/permit-decisions/{id}/rescind"""
        return self.post(
            f"/ej/permit-decisions/{decision_id}/rescind", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Community complaints
    # ------------------------------------------------------------------

    def create_complaint(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/community-complaints"""
        return self.post("/ej/community-complaints", json=payload, headers=headers)

    def get_complaint(
        self, complaint_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /ej/community-complaints/{id}"""
        return self.get(f"/ej/community-complaints/{complaint_id}", headers=headers)

    def list_complaints(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /ej/community-complaints"""
        return self.get("/ej/community-complaints", headers=headers, params=params)

    def triage_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/community-complaints/{id}/triage"""
        return self.post(
            f"/ej/community-complaints/{complaint_id}/triage",
            json=payload,
            headers=headers,
        )

    def reopen_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/community-complaints/{id}/reopen"""
        return self.post(
            f"/ej/community-complaints/{complaint_id}/reopen",
            json=payload,
            headers=headers,
        )

    def resolve_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/community-complaints/{id}/resolve"""
        return self.post(
            f"/ej/community-complaints/{complaint_id}/resolve",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------

    def assign_next_inspection(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/inspections/assign-next"""
        return self.post("/ej/inspections/assign-next", json=payload, headers=headers)

    def complete_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /ej/inspections/{id}/complete"""
        return self.post(
            f"/ej/inspections/{inspection_id}/complete", json=payload, headers=headers
        )

    def list_complaint_inspections(
        self,
        complaint_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/community-complaints/{id}/inspections"""
        return self.get(
            f"/ej/community-complaints/{complaint_id}/inspections",
            headers=headers,
            params=params,
        )

    def list_facility_inspections(
        self,
        facility_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /ej/facilities/{id}/inspections"""
        return self.get(
            f"/ej/facilities/{facility_id}/inspections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Program evaluation
    # ------------------------------------------------------------------

    def get_program_evaluation(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /ej/program-evaluation"""
        return self.get("/ej/program-evaluation", headers=headers, params=params)
