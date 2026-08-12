"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Members (PRD §3.1)
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def patch_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    def member_set_status(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/set-status", payload, headers)

    def renew_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/renew", payload, headers)

    # ------------------------------------------------------------------
    # Antenna site agreements (PRD §3.2)
    # ------------------------------------------------------------------
    def create_antenna_site_agreement(self, payload, headers):
        return self._request("POST", "/antenna-site-agreements", payload, headers)

    def list_antenna_site_agreements(self, headers, params=None):
        return self._request("GET", "/antenna-site-agreements", headers=headers, params=params)

    def get_antenna_site_agreement(self, agreement_id, headers):
        return self._request("GET", f"/antenna-site-agreements/{agreement_id}", headers=headers)

    def antenna_site_agreement_set_status(self, agreement_id, payload, headers):
        return self._request("POST", f"/antenna-site-agreements/{agreement_id}/set-status", payload, headers)

    # ------------------------------------------------------------------
    # Repeaters (PRD §3.2)
    # ------------------------------------------------------------------
    def create_repeater(self, payload, headers):
        return self._request("POST", "/repeaters", payload, headers)

    def list_repeaters(self, headers, params=None):
        return self._request("GET", "/repeaters", headers=headers, params=params)

    def get_repeater(self, repeater_id, headers):
        return self._request("GET", f"/repeaters/{repeater_id}", headers=headers)

    def repeater_set_status(self, repeater_id, payload, headers):
        return self._request("POST", f"/repeaters/{repeater_id}/set-status", payload, headers)

    # ------------------------------------------------------------------
    # Frequency coordination requests (PRD §3.2)
    # ------------------------------------------------------------------
    def create_coordination_request(self, payload, headers):
        return self._request("POST", "/coordination-requests", payload, headers)

    def list_coordination_requests(self, headers, params=None):
        return self._request("GET", "/coordination-requests", headers=headers, params=params)

    def get_coordination_request(self, request_id, headers):
        return self._request("GET", f"/coordination-requests/{request_id}", headers=headers)

    def submit_coordination_request(self, request_id, headers):
        return self._request("POST", f"/coordination-requests/{request_id}/submit", {}, headers)

    def record_coordination_decision(self, request_id, payload, headers):
        return self._request("POST", f"/coordination-requests/{request_id}/record-decision", payload, headers)

    def revise_coordination_request(self, request_id, payload, headers):
        return self._request("POST", f"/coordination-requests/{request_id}/revise", payload, headers)

    def withdraw_coordination_request(self, request_id, headers):
        return self._request("POST", f"/coordination-requests/{request_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Net sessions and check-ins (PRD §3.3)
    # ------------------------------------------------------------------
    def create_net_session(self, payload, headers):
        return self._request("POST", "/net-sessions", payload, headers)

    def list_net_sessions(self, headers, params=None):
        return self._request("GET", "/net-sessions", headers=headers, params=params)

    def get_net_session(self, net_id, headers):
        return self._request("GET", f"/net-sessions/{net_id}", headers=headers)

    def net_session_set_status(self, net_id, payload, headers):
        return self._request("POST", f"/net-sessions/{net_id}/set-status", payload, headers)

    def create_check_in(self, payload, headers):
        return self._request("POST", "/check-ins", payload, headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    def get_check_in(self, checkin_id, headers):
        return self._request("GET", f"/check-ins/{checkin_id}", headers=headers)

    # ------------------------------------------------------------------
    # Served-agency agreements, activations, rosters (PRD §3.4)
    # ------------------------------------------------------------------
    def create_served_agency_agreement(self, payload, headers):
        return self._request("POST", "/served-agency-agreements", payload, headers)

    def list_served_agency_agreements(self, headers, params=None):
        return self._request("GET", "/served-agency-agreements", headers=headers, params=params)

    def get_served_agency_agreement(self, agreement_id, headers):
        return self._request("GET", f"/served-agency-agreements/{agreement_id}", headers=headers)

    def served_agency_agreement_set_status(self, agreement_id, payload, headers):
        return self._request("POST", f"/served-agency-agreements/{agreement_id}/set-status", payload, headers)

    def create_emergency_activation(self, payload, headers):
        return self._request("POST", "/emergency-activations", payload, headers)

    def list_emergency_activations(self, headers, params=None):
        return self._request("GET", "/emergency-activations", headers=headers, params=params)

    def get_emergency_activation(self, activation_id, headers):
        return self._request("GET", f"/emergency-activations/{activation_id}", headers=headers)

    def emergency_activation_set_status(self, activation_id, payload, headers):
        return self._request("POST", f"/emergency-activations/{activation_id}/set-status", payload, headers)

    def create_roster_entry(self, payload, headers):
        return self._request("POST", "/roster-entries", payload, headers)

    def list_roster_entries(self, headers, params=None):
        return self._request("GET", "/roster-entries", headers=headers, params=params)

    def get_roster_entry(self, entry_id, headers):
        return self._request("GET", f"/roster-entries/{entry_id}", headers=headers)

    def roster_entry_set_status(self, entry_id, payload, headers):
        return self._request("POST", f"/roster-entries/{entry_id}/set-status", payload, headers)

    # ------------------------------------------------------------------
    # Drills and radiogram messages (PRD §3.5)
    # ------------------------------------------------------------------
    def create_drill(self, payload, headers):
        return self._request("POST", "/drills", payload, headers)

    def list_drills(self, headers, params=None):
        return self._request("GET", "/drills", headers=headers, params=params)

    def get_drill(self, drill_id, headers):
        return self._request("GET", f"/drills/{drill_id}", headers=headers)

    def drill_set_status(self, drill_id, payload, headers):
        return self._request("POST", f"/drills/{drill_id}/set-status", payload, headers)

    def create_drill_message(self, payload, headers):
        return self._request("POST", "/drill-messages", payload, headers)

    def list_drill_messages(self, headers, params=None):
        return self._request("GET", "/drill-messages", headers=headers, params=params)

    def get_drill_message(self, message_id, headers):
        return self._request("GET", f"/drill-messages/{message_id}", headers=headers)

    def drill_message_set_status(self, message_id, payload, headers):
        return self._request("POST", f"/drill-messages/{message_id}/set-status", payload, headers)

    # ------------------------------------------------------------------
    # Field day events and contacts (PRD §3.6)
    # ------------------------------------------------------------------
    def create_field_day_event(self, payload, headers):
        return self._request("POST", "/field-day-events", payload, headers)

    def list_field_day_events(self, headers, params=None):
        return self._request("GET", "/field-day-events", headers=headers, params=params)

    def get_field_day_event(self, event_id, headers):
        return self._request("GET", f"/field-day-events/{event_id}", headers=headers)

    def field_day_event_set_status(self, event_id, payload, headers):
        return self._request("POST", f"/field-day-events/{event_id}/set-status", payload, headers)

    def create_field_day_contact(self, payload, headers):
        return self._request("POST", "/field-day-contacts", payload, headers)

    def list_field_day_contacts(self, headers, params=None):
        return self._request("GET", "/field-day-contacts", headers=headers, params=params)

    def get_field_day_contact(self, contact_id, headers):
        return self._request("GET", f"/field-day-contacts/{contact_id}", headers=headers)

    def field_day_contact_set_duplicate(self, contact_id, payload, headers):
        return self._request("POST", f"/field-day-contacts/{contact_id}/set-duplicate", payload, headers)

    # ------------------------------------------------------------------
    # Exam sessions and candidates (PRD §3.7)
    # ------------------------------------------------------------------
    def create_exam_session(self, payload, headers):
        return self._request("POST", "/exam-sessions", payload, headers)

    def list_exam_sessions(self, headers, params=None):
        return self._request("GET", "/exam-sessions", headers=headers, params=params)

    def get_exam_session(self, session_id, headers):
        return self._request("GET", f"/exam-sessions/{session_id}", headers=headers)

    def exam_session_set_status(self, session_id, payload, headers):
        return self._request("POST", f"/exam-sessions/{session_id}/set-status", payload, headers)

    def create_exam_candidate(self, payload, headers):
        return self._request("POST", "/exam-candidates", payload, headers)

    def list_exam_candidates(self, headers, params=None):
        return self._request("GET", "/exam-candidates", headers=headers, params=params)

    def get_exam_candidate(self, candidate_id, headers):
        return self._request("GET", f"/exam-candidates/{candidate_id}", headers=headers)

    def exam_candidate_check_in(self, candidate_id, headers):
        return self._request("POST", f"/exam-candidates/{candidate_id}/check-in", {}, headers)

    def exam_candidate_record_result(self, candidate_id, payload, headers):
        return self._request("POST", f"/exam-candidates/{candidate_id}/record-result", payload, headers)

    def exam_candidate_mark_no_show(self, candidate_id, headers):
        return self._request("POST", f"/exam-candidates/{candidate_id}/mark-no-show", {}, headers)

    # ------------------------------------------------------------------
    # Equipment loans (PRD §3.8)
    # ------------------------------------------------------------------
    def create_equipment_loan(self, payload, headers):
        return self._request("POST", "/equipment-loans", payload, headers)

    def list_equipment_loans(self, headers, params=None):
        return self._request("GET", "/equipment-loans", headers=headers, params=params)

    def get_equipment_loan(self, loan_id, headers):
        return self._request("GET", f"/equipment-loans/{loan_id}", headers=headers)

    def return_equipment_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/equipment-loans/{loan_id}/return", payload, headers)

    def mark_loan_lost(self, loan_id, headers):
        return self._request("POST", f"/equipment-loans/{loan_id}/mark-lost", {}, headers)


api_client = ApiClient()
