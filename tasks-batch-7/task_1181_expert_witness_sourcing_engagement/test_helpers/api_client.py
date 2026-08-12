"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner kills and respawns the server before every test
        # (per-test-server isolation). A pooled keep-alive connection can race
        # the kill and surface as RemoteDisconnected on the next request, so
        # force one TCP connection per request.
        self.session.headers["Connection"] = "close"

    # --- Experts ---
    def create_expert(self, payload, headers):
        return self._request("POST", "/litigation/experts", payload, headers)

    def list_experts(self, headers, params=None):
        return self._request("GET", "/litigation/experts", headers=headers, params=params)

    def get_expert(self, expert_id, headers):
        return self._request("GET", f"/litigation/experts/{expert_id}", headers=headers)

    def set_roster_status(self, expert_id, payload, headers):
        return self._request("POST", f"/litigation/experts/{expert_id}/roster-status", payload, headers)

    def list_expert_conflict_checks(self, expert_id, headers):
        return self._request("GET", f"/litigation/experts/{expert_id}/conflict-checks", headers=headers)

    def list_expert_credential_reviews(self, expert_id, headers):
        return self._request("GET", f"/litigation/experts/{expert_id}/credential-reviews", headers=headers)

    def list_expert_evaluations(self, expert_id, headers):
        return self._request("GET", f"/litigation/experts/{expert_id}/evaluations", headers=headers)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/litigation/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/litigation/cases/{case_id}", headers=headers)

    def revise_budget(self, case_id, payload, headers):
        return self._request("POST", f"/litigation/cases/{case_id}/budget-revisions", payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/litigation/cases/{case_id}/close", {}, headers)

    def list_case_engagement_requests(self, case_id, headers):
        return self._request("GET", f"/litigation/cases/{case_id}/engagement-requests", headers=headers)

    # --- Engagement requests / screening ---
    def create_engagement_request(self, payload, headers):
        return self._request("POST", "/litigation/engagement-requests", payload, headers)

    def get_engagement_request(self, request_id, headers):
        return self._request("GET", f"/litigation/engagement-requests/{request_id}", headers=headers)

    def create_conflict_check(self, request_id, payload, headers):
        return self._request("POST", f"/litigation/engagement-requests/{request_id}/conflict-checks", payload, headers)

    def list_request_conflict_checks(self, request_id, headers):
        return self._request("GET", f"/litigation/engagement-requests/{request_id}/conflict-checks", headers=headers)

    def resolve_conflict_check(self, check_id, payload, headers):
        return self._request("POST", f"/litigation/conflict-checks/{check_id}/resolve", payload, headers)

    def create_credential_review(self, request_id, payload, headers):
        return self._request("POST", f"/litigation/engagement-requests/{request_id}/credential-reviews", payload, headers)

    def list_request_credential_reviews(self, request_id, headers):
        return self._request("GET", f"/litigation/engagement-requests/{request_id}/credential-reviews", headers=headers)

    def resolve_credential_review(self, review_id, payload, headers):
        return self._request("POST", f"/litigation/credential-reviews/{review_id}/resolve", payload, headers)

    # --- Engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/litigation/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/litigation/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/litigation/engagements/{engagement_id}", headers=headers)

    def propose_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/propose", payload, headers)

    def counter_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/counter", payload, headers)

    def sign_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/sign", {}, headers)

    def fund_retainer(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/fund-retainer", payload, headers)

    def amend_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/amend", payload, headers)

    def terminate_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/terminate", payload, headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/close", {}, headers)

    # --- Document productions ---
    def create_document_production(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/document-productions", payload, headers)

    def list_document_productions(self, engagement_id, headers):
        return self._request("GET", f"/litigation/engagements/{engagement_id}/document-productions", headers=headers)

    def advance_document_production(self, production_id, payload, headers):
        return self._request("POST", f"/litigation/document-productions/{production_id}/advance", payload, headers)

    # --- Reports ---
    def create_report(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/reports", payload, headers)

    def list_reports(self, engagement_id, headers):
        return self._request("GET", f"/litigation/engagements/{engagement_id}/reports", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/litigation/reports/{report_id}/submit", {}, headers)

    def review_report(self, report_id, payload, headers):
        return self._request("POST", f"/litigation/reports/{report_id}/review", payload, headers)

    def revise_report(self, report_id, payload, headers):
        return self._request("POST", f"/litigation/reports/{report_id}/revise", payload, headers)

    def disclose_report(self, report_id, headers):
        return self._request("POST", f"/litigation/reports/{report_id}/disclose", {}, headers)

    # --- Testimony schedules / venues ---
    def create_testimony_schedule(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/testimony-schedules", payload, headers)

    def list_engagement_schedules(self, engagement_id, headers):
        return self._request("GET", f"/litigation/engagements/{engagement_id}/testimony-schedules", headers=headers)

    def list_venue_schedules(self, venue_id, headers):
        return self._request("GET", f"/litigation/venues/{venue_id}/testimony-schedules", headers=headers)

    def confirm_schedule(self, schedule_id, headers):
        return self._request("POST", f"/litigation/testimony-schedules/{schedule_id}/confirm", {}, headers)

    def cancel_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/litigation/testimony-schedules/{schedule_id}/cancel", payload, headers)

    def complete_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/litigation/testimony-schedules/{schedule_id}/complete", payload, headers)

    def create_venue(self, payload, headers):
        return self._request("POST", "/litigation/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/litigation/venues/{venue_id}", headers=headers)

    # --- Invoices ---
    def create_invoice(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/invoices", payload, headers)

    def list_invoices(self, engagement_id, headers, params=None):
        return self._request("GET", f"/litigation/engagements/{engagement_id}/invoices", headers=headers, params=params)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/litigation/invoices/{invoice_id}/approve", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/litigation/invoices/{invoice_id}/dispute", payload, headers)

    def resubmit_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/litigation/invoices/{invoice_id}/resubmit", payload, headers)

    def settle_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/litigation/invoices/{invoice_id}/settle", payload, headers)

    # --- Evaluations ---
    def create_evaluation(self, engagement_id, payload, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/evaluations", payload, headers)

    def list_engagement_evaluations(self, engagement_id, headers):
        return self._request("GET", f"/litigation/engagements/{engagement_id}/evaluations", headers=headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
