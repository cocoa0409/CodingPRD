"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/appellate/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/appellate/_clock/current_utc", headers=headers)

    # --- Courts ---
    def create_court(self, payload, headers):
        return self._request("POST", "/appellate/courts", payload, headers)

    def get_court(self, court_id, headers):
        return self._request("GET", f"/appellate/courts/{court_id}", headers=headers)

    def list_courts(self, headers, params=None):
        return self._request("GET", "/appellate/courts", headers=headers, params=params)

    # --- Attorneys ---
    def create_attorney(self, payload, headers):
        return self._request("POST", "/appellate/attorneys", payload, headers)

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/appellate/attorneys/{attorney_id}", headers=headers)

    def list_attorneys(self, headers, params=None):
        return self._request("GET", "/appellate/attorneys", headers=headers, params=params)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/appellate/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/appellate/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/appellate/cases", headers=headers, params=params)

    # --- Appeal events ---
    def create_event(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/events", payload, headers)

    def list_events(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/appellate/events/{event_id}", headers=headers)

    # --- Deadlines ---
    def list_case_deadlines(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/deadlines", headers=headers, params=params)

    def get_deadline(self, deadline_id, headers):
        return self._request("GET", f"/appellate/deadlines/{deadline_id}", headers=headers)

    def list_deadlines(self, headers, params=None):
        return self._request("GET", "/appellate/deadlines", headers=headers, params=params)

    def list_event_deadlines(self, event_id, headers, params=None):
        return self._request("GET", f"/appellate/events/{event_id}/deadlines", headers=headers, params=params)

    # --- Records ---
    def get_case_record(self, case_id, headers):
        return self._request("GET", f"/appellate/cases/{case_id}/record", headers=headers)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/appellate/records/{record_id}", headers=headers)

    def designate_record(self, record_id, headers):
        return self._request("POST", f"/appellate/records/{record_id}/designate", {}, headers)

    def revoke_designation(self, record_id, headers):
        return self._request("POST", f"/appellate/records/{record_id}/revoke-designation", {}, headers)

    def file_record(self, record_id, headers):
        return self._request("POST", f"/appellate/records/{record_id}/file", {}, headers)

    # --- Transcript orders ---
    def create_transcript_order(self, record_id, payload, headers):
        return self._request("POST", f"/appellate/records/{record_id}/transcript-orders", payload, headers)

    def list_transcript_orders(self, record_id, headers, params=None):
        return self._request("GET", f"/appellate/records/{record_id}/transcript-orders", headers=headers, params=params)

    def get_transcript_order(self, transcript_id, headers):
        return self._request("GET", f"/appellate/transcript-orders/{transcript_id}", headers=headers)

    def begin_preparation(self, transcript_id, headers):
        return self._request("POST", f"/appellate/transcript-orders/{transcript_id}/begin-preparation", {}, headers)

    def deliver_transcript(self, transcript_id, payload, headers):
        return self._request("POST", f"/appellate/transcript-orders/{transcript_id}/deliver", payload, headers)

    def file_transcript(self, transcript_id, headers):
        return self._request("POST", f"/appellate/transcript-orders/{transcript_id}/file", {}, headers)

    def cancel_transcript(self, transcript_id, headers):
        return self._request("POST", f"/appellate/transcript-orders/{transcript_id}/cancel", {}, headers)

    # --- Briefing schedules ---
    def get_case_schedule(self, case_id, headers):
        return self._request("GET", f"/appellate/cases/{case_id}/briefing-schedule", headers=headers)

    def get_schedule(self, schedule_id, headers):
        return self._request("GET", f"/appellate/briefing-schedules/{schedule_id}", headers=headers)

    def vacate_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/appellate/briefing-schedules/{schedule_id}/vacate", payload, headers)

    # --- Briefs ---
    def create_brief(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/briefs", payload, headers)

    def list_case_briefs(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/briefs", headers=headers, params=params)

    def get_brief(self, brief_id, headers):
        return self._request("GET", f"/appellate/briefs/{brief_id}", headers=headers)

    def update_brief(self, brief_id, payload, headers):
        return self._request("PATCH", f"/appellate/briefs/{brief_id}", payload, headers)

    def submit_review(self, brief_id, headers):
        return self._request("POST", f"/appellate/briefs/{brief_id}/submit-review", {}, headers)

    def approve_brief(self, brief_id, headers):
        return self._request("POST", f"/appellate/briefs/{brief_id}/approve", {}, headers)

    def return_draft(self, brief_id, headers):
        return self._request("POST", f"/appellate/briefs/{brief_id}/return-draft", {}, headers)

    def efile_brief(self, brief_id, payload, headers):
        return self._request("POST", f"/appellate/briefs/{brief_id}/efile", payload, headers)

    def strike_brief(self, brief_id, payload, headers):
        return self._request("POST", f"/appellate/briefs/{brief_id}/strike", payload, headers)

    def list_schedule_briefs(self, schedule_id, headers, params=None):
        return self._request("GET", f"/appellate/briefing-schedules/{schedule_id}/briefs", headers=headers, params=params)

    def list_briefs(self, headers, params=None):
        return self._request("GET", "/appellate/briefs", headers=headers, params=params)

    def list_attorney_briefs(self, attorney_id, headers, params=None):
        return self._request("GET", f"/appellate/attorneys/{attorney_id}/briefs", headers=headers, params=params)

    # --- Table of authorities / citations ---
    def get_brief_toa(self, brief_id, headers):
        return self._request("GET", f"/appellate/briefs/{brief_id}/toa", headers=headers)

    def get_toa(self, toa_id, headers):
        return self._request("GET", f"/appellate/toas/{toa_id}", headers=headers)

    def add_citation(self, toa_id, payload, headers):
        return self._request("POST", f"/appellate/toas/{toa_id}/citations", payload, headers)

    def list_citations(self, toa_id, headers, params=None):
        return self._request("GET", f"/appellate/toas/{toa_id}/citations", headers=headers, params=params)

    def verify_citation(self, citation_id, headers):
        return self._request("POST", f"/appellate/citations/{citation_id}/verify", {}, headers)

    # --- Extension motions ---
    def create_extension_motion(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/extension-motions", payload, headers)

    def list_case_motions(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/extension-motions", headers=headers, params=params)

    def get_motion(self, motion_id, headers):
        return self._request("GET", f"/appellate/extension-motions/{motion_id}", headers=headers)

    def list_motions(self, headers, params=None):
        return self._request("GET", "/appellate/extension-motions", headers=headers, params=params)

    def list_schedule_motions(self, schedule_id, headers, params=None):
        return self._request("GET", f"/appellate/briefing-schedules/{schedule_id}/extension-motions", headers=headers, params=params)

    def grant_motion(self, motion_id, payload, headers):
        return self._request("POST", f"/appellate/extension-motions/{motion_id}/grant", payload, headers)

    def deny_motion(self, motion_id, headers):
        return self._request("POST", f"/appellate/extension-motions/{motion_id}/deny", {}, headers)

    def withdraw_motion(self, motion_id, headers):
        return self._request("POST", f"/appellate/extension-motions/{motion_id}/withdraw", {}, headers)

    # --- Filings ---
    def create_filing(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/filings", payload, headers)

    def list_case_filings(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/appellate/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/appellate/filings", headers=headers, params=params)

    def list_brief_filings(self, brief_id, headers, params=None):
        return self._request("GET", f"/appellate/briefs/{brief_id}/filings", headers=headers, params=params)

    def accept_filing(self, filing_id, headers):
        return self._request("POST", f"/appellate/filings/{filing_id}/accept", {}, headers)

    def reject_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/appellate/filings/{filing_id}/reject", payload, headers)

    # --- Oral arguments ---
    def create_oral_argument(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/oral-arguments", payload, headers)

    def list_case_oral_arguments(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/oral-arguments", headers=headers, params=params)

    def get_oral_argument(self, argument_id, headers):
        return self._request("GET", f"/appellate/oral-arguments/{argument_id}", headers=headers)

    def schedule_argument(self, argument_id, payload, headers):
        return self._request("POST", f"/appellate/oral-arguments/{argument_id}/schedule", payload, headers)

    def mark_held(self, argument_id, headers):
        return self._request("POST", f"/appellate/oral-arguments/{argument_id}/mark-held", {}, headers)

    def continue_argument(self, argument_id, headers):
        return self._request("POST", f"/appellate/oral-arguments/{argument_id}/continue", {}, headers)

    def waive_argument(self, argument_id, headers):
        return self._request("POST", f"/appellate/oral-arguments/{argument_id}/waive", {}, headers)

    def log_moot(self, argument_id, headers):
        return self._request("POST", f"/appellate/oral-arguments/{argument_id}/log-moot", {}, headers)

    # --- Decisions ---
    def create_decision(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/decisions", payload, headers)

    def list_case_decisions(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/decisions", headers=headers, params=params)

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"/appellate/decisions/{decision_id}", headers=headers)

    # --- Further-review petitions ---
    def create_petition(self, case_id, payload, headers):
        return self._request("POST", f"/appellate/cases/{case_id}/petitions", payload, headers)

    def list_case_petitions(self, case_id, headers, params=None):
        return self._request("GET", f"/appellate/cases/{case_id}/petitions", headers=headers, params=params)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/appellate/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/appellate/petitions", headers=headers, params=params)

    def list_decision_petitions(self, decision_id, headers, params=None):
        return self._request("GET", f"/appellate/decisions/{decision_id}/petitions", headers=headers, params=params)

    def file_petition(self, petition_id, headers):
        return self._request("POST", f"/appellate/petitions/{petition_id}/file", {}, headers)

    def grant_petition(self, petition_id, headers):
        return self._request("POST", f"/appellate/petitions/{petition_id}/grant", {}, headers)

    def deny_petition(self, petition_id, headers):
        return self._request("POST", f"/appellate/petitions/{petition_id}/deny", {}, headers)

    def withdraw_petition(self, petition_id, headers):
        return self._request("POST", f"/appellate/petitions/{petition_id}/withdraw", {}, headers)


api_client = ApiClient()
