"""API client: one method per endpoint defined in the PRD (§4 address map)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Campaign ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/fafsa/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/fafsa/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/fafsa/campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/fafsa/campaigns/{campaign_id}/activate", headers=headers
        )

    # --- School ---
    def create_school(self, payload, headers):
        return self._request("POST", "/fafsa/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/fafsa/schools", headers=headers, params=params)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/fafsa/schools/{school_id}", headers=headers)

    def enroll_school(self, school_id, headers):
        return self._request("POST", f"/fafsa/schools/{school_id}/enroll", headers=headers)

    def suspend_school(self, school_id, headers):
        return self._request(
            "POST", f"/fafsa/schools/{school_id}/suspend", headers=headers
        )

    def reinstate_school(self, school_id, headers):
        return self._request(
            "POST", f"/fafsa/schools/{school_id}/reinstate", headers=headers
        )

    # --- StaffProfile ---
    def create_staff_profile(self, payload, headers):
        return self._request("POST", "/fafsa/staff-profiles", payload, headers)

    def list_staff_profiles(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/staff-profiles", headers=headers, params=params
        )

    def get_staff_profile(self, staff_id, headers):
        return self._request(
            "GET", f"/fafsa/staff-profiles/{staff_id}", headers=headers
        )

    def record_background_check(self, staff_id, result, headers):
        return self._request(
            "POST",
            f"/fafsa/staff-profiles/{staff_id}/background-check",
            {"result": result},
            headers,
        )

    # --- SeniorRecord ---
    def create_senior_record(self, payload, headers):
        return self._request("POST", "/fafsa/senior-records", payload, headers)

    def list_senior_records(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/senior-records", headers=headers, params=params
        )

    def get_senior_record(self, senior_id, headers):
        return self._request(
            "GET", f"/fafsa/senior-records/{senior_id}", headers=headers
        )

    # --- AidRecord / AidStatusEvent ---
    def create_aid_record(self, payload, headers):
        return self._request("POST", "/fafsa/aid-records", payload, headers)

    def list_aid_records(self, headers, params=None):
        return self._request("GET", "/fafsa/aid-records", headers=headers, params=params)

    def get_aid_record(self, aid_record_id, headers):
        return self._request(
            "GET", f"/fafsa/aid-records/{aid_record_id}", headers=headers
        )

    def append_status_event(self, aid_record_id, payload, headers):
        return self._request(
            "POST", f"/fafsa/aid-records/{aid_record_id}/status-events", payload, headers
        )

    def list_status_events(self, aid_record_id, headers, params=None):
        return self._request(
            "GET",
            f"/fafsa/aid-records/{aid_record_id}/status-events",
            headers=headers,
            params=params,
        )

    # --- MatchLink ---
    def create_match_link(self, payload, headers):
        return self._request("POST", "/fafsa/match-links", payload, headers)

    def list_match_links(self, headers, params=None):
        return self._request("GET", "/fafsa/match-links", headers=headers, params=params)

    def get_match_link(self, link_id, headers):
        return self._request("GET", f"/fafsa/match-links/{link_id}", headers=headers)

    def confirm_match_link(self, link_id, headers):
        return self._request(
            "POST", f"/fafsa/match-links/{link_id}/confirm", headers=headers
        )

    def reject_match_link(self, link_id, headers):
        return self._request(
            "POST", f"/fafsa/match-links/{link_id}/reject", headers=headers
        )

    def invalidate_match_link(self, link_id, headers):
        return self._request(
            "POST", f"/fafsa/match-links/{link_id}/invalidate", headers=headers
        )

    # --- ConsentRecord ---
    def create_consent_record(self, payload, headers):
        return self._request("POST", "/fafsa/consent-records", payload, headers)

    def list_consent_records(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/consent-records", headers=headers, params=params
        )

    def get_consent_record(self, consent_id, headers):
        return self._request(
            "GET", f"/fafsa/consent-records/{consent_id}", headers=headers
        )

    def revoke_consent(self, consent_id, headers):
        return self._request(
            "POST", f"/fafsa/consent-records/{consent_id}/revoke", headers=headers
        )

    def regrant_consent(self, consent_id, headers):
        return self._request(
            "POST", f"/fafsa/consent-records/{consent_id}/regrant", headers=headers
        )

    # --- CompletionEvent ---
    def create_event(self, payload, headers):
        return self._request("POST", "/fafsa/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/fafsa/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/fafsa/events/{event_id}", headers=headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/fafsa/events/{event_id}/publish", headers=headers)

    def unpublish_event(self, event_id, headers):
        return self._request(
            "POST", f"/fafsa/events/{event_id}/unpublish", headers=headers
        )

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/fafsa/events/{event_id}/cancel", headers=headers)

    def complete_event(self, event_id, actual_cost_cents, headers):
        return self._request(
            "POST",
            f"/fafsa/events/{event_id}/complete",
            {"actual_cost_cents": actual_cost_cents},
            headers,
        )

    # --- StaffAssignment ---
    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/fafsa/staff-assignments", payload, headers)

    def list_staff_assignments(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/staff-assignments", headers=headers, params=params
        )

    def get_staff_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/fafsa/staff-assignments/{assignment_id}", headers=headers
        )

    def accept_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/fafsa/staff-assignments/{assignment_id}/accept", headers=headers
        )

    def decline_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/fafsa/staff-assignments/{assignment_id}/decline", headers=headers
        )

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/fafsa/staff-assignments/{assignment_id}/confirm", headers=headers
        )

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/fafsa/staff-assignments/{assignment_id}/cancel", headers=headers
        )

    def check_in_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/fafsa/staff-assignments/{assignment_id}/check-in", headers=headers
        )

    # --- EventRegistration ---
    def create_event_registration(self, payload, headers):
        return self._request("POST", "/fafsa/event-registrations", payload, headers)

    def list_event_registrations(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/event-registrations", headers=headers, params=params
        )

    def get_event_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/fafsa/event-registrations/{registration_id}", headers=headers
        )

    def cancel_event_registration(self, registration_id, headers):
        return self._request(
            "POST",
            f"/fafsa/event-registrations/{registration_id}/cancel",
            headers=headers,
        )

    # --- DocumentChecklist / ChecklistItem ---
    def list_document_checklists(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/document-checklists", headers=headers, params=params
        )

    def get_document_checklist(self, checklist_id, headers):
        return self._request(
            "GET", f"/fafsa/document-checklists/{checklist_id}", headers=headers
        )

    def list_checklist_items(self, checklist_id, headers, params=None):
        return self._request(
            "GET",
            f"/fafsa/document-checklists/{checklist_id}/items",
            headers=headers,
            params=params,
        )

    def receive_checklist_item(self, item_id, headers):
        return self._request(
            "POST", f"/fafsa/checklist-items/{item_id}/receive", headers=headers
        )

    def verify_checklist_item(self, item_id, headers):
        return self._request(
            "POST", f"/fafsa/checklist-items/{item_id}/verify", headers=headers
        )

    def reject_checklist_item(self, item_id, headers):
        return self._request(
            "POST", f"/fafsa/checklist-items/{item_id}/reject", headers=headers
        )

    def waive_checklist_item(self, item_id, headers):
        return self._request(
            "POST", f"/fafsa/checklist-items/{item_id}/waive", headers=headers
        )

    # --- SupportCase ---
    def create_support_case(self, payload, headers):
        return self._request("POST", "/fafsa/support-cases", payload, headers)

    def list_support_cases(self, headers, params=None):
        return self._request("GET", "/fafsa/support-cases", headers=headers, params=params)

    def get_support_case(self, case_id, headers):
        return self._request("GET", f"/fafsa/support-cases/{case_id}", headers=headers)

    def assign_support_case(self, case_id, specialist_id, headers):
        return self._request(
            "POST",
            f"/fafsa/support-cases/{case_id}/assign",
            {"specialist_id": specialist_id},
            headers,
        )

    def accept_support_case(self, case_id, headers):
        return self._request(
            "POST", f"/fafsa/support-cases/{case_id}/accept", headers=headers
        )

    def request_documents(self, case_id, headers):
        return self._request(
            "POST", f"/fafsa/support-cases/{case_id}/request-documents", headers=headers
        )

    def documents_received(self, case_id, headers):
        return self._request(
            "POST",
            f"/fafsa/support-cases/{case_id}/documents-received",
            headers=headers,
        )

    def escalate_support_case(self, case_id, headers):
        return self._request(
            "POST", f"/fafsa/support-cases/{case_id}/escalate", headers=headers
        )

    def resolve_support_case(self, case_id, headers, resolution_outcome=None):
        payload = {}
        if resolution_outcome is not None:
            payload["resolution_outcome"] = resolution_outcome
        return self._request(
            "POST", f"/fafsa/support-cases/{case_id}/resolve", payload, headers
        )

    # --- CompletionReport ---
    def create_completion_report(self, payload, headers):
        return self._request("POST", "/fafsa/completion-reports", payload, headers)

    def list_completion_reports(self, headers, params=None):
        return self._request(
            "GET", "/fafsa/completion-reports", headers=headers, params=params
        )

    def get_completion_report(self, report_id, headers):
        return self._request(
            "GET", f"/fafsa/completion-reports/{report_id}", headers=headers
        )

    def publish_completion_report(self, report_id, expected_campaign_version, headers):
        return self._request(
            "POST",
            f"/fafsa/completion-reports/{report_id}/publish",
            {"expected_campaign_version": expected_campaign_version},
            headers,
        )


api_client = ApiClient()
