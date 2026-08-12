"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Funders ----
    def create_funder(self, payload, headers):
        return self._request("POST", "/funders", payload, headers)

    def get_funder(self, funder_id, headers):
        return self._request("GET", f"/funders/{funder_id}", headers=headers)

    # ---- Grants ----
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def get_grant_summary(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}/summary", headers=headers)

    def activate_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/activate", {}, headers)

    def closeout_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/closeout", {}, headers)

    # ---- Budget lines ----
    def create_budget_line(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/budget-lines", payload, headers)

    def list_budget_lines(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/budget-lines", headers=headers, params=params)

    def get_budget_line(self, budget_line_id, headers):
        return self._request("GET", f"/budget-lines/{budget_line_id}", headers=headers)

    def list_budget_line_variance_explanations(self, budget_line_id, headers, params=None):
        return self._request(
            "GET", f"/budget-lines/{budget_line_id}/variance-explanations",
            headers=headers, params=params,
        )

    # ---- Funds ----
    def create_fund(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/funds", payload, headers)

    def list_funds(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/funds", headers=headers, params=params)

    # ---- Expenses ----
    def create_expense(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/expenses", payload, headers)

    def list_expenses(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/expenses", headers=headers, params=params)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expenses/{expense_id}", headers=headers)

    def post_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/post", {}, headers)

    def void_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/void", {}, headers)

    def create_allocation(self, expense_id, payload, headers):
        return self._request("POST", f"/expenses/{expense_id}/allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    # ---- Reports ----
    def list_reports(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def update_report(self, report_id, payload, headers):
        return self._request("PUT", f"/reports/{report_id}", payload, headers)

    def start_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/start", {}, headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/submit", {}, headers)

    def start_review_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/start-review", {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/accept", {}, headers)

    def return_report(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/return", payload, headers)

    def revise_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/revise", {}, headers)

    def create_variance_explanation(self, report_id, payload, headers):
        return self._request(
            "POST", f"/reports/{report_id}/variance-explanations", payload, headers
        )

    def list_variance_explanations(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/reports/{report_id}/variance-explanations",
            headers=headers, params=params,
        )

    # ---- Match contributions ----
    def create_match_contribution(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/grants/{grant_id}/match-contributions", payload, headers
        )

    def list_match_contributions(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/grants/{grant_id}/match-contributions",
            headers=headers, params=params,
        )

    def document_match_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"/match-contributions/{contribution_id}/document", payload, headers
        )

    def verify_match_contribution(self, contribution_id, headers):
        return self._request(
            "POST", f"/match-contributions/{contribution_id}/verify", {}, headers
        )

    # ---- Modification requests ----
    def create_modification_request(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/grants/{grant_id}/modification-requests", payload, headers
        )

    def list_modification_requests(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/grants/{grant_id}/modification-requests",
            headers=headers, params=params,
        )

    def submit_modification_request(self, request_id, headers):
        return self._request(
            "POST", f"/modification-requests/{request_id}/submit", {}, headers
        )

    def approve_modification_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/modification-requests/{request_id}/approve", payload, headers
        )

    def deny_modification_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/modification-requests/{request_id}/deny", payload, headers
        )

    def withdraw_modification_request(self, request_id, headers):
        return self._request(
            "POST", f"/modification-requests/{request_id}/withdraw", {}, headers
        )

    # ---- Audit engagements & findings ----
    def create_audit_engagement(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/grants/{grant_id}/audit-engagements", payload, headers
        )

    def list_audit_engagements(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/grants/{grant_id}/audit-engagements",
            headers=headers, params=params,
        )

    def get_audit_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"/audit-engagements/{engagement_id}", headers=headers
        )

    def advance_audit_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/audit-engagements/{engagement_id}/advance", {}, headers
        )

    def create_audit_finding(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/audit-engagements/{engagement_id}/findings", payload, headers
        )

    def list_audit_findings(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/audit-engagements/{engagement_id}/findings",
            headers=headers, params=params,
        )

    def respond_audit_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/audit-findings/{finding_id}/respond", payload, headers
        )

    def resolve_audit_finding(self, finding_id, headers):
        return self._request("POST", f"/audit-findings/{finding_id}/resolve", {}, headers)

    def reopen_audit_finding(self, finding_id, headers):
        return self._request("POST", f"/audit-findings/{finding_id}/reopen", {}, headers)

    # ---- Renewal applications ----
    def create_renewal_application(self, grant_id, headers):
        return self._request(
            "POST", f"/grants/{grant_id}/renewal-applications", {}, headers
        )

    def list_renewal_applications(self, grant_id, headers):
        return self._request(
            "GET", f"/grants/{grant_id}/renewal-applications", headers=headers
        )

    def submit_renewal_application(self, application_id, headers):
        return self._request(
            "POST", f"/renewal-applications/{application_id}/submit", {}, headers
        )

    def decide_renewal_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/renewal-applications/{application_id}/decide", payload, headers
        )

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
