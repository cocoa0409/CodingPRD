"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Safety programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/safety/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/safety/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/safety/programs/{program_id}", headers=headers)

    def patch_incentive_config(self, program_id, payload, headers):
        return self._request("PATCH", f"/safety/programs/{program_id}/incentive-config",
                             payload, headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/safety/programs/{program_id}/activate", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/safety/programs/{program_id}/close", {}, headers)

    def reconcile_program(self, program_id, headers):
        return self._request("POST", f"/safety/programs/{program_id}/reconcile", {}, headers)

    def sweep_program(self, program_id, payload, headers):
        return self._request("POST", f"/safety/programs/{program_id}/sweep",
                             payload or {}, headers)

    def get_leading_indicators(self, program_id, headers):
        return self._request("GET", f"/safety/programs/{program_id}/leading-indicators",
                             headers=headers)

    # ------------------------------------------------------------------
    # EMR forecasts
    # ------------------------------------------------------------------
    def create_emr_forecast(self, payload, headers):
        return self._request("POST", "/safety/emr-forecasts", payload, headers)

    def list_emr_forecasts(self, headers, params=None):
        return self._request("GET", "/safety/emr-forecasts", headers=headers, params=params)

    def get_emr_forecast(self, forecast_id, headers):
        return self._request("GET", f"/safety/emr-forecasts/{forecast_id}", headers=headers)

    # ------------------------------------------------------------------
    # Job roles, employees, training catalog
    # ------------------------------------------------------------------
    def create_job_role(self, payload, headers):
        return self._request("POST", "/safety/job-roles", payload, headers)

    def list_job_roles(self, headers, params=None):
        return self._request("GET", "/safety/job-roles", headers=headers, params=params)

    def get_job_role(self, job_role_id, headers):
        return self._request("GET", f"/safety/job-roles/{job_role_id}", headers=headers)

    def create_employee(self, payload, headers):
        return self._request("POST", "/safety/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/safety/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/safety/employees/{employee_id}", headers=headers)

    def deactivate_employee(self, employee_id, headers):
        return self._request("POST", f"/safety/employees/{employee_id}/deactivate",
                             {}, headers)

    def create_training_course(self, payload, headers):
        return self._request("POST", "/safety/training-courses", payload, headers)

    def list_training_courses(self, headers, params=None):
        return self._request("GET", "/safety/training-courses", headers=headers,
                             params=params)

    def get_training_course(self, course_id, headers):
        return self._request("GET", f"/safety/training-courses/{course_id}", headers=headers)

    # ------------------------------------------------------------------
    # Training assignments
    # ------------------------------------------------------------------
    def create_training_assignment(self, payload, headers):
        return self._request("POST", "/safety/training-assignments", payload, headers)

    def list_training_assignments(self, headers, params=None):
        return self._request("GET", "/safety/training-assignments", headers=headers,
                             params=params)

    def get_training_assignment(self, assignment_id, headers):
        return self._request("GET", f"/safety/training-assignments/{assignment_id}",
                             headers=headers)

    def complete_training_assignment(self, assignment_id, payload, headers):
        return self._request("POST",
                             f"/safety/training-assignments/{assignment_id}/complete",
                             payload or {}, headers)

    def reassign_training_assignment(self, assignment_id, payload, headers):
        return self._request("POST",
                             f"/safety/training-assignments/{assignment_id}/reassign",
                             payload, headers)

    # ------------------------------------------------------------------
    # Hazards and controls
    # ------------------------------------------------------------------
    def create_hazard(self, payload, headers):
        return self._request("POST", "/safety/hazards", payload, headers)

    def list_hazards(self, headers, params=None):
        return self._request("GET", "/safety/hazards", headers=headers, params=params)

    def get_hazard(self, hazard_id, headers):
        return self._request("GET", f"/safety/hazards/{hazard_id}", headers=headers)

    def assess_hazard(self, hazard_id, payload, headers):
        return self._request("POST", f"/safety/hazards/{hazard_id}/assess",
                             payload, headers)

    def reopen_hazard(self, hazard_id, payload, headers):
        return self._request("POST", f"/safety/hazards/{hazard_id}/reopen",
                             payload, headers)

    def create_control(self, hazard_id, payload, headers):
        return self._request("POST", f"/safety/hazards/{hazard_id}/controls",
                             payload, headers)

    def list_hazard_controls(self, hazard_id, headers, params=None):
        return self._request("GET", f"/safety/hazards/{hazard_id}/controls",
                             headers=headers, params=params)

    def list_controls(self, headers, params=None):
        return self._request("GET", "/safety/controls", headers=headers, params=params)

    def get_control(self, control_id, headers):
        return self._request("GET", f"/safety/controls/{control_id}", headers=headers)

    def implement_control(self, control_id, payload, headers):
        return self._request("POST", f"/safety/controls/{control_id}/implement",
                             payload or {}, headers)

    def verify_control(self, control_id, payload, headers):
        return self._request("POST", f"/safety/controls/{control_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------
    def create_observation(self, payload, headers):
        return self._request("POST", "/safety/observations", payload, headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/safety/observations", headers=headers, params=params)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/safety/observations/{observation_id}", headers=headers)

    def triage_observation(self, observation_id, payload, headers):
        return self._request("POST", f"/safety/observations/{observation_id}/triage",
                             payload, headers)

    # ------------------------------------------------------------------
    # Committee meetings and action items
    # ------------------------------------------------------------------
    def create_committee_meeting(self, payload, headers):
        return self._request("POST", "/safety/committee-meetings", payload, headers)

    def list_committee_meetings(self, headers, params=None):
        return self._request("GET", "/safety/committee-meetings", headers=headers,
                             params=params)

    def get_committee_meeting(self, meeting_id, headers):
        return self._request("GET", f"/safety/committee-meetings/{meeting_id}",
                             headers=headers)

    def hold_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"/safety/committee-meetings/{meeting_id}/hold",
                             payload, headers)

    def publish_minutes(self, meeting_id, payload, headers):
        return self._request("POST",
                             f"/safety/committee-meetings/{meeting_id}/publish-minutes",
                             payload, headers)

    def cancel_meeting(self, meeting_id, headers):
        return self._request("POST", f"/safety/committee-meetings/{meeting_id}/cancel",
                             {}, headers)

    def create_action_item(self, meeting_id, payload, headers):
        return self._request("POST",
                             f"/safety/committee-meetings/{meeting_id}/action-items",
                             payload, headers)

    def list_meeting_action_items(self, meeting_id, headers, params=None):
        return self._request("GET",
                             f"/safety/committee-meetings/{meeting_id}/action-items",
                             headers=headers, params=params)

    def list_action_items(self, headers, params=None):
        return self._request("GET", "/safety/action-items", headers=headers, params=params)

    def get_action_item(self, action_item_id, headers):
        return self._request("GET", f"/safety/action-items/{action_item_id}", headers=headers)

    def complete_action_item(self, action_item_id, payload, headers):
        return self._request("POST", f"/safety/action-items/{action_item_id}/complete",
                             payload or {}, headers)

    def verify_action_item(self, action_item_id, payload, headers):
        return self._request("POST", f"/safety/action-items/{action_item_id}/verify",
                             payload, headers)

    def reassign_action_item(self, action_item_id, payload, headers):
        return self._request("POST", f"/safety/action-items/{action_item_id}/reassign",
                             payload, headers)

    # ------------------------------------------------------------------
    # Contractor organizations
    # ------------------------------------------------------------------
    def create_contractor_org(self, payload, headers):
        return self._request("POST", "/safety/contractor-orgs", payload, headers)

    def list_contractor_orgs(self, headers, params=None):
        return self._request("GET", "/safety/contractor-orgs", headers=headers, params=params)

    def get_contractor_org(self, contractor_id, headers):
        return self._request("GET", f"/safety/contractor-orgs/{contractor_id}",
                             headers=headers)

    def submit_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"/safety/contractor-orgs/{contractor_id}/submit",
                             payload or {}, headers)

    def decide_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"/safety/contractor-orgs/{contractor_id}/decide",
                             payload, headers)

    def suspend_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"/safety/contractor-orgs/{contractor_id}/suspend",
                             payload, headers)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/safety/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/safety/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/safety/claims/{claim_id}", headers=headers)

    def accept_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/safety/claims/{claim_id}/accept",
                             payload or {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/safety/claims/{claim_id}/deny", payload, headers)

    def close_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/safety/claims/{claim_id}/close",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Loss-control recommendations
    # ------------------------------------------------------------------
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/safety/loss-control-recommendations",
                             payload, headers)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/safety/loss-control-recommendations",
                             headers=headers, params=params)

    def get_recommendation(self, recommendation_id, headers):
        return self._request("GET",
                             f"/safety/loss-control-recommendations/{recommendation_id}",
                             headers=headers)

    def respond_recommendation(self, recommendation_id, payload, headers):
        return self._request(
            "POST", f"/safety/loss-control-recommendations/{recommendation_id}/respond",
            payload, headers)

    def review_recommendation_response(self, recommendation_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/loss-control-recommendations/{recommendation_id}/review-response",
            payload, headers)

    # ------------------------------------------------------------------
    # Incentive awards and point-ledger events
    # ------------------------------------------------------------------
    def list_incentive_awards(self, headers, params=None):
        return self._request("GET", "/safety/incentive-awards", headers=headers,
                             params=params)

    def get_incentive_award(self, award_id, headers):
        return self._request("GET", f"/safety/incentive-awards/{award_id}", headers=headers)

    def approve_award(self, award_id, headers):
        return self._request("POST", f"/safety/incentive-awards/{award_id}/approve",
                             {}, headers)

    def pay_award(self, award_id, headers):
        return self._request("POST", f"/safety/incentive-awards/{award_id}/pay", {}, headers)

    def void_award(self, award_id, payload, headers):
        return self._request("POST", f"/safety/incentive-awards/{award_id}/void",
                             payload, headers)

    def list_incentive_events(self, headers, params=None):
        return self._request("GET", "/safety/incentive-events", headers=headers,
                             params=params)

    def get_incentive_event(self, event_id, headers):
        return self._request("GET", f"/safety/incentive-events/{event_id}", headers=headers)


api_client = ApiClient()
