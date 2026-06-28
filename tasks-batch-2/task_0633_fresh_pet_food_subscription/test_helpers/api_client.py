"""API client: one method per endpoint defined in the PRD.

Subclasses the framework ``GenericApiClient``; the base ``_request`` performs the HTTP call
and envelope-agnostic transport. The logical-clock endpoints live at the server root
(``/_clock``), every other route is under ``/api``.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock -------------------------------------------------- #
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Accounts & referral ------------------------------------------- #
    def register_account(self, payload, headers=None):
        return self._request("POST", "/api/accounts/register", payload, headers=headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def redeem_preview(self, payload, headers=None):
        return self._request("POST", "/api/referrals/redeem-preview", payload, headers=headers)

    def list_referral_credits(self, headers, params=None):
        return self._request("GET", "/api/referral-credits", headers=headers, params=params)

    def get_referral_credit(self, referral_credit_id, headers):
        return self._request(
            "GET", f"/api/referral-credits/{referral_credit_id}", headers=headers
        )

    # ---- Recipes -------------------------------------------------------- #
    def create_recipe(self, payload, headers):
        return self._request("POST", "/api/recipes", payload, headers=headers)

    def publish_recipe(self, recipe_id, headers):
        return self._request("POST", f"/api/recipes/{recipe_id}/publish", {}, headers=headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/api/recipes/{recipe_id}/retire", {}, headers=headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/api/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/api/recipes", headers=headers, params=params)

    # ---- Pets ----------------------------------------------------------- #
    def create_pet(self, payload, headers):
        return self._request("POST", "/api/pets", payload, headers=headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/api/pets/{pet_id}", headers=headers)

    def list_pets(self, headers, params=None):
        return self._request("GET", "/api/pets", headers=headers, params=params)

    def update_pet(self, pet_id, payload, headers):
        return self._request("PATCH", f"/api/pets/{pet_id}", payload, headers=headers)

    def archive_pet(self, pet_id, headers):
        return self._request("POST", f"/api/pets/{pet_id}/archive", {}, headers=headers)

    # ---- Weight logs ---------------------------------------------------- #
    def create_weight_log(self, payload, headers):
        return self._request("POST", "/api/weight-logs", payload, headers=headers)

    def list_weight_logs(self, headers, params=None):
        return self._request("GET", "/api/weight-logs", headers=headers, params=params)

    def get_weight_log(self, weight_log_id, headers):
        return self._request("GET", f"/api/weight-logs/{weight_log_id}", headers=headers)

    # ---- Subscriptions -------------------------------------------------- #
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers=headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/activate", {}, headers=headers
        )

    def pause_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST",
            f"/api/subscriptions/{subscription_id}/pause",
            payload if payload is not None else {},
            headers=headers,
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/resume", {}, headers=headers
        )

    def swap_recipe(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/swap-recipe", payload, headers=headers
        )

    def resize_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/resize", payload, headers=headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/cancel", {}, headers=headers
        )

    def generate_order(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/orders", payload, headers=headers
        )

    # ---- Orders --------------------------------------------------------- #
    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def skip_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/skip", {}, headers=headers)

    def charge_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/charge", {}, headers=headers)

    def settle_charge(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/settle-charge", payload, headers=headers
        )

    def retry_charge(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/retry-charge", {}, headers=headers)

    # ---- Shipments ------------------------------------------------------ #
    def list_shipments(self, headers, params=None):
        return self._request("GET", "/api/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def update_shipment(self, shipment_id, payload, headers):
        return self._request("PATCH", f"/api/shipments/{shipment_id}", payload, headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/dispatch", {}, headers=headers
        )

    def deliver_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/deliver", {}, headers=headers
        )


api_client = ApiClient()
