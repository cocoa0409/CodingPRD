"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock (PRD §2.4) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/api/programs/{program_id}", payload, headers)

    def pause_intake(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/pause-intake", {}, headers)

    def resume_intake(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/resume-intake", {}, headers)

    def run_promotion(self, program_id, payload, headers):
        return self._request("POST", f"/api/programs/{program_id}/promotion-runs", payload, headers)

    def daily_closeout(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/daily-closeout", {}, headers)

    def generate_outcome_report(self, program_id, payload, headers):
        return self._request("POST", f"/api/programs/{program_id}/outcome-reports", payload, headers)

    def list_program_outcome_reports(self, program_id, headers, params=None):
        return self._request("GET", f"/api/programs/{program_id}/outcome-reports", headers=headers, params=params)

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/api/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/api/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/api/participants/{participant_id}", headers=headers)

    def patch_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"/api/participants/{participant_id}", payload, headers)

    def submit_review(self, participant_id, headers):
        return self._request("POST", f"/api/participants/{participant_id}/submit-review", {}, headers)

    def approve_participant(self, participant_id, headers):
        return self._request("POST", f"/api/participants/{participant_id}/approve", {}, headers)

    def deny_participant(self, participant_id, payload, headers):
        return self._request("POST", f"/api/participants/{participant_id}/deny", payload, headers)

    def suspend_participant(self, participant_id, payload, headers):
        return self._request("POST", f"/api/participants/{participant_id}/suspend", payload, headers)

    def resume_participant(self, participant_id, headers):
        return self._request("POST", f"/api/participants/{participant_id}/resume", {}, headers)

    def disenroll_participant(self, participant_id, payload, headers):
        return self._request("POST", f"/api/participants/{participant_id}/disenroll", payload, headers)

    def reapply_participant(self, participant_id, headers):
        return self._request("POST", f"/api/participants/{participant_id}/reapply", {}, headers)

    # --- EmergencyContact ---
    def list_emergency_contacts(self, participant_id, headers, params=None):
        return self._request("GET", f"/api/participants/{participant_id}/emergency-contacts", headers=headers, params=params)

    def create_emergency_contact(self, participant_id, payload, headers):
        return self._request("POST", f"/api/participants/{participant_id}/emergency-contacts", payload, headers)

    def deactivate_emergency_contact(self, contact_id, headers):
        return self._request("POST", f"/api/emergency-contacts/{contact_id}/deactivate", {}, headers)

    def reactivate_emergency_contact(self, contact_id, headers):
        return self._request("POST", f"/api/emergency-contacts/{contact_id}/reactivate", {}, headers)

    # --- WaitlistEntry ---
    def list_participant_waitlist_entries(self, participant_id, headers, params=None):
        return self._request("GET", f"/api/participants/{participant_id}/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/api/waitlist-entries/{entry_id}", headers=headers)

    def accept_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/accept", {}, headers)

    def decline_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/decline", {}, headers)

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/withdraw", {}, headers)

    # --- CallSchedule ---
    def list_call_schedules(self, participant_id, headers, params=None):
        return self._request("GET", f"/api/participants/{participant_id}/call-schedules", headers=headers, params=params)

    def create_call_schedule(self, participant_id, payload, headers):
        return self._request("POST", f"/api/participants/{participant_id}/call-schedules", payload, headers)

    def pause_call_schedule(self, schedule_id, headers):
        return self._request("POST", f"/api/call-schedules/{schedule_id}/pause", {}, headers)

    def resume_call_schedule(self, schedule_id, headers):
        return self._request("POST", f"/api/call-schedules/{schedule_id}/resume", {}, headers)

    def archive_call_schedule(self, schedule_id, headers):
        return self._request("POST", f"/api/call-schedules/{schedule_id}/archive", {}, headers)

    # --- VolunteerCaller ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/api/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/api/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/api/volunteers/{volunteer_id}", headers=headers)

    def begin_training(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/begin-training", {}, headers)

    def certify_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/certify", {}, headers)

    def deactivate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/deactivate", {}, headers)

    def reactivate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/reactivate", {}, headers)

    def separate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/separate", {}, headers)

    # --- AvailabilityWindow ---
    def list_availability_windows(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/api/volunteers/{volunteer_id}/availability-windows", headers=headers, params=params)

    def create_availability_window(self, volunteer_id, payload, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/availability-windows", payload, headers)

    def delete_availability_window(self, window_id, headers):
        return self._request("DELETE", f"/api/availability-windows/{window_id}", headers=headers)

    # --- TrainingRecord ---
    def list_training_records(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/api/volunteers/{volunteer_id}/training-records", headers=headers, params=params)

    def create_training_record(self, volunteer_id, payload, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/training-records", payload, headers)

    # --- ConfidentialityAgreement ---
    def list_confidentiality_agreements(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/api/volunteers/{volunteer_id}/confidentiality-agreements", headers=headers, params=params)

    def sign_confidentiality_agreement(self, volunteer_id, payload, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/confidentiality-agreements", payload, headers)

    def revoke_confidentiality_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/confidentiality-agreements/{agreement_id}/revoke", {}, headers)

    # --- CallAssignment ---
    def list_call_assignments(self, headers, params=None):
        return self._request("GET", "/api/call-assignments", headers=headers, params=params)

    def create_call_assignment(self, payload, headers):
        return self._request("POST", "/api/call-assignments", payload, headers)

    def get_call_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/call-assignments/{assignment_id}", headers=headers)

    def cancel_call_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/call-assignments/{assignment_id}/cancel", {}, headers)

    def reschedule_call_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/call-assignments/{assignment_id}/reschedule", payload, headers)

    # --- CallLog ---
    def list_call_logs(self, assignment_id, headers, params=None):
        return self._request("GET", f"/api/call-assignments/{assignment_id}/call-logs", headers=headers, params=params)

    def create_call_log(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/call-assignments/{assignment_id}/call-logs", payload, headers)

    # --- EscalationCase ---
    def list_escalations(self, headers, params=None):
        return self._request("GET", "/api/escalations", headers=headers, params=params)

    def create_escalation(self, payload, headers):
        return self._request("POST", "/api/escalations", payload, headers)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/api/escalations/{escalation_id}", headers=headers)

    def advance_escalation(self, escalation_id, headers):
        return self._request("POST", f"/api/escalations/{escalation_id}/advance", {}, headers)

    def record_contact_attempt(self, escalation_id, payload, headers):
        return self._request("POST", f"/api/escalations/{escalation_id}/record-contact-attempt", payload, headers)

    def resolve_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/api/escalations/{escalation_id}/resolve", payload, headers)

    # --- WelfareCheckRequest ---
    def list_escalation_welfare_checks(self, escalation_id, headers, params=None):
        return self._request("GET", f"/api/escalations/{escalation_id}/welfare-checks", headers=headers, params=params)

    def list_welfare_checks(self, headers, params=None):
        return self._request("GET", "/api/welfare-checks", headers=headers, params=params)

    def get_welfare_check(self, check_id, headers):
        return self._request("GET", f"/api/welfare-checks/{check_id}", headers=headers)

    def dispatch_welfare_check(self, check_id, headers):
        return self._request("POST", f"/api/welfare-checks/{check_id}/dispatch", {}, headers)

    def complete_welfare_check(self, check_id, payload, headers):
        return self._request("POST", f"/api/welfare-checks/{check_id}/complete", payload, headers)

    def decline_welfare_check(self, check_id, payload, headers):
        return self._request("POST", f"/api/welfare-checks/{check_id}/decline", payload, headers)

    # --- ServiceReferral ---
    def list_service_referrals(self, headers, params=None):
        return self._request("GET", "/api/service-referrals", headers=headers, params=params)

    def create_service_referral(self, payload, headers):
        return self._request("POST", "/api/service-referrals", payload, headers)

    def get_service_referral(self, referral_id, headers):
        return self._request("GET", f"/api/service-referrals/{referral_id}", headers=headers)

    def submit_service_referral(self, referral_id, headers):
        return self._request("POST", f"/api/service-referrals/{referral_id}/submit", {}, headers)

    def accept_service_referral(self, referral_id, headers):
        return self._request("POST", f"/api/service-referrals/{referral_id}/accept", {}, headers)

    def decline_service_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/api/service-referrals/{referral_id}/decline", payload, headers)

    def revise_service_referral(self, referral_id, headers):
        return self._request("POST", f"/api/service-referrals/{referral_id}/revise", {}, headers)

    def withdraw_service_referral(self, referral_id, headers):
        return self._request("POST", f"/api/service-referrals/{referral_id}/withdraw", {}, headers)

    def close_service_referral(self, referral_id, headers):
        return self._request("POST", f"/api/service-referrals/{referral_id}/close", {}, headers)

    # --- SatisfactionSurvey ---
    def list_satisfaction_surveys(self, participant_id, headers, params=None):
        return self._request("GET", f"/api/participants/{participant_id}/satisfaction-surveys", headers=headers, params=params)

    def issue_satisfaction_survey(self, participant_id, payload, headers):
        return self._request("POST", f"/api/participants/{participant_id}/satisfaction-surveys", payload, headers)

    def get_satisfaction_survey(self, survey_id, headers):
        return self._request("GET", f"/api/satisfaction-surveys/{survey_id}", headers=headers)

    def return_satisfaction_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/api/satisfaction-surveys/{survey_id}/return", payload, headers)

    # --- OutcomeReport ---
    def get_outcome_report(self, report_id, headers):
        return self._request("GET", f"/api/outcome-reports/{report_id}", headers=headers)

    def finalize_outcome_report(self, report_id, headers):
        return self._request("POST", f"/api/outcome-reports/{report_id}/finalize", {}, headers)


api_client = ApiClient()
