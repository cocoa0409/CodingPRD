"""API client: one method per endpoint defined in the PRD.

All endpoints are rooted at the API host with no version or collection prefix;
every collection sits at the top level of the URL space (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- students
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def update_student_measures(self, student_id, payload, headers):
        return self._request(
            "POST", f"/students/{student_id}/measures", payload, headers
        )

    def list_student_determinations(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/students/{student_id}/determinations",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------------- courses
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def retire_course(self, course_id, headers, payload=None):
        return self._request("POST", f"/courses/{course_id}/retire", payload, headers)

    def get_course_equity_summary(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/courses/{course_id}/equity-summary", headers=headers, params=params
        )

    def list_course_requisites_of_course(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/courses/{course_id}/requisites", headers=headers, params=params
        )

    # ------------------------------------------------------ course requisites
    def create_course_requisite(self, payload, headers):
        return self._request("POST", "/course-requisites", payload, headers)

    def get_course_requisite(self, requisite_id, headers):
        return self._request(
            "GET", f"/course-requisites/{requisite_id}", headers=headers
        )

    def list_course_requisites(self, headers, params=None):
        return self._request(
            "GET", "/course-requisites", headers=headers, params=params
        )

    def retire_course_requisite(self, requisite_id, headers, payload=None):
        return self._request(
            "POST", f"/course-requisites/{requisite_id}/retire", payload, headers
        )

    # -------------------------------------------------------- placement rules
    def create_placement_rule(self, payload, headers):
        return self._request("POST", "/placement-rules", payload, headers)

    def get_placement_rule(self, rule_id, headers):
        return self._request("GET", f"/placement-rules/{rule_id}", headers=headers)

    def list_placement_rules(self, headers, params=None):
        return self._request("GET", "/placement-rules", headers=headers, params=params)

    def activate_placement_rule(self, rule_id, headers, payload=None):
        return self._request(
            "POST", f"/placement-rules/{rule_id}/activate", payload, headers
        )

    def retire_placement_rule(self, rule_id, headers, payload=None):
        return self._request(
            "POST", f"/placement-rules/{rule_id}/retire", payload, headers
        )

    # --------------------------------------------------- test administrations
    def create_test_administration(self, payload, headers):
        return self._request("POST", "/test-administrations", payload, headers)

    def get_test_administration(self, administration_id, headers):
        return self._request(
            "GET", f"/test-administrations/{administration_id}", headers=headers
        )

    def list_test_administrations(self, headers, params=None):
        return self._request(
            "GET", "/test-administrations", headers=headers, params=params
        )

    def set_test_administration_status(self, administration_id, payload, headers):
        return self._request(
            "POST",
            f"/test-administrations/{administration_id}/status",
            payload,
            headers,
        )

    def list_administration_attempts(self, administration_id, headers, params=None):
        return self._request(
            "GET",
            f"/test-administrations/{administration_id}/attempts",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- test attempts
    def create_test_attempt(self, payload, headers):
        return self._request("POST", "/test-attempts", payload, headers)

    def get_test_attempt(self, attempt_id, headers):
        return self._request("GET", f"/test-attempts/{attempt_id}", headers=headers)

    def list_test_attempts(self, headers, params=None):
        return self._request("GET", "/test-attempts", headers=headers, params=params)

    def check_in_test_attempt(self, attempt_id, headers, payload=None):
        return self._request(
            "POST", f"/test-attempts/{attempt_id}/check-in", payload, headers
        )

    def score_test_attempt(self, attempt_id, payload, headers):
        return self._request(
            "POST", f"/test-attempts/{attempt_id}/score", payload, headers
        )

    def void_test_attempt(self, attempt_id, payload, headers):
        return self._request(
            "POST", f"/test-attempts/{attempt_id}/void", payload, headers
        )

    def no_show_test_attempt(self, attempt_id, headers, payload=None):
        return self._request(
            "POST", f"/test-attempts/{attempt_id}/no-show", payload, headers
        )

    # ----------------------------------------------- placement determinations
    def create_placement_determination(self, payload, headers):
        return self._request("POST", "/placement-determinations", payload, headers)

    def get_placement_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/placement-determinations/{determination_id}", headers=headers
        )

    def list_placement_determinations(self, headers, params=None):
        return self._request(
            "GET", "/placement-determinations", headers=headers, params=params
        )

    def finalize_placement_determination(self, determination_id, headers, payload=None):
        return self._request(
            "POST",
            f"/placement-determinations/{determination_id}/finalize",
            payload,
            headers,
        )

    def set_determination_evidence(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"/placement-determinations/{determination_id}/evidence",
            payload,
            headers,
        )

    # ------------------------------------------------------ placement appeals
    def create_placement_appeal(self, payload, headers):
        return self._request("POST", "/placement-appeals", payload, headers)

    def get_placement_appeal(self, appeal_id, headers):
        return self._request("GET", f"/placement-appeals/{appeal_id}", headers=headers)

    def list_placement_appeals(self, headers, params=None):
        return self._request(
            "GET", "/placement-appeals", headers=headers, params=params
        )

    def start_appeal_review(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/placement-appeals/{appeal_id}/start-review", payload, headers
        )

    def request_appeal_info(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/placement-appeals/{appeal_id}/request-info", payload, headers
        )

    def resubmit_placement_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/placement-appeals/{appeal_id}/resubmit", payload, headers
        )

    def endorse_placement_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/placement-appeals/{appeal_id}/endorse", payload, headers
        )

    def decide_placement_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/placement-appeals/{appeal_id}/decide", payload, headers
        )

    def withdraw_placement_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/placement-appeals/{appeal_id}/withdraw", payload, headers
        )

    # --------------------------------------------------------------- sections
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    def pair_section(self, section_id, payload, headers):
        return self._request("POST", f"/sections/{section_id}/pair", payload, headers)

    def unpair_section(self, section_id, headers, payload=None):
        return self._request("POST", f"/sections/{section_id}/unpair", payload, headers)

    def set_section_status(self, section_id, payload, headers):
        return self._request("POST", f"/sections/{section_id}/status", payload, headers)

    def list_section_registrations(self, section_id, headers, params=None):
        return self._request(
            "GET", f"/sections/{section_id}/registrations", headers=headers, params=params
        )

    # ---------------------------------------------------------- registrations
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def confirm_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST", f"/registrations/{registration_id}/confirm", payload, headers
        )

    def drop_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST", f"/registrations/{registration_id}/drop", payload, headers
        )

    def grade_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/grade", payload, headers
        )

    # -------------------------------------------------- prerequisite overrides
    def create_prerequisite_override(self, payload, headers):
        return self._request("POST", "/prerequisite-overrides", payload, headers)

    def get_prerequisite_override(self, override_id, headers):
        return self._request(
            "GET", f"/prerequisite-overrides/{override_id}", headers=headers
        )

    def list_prerequisite_overrides(self, headers, params=None):
        return self._request(
            "GET", "/prerequisite-overrides", headers=headers, params=params
        )

    def revoke_prerequisite_override(self, override_id, headers, payload=None):
        return self._request(
            "POST", f"/prerequisite-overrides/{override_id}/revoke", payload, headers
        )

    # ------------------------------------------------------ validation studies
    def create_validation_study(self, payload, headers):
        return self._request("POST", "/validation-studies", payload, headers)

    def get_validation_study(self, study_id, headers):
        return self._request("GET", f"/validation-studies/{study_id}", headers=headers)

    def list_validation_studies(self, headers, params=None):
        return self._request(
            "GET", "/validation-studies", headers=headers, params=params
        )

    def run_validation_study(self, study_id, headers, payload=None):
        return self._request(
            "POST", f"/validation-studies/{study_id}/run", payload, headers
        )

    def decide_validation_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/validation-studies/{study_id}/decide", payload, headers
        )


api_client = ApiClient()
