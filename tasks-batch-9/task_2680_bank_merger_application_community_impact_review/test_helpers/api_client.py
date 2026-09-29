"""API client: one method per endpoint defined in the PRD.

All collections are mounted at the service root; there is no shared URL prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Institutions ---------------------------------------------------
    def create_institution(self, payload, headers):
        return self._request("POST", "/institutions", payload, headers=headers)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/institutions/{institution_id}", headers=headers)

    def list_institutions(self, headers, params=None):
        return self._request("GET", "/institutions", headers=headers, params=params)

    # --- Deposit markets ------------------------------------------------
    def create_deposit_market(self, payload, headers):
        return self._request("POST", "/deposit-markets", payload, headers=headers)

    def get_deposit_market(self, market_id, headers):
        return self._request("GET", f"/deposit-markets/{market_id}", headers=headers)

    def list_deposit_markets(self, headers, params=None):
        return self._request("GET", "/deposit-markets", headers=headers, params=params)

    # --- Branches -------------------------------------------------------
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers=headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/branches", headers=headers, params=params)

    def designate_branch(self, branch_id, payload, headers):
        return self._request("POST", f"/branches/{branch_id}/designate", payload, headers=headers)

    def rescind_branch_designation(self, branch_id, headers, payload=None):
        return self._request("POST", f"/branches/{branch_id}/rescind-designation",
                             payload if payload is not None else {}, headers=headers)

    # --- Merger applications --------------------------------------------
    def create_merger_application(self, payload, headers):
        return self._request("POST", "/merger-applications", payload, headers=headers)

    def get_merger_application(self, application_id, headers):
        return self._request("GET", f"/merger-applications/{application_id}", headers=headers)

    def list_merger_applications(self, headers, params=None):
        return self._request("GET", "/merger-applications", headers=headers, params=params)

    def amend_merger_application(self, application_id, payload, headers):
        return self._request("PATCH", f"/merger-applications/{application_id}", payload, headers=headers)

    def submit_merger_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/merger-applications/{application_id}/submit",
                             payload if payload is not None else {}, headers=headers)

    def accept_merger_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/merger-applications/{application_id}/accept",
                             payload if payload is not None else {}, headers=headers)

    def return_merger_application_for_amendment(self, application_id, payload, headers):
        return self._request("POST", f"/merger-applications/{application_id}/return-for-amendment",
                             payload, headers=headers)

    def recommend_merger_application(self, application_id, payload, headers):
        return self._request("POST", f"/merger-applications/{application_id}/recommend",
                             payload, headers=headers)

    def get_clearance_summary(self, application_id, headers):
        return self._request("GET", f"/merger-applications/{application_id}/clearance-summary",
                             headers=headers)

    # --- Pro forma capital schedules ------------------------------------
    def create_pro_forma_schedule(self, payload, headers):
        return self._request("POST", "/pro-forma-schedules", payload, headers=headers)

    def get_pro_forma_schedule(self, schedule_id, headers):
        return self._request("GET", f"/pro-forma-schedules/{schedule_id}", headers=headers)

    def list_pro_forma_schedules(self, headers, params=None):
        return self._request("GET", "/pro-forma-schedules", headers=headers, params=params)

    # --- Competitive analyses -------------------------------------------
    def create_competitive_analysis(self, payload, headers):
        return self._request("POST", "/competitive-analyses", payload, headers=headers)

    def get_competitive_analysis(self, analysis_id, headers):
        return self._request("GET", f"/competitive-analyses/{analysis_id}", headers=headers)

    def list_competitive_analyses(self, headers, params=None):
        return self._request("GET", "/competitive-analyses", headers=headers, params=params)

    # --- Comment periods ------------------------------------------------
    def create_comment_period(self, payload, headers):
        return self._request("POST", "/comment-periods", payload, headers=headers)

    def get_comment_period(self, period_id, headers):
        return self._request("GET", f"/comment-periods/{period_id}", headers=headers)

    def list_comment_periods(self, headers, params=None):
        return self._request("GET", "/comment-periods", headers=headers, params=params)

    def close_comment_period(self, period_id, headers, payload=None):
        return self._request("POST", f"/comment-periods/{period_id}/close",
                             payload if payload is not None else {}, headers=headers)

    # --- Public comments ------------------------------------------------
    def create_public_comment(self, payload, headers):
        return self._request("POST", "/public-comments", payload, headers=headers)

    def get_public_comment(self, comment_id, headers):
        return self._request("GET", f"/public-comments/{comment_id}", headers=headers)

    def list_public_comments(self, headers, params=None):
        return self._request("GET", "/public-comments", headers=headers, params=params)

    def respond_to_public_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/public-comments/{comment_id}/respond", payload, headers=headers)

    # --- Hearing requests -----------------------------------------------
    def create_hearing_request(self, payload, headers):
        return self._request("POST", "/hearing-requests", payload, headers=headers)

    def get_hearing_request(self, request_id, headers):
        return self._request("GET", f"/hearing-requests/{request_id}", headers=headers)

    def list_hearing_requests(self, headers, params=None):
        return self._request("GET", "/hearing-requests", headers=headers, params=params)

    def decide_hearing_request(self, request_id, payload, headers):
        return self._request("POST", f"/hearing-requests/{request_id}/decide", payload, headers=headers)

    def withdraw_hearing_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/hearing-requests/{request_id}/withdraw",
                             payload if payload is not None else {}, headers=headers)

    # --- Community benefits plans ---------------------------------------
    def create_benefits_plan(self, payload, headers):
        return self._request("POST", "/community-benefits-plans", payload, headers=headers)

    def get_benefits_plan(self, plan_id, headers):
        return self._request("GET", f"/community-benefits-plans/{plan_id}", headers=headers)

    def list_benefits_plans(self, headers, params=None):
        return self._request("GET", "/community-benefits-plans", headers=headers, params=params)

    def execute_benefits_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/community-benefits-plans/{plan_id}/execute",
                             payload if payload is not None else {}, headers=headers)

    # --- Commitment line items ------------------------------------------
    def create_line_item(self, payload, headers):
        return self._request("POST", "/commitment-line-items", payload, headers=headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/commitment-line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/commitment-line-items", headers=headers, params=params)

    # --- Approval decisions ---------------------------------------------
    def create_approval_decision(self, payload, headers):
        return self._request("POST", "/approval-decisions", payload, headers=headers)

    def get_approval_decision(self, decision_id, headers):
        return self._request("GET", f"/approval-decisions/{decision_id}", headers=headers)

    def list_approval_decisions(self, headers, params=None):
        return self._request("GET", "/approval-decisions", headers=headers, params=params)

    def consummate(self, decision_id, headers, payload=None):
        return self._request("POST", f"/approval-decisions/{decision_id}/consummate",
                             payload if payload is not None else {}, headers=headers)

    # --- Approval conditions --------------------------------------------
    def create_approval_condition(self, payload, headers):
        return self._request("POST", "/approval-conditions", payload, headers=headers)

    def get_approval_condition(self, condition_id, headers):
        return self._request("GET", f"/approval-conditions/{condition_id}", headers=headers)

    def list_approval_conditions(self, headers, params=None):
        return self._request("GET", "/approval-conditions", headers=headers, params=params)

    def satisfy_approval_condition(self, condition_id, headers, payload=None):
        return self._request("POST", f"/approval-conditions/{condition_id}/satisfy",
                             payload if payload is not None else {}, headers=headers)

    # --- Systems conversion plans ---------------------------------------
    def create_conversion_plan(self, payload, headers):
        return self._request("POST", "/systems-conversion-plans", payload, headers=headers)

    def get_conversion_plan(self, plan_id, headers):
        return self._request("GET", f"/systems-conversion-plans/{plan_id}", headers=headers)

    def list_conversion_plans(self, headers, params=None):
        return self._request("GET", "/systems-conversion-plans", headers=headers, params=params)

    def disclose_conversion_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/systems-conversion-plans/{plan_id}/disclose", payload, headers=headers)

    def convert_conversion_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/systems-conversion-plans/{plan_id}/convert",
                             payload if payload is not None else {}, headers=headers)

    # --- Performance reports --------------------------------------------
    def create_performance_report(self, payload, headers):
        return self._request("POST", "/performance-reports", payload, headers=headers)

    def get_performance_report(self, report_id, headers):
        return self._request("GET", f"/performance-reports/{report_id}", headers=headers)

    def list_performance_reports(self, headers, params=None):
        return self._request("GET", "/performance-reports", headers=headers, params=params)

    def review_performance_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/performance-reports/{report_id}/review",
                             payload if payload is not None else {}, headers=headers)

    def reopen_performance_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/performance-reports/{report_id}/reopen",
                             payload if payload is not None else {}, headers=headers)

    # --- Logical clock --------------------------------------------------
    def set_clock(self, now, headers):
        return self._request("POST", "/_clock/set_current_utc", {"now": now}, headers=headers)


api_client = ApiClient()
