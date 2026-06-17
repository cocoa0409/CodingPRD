"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /v1 prefix (PRD §2, §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- SystemClock ----
    def get_clock(self, headers):
        return self._request("GET", "/v1/clock", headers=headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/v1/clock/advance", payload, headers)

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/v1/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/v1/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}", headers=headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/open", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/close", {}, headers)

    def get_placement_report(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}/placement-report", headers=headers)

    # ---- Cohort ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/v1/cohorts", payload, headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/v1/cohorts", headers=headers, params=params)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/v1/cohorts/{cohort_id}", headers=headers)

    def start_cohort(self, cohort_id, headers):
        return self._request("POST", f"/v1/cohorts/{cohort_id}/start", {}, headers)

    def complete_cohort(self, cohort_id, headers):
        return self._request("POST", f"/v1/cohorts/{cohort_id}/complete", {}, headers)

    # ---- Student ----
    def create_student(self, payload, headers):
        return self._request("POST", "/v1/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/v1/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/v1/students/{student_id}", headers=headers)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/v1/students/{student_id}", payload, headers)

    # ---- ExternshipSite ----
    def create_externship_site(self, payload, headers):
        return self._request("POST", "/v1/externship-sites", payload, headers)

    def list_externship_sites(self, headers, params=None):
        return self._request("GET", "/v1/externship-sites", headers=headers, params=params)

    def get_externship_site(self, site_id, headers):
        return self._request("GET", f"/v1/externship-sites/{site_id}", headers=headers)

    def suspend_externship_site(self, site_id, headers):
        return self._request("POST", f"/v1/externship-sites/{site_id}/suspend", {}, headers)

    # ---- EnrollmentAgreement ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/v1/enrollment-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/v1/enrollment-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/v1/enrollment-agreements/{agreement_id}", headers=headers)

    def enroll_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/enrollment-agreements/{agreement_id}/enroll", {}, headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/enrollment-agreements/{agreement_id}/cancel", {}, headers)

    def start_loa(self, agreement_id, headers):
        return self._request("POST", f"/v1/enrollment-agreements/{agreement_id}/start-loa", {}, headers)

    def return_from_loa(self, agreement_id, headers):
        return self._request("POST", f"/v1/enrollment-agreements/{agreement_id}/return-from-loa", {}, headers)

    def graduate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/enrollment-agreements/{agreement_id}/graduate", {}, headers)

    def withdraw_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/enrollment-agreements/{agreement_id}/withdraw", {}, headers)

    # ---- AttendanceEntry ----
    def create_attendance_entry(self, payload, headers):
        return self._request("POST", "/v1/attendance-entries", payload, headers)

    def list_attendance_entries(self, headers, params=None):
        return self._request("GET", "/v1/attendance-entries", headers=headers, params=params)

    def get_attendance_entry(self, entry_id, headers):
        return self._request("GET", f"/v1/attendance-entries/{entry_id}", headers=headers)

    def excuse_attendance_entry(self, entry_id, headers):
        return self._request("POST", f"/v1/attendance-entries/{entry_id}/excuse", {}, headers)

    def void_attendance_entry(self, entry_id, headers):
        return self._request("POST", f"/v1/attendance-entries/{entry_id}/void", {}, headers)

    # ---- SapStanding ----
    def create_sap_standing(self, payload, headers):
        return self._request("POST", "/v1/sap-standings", payload, headers)

    def list_sap_standings(self, headers, params=None):
        return self._request("GET", "/v1/sap-standings", headers=headers, params=params)

    def get_sap_standing(self, sap_id, headers):
        return self._request("GET", f"/v1/sap-standings/{sap_id}", headers=headers)

    def appeal_sap_standing(self, sap_id, headers):
        return self._request("POST", f"/v1/sap-standings/{sap_id}/appeal", {}, headers)

    def resolve_appeal(self, sap_id, payload, headers):
        return self._request("POST", f"/v1/sap-standings/{sap_id}/resolve-appeal", payload, headers)

    # ---- AidDisbursement ----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/v1/aid-disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/v1/aid-disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/v1/aid-disbursements/{disbursement_id}", headers=headers)

    def release_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/v1/aid-disbursements/{disbursement_id}/release", {}, headers)

    def cancel_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/v1/aid-disbursements/{disbursement_id}/cancel", {}, headers)

    # ---- RefundCase ----
    def create_refund_case(self, payload, headers):
        return self._request("POST", "/v1/refund-cases", payload, headers)

    def list_refund_cases(self, headers, params=None):
        return self._request("GET", "/v1/refund-cases", headers=headers, params=params)

    def get_refund_case(self, refund_id, headers):
        return self._request("GET", f"/v1/refund-cases/{refund_id}", headers=headers)

    def settle_refund_case(self, refund_id, payload, headers):
        return self._request("POST", f"/v1/refund-cases/{refund_id}/settle", payload, headers)

    def reverse_refund_case(self, refund_id, headers):
        return self._request("POST", f"/v1/refund-cases/{refund_id}/reverse", {}, headers)

    # ---- ExternshipAssignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/v1/externship-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/v1/externship-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/v1/externship-assignments/{assignment_id}", headers=headers)

    def begin_assignment(self, assignment_id, headers):
        return self._request("POST", f"/v1/externship-assignments/{assignment_id}/begin", {}, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/v1/externship-assignments/{assignment_id}/complete", payload, headers)

    def terminate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/v1/externship-assignments/{assignment_id}/terminate", {}, headers)

    # ---- LicensureExamAttempt ----
    def create_exam_attempt(self, payload, headers):
        return self._request("POST", "/v1/licensure-exam-attempts", payload, headers)

    def list_exam_attempts(self, headers, params=None):
        return self._request("GET", "/v1/licensure-exam-attempts", headers=headers, params=params)

    def get_exam_attempt(self, attempt_id, headers):
        return self._request("GET", f"/v1/licensure-exam-attempts/{attempt_id}", headers=headers)

    # ---- PlacementOutcome ----
    def create_placement_outcome(self, payload, headers):
        return self._request("POST", "/v1/placement-outcomes", payload, headers)

    def list_placement_outcomes(self, headers, params=None):
        return self._request("GET", "/v1/placement-outcomes", headers=headers, params=params)

    def get_placement_outcome(self, outcome_id, headers):
        return self._request("GET", f"/v1/placement-outcomes/{outcome_id}", headers=headers)


api_client = ApiClient()
