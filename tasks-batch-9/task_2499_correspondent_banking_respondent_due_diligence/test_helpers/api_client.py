"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/correspondent-banking"


class ApiClient(GenericApiClient):
    # --- jurisdiction profiles ---
    def create_jurisdiction_profile(self, payload, headers):
        return self._request("POST", f"{P}/jurisdiction-profiles", payload, headers)

    def list_jurisdiction_profiles(self, headers, params=None):
        return self._request("GET", f"{P}/jurisdiction-profiles", headers=headers, params=params)

    def get_jurisdiction_profile(self, jurisdiction_profile_id, headers):
        return self._request(
            "GET", f"{P}/jurisdiction-profiles/{jurisdiction_profile_id}", headers=headers
        )

    def amend_jurisdiction_profile(self, jurisdiction_profile_id, payload, headers):
        return self._request(
            "PATCH", f"{P}/jurisdiction-profiles/{jurisdiction_profile_id}", payload, headers
        )

    # --- respondent banks ---
    def create_respondent(self, payload, headers):
        return self._request("POST", f"{P}/respondents", payload, headers)

    def list_respondents(self, headers, params=None):
        return self._request("GET", f"{P}/respondents", headers=headers, params=params)

    def get_respondent(self, respondent_id, headers):
        return self._request("GET", f"{P}/respondents/{respondent_id}", headers=headers)

    def amend_respondent(self, respondent_id, payload, headers):
        return self._request("PATCH", f"{P}/respondents/{respondent_id}", payload, headers)

    def verify_licensing(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/licensing-verification", payload, headers
        )

    def assess_risk(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/risk-assessment", payload, headers
        )

    def decide_committee(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/approval", payload, headers
        )

    def restrict_respondent(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/restriction", payload, headers
        )

    # --- beneficial owners ---
    def create_beneficial_owner(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/beneficial-owners", payload, headers
        )

    def list_beneficial_owners(self, headers, params=None):
        return self._request("GET", f"{P}/beneficial-owners", headers=headers, params=params)

    def get_beneficial_owner(self, beneficial_owner_id, headers):
        return self._request(
            "GET", f"{P}/beneficial-owners/{beneficial_owner_id}", headers=headers
        )

    def verify_owner(self, beneficial_owner_id, payload, headers):
        return self._request(
            "POST", f"{P}/beneficial-owners/{beneficial_owner_id}/verification", payload, headers
        )

    # --- questionnaires + control assessments ---
    def create_questionnaire(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/questionnaires", payload, headers
        )

    def list_questionnaires(self, headers, params=None):
        return self._request("GET", f"{P}/questionnaires", headers=headers, params=params)

    def get_questionnaire(self, questionnaire_id, headers):
        return self._request("GET", f"{P}/questionnaires/{questionnaire_id}", headers=headers)

    def submit_questionnaire(self, questionnaire_id, payload, headers):
        return self._request(
            "POST", f"{P}/questionnaires/{questionnaire_id}/submission", payload, headers
        )

    def decide_assessment(self, questionnaire_id, payload, headers):
        return self._request(
            "POST", f"{P}/questionnaires/{questionnaire_id}/assessment-decision", payload, headers
        )

    def create_control_assessment(self, questionnaire_id, payload, headers):
        return self._request(
            "POST", f"{P}/questionnaires/{questionnaire_id}/control-assessments", payload, headers
        )

    def list_control_assessments(self, headers, params=None):
        return self._request("GET", f"{P}/control-assessments", headers=headers, params=params)

    def get_control_assessment(self, control_assessment_id, headers):
        return self._request(
            "GET", f"{P}/control-assessments/{control_assessment_id}", headers=headers
        )

    def overlay_control_assessment(self, control_assessment_id, payload, headers):
        return self._request(
            "PATCH", f"{P}/control-assessments/{control_assessment_id}", payload, headers
        )

    # --- nested relationships ---
    def create_nested_relationship(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/nested-relationships", payload, headers
        )

    def list_nested_relationships(self, headers, params=None):
        return self._request("GET", f"{P}/nested-relationships", headers=headers, params=params)

    def get_nested_relationship(self, nested_relationship_id, headers):
        return self._request(
            "GET", f"{P}/nested-relationships/{nested_relationship_id}", headers=headers
        )

    def get_nested_chain(self, respondent_id, headers, params=None):
        return self._request(
            "GET", f"{P}/respondents/{respondent_id}/nested-chain", headers=headers, params=params
        )

    def adjudicate_nested(self, nested_relationship_id, payload, headers):
        return self._request(
            "POST",
            f"{P}/nested-relationships/{nested_relationship_id}/adjudication",
            payload,
            headers,
        )

    # --- monitoring profiles, calibration, observations ---
    def create_monitoring_profile(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/monitoring-profiles", payload, headers
        )

    def list_monitoring_profiles(self, headers, params=None):
        return self._request("GET", f"{P}/monitoring-profiles", headers=headers, params=params)

    def get_monitoring_profile(self, monitoring_profile_id, headers):
        return self._request(
            "GET", f"{P}/monitoring-profiles/{monitoring_profile_id}", headers=headers
        )

    def calibrate_profile(self, monitoring_profile_id, payload, headers):
        return self._request(
            "POST", f"{P}/monitoring-profiles/{monitoring_profile_id}/calibration", payload, headers
        )

    def create_observation(self, monitoring_profile_id, payload, headers):
        return self._request(
            "POST",
            f"{P}/monitoring-profiles/{monitoring_profile_id}/observations",
            payload,
            headers,
        )

    def list_activity_observations(self, headers, params=None):
        return self._request("GET", f"{P}/activity-observations", headers=headers, params=params)

    def get_activity_observation(self, activity_observation_id, headers):
        return self._request(
            "GET", f"{P}/activity-observations/{activity_observation_id}", headers=headers
        )

    # --- monitoring alerts ---
    def create_monitoring_alert(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/monitoring-alerts", payload, headers
        )

    def list_monitoring_alerts(self, headers, params=None):
        return self._request("GET", f"{P}/monitoring-alerts", headers=headers, params=params)

    def get_monitoring_alert(self, monitoring_alert_id, headers):
        return self._request(
            "GET", f"{P}/monitoring-alerts/{monitoring_alert_id}", headers=headers
        )

    def dispose_alert(self, monitoring_alert_id, payload, headers):
        return self._request(
            "POST", f"{P}/monitoring-alerts/{monitoring_alert_id}/disposition", payload, headers
        )

    # --- information requests ---
    def create_information_request(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/information-requests", payload, headers
        )

    def list_information_requests(self, headers, params=None):
        return self._request("GET", f"{P}/information-requests", headers=headers, params=params)

    def get_information_request(self, information_request_id, headers):
        return self._request(
            "GET", f"{P}/information-requests/{information_request_id}", headers=headers
        )

    def dispatch_request(self, information_request_id, payload, headers):
        return self._request(
            "POST", f"{P}/information-requests/{information_request_id}/dispatch", payload, headers
        )

    def respond_request(self, information_request_id, payload, headers):
        return self._request(
            "POST", f"{P}/information-requests/{information_request_id}/response", payload, headers
        )

    def mark_overdue(self, information_request_id, payload, headers):
        return self._request(
            "POST",
            f"{P}/information-requests/{information_request_id}/overdue-marking",
            payload,
            headers,
        )

    def adjudicate_request(self, information_request_id, payload, headers):
        return self._request(
            "POST",
            f"{P}/information-requests/{information_request_id}/adjudication",
            payload,
            headers,
        )

    # --- adverse media ---
    def create_adverse_media_event(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/adverse-media-events", payload, headers
        )

    def list_adverse_media_events(self, headers, params=None):
        return self._request("GET", f"{P}/adverse-media-events", headers=headers, params=params)

    def get_adverse_media_event(self, adverse_media_event_id, headers):
        return self._request(
            "GET", f"{P}/adverse-media-events/{adverse_media_event_id}", headers=headers
        )

    def triage_media(self, adverse_media_event_id, payload, headers):
        return self._request(
            "POST", f"{P}/adverse-media-events/{adverse_media_event_id}/triage", payload, headers
        )

    # --- periodic refreshes + sweep ---
    def create_periodic_refresh(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/periodic-refreshes", payload, headers
        )

    def list_periodic_refreshes(self, headers, params=None):
        return self._request("GET", f"{P}/periodic-refreshes", headers=headers, params=params)

    def get_periodic_refresh(self, periodic_refresh_id, headers):
        return self._request(
            "GET", f"{P}/periodic-refreshes/{periodic_refresh_id}", headers=headers
        )

    def progress_refresh(self, periodic_refresh_id, payload, headers):
        return self._request(
            "POST", f"{P}/periodic-refreshes/{periodic_refresh_id}/progression", payload, headers
        )

    def run_sweep(self, payload, headers):
        return self._request("POST", f"{P}/refresh-sweeps", payload, headers)

    # --- payment instructions ---
    def create_payment_instruction(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/payment-instructions", payload, headers
        )

    def list_payment_instructions(self, headers, params=None):
        return self._request("GET", f"{P}/payment-instructions", headers=headers, params=params)

    def get_payment_instruction(self, payment_instruction_id, headers):
        return self._request(
            "GET", f"{P}/payment-instructions/{payment_instruction_id}", headers=headers
        )

    def decide_screening(self, payment_instruction_id, payload, headers):
        return self._request(
            "POST",
            f"{P}/payment-instructions/{payment_instruction_id}/screening-decision",
            payload,
            headers,
        )

    # --- closure plans ---
    def create_closure_plan(self, respondent_id, payload, headers):
        return self._request(
            "POST", f"{P}/respondents/{respondent_id}/closure-plans", payload, headers
        )

    def list_closure_plans(self, headers, params=None):
        return self._request("GET", f"{P}/closure-plans", headers=headers, params=params)

    def get_closure_plan(self, closure_plan_id, headers):
        return self._request("GET", f"{P}/closure-plans/{closure_plan_id}", headers=headers)

    def submit_closure_plan(self, closure_plan_id, payload, headers):
        return self._request(
            "POST", f"{P}/closure-plans/{closure_plan_id}/submission", payload, headers
        )

    def approve_closure_plan(self, closure_plan_id, payload, headers):
        return self._request(
            "POST", f"{P}/closure-plans/{closure_plan_id}/approval", payload, headers
        )

    def progress_closure_plan(self, closure_plan_id, payload, headers):
        return self._request(
            "POST", f"{P}/closure-plans/{closure_plan_id}/progression", payload, headers
        )

    def allocate_settlement(self, closure_plan_id, payload, headers):
        return self._request(
            "POST", f"{P}/closure-plans/{closure_plan_id}/settlement-allocation", payload, headers
        )

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
