"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Trust accounts ---
    def create_trust(self, payload, headers):
        return self._request("POST", "/trusts", payload, headers)

    def list_trusts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts", headers=headers, params=params)

    def get_trust(self, trust_id, headers):
        return self._request("GET", f"/trusts/{trust_id}", headers=headers)

    def submit_for_acceptance(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/submit-for-acceptance", headers=headers)

    def accept_trust(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/accept", headers=headers)

    def decline_acceptance(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/decline-acceptance", payload, headers)

    def suspend_trust(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/suspend", payload, headers)

    def reinstate_trust(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/reinstate", headers=headers)

    def terminate_trust(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/terminate", payload, headers)

    def run_compliance_check(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/run-compliance-check", headers=headers)

    # --- Trust documents ---
    def create_document(self, payload, headers):
        return self._request("POST", "/trusts/documents", payload, headers)

    def list_documents(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/documents", headers=headers, params=params)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/trusts/documents/{document_id}", headers=headers)

    def submit_document(self, document_id, headers):
        return self._request("POST", f"/trusts/documents/{document_id}/submit", headers=headers)

    def interpret_document(self, document_id, payload, headers):
        return self._request("POST", f"/trusts/documents/{document_id}/interpret", payload, headers)

    def approve_document(self, document_id, headers):
        return self._request("POST", f"/trusts/documents/{document_id}/approve", headers=headers)

    def reject_interpretation(self, document_id, payload, headers):
        return self._request("POST", f"/trusts/documents/{document_id}/reject-interpretation", payload, headers)

    # --- Beneficiaries ---
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/trusts/beneficiaries", payload, headers)

    def list_beneficiaries(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/beneficiaries", headers=headers, params=params)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/trusts/beneficiaries/{beneficiary_id}", headers=headers)

    def mark_deceased(self, beneficiary_id, payload, headers):
        return self._request("POST", f"/trusts/beneficiaries/{beneficiary_id}/mark-deceased", payload, headers)

    # --- Committee members ---
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/trusts/committee-members", payload, headers)

    def list_committee_members(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/committee-members", headers=headers, params=params)

    def get_committee_member(self, member_id, headers):
        return self._request("GET", f"/trusts/committee-members/{member_id}", headers=headers)

    def deactivate_committee_member(self, member_id, headers):
        return self._request("POST", f"/trusts/committee-members/{member_id}/deactivate", headers=headers)

    # --- Distribution requests & votes ---
    def create_distribution_request(self, payload, headers):
        return self._request("POST", "/trusts/distribution-requests", payload, headers)

    def list_distribution_requests(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/distribution-requests", headers=headers, params=params)

    def get_distribution_request(self, request_id, headers):
        return self._request("GET", f"/trusts/distribution-requests/{request_id}", headers=headers)

    def start_review(self, request_id, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/start-review", headers=headers)

    def request_information(self, request_id, payload, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/request-information", payload, headers)

    def provide_information(self, request_id, payload, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/provide-information", payload, headers)

    def open_voting(self, request_id, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/open-voting", headers=headers)

    def cast_vote(self, request_id, payload, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/vote", payload, headers)

    def list_votes(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/votes", headers=headers, params=params)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"/trusts/votes/{vote_id}", headers=headers)

    def disburse_request(self, request_id, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/disburse", headers=headers)

    def withdraw_request(self, request_id, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/withdraw", headers=headers)

    def cancel_request(self, request_id, payload, headers):
        return self._request("POST", f"/trusts/distribution-requests/{request_id}/cancel", payload, headers)

    # --- Investment policy statements ---
    def create_ips(self, payload, headers):
        return self._request("POST", "/trusts/investment-policy-statements", payload, headers)

    def list_ips(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/investment-policy-statements", headers=headers, params=params)

    def get_ips(self, ips_id, headers):
        return self._request("GET", f"/trusts/investment-policy-statements/{ips_id}", headers=headers)

    def activate_ips(self, ips_id, headers):
        return self._request("POST", f"/trusts/investment-policy-statements/{ips_id}/activate", headers=headers)

    # --- Investment holdings ---
    def create_holding(self, payload, headers):
        return self._request("POST", "/trusts/investment-holdings", payload, headers)

    def list_holdings(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/investment-holdings", headers=headers, params=params)

    def get_holding(self, holding_id, headers):
        return self._request("GET", f"/trusts/investment-holdings/{holding_id}", headers=headers)

    def update_price(self, holding_id, payload, headers):
        return self._request("POST", f"/trusts/investment-holdings/{holding_id}/update-price", payload, headers)

    def sell_holding(self, holding_id, payload, headers):
        return self._request("POST", f"/trusts/investment-holdings/{holding_id}/sell", payload, headers)

    # --- Compliance reviews ---
    def list_compliance_reviews(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/compliance-reviews", headers=headers, params=params)

    def get_compliance_review(self, review_id, headers):
        return self._request("GET", f"/trusts/compliance-reviews/{review_id}", headers=headers)

    def plan_remediation(self, review_id, payload, headers):
        return self._request("POST", f"/trusts/compliance-reviews/{review_id}/plan-remediation", payload, headers)

    def resolve_review(self, review_id, headers):
        return self._request("POST", f"/trusts/compliance-reviews/{review_id}/resolve", headers=headers)

    def escalate_review(self, review_id, headers):
        return self._request("POST", f"/trusts/compliance-reviews/{review_id}/escalate", headers=headers)

    # --- Ledger entries ---
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/trusts/ledger-entries", payload, headers)

    def list_ledger_entries(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/trusts/ledger-entries/{entry_id}", headers=headers)

    def put_ledger_entry(self, entry_id, payload, headers):
        return self._request("PUT", f"/trusts/ledger-entries/{entry_id}", payload, headers)

    # --- Fee assessments ---
    def create_fee_assessment(self, payload, headers):
        return self._request("POST", "/trusts/fee-assessments", payload, headers)

    def list_fee_assessments(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/fee-assessments", headers=headers, params=params)

    def get_fee_assessment(self, fee_id, headers):
        return self._request("GET", f"/trusts/fee-assessments/{fee_id}", headers=headers)

    def disclose_fee(self, fee_id, headers):
        return self._request("POST", f"/trusts/fee-assessments/{fee_id}/disclose", headers=headers)

    def post_fee(self, fee_id, headers):
        return self._request("POST", f"/trusts/fee-assessments/{fee_id}/post", headers=headers)

    def dispute_fee(self, fee_id, payload, headers):
        return self._request("POST", f"/trusts/fee-assessments/{fee_id}/dispute", payload, headers)

    def recalculate_fee(self, fee_id, headers):
        return self._request("POST", f"/trusts/fee-assessments/{fee_id}/recalculate", headers=headers)

    def reverse_fee(self, fee_id, payload, headers):
        return self._request("POST", f"/trusts/fee-assessments/{fee_id}/reverse", payload, headers)

    # --- Annual statements ---
    def create_annual_statement(self, payload, headers):
        return self._request("POST", "/trusts/annual-statements", payload, headers)

    def list_annual_statements(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/annual-statements", headers=headers, params=params)

    def get_annual_statement(self, statement_id, headers):
        return self._request("GET", f"/trusts/annual-statements/{statement_id}", headers=headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/trusts/annual-statements/{statement_id}/finalize", headers=headers)

    def deliver_statement(self, statement_id, headers):
        return self._request("POST", f"/trusts/annual-statements/{statement_id}/deliver", headers=headers)

    def acknowledge_statement(self, statement_id, headers):
        return self._request("POST", f"/trusts/annual-statements/{statement_id}/acknowledge", headers=headers)

    def dispute_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/trusts/annual-statements/{statement_id}/dispute", payload, headers)

    def regenerate_statement(self, statement_id, headers):
        return self._request("POST", f"/trusts/annual-statements/{statement_id}/regenerate", headers=headers)

    # --- Tax return filings ---
    def create_tax_filing(self, payload, headers):
        return self._request("POST", "/trusts/tax-return-filings", payload, headers)

    def list_tax_filings(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/tax-return-filings", headers=headers, params=params)

    def get_tax_filing(self, filing_id, headers):
        return self._request("GET", f"/trusts/tax-return-filings/{filing_id}", headers=headers)

    def compute_tentative(self, filing_id, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/compute-tentative", headers=headers)

    def prepare_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/prepare", payload, headers)

    def submit_for_review(self, filing_id, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/submit-for-review", headers=headers)

    def approve_review(self, filing_id, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/approve-review", headers=headers)

    def record_acceptance(self, filing_id, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/record-acceptance", headers=headers)

    def require_amendment(self, filing_id, payload, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/require-amendment", payload, headers)

    def begin_amendment(self, filing_id, headers):
        return self._request("POST", f"/trusts/tax-return-filings/{filing_id}/begin-amendment", headers=headers)

    # --- Termination cases ---
    def list_termination_cases(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/trusts/termination-cases", headers=headers, params=params)

    def get_termination_case(self, case_id, headers):
        return self._request("GET", f"/trusts/termination-cases/{case_id}", headers=headers)

    def reserve_liabilities(self, case_id, payload, headers):
        return self._request("POST", f"/trusts/termination-cases/{case_id}/reserve-liabilities", payload, headers)

    def record_tax_clearance(self, case_id, headers):
        return self._request("POST", f"/trusts/termination-cases/{case_id}/record-tax-clearance", headers=headers)

    def approve_final_accounting(self, case_id, headers):
        return self._request("POST", f"/trusts/termination-cases/{case_id}/approve-final-accounting", headers=headers)

    def distribute_case(self, case_id, headers):
        return self._request("POST", f"/trusts/termination-cases/{case_id}/distribute", headers=headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/trusts/termination-cases/{case_id}/close", headers=headers)


api_client = ApiClient()
