"""API client: one method per endpoint defined in the PRD (§4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------
    # Producers
    # ---------------------------------------------------------------
    def create_agent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/agents", payload, headers)

    def update_agent(self, agent_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/agents/{agent_id}", payload, headers)

    def get_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    # ---------------------------------------------------------------
    # Inspectors
    # ---------------------------------------------------------------
    def create_inspector(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/inspectors", payload, headers)

    def update_inspector(self, inspector_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/inspectors/{inspector_id}", payload, headers)

    def get_inspector(self, inspector_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    # ---------------------------------------------------------------
    # Catastrophe capacity pools
    # ---------------------------------------------------------------
    def create_cat_capacity_pool(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cat-capacity-pools", payload, headers)

    def get_cat_capacity_pool(self, pool_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cat-capacity-pools/{pool_id}", headers=headers)

    def list_cat_capacity_pools(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cat-capacity-pools", headers=headers, params=params)

    def update_cat_capacity_pool(self, pool_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/cat-capacity-pools/{pool_id}", payload, headers)

    # ---------------------------------------------------------------
    # Farm accounts
    # ---------------------------------------------------------------
    def create_farm_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/farm-accounts", payload, headers)

    def get_farm_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/farm-accounts/{account_id}", headers=headers)

    def list_farm_accounts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/farm-accounts", headers=headers, params=params)

    # ---------------------------------------------------------------
    # Farm policies
    # ---------------------------------------------------------------
    def create_farm_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/farm-policies", payload, headers)

    def get_farm_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/farm-policies/{policy_id}", headers=headers)

    def list_farm_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/farm-policies", headers=headers, params=params)

    # ---------------------------------------------------------------
    # Scheduled items
    # ---------------------------------------------------------------
    def create_scheduled_item(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/scheduled-items", payload, headers)

    def list_scheduled_items(self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/farm-policies/{policy_id}/scheduled-items", headers=headers, params=params
        )

    def get_scheduled_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/scheduled-items/{item_id}", headers=headers)

    def update_scheduled_item(self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/scheduled-items/{item_id}", payload, headers)

    # ---------------------------------------------------------------
    # Livestock groups
    # ---------------------------------------------------------------
    def create_livestock_group(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/livestock-groups", payload, headers)

    def list_livestock_groups(self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/farm-policies/{policy_id}/livestock-groups", headers=headers, params=params
        )

    # ---------------------------------------------------------------
    # Liability exposures
    # ---------------------------------------------------------------
    def create_liability_exposure(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/liability-exposures", payload, headers)

    def list_liability_exposures(self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/farm-policies/{policy_id}/liability-exposures", headers=headers, params=params
        )

    # ---------------------------------------------------------------
    # Labor profile and workers-compensation coordination
    # ---------------------------------------------------------------
    def upsert_labor_profile(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/farm-policies/{policy_id}/labor-profile", payload, headers)

    def get_policy_labor_profile(self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/farm-policies/{policy_id}/labor-profile", headers=headers, params=params
        )

    def get_labor_profile(self, labor_profile_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/labor-profiles/{labor_profile_id}", headers=headers)

    def verify_wc_coordination(
        self, labor_profile_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/labor-profiles/{labor_profile_id}/wc-verification", payload, headers
        )

    # ---------------------------------------------------------------
    # Policy lifecycle
    # ---------------------------------------------------------------
    def rate_farm_policy(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/rate", payload, headers)

    def decide_referral(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/referral-decisions", payload, headers)

    def bind_farm_policy(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/bind", payload, headers)

    def decline_farm_policy(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/decline", payload, headers)

    def cancel_farm_policy(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/cancel", payload, headers)

    # ---------------------------------------------------------------
    # Premium ledger
    # ---------------------------------------------------------------
    def list_premium_transactions(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/farm-policies/{policy_id}/premium-transactions", headers=headers, params=params
        )

    # ---------------------------------------------------------------
    # Endorsements
    # ---------------------------------------------------------------
    def create_endorsement(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/farm-policies/{policy_id}/endorsements", payload, headers)

    def list_endorsements(self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/farm-policies/{policy_id}/endorsements", headers=headers, params=params
        )

    def get_endorsement(self, endorsement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/endorsements/{endorsement_id}", headers=headers)

    def decide_endorsement(self, endorsement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/endorsements/{endorsement_id}/decision", payload, headers)

    def rescind_endorsement(self, endorsement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/endorsements/{endorsement_id}/rescind", payload, headers)

    # ---------------------------------------------------------------
    # Catastrophe reservations
    # ---------------------------------------------------------------
    def get_cat_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cat-reservations/{reservation_id}", headers=headers)

    def list_cat_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cat-reservations", headers=headers, params=params)

    # ---------------------------------------------------------------
    # Inspections
    # ---------------------------------------------------------------
    def create_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/inspections/{inspection_id}/complete", payload, headers)

    def reinspect_inspection(self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/inspections/{inspection_id}/reinspection", payload, headers)

    # ---------------------------------------------------------------
    # Recommendations
    # ---------------------------------------------------------------
    def list_recommendations(
        self, inspection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/inspections/{inspection_id}/recommendations", headers=headers, params=params
        )

    def get_recommendation(self, recommendation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/recommendations/{recommendation_id}", headers=headers)

    def submit_recommendation_evidence(
        self, recommendation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/recommendations/{recommendation_id}/evidence", payload, headers)

    def review_recommendation(
        self, recommendation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/recommendations/{recommendation_id}/review", payload, headers)

    # ---------------------------------------------------------------
    # System drivers
    # ---------------------------------------------------------------
    def run_compliance_sweep(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compliance-sweeps", payload, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        """The clock setter is the only route that requires no headers at all."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers or {})


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
