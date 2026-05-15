"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. All paths carry the `/training` prefix per PRD §4.
Tests pass headers explicitly because PRD §2.1 requires X-User-ID and
X-User-Role on every call (except the public certificate-verification
endpoint).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Course categories (PRD §3.1)
    # =======================================================================
    def create_course_category(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/training/course-categories", payload, headers,
        )

    def list_course_categories(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/course-categories",
            headers=headers, params=params,
        )

    def update_course_category(self, category_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/training/course-categories/{category_id}",
            payload, headers,
        )

    # =======================================================================
    # Courses (PRD §3.1)
    # =======================================================================
    def create_course(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/training/courses", payload, headers)

    def list_courses(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/courses", headers=headers, params=params,
        )

    def get_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/courses/{course_id}", headers=headers,
        )

    def update_course(self, course_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/training/courses/{course_id}", payload, headers,
        )

    def submit_course_for_review(self, course_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/courses/{course_id}/submit-for-review",
            {}, headers,
        )

    def publish_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/courses/{course_id}/publish", {}, headers,
        )

    def reject_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/courses/{course_id}/reject", {}, headers,
        )

    def unpublish_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/courses/{course_id}/unpublish", {}, headers,
        )

    def archive_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/courses/{course_id}/archive", {}, headers,
        )

    def list_course_versions(self, course_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/courses/{course_id}/versions",
            headers=headers,
        )

    # =======================================================================
    # Instructors (PRD §3.2)
    # =======================================================================
    def create_instructor(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/training/instructors", payload, headers,
        )

    def list_instructors(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/instructors", headers=headers, params=params,
        )

    def update_instructor(self, instructor_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/training/instructors/{instructor_id}",
            payload, headers,
        )

    def blacklist_instructor(self, instructor_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/instructors/{instructor_id}/blacklist",
            payload, headers,
        )

    def reinstate_instructor(self, instructor_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/instructors/{instructor_id}/reinstate",
            {}, headers,
        )

    def create_instructor_availability(self, instructor_id: str,
                                       payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/training/instructors/{instructor_id}/availabilities",
            payload, headers,
        )

    # =======================================================================
    # Classrooms / OnlineRooms (PRD §3.3)
    # =======================================================================
    def create_classroom(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", "/training/classrooms", payload, headers,
        )

    def create_online_room(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/training/online-rooms", payload, headers,
        )

    # =======================================================================
    # Sessions (PRD §3.3, §3.5)
    # =======================================================================
    def create_session(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", "/training/sessions", payload, headers,
        )

    def list_sessions(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/sessions", headers=headers, params=params,
        )

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/sessions/{session_id}", headers=headers,
        )

    def open_session_enrollment(self, session_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/sessions/{session_id}/open-enrollment",
            {}, headers,
        )

    def complete_session(self, session_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/sessions/{session_id}/complete",
            {}, headers,
        )

    def cancel_session(self, session_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/sessions/{session_id}/cancel",
            payload, headers,
        )

    def get_instructor_fee(self, session_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/sessions/{session_id}/instructor-fee",
            headers=headers,
        )

    def create_check_in(self, session_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/sessions/{session_id}/check-ins",
            payload, headers,
        )

    # =======================================================================
    # Enrollments (PRD §3.4)
    # =======================================================================
    def create_enrollment(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/training/enrollments", payload, headers,
        )

    def list_enrollments(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/enrollments", headers=headers, params=params,
        )

    def approve_enrollment(self, enrollment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/enrollments/{enrollment_id}/approve",
            {}, headers,
        )

    def reject_enrollment(self, enrollment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/enrollments/{enrollment_id}/reject",
            payload, headers,
        )

    def cancel_enrollment(self, enrollment_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/enrollments/{enrollment_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Exam attempts and evaluations (PRD §3.5)
    # =======================================================================
    def create_exam_attempt(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/training/exam-attempts", payload, headers,
        )

    def submit_exam_attempt(self, attempt_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/exam-attempts/{attempt_id}/submit",
            payload, headers,
        )

    def create_evaluation(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/training/evaluations", payload, headers,
        )

    # =======================================================================
    # Credit pools and adjustments (PRD §2.11, §3.6)
    # =======================================================================
    def create_credit_pool(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/training/credit-pools", payload, headers,
        )

    def list_credit_pools(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/credit-pools",
            headers=headers, params=params,
        )

    def get_credit_pool(self, pool_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/credit-pools/{pool_id}", headers=headers,
        )

    def create_credit_adjustment(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/training/credit-adjustments", payload, headers,
        )

    # =======================================================================
    # Certificate templates / certificates (PRD §3.7)
    # =======================================================================
    def create_certificate_template(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", "/training/certificate-templates", payload, headers,
        )

    def list_certificates(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/certificates",
            headers=headers, params=params,
        )

    def get_certificate(self, certificate_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/certificates/{certificate_id}",
            headers=headers,
        )

    def renew_certificate(self, certificate_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/certificates/{certificate_id}/renew",
            payload, headers,
        )

    def revoke_certificate(self, certificate_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/training/certificates/{certificate_id}/revoke",
            payload, headers,
        )

    def verify_certificate(self, verification_code: str,
                           headers: Optional[Dict[str, str]] = None):
        # Public endpoint: PRD §2.1 — "The only exception is the public
        # certificate-verification endpoint ... which serves anonymous
        # traffic." Tests may pass empty headers.
        return self._request(
            "POST",
            f"/training/certificates/verify/{verification_code}",
            {}, headers or {},
        )

    # =======================================================================
    # Trainees (PRD §3.4)
    # =======================================================================
    def create_trainee(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", "/training/trainees", payload, headers,
        )

    def get_trainee(self, trainee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/training/trainees/{trainee_id}", headers=headers,
        )

    # =======================================================================
    # Sync events & audit logs (PRD §3.8)
    # =======================================================================
    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", "/training/_events/emit", payload, headers,
        )

    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/training/audit-logs",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driver endpoints — clock + sweep (PRD §2.10, §2.11)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/training/_clock/advance", payload, headers,
        )

    def sweep_run(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/training/_sweep/run", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
