"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock (PRD §2.5 — TestHarness)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    # =======================================================================
    # Exam lifecycle (PRD §3.1, §3.7, §4)
    # =======================================================================
    def create_exam(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/exams", payload, headers)

    def list_exams(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/exams", headers=headers, params=params)

    def get_exam(self, exam_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/exams/{exam_id}", headers=headers)

    def open_registration(self, exam_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/exams/{exam_id}/open-registration", headers=headers,
        )

    def close_registration(self, exam_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/exams/{exam_id}/close-registration", headers=headers,
        )

    def publish_scores(self, exam_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/exams/{exam_id}/publish-scores", headers=headers,
        )

    # =======================================================================
    # Question bank (PRD §3.1, §4)
    # =======================================================================
    def create_question(self, exam_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/exams/{exam_id}/questions", payload, headers,
        )

    def list_questions(self, exam_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/exams/{exam_id}/questions",
            headers=headers, params=params,
        )

    def get_question(self, exam_id: str, question_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/exams/{exam_id}/questions/{question_id}",
            headers=headers,
        )

    # =======================================================================
    # CandidateRegistration (PRD §3.1, §4)
    # =======================================================================
    def create_registration(self, exam_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/exams/{exam_id}/registrations", payload, headers,
        )

    def list_registrations(self, exam_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/exams/{exam_id}/registrations",
            headers=headers, params=params,
        )

    # =======================================================================
    # ExamAttempt (PRD §3.2, §3.4, §3.5, §4)
    # =======================================================================
    def create_attempt(self, exam_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/exams/{exam_id}/attempts", payload, headers,
        )

    def get_attempt(self, exam_id: str, attempt_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/exams/{exam_id}/attempts/{attempt_id}",
            headers=headers,
        )

    def begin_identity_check(self, exam_id: str, attempt_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/begin-identity-check",
            headers=headers,
        )

    def submit_identity_verification(self, exam_id: str, attempt_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/identity-verifications",
            payload, headers,
        )

    def network_disconnect(self, exam_id: str, attempt_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/network-disconnect",
            headers=headers,
        )

    def network_resume(self, exam_id: str, attempt_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/network-resume",
            headers=headers,
        )

    def record_abnormal_event(self, exam_id: str, attempt_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/abnormal-events",
            payload, headers,
        )

    def list_abnormal_events(self, exam_id: str, attempt_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/exams/{exam_id}/attempts/{attempt_id}/abnormal-events",
            headers=headers, params=params,
        )

    def submit_attempt(self, exam_id: str, attempt_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/submit",
            payload, headers,
        )

    # =======================================================================
    # GradingAssignment (PRD §3.6, §4)
    # =======================================================================
    def list_grading_assignments(self, exam_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/exams/{exam_id}/grading-assignments",
            headers=headers, params=params,
        )

    def claim_grading_assignment(self, exam_id: str, assignment_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/grading-assignments/{assignment_id}/claim",
            headers=headers,
        )

    def score_grading_assignment(self, exam_id: str, assignment_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/grading-assignments/{assignment_id}/score",
            payload, headers,
        )

    # =======================================================================
    # Appeal (PRD §3.7, §4)
    # =======================================================================
    def create_appeal(self, exam_id: str, attempt_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/attempts/{attempt_id}/appeals",
            payload, headers,
        )

    def claim_appeal(self, exam_id: str, appeal_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/appeals/{appeal_id}/claim",
            headers=headers,
        )

    def secondary_mark_appeal(self, exam_id: str, appeal_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/appeals/{appeal_id}/secondary-mark",
            payload, headers,
        )

    def decide_appeal(self, exam_id: str, appeal_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exams/{exam_id}/appeals/{appeal_id}/decide",
            payload, headers,
        )

    def list_appeals(self, exam_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/exams/{exam_id}/appeals",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit log (PRD §2.9, §4)
    # =======================================================================
    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-log", headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
