"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- partner orgs ----------------
    def create_partner_org(self, payload, headers):
        return self._request("POST", "/partner-orgs", payload, headers=headers)

    def get_partner_org(self, partner_org_id, headers):
        return self._request("GET", f"/partner-orgs/{partner_org_id}", headers=headers)

    def get_partner_org_summary(self, partner_org_id, headers):
        return self._request(
            "GET", f"/partner-orgs/{partner_org_id}/summary", headers=headers
        )

    def patch_partner_org_status(self, partner_org_id, payload, headers):
        return self._request(
            "PATCH", f"/partner-orgs/{partner_org_id}/status", payload, headers=headers
        )

    def list_partner_org_satisfaction_surveys(self, partner_org_id, headers, params=None):
        return self._request(
            "GET",
            f"/partner-orgs/{partner_org_id}/satisfaction-surveys",
            headers=headers,
            params=params,
        )

    # ---------------- program cycles ----------------
    def create_program_cycle(self, payload, headers):
        return self._request("POST", "/program-cycles", payload, headers=headers)

    def get_program_cycle(self, cycle_id, headers):
        return self._request("GET", f"/program-cycles/{cycle_id}", headers=headers)

    def recalculate_program_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/recalculate", payload, headers=headers
        )

    def list_cycle_engagements(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/program-cycles/{cycle_id}/engagements", headers=headers, params=params
        )

    # ---------------- project requests ----------------
    def create_project_request(self, payload, headers):
        return self._request("POST", "/project-requests", payload, headers=headers)

    def get_project_request(self, request_id, headers):
        return self._request("GET", f"/project-requests/{request_id}", headers=headers)

    def list_project_requests(self, headers, params=None):
        return self._request("GET", "/project-requests", headers=headers, params=params)

    def submit_for_scoping(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/project-requests/{request_id}/submit-for-scoping",
            payload,
            headers=headers,
        )

    def create_scope_definition(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/project-requests/{request_id}/scope-definitions",
            payload,
            headers=headers,
        )

    def match_project_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/project-requests/{request_id}/match", payload, headers=headers
        )

    def rescope_project_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/project-requests/{request_id}/rescope", payload, headers=headers
        )

    def abandon_project_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/project-requests/{request_id}/abandon", payload, headers=headers
        )

    # ---------------- scope definitions ----------------
    def get_scope_definition(self, scope_id, headers):
        return self._request("GET", f"/scope-definitions/{scope_id}", headers=headers)

    def list_scope_definitions(self, headers, params=None):
        return self._request("GET", "/scope-definitions", headers=headers, params=params)

    def create_deliverable(self, scope_id, payload, headers):
        return self._request(
            "POST", f"/scope-definitions/{scope_id}/deliverables", payload, headers=headers
        )

    def list_deliverables(self, scope_id, headers, params=None):
        return self._request(
            "GET",
            f"/scope-definitions/{scope_id}/deliverables",
            headers=headers,
            params=params,
        )

    def approve_scope_definition(self, scope_id, headers, payload=None):
        return self._request(
            "POST", f"/scope-definitions/{scope_id}/approve", payload, headers=headers
        )

    # ---------------- volunteers ----------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers=headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def vet_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/vet", payload, headers=headers
        )

    def patch_volunteer_status(self, volunteer_id, payload, headers):
        return self._request(
            "PATCH", f"/volunteers/{volunteer_id}/status", payload, headers=headers
        )

    def create_skill_profile(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/skill-profiles", payload, headers=headers
        )

    def list_skill_profiles(self, volunteer_id, headers, params=None):
        return self._request(
            "GET",
            f"/volunteers/{volunteer_id}/skill-profiles",
            headers=headers,
            params=params,
        )

    def create_availability_window(self, volunteer_id, payload, headers):
        return self._request(
            "POST",
            f"/volunteers/{volunteer_id}/availability-windows",
            payload,
            headers=headers,
        )

    def list_availability_windows(self, volunteer_id, headers, params=None):
        return self._request(
            "GET",
            f"/volunteers/{volunteer_id}/availability-windows",
            headers=headers,
            params=params,
        )

    # ---------------- match offers ----------------
    def get_match_offer(self, offer_id, headers):
        return self._request("GET", f"/match-offers/{offer_id}", headers=headers)

    def list_match_offers(self, headers, params=None):
        return self._request("GET", "/match-offers", headers=headers, params=params)

    def accept_match_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/match-offers/{offer_id}/accept", payload, headers=headers
        )

    def decline_match_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/match-offers/{offer_id}/decline", payload, headers=headers
        )

    def withdraw_match_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/match-offers/{offer_id}/withdraw", payload, headers=headers
        )

    # ---------------- engagements ----------------
    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def create_agreement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/agreements", payload, headers=headers
        )

    def list_agreements(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/agreements", headers=headers, params=params
        )

    def send_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/agreements/{agreement_id}/send", payload, headers=headers
        )

    def counter_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/counter", payload, headers=headers
        )

    def execute_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/agreements/{agreement_id}/execute", payload, headers=headers
        )

    def void_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/agreements/{agreement_id}/void", payload, headers=headers
        )

    def start_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/start", payload, headers=headers
        )

    def create_milestone(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/milestones", payload, headers=headers
        )

    def list_milestones(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/milestones", headers=headers, params=params
        )

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/milestones/{milestone_id}", headers=headers)

    def hold_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/milestones/{milestone_id}/hold", payload, headers=headers
        )

    def list_milestone_time_logs(self, milestone_id, headers, params=None):
        return self._request(
            "GET", f"/milestones/{milestone_id}/time-logs", headers=headers, params=params
        )

    def create_time_log(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/time-logs", payload, headers=headers
        )

    def list_time_logs(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/time-logs", headers=headers, params=params
        )

    def create_scope_change_request(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/scope-change-requests",
            payload,
            headers=headers,
        )

    def list_scope_change_requests(self, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/scope-change-requests",
            headers=headers,
            params=params,
        )

    def decide_scope_change_request(self, scope_change_id, payload, headers):
        return self._request(
            "POST",
            f"/scope-change-requests/{scope_change_id}/decide",
            payload,
            headers=headers,
        )

    def submit_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/submit", payload, headers=headers
        )

    def create_quality_review(self, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/quality-reviews",
            payload,
            headers=headers,
        )

    def list_quality_reviews(self, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/quality-reviews",
            headers=headers,
            params=params,
        )

    def score_quality_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/quality-reviews/{review_id}/score", payload, headers=headers
        )

    def decide_quality_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/quality-reviews/{review_id}/decide", payload, headers=headers
        )

    def handoff_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/handoff", payload, headers=headers
        )

    def terminate_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/terminate", payload, headers=headers
        )

    def create_valuation(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/valuations", payload, headers=headers
        )

    def list_valuation_records(self, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/valuation-records",
            headers=headers,
            params=params,
        )

    def create_satisfaction_survey(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/satisfaction-surveys",
            payload,
            headers=headers,
        )

    def list_engagement_satisfaction_surveys(self, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/satisfaction-surveys",
            headers=headers,
            params=params,
        )

    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
