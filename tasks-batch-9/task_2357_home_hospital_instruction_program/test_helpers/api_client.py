"""API client: one method per endpoint defined in the PRD (§4).

Every endpoint is mounted under the `/hhi` prefix with the sole exception of
the logical clock control capability (PRD §2.4).
"""

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/hhi"


class ApiClient(GenericApiClient):
    """Home and Hospital Instruction API client."""

    # ------------------------------------------------------------------
    # Logical service clock (PRD §2.4) — NOT under the /hhi prefix
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------

    def create_student(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/students/{student_id}", headers=headers
        )

    def list_students(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/students", headers=headers, params=params
        )

    def set_student_enrollment(self, student_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/students/{student_id}/enrollment", payload, headers
        )

    # ------------------------------------------------------------------
    # Teachers
    # ------------------------------------------------------------------

    def create_teacher(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/teachers", payload, headers)

    def get_teacher(self, teacher_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/teachers/{teacher_id}", headers=headers
        )

    def list_teachers(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/teachers", headers=headers, params=params
        )

    def update_teacher_clearance(self, teacher_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/teachers/{teacher_id}/clearance", payload, headers
        )

    # ------------------------------------------------------------------
    # Entitlement rules
    # ------------------------------------------------------------------

    def create_entitlement_rule(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/entitlement-rules", payload, headers
        )

    def get_entitlement_rule(self, rule_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/entitlement-rules/{rule_id}", headers=headers
        )

    def list_entitlement_rules(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/entitlement-rules", headers=headers, params=params
        )

    def retire_entitlement_rule(self, rule_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/entitlement-rules/{rule_id}/retire",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Homebound cases
    # ------------------------------------------------------------------

    def create_case(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{API_PREFIX}/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/cases", headers=headers, params=params
        )

    def activate_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/activate", payload, headers
        )

    def deny_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/deny", payload, headers
        )

    def close_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/close", payload, headers
        )

    def report_case_funding(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/funding/report", payload, headers
        )

    def reconcile_case_funding(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/funding/reconcile", payload, headers
        )

    def get_funding_summary(self, case_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/cases/{case_id}/funding-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Physician certifications
    # ------------------------------------------------------------------

    def create_certification(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/certifications/{certification_id}", headers=headers
        )

    def list_certifications(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/certifications", headers=headers, params=params
        )

    def review_certification(self, certification_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/certifications/{certification_id}/review",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Teacher assignments
    # ------------------------------------------------------------------

    def create_assignment(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/assignments/{assignment_id}", headers=headers
        )

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/assignments", headers=headers, params=params
        )

    def accept_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/assignments/{assignment_id}/accept", payload, headers
        )

    def decline_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/assignments/{assignment_id}/decline",
            payload,
            headers,
        )

    def release_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/assignments/{assignment_id}/release",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Home visit safety reviews
    # ------------------------------------------------------------------

    def create_safety_review(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/safety-reviews", payload, headers)

    def get_safety_review(self, review_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/safety-reviews/{review_id}", headers=headers
        )

    def list_safety_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/safety-reviews", headers=headers, params=params
        )

    def finalize_safety_review(self, review_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/safety-reviews/{review_id}/finalize",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Instruction sessions
    # ------------------------------------------------------------------

    def create_session(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/sessions/{session_id}", headers=headers
        )

    def list_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/sessions", headers=headers, params=params
        )

    def log_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sessions/{session_id}/log", payload, headers
        )

    def verify_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/sessions/{session_id}/verify", payload, headers
        )

    def void_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sessions/{session_id}/void", payload, headers
        )

    def cancel_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/sessions/{session_id}/cancel", payload, headers
        )

    def create_makeup_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sessions/{session_id}/makeup", payload, headers
        )

    # ------------------------------------------------------------------
    # Attendance ledger (append-only)
    # ------------------------------------------------------------------

    def get_attendance_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/attendance-entries/{entry_id}", headers=headers
        )

    def list_attendance_entries(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/attendance-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Extension requests
    # ------------------------------------------------------------------

    def create_extension_request(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/extension-requests", payload, headers
        )

    def get_extension_request(self, request_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/extension-requests/{request_id}", headers=headers
        )

    def list_extension_requests(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/extension-requests", headers=headers, params=params
        )

    def start_extension_review(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/extension-requests/{request_id}/start-review",
            payload,
            headers,
        )

    def request_extension_info(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/extension-requests/{request_id}/request-info",
            payload,
            headers,
        )

    def resubmit_extension_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/extension-requests/{request_id}/resubmit",
            payload,
            headers,
        )

    def decide_extension_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/extension-requests/{request_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Transition plans
    # ------------------------------------------------------------------

    def create_transition_plan(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/transition-plans", payload, headers)

    def get_transition_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/transition-plans/{plan_id}", headers=headers
        )

    def list_transition_plans(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/transition-plans", headers=headers, params=params
        )

    def coordinate_transition_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/transition-plans/{plan_id}/coordinate",
            payload,
            headers,
        )

    def complete_transition_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/transition-plans/{plan_id}/complete",
            payload,
            headers,
        )

    def abort_transition_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/transition-plans/{plan_id}/abort", payload, headers
        )

    # ------------------------------------------------------------------
    # Curriculum pacing coordination
    # ------------------------------------------------------------------

    def create_pacing_sync(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/pacing-syncs", payload, headers)

    def get_pacing_sync(self, sync_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/pacing-syncs/{sync_id}", headers=headers
        )

    def list_pacing_syncs(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/pacing-syncs", headers=headers, params=params
        )

    def acknowledge_pacing_sync(self, sync_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/pacing-syncs/{sync_id}/acknowledge", payload, headers
        )

    def dispute_pacing_sync(self, sync_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/pacing-syncs/{sync_id}/dispute", payload, headers
        )

    # ------------------------------------------------------------------
    # Special-education service continuation logs
    # ------------------------------------------------------------------

    def create_sped_service_log(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sped-service-logs", payload, headers
        )

    def get_sped_service_log(self, log_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/sped-service-logs/{log_id}", headers=headers
        )

    def list_sped_service_logs(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/sped-service-logs", headers=headers, params=params
        )

    def record_sped_delivery(self, log_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sped-service-logs/{log_id}/record-delivery",
            payload,
            headers,
        )

    def change_sped_continuation(self, log_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sped-service-logs/{log_id}/continuation",
            payload,
            headers,
        )


api_client = ApiClient()
