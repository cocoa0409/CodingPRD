"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Engineers
    # ------------------------------------------------------------------
    def create_engineer(self, payload, headers):
        return self._request("POST", "/engineers", payload, headers)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/engineers/{engineer_id}", headers=headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/engineers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Licenses
    # ------------------------------------------------------------------
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def renew_license(self, license_id, headers, payload=None):
        return self._request(
            "POST", f"/licenses/{license_id}/renew", payload or {}, headers
        )

    def reinstate_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/reinstate", payload, headers
        )

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def evaluate_education(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/education-evaluation", payload, headers
        )

    def transmit_ncees_verification(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/ncees-verification", payload, headers
        )

    def get_fee_assessment(self, application_id, headers):
        return self._request(
            "GET", f"/applications/{application_id}/fee-assessment", headers=headers
        )

    def pay_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/payments", payload, headers
        )

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/submit", payload or {}, headers
        )

    def start_review(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/start-review", payload or {}, headers
        )

    def raise_deficiency(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/deficiency", payload, headers
        )

    def respond_deficiency(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/respond-deficiency", payload, headers
        )

    def determine_credit(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/applications/{application_id}/credit-determination",
            payload or {},
            headers,
        )

    def approve_exam(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/approve-exam", payload or {}, headers
        )

    def issue_license(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/issue-license", payload or {}, headers
        )

    def deny_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/deny", payload, headers
        )

    def withdraw_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Experience records
    # ------------------------------------------------------------------
    def create_experience_record(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/experience-records", payload, headers
        )

    def get_experience_record(self, experience_record_id, headers):
        return self._request(
            "GET", f"/experience-records/{experience_record_id}", headers=headers
        )

    def list_experience_records(self, headers, params=None):
        return self._request("GET", "/experience-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------
    def create_reference(self, experience_record_id, payload, headers):
        return self._request(
            "POST",
            f"/experience-records/{experience_record_id}/references",
            payload,
            headers,
        )

    def get_reference(self, reference_id, headers):
        return self._request("GET", f"/references/{reference_id}", headers=headers)

    def list_references(self, headers, params=None):
        return self._request("GET", "/references", headers=headers, params=params)

    def submit_reference(self, reference_id, payload, headers):
        return self._request(
            "POST", f"/references/{reference_id}/submit", payload, headers
        )

    def evaluate_reference(self, reference_id, payload, headers):
        return self._request(
            "POST", f"/references/{reference_id}/evaluate", payload, headers
        )

    def recant_reference(self, reference_id, payload, headers):
        return self._request(
            "POST", f"/references/{reference_id}/recant", payload, headers
        )

    # ------------------------------------------------------------------
    # Test centres
    # ------------------------------------------------------------------
    def create_test_center(self, payload, headers):
        return self._request("POST", "/test-centers", payload, headers)

    def get_test_center(self, test_center_id, headers):
        return self._request("GET", f"/test-centers/{test_center_id}", headers=headers)

    def list_test_centers(self, headers, params=None):
        return self._request("GET", "/test-centers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Exam authorizations
    # ------------------------------------------------------------------
    def get_exam_authorization(self, exam_authorization_id, headers):
        return self._request(
            "GET", f"/exam-authorizations/{exam_authorization_id}", headers=headers
        )

    def list_exam_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/exam-authorizations", headers=headers, params=params
        )

    def score_exam(self, exam_authorization_id, payload, headers):
        return self._request(
            "POST", f"/exam-authorizations/{exam_authorization_id}/score", payload, headers
        )

    def retake_exam(self, exam_authorization_id, headers, payload=None):
        return self._request(
            "POST",
            f"/exam-authorizations/{exam_authorization_id}/retake",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Exam appointments
    # ------------------------------------------------------------------
    def create_exam_appointment(self, payload, headers):
        return self._request("POST", "/exam-appointments", payload, headers)

    def get_exam_appointment(self, exam_appointment_id, headers):
        return self._request(
            "GET", f"/exam-appointments/{exam_appointment_id}", headers=headers
        )

    def list_exam_appointments(self, headers, params=None):
        return self._request("GET", "/exam-appointments", headers=headers, params=params)

    def cancel_exam_appointment(self, exam_appointment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/exam-appointments/{exam_appointment_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Firm registrations
    # ------------------------------------------------------------------
    def create_firm_registration(self, payload, headers):
        return self._request("POST", "/firm-registrations", payload, headers)

    def get_firm_registration(self, firm_registration_id, headers):
        return self._request(
            "GET", f"/firm-registrations/{firm_registration_id}", headers=headers
        )

    def list_firm_registrations(self, headers, params=None):
        return self._request("GET", "/firm-registrations", headers=headers, params=params)

    def nominate_responsible_charge(self, firm_registration_id, payload, headers):
        return self._request(
            "POST",
            f"/firm-registrations/{firm_registration_id}/responsible-charge",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Plan submissions
    # ------------------------------------------------------------------
    def create_plan_submission(self, payload, headers):
        return self._request("POST", "/plan-submissions", payload, headers)

    def get_plan_submission(self, plan_submission_id, headers):
        return self._request(
            "GET", f"/plan-submissions/{plan_submission_id}", headers=headers
        )

    def list_plan_submissions(self, headers, params=None):
        return self._request("GET", "/plan-submissions", headers=headers, params=params)

    def seal_plan_submission(self, plan_submission_id, payload, headers):
        return self._request(
            "POST", f"/plan-submissions/{plan_submission_id}/seal", payload, headers
        )

    def flag_plan_submission(self, plan_submission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/plan-submissions/{plan_submission_id}/flag",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # CPC reports and PDH records
    # ------------------------------------------------------------------
    def create_cpc_report(self, payload, headers):
        return self._request("POST", "/cpc-reports", payload, headers)

    def get_cpc_report(self, cpc_report_id, headers):
        return self._request("GET", f"/cpc-reports/{cpc_report_id}", headers=headers)

    def list_cpc_reports(self, headers, params=None):
        return self._request("GET", "/cpc-reports", headers=headers, params=params)

    def create_pdh_record(self, cpc_report_id, payload, headers):
        return self._request(
            "POST", f"/cpc-reports/{cpc_report_id}/pdh-records", payload, headers
        )

    def get_pdh_record(self, pdh_record_id, headers):
        return self._request("GET", f"/pdh-records/{pdh_record_id}", headers=headers)

    def list_pdh_records(self, headers, params=None):
        return self._request("GET", "/pdh-records", headers=headers, params=params)

    def review_pdh_documentation(self, pdh_record_id, payload, headers):
        return self._request(
            "POST", f"/pdh-records/{pdh_record_id}/documentation-review", payload, headers
        )

    def accept_cpc_report(self, cpc_report_id, headers, payload=None):
        return self._request(
            "POST", f"/cpc-reports/{cpc_report_id}/accept", payload or {}, headers
        )

    def audit_decision(self, cpc_report_id, payload, headers):
        return self._request(
            "POST", f"/cpc-reports/{cpc_report_id}/audit-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # CPC audits
    # ------------------------------------------------------------------
    def create_cpc_audit(self, payload, headers):
        return self._request("POST", "/cpc-audits", payload, headers)

    def get_cpc_audit(self, cpc_audit_id, headers):
        return self._request("GET", f"/cpc-audits/{cpc_audit_id}", headers=headers)

    def list_cpc_audits(self, headers, params=None):
        return self._request("GET", "/cpc-audits", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def open_investigation(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/cases/{case_id}/open-investigation", payload or {}, headers
        )

    def record_finding(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/finding", payload, headers)

    def refer_hearing(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/cases/{case_id}/refer-hearing", payload or {}, headers
        )

    def close_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/cases/{case_id}/close", payload or {}, headers)

    # ------------------------------------------------------------------
    # Consent orders
    # ------------------------------------------------------------------
    def create_consent_order(self, payload, headers):
        return self._request("POST", "/consent-orders", payload, headers)

    def get_consent_order(self, consent_order_id, headers):
        return self._request(
            "GET", f"/consent-orders/{consent_order_id}", headers=headers
        )

    def list_consent_orders(self, headers, params=None):
        return self._request("GET", "/consent-orders", headers=headers, params=params)

    def execute_consent_order(self, consent_order_id, payload, headers):
        return self._request(
            "POST", f"/consent-orders/{consent_order_id}/execute", payload, headers
        )


api_client = ApiClient()
