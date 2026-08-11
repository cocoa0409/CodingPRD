"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner SIGKILLs and respawns the API server before every test
        # (per-test-server isolation). A pooled keep-alive connection can race
        # that restart — or be torn down under parallel-sweep load — surfacing
        # as ConnectionResetError mid-test. Force one TCP connection per
        # request so no stale pooled connection is ever reused.
        self.session.headers["Connection"] = "close"

    # --- AlumniRecord ---
    def create_record(self, payload, headers):
        return self._request("POST", "/alumni/records", payload, headers)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/alumni/records/{record_id}", headers=headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/alumni/records", headers=headers, params=params)

    def update_record(self, record_id, payload, headers):
        return self._request("PUT", f"/alumni/records/{record_id}", payload, headers)

    def mark_lost(self, record_id, headers):
        return self._request("POST", f"/alumni/records/{record_id}/mark-lost", {}, headers)

    def set_do_not_contact(self, record_id, headers):
        return self._request("POST", f"/alumni/records/{record_id}/set-do-not-contact", {}, headers)

    def clear_do_not_contact(self, record_id, headers):
        return self._request("POST", f"/alumni/records/{record_id}/clear-do-not-contact", {}, headers)

    def mark_deceased(self, record_id, headers):
        return self._request("POST", f"/alumni/records/{record_id}/mark-deceased", {}, headers)

    # --- LostAlumniResearchCase ---
    def create_research_case(self, payload, headers):
        return self._request("POST", "/alumni/research-cases", payload, headers)

    def get_research_case(self, case_id, headers):
        return self._request("GET", f"/alumni/research-cases/{case_id}", headers=headers)

    def list_research_cases(self, headers, params=None):
        return self._request("GET", "/alumni/research-cases", headers=headers, params=params)

    def log_lead(self, case_id, payload, headers):
        return self._request("POST", f"/alumni/research-cases/{case_id}/log-lead", payload, headers)

    def verify_case(self, case_id, headers):
        return self._request("POST", f"/alumni/research-cases/{case_id}/verify", {}, headers)

    def reopen_case(self, case_id, headers):
        return self._request("POST", f"/alumni/research-cases/{case_id}/reopen", {}, headers)

    def reunite_case(self, case_id, headers):
        return self._request("POST", f"/alumni/research-cases/{case_id}/reunite", {}, headers)

    def dead_end_case(self, case_id, headers):
        return self._request("POST", f"/alumni/research-cases/{case_id}/dead-end", {}, headers)

    # --- ReunionEvent ---
    def create_event(self, payload, headers):
        return self._request("POST", "/alumni/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/alumni/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/alumni/events", headers=headers, params=params)

    def form_committee(self, event_id, headers):
        return self._request("POST", f"/alumni/events/{event_id}/form-committee", {}, headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/alumni/events/{event_id}/open-registration", {}, headers)

    def mark_held(self, event_id, headers):
        return self._request("POST", f"/alumni/events/{event_id}/mark-held", {}, headers)

    def reconcile_event(self, event_id, headers):
        return self._request("POST", f"/alumni/events/{event_id}/reconcile", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/alumni/events/{event_id}/cancel", {}, headers)

    # --- ReunionCommittee ---
    def create_committee(self, event_id, payload, headers):
        return self._request("POST", f"/alumni/events/{event_id}/committee", payload, headers)

    def get_committee(self, event_id, headers):
        return self._request("GET", f"/alumni/events/{event_id}/committee", headers=headers)

    # --- CommitteeMembership ---
    def create_membership(self, committee_id, payload, headers):
        return self._request("POST", f"/alumni/committees/{committee_id}/memberships", payload, headers)

    def list_committee_memberships(self, committee_id, headers, params=None):
        return self._request("GET", f"/alumni/committees/{committee_id}/memberships", headers=headers, params=params)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/alumni/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/alumni/memberships/{membership_id}", headers=headers)

    def accept_membership(self, membership_id, headers):
        return self._request("POST", f"/alumni/memberships/{membership_id}/accept", {}, headers)

    def decline_membership(self, membership_id, headers):
        return self._request("POST", f"/alumni/memberships/{membership_id}/decline", {}, headers)

    def end_membership(self, membership_id, headers):
        return self._request("POST", f"/alumni/memberships/{membership_id}/end", {}, headers)

    # --- TicketTier ---
    def create_ticket_tier(self, event_id, payload, headers):
        return self._request("POST", f"/alumni/events/{event_id}/ticket-tiers", payload, headers)

    def list_ticket_tiers(self, event_id, headers, params=None):
        return self._request("GET", f"/alumni/events/{event_id}/ticket-tiers", headers=headers, params=params)

    def get_ticket_tier(self, tier_id, headers):
        return self._request("GET", f"/alumni/ticket-tiers/{tier_id}", headers=headers)

    # --- EventRegistration ---
    def create_registration(self, event_id, payload, headers):
        return self._request("POST", f"/alumni/events/{event_id}/registrations", payload, headers)

    def list_event_registrations(self, event_id, headers, params=None):
        return self._request("GET", f"/alumni/events/{event_id}/registrations", headers=headers, params=params)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/alumni/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/alumni/registrations/{registration_id}", headers=headers)

    def confirm_payment(self, registration_id, headers):
        return self._request("POST", f"/alumni/registrations/{registration_id}/confirm-payment", {}, headers)

    def refund_registration(self, registration_id, headers):
        return self._request("POST", f"/alumni/registrations/{registration_id}/refund", {}, headers)

    def check_in_registration(self, registration_id, headers):
        return self._request("POST", f"/alumni/registrations/{registration_id}/check-in", {}, headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/alumni/registrations/{registration_id}/cancel", {}, headers)

    # --- AffinityGroup ---
    def create_group(self, payload, headers):
        return self._request("POST", "/alumni/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/alumni/groups/{group_id}", headers=headers)

    def list_groups(self, headers, params=None):
        return self._request("GET", "/alumni/groups", headers=headers, params=params)

    def suspend_group(self, group_id, headers):
        return self._request("POST", f"/alumni/groups/{group_id}/suspend", {}, headers)

    def reactivate_group(self, group_id, headers):
        return self._request("POST", f"/alumni/groups/{group_id}/reactivate", {}, headers)

    def dissolve_group(self, group_id, headers):
        return self._request("POST", f"/alumni/groups/{group_id}/dissolve", {}, headers)

    # --- ChapterProgram ---
    def create_program(self, group_id, payload, headers):
        return self._request("POST", f"/alumni/groups/{group_id}/programs", payload, headers)

    def list_group_programs(self, group_id, headers, params=None):
        return self._request("GET", f"/alumni/groups/{group_id}/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/alumni/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/alumni/programs", headers=headers, params=params)

    def propose_program(self, program_id, headers):
        return self._request("POST", f"/alumni/programs/{program_id}/propose", {}, headers)

    def withdraw_program(self, program_id, headers):
        return self._request("POST", f"/alumni/programs/{program_id}/withdraw", {}, headers)

    def approve_program(self, program_id, headers):
        return self._request("POST", f"/alumni/programs/{program_id}/approve", {}, headers)

    def publish_program(self, program_id, headers):
        return self._request("POST", f"/alumni/programs/{program_id}/publish", {}, headers)

    def complete_program(self, program_id, payload, headers):
        return self._request("POST", f"/alumni/programs/{program_id}/complete", payload, headers)

    def cancel_program(self, program_id, headers):
        return self._request("POST", f"/alumni/programs/{program_id}/cancel", {}, headers)

    # --- CommunicationPreference / suppression list ---
    def create_preference(self, record_id, payload, headers):
        return self._request("POST", f"/alumni/records/{record_id}/preferences", payload, headers)

    def list_preferences(self, record_id, headers, params=None):
        return self._request("GET", f"/alumni/records/{record_id}/preferences", headers=headers, params=params)

    def update_preference(self, preference_id, payload, headers):
        return self._request("PUT", f"/alumni/preferences/{preference_id}", payload, headers)

    def add_suppression(self, payload, headers):
        return self._request("POST", "/alumni/suppression-list", payload, headers)

    def remove_suppression(self, payload, headers):
        return self._request("DELETE", "/alumni/suppression-list", payload, headers)

    # --- GiftCampaign ---
    def create_campaign(self, event_id, payload, headers):
        return self._request("POST", f"/alumni/events/{event_id}/campaigns", payload, headers)

    def get_event_campaign(self, event_id, headers):
        return self._request("GET", f"/alumni/events/{event_id}/campaigns", headers=headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/alumni/campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/alumni/campaigns/{campaign_id}/activate", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/alumni/campaigns/{campaign_id}/close", {}, headers)

    # --- GiftPledge ---
    def create_pledge(self, campaign_id, payload, headers):
        return self._request("POST", f"/alumni/campaigns/{campaign_id}/pledges", payload, headers)

    def list_campaign_pledges(self, campaign_id, headers, params=None):
        return self._request("GET", f"/alumni/campaigns/{campaign_id}/pledges", headers=headers, params=params)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/alumni/pledges", headers=headers, params=params)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/alumni/pledges/{pledge_id}", headers=headers)

    def fulfill_pledge(self, pledge_id, headers):
        return self._request("POST", f"/alumni/pledges/{pledge_id}/fulfill", {}, headers)

    def lapse_pledge(self, pledge_id, headers):
        return self._request("POST", f"/alumni/pledges/{pledge_id}/lapse", {}, headers)

    def write_off_pledge(self, pledge_id, headers):
        return self._request("POST", f"/alumni/pledges/{pledge_id}/write-off", {}, headers)

    # --- MemorabiliaPublication ---
    def create_publication(self, event_id, payload, headers):
        return self._request("POST", f"/alumni/events/{event_id}/publications", payload, headers)

    def list_event_publications(self, event_id, headers, params=None):
        return self._request("GET", f"/alumni/events/{event_id}/publications", headers=headers, params=params)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/alumni/publications/{publication_id}", headers=headers)

    def submit_review(self, publication_id, headers):
        return self._request("POST", f"/alumni/publications/{publication_id}/submit-review", {}, headers)

    def return_for_edits(self, publication_id, headers):
        return self._request("POST", f"/alumni/publications/{publication_id}/return-for-edits", {}, headers)

    def approve_publication(self, publication_id, headers):
        return self._request("POST", f"/alumni/publications/{publication_id}/approve", {}, headers)

    def request_re_review(self, publication_id, headers):
        return self._request("POST", f"/alumni/publications/{publication_id}/request-re-review", {}, headers)

    def publish_publication(self, publication_id, headers):
        return self._request("POST", f"/alumni/publications/{publication_id}/publish", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/alumni/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
