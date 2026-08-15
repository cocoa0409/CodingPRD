"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/v1/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}", headers=headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/open", {}, headers)

    def lock_allocation(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/lock-allocation", {}, headers)

    def clear_climate_review(self, program_id, payload, headers):
        return self._request("POST", f"/v1/programs/{program_id}/clear-climate-review", payload, headers)

    def get_impact_report(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}/impact-report", headers=headers)

    # --- Sponsors ---
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/v1/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/v1/sponsors/{sponsor_id}", headers=headers)

    def set_sponsor_status(self, sponsor_id, payload, headers):
        return self._request("POST", f"/v1/sponsors/{sponsor_id}/set-status", payload, headers)

    # --- Groups ---
    def create_group(self, payload, headers):
        return self._request("POST", "/v1/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/v1/groups/{group_id}", headers=headers)

    def list_groups(self, headers, params=None):
        return self._request("GET", "/v1/groups", headers=headers, params=params)

    def assign_sponsor(self, group_id, payload, headers):
        return self._request("POST", f"/v1/groups/{group_id}/assign-sponsor", payload, headers)

    def submit_charter(self, group_id, headers):
        return self._request("POST", f"/v1/groups/{group_id}/submit-charter", {}, headers)

    def group_sponsor_decision(self, group_id, payload, headers):
        return self._request("POST", f"/v1/groups/{group_id}/sponsor-decision", payload, headers)

    def group_dei_decision(self, group_id, payload, headers):
        return self._request("POST", f"/v1/groups/{group_id}/dei-decision", payload, headers)

    def set_group_status(self, group_id, payload, headers):
        return self._request("POST", f"/v1/groups/{group_id}/set-status", payload, headers)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/v1/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/v1/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/v1/memberships", headers=headers, params=params)

    def leave_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/leave", {}, headers)

    # --- Leadership terms ---
    def create_leadership_term(self, payload, headers):
        return self._request("POST", "/v1/leadership-terms", payload, headers)

    def get_leadership_term(self, term_id, headers):
        return self._request("GET", f"/v1/leadership-terms/{term_id}", headers=headers)

    def list_leadership_terms(self, headers, params=None):
        return self._request("GET", "/v1/leadership-terms", headers=headers, params=params)

    def resign_leadership_term(self, term_id, headers):
        return self._request("POST", f"/v1/leadership-terms/{term_id}/resign", {}, headers)

    # --- Funding requests ---
    def create_funding_request(self, payload, headers):
        return self._request("POST", "/v1/funding-requests", payload, headers)

    def get_funding_request(self, request_id, headers):
        return self._request("GET", f"/v1/funding-requests/{request_id}", headers=headers)

    def list_funding_requests(self, headers, params=None):
        return self._request("GET", "/v1/funding-requests", headers=headers, params=params)

    def funding_sponsor_decision(self, request_id, payload, headers):
        return self._request("POST", f"/v1/funding-requests/{request_id}/sponsor-decision", payload, headers)

    def revise_funding_request(self, request_id, payload, headers):
        return self._request("POST", f"/v1/funding-requests/{request_id}/revise", payload, headers)

    def funding_dei_decision(self, request_id, payload, headers):
        return self._request("POST", f"/v1/funding-requests/{request_id}/dei-decision", payload, headers)

    def disburse_funding_request(self, request_id, headers):
        return self._request("POST", f"/v1/funding-requests/{request_id}/disburse", {}, headers)

    def reconcile_funding_request(self, request_id, payload, headers):
        return self._request("POST", f"/v1/funding-requests/{request_id}/reconcile", payload, headers)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/v1/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/v1/venues/{venue_id}", headers=headers)

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/v1/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/v1/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/v1/events", headers=headers, params=params)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/publish", {}, headers)

    def reschedule_event(self, event_id, payload, headers):
        return self._request("POST", f"/v1/events/{event_id}/reschedule", payload, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/cancel", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/complete", {}, headers)

    # --- RSVPs ---
    def create_rsvp(self, payload, headers):
        return self._request("POST", "/v1/rsvps", payload, headers)

    def get_rsvp(self, rsvp_id, headers):
        return self._request("GET", f"/v1/rsvps/{rsvp_id}", headers=headers)

    def list_rsvps(self, headers, params=None):
        return self._request("GET", "/v1/rsvps", headers=headers, params=params)

    def cancel_rsvp(self, rsvp_id, headers):
        return self._request("POST", f"/v1/rsvps/{rsvp_id}/cancel", {}, headers)

    def check_in_rsvp(self, rsvp_id, headers):
        return self._request("POST", f"/v1/rsvps/{rsvp_id}/check-in", {}, headers)

    # --- Climate surveys ---
    def create_climate_survey(self, payload, headers):
        return self._request("POST", "/v1/climate-surveys", payload, headers)

    def get_climate_survey(self, survey_id, headers):
        return self._request("GET", f"/v1/climate-surveys/{survey_id}", headers=headers)

    def list_climate_surveys(self, headers, params=None):
        return self._request("GET", "/v1/climate-surveys", headers=headers, params=params)

    def open_climate_survey(self, survey_id, headers):
        return self._request("POST", f"/v1/climate-surveys/{survey_id}/open", {}, headers)

    def close_climate_survey(self, survey_id, headers):
        return self._request("POST", f"/v1/climate-surveys/{survey_id}/close", {}, headers)

    # --- Survey responses ---
    def create_survey_response(self, payload, headers):
        return self._request("POST", "/v1/survey-responses", payload, headers)

    def get_survey_response(self, response_id, headers):
        return self._request("GET", f"/v1/survey-responses/{response_id}", headers=headers)

    def list_survey_responses(self, headers, params=None):
        return self._request("GET", "/v1/survey-responses", headers=headers, params=params)

    # --- Mentoring engagements ---
    def create_mentoring_engagement(self, payload, headers):
        return self._request("POST", "/v1/mentoring-engagements", payload, headers)

    def get_mentoring_engagement(self, engagement_id, headers):
        return self._request("GET", f"/v1/mentoring-engagements/{engagement_id}", headers=headers)

    def list_mentoring_engagements(self, headers, params=None):
        return self._request("GET", "/v1/mentoring-engagements", headers=headers, params=params)

    def mentoring_sponsor_decision(self, engagement_id, payload, headers):
        return self._request("POST", f"/v1/mentoring-engagements/{engagement_id}/sponsor-decision", payload, headers)

    def complete_mentoring_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/v1/mentoring-engagements/{engagement_id}/complete", payload, headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
