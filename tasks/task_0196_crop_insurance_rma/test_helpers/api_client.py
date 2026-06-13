"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only the PRD-specific endpoint
methods are defined here. The inherited _request(method, path, body=None,
headers=None, params=None) performs the actual HTTP call.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Identity ─────────────────────────────────────────────────────────
    def create_producer(self, payload, headers):
        return self._request("POST", "/producers", payload, headers)

    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    # ─── CommodityProgram ─────────────────────────────────────────────────
    def create_commodity_program(self, payload, headers):
        return self._request("POST", "/commodity-programs", payload, headers)

    def get_commodity_program(self, program_id, headers):
        return self._request("GET", f"/commodity-programs/{program_id}", headers=headers)

    def list_commodity_programs(self, headers, params=None):
        return self._request("GET", "/commodity-programs", headers=headers, params=params)

    def open_commodity_program(self, program_id, headers):
        return self._request("POST", f"/commodity-programs/{program_id}/open", {}, headers)

    def close_commodity_program(self, program_id, headers):
        return self._request("POST", f"/commodity-programs/{program_id}/close", {}, headers)

    def publish_harvest_price(self, program_id, payload, headers):
        return self._request("POST", f"/commodity-programs/{program_id}/publish-harvest-price", payload, headers)

    # ─── Policy ───────────────────────────────────────────────────────────
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def list_policy_coverage_elections(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/coverage-elections", headers=headers, params=params)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/activate", {}, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    # ─── CoverageElection ─────────────────────────────────────────────────
    def create_coverage_election(self, payload, headers):
        return self._request("POST", "/coverage-elections", payload, headers)

    def get_coverage_election(self, election_id, headers):
        return self._request("GET", f"/coverage-elections/{election_id}", headers=headers)

    def list_coverage_elections(self, headers, params=None):
        return self._request("GET", "/coverage-elections", headers=headers, params=params)

    def list_election_units(self, election_id, headers, params=None):
        return self._request("GET", f"/coverage-elections/{election_id}/units", headers=headers, params=params)

    def void_coverage_election(self, election_id, payload, headers):
        return self._request("POST", f"/coverage-elections/{election_id}/void", payload, headers)

    # ─── Unit ─────────────────────────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def list_unit_acreage_reports(self, unit_id, headers, params=None):
        return self._request("GET", f"/units/{unit_id}/acreage-reports", headers=headers, params=params)

    # ─── AcreageReport ────────────────────────────────────────────────────
    def create_acreage_report(self, payload, headers):
        return self._request("POST", "/acreage-reports", payload, headers)

    def get_acreage_report(self, report_id, headers):
        return self._request("GET", f"/acreage-reports/{report_id}", headers=headers)

    def list_acreage_reports(self, headers, params=None):
        return self._request("GET", "/acreage-reports", headers=headers, params=params)

    # ─── LossClaim ────────────────────────────────────────────────────────
    def create_loss_claim(self, payload, headers):
        return self._request("POST", "/loss-claims", payload, headers)

    def get_loss_claim(self, claim_id, headers):
        return self._request("GET", f"/loss-claims/{claim_id}", headers=headers)

    def list_loss_claims(self, headers, params=None):
        return self._request("GET", "/loss-claims", headers=headers, params=params)

    def submit_loss_claim(self, claim_id, headers):
        return self._request("POST", f"/loss-claims/{claim_id}/submit", {}, headers)

    def return_loss_claim(self, claim_id, headers):
        return self._request("POST", f"/loss-claims/{claim_id}/return", {}, headers)

    def approve_loss_claim(self, claim_id, headers):
        return self._request("POST", f"/loss-claims/{claim_id}/approve", {}, headers)

    def deny_loss_claim(self, claim_id, headers):
        return self._request("POST", f"/loss-claims/{claim_id}/deny", {}, headers)

    def pay_loss_claim(self, claim_id, headers):
        return self._request("POST", f"/loss-claims/{claim_id}/pay", {}, headers)

    # ─── PreventedPlantingClaim ───────────────────────────────────────────
    def create_pp_claim(self, payload, headers):
        return self._request("POST", "/prevented-planting-claims", payload, headers)

    def get_pp_claim(self, claim_id, headers):
        return self._request("GET", f"/prevented-planting-claims/{claim_id}", headers=headers)

    def list_pp_claims(self, headers, params=None):
        return self._request("GET", "/prevented-planting-claims", headers=headers, params=params)

    def submit_pp_claim(self, claim_id, headers):
        return self._request("POST", f"/prevented-planting-claims/{claim_id}/submit", {}, headers)

    def approve_pp_claim(self, claim_id, headers):
        return self._request("POST", f"/prevented-planting-claims/{claim_id}/approve", {}, headers)

    def deny_pp_claim(self, claim_id, headers):
        return self._request("POST", f"/prevented-planting-claims/{claim_id}/deny", {}, headers)

    # ─── AgentCommission ──────────────────────────────────────────────────
    def get_agent_commission(self, commission_id, headers):
        return self._request("GET", f"/agent-commissions/{commission_id}", headers=headers)

    def list_agent_commissions(self, headers, params=None):
        return self._request("GET", "/agent-commissions", headers=headers, params=params)

    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
