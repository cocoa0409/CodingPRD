"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving infrastructure ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/coaching/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def simulate_payment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/_payments/simulate", payload, headers)

    # --- coaches ---
    def create_coach(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/coaches", payload, headers)

    def get_coach(self, coach_id: str, headers: Dict):
        return self._request("GET", f"/coaching/coaches/{coach_id}", headers=headers)

    def list_coaches(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/coaching/coaches", headers=headers, params=params)

    def verify_credential(self, coach_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/coaches/{coach_id}/verify-credential", {}, headers
        )

    def revoke_credential(self, coach_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/coaches/{coach_id}/revoke-credential", {}, headers
        )

    def suspend_ethics(self, coach_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/coaches/{coach_id}/suspend-ethics", {}, headers
        )

    def list_coach_fit_assessments(self, coach_id: str, headers: Dict,
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/coaches/{coach_id}/fit-assessments",
            headers=headers, params=params,
        )

    # --- clients ---
    def create_client(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/clients/{client_id}", headers=headers, params=params
        )

    def list_clients(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/coaching/clients", headers=headers, params=params)

    # --- program tiers ---
    def create_program_tier(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/program-tiers", payload, headers)

    def get_program_tier(self, tier_id: str, headers: Dict):
        return self._request(
            "GET", f"/coaching/program-tiers/{tier_id}", headers=headers
        )

    def list_program_tiers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/coaching/program-tiers", headers=headers, params=params
        )

    def retire_program_tier(self, tier_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/program-tiers/{tier_id}/retire", {}, headers
        )

    # --- discovery calls & fit assessments ---
    def create_discovery_call(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/discovery-calls", payload, headers)

    def get_discovery_call(self, call_id: str, headers: Dict):
        return self._request(
            "GET", f"/coaching/discovery-calls/{call_id}", headers=headers
        )

    def list_discovery_calls(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/coaching/discovery-calls", headers=headers, params=params
        )

    def complete_discovery_call(self, call_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/discovery-calls/{call_id}/complete", {}, headers
        )

    def mark_discovery_call_no_show(self, call_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/discovery-calls/{call_id}/mark-no-show", {}, headers
        )

    def reschedule_discovery_call(self, call_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PUT", f"/coaching/discovery-calls/{call_id}", payload, headers
        )

    def cancel_discovery_call(self, call_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/discovery-calls/{call_id}/cancel", {}, headers
        )

    def create_fit_assessment(self, call_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/discovery-calls/{call_id}/fit-assessment",
            payload, headers,
        )

    def get_fit_assessment(self, call_id: str, headers: Dict):
        return self._request(
            "GET", f"/coaching/discovery-calls/{call_id}/fit-assessment",
            headers=headers,
        )

    # --- enrollments ---
    def create_enrollment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict):
        return self._request(
            "GET", f"/coaching/enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/coaching/enrollments", headers=headers, params=params
        )

    def list_enrollment_installments(self, enrollment_id: str, headers: Dict,
                                     params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/enrollments/{enrollment_id}/installments",
            headers=headers, params=params,
        )

    def list_enrollment_cohort_memberships(self, enrollment_id: str, headers: Dict,
                                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/enrollments/{enrollment_id}/cohort-memberships",
            headers=headers, params=params,
        )

    def pause_enrollment(self, enrollment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/enrollments/{enrollment_id}/pause", payload, headers
        )

    def resume_enrollment(self, enrollment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/enrollments/{enrollment_id}/resume", payload, headers
        )

    def cancel_enrollment(self, enrollment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/enrollments/{enrollment_id}/cancel", payload, headers
        )

    # --- sessions ---
    def book_session(self, enrollment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/enrollments/{enrollment_id}/sessions",
            payload, headers,
        )

    def get_session(self, session_id: str, headers: Dict):
        return self._request("GET", f"/coaching/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/coaching/sessions", headers=headers, params=params)

    def list_enrollment_sessions(self, enrollment_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/enrollments/{enrollment_id}/sessions",
            headers=headers, params=params,
        )

    def complete_session(self, session_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/sessions/{session_id}/complete", {}, headers
        )

    def mark_session_no_show(self, session_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/sessions/{session_id}/mark-no-show", {}, headers
        )

    def cancel_session(self, session_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/sessions/{session_id}/cancel", {}, headers
        )

    def reschedule_session(self, session_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/sessions/{session_id}/reschedule", payload, headers
        )

    # --- goals & habit check-ins ---
    def create_goal(self, enrollment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/enrollments/{enrollment_id}/goals", payload, headers
        )

    def get_goal(self, goal_id: str, headers: Dict):
        return self._request("GET", f"/coaching/goals/{goal_id}", headers=headers)

    def abandon_goal(self, goal_id: str, headers: Dict):
        return self._request("POST", f"/coaching/goals/{goal_id}/abandon", {}, headers)

    def list_enrollment_goals(self, enrollment_id: str, headers: Dict,
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/enrollments/{enrollment_id}/goals",
            headers=headers, params=params,
        )

    def create_check_in(self, goal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/goals/{goal_id}/check-ins", payload, headers
        )

    def list_check_ins(self, goal_id: str, headers: Dict,
                       params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/goals/{goal_id}/check-ins",
            headers=headers, params=params,
        )

    # --- cohorts & memberships ---
    def create_cohort(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/cohorts", payload, headers)

    def get_cohort(self, cohort_id: str, headers: Dict):
        return self._request("GET", f"/coaching/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/coaching/cohorts", headers=headers, params=params)

    def open_cohort(self, cohort_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/cohorts/{cohort_id}/open", {}, headers
        )

    def cancel_cohort(self, cohort_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/cohorts/{cohort_id}/cancel", {}, headers
        )

    def add_cohort_member(self, cohort_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/coaching/cohorts/{cohort_id}/members", payload, headers
        )

    def list_cohort_members(self, cohort_id: str, headers: Dict,
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"/coaching/cohorts/{cohort_id}/members",
            headers=headers, params=params,
        )

    def remove_cohort_member(self, cohort_id: str, membership_id: str, headers: Dict):
        return self._request(
            "DELETE", f"/coaching/cohorts/{cohort_id}/members/{membership_id}",
            headers=headers,
        )

    # --- testimonials ---
    def create_testimonial(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/testimonials", payload, headers)

    def get_testimonial(self, testimonial_id: str, headers: Dict):
        return self._request(
            "GET", f"/coaching/testimonials/{testimonial_id}", headers=headers
        )

    def list_testimonials(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/coaching/testimonials", headers=headers, params=params
        )

    def consent_testimonial(self, testimonial_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/testimonials/{testimonial_id}/consent", {}, headers
        )

    def decline_testimonial(self, testimonial_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/testimonials/{testimonial_id}/decline", {}, headers
        )

    def publish_testimonial(self, testimonial_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/testimonials/{testimonial_id}/publish", {}, headers
        )

    def revoke_consent_testimonial(self, testimonial_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/testimonials/{testimonial_id}/revoke-consent",
            {}, headers,
        )

    # --- refund requests ---
    def create_refund_request(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coaching/refund-requests", payload, headers)

    def get_refund_request(self, request_id: str, headers: Dict):
        return self._request(
            "GET", f"/coaching/refund-requests/{request_id}", headers=headers
        )

    def list_refund_requests(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/coaching/refund-requests", headers=headers, params=params
        )

    def approve_refund_request(self, request_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/refund-requests/{request_id}/approve", {}, headers
        )

    def deny_refund_request(self, request_id: str, headers: Dict):
        return self._request(
            "POST", f"/coaching/refund-requests/{request_id}/deny", {}, headers
        )


api_client = ApiClient()
