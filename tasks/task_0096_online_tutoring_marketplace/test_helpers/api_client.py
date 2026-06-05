"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only the PRD-specific endpoint
methods are defined here. The base _request() handles URL construction,
session reuse, and JSON/query encoding.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Deterministic clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # --- Subjects ---
    def create_subject(self, payload, headers):
        return self._request("POST", "/subjects", payload, headers)

    def get_subject(self, subject_id, headers):
        return self._request("GET", f"/subjects/{subject_id}", headers=headers)

    # --- Commission policies ---
    def create_commission_policy(self, payload, headers):
        return self._request("POST", "/commission-policies", payload, headers)

    def activate_commission_policy(self, policy_id, headers):
        return self._request(
            "POST", f"/commission-policies/{policy_id}/activate", {}, headers
        )

    def get_commission_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/commission-policies/{policy_id}", headers=headers
        )

    # --- Tutors ---
    def create_tutor(self, payload, headers):
        return self._request("POST", "/tutors", payload, headers)

    def get_tutor(self, tutor_id, headers):
        return self._request("GET", f"/tutors/{tutor_id}", headers=headers)

    def suspend_tutor(self, tutor_id, headers):
        return self._request("POST", f"/tutors/{tutor_id}/suspend", {}, headers)

    def reinstate_tutor(self, tutor_id, headers):
        return self._request("POST", f"/tutors/{tutor_id}/reinstate", {}, headers)

    # --- Credentials ---
    def create_credential(self, payload, headers):
        return self._request("POST", "/credentials", payload, headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/credentials", headers=headers, params=params)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def start_review_credential(self, credential_id, headers):
        return self._request(
            "POST", f"/credentials/{credential_id}/start-review", {}, headers
        )

    def verify_credential(self, credential_id, headers):
        return self._request(
            "POST", f"/credentials/{credential_id}/verify", {}, headers
        )

    def reject_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/credentials/{credential_id}/reject", payload, headers
        )

    def expire_credential(self, credential_id, headers):
        return self._request(
            "POST", f"/credentials/{credential_id}/expire", {}, headers
        )

    # --- Tutor subject tags ---
    def create_subject_tag(self, payload, headers):
        return self._request("POST", "/subject-tags", payload, headers)

    def list_subject_tags(self, headers, params=None):
        return self._request("GET", "/subject-tags", headers=headers, params=params)

    def get_subject_tag(self, tag_id, headers):
        return self._request("GET", f"/subject-tags/{tag_id}", headers=headers)

    def approve_subject_tag(self, tag_id, headers):
        return self._request("POST", f"/subject-tags/{tag_id}/approve", {}, headers)

    def revoke_subject_tag(self, tag_id, headers):
        return self._request("POST", f"/subject-tags/{tag_id}/revoke", {}, headers)

    # --- Parent accounts ---
    def create_parent_account(self, payload, headers):
        return self._request("POST", "/parent-accounts", payload, headers)

    def get_parent_account(self, parent_id, headers):
        return self._request("GET", f"/parent-accounts/{parent_id}", headers=headers)

    def deposit(self, parent_id, payload, headers):
        return self._request(
            "POST", f"/parent-accounts/{parent_id}/deposit", payload, headers
        )

    # --- Students ---
    def create_student(self, parent_id, payload, headers):
        return self._request(
            "POST", f"/parent-accounts/{parent_id}/students", payload, headers
        )

    def list_students(self, parent_id, headers, params=None):
        return self._request(
            "GET", f"/parent-accounts/{parent_id}/students", headers=headers, params=params
        )

    def archive_student(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/archive", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def request_reschedule(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/request-reschedule", payload, headers
        )

    def confirm_reschedule(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/confirm-reschedule", payload, headers
        )

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def deliver_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/deliver", payload, headers
        )

    def mark_no_show(self, booking_id, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/mark-no-show", {}, headers
        )

    # --- Sessions ---
    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def confirm_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/confirm", {}, headers)

    def dispute_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/dispute", {}, headers)

    # --- Settlements ---
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    # --- Refund cases ---
    def create_refund_case(self, payload, headers):
        return self._request("POST", "/refund-cases", payload, headers)

    def list_refund_cases(self, headers, params=None):
        return self._request("GET", "/refund-cases", headers=headers, params=params)

    def get_refund_case(self, case_id, headers):
        return self._request("GET", f"/refund-cases/{case_id}", headers=headers)

    def counter_refund_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/counter", payload, headers
        )

    def repropose_refund_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/repropose", payload, headers
        )

    def accept_counter_refund_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/accept-counter", payload, headers
        )

    def accept_offer_refund_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/accept-offer", payload, headers
        )

    def escalate_refund_case(self, case_id, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/escalate", {}, headers
        )

    def arbitrate_refund_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/arbitrate", payload, headers
        )

    def withdraw_refund_case(self, case_id, headers):
        return self._request(
            "POST", f"/refund-cases/{case_id}/withdraw", {}, headers
        )


api_client = ApiClient()
