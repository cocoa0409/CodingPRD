"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    # ---- AgeCohort ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", headers=headers, params=params)

    def run_selection(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/run-selection", {}, headers)

    # ---- Family ----
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def verify_eligibility(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/verify-eligibility", payload, headers)

    def waitlist_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/waitlist", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    # ---- Offer ----
    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", {}, headers)

    def expire_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/expire", {}, headers)

    # ---- Enrollment ----
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    def disenroll(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/disenroll", payload, headers)

    # ---- AttendanceRecord ----
    def create_attendance_record(self, payload, headers):
        return self._request("POST", "/attendance-records", payload, headers)

    def list_attendance_records(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/attendance-records", headers=headers, params=params)

    # ---- HealthScreening ----
    def create_health_screening(self, payload, headers):
        return self._request("POST", "/health-screenings", payload, headers)

    def update_health_screening(self, screening_id, payload, headers):
        return self._request("PATCH", f"/health-screenings/{screening_id}", payload, headers)

    def list_health_screenings(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/health-screenings", headers=headers, params=params)

    # ---- HomeVisit ----
    def create_home_visit(self, payload, headers):
        return self._request("POST", "/home-visits", payload, headers)

    def complete_home_visit(self, home_visit_id, headers):
        return self._request("POST", f"/home-visits/{home_visit_id}/complete", {}, headers)

    def list_home_visits(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/home-visits", headers=headers, params=params)

    # ---- TransitionPlan ----
    def create_transition_plan(self, payload, headers):
        return self._request("POST", "/transition-plans", payload, headers)

    def complete_transition_plan(self, plan_id, headers):
        return self._request("POST", f"/transition-plans/{plan_id}/complete", {}, headers)

    def list_transition_plans(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/transition-plans", headers=headers, params=params)

    # ---- PIRReport ----
    def create_pir_report(self, payload, headers):
        return self._request("POST", "/pir-reports", payload, headers)

    def get_pir_report(self, report_id, headers):
        return self._request("GET", f"/pir-reports/{report_id}", headers=headers)

    def list_pir_reports(self, headers, params=None):
        return self._request("GET", "/pir-reports", headers=headers, params=params)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
