"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Real Estate Entitlement API (/entitlement)."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/entitlement/_clock/set_current_utc", payload, headers
        )

    # --- Fee schedules ---
    def create_fee_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/entitlement/fee-schedules", payload, headers)

    def adopt_fee_schedule(self, fs_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/fee-schedules/{fs_id}/adopt", {}, headers
        )

    def get_fee_schedule(self, fs_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/fee-schedules/{fs_id}", headers=headers
        )

    def list_fee_schedules(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/fee-schedules", headers=headers, params=params
        )

    # --- Applicants ---
    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/entitlement/applicants", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/applicants/{applicant_id}", headers=headers
        )

    # --- Staff reviewers ---
    def create_staff_reviewer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/entitlement/staff-reviewers", payload, headers)

    def get_staff_reviewer(self, reviewer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/staff-reviewers/{reviewer_id}", headers=headers
        )

    # --- Decision authorities ---
    def create_decision_authority(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/entitlement/decision-authorities", payload, headers
        )

    def get_decision_authority(self, authority_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/decision-authorities/{authority_id}", headers=headers
        )

    # --- Projects ---
    def create_project(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/entitlement/projects", payload, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/projects/{project_id}", headers=headers
        )

    def list_projects(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/entitlement/projects", headers=headers, params=params)

    # --- Applications ---
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/entitlement/applications", payload, headers)

    def get_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/applications/{app_id}", headers=headers
        )

    def list_applications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/applications", headers=headers, params=params
        )

    def submit_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/submit", {}, headers
        )

    def open_review(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/open-review", {}, headers
        )

    def advance_to_decision(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/advance-to-decision", {}, headers
        )

    def withdraw_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/withdraw", {}, headers
        )

    # --- Review comments ---
    def create_review_comment(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/review-comments", payload, headers
        )

    def list_review_comments(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/applications/{app_id}/review-comments",
            headers=headers,
            params=params,
        )

    def get_review_comment(self, comment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/review-comments/{comment_id}", headers=headers
        )

    def list_review_comments_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/review-comments", headers=headers, params=params
        )

    def address_review_comment(self, comment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/review-comments/{comment_id}/address", {}, headers
        )

    def verify_review_comment(self, comment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/review-comments/{comment_id}/verify", {}, headers
        )

    def waive_review_comment(self, comment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/review-comments/{comment_id}/waive", {}, headers
        )

    # --- Outreach events ---
    def create_outreach_event(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/outreach-events", payload, headers
        )

    def list_outreach_events(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/applications/{app_id}/outreach-events",
            headers=headers,
            params=params,
        )

    def get_outreach_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/outreach-events/{event_id}", headers=headers
        )

    def list_outreach_events_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/outreach-events", headers=headers, params=params
        )

    # --- Public hearings ---
    def create_hearing(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/hearings", payload, headers
        )

    def list_hearings(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/entitlement/applications/{app_id}/hearings", headers=headers, params=params
        )

    def get_hearing(self, hearing_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/hearings/{hearing_id}", headers=headers
        )

    def list_hearings_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/entitlement/hearings", headers=headers, params=params)

    def mark_hearing_held(self, hearing_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/hearings/{hearing_id}/mark-held", {}, headers
        )

    def continue_hearing(
        self, hearing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/hearings/{hearing_id}/continue", payload, headers
        )

    def renotice_hearing(
        self, hearing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/hearings/{hearing_id}/renotice", payload, headers
        )

    def cancel_hearing(self, hearing_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/hearings/{hearing_id}/cancel", {}, headers
        )

    # --- Decisions ---
    def render_decision(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/decisions", payload, headers
        )

    def list_decisions(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/entitlement/applications/{app_id}/decisions", headers=headers, params=params
        )

    def get_decision(self, decision_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/decisions/{decision_id}", headers=headers
        )

    def list_decisions_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/entitlement/decisions", headers=headers, params=params)

    # --- Conditions of approval ---
    def create_condition(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/conditions", payload, headers
        )

    def list_conditions(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/entitlement/applications/{app_id}/conditions", headers=headers, params=params
        )

    def get_condition(self, condition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/conditions/{condition_id}", headers=headers
        )

    def list_conditions_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/entitlement/conditions", headers=headers, params=params)

    def satisfy_condition(self, condition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/conditions/{condition_id}/satisfy", {}, headers
        )

    def waive_condition(self, condition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/conditions/{condition_id}/waive", {}, headers
        )

    # --- Impact fee assessments / payments ---
    def list_assessments(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/applications/{app_id}/assessments",
            headers=headers,
            params=params,
        )

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/assessments/{assessment_id}", headers=headers
        )

    def list_assessments_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/assessments", headers=headers, params=params
        )

    def record_payment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/entitlement/assessments/{assessment_id}/payments",
            payload,
            headers,
        )

    def list_payments(
        self, assessment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/assessments/{assessment_id}/payments",
            headers=headers,
            params=params,
        )

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/payments/{payment_id}", headers=headers
        )

    def list_payments_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/entitlement/payments", headers=headers, params=params)

    def defer_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/assessments/{assessment_id}/defer", {}, headers
        )

    # --- Development agreements / referendum petitions ---
    def create_development_agreement(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/entitlement/applications/{app_id}/development-agreements",
            payload,
            headers,
        )

    def get_development_agreement(self, da_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/development-agreements/{da_id}", headers=headers
        )

    def list_development_agreements(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/applications/{app_id}/development-agreements",
            headers=headers,
            params=params,
        )

    def list_development_agreements_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/development-agreements", headers=headers, params=params
        )

    def adopt_development_agreement(self, da_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/development-agreements/{da_id}/adopt", {}, headers
        )

    def finalize_vesting(self, da_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/entitlement/development-agreements/{da_id}/finalize-vesting",
            {},
            headers,
        )

    def file_referendum_petition(
        self, da_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/entitlement/development-agreements/{da_id}/referendum-petitions",
            payload,
            headers,
        )

    def list_referendum_petitions(
        self, da_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/development-agreements/{da_id}/referendum-petitions",
            headers=headers,
            params=params,
        )

    def get_referendum_petition(self, petition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/referendum-petitions/{petition_id}", headers=headers
        )

    def list_referendum_petitions_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/referendum-petitions", headers=headers, params=params
        )

    def certify_referendum_petition(self, petition_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/entitlement/referendum-petitions/{petition_id}/certify",
            {},
            headers,
        )

    # --- Appeals ---
    def file_appeal(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/applications/{app_id}/appeals", payload, headers
        )

    def list_appeals(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/entitlement/applications/{app_id}/appeals", headers=headers, params=params
        )

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/entitlement/appeals/{appeal_id}", headers=headers)

    def list_appeals_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/entitlement/appeals", headers=headers, params=params)

    def resolve_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlement/appeals/{appeal_id}/resolve", payload, headers
        )

    # --- Permit sequences ---
    def request_permit_sequence(
        self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/entitlement/applications/{app_id}/permit-sequences",
            payload,
            headers,
        )

    def list_permit_sequences(
        self, app_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/entitlement/applications/{app_id}/permit-sequences",
            headers=headers,
            params=params,
        )

    def get_permit_sequence(self, seq_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/entitlement/permit-sequences/{seq_id}", headers=headers
        )

    def list_permit_sequences_global(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/entitlement/permit-sequences", headers=headers, params=params
        )

    def issue_permit(self, seq_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlement/permit-sequences/{seq_id}/issue", {}, headers
        )


api_client = ApiClient()
