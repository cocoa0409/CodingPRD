"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- FamilyAccount ----
    def create_family_account(self, payload, headers):
        return self._request("POST", "/family-accounts", payload, headers)

    def get_family_account(self, account_id, headers):
        return self._request("GET", f"/family-accounts/{account_id}", headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # ---- Chair ----
    def create_chair(self, payload, headers):
        return self._request("POST", "/chairs", payload, headers)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"/chairs/{chair_id}", headers=headers)

    # ---- GrowthRecord ----
    def create_growth_record(self, payload, headers):
        return self._request("POST", "/growth-records", payload, headers)

    def get_growth_record(self, record_id, headers):
        return self._request("GET", f"/growth-records/{record_id}", headers=headers)

    def list_growth_records(self, headers, params=None):
        return self._request("GET", "/growth-records", headers=headers, params=params)

    def finalize_growth_record(self, record_id, headers):
        return self._request("POST", f"/growth-records/{record_id}/finalize", headers=headers)

    # ---- InsurancePolicy ----
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def terminate_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/terminate", headers=headers)

    # ---- TreatmentPlan ----
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def propose_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/propose", headers=headers)

    def revise_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/revise", headers=headers)

    def activate_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/activate", headers=headers)

    def debond_treatment_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/treatment-plans/{plan_id}/debond", payload or {}, headers)

    def complete_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/complete", headers=headers)

    def cancel_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/cancel", headers=headers)

    # ---- TreatmentPhase ----
    def create_treatment_phase(self, payload, headers):
        return self._request("POST", "/treatment-phases", payload, headers)

    def get_treatment_phase(self, phase_id, headers):
        return self._request("GET", f"/treatment-phases/{phase_id}", headers=headers)

    def list_treatment_phases(self, headers, params=None):
        return self._request("GET", "/treatment-phases", headers=headers, params=params)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    # ---- Installment ----
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", "/installments", headers=headers, params=params)

    def charge_installment(self, installment_id, payload, headers):
        return self._request("POST", f"/installments/{installment_id}/charge", payload, headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", headers=headers)

    # ---- InsuranceClaim ----
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id, headers):
        return self._request("GET", f"/insurance-claims/{claim_id}", headers=headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", "/insurance-claims", headers=headers, params=params)

    def approve_insurance_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/approve", headers=headers)

    def deny_insurance_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/deny", headers=headers)

    def mark_paid_insurance_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/mark-paid", headers=headers)

    def void_insurance_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/void", headers=headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def checkin_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", headers=headers)

    def noshow_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show", headers=headers)

    # ---- Retainer ----
    def get_retainer(self, retainer_id, headers):
        return self._request("GET", f"/retainers/{retainer_id}", headers=headers)

    def list_retainers(self, headers, params=None):
        return self._request("GET", "/retainers", headers=headers, params=params)

    def replace_retainer(self, retainer_id, headers, payload=None):
        return self._request("POST", f"/retainers/{retainer_id}/replace", payload or {}, headers)


api_client = ApiClient()
