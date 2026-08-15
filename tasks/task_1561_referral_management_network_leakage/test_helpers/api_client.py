"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Referring providers ---
    def create_referring_provider(self, payload, headers):
        return self._request("POST", "/referring-providers", payload, headers)

    def list_referring_providers(self, headers, params=None):
        return self._request("GET", "/referring-providers", headers=headers, params=params)

    def get_referring_provider(self, provider_id, headers):
        return self._request("GET", f"/referring-providers/{provider_id}", headers=headers)

    def suspend_referring_provider(self, provider_id, headers):
        return self._request("POST", f"/referring-providers/{provider_id}/suspend", headers=headers)

    def reactivate_referring_provider(self, provider_id, headers):
        return self._request("POST", f"/referring-providers/{provider_id}/reactivate", headers=headers)

    def list_provider_referrals(self, provider_id, headers, params=None):
        return self._request("GET", f"/referring-providers/{provider_id}/referrals", headers=headers, params=params)

    def list_provider_leakage_records(self, provider_id, headers, params=None):
        return self._request("GET", f"/referring-providers/{provider_id}/leakage-records", headers=headers, params=params)

    def list_provider_leakage_snapshots(self, provider_id, headers, params=None):
        return self._request("GET", f"/referring-providers/{provider_id}/leakage-snapshots", headers=headers, params=params)

    def get_provider_leakage_report(self, provider_id, headers, params=None):
        return self._request("GET", f"/referring-providers/{provider_id}/leakage-report", headers=headers, params=params)

    # --- Specialist providers ---
    def create_specialist(self, payload, headers):
        return self._request("POST", "/specialty-providers", payload, headers)

    def list_specialists(self, headers, params=None):
        return self._request("GET", "/specialty-providers", headers=headers, params=params)

    def get_specialist(self, specialist_id, headers):
        return self._request("GET", f"/specialty-providers/{specialist_id}", headers=headers)

    def suspend_specialist(self, specialist_id, headers):
        return self._request("POST", f"/specialty-providers/{specialist_id}/suspend", headers=headers)

    def reactivate_specialist(self, specialist_id, headers):
        return self._request("POST", f"/specialty-providers/{specialist_id}/reactivate", headers=headers)

    def list_specialist_participations(self, specialist_id, headers, params=None):
        return self._request("GET", f"/specialty-providers/{specialist_id}/network-participations", headers=headers, params=params)

    def list_specialist_appointments(self, specialist_id, headers, params=None):
        return self._request("GET", f"/specialty-providers/{specialist_id}/appointments", headers=headers, params=params)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patient_referrals(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/referrals", headers=headers, params=params)

    # --- Insurance plans ---
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def list_insurance_plans(self, headers, params=None):
        return self._request("GET", "/insurance-plans", headers=headers, params=params)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    def retire_insurance_plan(self, plan_id, headers):
        return self._request("POST", f"/insurance-plans/{plan_id}/retire", headers=headers)

    # --- Network participation ---
    def create_participation(self, payload, headers):
        return self._request("POST", "/network-participations", payload, headers)

    def list_participations(self, headers, params=None):
        return self._request("GET", "/network-participations", headers=headers, params=params)

    def get_participation(self, participation_id, headers):
        return self._request("GET", f"/network-participations/{participation_id}", headers=headers)

    def terminate_participation(self, participation_id, headers):
        return self._request("POST", f"/network-participations/{participation_id}/terminate", headers=headers)

    # --- Prior auth rules ---
    def create_auth_rule(self, payload, headers):
        return self._request("POST", "/prior-auth-rules", payload, headers)

    def list_auth_rules(self, headers, params=None):
        return self._request("GET", "/prior-auth-rules", headers=headers, params=params)

    def get_auth_rule(self, rule_id, headers):
        return self._request("GET", f"/prior-auth-rules/{rule_id}", headers=headers)

    def retire_auth_rule(self, rule_id, headers):
        return self._request("POST", f"/prior-auth-rules/{rule_id}/retire", headers=headers)

    # --- Referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def request_info(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/request-info", payload, headers)

    def resubmit_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/resubmit", payload, headers)

    def reject_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/reject", payload, headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/accept", headers=headers)

    def auto_match(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/auto-match", headers=headers)

    def assign_specialist(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/assign-specialist", payload, headers)

    def document_patient_choice(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/document-patient-choice", payload, headers)

    def cancel_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/cancel", payload, headers)

    def submit_auth(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/auth/submit", headers=headers)

    def record_auth_outcome(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/auth/record-outcome", payload, headers)

    def book_appointment(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/appointments", payload, headers)

    def list_referral_appointments(self, referral_id, headers, params=None):
        return self._request("GET", f"/referrals/{referral_id}/appointments", headers=headers, params=params)

    def list_referral_authorization_records(self, referral_id, headers, params=None):
        return self._request("GET", f"/referrals/{referral_id}/authorization-records", headers=headers, params=params)

    def list_referral_consult_notes(self, referral_id, headers, params=None):
        return self._request("GET", f"/referrals/{referral_id}/consult-notes", headers=headers, params=params)

    def list_referral_loop_closures(self, referral_id, headers, params=None):
        return self._request("GET", f"/referrals/{referral_id}/loop-closures", headers=headers, params=params)

    def list_referral_leakage_records(self, referral_id, headers, params=None):
        return self._request("GET", f"/referrals/{referral_id}/leakage-records", headers=headers, params=params)

    def create_loop_closure(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/loop-closures", payload, headers)

    def run_aging_sweep(self, headers):
        return self._request("POST", "/referrals/aging-sweep", headers=headers)

    # --- Appointments ---
    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/confirm", payload, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", headers=headers)

    def mark_no_show(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/mark-no-show", headers=headers)

    def excuse_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/excuse", payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", headers=headers)

    def create_consult_note(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/consult-note", payload, headers)

    def list_appointment_consult_notes(self, appointment_id, headers, params=None):
        return self._request("GET", f"/appointments/{appointment_id}/consult-notes", headers=headers, params=params)

    def list_consult_notes(self, headers, params=None):
        return self._request("GET", "/consult-notes", headers=headers, params=params)

    def get_consult_note(self, note_id, headers):
        return self._request("GET", f"/consult-notes/{note_id}", headers=headers)

    # --- Analytics ---
    def close_period(self, payload, headers):
        return self._request("POST", "/analytics/periods/close", payload, headers)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", "/analytics/snapshots", headers=headers, params=params)


api_client = ApiClient()
