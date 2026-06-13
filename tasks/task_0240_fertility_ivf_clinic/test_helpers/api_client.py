"""API client: one method per endpoint defined in the PRD.

All resource collections live under a clinic. Cross-entity scoping is carried in
request bodies and surfaced through filtered-list query params (PRD 2).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clinic + deterministic clock ----
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Insurance packages ----
    def create_package(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/packages", payload, headers)

    def list_packages(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/packages", headers=headers, params=params)

    def get_package(self, clinic_id, package_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/packages/{package_id}", headers=headers)

    def retire_package(self, clinic_id, package_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/packages/{package_id}/retire", {}, headers)

    # ---- Patients ----
    def create_patient(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients", payload, headers)

    def list_patients(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/patients", headers=headers, params=params)

    def get_patient(self, clinic_id, patient_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/patients/{patient_id}", headers=headers)

    def deactivate_patient(self, clinic_id, patient_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patients/{patient_id}/deactivate", {}, headers)

    # ---- Donor / surrogate ----
    def create_donor(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/donors", payload, headers)

    def list_donors(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/donors", headers=headers, params=params)

    def get_donor(self, clinic_id, donor_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/donors/{donor_id}", headers=headers)

    def create_surrogate(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/surrogates", payload, headers)

    def list_surrogates(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/surrogates", headers=headers, params=params)

    def get_surrogate(self, clinic_id, surrogate_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/surrogates/{surrogate_id}", headers=headers)

    # ---- Consent forms ----
    def create_consent_form(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/consent-forms", payload, headers)

    def list_consent_forms(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/consent-forms", headers=headers, params=params)

    def get_consent_form(self, clinic_id, form_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/consent-forms/{form_id}", headers=headers)

    def publish_consent_form(self, clinic_id, form_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/consent-forms/{form_id}/publish", {}, headers)

    # ---- Patient consents ----
    def create_patient_consent(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patient-consents", payload, headers)

    def list_patient_consents(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/patient-consents", headers=headers, params=params)

    def get_patient_consent(self, clinic_id, consent_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/patient-consents/{consent_id}", headers=headers)

    def revoke_patient_consent(self, clinic_id, consent_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/patient-consents/{consent_id}/revoke", {}, headers)

    # ---- Cryo tanks ----
    def create_tank(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/tanks", payload, headers)

    def list_tanks(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/tanks", headers=headers, params=params)

    def get_tank(self, clinic_id, tank_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/tanks/{tank_id}", headers=headers)

    def set_tank_maintenance(self, clinic_id, tank_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/tanks/{tank_id}/set-maintenance", {}, headers)

    # ---- Treatment cycles ----
    def create_cycle(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles", payload, headers)

    def list_cycles(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/cycles", headers=headers, params=params)

    def get_cycle(self, clinic_id, cycle_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/cycles/{cycle_id}", headers=headers)

    def start_stim(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/start-stim", {}, headers)

    def retrieve(self, clinic_id, cycle_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/retrieve", payload, headers)

    def revert_to_stim(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/revert-to-stim", {}, headers)

    def fertilize(self, clinic_id, cycle_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/fertilize", payload, headers)

    def transfer(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/transfer", {}, headers)

    def freeze_all(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/freeze-all", {}, headers)

    def complete_cycle(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/complete", {}, headers)

    def cancel_cycle(self, clinic_id, cycle_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/cancel", payload, headers)

    # ---- Medication calendar ----
    def create_medication(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/medications", payload, headers)

    def list_medications(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/medications", headers=headers, params=params)

    def get_medication(self, clinic_id, med_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/medications/{med_id}", headers=headers)

    def administer_medication(self, clinic_id, med_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/medications/{med_id}/administer", {}, headers)

    def cancel_medication(self, clinic_id, med_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/medications/{med_id}/cancel", {}, headers)

    # ---- Monitoring appointments ----
    def create_appointment(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/monitoring-appointments", payload, headers)

    def list_appointments(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/monitoring-appointments", headers=headers, params=params)

    def get_appointment(self, clinic_id, appt_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/monitoring-appointments/{appt_id}", headers=headers)

    def reschedule_appointment(self, clinic_id, appt_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/monitoring-appointments/{appt_id}/reschedule", payload, headers)

    def confirm_appointment(self, clinic_id, appt_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/monitoring-appointments/{appt_id}/confirm", {}, headers)

    def complete_appointment(self, clinic_id, appt_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/monitoring-appointments/{appt_id}/complete", {}, headers)

    def no_show_appointment(self, clinic_id, appt_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/monitoring-appointments/{appt_id}/no-show", {}, headers)

    def cancel_appointment(self, clinic_id, appt_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/monitoring-appointments/{appt_id}/cancel", {}, headers)

    # ---- Cryo specimens ----
    def create_specimen(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cryo-specimens", payload, headers)

    def list_specimens(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/cryo-specimens", headers=headers, params=params)

    def get_specimen(self, clinic_id, specimen_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/cryo-specimens/{specimen_id}", headers=headers)

    def store_specimen(self, clinic_id, specimen_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cryo-specimens/{specimen_id}/store", payload, headers)

    def accrue_storage_year(self, clinic_id, specimen_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cryo-specimens/{specimen_id}/accrue-storage-year", {}, headers)

    def thaw_specimen(self, clinic_id, specimen_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cryo-specimens/{specimen_id}/thaw", {}, headers)

    def discard_specimen(self, clinic_id, specimen_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cryo-specimens/{specimen_id}/discard", {}, headers)

    def transfer_out_specimen(self, clinic_id, specimen_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cryo-specimens/{specimen_id}/transfer-out", {}, headers)

    # ---- Billing ----
    def estimate_billing(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/billing/estimate", {}, headers)

    def settle_billing(self, clinic_id, cycle_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/billing/settle", payload, headers)

    def write_off_billing(self, clinic_id, cycle_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cycles/{cycle_id}/billing/write-off", {}, headers)

    def list_invoices(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/cycle-invoices", headers=headers, params=params)

    def get_invoice(self, clinic_id, invoice_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/cycle-invoices/{invoice_id}", headers=headers)

    # ---- Outcome reporting ----
    def create_outcome(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/outcome-reports", payload, headers)

    def list_outcomes(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/outcome-reports", headers=headers, params=params)

    def get_outcome(self, clinic_id, outcome_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}/outcome-reports/{outcome_id}", headers=headers)


api_client = ApiClient()
