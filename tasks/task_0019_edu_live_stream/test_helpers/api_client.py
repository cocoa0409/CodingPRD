"""API client: one method per endpoint defined in the Edu Live Stream PRD §4."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client. Every method returns the raw requests.Response."""

    # ─────────────────── Courses ───────────────────

    def create_course(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def patch_course(self, course_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/courses/{course_id}", payload, headers)

    def submit_course_for_review(self, course_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/submit-for-review", headers=headers)

    def approve_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/approve", headers=headers)

    def reject_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/reject", headers=headers)

    def return_course_to_draft(self, course_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/return-to-draft", headers=headers)

    def delist_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/delist", headers=headers)

    def list_syllabus_revisions(self, course_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/courses/{course_id}/syllabus-revisions", headers=headers, params=params
        )

    # ─────────────────── Chapters ───────────────────

    def create_chapter(self, course_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/chapters", payload, headers)

    def list_chapters(self, course_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/courses/{course_id}/chapters", headers=headers, params=params)

    # ─────────────────── Instructors / Students ───────────────────

    def create_instructor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def patch_instructor_availability(self, instructor_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/instructors/{instructor_id}/availability", payload, headers
        )

    def create_student(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/students", payload, headers)

    # ─────────────────── Enrollments ───────────────────

    def create_enrollment(self, course_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    # ─────────────────── Class groups + announcements ───────────────────

    def create_class_group(self, course_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/class-groups", payload, headers)

    def assign_enrollment_to_group(self, class_group_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/class-groups/{class_group_id}/assign-enrollment", payload, headers
        )

    def create_announcement(self, class_group_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/class-groups/{class_group_id}/announcements", payload, headers
        )

    # ─────────────────── Live classes + attendance + leave ───────────────────

    def create_live_class(self, course_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/live-classes", payload, headers)

    def start_live_class(self, live_class_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/live-classes/{live_class_id}/start", headers=headers)

    def end_live_class(self, live_class_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/live-classes/{live_class_id}/end", headers=headers)

    def reschedule_live_class(self, live_class_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/live-classes/{live_class_id}/reschedule", payload, headers
        )

    def check_in(self, live_class_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/live-classes/{live_class_id}/check-in", payload, headers)

    def create_leave_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/leave-requests", payload, headers)

    def approve_leave_request(self, leave_request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/leave-requests/{leave_request_id}/approve", headers=headers)

    def reject_leave_request(self, leave_request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/leave-requests/{leave_request_id}/reject", headers=headers)

    # ─────────────────── Assignments + submissions ───────────────────

    def create_assignment(self, course_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/courses/{course_id}/assignments", payload, headers)

    def create_submission(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/assignments/{assignment_id}/submissions", payload, headers
        )

    def update_submission_payload(self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/submissions/{submission_id}/payload", payload, headers)

    def start_submission_review(self, submission_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/submissions/{submission_id}/start-review", headers=headers)

    def request_submission_revision(self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/submissions/{submission_id}/request-revision", payload, headers
        )

    def grade_submission(self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/submissions/{submission_id}/grade", payload, headers)

    # ─────────────────── Watch sessions ───────────────────

    def create_watch_session(self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/watch-sessions", payload, headers
        )

    # ─────────────────── Refund requests ───────────────────

    def create_refund_request(self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/refund-requests", payload, headers
        )

    def approve_refund_request(self, refund_request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refund-requests/{refund_request_id}/approve", headers=headers)

    def reject_refund_request(self, refund_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/refund-requests/{refund_request_id}/reject", payload, headers)

    def list_refund_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    # ─────────────────── Audit + test-driving ───────────────────

    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    def advance_clock(self, seconds: int, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"seconds": seconds}, headers)

    def sweep_at_risk(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/at-risk", headers=headers)


api_client = ApiClient()
