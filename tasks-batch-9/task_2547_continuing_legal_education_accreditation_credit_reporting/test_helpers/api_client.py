"""API client: one method per endpoint the PRD declares."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every method returns the raw HTTP response so tests can assert status."""

    # --- Logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Providers -------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/cle/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/cle/providers/{provider_id}", headers=headers)

    def provider_accreditation_action(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/cle/providers/{provider_id}/accreditation-actions", payload, headers
        )

    # --- Courses ---------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/cle/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/cle/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/cle/courses", headers=headers, params=params)

    def list_course_credit_allocations(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/cle/courses/{course_id}/credit-allocations",
            headers=headers, params=params,
        )

    def list_course_attendance_reports(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/cle/courses/{course_id}/attendance-reports",
            headers=headers, params=params,
        )

    # --- Course applications --------------------------------------------
    def create_course_application(self, course_id, headers, payload=None):
        return self._request(
            "POST", f"/cle/courses/{course_id}/applications", payload or {}, headers
        )

    def list_course_applications(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/cle/courses/{course_id}/applications", headers=headers, params=params
        )

    def get_course_application(self, application_id, headers):
        return self._request(
            "GET", f"/cle/course-applications/{application_id}", headers=headers
        )

    def application_review_action(self, application_id, payload, headers):
        return self._request(
            "POST", f"/cle/course-applications/{application_id}/review-actions",
            payload, headers,
        )

    def application_appellant_action(self, application_id, payload, headers):
        return self._request(
            "POST", f"/cle/course-applications/{application_id}/appellant-actions",
            payload, headers,
        )

    def application_appeal_decision(self, application_id, payload, headers):
        return self._request(
            "POST", f"/cle/course-applications/{application_id}/appeal-decisions",
            payload, headers,
        )

    # --- Attorneys -------------------------------------------------------
    def create_attorney(self, payload, headers):
        return self._request("POST", "/cle/attorneys", payload, headers)

    def attorney_status_change(self, attorney_id, payload, headers):
        return self._request(
            "POST", f"/cle/attorneys/{attorney_id}/status-changes", payload, headers
        )

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/cle/attorneys/{attorney_id}", headers=headers)

    def create_compliance_cycle(self, attorney_id, payload, headers):
        return self._request(
            "POST", f"/cle/attorneys/{attorney_id}/compliance-cycles", payload, headers
        )

    def list_attorney_reciprocity_claims(self, attorney_id, headers, params=None):
        return self._request(
            "GET", f"/cle/attorneys/{attorney_id}/reciprocity-claims",
            headers=headers, params=params,
        )

    def attorney_reinstatement(self, attorney_id, payload, headers):
        return self._request(
            "POST", f"/cle/attorneys/{attorney_id}/reinstatement", payload, headers
        )

    # --- Compliance cycles ----------------------------------------------
    def get_compliance_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/cle/compliance-cycles/{cycle_id}", headers=headers
        )

    def list_compliance_cycles(self, headers, params=None):
        return self._request(
            "GET", "/cle/compliance-cycles", headers=headers, params=params
        )

    def get_cycle_summary(self, cycle_id, headers):
        return self._request(
            "GET", f"/cle/compliance-cycles/{cycle_id}/summary", headers=headers
        )

    def create_affirmation(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/cle/compliance-cycles/{cycle_id}/affirmations", payload, headers
        )

    def list_affirmations(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/cle/compliance-cycles/{cycle_id}/affirmations",
            headers=headers, params=params,
        )

    def certify_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/cle/compliance-cycles/{cycle_id}/certification", payload or {}, headers
        )

    # --- Credit records --------------------------------------------------
    def create_credit_record(self, payload, headers):
        return self._request("POST", "/cle/credit-records", payload, headers)

    def get_credit_record(self, record_id, headers):
        return self._request("GET", f"/cle/credit-records/{record_id}", headers=headers)

    def list_credit_records(self, headers, params=None):
        return self._request("GET", "/cle/credit-records", headers=headers, params=params)

    def credit_record_adjudication(self, record_id, payload, headers):
        return self._request(
            "POST", f"/cle/credit-records/{record_id}/adjudication", payload, headers
        )

    # --- Attendance reports ----------------------------------------------
    def create_attendance_report(self, payload, headers):
        return self._request("POST", "/cle/attendance-reports", payload, headers)

    # --- Reciprocity and comity ------------------------------------------
    def create_reciprocity_claim(self, payload, headers):
        return self._request("POST", "/cle/reciprocity-claims", payload, headers)

    def reciprocity_claim_determination(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/cle/reciprocity-claims/{claim_id}/determination", payload, headers
        )

    # --- Provider audits --------------------------------------------------
    def create_provider_audit(self, payload, headers):
        return self._request("POST", "/cle/provider-audits", payload, headers)

    def get_provider_audit(self, audit_id, headers):
        return self._request("GET", f"/cle/provider-audits/{audit_id}", headers=headers)

    def list_provider_audits(self, headers, params=None):
        return self._request(
            "GET", "/cle/provider-audits", headers=headers, params=params
        )

    def provider_audit_action(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/cle/provider-audits/{audit_id}/audit-actions", payload, headers
        )

    # --- Complaints -------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/cle/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/cle/complaints/{complaint_id}", headers=headers)

    def complaint_disposition(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/cle/complaints/{complaint_id}/disposition", payload, headers
        )

    # --- Fee assessments ---------------------------------------------------
    def get_fee_assessment(self, fee_assessment_id, headers):
        return self._request(
            "GET", f"/cle/fee-assessments/{fee_assessment_id}", headers=headers
        )

    def list_fee_assessments(self, headers, params=None):
        return self._request(
            "GET", "/cle/fee-assessments", headers=headers, params=params
        )

    def fee_settlement(self, fee_assessment_id, payload, headers):
        return self._request(
            "POST", f"/cle/fee-assessments/{fee_assessment_id}/settlement", payload, headers
        )

    # --- Reporting sweep ----------------------------------------------------
    def create_reporting_sweep(self, headers, payload=None):
        return self._request("POST", "/cle/reporting-sweeps", payload or {}, headers)


api_client = ApiClient()
