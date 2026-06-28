"""API client: one method per endpoint defined in the PRD (Dermatology Practice API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving: logical clock & recall sweep ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def recall_sweep(self, headers):
        return self._request("POST", "/_recall/sweep", {}, headers)

    # ---- Providers ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    # ---- Rooms ----
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ---- Encounters ----
    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def check_in_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/check-in", {}, headers)

    def start_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/start", {}, headers)

    def clinical_close_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/clinical-close", {}, headers)

    def cancel_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/cancel", {}, headers)

    def finalize_billing(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/finalize-billing", {}, headers)

    def void_billing(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/void-billing", {}, headers)

    def get_cosmetic_summary(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}/cosmetic-summary", headers=headers)

    # ---- Skin exam photos ----
    def create_skin_exam_photo(self, payload, headers):
        return self._request("POST", "/skin-exam-photos", payload, headers)

    def get_skin_exam_photo(self, photo_id, headers):
        return self._request("GET", f"/skin-exam-photos/{photo_id}", headers=headers)

    def list_skin_exam_photos(self, headers, params=None):
        return self._request("GET", "/skin-exam-photos", headers=headers, params=params)

    # ---- Biopsies ----
    def create_biopsy(self, payload, headers):
        return self._request("POST", "/biopsies", payload, headers)

    def get_biopsy(self, biopsy_id, headers):
        return self._request("GET", f"/biopsies/{biopsy_id}", headers=headers)

    def list_biopsies(self, headers, params=None):
        return self._request("GET", "/biopsies", headers=headers, params=params)

    def send_biopsy_to_lab(self, biopsy_id, headers):
        return self._request("POST", f"/biopsies/{biopsy_id}/send-to-lab", {}, headers)

    def result_biopsy(self, biopsy_id, payload, headers):
        return self._request("POST", f"/biopsies/{biopsy_id}/result", payload, headers)

    def sign_out_biopsy(self, biopsy_id, headers):
        return self._request("POST", f"/biopsies/{biopsy_id}/sign-out", {}, headers)

    def cancel_biopsy(self, biopsy_id, headers):
        return self._request("POST", f"/biopsies/{biopsy_id}/cancel", {}, headers)

    # ---- Procedure bookings ----
    def create_procedure_booking(self, payload, headers):
        return self._request("POST", "/procedure-bookings", payload, headers)

    def get_procedure_booking(self, booking_id, headers):
        return self._request("GET", f"/procedure-bookings/{booking_id}", headers=headers)

    def list_procedure_bookings(self, headers, params=None):
        return self._request("GET", "/procedure-bookings", headers=headers, params=params)

    def complete_procedure_booking(self, booking_id, headers):
        return self._request("POST", f"/procedure-bookings/{booking_id}/complete", {}, headers)

    def cancel_procedure_booking(self, booking_id, headers):
        return self._request("POST", f"/procedure-bookings/{booking_id}/cancel", {}, headers)

    # ---- Prior authorizations ----
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/prior-authorizations", payload, headers)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"/prior-authorizations/{pa_id}", headers=headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", "/prior-authorizations", headers=headers, params=params)

    def create_step_therapy_trial(self, pa_id, payload, headers):
        return self._request("POST", f"/prior-authorizations/{pa_id}/step-therapy-trials", payload, headers)

    def list_step_therapy_trials(self, pa_id, headers, params=None):
        return self._request("GET", f"/prior-authorizations/{pa_id}/step-therapy-trials", headers=headers, params=params)

    def submit_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"/prior-authorizations/{pa_id}/submit", {}, headers)

    def adjudicate_prior_authorization(self, pa_id, payload, headers):
        return self._request("POST", f"/prior-authorizations/{pa_id}/adjudicate", payload, headers)

    # ---- Cosmetic memberships ----
    def create_cosmetic_membership(self, payload, headers):
        return self._request("POST", "/cosmetic-memberships", payload, headers)

    def get_cosmetic_membership(self, membership_id, headers):
        return self._request("GET", f"/cosmetic-memberships/{membership_id}", headers=headers)

    def list_cosmetic_memberships(self, headers, params=None):
        return self._request("GET", "/cosmetic-memberships", headers=headers, params=params)

    def activate_cosmetic_membership(self, membership_id, headers):
        return self._request("POST", f"/cosmetic-memberships/{membership_id}/activate", {}, headers)

    def cancel_cosmetic_membership(self, membership_id, headers):
        return self._request("POST", f"/cosmetic-memberships/{membership_id}/cancel", {}, headers)

    # ---- Cosmetic treatments ----
    def create_cosmetic_treatment(self, payload, headers):
        return self._request("POST", "/cosmetic-treatments", payload, headers)

    def get_cosmetic_treatment(self, treatment_id, headers):
        return self._request("GET", f"/cosmetic-treatments/{treatment_id}", headers=headers)

    def list_cosmetic_treatments(self, headers, params=None):
        return self._request("GET", "/cosmetic-treatments", headers=headers, params=params)

    # ---- Charges ----
    def create_charge(self, payload, headers):
        return self._request("POST", "/charges", payload, headers)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def pay_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/pay", {}, headers)

    def void_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/void", {}, headers)

    # ---- Recall reminders ----
    def create_recall_reminder(self, payload, headers):
        return self._request("POST", "/recall-reminders", payload, headers)

    def get_recall_reminder(self, recall_id, headers):
        return self._request("GET", f"/recall-reminders/{recall_id}", headers=headers)

    def list_recall_reminders(self, headers, params=None):
        return self._request("GET", "/recall-reminders", headers=headers, params=params)

    def dismiss_recall_reminder(self, recall_id, headers):
        return self._request("POST", f"/recall-reminders/{recall_id}/dismiss", {}, headers)


api_client = ApiClient()
