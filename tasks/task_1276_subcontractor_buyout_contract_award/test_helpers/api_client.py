"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def open_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/open", headers=headers)

    def advance_clock(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/clock", payload, headers)

    def get_buyout_summary(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/buyout-summary",
                             headers=headers, params=params)

    # --- TradePackage ---
    def create_trade_package(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/trade-packages",
                             payload, headers)

    def get_trade_package(self, package_id, headers, params=None):
        return self._request("GET", f"/trade-packages/{package_id}",
                             headers=headers, params=params)

    def list_trade_packages(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/trade-packages",
                             headers=headers, params=params)

    def publish_trade_package(self, package_id, headers):
        return self._request("POST", f"/trade-packages/{package_id}/publish",
                             headers=headers)

    def close_bidding(self, package_id, headers):
        return self._request("POST", f"/trade-packages/{package_id}/close-bidding",
                             headers=headers)

    def get_replacement_analysis(self, package_id, headers):
        return self._request("GET", f"/trade-packages/{package_id}/replacement-analysis",
                             headers=headers)

    # --- Bid ---
    def create_bid(self, package_id, payload, headers):
        return self._request("POST", f"/trade-packages/{package_id}/bids",
                             payload, headers)

    def list_bids(self, package_id, headers, params=None):
        return self._request("GET", f"/trade-packages/{package_id}/bids",
                             headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, package_id, bid_id, headers):
        return self._request("POST",
                             f"/trade-packages/{package_id}/bids/{bid_id}/withdraw",
                             headers=headers)

    def award_bid(self, package_id, bid_id, headers):
        return self._request("POST",
                             f"/trade-packages/{package_id}/bids/{bid_id}/award",
                             headers=headers)

    def unaward_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/un-award", headers=headers)

    def list_bid_subcontracts(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/subcontracts",
                             headers=headers, params=params)

    # --- ScopeGap ---
    def create_gap(self, package_id, payload, headers):
        return self._request("POST", f"/trade-packages/{package_id}/gaps",
                             payload, headers)

    def list_gaps(self, package_id, headers, params=None):
        return self._request("GET", f"/trade-packages/{package_id}/gaps",
                             headers=headers, params=params)

    def get_gap(self, gap_id, headers):
        return self._request("GET", f"/gaps/{gap_id}", headers=headers)

    def resolve_gap(self, gap_id, payload, headers):
        return self._request("POST", f"/gaps/{gap_id}/resolve", payload, headers)

    def defer_gap(self, gap_id, headers):
        return self._request("POST", f"/gaps/{gap_id}/defer", headers=headers)

    def reopen_gap(self, gap_id, headers):
        return self._request("POST", f"/gaps/{gap_id}/reopen", headers=headers)

    # --- Subcontract ---
    def create_subcontract(self, package_id, payload, headers):
        return self._request("POST", f"/trade-packages/{package_id}/subcontracts",
                             payload, headers)

    def get_subcontract(self, subcontract_id, headers):
        return self._request("GET", f"/subcontracts/{subcontract_id}", headers=headers)

    def list_subcontracts(self, package_id, headers, params=None):
        return self._request("GET", f"/trade-packages/{package_id}/subcontracts",
                             headers=headers, params=params)

    def recommend_award(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/recommend-award",
                             payload, headers)

    def renegotiate(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/renegotiate",
                             payload, headers)

    def award_subcontract(self, subcontract_id, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/award",
                             headers=headers)

    def issue_subcontract(self, subcontract_id, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/issue",
                             headers=headers)

    def execute_subcontract(self, subcontract_id, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/execute",
                             headers=headers)

    def declare_default(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/declare-default",
                             payload, headers)

    def replace_subcontract(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/replace",
                             payload, headers)

    def terminate_subcontract(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/terminate",
                             payload, headers)

    def list_negotiation_rounds(self, subcontract_id, headers, params=None):
        return self._request("GET", f"/subcontracts/{subcontract_id}/negotiation-rounds",
                             headers=headers, params=params)

    def list_subcontract_sovs(self, subcontract_id, headers, params=None):
        return self._request("GET",
                             f"/subcontracts/{subcontract_id}/schedule-of-values",
                             headers=headers, params=params)

    def list_replacements(self, subcontract_id, headers, params=None):
        return self._request("GET", f"/subcontracts/{subcontract_id}/replacements",
                             headers=headers, params=params)

    # --- InsuranceCertificate ---
    def create_insurance_certificate(self, subcontract_id, payload, headers):
        return self._request("POST",
                             f"/subcontracts/{subcontract_id}/insurance-certificates",
                             payload, headers)

    def list_insurance_certificates(self, subcontract_id, headers, params=None):
        return self._request("GET",
                             f"/subcontracts/{subcontract_id}/insurance-certificates",
                             headers=headers, params=params)

    # --- BondDecision ---
    def create_bond_decision(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/bond-decision",
                             payload, headers)

    def list_bond_decisions(self, subcontract_id, headers, params=None):
        return self._request("GET", f"/subcontracts/{subcontract_id}/bond-decisions",
                             headers=headers, params=params)

    # --- ScheduleOfValues ---
    def create_sov(self, subcontract_id, payload, headers):
        return self._request("POST",
                             f"/subcontracts/{subcontract_id}/schedule-of-values",
                             payload, headers)

    def get_sov(self, sov_id, headers):
        return self._request("GET", f"/schedule-of-values/{sov_id}", headers=headers)

    def reject_sov(self, sov_id, payload, headers):
        return self._request("POST", f"/schedule-of-values/{sov_id}/reject",
                             payload, headers)

    def revise_sov(self, sov_id, payload, headers):
        return self._request("POST", f"/schedule-of-values/{sov_id}/revise",
                             payload, headers)

    def approve_sov(self, sov_id, headers):
        return self._request("POST", f"/schedule-of-values/{sov_id}/approve",
                             headers=headers)

    # --- ChangeOrder ---
    def create_change_order(self, subcontract_id, payload, headers):
        return self._request("POST", f"/subcontracts/{subcontract_id}/change-orders",
                             payload, headers)

    def list_change_orders(self, subcontract_id, headers, params=None):
        return self._request("GET", f"/subcontracts/{subcontract_id}/change-orders",
                             headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def submit_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/submit",
                             headers=headers)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve",
                             headers=headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject",
                             headers=headers)

    def void_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/void",
                             payload, headers)


api_client = ApiClient()
