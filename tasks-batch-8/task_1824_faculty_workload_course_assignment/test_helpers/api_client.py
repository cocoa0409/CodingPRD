"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- WorkloadTerm ---
    def create_term(self, payload, headers):
        return self._request("POST", "/workload-terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/workload-terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/workload-terms/{term_id}", headers=headers)

    def patch_term(self, term_id, payload, headers):
        return self._request("PATCH", f"/workload-terms/{term_id}", payload, headers)

    def transition_term(self, term_id, payload, headers):
        return self._request("POST", f"/workload-terms/{term_id}/transition", payload, headers)

    def close_census(self, term_id, payload, headers):
        return self._request("POST", f"/workload-terms/{term_id}/close-census", payload, headers)

    def get_load_summary(self, term_id, headers):
        return self._request("GET", f"/workload-terms/{term_id}/load-summary", headers=headers)

    # --- FacultyMember ---
    def create_faculty(self, payload, headers):
        return self._request("POST", "/faculty-members", payload, headers)

    def list_faculty(self, headers, params=None):
        return self._request("GET", "/faculty-members", headers=headers, params=params)

    def get_faculty(self, faculty_id, headers):
        return self._request("GET", f"/faculty-members/{faculty_id}", headers=headers)

    def patch_faculty(self, faculty_id, payload, headers):
        return self._request("PATCH", f"/faculty-members/{faculty_id}", payload, headers)

    # --- Course ---
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    # --- Qualification ---
    def create_qualification(self, payload, headers):
        return self._request("POST", "/qualifications", payload, headers)

    def list_qualifications(self, headers, params=None):
        return self._request("GET", "/qualifications", headers=headers, params=params)

    def get_qualification(self, qualification_id, headers):
        return self._request("GET", f"/qualifications/{qualification_id}", headers=headers)

    def patch_qualification(self, qualification_id, payload, headers):
        return self._request("PATCH", f"/qualifications/{qualification_id}", payload, headers)

    # --- CourseSection ---
    def create_section(self, payload, headers):
        return self._request("POST", "/course-sections", payload, headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/course-sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/course-sections/{section_id}", headers=headers)

    def transition_section(self, section_id, payload, headers):
        return self._request("POST", f"/course-sections/{section_id}/transition", payload, headers)

    def enrollment_sync(self, section_id, payload, headers):
        return self._request("POST", f"/course-sections/{section_id}/enrollment-sync", payload, headers)

    # --- Assignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def transition_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/transition", payload, headers)

    # --- ReleaseTimeGrant ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/release-time-grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/release-time-grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/release-time-grants/{grant_id}", headers=headers)

    def transition_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/release-time-grants/{grant_id}/transition", payload, headers)

    # --- OverloadRequest ---
    def create_overload_request(self, payload, headers):
        return self._request("POST", "/overload-requests", payload, headers)

    def list_overload_requests(self, headers, params=None):
        return self._request("GET", "/overload-requests", headers=headers, params=params)

    def get_overload_request(self, request_id, headers):
        return self._request("GET", f"/overload-requests/{request_id}", headers=headers)

    def transition_overload_request(self, request_id, payload, headers):
        return self._request("POST", f"/overload-requests/{request_id}/transition", payload, headers)

    # --- LoadSheet (read-only) ---
    def list_load_sheets(self, headers, params=None):
        return self._request("GET", "/load-sheets", headers=headers, params=params)

    def get_load_sheet(self, load_sheet_id, headers):
        return self._request("GET", f"/load-sheets/{load_sheet_id}", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
