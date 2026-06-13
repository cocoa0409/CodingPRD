"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Institution ---
    def create_institution(self, payload, headers):
        return self._request("POST", "/institutions", payload, headers)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/institutions/{institution_id}", headers=headers)

    def set_clock(self, institution_id, payload, headers):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/_clock/set_current_utc",
            payload,
            headers,
        )

    # --- AcademicTerm ---
    def create_term(self, payload, headers):
        return self._request("POST", "/institutions/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/institutions/terms/{term_id}", headers=headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/institutions/terms", headers=headers, params=params)

    def lock_term(self, term_id, headers):
        return self._request("POST", f"/institutions/terms/{term_id}/lock", headers=headers)

    def close_term(self, term_id, headers):
        return self._request("POST", f"/institutions/terms/{term_id}/close", headers=headers)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/institutions/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/institutions/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/institutions/students", headers=headers, params=params)

    # --- PlanTemplate ---
    def create_plan_template(self, payload, headers):
        return self._request("POST", "/institutions/plan-templates", payload, headers)

    def get_plan_template(self, plan_template_id, headers):
        return self._request(
            "GET", f"/institutions/plan-templates/{plan_template_id}", headers=headers
        )

    def list_plan_templates(self, headers, params=None):
        return self._request(
            "GET", "/institutions/plan-templates", headers=headers, params=params
        )

    def retire_plan_template(self, plan_template_id, headers):
        return self._request(
            "POST", f"/institutions/plan-templates/{plan_template_id}/retire", headers=headers
        )

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/institutions/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/institutions/enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/institutions/enrollments", headers=headers, params=params
        )

    def activate_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/institutions/enrollments/{enrollment_id}/activate", payload, headers
        )

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/institutions/enrollments/{enrollment_id}/withdraw", payload, headers
        )

    def run_delinquency(self, enrollment_id, headers):
        return self._request(
            "POST", f"/institutions/enrollments/{enrollment_id}/run-delinquency", headers=headers
        )

    # --- Installment ---
    def get_installment(self, installment_id, headers):
        return self._request(
            "GET", f"/institutions/installments/{installment_id}", headers=headers
        )

    def list_installments(self, headers, params=None):
        return self._request(
            "GET", "/institutions/installments", headers=headers, params=params
        )

    # --- Charge ---
    def create_charge(self, payload, headers):
        return self._request("POST", "/institutions/charges", payload, headers)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/institutions/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/institutions/charges", headers=headers, params=params)

    def reverse_charge(self, charge_id, headers):
        return self._request(
            "POST", f"/institutions/charges/{charge_id}/reverse", headers=headers
        )

    # --- FinancialAid ---
    def create_aid(self, payload, headers):
        return self._request("POST", "/institutions/aids", payload, headers)

    def get_aid(self, aid_id, headers):
        return self._request("GET", f"/institutions/aids/{aid_id}", headers=headers)

    def list_aids(self, headers, params=None):
        return self._request("GET", "/institutions/aids", headers=headers, params=params)

    def cancel_aid(self, aid_id, headers):
        return self._request("POST", f"/institutions/aids/{aid_id}/cancel", headers=headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/institutions/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/institutions/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/institutions/payments", headers=headers, params=params)

    def settle_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/institutions/payments/{payment_id}/settle", headers=headers
        )

    def fail_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/institutions/payments/{payment_id}/fail", headers=headers
        )

    # --- LateFee ---
    def get_late_fee(self, late_fee_id, headers):
        return self._request("GET", f"/institutions/late-fees/{late_fee_id}", headers=headers)

    def list_late_fees(self, headers, params=None):
        return self._request("GET", "/institutions/late-fees", headers=headers, params=params)

    def waive_late_fee(self, late_fee_id, headers):
        return self._request(
            "POST", f"/institutions/late-fees/{late_fee_id}/waive", headers=headers
        )

    # --- Hold ---
    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/institutions/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/institutions/holds", headers=headers, params=params)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/institutions/holds/{hold_id}/release", headers=headers)

    # --- Withdrawal ---
    def get_withdrawal(self, withdrawal_id, headers):
        return self._request(
            "GET", f"/institutions/withdrawals/{withdrawal_id}", headers=headers
        )

    def list_withdrawals(self, headers, params=None):
        return self._request(
            "GET", "/institutions/withdrawals", headers=headers, params=params
        )


api_client = ApiClient()
