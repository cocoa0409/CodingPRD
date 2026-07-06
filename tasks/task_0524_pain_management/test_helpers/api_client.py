"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clinic ---
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Providers ---
    def create_provider(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/providers", payload, headers)

    def list_providers(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # --- Patients ---
    def create_patient(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients", payload, headers)

    def list_patients(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/patients", headers=headers, params=params)

    def get_patient(self, clinic_id, patient_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/patients/{patient_id}", headers=headers)

    def schedule_intake(self, clinic_id, patient_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/schedule-intake", payload, headers)

    def complete_intake(self, clinic_id, patient_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/complete-intake", {}, headers)

    def activate_patient(self, clinic_id, patient_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/activate", {}, headers)

    def discharge_patient(self, clinic_id, patient_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/discharge", {}, headers)

    def clear_flag(self, clinic_id, patient_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/clear-flag", {}, headers)

    def get_patient_ledger(self, clinic_id, patient_id, headers):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/controlled-substance-ledger", headers=headers
        )

    # --- Opioid agreements ---
    def create_opioid_agreement(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/opioid-agreements", payload, headers)

    def list_opioid_agreements(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/opioid-agreements", headers=headers, params=params)

    def counter_sign_agreement(self, clinic_id, agreement_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/opioid-agreements/{agreement_id}/counter-sign", {}, headers
        )

    def revoke_agreement(self, clinic_id, agreement_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/opioid-agreements/{agreement_id}/revoke", {}, headers
        )

    # --- PDMP checks ---
    def create_pdmp_check(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/pdmp-checks", payload, headers)

    def list_pdmp_checks(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/pdmp-checks", headers=headers, params=params)

    # --- Treatment plans ---
    def create_treatment_plan(self, clinic_id, patient_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/treatment-plans", payload, headers)

    def list_treatment_plans(self, clinic_id, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/treatment-plans", headers=headers, params=params
        )

    def approve_treatment_plan(self, clinic_id, patient_id, plan_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/treatment-plans/{plan_id}/approve", {}, headers
        )

    def route_treatment_plan(self, clinic_id, patient_id, plan_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/treatment-plans/{plan_id}/route", {}, headers
        )

    def complete_treatment_plan(self, clinic_id, patient_id, plan_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/treatment-plans/{plan_id}/complete", {}, headers
        )

    # --- Fluoroscopy suites ---
    def create_fluoroscopy_suite(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/fluoroscopy-suites", payload, headers)

    def list_fluoroscopy_suites(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/fluoroscopy-suites", headers=headers, params=params)

    # --- Prior authorizations ---
    def create_prior_authorization(self, clinic_id, patient_id, payload, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/prior-authorizations", payload, headers
        )

    def list_prior_authorizations(self, clinic_id, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/prior-authorizations", headers=headers, params=params
        )

    def decide_prior_authorization(self, clinic_id, patient_id, pa_id, payload, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/prior-authorizations/{pa_id}/decide", payload, headers
        )

    # --- Procedures ---
    def create_procedure(self, clinic_id, patient_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/procedures", payload, headers)

    def list_procedures(self, clinic_id, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/procedures", headers=headers, params=params
        )

    def schedule_procedure(self, clinic_id, patient_id, procedure_id, payload, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/procedures/{procedure_id}/schedule", payload, headers
        )

    def complete_procedure(self, clinic_id, patient_id, procedure_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/procedures/{procedure_id}/complete", {}, headers
        )

    def cancel_procedure(self, clinic_id, patient_id, procedure_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/procedures/{procedure_id}/cancel", {}, headers
        )

    # --- Prescriptions ---
    def create_prescription(self, clinic_id, patient_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/prescriptions", payload, headers)

    def list_prescriptions(self, clinic_id, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/prescriptions", headers=headers, params=params
        )

    def activate_prescription(self, clinic_id, patient_id, rx_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/prescriptions/{rx_id}/activate", {}, headers
        )

    def start_taper(self, clinic_id, patient_id, rx_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/prescriptions/{rx_id}/start-taper", {}, headers
        )

    def re_escalate(self, clinic_id, patient_id, rx_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/prescriptions/{rx_id}/re-escalate", {}, headers
        )

    def discontinue_prescription(self, clinic_id, patient_id, rx_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/prescriptions/{rx_id}/discontinue", {}, headers
        )

    # --- Urine drug screens ---
    def create_urine_drug_screen(self, clinic_id, patient_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/urine-drug-screens", payload, headers)

    def list_urine_drug_screens(self, clinic_id, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/urine-drug-screens", headers=headers, params=params
        )

    def collect_urine_drug_screen(self, clinic_id, patient_id, uds_id, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/urine-drug-screens/{uds_id}/collect", {}, headers
        )

    def result_urine_drug_screen(self, clinic_id, patient_id, uds_id, payload, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/urine-drug-screens/{uds_id}/result", payload, headers
        )

    def recollect_urine_drug_screen(self, clinic_id, patient_id, uds_id, payload, headers):
        return self._request(
            "POST", f"/clinics/{clinic_id}/patients/{patient_id}/urine-drug-screens/{uds_id}/recollect", payload, headers
        )

    # --- Pill-count audits ---
    def create_pill_count_audit(self, clinic_id, patient_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/pill-count-audits", payload, headers)

    def list_pill_count_audits(self, clinic_id, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/patients/{patient_id}/pill-count-audits", headers=headers, params=params
        )


api_client = ApiClient()
