"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Clinic ----
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    # ---- ExamRoom ----
    def create_exam_room(self, payload, headers):
        return self._request("POST", "/exam-rooms", payload, headers)

    def get_exam_room(self, room_id, headers):
        return self._request("GET", f"/exam-rooms/{room_id}", headers=headers)

    def list_exam_rooms(self, headers, params=None):
        return self._request("GET", "/exam-rooms", headers=headers, params=params)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    # ---- IntakeSession ----
    def create_intake_session(self, payload, headers):
        return self._request("POST", "/intake-sessions", payload, headers)

    def get_intake_session(self, session_id, headers):
        return self._request("GET", f"/intake-sessions/{session_id}", headers=headers)

    def list_intake_sessions(self, headers, params=None):
        return self._request("GET", "/intake-sessions", headers=headers, params=params)

    def check_in_session(self, session_id, headers):
        return self._request("POST", f"/intake-sessions/{session_id}/check-in", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/intake-sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/intake-sessions/{session_id}/cancel", {}, headers)

    def waive_copay(self, session_id, headers):
        return self._request("POST", f"/intake-sessions/{session_id}/waive-copay", {}, headers)

    # ---- InsuranceCard ----
    def create_insurance_card(self, payload, headers):
        return self._request("POST", "/insurance-cards", payload, headers)

    def get_insurance_card(self, card_id, headers):
        return self._request("GET", f"/insurance-cards/{card_id}", headers=headers)

    def list_insurance_cards(self, headers, params=None):
        return self._request("GET", "/insurance-cards", headers=headers, params=params)

    def verify_insurance_card(self, card_id, headers):
        return self._request("POST", f"/insurance-cards/{card_id}/verify", {}, headers)

    def resolve_eligibility(self, card_id, payload, headers):
        return self._request("POST", f"/insurance-cards/{card_id}/resolve-eligibility", payload, headers)

    # ---- EligibilityCheck ----
    def get_eligibility_check(self, check_id, headers):
        return self._request("GET", f"/eligibility-checks/{check_id}", headers=headers)

    def list_eligibility_checks(self, headers, params=None):
        return self._request("GET", "/eligibility-checks", headers=headers, params=params)

    # ---- ConsentDocument ----
    def create_consent_document(self, payload, headers):
        return self._request("POST", "/consent-documents", payload, headers)

    def get_consent_document(self, consent_id, headers):
        return self._request("GET", f"/consent-documents/{consent_id}", headers=headers)

    def list_consent_documents(self, headers, params=None):
        return self._request("GET", "/consent-documents", headers=headers, params=params)

    def sign_consent(self, consent_id, payload, headers):
        return self._request("POST", f"/consent-documents/{consent_id}/sign", payload, headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-documents/{consent_id}/revoke", {}, headers)

    def reissue_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-documents/{consent_id}/reissue", {}, headers)

    # ---- QuestionnaireResponse ----
    def create_questionnaire(self, payload, headers):
        return self._request("POST", "/questionnaire-responses", payload, headers)

    def get_questionnaire(self, qr_id, headers):
        return self._request("GET", f"/questionnaire-responses/{qr_id}", headers=headers)

    def list_questionnaires(self, headers, params=None):
        return self._request("GET", "/questionnaire-responses", headers=headers, params=params)

    def patch_questionnaire(self, qr_id, payload, headers):
        return self._request("PATCH", f"/questionnaire-responses/{qr_id}", payload, headers)

    def submit_questionnaire(self, qr_id, headers):
        return self._request("POST", f"/questionnaire-responses/{qr_id}/submit", {}, headers)

    def accept_questionnaire(self, qr_id, headers):
        return self._request("POST", f"/questionnaire-responses/{qr_id}/accept", {}, headers)

    def revise_questionnaire(self, qr_id, headers):
        return self._request("POST", f"/questionnaire-responses/{qr_id}/revise", {}, headers)

    # ---- CopayPayment ----
    def create_copay_payment(self, payload, headers):
        return self._request("POST", "/copay-payments", payload, headers)

    def get_copay_payment(self, payment_id, headers):
        return self._request("GET", f"/copay-payments/{payment_id}", headers=headers)

    def list_copay_payments(self, headers, params=None):
        return self._request("GET", "/copay-payments", headers=headers, params=params)

    def capture_copay(self, payment_id, headers):
        return self._request("POST", f"/copay-payments/{payment_id}/capture", {}, headers)

    def void_copay(self, payment_id, headers):
        return self._request("POST", f"/copay-payments/{payment_id}/void", {}, headers)

    def refund_copay(self, payment_id, headers):
        return self._request("POST", f"/copay-payments/{payment_id}/refund", {}, headers)

    # ---- KioskQueueEntry ----
    def get_queue_entry(self, entry_id, headers):
        return self._request("GET", f"/queue-entries/{entry_id}", headers=headers)

    def list_queue_entries(self, headers, params=None):
        return self._request("GET", "/queue-entries", headers=headers, params=params)

    def call_queue_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/queue-entries/{entry_id}/call", payload, headers)

    def room_in_queue_entry(self, entry_id, headers):
        return self._request("POST", f"/queue-entries/{entry_id}/room-in", {}, headers)

    def done_queue_entry(self, entry_id, headers):
        return self._request("POST", f"/queue-entries/{entry_id}/done", {}, headers)

    def no_show_queue_entry(self, entry_id, headers):
        return self._request("POST", f"/queue-entries/{entry_id}/no-show", {}, headers)

    # ---- RoomBooking ----
    def create_room_booking(self, payload, headers):
        return self._request("POST", "/room-bookings", payload, headers)

    def get_room_booking(self, booking_id, headers):
        return self._request("GET", f"/room-bookings/{booking_id}", headers=headers)

    def list_room_bookings(self, headers, params=None):
        return self._request("GET", "/room-bookings", headers=headers, params=params)

    # ---- Reminder ----
    def create_reminder(self, payload, headers):
        return self._request("POST", "/reminders", payload, headers)

    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/reminders/{reminder_id}", headers=headers)

    def list_reminders(self, headers, params=None):
        return self._request("GET", "/reminders", headers=headers, params=params)

    def cancel_reminder(self, reminder_id, headers):
        return self._request("POST", f"/reminders/{reminder_id}/cancel", {}, headers)

    # ---- DemographicsSyncJob ----
    def create_demographics_sync_job(self, payload, headers):
        return self._request("POST", "/demographics-sync-jobs", payload, headers)

    def get_demographics_sync_job(self, job_id, headers):
        return self._request("GET", f"/demographics-sync-jobs/{job_id}", headers=headers)

    def list_demographics_sync_jobs(self, headers, params=None):
        return self._request("GET", "/demographics-sync-jobs", headers=headers, params=params)


api_client = ApiClient()
