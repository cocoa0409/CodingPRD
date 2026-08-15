"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- investigators ---
    def create_investigator(self, payload, headers):
        return self._request("POST", "/irb/investigators", payload, headers)

    def get_investigator(self, investigator_id, headers):
        return self._request("GET", f"/irb/investigators/{investigator_id}", headers=headers)

    def list_investigators(self, headers, params=None):
        return self._request("GET", "/irb/investigators", headers=headers, params=params)

    # --- IRB members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/irb/irb-members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/irb/irb-members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/irb/irb-members", headers=headers, params=params)

    def deactivate_member(self, member_id, headers):
        return self._request("POST", f"/irb/irb-members/{member_id}/deactivate", {}, headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/irb/irb-members/{member_id}/reactivate", {}, headers)

    # --- protocols ---
    def create_protocol(self, payload, headers):
        return self._request("POST", "/irb/protocols", payload, headers)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/irb/protocols/{protocol_id}", headers=headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/irb/protocols", headers=headers, params=params)

    def submit_protocol(self, protocol_id, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/submit", {}, headers)

    def return_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/return", payload, headers)

    def record_determination(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/determinations", payload, headers)

    def expedited_determination(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/expedited-determination", payload, headers)

    def withdraw_protocol(self, protocol_id, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/withdraw", {}, headers)

    def close_protocol(self, protocol_id, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/close", {}, headers)

    def reinstate_protocol(self, protocol_id, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/reinstate", {}, headers)

    # --- consent documents ---
    def upload_consent_document(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/consent-documents", payload, headers)

    def get_consent_document(self, consent_document_id, headers):
        return self._request("GET", f"/irb/consent-documents/{consent_document_id}", headers=headers)

    def list_consent_documents(self, protocol_id, headers, params=None):
        return self._request("GET", f"/irb/protocols/{protocol_id}/consent-documents", headers=headers, params=params)

    def list_consent_document_modifications(self, consent_document_id, headers, params=None):
        return self._request("GET", f"/irb/consent-documents/{consent_document_id}/modifications", headers=headers, params=params)

    def review_consent_document(self, consent_document_id, payload, headers):
        return self._request("POST", f"/irb/consent-documents/{consent_document_id}/review", payload, headers)

    # --- review assignments ---
    def create_review_assignment(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/review-assignments", payload, headers)

    def get_review_assignment(self, assignment_id, headers):
        return self._request("GET", f"/irb/review-assignments/{assignment_id}", headers=headers)

    def list_review_assignments(self, headers, params=None):
        return self._request("GET", "/irb/review-assignments", headers=headers, params=params)

    def respond_to_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/irb/review-assignments/{assignment_id}/respond", payload, headers)

    def submit_recommendation(self, assignment_id, payload, headers):
        return self._request("POST", f"/irb/review-assignments/{assignment_id}/recommendations", payload, headers)

    # --- conflict declarations ---
    def create_conflict_declaration(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/conflict-declarations", payload, headers)

    def get_conflict_declaration(self, declaration_id, headers):
        return self._request("GET", f"/irb/conflict-declarations/{declaration_id}", headers=headers)

    def list_conflict_declarations(self, headers, params=None):
        return self._request("GET", "/irb/conflict-declarations", headers=headers, params=params)

    def adjudicate_conflict_declaration(self, declaration_id, payload, headers):
        return self._request("POST", f"/irb/conflict-declarations/{declaration_id}/adjudicate", payload, headers)

    # --- board meetings & agenda ---
    def create_board_meeting(self, payload, headers):
        return self._request("POST", "/irb/board-meetings", payload, headers)

    def get_board_meeting(self, meeting_id, headers):
        return self._request("GET", f"/irb/board-meetings/{meeting_id}", headers=headers)

    def list_board_meetings(self, headers, params=None):
        return self._request("GET", "/irb/board-meetings", headers=headers, params=params)

    def add_agenda_item(self, meeting_id, payload, headers):
        return self._request("POST", f"/irb/board-meetings/{meeting_id}/agenda-items", payload, headers)

    def list_meeting_agenda_items(self, meeting_id, headers, params=None):
        return self._request("GET", f"/irb/board-meetings/{meeting_id}/agenda-items", headers=headers, params=params)

    def get_agenda_item(self, agenda_item_id, headers):
        return self._request("GET", f"/irb/agenda-items/{agenda_item_id}", headers=headers)

    def list_agenda_items(self, headers, params=None):
        return self._request("GET", "/irb/agenda-items", headers=headers, params=params)

    def convene_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"/irb/board-meetings/{meeting_id}/convene", payload, headers)

    def adjourn_meeting(self, meeting_id, headers):
        return self._request("POST", f"/irb/board-meetings/{meeting_id}/adjourn", {}, headers)

    def reschedule_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"/irb/board-meetings/{meeting_id}/reschedule", payload, headers)

    def vote_agenda_item(self, agenda_item_id, payload, headers):
        return self._request("POST", f"/irb/agenda-items/{agenda_item_id}/vote", payload, headers)

    # --- modifications ---
    def create_modification(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/modifications", payload, headers)

    def get_modification(self, modification_id, headers):
        return self._request("GET", f"/irb/modifications/{modification_id}", headers=headers)

    def list_modifications(self, protocol_id, headers, params=None):
        return self._request("GET", f"/irb/protocols/{protocol_id}/modifications", headers=headers, params=params)

    def adjudicate_modification(self, modification_id, payload, headers):
        return self._request("POST", f"/irb/modifications/{modification_id}/adjudicate", payload, headers)

    # --- continuing reviews ---
    def get_continuing_review(self, continuing_review_id, headers):
        return self._request("GET", f"/irb/continuing-reviews/{continuing_review_id}", headers=headers)

    def list_continuing_reviews(self, protocol_id, headers, params=None):
        return self._request("GET", f"/irb/protocols/{protocol_id}/continuing-reviews", headers=headers, params=params)

    def submit_continuing_review(self, continuing_review_id, headers):
        return self._request("POST", f"/irb/continuing-reviews/{continuing_review_id}/submit", {}, headers)

    def adjudicate_continuing_review(self, continuing_review_id, payload, headers):
        return self._request("POST", f"/irb/continuing-reviews/{continuing_review_id}/adjudicate", payload, headers)

    # --- adverse events ---
    def file_adverse_event(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/adverse-events", payload, headers)

    def get_adverse_event(self, adverse_event_id, headers):
        return self._request("GET", f"/irb/adverse-events/{adverse_event_id}", headers=headers)

    def list_adverse_events(self, protocol_id, headers, params=None):
        return self._request("GET", f"/irb/protocols/{protocol_id}/adverse-events", headers=headers, params=params)

    def triage_adverse_event(self, adverse_event_id, payload, headers):
        return self._request("POST", f"/irb/adverse-events/{adverse_event_id}/triage", payload, headers)

    def disposition_adverse_event(self, adverse_event_id, payload, headers):
        return self._request("POST", f"/irb/adverse-events/{adverse_event_id}/disposition", payload, headers)

    # --- non-compliance cases ---
    def create_non_compliance_case(self, protocol_id, payload, headers):
        return self._request("POST", f"/irb/protocols/{protocol_id}/non-compliance-cases", payload, headers)

    def get_non_compliance_case(self, case_id, headers):
        return self._request("GET", f"/irb/non-compliance-cases/{case_id}", headers=headers)

    def list_non_compliance_cases(self, protocol_id, headers, params=None):
        return self._request("GET", f"/irb/protocols/{protocol_id}/non-compliance-cases", headers=headers, params=params)

    def open_investigation(self, case_id, headers):
        return self._request("POST", f"/irb/non-compliance-cases/{case_id}/open-investigation", {}, headers)

    def issue_finding(self, case_id, payload, headers):
        return self._request("POST", f"/irb/non-compliance-cases/{case_id}/issue-finding", payload, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/irb/non-compliance-cases/{case_id}/close", payload, headers)

    # --- reliance agreements ---
    def create_reliance_agreement(self, payload, headers):
        return self._request("POST", "/irb/reliance-agreements", payload, headers)

    def get_reliance_agreement(self, reliance_id, headers):
        return self._request("GET", f"/irb/reliance-agreements/{reliance_id}", headers=headers)

    def list_reliance_agreements(self, headers, params=None):
        return self._request("GET", "/irb/reliance-agreements", headers=headers, params=params)

    def execute_reliance_agreement(self, reliance_id, headers):
        return self._request("POST", f"/irb/reliance-agreements/{reliance_id}/execute", {}, headers)

    def terminate_reliance_agreement(self, reliance_id, headers):
        return self._request("POST", f"/irb/reliance-agreements/{reliance_id}/terminate", {}, headers)


api_client = ApiClient()
