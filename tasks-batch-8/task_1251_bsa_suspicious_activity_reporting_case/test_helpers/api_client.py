"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving / ops ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/ops/jobs/daily-compliance-sweep", {}, headers)

    # ---- reference data ----
    def create_analyst(self, payload, headers):
        return self._request("POST", "/analysts", payload, headers)

    def get_analyst(self, analyst_id, headers):
        return self._request("GET", f"/analysts/{analyst_id}", headers=headers)

    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_account(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/accounts", payload, headers)

    def list_accounts(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def post_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/transactions", payload, headers)

    def list_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/transactions", headers=headers, params=params)

    # ---- monitoring scenarios & threshold versions ----
    def create_scenario(self, payload, headers):
        return self._request("POST", "/monitoring-scenarios", payload, headers)

    def get_scenario(self, scenario_id, headers):
        return self._request("GET", f"/monitoring-scenarios/{scenario_id}", headers=headers)

    def activate_scenario(self, scenario_id, headers):
        return self._request("POST", f"/monitoring-scenarios/{scenario_id}/activate", {}, headers)

    def suspend_scenario(self, scenario_id, headers):
        return self._request("POST", f"/monitoring-scenarios/{scenario_id}/suspend", {}, headers)

    def retire_scenario(self, scenario_id, headers):
        return self._request("POST", f"/monitoring-scenarios/{scenario_id}/retire", {}, headers)

    def propose_threshold(self, scenario_id, payload, headers):
        return self._request("POST", f"/monitoring-scenarios/{scenario_id}/threshold-versions", payload, headers)

    def list_thresholds(self, scenario_id, headers, params=None):
        return self._request("GET", f"/monitoring-scenarios/{scenario_id}/threshold-versions", headers=headers, params=params)

    def approve_threshold(self, threshold_id, headers):
        return self._request("POST", f"/threshold-versions/{threshold_id}/approve", {}, headers)

    def return_threshold(self, threshold_id, headers):
        return self._request("POST", f"/threshold-versions/{threshold_id}/return", {}, headers)

    def activate_threshold(self, threshold_id, headers):
        return self._request("POST", f"/threshold-versions/{threshold_id}/activate", {}, headers)

    def evaluate_scenario(self, scenario_id, payload, headers):
        return self._request("POST", f"/monitoring-scenarios/{scenario_id}/evaluate", payload, headers)

    # ---- alerts ----
    def list_alerts(self, headers, params=None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    def triage_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/triage", {}, headers)

    def dismiss_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/dismiss", payload, headers)

    def reopen_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/reopen", {}, headers)

    def link_alert_to_case(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/link-to-case", payload, headers)

    # ---- cases ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assign", payload, headers)

    def start_investigation(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/start-investigation", {}, headers)

    def record_sar_decision(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/sar-decision", payload, headers)

    def review_case_qa(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/qa-review", payload, headers)

    # ---- SARs ----
    def create_sar_report(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/sar-reports", payload, headers)

    def list_sar_reports(self, headers, params=None):
        return self._request("GET", "/sar-reports", headers=headers, params=params)

    def get_sar_report(self, sar_id, headers):
        return self._request("GET", f"/sar-reports/{sar_id}", headers=headers)

    def update_sar_narrative(self, sar_id, payload, headers):
        return self._request("PUT", f"/sar-reports/{sar_id}/narrative", payload, headers)

    def submit_sar_for_qa(self, sar_id, headers):
        return self._request("POST", f"/sar-reports/{sar_id}/submit-qa", {}, headers)

    def review_sar_qa(self, sar_id, payload, headers):
        return self._request("POST", f"/sar-reports/{sar_id}/qa-review", payload, headers)

    def approve_sar(self, sar_id, headers):
        return self._request("POST", f"/sar-reports/{sar_id}/approve", {}, headers)

    def file_sar(self, sar_id, headers):
        return self._request("POST", f"/sar-reports/{sar_id}/file", {}, headers)

    # ---- continuing reviews ----
    def list_continuing_reviews(self, sar_id, headers, params=None):
        return self._request("GET", f"/sar-reports/{sar_id}/continuing-reviews", headers=headers, params=params)

    def get_continuing_review(self, review_id, headers):
        return self._request("GET", f"/continuing-reviews/{review_id}", headers=headers)

    def start_continuing_review(self, review_id, headers):
        return self._request("POST", f"/continuing-reviews/{review_id}/start", {}, headers)

    def complete_continuing_review(self, review_id, payload, headers):
        return self._request("POST", f"/continuing-reviews/{review_id}/complete", payload, headers)

    # ---- law enforcement inquiries ----
    def create_le_inquiry(self, payload, headers):
        return self._request("POST", "/law-enforcement-inquiries", payload, headers)

    def list_le_inquiries(self, headers, params=None):
        return self._request("GET", "/law-enforcement-inquiries", headers=headers, params=params)

    def get_le_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/law-enforcement-inquiries/{inquiry_id}", headers=headers)

    def link_inquiry_to_case(self, inquiry_id, payload, headers):
        return self._request("POST", f"/law-enforcement-inquiries/{inquiry_id}/link-case", payload, headers)

    def respond_to_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/law-enforcement-inquiries/{inquiry_id}/respond", payload, headers)

    def close_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/law-enforcement-inquiries/{inquiry_id}/close", {}, headers)

    # ---- 314(b) information sharing ----
    def create_info_share(self, payload, headers):
        return self._request("POST", "/info-share-requests", payload, headers)

    def list_info_shares(self, headers, params=None):
        return self._request("GET", "/info-share-requests", headers=headers, params=params)

    def get_info_share(self, share_id, headers):
        return self._request("GET", f"/info-share-requests/{share_id}", headers=headers)

    def send_info_share(self, share_id, headers):
        return self._request("POST", f"/info-share-requests/{share_id}/send", {}, headers)

    def record_info_share_response(self, share_id, payload, headers):
        return self._request("POST", f"/info-share-requests/{share_id}/record-response", payload, headers)

    # ---- subject account decisioning ----
    def propose_account_decision(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/exit-decisions", payload, headers)

    def list_account_decisions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/exit-decisions", headers=headers, params=params)

    def get_account_decision(self, decision_id, headers):
        return self._request("GET", f"/account-decisions/{decision_id}", headers=headers)

    def approve_account_decision(self, decision_id, headers):
        return self._request("POST", f"/account-decisions/{decision_id}/approve", {}, headers)

    def execute_account_decision(self, decision_id, headers):
        return self._request("POST", f"/account-decisions/{decision_id}/execute", {}, headers)

    def reverse_account_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/account-decisions/{decision_id}/reverse", payload, headers)

    # ---- quality assurance & backlog ----
    def create_qa_review(self, payload, headers):
        return self._request("POST", "/qa-reviews", payload, headers)

    def list_qa_reviews(self, headers, params=None):
        return self._request("GET", "/qa-reviews", headers=headers, params=params)

    def get_qa_review(self, review_id, headers):
        return self._request("GET", f"/qa-reviews/{review_id}", headers=headers)

    def complete_qa_review(self, review_id, payload, headers):
        return self._request("POST", f"/qa-reviews/{review_id}/complete", payload, headers)

    def get_backlog_summary(self, headers):
        return self._request("GET", "/backlog/summary", headers=headers)


api_client = ApiClient()
