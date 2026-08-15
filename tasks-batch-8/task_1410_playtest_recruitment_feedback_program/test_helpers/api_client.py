"""API client: one method per endpoint defined in the PRD (§4 table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock + expiry sweep (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/playtests/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_expiry_sweep(self, headers):
        return self._request("POST", "/playtests/_sweeps/run-expiry", {}, headers)

    # ------------------------------------------------------------------
    # Participants (PRD §3.1)
    # ------------------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/playtests/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/playtests/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/playtests/participants/{participant_id}", headers=headers)

    def activate_participant(self, participant_id, headers):
        return self._request("POST", f"/playtests/participants/{participant_id}/activate", {}, headers)

    def verify_participant_attributes(self, participant_id, verified_platform_tags, headers):
        return self._request("POST", f"/playtests/participants/{participant_id}/verify-attributes",
                             {"verified_platform_tags": verified_platform_tags}, headers)

    def suspend_participant(self, participant_id, headers):
        return self._request("POST", f"/playtests/participants/{participant_id}/suspend", {}, headers)

    def reinstate_participant(self, participant_id, headers):
        return self._request("POST", f"/playtests/participants/{participant_id}/reinstate", {}, headers)

    def ban_participant(self, participant_id, headers):
        return self._request("POST", f"/playtests/participants/{participant_id}/ban", {}, headers)

    # ------------------------------------------------------------------
    # Moderators (PRD §3.1)
    # ------------------------------------------------------------------
    def create_moderator(self, payload, headers):
        return self._request("POST", "/playtests/moderators", payload, headers)

    def list_moderators(self, headers, params=None):
        return self._request("GET", "/playtests/moderators", headers=headers, params=params)

    def get_moderator(self, moderator_id, headers):
        return self._request("GET", f"/playtests/moderators/{moderator_id}", headers=headers)

    def update_moderator(self, moderator_id, payload, headers):
        return self._request("PATCH", f"/playtests/moderators/{moderator_id}", payload, headers)

    # ------------------------------------------------------------------
    # Studies (PRD §3.1)
    # ------------------------------------------------------------------
    def create_study(self, payload, headers):
        return self._request("POST", "/playtests/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/playtests/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/playtests/studies/{study_id}", headers=headers)

    def amend_study(self, study_id, payload, headers):
        return self._request("PATCH", f"/playtests/studies/{study_id}", payload, headers)

    def open_recruitment(self, study_id, headers):
        return self._request("POST", f"/playtests/studies/{study_id}/open-recruitment", {}, headers)

    def close_recruitment(self, study_id, headers):
        return self._request("POST", f"/playtests/studies/{study_id}/close-recruitment", {}, headers)

    def begin_analysis(self, study_id, headers):
        return self._request("POST", f"/playtests/studies/{study_id}/begin-analysis", {}, headers)

    def complete_study(self, study_id, headers):
        return self._request("POST", f"/playtests/studies/{study_id}/complete", {}, headers)

    def get_cohort_summary(self, study_id, headers):
        return self._request("GET", f"/playtests/studies/{study_id}/cohort-summary", headers=headers)

    # ------------------------------------------------------------------
    # Screening applications (PRD §3.2)
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/playtests/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/playtests/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/playtests/applications/{application_id}", headers=headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/playtests/applications/{application_id}/start-review", {}, headers)

    def request_app_info(self, application_id, info_request_note, headers):
        return self._request("POST", f"/playtests/applications/{application_id}/request-info",
                             {"info_request_note": info_request_note}, headers)

    def submit_app_info(self, application_id, headers, supplemental_note=None):
        payload = {} if supplemental_note is None else {"supplemental_note": supplemental_note}
        return self._request("POST", f"/playtests/applications/{application_id}/submit-info",
                             payload, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/playtests/applications/{application_id}/approve", {}, headers)

    def reject_application(self, application_id, decision_reason, headers):
        return self._request("POST", f"/playtests/applications/{application_id}/reject",
                             {"decision_reason": decision_reason}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/playtests/applications/{application_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # NDA agreements & signatures (PRD §3.3)
    # ------------------------------------------------------------------
    def create_nda_agreement(self, payload, headers):
        return self._request("POST", "/playtests/nda-agreements", payload, headers)

    def list_nda_agreements(self, headers, params=None):
        return self._request("GET", "/playtests/nda-agreements", headers=headers, params=params)

    def get_nda_agreement(self, agreement_id, headers):
        return self._request("GET", f"/playtests/nda-agreements/{agreement_id}", headers=headers)

    def publish_nda_agreement(self, agreement_id, headers):
        return self._request("POST", f"/playtests/nda-agreements/{agreement_id}/publish", {}, headers)

    def list_nda_signatures(self, headers, params=None):
        return self._request("GET", "/playtests/nda-signatures", headers=headers, params=params)

    def get_nda_signature(self, signature_id, headers):
        return self._request("GET", f"/playtests/nda-signatures/{signature_id}", headers=headers)

    def sign_nda_signature(self, signature_id, headers):
        return self._request("POST", f"/playtests/nda-signatures/{signature_id}/sign", {}, headers)

    # ------------------------------------------------------------------
    # Builds & access keys (PRD §3.4)
    # ------------------------------------------------------------------
    def create_build(self, payload, headers):
        return self._request("POST", "/playtests/builds", payload, headers)

    def list_builds(self, headers, params=None):
        return self._request("GET", "/playtests/builds", headers=headers, params=params)

    def get_build(self, build_id, headers):
        return self._request("GET", f"/playtests/builds/{build_id}", headers=headers)

    def release_build(self, build_id, headers):
        return self._request("POST", f"/playtests/builds/{build_id}/release", {}, headers)

    def retire_build(self, build_id, headers):
        return self._request("POST", f"/playtests/builds/{build_id}/retire", {}, headers)

    def create_access_key(self, payload, headers):
        return self._request("POST", "/playtests/access-keys", payload, headers)

    def list_access_keys(self, headers, params=None):
        return self._request("GET", "/playtests/access-keys", headers=headers, params=params)

    def get_access_key(self, key_id, headers):
        return self._request("GET", f"/playtests/access-keys/{key_id}", headers=headers)

    def redeem_access_key(self, key_id, headers):
        return self._request("POST", f"/playtests/access-keys/{key_id}/redeem", {}, headers)

    def revoke_access_key(self, key_id, headers):
        return self._request("POST", f"/playtests/access-keys/{key_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Lab stations (PRD §3.1)
    # ------------------------------------------------------------------
    def create_lab_station(self, payload, headers):
        return self._request("POST", "/playtests/lab-stations", payload, headers)

    def list_lab_stations(self, headers, params=None):
        return self._request("GET", "/playtests/lab-stations", headers=headers, params=params)

    def get_lab_station(self, station_id, headers):
        return self._request("GET", f"/playtests/lab-stations/{station_id}", headers=headers)

    def update_lab_station(self, station_id, payload, headers):
        return self._request("PATCH", f"/playtests/lab-stations/{station_id}", payload, headers)

    # ------------------------------------------------------------------
    # Playtest sessions (PRD §3.5)
    # ------------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/playtests/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/playtests/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/playtests/sessions/{session_id}", headers=headers)

    def assign_moderator(self, session_id, moderator_id, headers):
        return self._request("POST", f"/playtests/sessions/{session_id}/assign-moderator",
                             {"moderator_id": moderator_id}, headers)

    def reschedule_session(self, session_id, payload, headers):
        return self._request("PATCH", f"/playtests/sessions/{session_id}/reschedule", payload, headers)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/playtests/sessions/{session_id}/start", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/playtests/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/playtests/sessions/{session_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Session bookings (PRD §3.5)
    # ------------------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/playtests/session-bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/playtests/session-bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/playtests/session-bookings/{booking_id}", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/playtests/session-bookings/{booking_id}/cancel", {}, headers)

    def mark_booking_attended(self, booking_id, headers):
        return self._request("POST", f"/playtests/session-bookings/{booking_id}/mark-attended", {}, headers)

    def mark_booking_no_show(self, booking_id, headers):
        return self._request("POST", f"/playtests/session-bookings/{booking_id}/mark-no-show", {}, headers)

    # ------------------------------------------------------------------
    # Survey instruments & responses (PRD §3.6)
    # ------------------------------------------------------------------
    def create_survey_instrument(self, payload, headers):
        return self._request("POST", "/playtests/survey-instruments", payload, headers)

    def list_survey_instruments(self, headers, params=None):
        return self._request("GET", "/playtests/survey-instruments", headers=headers, params=params)

    def get_survey_instrument(self, instrument_id, headers):
        return self._request("GET", f"/playtests/survey-instruments/{instrument_id}", headers=headers)

    def publish_survey_instrument(self, instrument_id, headers):
        return self._request("POST", f"/playtests/survey-instruments/{instrument_id}/publish", {}, headers)

    def retire_survey_instrument(self, instrument_id, headers):
        return self._request("POST", f"/playtests/survey-instruments/{instrument_id}/retire", {}, headers)

    def create_survey_response(self, payload, headers):
        return self._request("POST", "/playtests/survey-responses", payload, headers)

    def list_survey_responses(self, headers, params=None):
        return self._request("GET", "/playtests/survey-responses", headers=headers, params=params)

    def get_survey_response(self, response_id, headers):
        return self._request("GET", f"/playtests/survey-responses/{response_id}", headers=headers)

    def submit_survey_response(self, response_id, headers):
        return self._request("POST", f"/playtests/survey-responses/{response_id}/submit", {}, headers)

    # ------------------------------------------------------------------
    # Feedback tickets (PRD §3.7)
    # ------------------------------------------------------------------
    def create_feedback_ticket(self, payload, headers):
        return self._request("POST", "/playtests/feedback-tickets", payload, headers)

    def list_feedback_tickets(self, headers, params=None):
        return self._request("GET", "/playtests/feedback-tickets", headers=headers, params=params)

    def get_feedback_ticket(self, ticket_id, headers):
        return self._request("GET", f"/playtests/feedback-tickets/{ticket_id}", headers=headers)

    def triage_feedback_ticket(self, ticket_id, headers):
        return self._request("POST", f"/playtests/feedback-tickets/{ticket_id}/triage", {}, headers)

    def request_ticket_info(self, ticket_id, headers):
        return self._request("POST", f"/playtests/feedback-tickets/{ticket_id}/request-info", {}, headers)

    def route_feedback_ticket(self, ticket_id, backlog_target, headers):
        return self._request("POST", f"/playtests/feedback-tickets/{ticket_id}/route",
                             {"backlog_target": backlog_target}, headers)

    def resolve_feedback_ticket(self, ticket_id, headers):
        return self._request("POST", f"/playtests/feedback-tickets/{ticket_id}/resolve", {}, headers)

    def mark_ticket_wont_fix(self, ticket_id, headers):
        return self._request("POST", f"/playtests/feedback-tickets/{ticket_id}/mark-wont-fix", {}, headers)

    # ------------------------------------------------------------------
    # Incentive payouts (PRD §3.8)
    # ------------------------------------------------------------------
    def create_incentive_payout(self, payload, headers):
        return self._request("POST", "/playtests/incentive-payouts", payload, headers)

    def list_incentive_payouts(self, headers, params=None):
        return self._request("GET", "/playtests/incentive-payouts", headers=headers, params=params)

    def get_incentive_payout(self, payout_id, headers):
        return self._request("GET", f"/playtests/incentive-payouts/{payout_id}", headers=headers)

    def submit_payout(self, payout_id, headers):
        return self._request("POST", f"/playtests/incentive-payouts/{payout_id}/submit", {}, headers)

    def approve_payout(self, payout_id, headers):
        return self._request("POST", f"/playtests/incentive-payouts/{payout_id}/approve", {}, headers)

    def reject_payout(self, payout_id, rejection_reason, headers):
        return self._request("POST", f"/playtests/incentive-payouts/{payout_id}/reject",
                             {"rejection_reason": rejection_reason}, headers)

    def resubmit_payout(self, payout_id, headers):
        return self._request("POST", f"/playtests/incentive-payouts/{payout_id}/resubmit", {}, headers)

    def issue_payout(self, payout_id, headers):
        return self._request("POST", f"/playtests/incentive-payouts/{payout_id}/issue", {}, headers)

    # ------------------------------------------------------------------
    # Breach cases (PRD §3.9)
    # ------------------------------------------------------------------
    def create_breach_case(self, payload, headers):
        return self._request("POST", "/playtests/breach-cases", payload, headers)

    def list_breach_cases(self, headers, params=None):
        return self._request("GET", "/playtests/breach-cases", headers=headers, params=params)

    def get_breach_case(self, case_id, headers):
        return self._request("GET", f"/playtests/breach-cases/{case_id}", headers=headers)

    def open_investigation(self, case_id, headers):
        return self._request("POST", f"/playtests/breach-cases/{case_id}/open-investigation", {}, headers)

    def substantiate_breach_case(self, case_id, headers):
        return self._request("POST", f"/playtests/breach-cases/{case_id}/substantiate", {}, headers)

    def dismiss_breach_case(self, case_id, headers):
        return self._request("POST", f"/playtests/breach-cases/{case_id}/dismiss", {}, headers)

    def sanction_breach_case(self, case_id, sanction_type, headers, sanction_note=None):
        payload = {"sanction_type": sanction_type}
        if sanction_note is not None:
            payload["sanction_note"] = sanction_note
        return self._request("POST", f"/playtests/breach-cases/{case_id}/sanction", payload, headers)

    # ------------------------------------------------------------------
    # Exposure journal (PRD §2.5)
    # ------------------------------------------------------------------
    def list_exposure_records(self, headers, params=None):
        return self._request("GET", "/playtests/exposure-records", headers=headers, params=params)

    def get_exposure_record(self, record_id, headers):
        return self._request("GET", f"/playtests/exposure-records/{record_id}", headers=headers)


api_client = ApiClient()
