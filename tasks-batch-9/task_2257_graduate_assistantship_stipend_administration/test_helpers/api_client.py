"""API client: one method per endpoint defined by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------- terms #
    def create_academic_term(self, payload, headers):
        return self._request("POST", "/academic-terms", payload, headers)

    def get_academic_term(self, term_id, headers):
        return self._request("GET", f"/academic-terms/{term_id}", headers=headers)

    def open_academic_term(self, term_id, headers, payload=None):
        return self._request(
            "POST", f"/academic-terms/{term_id}/open", payload or {}, headers
        )

    def lock_payroll(self, term_id, headers, payload=None):
        return self._request(
            "POST", f"/academic-terms/{term_id}/lock-payroll", payload or {}, headers
        )

    def close_academic_term(self, term_id, headers, payload=None):
        return self._request(
            "POST", f"/academic-terms/{term_id}/close", payload or {}, headers
        )

    def list_term_stipend_policies(self, term_id, headers, params=None):
        return self._request(
            "GET", f"/academic-terms/{term_id}/stipend-policies",
            headers=headers, params=params,
        )

    def list_term_pay_periods(self, term_id, headers, params=None):
        return self._request(
            "GET", f"/academic-terms/{term_id}/pay-periods",
            headers=headers, params=params,
        )

    # ----------------------------------------------------------- departments #
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    # ------------------------------------------- stipend policies / periods #
    def create_stipend_policy(self, payload, headers):
        return self._request("POST", "/stipend-policies", payload, headers)

    def create_pay_period(self, payload, headers):
        return self._request("POST", "/pay-periods", payload, headers)

    # -------------------------------------------------------------- students #
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def patch_academic_progress(self, student_id, payload, headers):
        return self._request(
            "PATCH", f"/students/{student_id}/academic-progress", payload, headers
        )

    def effort_cap_override(self, student_id, payload, headers):
        return self._request(
            "POST", f"/students/{student_id}/effort-cap-override", payload, headers
        )

    # ------------------------------------------------------- funding sources #
    def create_funding_source(self, payload, headers):
        return self._request("POST", "/funding-sources", payload, headers)

    def get_funding_source(self, source_id, headers):
        return self._request("GET", f"/funding-sources/{source_id}", headers=headers)

    def list_funding_sources(self, headers, params=None):
        return self._request("GET", "/funding-sources", headers=headers, params=params)

    def suspend_funding_source(self, source_id, payload, headers):
        return self._request(
            "POST", f"/funding-sources/{source_id}/suspend", payload, headers
        )

    def reinstate_funding_source(self, source_id, headers, payload=None):
        return self._request(
            "POST", f"/funding-sources/{source_id}/reinstate", payload or {}, headers
        )

    def close_funding_source(self, source_id, headers, payload=None):
        return self._request(
            "POST", f"/funding-sources/{source_id}/close", payload or {}, headers
        )

    # ---------------------------------------------------------- appointments #
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def replace_funding_plan(self, appointment_id, payload, headers):
        return self._request(
            "PUT", f"/appointments/{appointment_id}/funding-plan", payload, headers
        )

    def submit_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/submit", payload or {}, headers
        )

    def return_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/return", payload, headers
        )

    def verify_funding(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/verify-funding",
            payload or {}, headers,
        )

    def approve_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/approve", payload or {}, headers
        )

    def activate_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/activate", payload or {}, headers
        )

    def schedule_payroll(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/schedule-payroll",
            payload or {}, headers,
        )

    def terminate_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/terminate", payload, headers
        )

    def suspend_pay(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/suspend-pay", payload, headers
        )

    def resume_pay(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/resume-pay", payload or {}, headers
        )

    # ----------------------------------------------------- funding allocations #
    def get_funding_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/funding-allocations/{allocation_id}", headers=headers
        )

    def list_funding_allocations(self, headers, params=None):
        return self._request(
            "GET", "/funding-allocations", headers=headers, params=params
        )

    def release_funding_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/funding-allocations/{allocation_id}/release", payload, headers
        )

    # -------------------------------------------------- stipend disbursements #
    def get_stipend_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/stipend-disbursements/{disbursement_id}", headers=headers
        )

    def list_stipend_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/stipend-disbursements", headers=headers, params=params
        )

    def pay_stipend_disbursement(self, disbursement_id, headers, payload=None):
        return self._request(
            "POST", f"/stipend-disbursements/{disbursement_id}/pay",
            payload or {}, headers,
        )

    def reverse_stipend_disbursement(self, disbursement_id, payload, headers):
        return self._request(
            "POST", f"/stipend-disbursements/{disbursement_id}/reverse", payload, headers
        )

    # ------------------------------------------------------ renewal decisions #
    def create_renewal_decision(self, payload, headers):
        return self._request("POST", "/renewal-decisions", payload, headers)

    def get_renewal_decision(self, decision_id, headers):
        return self._request(
            "GET", f"/renewal-decisions/{decision_id}", headers=headers
        )

    def list_renewal_decisions(self, headers, params=None):
        return self._request(
            "GET", "/renewal-decisions", headers=headers, params=params
        )

    def certify_progress(self, decision_id, headers, payload=None):
        return self._request(
            "POST", f"/renewal-decisions/{decision_id}/certify-progress",
            payload or {}, headers,
        )

    def issue_notice(self, decision_id, payload, headers):
        return self._request(
            "POST", f"/renewal-decisions/{decision_id}/issue-notice", payload, headers
        )

    def acknowledge_notice(self, decision_id, headers, payload=None):
        return self._request(
            "POST", f"/renewal-decisions/{decision_id}/acknowledge",
            payload or {}, headers,
        )

    # --------------------------------------------------------- tax assessments #
    def create_tax_assessment(self, payload, headers):
        return self._request("POST", "/tax-assessments", payload, headers)

    def get_tax_assessment(self, assessment_id, headers):
        return self._request("GET", f"/tax-assessments/{assessment_id}", headers=headers)

    def list_tax_assessments(self, headers, params=None):
        return self._request("GET", "/tax-assessments", headers=headers, params=params)

    def finalize_tax_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"/tax-assessments/{assessment_id}/finalize", payload or {}, headers
        )

    def amend_tax_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/tax-assessments/{assessment_id}/amend", payload, headers
        )

    # ---------------------------------------------------------- logical clock #
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
