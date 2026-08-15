"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ExamCycle ---
    def create_exam_cycle(self, payload, headers):
        return self._request("POST", "/exam-cycles", payload, headers)

    def get_exam_cycle(self, cycle_id, headers):
        return self._request("GET", f"/exam-cycles/{cycle_id}", headers=headers)

    def open_exam_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/exam-cycles/{cycle_id}/open", headers=headers
        )

    def get_equity_report(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/exam-cycles/{cycle_id}/equity-report",
            headers=headers,
            params=params,
        )

    def release_scores(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/exam-cycles/{cycle_id}/release-scores", payload, headers
        )

    # --- Course ---
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    # --- Teacher ---
    def create_teacher(self, payload, headers):
        return self._request("POST", "/teachers", payload, headers)

    # --- TeacherAuthorization ---
    def create_teacher_authorization(self, payload, headers):
        return self._request("POST", "/teacher-authorizations", payload, headers)

    def list_teacher_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/teacher-authorizations", headers=headers, params=params
        )

    def get_teacher_authorization(self, authorization_id, headers):
        return self._request(
            "GET",
            f"/teacher-authorizations/{authorization_id}",
            headers=headers,
        )

    def complete_training(self, authorization_id, headers):
        return self._request(
            "POST",
            f"/teacher-authorizations/{authorization_id}/complete-training",
            headers=headers,
        )

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student_statement(self, student_id, headers):
        return self._request(
            "GET", f"/students/{student_id}/statement", headers=headers
        )

    # --- FeeReductionApplication ---
    def create_fee_reduction_application(self, payload, headers):
        return self._request(
            "POST", "/fee-reduction-applications", payload, headers
        )

    def list_fee_reduction_applications(self, headers, params=None):
        return self._request(
            "GET", "/fee-reduction-applications", headers=headers, params=params
        )

    def get_fee_reduction_application(self, application_id, headers):
        return self._request(
            "GET",
            f"/fee-reduction-applications/{application_id}",
            headers=headers,
        )

    def approve_fee_reduction_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/fee-reduction-applications/{application_id}/approve",
            headers=headers,
        )

    def deny_fee_reduction_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/fee-reduction-applications/{application_id}/deny",
            headers=headers,
        )

    def resubmit_fee_reduction_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/fee-reduction-applications/{application_id}/resubmit",
            headers=headers,
        )

    # --- ExamRegistration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers
        )

    def cancel_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/cancel", headers=headers
        )

    def post_to_transcript(self, registration_id, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/post-to-transcript",
            headers=headers,
        )

    # --- ExamOrder ---
    def create_exam_order(self, payload, headers):
        return self._request("POST", "/exam-orders", payload, headers)

    def list_exam_orders(self, headers, params=None):
        return self._request("GET", "/exam-orders", headers=headers, params=params)

    def get_exam_order(self, order_id, headers):
        return self._request("GET", f"/exam-orders/{order_id}", headers=headers)

    def patch_exam_order(self, order_id, payload, headers):
        return self._request(
            "PATCH", f"/exam-orders/{order_id}", payload, headers
        )

    def submit_exam_order(self, order_id, headers):
        return self._request(
            "POST", f"/exam-orders/{order_id}/submit", headers=headers
        )

    def lock_exam_order(self, order_id, headers):
        return self._request(
            "POST", f"/exam-orders/{order_id}/lock", headers=headers
        )

    def reconcile_exam_order(self, order_id, headers):
        return self._request(
            "POST", f"/exam-orders/{order_id}/reconcile", headers=headers
        )

    # --- ExamSession ---
    def create_exam_session(self, payload, headers):
        return self._request("POST", "/exam-sessions", payload, headers)

    def list_exam_sessions(self, headers, params=None):
        return self._request("GET", "/exam-sessions", headers=headers, params=params)

    def get_exam_session(self, session_id, headers):
        return self._request(
            "GET", f"/exam-sessions/{session_id}", headers=headers
        )

    def administer_exam_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/administer", payload, headers
        )

    def cancel_exam_session(self, session_id, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/cancel", headers=headers
        )

    # --- ProctorAssignment ---
    def create_proctor_assignment(self, payload, headers):
        return self._request("POST", "/proctor-assignments", payload, headers)

    def list_proctor_assignments(self, headers, params=None):
        return self._request(
            "GET", "/proctor-assignments", headers=headers, params=params
        )

    def get_proctor_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/proctor-assignments/{assignment_id}", headers=headers
        )

    def release_proctor_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/proctor-assignments/{assignment_id}/release", headers=headers
        )

    # --- IrregularityReport ---
    def create_irregularity_report(self, payload, headers):
        return self._request("POST", "/irregularity-reports", payload, headers)

    def list_irregularity_reports(self, headers, params=None):
        return self._request(
            "GET", "/irregularity-reports", headers=headers, params=params
        )

    def get_irregularity_report(self, report_id, headers):
        return self._request(
            "GET", f"/irregularity-reports/{report_id}", headers=headers
        )

    def resolve_irregularity_report(self, report_id, headers):
        return self._request(
            "POST", f"/irregularity-reports/{report_id}/resolve", headers=headers
        )

    def cancel_scores_irregularity_report(self, report_id, headers):
        return self._request(
            "POST",
            f"/irregularity-reports/{report_id}/cancel-scores",
            headers=headers,
        )


api_client = ApiClient()
