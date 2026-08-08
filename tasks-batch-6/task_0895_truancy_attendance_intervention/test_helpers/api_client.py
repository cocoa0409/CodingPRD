"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- School ---
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def list_school_students(self, school_id, headers, params=None):
        return self._request("GET", f"/schools/{school_id}/students", headers=headers, params=params)

    def list_school_staff(self, school_id, headers, params=None):
        return self._request("GET", f"/schools/{school_id}/staff", headers=headers, params=params)

    def get_school_report(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}/report", headers=headers)

    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def change_enrollment(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/enrollment", payload, headers)

    def create_attendance_record(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/attendance-records", payload, headers)

    def list_attendance_records(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/attendance-records", headers=headers, params=params)

    def reclassify_attendance_record(self, student_id, record_id, payload, headers):
        return self._request(
            "POST",
            f"/students/{student_id}/attendance-records/{record_id}/reclassify",
            payload,
            headers,
        )

    # --- TruancyCase ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assign", payload, headers)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/transition", payload, headers)

    # --- Conference ---
    def create_conference(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/conferences", payload, headers)

    def list_conferences(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/conferences", headers=headers, params=params)

    def transition_conference(self, case_id, conference_id, payload, headers):
        return self._request(
            "POST",
            f"/cases/{case_id}/conferences/{conference_id}/transition",
            payload,
            headers,
        )

    # --- AttendanceContract ---
    def create_contract(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/contracts", payload, headers)

    def list_contracts(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/contracts", headers=headers, params=params)

    def update_goal_progress(self, case_id, contract_id, goal_id, payload, headers):
        return self._request(
            "POST",
            f"/cases/{case_id}/contracts/{contract_id}/goals/{goal_id}/progress",
            payload,
            headers,
        )

    def transition_contract(self, case_id, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/cases/{case_id}/contracts/{contract_id}/transition",
            payload,
            headers,
        )

    # --- ServiceReferral ---
    def create_service_referral(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/service-referrals", payload, headers)

    def list_service_referrals(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/service-referrals", headers=headers, params=params)

    def transition_service_referral(self, case_id, referral_id, payload, headers):
        return self._request(
            "POST",
            f"/cases/{case_id}/service-referrals/{referral_id}/transition",
            payload,
            headers,
        )

    # --- CourtCitation ---
    def create_court_citation(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/court-citations", payload, headers)

    def list_court_citations(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/court-citations", headers=headers, params=params)

    def transition_court_citation(self, case_id, citation_id, payload, headers):
        return self._request(
            "POST",
            f"/cases/{case_id}/court-citations/{citation_id}/transition",
            payload,
            headers,
        )

    # --- ComplianceCheck ---
    def create_compliance_check(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/compliance-checks", payload, headers)

    def list_compliance_checks(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/compliance-checks", headers=headers, params=params)


api_client = ApiClient()
