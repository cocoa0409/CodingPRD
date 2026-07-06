"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (Ops test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/grant-desk/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/grant-desk/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/grant-desk/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/grant-desk/clients", headers=headers, params=params)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/grant-desk/clients/{client_id}/suspend", {}, headers)

    # ---- FundingOpportunity ----
    def create_opportunity(self, payload, headers):
        return self._request("POST", "/grant-desk/opportunities", payload, headers)

    def get_opportunity(self, opp_id, headers):
        return self._request("GET", f"/grant-desk/opportunities/{opp_id}", headers=headers)

    def list_opportunities(self, headers, params=None):
        return self._request("GET", "/grant-desk/opportunities", headers=headers, params=params)

    # ---- Engagement ----
    def create_engagement(self, payload, headers):
        return self._request("POST", "/grant-desk/engagements", payload, headers)

    def get_engagement(self, eng_id, headers):
        return self._request("GET", f"/grant-desk/engagements/{eng_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/grant-desk/engagements", headers=headers, params=params)

    def activate_engagement(self, eng_id, headers):
        return self._request("POST", f"/grant-desk/engagements/{eng_id}/activate", {}, headers)

    def pause_engagement(self, eng_id, headers):
        return self._request("POST", f"/grant-desk/engagements/{eng_id}/pause", {}, headers)

    def close_engagement(self, eng_id, headers):
        return self._request("POST", f"/grant-desk/engagements/{eng_id}/close", {}, headers)

    # ---- MatchAssessment ----
    def create_match(self, payload, headers):
        return self._request("POST", "/grant-desk/matches", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/grant-desk/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/grant-desk/matches", headers=headers, params=params)

    def pursue_match(self, match_id, headers):
        return self._request("POST", f"/grant-desk/matches/{match_id}/pursue", {}, headers)

    def decline_match(self, match_id, headers):
        return self._request("POST", f"/grant-desk/matches/{match_id}/decline", {}, headers)

    # ---- Proposal ----
    def create_proposal(self, payload, headers):
        return self._request("POST", "/grant-desk/proposals", payload, headers)

    def get_proposal(self, prop_id, headers):
        return self._request("GET", f"/grant-desk/proposals/{prop_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/grant-desk/proposals", headers=headers, params=params)

    def submit_proposal_for_review(self, prop_id, headers):
        return self._request("POST", f"/grant-desk/proposals/{prop_id}/submit-for-review", {}, headers)

    def request_changes_proposal(self, prop_id, headers):
        return self._request("POST", f"/grant-desk/proposals/{prop_id}/request-changes", {}, headers)

    def approve_proposal(self, prop_id, headers):
        return self._request("POST", f"/grant-desk/proposals/{prop_id}/approve", {}, headers)

    def withdraw_proposal(self, prop_id, headers):
        return self._request("POST", f"/grant-desk/proposals/{prop_id}/withdraw", {}, headers)

    # ---- BudgetLine ----
    def create_budget_line(self, payload, headers):
        return self._request("POST", "/grant-desk/budget-lines", payload, headers)

    def get_budget_line(self, line_id, headers):
        return self._request("GET", f"/grant-desk/budget-lines/{line_id}", headers=headers)

    def list_budget_lines(self, headers, params=None):
        return self._request("GET", "/grant-desk/budget-lines", headers=headers, params=params)

    # ---- Deliverable ----
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/grant-desk/deliverables", payload, headers)

    def get_deliverable(self, deliv_id, headers):
        return self._request("GET", f"/grant-desk/deliverables/{deliv_id}", headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/grant-desk/deliverables", headers=headers, params=params)

    def patch_deliverable(self, deliv_id, payload, headers):
        return self._request("PATCH", f"/grant-desk/deliverables/{deliv_id}", payload, headers)

    def advance_deliverable_content(self, deliv_id, headers):
        return self._request("POST", f"/grant-desk/deliverables/{deliv_id}/advance-content", {}, headers)

    def approve_deliverable(self, deliv_id, headers):
        return self._request("POST", f"/grant-desk/deliverables/{deliv_id}/approve", {}, headers)

    # ---- RevisionRequest ----
    def create_revision_request(self, payload, headers):
        return self._request("POST", "/grant-desk/revision-requests", payload, headers)

    def get_revision_request(self, rev_id, headers):
        return self._request("GET", f"/grant-desk/revision-requests/{rev_id}", headers=headers)

    def list_revision_requests(self, headers, params=None):
        return self._request("GET", "/grant-desk/revision-requests", headers=headers, params=params)

    def resolve_revision_request(self, rev_id, headers):
        return self._request("POST", f"/grant-desk/revision-requests/{rev_id}/resolve", {}, headers)

    # ---- Submission ----
    def create_submission(self, payload, headers):
        return self._request("POST", "/grant-desk/submissions", payload, headers)

    def get_submission(self, sub_id, headers):
        return self._request("GET", f"/grant-desk/submissions/{sub_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/grant-desk/submissions", headers=headers, params=params)

    def record_decision(self, sub_id, decision, headers):
        return self._request("POST", f"/grant-desk/submissions/{sub_id}/record-decision",
                             {"decision": decision}, headers)

    def withdraw_submission(self, sub_id, headers):
        return self._request("POST", f"/grant-desk/submissions/{sub_id}/withdraw", {}, headers)

    # ---- TimeEntry ----
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/grant-desk/time-entries", payload, headers)

    def get_time_entry(self, te_id, headers):
        return self._request("GET", f"/grant-desk/time-entries/{te_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/grant-desk/time-entries", headers=headers, params=params)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/grant-desk/invoices", payload, headers)

    def get_invoice(self, inv_id, headers):
        return self._request("GET", f"/grant-desk/invoices/{inv_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/grant-desk/invoices", headers=headers, params=params)

    def void_invoice(self, inv_id, headers):
        return self._request("POST", f"/grant-desk/invoices/{inv_id}/void", {}, headers)

    # ---- Award ----
    def create_award(self, payload, headers):
        return self._request("POST", "/grant-desk/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/grant-desk/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/grant-desk/awards", headers=headers, params=params)

    def close_out_award(self, award_id, headers):
        return self._request("POST", f"/grant-desk/awards/{award_id}/close-out", {}, headers)

    # ---- ComplianceReport ----
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/grant-desk/compliance-reports", payload, headers)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/grant-desk/compliance-reports/{report_id}", headers=headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request("GET", "/grant-desk/compliance-reports", headers=headers, params=params)

    def file_compliance_report(self, report_id, headers):
        return self._request("POST", f"/grant-desk/compliance-reports/{report_id}/file", {}, headers)

    # ---- BoilerplateSnippet ----
    def create_boilerplate(self, payload, headers):
        return self._request("POST", "/grant-desk/boilerplate", payload, headers)

    def get_boilerplate(self, snip_id, headers):
        return self._request("GET", f"/grant-desk/boilerplate/{snip_id}", headers=headers)

    def list_boilerplate(self, headers, params=None):
        return self._request("GET", "/grant-desk/boilerplate", headers=headers, params=params)

    def retire_boilerplate(self, snip_id, headers):
        return self._request("POST", f"/grant-desk/boilerplate/{snip_id}/retire", {}, headers)


api_client = ApiClient()
