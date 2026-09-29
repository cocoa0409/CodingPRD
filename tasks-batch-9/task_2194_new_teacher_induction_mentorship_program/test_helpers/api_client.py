"""One method per endpoint of the induction mentorship API.

Paths are served under the API root with no version or resource prefix, so the
literal paths of the PRD's endpoint table are used verbatim.  Every method
returns the raw response so tests can assert status codes themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class InductionApiClient(GenericApiClient):
    """Thin endpoint surface for the district induction program API."""

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------
    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/sites/{site_id}", None, headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sites", params, headers)

    def close_site(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sites/{site_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Mentors
    # ------------------------------------------------------------------
    def create_mentor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/mentors", payload, headers)

    def get_mentor(self, mentor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/mentors/{mentor_id}", None, headers)

    def list_mentors(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/mentors", params, headers)

    def post_training_credit(
        self, mentor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/mentors/{mentor_id}/training-credits", payload, headers)

    def certification_action(
        self, mentor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/mentors/{mentor_id}/certification", payload, headers)

    # ------------------------------------------------------------------
    # Cohorts
    # ------------------------------------------------------------------
    def create_cohort(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cohorts/{cohort_id}", None, headers)

    def list_cohorts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/cohorts", params, headers)

    def close_cohort(
        self, cohort_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cohorts/{cohort_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Novice teachers
    # ------------------------------------------------------------------
    def create_novice(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/novice-teachers", payload, headers)

    def get_novice(self, novice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/novice-teachers/{novice_id}", None, headers)

    def list_novices(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/novice-teachers", params, headers)

    def get_readiness(self, novice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/novice-teachers/{novice_id}/readiness", None, headers)

    def withdraw_novice(
        self, novice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/novice-teachers/{novice_id}/withdraw", payload, headers)

    def record_retention_outcome(
        self, novice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/novice-teachers/{novice_id}/retention-outcome", payload, headers
        )

    # ------------------------------------------------------------------
    # Mentor matches
    # ------------------------------------------------------------------
    def create_match(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/mentor-matches", payload, headers)

    def get_match(self, match_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/mentor-matches/{match_id}", None, headers)

    def list_matches(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/mentor-matches", params, headers)

    def dispose_match(
        self, match_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/mentor-matches/{match_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Contact logs
    # ------------------------------------------------------------------
    def create_contact_log(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/contact-logs", payload, headers)

    def get_contact_log(self, log_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/contact-logs/{log_id}", None, headers)

    def list_contact_logs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/contact-logs", params, headers)

    def review_contact_log(
        self, log_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/contact-logs/{log_id}/review", payload, headers)

    def resubmit_contact_log(
        self, log_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/contact-logs/{log_id}/resubmit", payload, headers)

    def void_contact_log(
        self, log_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/contact-logs/{log_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Observation cycles
    # ------------------------------------------------------------------
    def create_observation_cycle(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/observation-cycles", payload, headers)

    def get_observation_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/observation-cycles/{cycle_id}", None, headers)

    def list_observation_cycles(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/observation-cycles", params, headers)

    def advance_cycle(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/observation-cycles/{cycle_id}/advance", payload, headers)

    def write_feedback(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/observation-cycles/{cycle_id}/feedback", payload, headers)

    def review_feedback(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/observation-cycles/{cycle_id}/feedback-review", payload, headers
        )

    # ------------------------------------------------------------------
    # Milestones and attainments
    # ------------------------------------------------------------------
    def create_milestone(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/milestones", payload, headers)

    def get_milestone(self, milestone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/milestones/{milestone_id}", None, headers)

    def list_milestones(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/milestones", params, headers)

    def create_attainment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/milestone-attainments", payload, headers)

    def get_attainment(self, attainment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/milestone-attainments/{attainment_id}", None, headers)

    def list_attainments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/milestone-attainments", params, headers)

    def attainment_decision(
        self, attainment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/milestone-attainments/{attainment_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Seminar sessions and attendance
    # ------------------------------------------------------------------
    def create_seminar_session(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/seminar-sessions", payload, headers)

    def get_seminar_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/seminar-sessions/{session_id}", None, headers)

    def list_seminar_sessions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/seminar-sessions", params, headers)

    def set_session_status(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/seminar-sessions/{session_id}/status", payload, headers)

    def create_attendance(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/seminar-attendances", payload, headers)

    def get_attendance(self, attendance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/seminar-attendances/{attendance_id}", None, headers)

    def list_attendances(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/seminar-attendances", params, headers)

    # ------------------------------------------------------------------
    # Stipend disbursements
    # ------------------------------------------------------------------
    def create_disbursement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/stipend-disbursements", payload, headers)

    def get_disbursement(self, disbursement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/stipend-disbursements/{disbursement_id}", None, headers)

    def list_disbursements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/stipend-disbursements", params, headers)

    def set_disbursement_status(
        self, disbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/stipend-disbursements/{disbursement_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Completion certification packets
    # ------------------------------------------------------------------
    def create_packet(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/completion-certifications", payload, headers)

    def get_packet(self, packet_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/completion-certifications/{packet_id}", None, headers)

    def list_packets(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/completion-certifications", params, headers)

    def packet_transition(
        self, packet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/completion-certifications/{packet_id}/transition", payload, headers
        )

    def packet_state_decision(
        self, packet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/completion-certifications/{packet_id}/state-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock test hook
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )
