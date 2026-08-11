"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Home Inventory & Valuables Vault API."""

    # --- Logical clock (outside the /vault mount) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Members ---
    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/members/{member_id}", headers=headers)

    def list_members(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/members", headers=headers, params=params)

    # --- Households ---
    def create_household(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/households", payload, headers)

    def get_household(self, household_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/households/{household_id}", headers=headers)

    def list_households(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/households", headers=headers, params=params)

    # --- Subscriptions ---
    def create_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/subscriptions", payload, headers)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vault/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/vault/subscriptions", headers=headers, params=params
        )

    def billing_event(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/vault/subscriptions/{subscription_id}/billing-event",
            payload,
            headers,
        )

    def change_tier(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/vault/subscriptions/{subscription_id}/change-tier",
            payload,
            headers,
        )

    def attest_refresh(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/vault/subscriptions/{subscription_id}/attest-refresh",
            payload,
            headers,
        )

    def reinstate_subscription(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/vault/subscriptions/{subscription_id}/reinstate",
            payload,
            headers,
        )

    # --- Rooms ---
    def create_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/rooms", payload, headers)

    def get_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/rooms", headers=headers, params=params)

    # --- Items ---
    def create_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/items", payload, headers)

    def get_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/items/{item_id}", headers=headers)

    def list_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/items", headers=headers, params=params)

    def patch_item(self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/vault/items/{item_id}", payload, headers)

    def declare_value(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/items/{item_id}/declare-value", payload, headers
        )

    def schedule_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/items/{item_id}/schedule", payload, headers
        )

    def unschedule_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/items/{item_id}/unschedule", payload, headers
        )

    def replace_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/vault/items/{item_id}/replace", payload, headers)

    def upload_asset(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/vault/items/{item_id}/assets", payload, headers)

    # --- Assets ---
    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/assets/{asset_id}", headers=headers)

    def list_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/assets", headers=headers, params=params)

    def delete_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/vault/assets/{asset_id}", headers=headers)

    # --- Category schedules ---
    def create_category_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/category-schedules", payload, headers)

    def list_category_schedules(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/vault/category-schedules", headers=headers, params=params
        )

    # --- Appraisers ---
    def create_appraiser(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/appraisers/{appraiser_id}", headers=headers)

    def list_appraisers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/appraisers", headers=headers, params=params)

    def suspend_appraiser(
        self, appraiser_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/appraisers/{appraiser_id}/suspend", payload, headers
        )

    # --- Appraisals ---
    def create_appraisal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/appraisals", headers=headers, params=params)

    def certify_appraisal(
        self, appraisal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/appraisals/{appraisal_id}/certify", payload, headers
        )

    def void_appraisal(
        self, appraisal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/appraisals/{appraisal_id}/void", payload, headers
        )

    # --- Policies ---
    def create_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/policies", payload, headers)

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/policies/{policy_id}", headers=headers)

    def list_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/policies", headers=headers, params=params)

    def patch_policy(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/vault/policies/{policy_id}", payload, headers)

    def get_coverage_gap(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/vault/policies/{policy_id}/coverage-gap",
            headers=headers,
            params=params,
        )

    # --- Documentation packages ---
    def create_package(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/packages", payload, headers)

    def get_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/packages/{package_id}", headers=headers)

    def list_packages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/packages", headers=headers, params=params)

    def generate_package(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/packages/{package_id}/generate", payload, headers
        )

    def deliver_package(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/packages/{package_id}/deliver", payload, headers
        )

    def get_package_line(self, package_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vault/package-lines/{package_line_id}", headers=headers
        )

    def list_package_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/vault/package-lines", headers=headers, params=params
        )

    # --- Loss claims ---
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/claims", headers=headers, params=params)

    def add_claim_line(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/vault/claims/{claim_id}/lines", payload, headers)

    def get_claim_line(self, claim_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vault/claim-lines/{claim_line_id}", headers=headers
        )

    def list_claim_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/claim-lines", headers=headers, params=params)

    def submit_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/claims/{claim_id}/submit", payload, headers
        )

    def adjudicate_claim_line(
        self, claim_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/claim-lines/{claim_line_id}/adjudicate", payload, headers
        )

    def appeal_claim_line(
        self, claim_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/claim-lines/{claim_line_id}/appeal", payload, headers
        )

    def settle_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/claims/{claim_id}/settle", payload, headers
        )

    def withdraw_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/claims/{claim_id}/withdraw", payload, headers
        )

    # --- Estate plans and allocations ---
    def create_estate_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/estate-plans", payload, headers)

    def get_estate_plan(self, estate_plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vault/estate-plans/{estate_plan_id}", headers=headers
        )

    def list_estate_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/vault/estate-plans", headers=headers, params=params
        )

    def create_allocation(
        self, estate_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/estate-plans/{estate_plan_id}/allocations", payload, headers
        )

    def get_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vault/allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vault/allocations", headers=headers, params=params)

    def delete_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/vault/allocations/{allocation_id}", headers=headers
        )

    def propose_plan(
        self, estate_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/estate-plans/{estate_plan_id}/propose", payload, headers
        )

    def approve_plan(
        self, estate_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/estate-plans/{estate_plan_id}/approve", payload, headers
        )

    def execute_plan(
        self, estate_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/estate-plans/{estate_plan_id}/execute", payload, headers
        )

    # --- Share grants ---
    def create_share_grant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vault/share-grants", payload, headers)

    def get_share_grant(self, share_grant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vault/share-grants/{share_grant_id}", headers=headers
        )

    def list_share_grants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/vault/share-grants", headers=headers, params=params
        )

    def revoke_share_grant(
        self, share_grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vault/share-grants/{share_grant_id}/revoke", payload, headers
        )

    def redeem_share(self, share_token: str, headers: Dict[str, str]):
        return self._request("GET", f"/vault/shared/{share_token}", headers=headers)


api_client = ApiClient()
