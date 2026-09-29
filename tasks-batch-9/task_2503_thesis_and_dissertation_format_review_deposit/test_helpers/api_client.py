"""API client: one method per endpoint defined in the PRD.

All paths are mounted under /graduate-school.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/graduate-school"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_term(self, term_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/terms/{term_id}", headers=headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/students/{student_id}", headers=headers)

    def list_student_graduation_clearances(
        self, student_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/students/{student_id}/graduation-clearances",
            headers=headers,
            params=params,
        )

    def get_faculty_member(self, faculty_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/faculty-members/{faculty_id}", headers=headers
        )

    def get_defense_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/defense-rooms/{room_id}", headers=headers)

    def list_theses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/theses", headers=headers, params=params)

    def get_thesis(self, thesis_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/theses/{thesis_id}", headers=headers)

    def get_thesis_committee(self, thesis_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/theses/{thesis_id}/committee", headers=headers
        )

    def list_thesis_format_reviews(
        self, thesis_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/theses/{thesis_id}/format-reviews",
            headers=headers,
            params=params,
        )

    def list_thesis_embargo_requests(
        self, thesis_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/theses/{thesis_id}/embargo-requests",
            headers=headers,
            params=params,
        )

    def list_thesis_permission_records(
        self, thesis_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/theses/{thesis_id}/permission-records",
            headers=headers,
            params=params,
        )

    def list_thesis_integrity_screenings(
        self, thesis_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/theses/{thesis_id}/integrity-screenings",
            headers=headers,
            params=params,
        )

    def get_thesis_repository_deposit(
        self, thesis_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/theses/{thesis_id}/repository-deposit",
            headers=headers,
            params=params,
        )

    def get_deposit_readiness(self, thesis_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/theses/{thesis_id}/deposit-readiness", headers=headers
        )

    def get_committee_member(self, seat_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/committee-members/{seat_id}", headers=headers
        )

    def list_committee_members(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/committee-members", headers=headers, params=params
        )

    def get_defense_event(self, defense_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/defense-events/{defense_id}", headers=headers
        )

    def list_defense_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/defense-events", headers=headers, params=params
        )

    def get_format_review(self, review_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/format-reviews/{review_id}", headers=headers
        )

    def get_embargo_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/embargo-requests/{request_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Registrar groundwork
    # ------------------------------------------------------------------

    def create_term(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/terms", payload, headers)

    def close_term_deposit(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/terms/{term_id}/close-deposit", {}, headers
        )

    def confer_term_degrees(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/terms/{term_id}/confer-degrees", {}, headers
        )

    def create_student(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/students", payload, headers)

    def create_faculty_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/faculty-members", payload, headers)

    def create_defense_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/defense-rooms", payload, headers)

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{BASE}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Thesis, committee, defense
    # ------------------------------------------------------------------

    def create_thesis(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/theses", payload, headers)

    def create_committee(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/committees", payload, headers)

    def create_committee_member(
        self, committee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/committees/{committee_id}/members", payload, headers
        )

    def release_committee_member(
        self,
        seat_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """Soft-delete a seat, carrying the withdrawal reason two equivalent ways.

        The reason travels both as a query parameter and as a JSON body so the
        request is readable whichever convention the service uses for a delete
        that carries data.
        """
        return self.session.request(
            "DELETE",
            f"{self.base_url}{BASE}/committee-members/{seat_id}",
            headers=headers or {},
            params=payload or None,
            json=payload,
        )

    def submit_committee(self, committee_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/committees/{committee_id}/submit", {}, headers
        )

    def decide_committee(
        self, committee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/committees/{committee_id}/decision", payload, headers
        )

    def create_defense_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/defense-events", payload, headers)

    def announce_defense_event(self, defense_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/defense-events/{defense_id}/announce", {}, headers
        )

    def record_defense_outcome(
        self, defense_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/defense-events/{defense_id}/outcome", payload, headers
        )

    def cancel_defense_event(
        self, defense_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/defense-events/{defense_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Format review, permissions, screening
    # ------------------------------------------------------------------

    def create_format_submission(self, thesis_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/theses/{thesis_id}/format-submissions", {}, headers
        )

    def decide_format_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/format-reviews/{review_id}/decision", payload, headers
        )

    def create_permission_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/permission-records", payload, headers)

    def review_permission_record(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/permission-records/{record_id}/review", payload, headers
        )

    def create_integrity_screening(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/integrity-screenings", payload, headers)

    def act_on_integrity_screening(
        self, screening_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/integrity-screenings/{screening_id}/action",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Embargo and deposit
    # ------------------------------------------------------------------

    def create_embargo_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/embargo-requests", payload, headers)

    def decide_embargo_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/embargo-requests/{request_id}/decision", payload, headers
        )

    def supplement_embargo_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/embargo-requests/{request_id}/supplement", payload, headers
        )

    def create_repository_deposit(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/repository-deposits", payload, headers)


api_client = ApiClient()
