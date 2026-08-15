"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Easements ---
    def create_easement(self, payload, headers):
        return self._request("POST", "/stewardship/easements", payload, headers)

    def list_easements(self, headers, params=None):
        return self._request("GET", "/stewardship/easements", headers=headers, params=params)

    def get_easement(self, easement_id, headers):
        return self._request("GET", f"/stewardship/easements/{easement_id}", headers=headers)

    def record_easement(self, easement_id, headers):
        return self._request("POST", f"/stewardship/easements/{easement_id}/record", {}, headers)

    # --- Landowners ---
    def create_landowner(self, payload, headers):
        return self._request("POST", "/stewardship/landowners", payload, headers)

    def list_landowners(self, headers, params=None):
        return self._request("GET", "/stewardship/landowners", headers=headers, params=params)

    def get_landowner(self, landowner_id, headers):
        return self._request("GET", f"/stewardship/landowners/{landowner_id}", headers=headers)

    # --- Baseline Reports ---
    def create_baseline_report(self, payload, headers):
        return self._request("POST", "/stewardship/baseline-reports", payload, headers)

    def list_baseline_reports(self, headers, params=None):
        return self._request("GET", "/stewardship/baseline-reports", headers=headers, params=params)

    def get_baseline_report(self, baseline_report_id, headers):
        return self._request("GET", f"/stewardship/baseline-reports/{baseline_report_id}", headers=headers)

    def submit_baseline_report(self, baseline_report_id, headers):
        return self._request("POST", f"/stewardship/baseline-reports/{baseline_report_id}/submit", {}, headers)

    def accept_baseline_report(self, baseline_report_id, headers):
        return self._request("POST", f"/stewardship/baseline-reports/{baseline_report_id}/accept", {}, headers)

    def request_baseline_revision(self, baseline_report_id, payload, headers):
        return self._request("POST", f"/stewardship/baseline-reports/{baseline_report_id}/request-revision", payload, headers)

    # --- Monitoring Visits ---
    def create_monitoring_visit(self, payload, headers):
        return self._request("POST", "/stewardship/monitoring-visits", payload, headers)

    def list_monitoring_visits(self, headers, params=None):
        return self._request("GET", "/stewardship/monitoring-visits", headers=headers, params=params)

    def get_monitoring_visit(self, monitoring_visit_id, headers):
        return self._request("GET", f"/stewardship/monitoring-visits/{monitoring_visit_id}", headers=headers)

    def complete_monitoring_visit(self, monitoring_visit_id, payload, headers):
        return self._request("POST", f"/stewardship/monitoring-visits/{monitoring_visit_id}/complete", payload, headers)

    def cancel_monitoring_visit(self, monitoring_visit_id, headers):
        return self._request("POST", f"/stewardship/monitoring-visits/{monitoring_visit_id}/cancel", {}, headers)

    # --- Violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/stewardship/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/stewardship/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/stewardship/violations/{violation_id}", headers=headers)

    def send_violation_notice(self, violation_id, headers):
        return self._request("POST", f"/stewardship/violations/{violation_id}/send-notice", {}, headers)

    def start_violation_cure(self, violation_id, headers):
        return self._request("POST", f"/stewardship/violations/{violation_id}/start-cure", {}, headers)

    def resolve_violation(self, violation_id, headers):
        return self._request("POST", f"/stewardship/violations/{violation_id}/resolve", {}, headers)

    def escalate_violation(self, violation_id, headers):
        return self._request("POST", f"/stewardship/violations/{violation_id}/escalate", {}, headers)

    # --- Enforcement Actions ---
    def list_enforcement_actions(self, headers, params=None):
        return self._request("GET", "/stewardship/enforcement-actions", headers=headers, params=params)

    def get_enforcement_action(self, enforcement_action_id, headers):
        return self._request("GET", f"/stewardship/enforcement-actions/{enforcement_action_id}", headers=headers)

    def execute_enforcement_action(self, enforcement_action_id, payload, headers):
        return self._request("POST", f"/stewardship/enforcement-actions/{enforcement_action_id}/execute", payload, headers)

    def complete_enforcement_action(self, enforcement_action_id, headers):
        return self._request("POST", f"/stewardship/enforcement-actions/{enforcement_action_id}/complete", {}, headers)

    def breach_enforcement_action(self, enforcement_action_id, payload, headers):
        return self._request("POST", f"/stewardship/enforcement-actions/{enforcement_action_id}/breach", payload, headers)

    def renegotiate_enforcement_action(self, enforcement_action_id, payload, headers):
        return self._request("POST", f"/stewardship/enforcement-actions/{enforcement_action_id}/renegotiate", payload, headers)

    # --- Amendment Requests ---
    def create_amendment_request(self, payload, headers):
        return self._request("POST", "/stewardship/amendment-requests", payload, headers)

    def list_amendment_requests(self, headers, params=None):
        return self._request("GET", "/stewardship/amendment-requests", headers=headers, params=params)

    def get_amendment_request(self, amendment_request_id, headers):
        return self._request("GET", f"/stewardship/amendment-requests/{amendment_request_id}", headers=headers)

    def start_amendment_review(self, amendment_request_id, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/start-review", {}, headers)

    def request_amendment_revision(self, amendment_request_id, payload, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/request-revision", payload, headers)

    def resubmit_amendment_request(self, amendment_request_id, payload, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/resubmit", payload, headers)

    def escalate_amendment_to_board(self, amendment_request_id, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/escalate-board", {}, headers)

    def approve_amendment_request(self, amendment_request_id, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/approve", {}, headers)

    def reject_amendment_request(self, amendment_request_id, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/reject", {}, headers)

    def withdraw_amendment_request(self, amendment_request_id, headers):
        return self._request("POST", f"/stewardship/amendment-requests/{amendment_request_id}/withdraw", {}, headers)

    # --- Use Authorizations ---
    def create_use_authorization(self, payload, headers):
        return self._request("POST", "/stewardship/use-authorizations", payload, headers)

    def list_use_authorizations(self, headers, params=None):
        return self._request("GET", "/stewardship/use-authorizations", headers=headers, params=params)

    def get_use_authorization(self, use_authorization_id, headers):
        return self._request("GET", f"/stewardship/use-authorizations/{use_authorization_id}", headers=headers)

    def decide_use_authorization(self, use_authorization_id, payload, headers):
        return self._request("POST", f"/stewardship/use-authorizations/{use_authorization_id}/decide", payload, headers)

    # --- Succession Notices ---
    def create_succession_notice(self, payload, headers):
        return self._request("POST", "/stewardship/succession-notices", payload, headers)

    def list_succession_notices(self, headers, params=None):
        return self._request("GET", "/stewardship/succession-notices", headers=headers, params=params)

    def get_succession_notice(self, succession_notice_id, headers):
        return self._request("GET", f"/stewardship/succession-notices/{succession_notice_id}", headers=headers)

    def acknowledge_succession_notice(self, succession_notice_id, headers):
        return self._request("POST", f"/stewardship/succession-notices/{succession_notice_id}/acknowledge", {}, headers)

    def record_succession_notice(self, succession_notice_id, payload, headers):
        return self._request("POST", f"/stewardship/succession-notices/{succession_notice_id}/record", payload, headers)

    # --- Appraisals ---
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/stewardship/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/stewardship/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/stewardship/appraisals/{appraisal_id}", headers=headers)

    def deliver_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/stewardship/appraisals/{appraisal_id}/deliver", payload, headers)

    def certify_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/stewardship/appraisals/{appraisal_id}/certify", {}, headers)

    def withdraw_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/stewardship/appraisals/{appraisal_id}/withdraw", {}, headers)

    # --- Endowment Funds & Ledger ---
    def create_endowment_fund(self, payload, headers):
        return self._request("POST", "/stewardship/endowment-funds", payload, headers)

    def list_endowment_funds(self, headers, params=None):
        return self._request("GET", "/stewardship/endowment-funds", headers=headers, params=params)

    def get_endowment_fund(self, endowment_fund_id, headers):
        return self._request("GET", f"/stewardship/endowment-funds/{endowment_fund_id}", headers=headers)

    def post_contribution(self, endowment_fund_id, payload, headers):
        return self._request("POST", f"/stewardship/endowment-funds/{endowment_fund_id}/contributions", payload, headers)

    def post_return(self, endowment_fund_id, payload, headers):
        return self._request("POST", f"/stewardship/endowment-funds/{endowment_fund_id}/returns", payload, headers)

    def post_draw(self, endowment_fund_id, payload, headers):
        return self._request("POST", f"/stewardship/endowment-funds/{endowment_fund_id}/draws", payload, headers)

    def close_fund_year(self, endowment_fund_id, headers):
        return self._request("POST", f"/stewardship/endowment-funds/{endowment_fund_id}/close-year", {}, headers)

    def list_fund_transactions(self, endowment_fund_id, headers, params=None):
        return self._request("GET", f"/stewardship/endowment-funds/{endowment_fund_id}/transactions", headers=headers, params=params)

    # --- Test-driving clock (outside the /stewardship mount) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
