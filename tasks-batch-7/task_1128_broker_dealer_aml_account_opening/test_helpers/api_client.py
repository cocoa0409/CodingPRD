"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock & daily sweep (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/aml/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/aml/maintenance/run-daily-sweep", {}, headers)

    # --- Registered reps (PRD §3.1) ---
    def create_rep(self, payload, headers):
        return self._request("POST", "/aml/reps", payload, headers)

    def list_reps(self, headers, params=None):
        return self._request("GET", "/aml/reps", headers=headers, params=params)

    def get_rep(self, rep_id, headers):
        return self._request("GET", f"/aml/reps/{rep_id}", headers=headers)

    def suspend_rep(self, rep_id, headers):
        return self._request("POST", f"/aml/reps/{rep_id}/suspend", {}, headers)

    def reinstate_rep(self, rep_id, headers):
        return self._request("POST", f"/aml/reps/{rep_id}/reinstate", {}, headers)

    # --- Customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/aml/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/aml/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/aml/customers/{customer_id}", headers=headers)

    # --- Identification documents (PRD §3.1) ---
    def submit_document(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/aml/customers/{customer_id}/identification-documents", payload, headers
        )

    def list_documents(self, headers, params=None):
        return self._request("GET", "/aml/identification-documents", headers=headers, params=params)

    def get_document(self, doc_id, headers):
        return self._request("GET", f"/aml/identification-documents/{doc_id}", headers=headers)

    def verify_document(self, doc_id, headers):
        return self._request("POST", f"/aml/identification-documents/{doc_id}/verify", {}, headers)

    def reject_document(self, doc_id, payload, headers):
        return self._request(
            "POST", f"/aml/identification-documents/{doc_id}/reject", payload, headers
        )

    # --- Beneficial ownership (PRD §3.2) ---
    def create_certification(self, customer_id, payload, headers):
        return self._request(
            "POST",
            f"/aml/customers/{customer_id}/beneficial-ownership-certifications",
            payload,
            headers,
        )

    def list_certifications(self, headers, params=None):
        return self._request(
            "GET", "/aml/beneficial-ownership-certifications", headers=headers, params=params
        )

    def get_certification(self, cert_id, headers):
        return self._request(
            "GET", f"/aml/beneficial-ownership-certifications/{cert_id}", headers=headers
        )

    def add_owner(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/aml/beneficial-ownership-certifications/{cert_id}/owners", payload, headers
        )

    def list_owners(self, headers, params=None):
        return self._request("GET", "/aml/beneficial-owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/aml/beneficial-owners/{owner_id}", headers=headers)

    def certify(self, cert_id, headers):
        return self._request(
            "POST", f"/aml/beneficial-ownership-certifications/{cert_id}/certify", {}, headers
        )

    # --- Brokerage accounts (PRD §3.3) ---
    def create_account(self, payload, headers):
        return self._request("POST", "/aml/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/aml/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/aml/accounts/{account_id}", headers=headers)

    def approve_account(self, account_id, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/approve", {}, headers)

    def decline_account(self, account_id, payload, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/decline", payload, headers)

    def restrict_account(self, account_id, payload, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/restrict", payload, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/reinstate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/close", {}, headers)

    def recalculate_risk(self, account_id, payload, headers):
        return self._request(
            "POST", f"/aml/accounts/{account_id}/risk-recalculations", payload, headers
        )

    # --- EDD reviews (PRD §3.4) ---
    def create_edd_review(self, account_id, payload, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/edd-reviews", payload, headers)

    def list_edd_reviews(self, headers, params=None):
        return self._request("GET", "/aml/edd-reviews", headers=headers, params=params)

    def get_edd_review(self, review_id, headers):
        return self._request("GET", f"/aml/edd-reviews/{review_id}", headers=headers)

    def begin_edd_review(self, review_id, headers):
        return self._request("POST", f"/aml/edd-reviews/{review_id}/begin", {}, headers)

    def complete_edd_review(self, review_id, payload, headers):
        return self._request("POST", f"/aml/edd-reviews/{review_id}/complete", payload, headers)

    # --- Transactions (PRD §3.5) ---
    def post_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/aml/accounts/{account_id}/transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/aml/transactions", headers=headers, params=params)

    def get_transaction(self, txn_id, headers):
        return self._request("GET", f"/aml/transactions/{txn_id}", headers=headers)

    def reverse_transaction(self, txn_id, payload, headers):
        return self._request("POST", f"/aml/transactions/{txn_id}/reverse", payload, headers)

    def clear_transaction(self, txn_id, headers):
        return self._request("POST", f"/aml/transactions/{txn_id}/clear", {}, headers)

    # --- Monitoring rules & scans (PRD §3.5) ---
    def create_rule(self, payload, headers):
        return self._request("POST", "/aml/monitoring-rules", payload, headers)

    def list_rules(self, headers, params=None):
        return self._request("GET", "/aml/monitoring-rules", headers=headers, params=params)

    def get_rule(self, rule_id, headers):
        return self._request("GET", f"/aml/monitoring-rules/{rule_id}", headers=headers)

    def update_rule(self, rule_id, payload, headers):
        return self._request("PATCH", f"/aml/monitoring-rules/{rule_id}", payload, headers)

    def run_scan(self, headers):
        return self._request("POST", "/aml/monitoring-scans/run", {}, headers)

    # --- Alerts (PRD §3.5) ---
    def list_alerts(self, headers, params=None):
        return self._request("GET", "/aml/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/aml/alerts/{alert_id}", headers=headers)

    def begin_alert_review(self, alert_id, headers):
        return self._request("POST", f"/aml/alerts/{alert_id}/begin-review", {}, headers)

    def close_alert_no_action(self, alert_id, payload, headers):
        return self._request("POST", f"/aml/alerts/{alert_id}/close-no-action", payload, headers)

    def reopen_alert(self, alert_id, headers):
        return self._request("POST", f"/aml/alerts/{alert_id}/reopen", {}, headers)

    def escalate_alert(self, alert_id, headers):
        return self._request("POST", f"/aml/alerts/{alert_id}/escalate", {}, headers)

    # --- AML cases (PRD §3.6) ---
    def create_case(self, payload, headers):
        return self._request("POST", "/aml/aml-cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/aml/aml-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/aml/aml-cases/{case_id}", headers=headers)

    def begin_investigation(self, case_id, headers):
        return self._request("POST", f"/aml/aml-cases/{case_id}/begin-investigation", {}, headers)

    def recommend_sar(self, case_id, payload, headers):
        return self._request("POST", f"/aml/aml-cases/{case_id}/recommend-sar", payload, headers)

    def decide_no_file(self, case_id, payload, headers):
        return self._request("POST", f"/aml/aml-cases/{case_id}/decide-no-file", payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/aml/aml-cases/{case_id}/close", {}, headers)

    def reopen_case(self, case_id, payload, headers):
        return self._request("POST", f"/aml/aml-cases/{case_id}/reopen", payload, headers)

    # --- SAR filings (PRD §3.6) ---
    def create_sar_filing(self, payload, headers):
        return self._request("POST", "/aml/sar-filings", payload, headers)

    def list_sar_filings(self, headers, params=None):
        return self._request("GET", "/aml/sar-filings", headers=headers, params=params)

    def get_sar_filing(self, filing_id, headers):
        return self._request("GET", f"/aml/sar-filings/{filing_id}", headers=headers)

    def file_sar(self, filing_id, headers):
        return self._request("POST", f"/aml/sar-filings/{filing_id}/file", {}, headers)

    def record_continuing_review(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/aml/sar-filings/{filing_id}/continuing-reviews", payload, headers
        )

    # --- FinCEN 314(a) (PRD §3.7) ---
    def create_fincen_request(self, payload, headers):
        return self._request("POST", "/aml/fincen-314a-requests", payload, headers)

    def list_fincen_requests(self, headers, params=None):
        return self._request("GET", "/aml/fincen-314a-requests", headers=headers, params=params)

    def get_fincen_request(self, request_id, headers):
        return self._request("GET", f"/aml/fincen-314a-requests/{request_id}", headers=headers)

    def scan_fincen_request(self, request_id, headers):
        return self._request("POST", f"/aml/fincen-314a-requests/{request_id}/scan", {}, headers)

    def submit_fincen_response(self, request_id, headers):
        return self._request(
            "POST", f"/aml/fincen-314a-requests/{request_id}/submit-response", {}, headers
        )

    def list_matches(self, headers, params=None):
        return self._request("GET", "/aml/fincen-314a-matches", headers=headers, params=params)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/aml/fincen-314a-matches/{match_id}", headers=headers)

    def confirm_match(self, match_id, headers):
        return self._request("POST", f"/aml/fincen-314a-matches/{match_id}/confirm", {}, headers)

    def mark_false_positive(self, match_id, payload, headers):
        return self._request(
            "POST", f"/aml/fincen-314a-matches/{match_id}/mark-false-positive", payload, headers
        )

    def resolve_match(self, match_id, headers):
        return self._request("POST", f"/aml/fincen-314a-matches/{match_id}/resolve", {}, headers)

    # --- Physical certificate deposits (PRD §3.8) ---
    def create_deposit(self, account_id, payload, headers):
        return self._request(
            "POST", f"/aml/accounts/{account_id}/certificate-deposits", payload, headers
        )

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/aml/certificate-deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/aml/certificate-deposits/{deposit_id}", headers=headers)

    def advance_deposit(self, deposit_id, headers):
        return self._request("POST", f"/aml/certificate-deposits/{deposit_id}/advance", {}, headers)

    def supplement_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/aml/certificate-deposits/{deposit_id}/supplement", payload, headers
        )

    def decide_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/aml/certificate-deposits/{deposit_id}/decision", payload, headers
        )

    def resubmit_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/aml/certificate-deposits/{deposit_id}/resubmit", payload, headers
        )

    # --- Lost/stolen registry (PRD §3.8) ---
    def create_lost_stolen_entry(self, payload, headers):
        return self._request("POST", "/aml/lost-stolen-certificates", payload, headers)

    def list_lost_stolen_entries(self, headers, params=None):
        return self._request("GET", "/aml/lost-stolen-certificates", headers=headers, params=params)

    def get_lost_stolen_entry(self, entry_id, headers):
        return self._request("GET", f"/aml/lost-stolen-certificates/{entry_id}", headers=headers)

    # --- Independent testing & audit (PRD §3.9) ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/aml/audit-engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/aml/audit-engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/aml/audit-engagements/{engagement_id}", headers=headers)

    def begin_fieldwork(self, engagement_id, headers):
        return self._request(
            "POST", f"/aml/audit-engagements/{engagement_id}/begin-fieldwork", {}, headers
        )

    def issue_report(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/aml/audit-engagements/{engagement_id}/issue-report", payload, headers
        )

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/aml/audit-engagements/{engagement_id}/close", {}, headers)

    def create_finding(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/aml/audit-engagements/{engagement_id}/findings", payload, headers
        )

    def list_findings(self, headers, params=None):
        return self._request("GET", "/aml/audit-findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/aml/audit-findings/{finding_id}", headers=headers)

    def submit_remediation(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/aml/audit-findings/{finding_id}/submit-remediation", payload, headers
        )

    def verify_remediation(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/aml/audit-findings/{finding_id}/verify-remediation", payload, headers
        )

    def accept_risk(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/aml/audit-findings/{finding_id}/accept-risk", payload, headers
        )


api_client = ApiClient()
