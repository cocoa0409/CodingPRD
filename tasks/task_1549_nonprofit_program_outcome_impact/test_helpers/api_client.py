"""API client: one method per endpoint defined in the PRD section 4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- programs ----------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", {}, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/resume", {}, headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/archive", {}, headers)

    def consent_form_bump(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/consent-form-bump", {}, headers)

    # ---------------- funders ----------------
    def create_funder(self, payload, headers):
        return self._request("POST", "/funders", payload, headers)

    def list_funders(self, headers, params=None):
        return self._request("GET", "/funders", headers=headers, params=params)

    def get_funder(self, funder_id, headers):
        return self._request("GET", f"/funders/{funder_id}", headers=headers)

    def deactivate_funder(self, funder_id, headers):
        return self._request("POST", f"/funders/{funder_id}/deactivate", {}, headers)

    def reactivate_funder(self, funder_id, headers):
        return self._request("POST", f"/funders/{funder_id}/reactivate", {}, headers)

    # ---------------- logic models & indicators ----------------
    def create_logic_model(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/logic-models", payload, headers)

    def list_logic_models(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/logic-models", headers=headers, params=params)

    def get_logic_model(self, model_id, headers):
        return self._request("GET", f"/logic-models/{model_id}", headers=headers)

    def submit_logic_model(self, model_id, headers):
        return self._request("POST", f"/logic-models/{model_id}/submit", {}, headers)

    def approve_logic_model(self, model_id, payload, headers):
        return self._request("POST", f"/logic-models/{model_id}/approve", payload, headers)

    def reject_logic_model(self, model_id, payload, headers):
        return self._request("POST", f"/logic-models/{model_id}/reject", payload, headers)

    def revise_logic_model(self, model_id, headers):
        return self._request("POST", f"/logic-models/{model_id}/revise", {}, headers)

    def list_indicators(self, model_id, headers, params=None):
        return self._request("GET", f"/logic-models/{model_id}/indicators", headers=headers, params=params)

    def create_indicator(self, model_id, payload, headers):
        return self._request("POST", f"/logic-models/{model_id}/indicators", payload, headers)

    def get_indicator(self, indicator_id, headers):
        return self._request("GET", f"/indicators/{indicator_id}", headers=headers)

    def patch_indicator(self, indicator_id, payload, headers):
        return self._request("PATCH", f"/indicators/{indicator_id}", payload, headers)

    def retire_indicator(self, indicator_id, headers):
        return self._request("POST", f"/indicators/{indicator_id}/retire", {}, headers)

    def get_indicator_attainment(self, indicator_id, headers, params=None):
        return self._request("GET", f"/indicators/{indicator_id}/attainment", headers=headers, params=params)

    # ---------------- program cycles ----------------
    def create_cycle(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/cycles", payload, headers)

    def list_program_cycles(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/cycles", headers=headers, params=params)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def open_enrollment(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/open-enrollment", {}, headers)

    def revert_setup(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/revert-setup", {}, headers)

    def activate_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/activate", {}, headers)

    def close_data(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/close-data", {}, headers)

    def reopen_data(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/reopen-data", {}, headers)

    def begin_review(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/begin-review", {}, headers)

    def mark_reported(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/mark-reported", {}, headers)

    def archive_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/archive", {}, headers)

    def evaluate_milestones(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/evaluate-milestones", {}, headers)

    def list_participants(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cycles/{cycle_id}/participants", headers=headers, params=params)

    def list_cycle_observations(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cycles/{cycle_id}/observations", headers=headers, params=params)

    def list_cycle_milestones(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cycles/{cycle_id}/milestones", headers=headers, params=params)

    def list_cycle_audits(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cycles/{cycle_id}/audits", headers=headers, params=params)

    def list_cycle_reports(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cycles/{cycle_id}/reports", headers=headers, params=params)

    def get_dashboard(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}/dashboard", headers=headers)

    # ---------------- participants & consents ----------------
    def enroll_participant(self, cycle_id, payload, headers):
        return self._request("POST", f"/cycles/{cycle_id}/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def exit_participant(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/exit", payload, headers)

    def re_enroll_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/re-enroll", {}, headers)

    def list_consents(self, participant_id, headers, params=None):
        return self._request("GET", f"/participants/{participant_id}/consents", headers=headers, params=params)

    def list_participant_observations(self, participant_id, headers, params=None):
        return self._request("GET", f"/participants/{participant_id}/observations", headers=headers, params=params)

    def list_participant_findings(self, participant_id, headers, params=None):
        return self._request("GET", f"/participants/{participant_id}/findings", headers=headers, params=params)

    def grant_consent(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/consents", payload, headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consents/{consent_id}/revoke", {}, headers)

    # ---------------- instruments & certifications ----------------
    def create_instrument(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/instruments", payload, headers)

    def list_instruments(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/instruments/{instrument_id}", headers=headers)

    def publish_instrument(self, instrument_id, headers):
        return self._request("POST", f"/instruments/{instrument_id}/publish", {}, headers)

    def new_revision_instrument(self, instrument_id, headers):
        return self._request("POST", f"/instruments/{instrument_id}/new-revision", {}, headers)

    def retire_instrument(self, instrument_id, headers):
        return self._request("POST", f"/instruments/{instrument_id}/retire", {}, headers)

    def list_instrument_observations(self, instrument_id, headers, params=None):
        return self._request("GET", f"/instruments/{instrument_id}/observations", headers=headers, params=params)

    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/certifications/{certification_id}", headers=headers)

    def suspend_certification(self, certification_id, headers):
        return self._request("POST", f"/certifications/{certification_id}/suspend", {}, headers)

    def reinstate_certification(self, certification_id, headers):
        return self._request("POST", f"/certifications/{certification_id}/reinstate", {}, headers)

    # ---------------- observations ----------------
    def record_observation(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/observations", payload, headers)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/observations", headers=headers, params=params)

    def validate_observation(self, observation_id, headers):
        return self._request("POST", f"/observations/{observation_id}/validate", {}, headers)

    def flag_observation(self, observation_id, payload, headers):
        return self._request("POST", f"/observations/{observation_id}/flag", payload, headers)

    def exclude_observation(self, observation_id, payload, headers):
        return self._request("POST", f"/observations/{observation_id}/exclude", payload, headers)

    # ---------------- milestones ----------------
    def create_milestone(self, cycle_id, payload, headers):
        return self._request("POST", f"/cycles/{cycle_id}/milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/milestones/{milestone_id}", headers=headers)

    def list_indicator_milestones(self, indicator_id, headers, params=None):
        return self._request("GET", f"/indicators/{indicator_id}/milestones", headers=headers, params=params)

    # ---------------- data quality audits & findings ----------------
    def open_audit(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/audits", {}, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/close", {}, headers)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request("GET", f"/audits/{audit_id}/findings", headers=headers, params=params)

    def record_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/findings", payload, headers)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def waive_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/waive", payload, headers)

    def remediate_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/remediate", payload, headers)

    # ---------------- reports ----------------
    def create_report(self, cycle_id, payload, headers):
        return self._request("POST", f"/cycles/{cycle_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def generate_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/generate", {}, headers)

    def deliver_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/deliver", {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/accept", {}, headers)

    def return_report(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/return", payload, headers)

    def regenerate_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/regenerate", {}, headers)

    # ---------------- vendor engagements ----------------
    def create_engagement(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/vendor-engagements", payload, headers)

    def list_engagements(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/vendor-engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/vendor-engagements/{engagement_id}", headers=headers)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/vendor-engagements/{engagement_id}/activate", {}, headers)

    def complete_engagement(self, engagement_id, headers):
        return self._request("POST", f"/vendor-engagements/{engagement_id}/complete", {}, headers)

    def terminate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/vendor-engagements/{engagement_id}/terminate", {}, headers)

    def submit_deliverable(self, engagement_id, payload, headers):
        return self._request("POST", f"/vendor-engagements/{engagement_id}/submit-deliverable", payload, headers)

    # ---------------- improvement actions ----------------
    def create_improvement_action(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/improvement-actions", payload, headers)

    def list_program_improvement_actions(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/improvement-actions", headers=headers, params=params)

    def get_improvement_action(self, action_id, headers):
        return self._request("GET", f"/improvement-actions/{action_id}", headers=headers)

    def list_improvement_actions(self, headers, params=None):
        return self._request("GET", "/improvement-actions", headers=headers, params=params)

    def approve_improvement_action(self, action_id, headers):
        return self._request("POST", f"/improvement-actions/{action_id}/approve", {}, headers)

    def start_improvement_action(self, action_id, headers):
        return self._request("POST", f"/improvement-actions/{action_id}/start", {}, headers)

    def implement_improvement_action(self, action_id, headers):
        return self._request("POST", f"/improvement-actions/{action_id}/implement", {}, headers)

    def verify_improvement_action(self, action_id, payload, headers):
        return self._request("POST", f"/improvement-actions/{action_id}/verify", payload, headers)

    def reopen_improvement_action(self, action_id, headers):
        return self._request("POST", f"/improvement-actions/{action_id}/reopen", {}, headers)


api_client = ApiClient()
