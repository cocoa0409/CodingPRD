"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Patients ----------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def deactivate_patient(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/deactivate", {}, headers)

    def create_tooth_chart(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/tooth-chart", payload, headers)

    def list_tooth_chart_entries(self, headers, params=None):
        return self._request("GET", "/tooth-chart-entries", headers=headers, params=params)

    def get_tooth_chart_entry(self, entry_id, headers):
        return self._request("GET", f"/tooth-chart-entries/{entry_id}", headers=headers)

    # ---------------- Providers ----------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def deactivate_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/deactivate", {}, headers)

    # ---------------- Operatories ----------------
    def create_operatory(self, payload, headers):
        return self._request("POST", "/operatories", payload, headers)

    def list_operatories(self, headers, params=None):
        return self._request("GET", "/operatories", headers=headers, params=params)

    def get_operatory(self, operatory_id, headers):
        return self._request("GET", f"/operatories/{operatory_id}", headers=headers)

    def close_operatory(self, operatory_id, headers):
        return self._request("POST", f"/operatories/{operatory_id}/close", {}, headers)

    # ---------------- Insurance Plans ----------------
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    # ---------------- Patient Coverages ----------------
    def create_patient_coverage(self, payload, headers):
        return self._request("POST", "/patient-coverages", payload, headers)

    def list_patient_coverages(self, headers, params=None):
        return self._request("GET", "/patient-coverages", headers=headers, params=params)

    def get_patient_coverage(self, coverage_id, headers):
        return self._request("GET", f"/patient-coverages/{coverage_id}", headers=headers)

    def terminate_patient_coverage(self, coverage_id, headers):
        return self._request("POST", f"/patient-coverages/{coverage_id}/terminate", {}, headers)

    # ---------------- Treatment Plans ----------------
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def add_treatment_plan_item(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/items", payload, headers)

    def list_treatment_plan_items(self, headers, params=None):
        return self._request("GET", "/treatment-plan-items", headers=headers, params=params)

    def get_treatment_plan_item(self, item_id, headers):
        return self._request("GET", f"/treatment-plan-items/{item_id}", headers=headers)

    def propose_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/propose", {}, headers)

    def revise_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/revise", {}, headers)

    def accept_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/accept", {}, headers)

    def complete_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/complete", {}, headers)

    def cancel_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/cancel", {}, headers)

    # ---------------- Appointments ----------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show", {}, headers)

    # ---------------- Predeterminations ----------------
    def create_predetermination(self, payload, headers):
        return self._request("POST", "/predeterminations", payload, headers)

    def list_predeterminations(self, headers, params=None):
        return self._request("GET", "/predeterminations", headers=headers, params=params)

    def get_predetermination(self, pred_id, headers):
        return self._request("GET", f"/predeterminations/{pred_id}", headers=headers)

    def approve_predetermination(self, pred_id, payload, headers):
        return self._request("POST", f"/predeterminations/{pred_id}/approve", payload, headers)

    def deny_predetermination(self, pred_id, headers):
        return self._request("POST", f"/predeterminations/{pred_id}/deny", {}, headers)

    # ---------------- Claims ----------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def add_claim_attachment(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/attachments", payload, headers)

    def list_claim_attachments(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/attachments", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/void", {}, headers)

    # ---------------- Recare Recall ----------------
    def create_recare_recall(self, payload, headers):
        return self._request("POST", "/recare-recalls", payload, headers)

    def list_recare_recalls(self, headers, params=None):
        return self._request("GET", "/recare-recalls", headers=headers, params=params)

    def get_recare_recall(self, recall_id, headers):
        return self._request("GET", f"/recare-recalls/{recall_id}", headers=headers)

    def fulfill_recare_recall(self, recall_id, payload, headers):
        return self._request("POST", f"/recare-recalls/{recall_id}/fulfill", payload, headers)

    # ---------------- Payment Plans ----------------
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/payment-plans", payload, headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def post_installment(self, plan_id, payload, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/post-installment", payload, headers)

    def reverse_installment(self, plan_id, payload, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/reverse-installment", payload, headers)

    def default_payment_plan(self, plan_id, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/default", {}, headers)

    # ---------------- Deterministic clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
