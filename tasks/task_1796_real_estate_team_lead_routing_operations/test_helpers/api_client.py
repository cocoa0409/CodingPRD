"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving endpoint, TeamAdmin only) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Teams ---
    def create_team(self, payload, headers):
        return self._request("POST", "/crm/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/crm/teams/{team_id}", headers=headers)

    # --- Agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/crm/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/crm/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/crm/agents", headers=headers, params=params)

    def activate_agent(self, agent_id, headers):
        return self._request("POST", f"/crm/agents/{agent_id}/activate", {}, headers)

    def pause_agent(self, agent_id, headers):
        return self._request("POST", f"/crm/agents/{agent_id}/pause", {}, headers)

    def resume_agent(self, agent_id, headers):
        return self._request("POST", f"/crm/agents/{agent_id}/resume", {}, headers)

    def offboard_agent(self, agent_id, headers):
        return self._request("POST", f"/crm/agents/{agent_id}/offboard", {}, headers)

    def get_agent_scorecard(self, agent_id, headers):
        return self._request("GET", f"/crm/agents/{agent_id}/scorecard", headers=headers)

    def import_production_stats(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/crm/agents/{agent_id}/import-production-stats", payload, headers
        )

    def create_time_off(self, agent_id, payload, headers):
        return self._request("POST", f"/crm/agents/{agent_id}/time-offs", payload, headers)

    def list_time_offs(self, agent_id, headers):
        return self._request("GET", f"/crm/agents/{agent_id}/time-offs", headers=headers)

    # --- Routing policies ---
    def create_routing_policy(self, payload, headers):
        return self._request("POST", "/crm/routing-policies", payload, headers)

    def get_routing_policy(self, policy_id, headers):
        return self._request("GET", f"/crm/routing-policies/{policy_id}", headers=headers)

    def list_routing_policies(self, headers, params=None):
        return self._request("GET", "/crm/routing-policies", headers=headers, params=params)

    def activate_routing_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/crm/routing-policies/{policy_id}/activate", payload, headers
        )

    # --- Lead sources ---
    def create_lead_source(self, payload, headers):
        return self._request("POST", "/crm/lead-sources", payload, headers)

    def get_lead_source(self, source_id, headers):
        return self._request("GET", f"/crm/lead-sources/{source_id}", headers=headers)

    def list_lead_sources(self, headers, params=None):
        return self._request("GET", "/crm/lead-sources", headers=headers, params=params)

    def pause_lead_source(self, source_id, headers):
        return self._request("POST", f"/crm/lead-sources/{source_id}/pause", {}, headers)

    def resume_lead_source(self, source_id, headers):
        return self._request("POST", f"/crm/lead-sources/{source_id}/resume", {}, headers)

    def get_source_roi(self, source_id, headers, params=None):
        return self._request(
            "GET", f"/crm/lead-sources/{source_id}/roi", headers=headers, params=params
        )

    # --- Leads ---
    def create_lead(self, payload, headers):
        return self._request("POST", "/crm/leads", payload, headers)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/crm/leads/{lead_id}", headers=headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/crm/leads", headers=headers, params=params)

    def route_lead(self, lead_id, headers):
        return self._request("POST", f"/crm/leads/{lead_id}/route", {}, headers)

    def claim_lead(self, lead_id, headers):
        return self._request("POST", f"/crm/leads/{lead_id}/claim", {}, headers)

    def release_lead(self, lead_id, payload, headers):
        return self._request("POST", f"/crm/leads/{lead_id}/release", payload, headers)

    def log_response(self, lead_id, headers):
        return self._request("POST", f"/crm/leads/{lead_id}/log-response", {}, headers)

    def create_engagement_event(self, lead_id, payload, headers):
        return self._request(
            "POST", f"/crm/leads/{lead_id}/engagement-events", payload, headers
        )

    def list_engagement_events(self, lead_id, headers):
        return self._request(
            "GET", f"/crm/leads/{lead_id}/engagement-events", headers=headers
        )

    def close_lost(self, lead_id, payload, headers):
        return self._request("POST", f"/crm/leads/{lead_id}/close-lost", payload, headers)

    def recycle_lead(self, lead_id, headers):
        return self._request("POST", f"/crm/leads/{lead_id}/recycle", {}, headers)

    # --- Assignments ---
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crm/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/crm/assignments", headers=headers, params=params)

    def reassign_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crm/assignments/{assignment_id}/reassign", payload, headers
        )

    # --- Nurture campaigns ---
    def create_nurture_campaign(self, payload, headers):
        return self._request("POST", "/crm/nurture-campaigns", payload, headers)

    def get_nurture_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/crm/nurture-campaigns/{campaign_id}", headers=headers
        )

    def list_nurture_campaigns(self, headers, params=None):
        return self._request("GET", "/crm/nurture-campaigns", headers=headers, params=params)

    def activate_nurture_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/crm/nurture-campaigns/{campaign_id}/activate", {}, headers
        )

    def pause_nurture_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/crm/nurture-campaigns/{campaign_id}/pause", {}, headers
        )

    # --- Nurture enrollments ---
    def create_nurture_enrollment(self, payload, headers):
        return self._request("POST", "/crm/nurture-enrollments", payload, headers)

    def get_nurture_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/crm/nurture-enrollments/{enrollment_id}", headers=headers
        )

    def list_nurture_enrollments(self, headers, params=None):
        return self._request("GET", "/crm/nurture-enrollments", headers=headers, params=params)

    def exit_nurture_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/crm/nurture-enrollments/{enrollment_id}/exit", {}, headers
        )

    # --- Referral partners ---
    def create_referral_partner(self, payload, headers):
        return self._request("POST", "/crm/referral-partners", payload, headers)

    def get_referral_partner(self, partner_id, headers):
        return self._request("GET", f"/crm/referral-partners/{partner_id}", headers=headers)

    def list_referral_partners(self, headers, params=None):
        return self._request("GET", "/crm/referral-partners", headers=headers, params=params)

    # --- Split agreements ---
    def create_split_agreement(self, payload, headers):
        return self._request("POST", "/crm/split-agreements", payload, headers)

    def get_split_agreement(self, agreement_id, headers):
        return self._request("GET", f"/crm/split-agreements/{agreement_id}", headers=headers)

    def list_split_agreements(self, headers, params=None):
        return self._request("GET", "/crm/split-agreements", headers=headers, params=params)

    def terminate_split_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/crm/split-agreements/{agreement_id}/terminate", {}, headers
        )

    # --- Deals ---
    def create_deal(self, payload, headers):
        return self._request("POST", "/crm/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/crm/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/crm/deals", headers=headers, params=params)

    def approve_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/crm/deals/{deal_id}/approve", payload, headers)

    def dispute_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/crm/deals/{deal_id}/dispute", payload, headers)

    def mark_deal_paid(self, deal_id, headers):
        return self._request("POST", f"/crm/deals/{deal_id}/mark-paid", {}, headers)


api_client = ApiClient()
