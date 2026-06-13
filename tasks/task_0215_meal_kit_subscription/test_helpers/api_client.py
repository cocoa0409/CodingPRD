"""API client: one method per endpoint defined in the Meal Kit Subscription PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Plan (catalog) ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    # ---- ShippingZone (catalog) ----
    def create_shipping_zone(self, payload, headers):
        return self._request("POST", "/shipping-zones", payload, headers)

    def list_shipping_zones(self, headers, params=None):
        return self._request("GET", "/shipping-zones", headers=headers, params=params)

    def get_shipping_zone(self, zone_id, headers):
        return self._request("GET", f"/shipping-zones/{zone_id}", headers=headers)

    # ---- Recipe (catalog) ----
    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def list_recipe_box_recipes(self, recipe_id, headers, params=None):
        return self._request("GET", f"/recipes/{recipe_id}/box-recipes",
                             headers=headers, params=params)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def get_referral_summary(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/referral-summary",
                             headers=headers)

    def deactivate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/deactivate", headers=headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def change_plan(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/plan-changes",
                             payload, headers)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause",
                             payload, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume",
                             headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel",
                             headers=headers)

    # ---- WeeklyBox ----
    def create_weekly_box(self, payload, headers):
        return self._request("POST", "/weekly-boxes", payload, headers)

    def list_weekly_boxes(self, headers, params=None):
        return self._request("GET", "/weekly-boxes", headers=headers, params=params)

    def get_weekly_box(self, box_id, headers):
        return self._request("GET", f"/weekly-boxes/{box_id}", headers=headers)

    def add_recipe_to_box(self, box_id, payload, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/recipes", payload, headers)

    def list_box_recipes(self, box_id, headers, params=None):
        return self._request("GET", f"/weekly-boxes/{box_id}/recipes",
                             headers=headers, params=params)

    def delete_box_recipe(self, box_id, box_recipe_id, headers):
        return self._request("DELETE",
                             f"/weekly-boxes/{box_id}/recipes/{box_recipe_id}",
                             headers=headers)

    def lock_selection(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/lock-selection",
                             headers=headers)

    def skip_box(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/skip", headers=headers)

    def charge_box(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/charge", headers=headers)

    def ship_box(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/ship", headers=headers)

    def refund_box(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/refund", headers=headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def void_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/void", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
