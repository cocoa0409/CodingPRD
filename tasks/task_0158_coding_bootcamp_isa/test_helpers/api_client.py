"""API client: one method per endpoint defined in the PRD (Coding Bootcamp ISA)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Test-driving clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------- Cohort ----------
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", headers=headers, params=params)

    def open_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/open", {}, headers)

    def start_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/start", {}, headers)

    def graduate_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/graduate", {}, headers)

    def archive_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/archive", {}, headers)

    def list_cohort_enrollments(self, cohort_id, headers, params=None):
        return self._request(
            "GET", f"/cohorts/{cohort_id}/enrollments", headers=headers, params=params
        )

    def list_cohort_cirr_reports(self, cohort_id, headers, params=None):
        return self._request(
            "GET", f"/cohorts/{cohort_id}/cirr-reports", headers=headers, params=params
        )

    # ---------- Applicant ----------
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    def admit_applicant(self, applicant_id, headers):
        return self._request("POST", f"/applicants/{applicant_id}/admit", {}, headers)

    def reject_applicant(self, applicant_id, headers):
        return self._request("POST", f"/applicants/{applicant_id}/reject", {}, headers)

    def withdraw_applicant(self, applicant_id, headers):
        return self._request("POST", f"/applicants/{applicant_id}/withdraw", {}, headers)

    # ---------- Enrollment ----------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def graduate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/graduate", {}, headers)

    def dismiss_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/dismiss", {}, headers)

    def withdraw_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", payload or {}, headers
        )

    def list_enrollment_attendance(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/attendance", headers=headers, params=params
        )

    # ---------- AttendanceRecord ----------
    def create_attendance_record(self, payload, headers):
        return self._request("POST", "/attendance-records", payload, headers)

    # ---------- Scholarship ----------
    def create_scholarship(self, payload, headers):
        return self._request("POST", "/scholarships", payload, headers)

    def get_scholarship(self, scholarship_id, headers):
        return self._request("GET", f"/scholarships/{scholarship_id}", headers=headers)

    def list_scholarships(self, headers, params=None):
        return self._request("GET", "/scholarships", headers=headers, params=params)

    # ---------- Deposit ----------
    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    # ---------- ISAContract ----------
    def get_isa_contract(self, contract_id, headers):
        return self._request("GET", f"/isa-contracts/{contract_id}", headers=headers)

    def list_isa_contracts(self, headers, params=None):
        return self._request("GET", "/isa-contracts", headers=headers, params=params)

    def get_isa_projection(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/isa-contracts/{contract_id}/projection", headers=headers, params=params
        )

    def list_isa_payments(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/isa-contracts/{contract_id}/payments", headers=headers, params=params
        )

    def list_isa_income_reports(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/isa-contracts/{contract_id}/income-reports", headers=headers, params=params
        )

    def list_isa_deferment_requests(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/isa-contracts/{contract_id}/deferment-requests", headers=headers, params=params
        )

    # ---------- IncomeReport ----------
    def create_income_report(self, payload, headers):
        return self._request("POST", "/income-reports", payload, headers)

    def get_income_report(self, report_id, headers):
        return self._request("GET", f"/income-reports/{report_id}", headers=headers)

    # ---------- Payment ----------
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def settle_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/settle", {}, headers)

    def fail_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/fail", {}, headers)

    def retry_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/retry", {}, headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", {}, headers)

    # ---------- DefermentRequest ----------
    def create_deferment_request(self, payload, headers):
        return self._request("POST", "/deferment-requests", payload, headers)

    def get_deferment_request(self, request_id, headers):
        return self._request("GET", f"/deferment-requests/{request_id}", headers=headers)

    def approve_deferment_request(self, request_id, headers):
        return self._request("POST", f"/deferment-requests/{request_id}/approve", {}, headers)

    def deny_deferment_request(self, request_id, headers):
        return self._request("POST", f"/deferment-requests/{request_id}/deny", {}, headers)

    def end_deferment_request(self, request_id, headers):
        return self._request("POST", f"/deferment-requests/{request_id}/end", {}, headers)

    # ---------- RefundRequest ----------
    def get_refund_request(self, request_id, headers):
        return self._request("GET", f"/refund-requests/{request_id}", headers=headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    def approve_refund_request(self, request_id, headers):
        return self._request("POST", f"/refund-requests/{request_id}/approve", {}, headers)

    def reject_refund_request(self, request_id, headers):
        return self._request("POST", f"/refund-requests/{request_id}/reject", {}, headers)

    # ---------- PlacementOutcome ----------
    def create_placement_outcome(self, payload, headers):
        return self._request("POST", "/placement-outcomes", payload, headers)

    def get_placement_outcome(self, outcome_id, headers):
        return self._request("GET", f"/placement-outcomes/{outcome_id}", headers=headers)

    def list_placement_outcomes(self, headers, params=None):
        return self._request("GET", "/placement-outcomes", headers=headers, params=params)

    # ---------- CIRRReport ----------
    def create_cirr_report(self, payload, headers):
        return self._request("POST", "/cirr-reports", payload, headers)

    def get_cirr_report(self, report_id, headers):
        return self._request("GET", f"/cirr-reports/{report_id}", headers=headers)

    def publish_cirr_report(self, report_id, headers):
        return self._request("POST", f"/cirr-reports/{report_id}/publish", {}, headers)


api_client = ApiClient()
