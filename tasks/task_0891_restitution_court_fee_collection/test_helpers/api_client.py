"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() handles
the HTTP call and envelope transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/collections/cases", payload, headers=headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/collections/cases/{case_id}", headers=headers)

    # ---- Victim ----
    def create_victim(self, payload, headers):
        return self._request("POST", "/collections/victims", payload, headers=headers)

    def get_victim(self, victim_id, headers):
        return self._request("GET", f"/collections/victims/{victim_id}", headers=headers)

    # ---- Obligation ----
    def create_obligation(self, payload, headers):
        return self._request("POST", "/collections/obligations", payload, headers=headers)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/collections/obligations/{obligation_id}", headers=headers)

    def list_obligations(self, headers, params=None):
        return self._request("GET", "/collections/obligations", headers=headers, params=params)

    def write_off_obligation(self, obligation_id, headers):
        return self._request("POST", f"/collections/obligations/{obligation_id}/write-off", {}, headers=headers)

    # ---- PaymentPlan ----
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/collections/payment-plans", payload, headers=headers)

    def get_payment_plan(self, payment_plan_id, headers):
        return self._request("GET", f"/collections/payment-plans/{payment_plan_id}", headers=headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/collections/payment-plans", headers=headers, params=params)

    def activate_payment_plan(self, payment_plan_id, headers):
        return self._request("POST", f"/collections/payment-plans/{payment_plan_id}/activate", {}, headers=headers)

    def reinstate_payment_plan(self, payment_plan_id, headers):
        return self._request("POST", f"/collections/payment-plans/{payment_plan_id}/reinstate", {}, headers=headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/collections/payments", payload, headers=headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/collections/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/collections/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/collections/payments/{payment_id}/reverse", {}, headers=headers)

    # ---- Disbursement ----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/collections/disbursements", payload, headers=headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/collections/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/collections/disbursements", headers=headers, params=params)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/collections/disbursements/{disbursement_id}/void", {}, headers=headers)

    # ---- WageAssignment ----
    def create_wage_assignment(self, payload, headers):
        return self._request("POST", "/collections/wage-assignments", payload, headers=headers)

    def get_wage_assignment(self, wage_assignment_id, headers):
        return self._request("GET", f"/collections/wage-assignments/{wage_assignment_id}", headers=headers)

    def list_wage_assignments(self, headers, params=None):
        return self._request("GET", "/collections/wage-assignments", headers=headers, params=params)

    def terminate_wage_assignment(self, wage_assignment_id, headers):
        return self._request("POST", f"/collections/wage-assignments/{wage_assignment_id}/terminate", {}, headers=headers)

    # ---- EnforcementAction ----
    def get_enforcement_action(self, enforcement_action_id, headers):
        return self._request("GET", f"/collections/enforcement-actions/{enforcement_action_id}", headers=headers)

    def list_enforcement_actions(self, headers, params=None):
        return self._request("GET", "/collections/enforcement-actions", headers=headers, params=params)

    def lift_enforcement_action(self, enforcement_action_id, headers):
        return self._request("POST", f"/collections/enforcement-actions/{enforcement_action_id}/lift", {}, headers=headers)

    # ---- WaiverRequest ----
    def create_waiver_request(self, payload, headers):
        return self._request("POST", "/collections/waiver-requests", payload, headers=headers)

    def get_waiver_request(self, waiver_request_id, headers):
        return self._request("GET", f"/collections/waiver-requests/{waiver_request_id}", headers=headers)

    def list_waiver_requests(self, headers, params=None):
        return self._request("GET", "/collections/waiver-requests", headers=headers, params=params)

    def approve_waiver_request(self, waiver_request_id, headers):
        return self._request("POST", f"/collections/waiver-requests/{waiver_request_id}/approve", {}, headers=headers)

    def deny_waiver_request(self, waiver_request_id, headers):
        return self._request("POST", f"/collections/waiver-requests/{waiver_request_id}/deny", {}, headers=headers)

    # ---- AmnestyProgram ----
    def create_amnesty_program(self, payload, headers):
        return self._request("POST", "/collections/amnesty-programs", payload, headers=headers)

    def get_amnesty_program(self, amnesty_program_id, headers):
        return self._request("GET", f"/collections/amnesty-programs/{amnesty_program_id}", headers=headers)

    # ---- System / reporting ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/collections/_clock/set_current_utc", payload, headers=headers)

    def delinquency_sweep(self, headers):
        return self._request("POST", "/collections/delinquency-sweep", {}, headers=headers)

    def get_aging_report(self, headers, params=None):
        return self._request("GET", "/collections/reports/aging", headers=headers, params=params)


api_client = ApiClient()
