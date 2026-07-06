"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patient_visits(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/visits", headers=headers, params=params)

    # ---- Visit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def triage_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/triage", payload, headers)

    def begin_treatment(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/begin-treatment", headers=headers)

    def ready_for_discharge(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/ready-for-discharge", headers=headers)

    def discharge(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/discharge", headers=headers)

    def mark_deceased(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/mark-deceased", headers=headers)

    def mark_lwbs(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/mark-lwbs", headers=headers)

    # ---- Referral ----
    def create_referral(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/referrals", payload, headers)

    def list_referrals(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/referrals", headers=headers, params=params)

    def accept_referral(self, visit_id, referral_id, headers):
        return self._request("POST", f"/visits/{visit_id}/referrals/{referral_id}/accept", headers=headers)

    def decline_referral(self, visit_id, referral_id, headers):
        return self._request("POST", f"/visits/{visit_id}/referrals/{referral_id}/decline", headers=headers)

    # ---- Estimate ----
    def create_estimate(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/estimates", payload, headers)

    def list_estimates(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/estimates", headers=headers, params=params)

    def get_estimate(self, visit_id, estimate_id, headers):
        return self._request("GET", f"/visits/{visit_id}/estimates/{estimate_id}", headers=headers)

    def issue_estimate(self, visit_id, estimate_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/estimates/{estimate_id}/issue", payload, headers)

    # ---- Authorization ----
    def create_authorization(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/authorizations", payload, headers)

    def list_authorizations(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    def list_authorizations_top(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def approve_authorization(self, visit_id, authorization_id, headers):
        return self._request("POST", f"/visits/{visit_id}/authorizations/{authorization_id}/approve", headers=headers)

    def decline_authorization(self, visit_id, authorization_id, headers):
        return self._request("POST", f"/visits/{visit_id}/authorizations/{authorization_id}/decline", headers=headers)

    def void_authorization(self, visit_id, authorization_id, headers):
        return self._request("POST", f"/visits/{visit_id}/authorizations/{authorization_id}/void", headers=headers)

    # ---- Hospitalization ----
    def create_hospitalization(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/hospitalizations", payload, headers)

    def list_hospitalizations(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/hospitalizations", headers=headers, params=params)

    def release_hospitalization(self, visit_id, hospitalization_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/hospitalizations/{hospitalization_id}/release", payload, headers)

    def cancel_hospitalization(self, visit_id, hospitalization_id, headers):
        return self._request("POST", f"/visits/{visit_id}/hospitalizations/{hospitalization_id}/cancel", headers=headers)

    # ---- Procedure ----
    def create_procedure(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/procedures", payload, headers)

    def list_procedures(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/procedures", headers=headers, params=params)

    def perform_procedure(self, visit_id, procedure_id, headers):
        return self._request("POST", f"/visits/{visit_id}/procedures/{procedure_id}/perform", headers=headers)

    def cancel_procedure(self, visit_id, procedure_id, headers):
        return self._request("POST", f"/visits/{visit_id}/procedures/{procedure_id}/cancel", headers=headers)

    # ---- Invoice ----
    def get_invoice(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/invoice", headers=headers, params=params)

    def finalize_invoice(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/invoice/finalize", headers=headers)

    def pay_invoice(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/invoice/pay", payload, headers)

    # ---- PaymentPlan ----
    def create_payment_plan(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/payment-plans", payload, headers)

    def list_payment_plans(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/payment-plans", headers=headers, params=params)

    def get_payment_plan(self, payment_plan_id, headers):
        return self._request("GET", f"/payment-plans/{payment_plan_id}", headers=headers)

    def list_payment_plans_top(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def activate_payment_plan(self, visit_id, payment_plan_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/payment-plans/{payment_plan_id}/activate", payload, headers)

    def cancel_payment_plan(self, visit_id, payment_plan_id, headers):
        return self._request("POST", f"/visits/{visit_id}/payment-plans/{payment_plan_id}/cancel", headers=headers)

    # ---- ReferringVetReport ----
    def list_referring_vet_reports(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/referring-vet-reports", headers=headers, params=params)

    # ---- Test-driving: system clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
