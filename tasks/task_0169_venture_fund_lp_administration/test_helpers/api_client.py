"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Fund ----
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/funds", headers=headers, params=params)

    def activate_fund(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/activate", {}, headers)

    def begin_harvest_fund(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/begin-harvest", {}, headers)

    def wind_down_fund(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/wind-down", {}, headers)

    def get_fund_nav(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}/nav", headers=headers)

    # ---- LimitedPartner ----
    def create_limited_partner(self, payload, headers):
        return self._request("POST", "/limited-partners", payload, headers)

    def get_limited_partner(self, lp_id, headers):
        return self._request("GET", f"/limited-partners/{lp_id}", headers=headers)

    # ---- Commitment ----
    def create_commitment(self, payload, headers):
        return self._request("POST", "/commitments", payload, headers)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/commitments/{commitment_id}", headers=headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", "/commitments", headers=headers, params=params)

    def accept_commitment(self, commitment_id, headers):
        return self._request("POST", f"/commitments/{commitment_id}/accept", {}, headers)

    def declare_default_commitment(self, commitment_id, headers):
        return self._request("POST", f"/commitments/{commitment_id}/declare-default", {}, headers)

    def get_commitment_statement(self, commitment_id, headers):
        return self._request("GET", f"/commitments/{commitment_id}/statement", headers=headers)

    # ---- CapitalCall ----
    def create_capital_call(self, payload, headers):
        return self._request("POST", "/capital-calls", payload, headers)

    def get_capital_call(self, call_id, headers):
        return self._request("GET", f"/capital-calls/{call_id}", headers=headers)

    def list_capital_calls(self, headers, params=None):
        return self._request("GET", "/capital-calls", headers=headers, params=params)

    def cancel_capital_call(self, call_id, headers):
        return self._request("POST", f"/capital-calls/{call_id}/cancel", {}, headers)

    def list_call_allocations(self, call_id, headers, params=None):
        return self._request("GET", f"/capital-calls/{call_id}/allocations", headers=headers, params=params)

    # ---- CapitalCallAllocation ----
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/capital-call-allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/capital-call-allocations", headers=headers, params=params)

    def fund_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/capital-call-allocations/{allocation_id}/fund", payload, headers)

    def default_allocation(self, allocation_id, headers):
        return self._request("POST", f"/capital-call-allocations/{allocation_id}/default", {}, headers)

    # ---- PortfolioCompany ----
    def create_portfolio_company(self, payload, headers):
        return self._request("POST", "/portfolio-companies", payload, headers)

    def get_portfolio_company(self, company_id, headers):
        return self._request("GET", f"/portfolio-companies/{company_id}", headers=headers)

    # ---- Investment ----
    def create_investment(self, payload, headers):
        return self._request("POST", "/investments", payload, headers)

    def get_investment(self, investment_id, headers):
        return self._request("GET", f"/investments/{investment_id}", headers=headers)

    def list_investments(self, headers, params=None):
        return self._request("GET", "/investments", headers=headers, params=params)

    def realize_investment(self, investment_id, payload, headers):
        return self._request("POST", f"/investments/{investment_id}/realize", payload, headers)

    # ---- ValuationMark ----
    def create_valuation_mark(self, payload, headers):
        return self._request("POST", "/valuation-marks", payload, headers)

    def get_valuation_mark(self, mark_id, headers):
        return self._request("GET", f"/valuation-marks/{mark_id}", headers=headers)

    def list_valuation_marks(self, headers, params=None):
        return self._request("GET", "/valuation-marks", headers=headers, params=params)

    def finalize_valuation_mark(self, mark_id, headers):
        return self._request("POST", f"/valuation-marks/{mark_id}/finalize", {}, headers)

    # ---- ManagementFeeAccrual ----
    def create_fee_accrual(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/fee-accruals", payload, headers)

    def list_fee_accruals(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/fee-accruals", headers=headers, params=params)

    def get_fee_accrual(self, accrual_id, headers):
        return self._request("GET", f"/fee-accruals/{accrual_id}", headers=headers)

    # ---- DistributionEvent ----
    def create_distribution_event(self, payload, headers):
        return self._request("POST", "/distribution-events", payload, headers)

    def get_distribution_event(self, event_id, headers):
        return self._request("GET", f"/distribution-events/{event_id}", headers=headers)

    def list_distribution_events(self, headers, params=None):
        return self._request("GET", "/distribution-events", headers=headers, params=params)

    def pay_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/pay", {}, headers)

    def recall_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/recall", {}, headers)

    def reverse_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/reverse", {}, headers)

    # ---- DistributionAllocation ----
    def get_distribution_allocation(self, allocation_id, headers):
        return self._request("GET", f"/distribution-allocations/{allocation_id}", headers=headers)

    def list_distribution_allocations(self, headers, params=None):
        return self._request("GET", "/distribution-allocations", headers=headers, params=params)

    # ---- SideLetter ----
    def create_side_letter(self, payload, headers):
        return self._request("POST", "/side-letters", payload, headers)

    def get_side_letter(self, letter_id, headers):
        return self._request("GET", f"/side-letters/{letter_id}", headers=headers)

    def list_side_letters(self, headers, params=None):
        return self._request("GET", "/side-letters", headers=headers, params=params)

    def execute_side_letter(self, letter_id, headers):
        return self._request("POST", f"/side-letters/{letter_id}/execute", {}, headers)

    # ---- Raw passthrough (for auth/pagination edge tests) ----
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
