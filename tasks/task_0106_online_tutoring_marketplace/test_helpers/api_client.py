"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Tutor — PRD §4
    # =======================================================================
    def create_tutor(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/tutoring/tutors", payload, headers)

    def get_tutor(self, tutor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tutoring/tutors/{tutor_id}", headers=headers,
        )

    def patch_tutor(self, tutor_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/tutoring/tutors/{tutor_id}", payload, headers,
        )

    def list_tutors(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tutoring/tutors", headers=headers, params=params,
        )

    def suspend_tutor(self, tutor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/tutors/{tutor_id}/suspend", {}, headers,
        )

    def reinstate_tutor(self, tutor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/tutors/{tutor_id}/reinstate", {}, headers,
        )

    # =======================================================================
    # Credential — PRD §4
    # =======================================================================
    def submit_credential(self, tutor_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/tutors/{tutor_id}/credentials",
            payload, headers,
        )

    def approve_credential(self, tutor_id: str, credential_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tutoring/tutors/{tutor_id}/credentials/"
            f"{credential_id}/approve",
            {}, headers,
        )

    def reject_credential(self, tutor_id: str, credential_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tutoring/tutors/{tutor_id}/credentials/"
            f"{credential_id}/reject",
            {}, headers,
        )

    # =======================================================================
    # SubjectTag — PRD §4
    # =======================================================================
    def propose_subject(self, tutor_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/tutors/{tutor_id}/subjects",
            payload, headers,
        )

    def approve_subject(self, tutor_id: str, subject_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tutoring/tutors/{tutor_id}/subjects/{subject_id}/approve",
            {}, headers,
        )

    def delete_subject(self, tutor_id: str, subject_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/tutoring/tutors/{tutor_id}/subjects/{subject_id}",
            headers=headers,
        )

    # =======================================================================
    # Student — PRD §4
    # =======================================================================
    def create_student(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", "/tutoring/students", payload, headers,
        )

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tutoring/students/{student_id}", headers=headers,
        )

    # =======================================================================
    # Parent + ParentChildLink — PRD §4
    # =======================================================================
    def create_parent(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/tutoring/parents", payload, headers,
        )

    def get_parent(self, parent_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tutoring/parents/{parent_id}", headers=headers,
        )

    def list_parent_links(self, parent_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tutoring/parents/{parent_id}/links",
            headers=headers, params=params,
        )

    def approve_link(self, parent_id: str, link_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tutoring/parents/{parent_id}/links/{link_id}/approve",
            {}, headers,
        )

    def revoke_link(self, parent_id: str, link_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/tutoring/parents/{parent_id}/links/{link_id}",
            headers=headers,
        )

    # =======================================================================
    # Session — PRD §4
    # =======================================================================
    def book_session(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", "/tutoring/sessions", payload, headers,
        )

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tutoring/sessions/{session_id}", headers=headers,
        )

    def list_sessions(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tutoring/sessions", headers=headers, params=params,
        )

    def confirm_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/sessions/{session_id}/confirm",
            {}, headers,
        )

    def cancel_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/sessions/{session_id}/cancel",
            {}, headers,
        )

    def complete_session(self, session_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/sessions/{session_id}/complete",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # RefundDispute — PRD §4
    # =======================================================================
    def open_dispute(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", "/tutoring/disputes", payload, headers,
        )

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tutoring/disputes/{dispute_id}", headers=headers,
        )

    def respond_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/respond",
            {}, headers,
        )

    def counter_dispute(self, dispute_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/counter",
            payload, headers,
        )

    def accept_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/accept",
            {}, headers,
        )

    def reopen_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/reopen",
            {}, headers,
        )

    def escalate_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/escalate",
            {}, headers,
        )

    def arbitrate_dispute(self, dispute_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/arbitrate",
            payload, headers,
        )

    def withdraw_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/disputes/{dispute_id}/withdraw",
            {}, headers,
        )

    # =======================================================================
    # PayoutBatch — PRD §4
    # =======================================================================
    def create_payout(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/tutoring/payouts", payload, headers,
        )

    def mark_payout_paid(self, payout_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/payouts/{payout_id}/mark-paid",
            {}, headers,
        )

    def reverse_payout(self, payout_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tutoring/payouts/{payout_id}/reverse",
            {}, headers,
        )

    def list_payouts(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tutoring/payouts", headers=headers, params=params,
        )

    # =======================================================================
    # Clock — PRD §4 (PlatformAdmin only for advance)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/tutoring/_clock/advance", payload, headers,
        )

    def read_clock(self, headers: Dict[str, str]):
        return self._request(
            "GET", "/tutoring/_clock", headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
