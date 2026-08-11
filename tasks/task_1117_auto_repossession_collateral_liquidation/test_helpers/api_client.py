"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Borrowers ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def list_borrower_loan_accounts(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}/loan-accounts", headers=headers)

    def list_borrower_complaints(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}/complaints", headers=headers)

    # --- Loan accounts ---
    def create_loan_account(self, payload, headers):
        return self._request("POST", "/loan-accounts", payload, headers)

    def get_loan_account(self, loan_id, headers):
        return self._request("GET", f"/loan-accounts/{loan_id}", headers=headers)

    def list_loan_recovery_cases(self, loan_id, headers):
        return self._request("GET", f"/loan-accounts/{loan_id}/recovery-cases", headers=headers)

    # --- Recovery cases ---
    def create_recovery_case(self, payload, headers):
        return self._request("POST", "/recovery-cases", payload, headers)

    def get_recovery_case(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}", headers=headers)

    def list_recovery_cases(self, headers, params=None):
        return self._request("GET", "/recovery-cases", headers=headers, params=params)

    def close_recovery_case(self, case_id, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/close", {}, headers)

    # --- Cure notices & payments ---
    def create_cure_notice(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/cure-notices", payload, headers)

    def list_cure_notices(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/cure-notices", headers=headers)

    def create_cure_payment(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/cure-payments", payload, headers)

    # --- Ledger ---
    def create_ledger_entry(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/ledger-entries", payload, headers)

    def list_ledger_entries(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/ledger-entries", headers=headers)

    # --- Repo agents ---
    def create_repo_agent(self, payload, headers):
        return self._request("POST", "/repo-agents", payload, headers)

    def get_repo_agent(self, agent_id, headers):
        return self._request("GET", f"/repo-agents/{agent_id}", headers=headers)

    def suspend_repo_agent(self, agent_id, headers):
        return self._request("POST", f"/repo-agents/{agent_id}/suspend", {}, headers)

    def list_agent_assignments(self, agent_id, headers):
        return self._request("GET", f"/repo-agents/{agent_id}/repo-assignments", headers=headers)

    # --- Repo assignments ---
    def create_repo_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/repo-assignments", payload, headers)

    def list_case_assignments(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/repo-assignments", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/repo-assignments/{assignment_id}/accept", {}, headers)

    def report_secured(self, assignment_id, payload, headers):
        return self._request("POST", f"/repo-assignments/{assignment_id}/report-secured", payload, headers)

    def report_breach(self, assignment_id, headers):
        return self._request("POST", f"/repo-assignments/{assignment_id}/report-breach", {}, headers)

    # --- Personal property ---
    def create_property_item(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/personal-property-items", payload, headers)

    def list_property_items(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/personal-property-items", headers=headers)

    def claim_property_item(self, item_id, headers):
        return self._request("POST", f"/personal-property-items/{item_id}/claim", {}, headers)

    def unclaim_property_item(self, item_id, headers):
        return self._request("POST", f"/personal-property-items/{item_id}/unclaim", {}, headers)

    def mark_item_returned(self, item_id, headers):
        return self._request("POST", f"/personal-property-items/{item_id}/mark-returned", {}, headers)

    def dispose_property_item(self, item_id, headers):
        return self._request("POST", f"/personal-property-items/{item_id}/dispose", {}, headers)

    # --- Redemption / reinstatement ---
    def create_redemption_quote(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/redemption-quotes", payload, headers)

    def list_redemption_quotes(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/redemption-quotes", headers=headers)

    def accept_redemption_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/redemption-quotes/{quote_id}/accept", payload, headers)

    # --- Auction houses & consignments ---
    def create_auction_house(self, payload, headers):
        return self._request("POST", "/auction-houses", payload, headers)

    def get_auction_house(self, auction_house_id, headers):
        return self._request("GET", f"/auction-houses/{auction_house_id}", headers=headers)

    def list_auction_house_consignments(self, auction_house_id, headers):
        return self._request("GET", f"/auction-houses/{auction_house_id}/consignments", headers=headers)

    def create_consignment(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/consignments", payload, headers)

    def list_case_consignments(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/consignments", headers=headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}", headers=headers)

    def list_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/list", payload, headers)

    def relist_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/relist", payload, headers)

    def report_sale(self, consignment_id, payload, headers):
        return self._request("POST", f"/consignments/{consignment_id}/report-sale", payload, headers)

    def report_unsold(self, consignment_id, headers):
        return self._request("POST", f"/consignments/{consignment_id}/report-unsold", {}, headers)

    def list_sale_records(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}/sale-records", headers=headers)

    def certify_sale(self, sale_id, headers):
        return self._request("POST", f"/sale-records/{sale_id}/certify", {}, headers)

    # --- Deficiency ---
    def get_deficiency_estimate(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/deficiency-estimate", headers=headers)

    def create_deficiency_notice(self, case_id, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/deficiency-notices", {}, headers)

    def list_deficiency_notices(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/deficiency-notices", headers=headers)

    def send_deficiency_notice(self, notice_id, headers):
        return self._request("POST", f"/deficiency-notices/{notice_id}/send", {}, headers)

    def dispute_deficiency_notice(self, notice_id, headers):
        return self._request("POST", f"/deficiency-notices/{notice_id}/dispute", {}, headers)

    def revise_deficiency_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/deficiency-notices/{notice_id}/revise", payload, headers)

    def waive_deficiency_notice(self, notice_id, headers):
        return self._request("POST", f"/deficiency-notices/{notice_id}/waive", {}, headers)

    def record_deficiency_payment(self, notice_id, payload, headers):
        return self._request("POST", f"/deficiency-notices/{notice_id}/record-payment", payload, headers)

    # --- Complaints ---
    def create_complaint(self, case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{case_id}/complaints", payload, headers)

    def list_case_complaints(self, case_id, headers):
        return self._request("GET", f"/recovery-cases/{case_id}/complaints", headers=headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
