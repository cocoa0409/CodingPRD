"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Coverage Plans ---
    def create_coverage_plan(self, payload, headers):
        return self._request("POST", "/coverage-plans", payload, headers)

    def list_coverage_plans(self, headers, params=None):
        return self._request("GET", "/coverage-plans", headers=headers, params=params)

    def get_coverage_plan(self, plan_id, headers):
        return self._request("GET", f"/coverage-plans/{plan_id}", headers=headers)

    def activate_coverage_plan(self, plan_id, headers):
        return self._request("POST", f"/coverage-plans/{plan_id}/activate", {}, headers)

    def retire_coverage_plan(self, plan_id, headers):
        return self._request("POST", f"/coverage-plans/{plan_id}/retire", {}, headers)

    # --- Reinsurance Pools ---
    def create_reinsurance_pool(self, payload, headers):
        return self._request("POST", "/reinsurance-pools", payload, headers)

    def list_reinsurance_pools(self, headers, params=None):
        return self._request("GET", "/reinsurance-pools", headers=headers, params=params)

    def get_reinsurance_pool(self, pool_id, headers):
        return self._request("GET", f"/reinsurance-pools/{pool_id}", headers=headers)

    def list_pool_ledger_entries(self, pool_id, headers, params=None):
        return self._request("GET", f"/reinsurance-pools/{pool_id}/ledger-entries", headers=headers, params=params)

    def list_pool_claims(self, pool_id, headers, params=None):
        return self._request("GET", f"/reinsurance-pools/{pool_id}/claims", headers=headers, params=params)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def lapse_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/lapse", {}, headers)

    def reinstate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/reinstate", {}, headers)

    def list_contract_ancillary_products(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/ancillary-products", headers=headers)

    def list_contract_claims(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/claims", headers=headers)

    def list_contract_cancellation(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/cancellation", headers=headers)

    def list_contract_ledger_entries(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/ledger-entries", headers=headers, params=params)

    # --- Ancillary Products ---
    def create_ancillary_product(self, payload, headers):
        return self._request("POST", "/ancillary-products", payload, headers)

    def get_ancillary_product(self, ancillary_id, headers):
        return self._request("GET", f"/ancillary-products/{ancillary_id}", headers=headers)

    # --- Repair Facilities ---
    def create_repair_facility(self, payload, headers):
        return self._request("POST", "/repair-facilities", payload, headers)

    def get_repair_facility(self, facility_id, headers):
        return self._request("GET", f"/repair-facilities/{facility_id}", headers=headers)

    def list_facility_claims(self, facility_id, headers, params=None):
        return self._request("GET", f"/repair-facilities/{facility_id}/claims", headers=headers, params=params)

    def list_facility_repair_authorizations(self, facility_id, headers, params=None):
        return self._request("GET", f"/repair-facilities/{facility_id}/repair-authorizations", headers=headers, params=params)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def create_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/lines", payload, headers)

    def list_claim_lines(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/lines", headers=headers)

    def start_review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/start-review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def authorize_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/authorize", {}, headers)

    # --- Repair Authorizations ---
    def get_repair_authorization(self, auth_id, headers):
        return self._request("GET", f"/repair-authorizations/{auth_id}", headers=headers)

    def list_claim_repair_authorizations(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/repair-authorizations", headers=headers)

    def disburse_repair_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"/repair-authorizations/{auth_id}/disburse", payload, headers)

    def reverse_repair_authorization(self, auth_id, headers):
        return self._request("POST", f"/repair-authorizations/{auth_id}/reverse", {}, headers)

    # --- Cancellations ---
    def create_cancellation(self, payload, headers):
        return self._request("POST", "/cancellations", payload, headers)

    def get_cancellation(self, cancellation_id, headers):
        return self._request("GET", f"/cancellations/{cancellation_id}", headers=headers)

    def approve_cancellation(self, cancellation_id, headers):
        return self._request("POST", f"/cancellations/{cancellation_id}/approve", {}, headers)

    def reject_cancellation(self, cancellation_id, headers):
        return self._request("POST", f"/cancellations/{cancellation_id}/reject", {}, headers)

    def refund_cancellation(self, cancellation_id, headers):
        return self._request("POST", f"/cancellations/{cancellation_id}/refund", {}, headers)

    # --- Clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
