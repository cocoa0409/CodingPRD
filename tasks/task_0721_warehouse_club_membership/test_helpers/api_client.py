"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def renew_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/renew", payload, headers)

    def cancel_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", payload, headers)

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # --- Household cards ---
    def create_household_card(self, payload, headers):
        return self._request("POST", "/household-cards", payload, headers)

    def list_household_cards(self, headers, params=None):
        return self._request("GET", "/household-cards", headers=headers, params=params)

    def get_household_card(self, card_id, headers):
        return self._request("GET", f"/household-cards/{card_id}", headers=headers)

    def revoke_household_card(self, card_id, headers):
        return self._request("POST", f"/household-cards/{card_id}/revoke", {}, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # --- Instant savings ---
    def create_instant_saving(self, payload, headers):
        return self._request("POST", "/instant-savings", payload, headers)

    def list_instant_savings(self, headers, params=None):
        return self._request("GET", "/instant-savings", headers=headers, params=params)

    # --- Transactions ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def add_line(self, transaction_id, payload, headers):
        return self._request("POST", f"/transactions/{transaction_id}/lines", payload, headers)

    def list_lines(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/lines", headers=headers, params=params)

    def finalize_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/finalize", {}, headers)

    def void_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/void", {}, headers)

    # --- Returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    # --- Ledger / fee reads ---
    def list_reward_ledger(self, headers, params=None):
        return self._request("GET", "/reward-ledger", headers=headers, params=params)

    def list_fee_events(self, headers, params=None):
        return self._request("GET", "/fee-events", headers=headers, params=params)


api_client = ApiClient()
