"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Students ----
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def list_student_enrollments(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/enrollments", headers=headers, params=params)

    def list_student_compliance_events(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/compliance-events", headers=headers, params=params)

    def list_student_add_ons(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/add-ons", headers=headers, params=params)

    def list_student_placement_tests(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/placement-tests", headers=headers, params=params)

    def issue_i20(self, student_id, headers, payload=None):
        return self._request("POST", f"/students/{student_id}/issue-i20", payload or {}, headers)

    def activate_status(self, student_id, headers, payload=None):
        return self._request("POST", f"/students/{student_id}/activate-status", payload or {}, headers)

    def place_probation(self, student_id, headers, payload=None):
        return self._request("POST", f"/students/{student_id}/place-probation", payload or {}, headers)

    def clear_probation(self, student_id, headers, payload=None):
        return self._request("POST", f"/students/{student_id}/clear-probation", payload or {}, headers)

    def terminate_status(self, student_id, headers, payload=None):
        return self._request("POST", f"/students/{student_id}/terminate-status", payload or {}, headers)

    # ---- Placement Tests ----
    def create_placement_test(self, payload, headers):
        return self._request("POST", "/placement-tests", payload, headers)

    def get_placement_test(self, test_id, headers):
        return self._request("GET", f"/placement-tests/{test_id}", headers=headers)

    def score_placement_test(self, test_id, payload, headers):
        return self._request("POST", f"/placement-tests/{test_id}/score", payload, headers)

    def void_placement_test(self, test_id, headers, payload=None):
        return self._request("POST", f"/placement-tests/{test_id}/void", payload or {}, headers)

    # ---- Cohorts ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", headers=headers, params=params)

    def list_cohort_enrollments(self, cohort_id, headers, params=None):
        return self._request("GET", f"/cohorts/{cohort_id}/enrollments", headers=headers, params=params)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def confirm_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/confirm", payload, headers)

    def withdraw_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", payload or {}, headers)

    def terminate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/terminate", payload, headers)

    def complete_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/complete", payload or {}, headers)

    # ---- Attendance ----
    def create_attendance(self, payload, headers):
        return self._request("POST", "/attendance", payload, headers)

    def list_enrollment_attendance(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/attendance", headers=headers, params=params)

    # ---- Progress Reports ----
    def create_progress_report(self, payload, headers):
        return self._request("POST", "/progress-reports", payload, headers)

    def list_enrollment_progress_reports(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/progress-reports", headers=headers, params=params)

    # ---- Add-ons ----
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    def list_enrollment_add_ons(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/add-ons", headers=headers, params=params)

    def cancel_add_on(self, add_on_id, headers, payload=None):
        return self._request("POST", f"/add-ons/{add_on_id}/cancel", payload or {}, headers)

    # ---- Corporate Contracts ----
    def create_corporate_contract(self, payload, headers):
        return self._request("POST", "/corporate-contracts", payload, headers)

    def get_corporate_contract(self, contract_id, headers):
        return self._request("GET", f"/corporate-contracts/{contract_id}", headers=headers)

    def list_contract_students(self, contract_id, headers, params=None):
        return self._request("GET", f"/corporate-contracts/{contract_id}/students", headers=headers, params=params)

    def close_corporate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/corporate-contracts/{contract_id}/close", payload, headers)

    # ---- Test-driving / logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Raw helper (for no-auth-header tests) ----
    def raw_request(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
