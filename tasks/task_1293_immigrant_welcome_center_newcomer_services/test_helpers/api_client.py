"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving: logical clock + maintenance sweep (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_sweeps(self, headers):
        return self._request("POST", "/_sweeps/run", None, headers)

    # --- Clients (PRD §3.1) ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def exit_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/exit", None, headers)

    def update_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}", payload, headers)

    # --- Staff (PRD §3.1) ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    # --- Organizations (PRD §3.1) ---
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, organization_id, headers):
        return self._request("GET", f"/organizations/{organization_id}", headers=headers)

    def suspend_organization(self, organization_id, headers):
        return self._request("POST", f"/organizations/{organization_id}/suspend", None, headers)

    def reactivate_organization(self, organization_id, headers):
        return self._request("POST", f"/organizations/{organization_id}/reactivate", None, headers)

    # --- Rooms (PRD §3.1) ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    # --- Cases (PRD §3.2) ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/transition", payload, headers)

    def set_case_privacy(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/privacy", payload, headers)

    # --- Needs assessments (PRD §3.3) ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/submit", None, headers)

    def verify_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/verify", None, headers)

    # --- Case plans (PRD §3.4) ---
    def create_plan(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def transition_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/transition", payload, headers)

    # --- Case notes (PRD §3.2) ---
    def create_case_note(self, payload, headers):
        return self._request("POST", "/case-notes", payload, headers)

    def get_case_note(self, note_id, headers):
        return self._request("GET", f"/case-notes/{note_id}", headers=headers)

    def list_case_notes(self, headers, params=None):
        return self._request("GET", "/case-notes", headers=headers, params=params)

    def redact_case_note(self, note_id, payload, headers):
        return self._request("POST", f"/case-notes/{note_id}/redact", payload, headers)

    # --- Consents (PRD §3.5) ---
    def create_consent(self, payload, headers):
        return self._request("POST", "/consents", payload, headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/consents/{consent_id}", headers=headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/consents", headers=headers, params=params)

    def revoke_consent(self, consent_id, payload, headers):
        return self._request("POST", f"/consents/{consent_id}/revoke", payload, headers)

    # --- Referrals (PRD §3.5) ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def send_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/send", None, headers)

    def respond_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/respond", payload, headers)

    def confirm_handoff(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/confirm-handoff", None, headers)

    def complete_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/complete", None, headers)

    def withdraw_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", None, headers)

    def reroute_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/reroute", payload, headers)

    def resume_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/resume", None, headers)

    # --- Appointments (PRD §3.6) ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/confirm", None, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", None, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", None, headers)

    # --- Programs (PRD §3.8) ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", None, headers)

    # --- Program enrollments (PRD §3.8) ---
    def create_program_enrollment(self, payload, headers):
        return self._request("POST", "/program-enrollments", payload, headers)

    def get_program_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/program-enrollments/{enrollment_id}", headers=headers)

    def list_program_enrollments(self, headers, params=None):
        return self._request("GET", "/program-enrollments", headers=headers, params=params)

    def transition_program_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/program-enrollments/{enrollment_id}/transition", payload, headers)

    def arrange_fee(self, enrollment_id, headers):
        return self._request("POST", f"/program-enrollments/{enrollment_id}/arrange-fee", None, headers)

    # --- Workshop sessions (PRD §3.8) ---
    def create_workshop_session(self, payload, headers):
        return self._request("POST", "/workshop-sessions", payload, headers)

    def get_workshop_session(self, session_id, headers):
        return self._request("GET", f"/workshop-sessions/{session_id}", headers=headers)

    def list_workshop_sessions(self, headers, params=None):
        return self._request("GET", "/workshop-sessions", headers=headers, params=params)

    def cancel_workshop_session(self, session_id, headers):
        return self._request("POST", f"/workshop-sessions/{session_id}/cancel", None, headers)

    # --- Workshop enrollments (PRD §3.8) ---
    def create_workshop_enrollment(self, payload, headers):
        return self._request("POST", "/workshop-enrollments", payload, headers)

    def get_workshop_enrollment(self, wk_enrollment_id, headers):
        return self._request("GET", f"/workshop-enrollments/{wk_enrollment_id}", headers=headers)

    def list_workshop_enrollments(self, headers, params=None):
        return self._request("GET", "/workshop-enrollments", headers=headers, params=params)

    def cancel_workshop_enrollment(self, wk_enrollment_id, headers):
        return self._request("POST", f"/workshop-enrollments/{wk_enrollment_id}/cancel", None, headers)

    def mark_attendance(self, wk_enrollment_id, payload, headers):
        return self._request("POST", f"/workshop-enrollments/{wk_enrollment_id}/mark-attendance", payload, headers)

    # --- Benefit screenings (PRD §3.7) ---
    def create_benefit_screening(self, payload, headers):
        return self._request("POST", "/benefit-screenings", payload, headers)

    def get_benefit_screening(self, screening_id, headers):
        return self._request("GET", f"/benefit-screenings/{screening_id}", headers=headers)

    def list_benefit_screenings(self, headers, params=None):
        return self._request("GET", "/benefit-screenings", headers=headers, params=params)

    def run_benefit_screening(self, screening_id, headers):
        return self._request("POST", f"/benefit-screenings/{screening_id}/run", None, headers)

    def verify_benefit_screening(self, screening_id, payload, headers):
        return self._request("POST", f"/benefit-screenings/{screening_id}/verify", payload, headers)

    def explain_benefit_screening(self, screening_id, headers):
        return self._request("POST", f"/benefit-screenings/{screening_id}/explain", None, headers)

    def reopen_benefit_screening(self, screening_id, headers):
        return self._request("POST", f"/benefit-screenings/{screening_id}/reopen", None, headers)

    # --- Funder reports (PRD §3.9) ---
    def create_funder_report(self, payload, headers):
        return self._request("POST", "/funder-reports", payload, headers)

    def get_funder_report(self, report_id, headers):
        return self._request("GET", f"/funder-reports/{report_id}", headers=headers)

    def list_funder_reports(self, headers, params=None):
        return self._request("GET", "/funder-reports", headers=headers, params=params)

    def regenerate_funder_report(self, report_id, headers):
        return self._request("POST", f"/funder-reports/{report_id}/regenerate", None, headers)

    def submit_funder_report(self, report_id, headers):
        return self._request("POST", f"/funder-reports/{report_id}/submit", None, headers)

    def review_funder_report(self, report_id, payload, headers):
        return self._request("POST", f"/funder-reports/{report_id}/review", payload, headers)


api_client = ApiClient()
