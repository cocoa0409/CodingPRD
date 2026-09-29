"""Thin HTTP client with one method per declared endpoint.

Every collection is mounted directly at the root of the API, so each path below
is complete as written.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per endpoint of the adult-education HSE testing service."""

    # -- learners ---------------------------------------------------------

    def create_student(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/students", payload=payload, headers=headers)

    def complete_orientation(
        self, student_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/students/{student_id}/orientation-completion",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def adjust_voucher(
        self, student_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/students/{student_id}/voucher-adjustments", payload=payload, headers=headers
        )

    def get_student(self, student_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", "/students", params=params, headers=headers)

    def get_skill_gain(
        self, student_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/students/{student_id}/skill-gain", params=params, headers=headers
        )

    # -- testing centres --------------------------------------------------

    def create_testing_center(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/testing-centers", payload=payload, headers=headers)

    def decide_center_authorization(
        self, center_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/testing-centers/{center_id}/authorization-decision",
            payload=payload,
            headers=headers,
        )

    def suspend_center(
        self, center_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/testing-centers/{center_id}/suspend", payload=payload, headers=headers
        )

    def get_testing_center(self, center_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/testing-centers/{center_id}", headers=headers)

    def list_testing_centers(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/testing-centers", params=params, headers=headers)

    # -- testing rooms ----------------------------------------------------

    def create_testing_room(
        self, center_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/testing-centers/{center_id}/rooms", payload=payload, headers=headers
        )

    def take_room_out_of_service(
        self, room_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/testing-rooms/{room_id}/out-of-service", payload=payload, headers=headers
        )

    def get_testing_room(self, room_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/testing-rooms/{room_id}", headers=headers)

    def list_testing_rooms(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/testing-rooms", params=params, headers=headers)

    # -- proctors ---------------------------------------------------------

    def create_proctor(
        self, center_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/testing-centers/{center_id}/proctors", payload=payload, headers=headers
        )

    def decide_proctor_certification(
        self, proctor_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/proctors/{proctor_id}/certification-decision",
            payload=payload,
            headers=headers,
        )

    def get_proctor(self, proctor_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/proctors/{proctor_id}", headers=headers)

    def list_proctors(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", "/proctors", params=params, headers=headers)

    # -- class sections ---------------------------------------------------

    def create_class_section(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/class-sections", payload=payload, headers=headers)

    def transition_class_section(
        self, section_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/class-sections/{section_id}/status-transition",
            payload=payload,
            headers=headers,
        )

    def get_class_section(self, section_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/class-sections/{section_id}", headers=headers)

    def list_class_sections(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/class-sections", params=params, headers=headers)

    # -- enrollments ------------------------------------------------------

    def create_enrollment(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/enrollments", payload=payload, headers=headers)

    def withdraw_enrollment(
        self, enrollment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", payload=payload, headers=headers
        )

    def get_enrollment(self, enrollment_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/enrollments", params=params, headers=headers)

    # -- attendance -------------------------------------------------------

    def create_attendance_entry(
        self, enrollment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/attendance-entries",
            payload=payload,
            headers=headers,
        )

    def void_attendance_entry(
        self, entry_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/attendance-entries/{entry_id}/void", payload=payload, headers=headers
        )

    def get_attendance_entry(self, entry_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/attendance-entries/{entry_id}", headers=headers)

    def list_attendance_entries(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/attendance-entries", params=params, headers=headers)

    # -- standardised test events ----------------------------------------

    def create_test_event(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/test-events", payload=payload, headers=headers)

    def score_test_event(
        self, test_event_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-events/{test_event_id}/score", payload=payload, headers=headers
        )

    def get_test_event(self, test_event_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/test-events/{test_event_id}", headers=headers)

    def list_test_events(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/test-events", params=params, headers=headers)

    # -- exam sittings ----------------------------------------------------

    def create_exam_session(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/exam-sessions", payload=payload, headers=headers)

    def assign_proctor(
        self, session_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/exam-sessions/{session_id}/proctor-assignment",
            payload=payload,
            headers=headers,
        )

    def cancel_exam_session(
        self, session_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/exam-sessions/{session_id}/cancel", payload=payload, headers=headers
        )

    def get_exam_session(self, session_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/exam-sessions/{session_id}", headers=headers)

    def list_exam_sessions(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/exam-sessions", params=params, headers=headers)

    # -- exam registrations ----------------------------------------------

    def create_exam_registration(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/exam-registrations", payload=payload, headers=headers)

    def verify_identity(
        self, registration_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/exam-registrations/{registration_id}/identity-verification",
            payload=payload,
            headers=headers,
        )

    def check_in(
        self, registration_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/exam-registrations/{registration_id}/check-in",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def record_result(
        self, registration_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/exam-registrations/{registration_id}/result",
            payload=payload,
            headers=headers,
        )

    def cancel_exam_registration(
        self, registration_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/exam-registrations/{registration_id}/cancel",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_exam_registration(
        self, registration_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/exam-registrations/{registration_id}", headers=headers)

    def list_exam_registrations(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/exam-registrations", params=params, headers=headers)

    # -- accommodations ---------------------------------------------------

    def create_accommodation_request(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/accommodation-requests", payload=payload, headers=headers)

    def request_accommodation_info(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/info-request",
            payload=payload,
            headers=headers,
        )

    def resubmit_accommodation(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/resubmission",
            payload=payload,
            headers=headers,
        )

    def decide_accommodation(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/decision",
            payload=payload,
            headers=headers,
        )

    def get_accommodation_request(
        self, request_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/accommodation-requests/{request_id}", headers=headers)

    def list_accommodation_requests(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/accommodation-requests", params=params, headers=headers)

    # -- credentials ------------------------------------------------------

    def issue_credential(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/credentials", payload=payload, headers=headers)

    def get_credential(self, credential_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def list_credentials(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/credentials", params=params, headers=headers)

    # -- transcript orders ------------------------------------------------

    def create_transcript_order(
        self, student_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/students/{student_id}/transcript-orders", payload=payload, headers=headers
        )

    def fulfill_transcript_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/transcript-orders/{order_id}/fulfillment",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_transcript_order(self, order_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/transcript-orders/{order_id}", headers=headers)

    def list_transcript_orders(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/transcript-orders", params=params, headers=headers)

    # -- outcome claims ---------------------------------------------------

    def create_outcome_record(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/outcome-records", payload=payload, headers=headers)

    def decide_outcome_certification(
        self, outcome_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/outcome-records/{outcome_id}/certification", payload=payload, headers=headers
        )

    def get_outcome_record(self, outcome_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/outcome-records/{outcome_id}", headers=headers)

    def list_outcome_records(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/outcome-records", params=params, headers=headers)

    # -- funding periods --------------------------------------------------

    def create_funding_period(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/funding-periods", payload=payload, headers=headers)

    def run_allocation(
        self, period_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/funding-periods/{period_id}/allocation-run", payload=payload, headers=headers
        )

    def close_funding_period(
        self, period_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/funding-periods/{period_id}/close",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_funding_period(self, period_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/funding-periods/{period_id}", headers=headers)

    def list_funding_periods(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/funding-periods", params=params, headers=headers)

    def get_allocation_preview(
        self, period_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/funding-periods/{period_id}/allocation-preview", params=params, headers=headers
        )

    # -- logical clock ----------------------------------------------------

    def set_clock(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    def get_clock(self, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/_clock/current_utc", headers=headers)


#: Shared client instance used by every test.
api_client = ApiClient()
