"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/stop-loss/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/stop-loss/plans/{plan_id}",
                             headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/stop-loss/plans", headers=headers,
                             params=params)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/stop-loss/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/stop-loss/contracts/{contract_id}",
                             headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/stop-loss/contracts", headers=headers,
                             params=params)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/stop-loss/contracts/{contract_id}/activate", {},
            headers)

    def renew_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/stop-loss/contracts/{contract_id}/renew", payload,
            headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/stop-loss/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/stop-loss/members/{member_id}",
                             headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/stop-loss/members", headers=headers,
                             params=params)

    def terminate_member(self, member_id, payload, headers):
        return self._request(
            "POST", f"/stop-loss/members/{member_id}/terminate", payload,
            headers)

    def file_notice(self, member_id, headers):
        return self._request(
            "POST", f"/stop-loss/members/{member_id}/file-notice", {},
            headers)

    # --- Lasered terms ---
    def create_lasered_term(self, payload, headers):
        return self._request("POST", "/stop-loss/lasered-terms", payload,
                             headers)

    def rescind_lasered_term(self, laser_id, headers):
        return self._request(
            "POST", f"/stop-loss/lasered-terms/{laser_id}/rescind", {},
            headers)

    def list_lasered_terms(self, headers, params=None):
        return self._request("GET", "/stop-loss/lasered-terms",
                             headers=headers, params=params)

    def get_lasered_term(self, laser_id, headers):
        return self._request("GET", f"/stop-loss/lasered-terms/{laser_id}",
                             headers=headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/stop-loss/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/stop-loss/claims/{claim_id}",
                             headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/stop-loss/claims", headers=headers,
                             params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/stop-loss/claims/{claim_id}/adjudicate", payload,
            headers)

    def pay_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/stop-loss/claims/{claim_id}/pay",
                             payload, headers)

    def reverse_claim(self, claim_id, headers):
        return self._request("POST", f"/stop-loss/claims/{claim_id}/reverse",
                             {}, headers)

    # --- Accumulations ---
    def list_accumulations(self, headers, params=None):
        return self._request("GET", "/stop-loss/accumulations",
                             headers=headers, params=params)

    def get_accumulation(self, accumulation_id, headers):
        return self._request(
            "GET", f"/stop-loss/accumulations/{accumulation_id}",
            headers=headers)

    # --- Filings ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/stop-loss/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/stop-loss/filings/{filing_id}",
                             headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/stop-loss/filings", headers=headers,
                             params=params)

    def list_filing_line_items(self, filing_id, headers, params=None):
        return self._request(
            "GET", f"/stop-loss/filings/{filing_id}/line-items",
            headers=headers, params=params)

    def list_all_line_items(self, headers, params=None):
        return self._request("GET", "/stop-loss/filing-line-items",
                             headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request(
            "GET", f"/stop-loss/filing-line-items/{line_item_id}",
            headers=headers)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/stop-loss/filings/{filing_id}/submit",
                             {}, headers)

    def begin_review(self, filing_id, headers):
        return self._request(
            "POST", f"/stop-loss/filings/{filing_id}/begin-review", {},
            headers)

    def dispute_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/stop-loss/filings/{filing_id}/dispute", payload,
            headers)

    def resolve_dispute(self, filing_id, headers):
        return self._request(
            "POST", f"/stop-loss/filings/{filing_id}/resolve-dispute", {},
            headers)

    def approve_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/stop-loss/filings/{filing_id}/approve", payload,
            headers)

    def deny_filing(self, filing_id, headers):
        return self._request("POST", f"/stop-loss/filings/{filing_id}/deny",
                             {}, headers)

    # --- Reimbursements ---
    def create_reimbursement(self, payload, headers):
        return self._request("POST", "/stop-loss/reimbursements", payload,
                             headers)

    def get_reimbursement(self, reimbursement_id, headers):
        return self._request(
            "GET", f"/stop-loss/reimbursements/{reimbursement_id}",
            headers=headers)

    def list_reimbursements(self, headers, params=None):
        return self._request("GET", "/stop-loss/reimbursements",
                             headers=headers, params=params)

    def post_reimbursement(self, reimbursement_id, headers):
        return self._request(
            "POST", f"/stop-loss/reimbursements/{reimbursement_id}/post", {},
            headers)

    # --- Forecasts ---
    def create_forecast(self, payload, headers):
        return self._request("POST", "/stop-loss/forecasts", payload, headers)

    def get_forecast(self, forecast_id, headers):
        return self._request("GET", f"/stop-loss/forecasts/{forecast_id}",
                             headers=headers)

    def list_forecasts(self, headers, params=None):
        return self._request("GET", "/stop-loss/forecasts", headers=headers,
                             params=params)

    # --- Audits ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/stop-loss/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/stop-loss/audits/{audit_id}",
                             headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/stop-loss/audits", headers=headers,
                             params=params)

    def issue_findings(self, audit_id, headers):
        return self._request(
            "POST", f"/stop-loss/audits/{audit_id}/issue-findings", {},
            headers)

    def resolve_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/stop-loss/audits/{audit_id}/resolve",
                             payload, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/stop-loss/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
