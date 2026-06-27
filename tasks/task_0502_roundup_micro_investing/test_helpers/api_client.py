"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- SubscriptionPlan ----
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/subscription-plans/{plan_id}", headers=headers)

    # ---- ModelPortfolio ----
    def create_model_portfolio(self, payload, headers):
        return self._request("POST", "/model-portfolios", payload, headers)

    def get_model_portfolio(self, mp_id, headers):
        return self._request("GET", f"/model-portfolios/{mp_id}", headers=headers)

    # ---- FoundMoneyOffer ----
    def create_found_money_offer(self, payload, headers):
        return self._request("POST", "/found-money-offers", payload, headers)

    def get_found_money_offer(self, offer_id, headers):
        return self._request("GET", f"/found-money-offers/{offer_id}", headers=headers)

    # ---- Account ----
    def register_account(self, payload, headers):
        return self._request("POST", "/accounts/register", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def verify_kyc(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/verify-kyc", {}, headers)

    def restrict_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/restrict", {}, headers)

    def charge_subscription(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/billing/charge-subscription", {}, headers
        )

    def mark_past_due(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/billing/mark-past-due", {}, headers
        )

    def sweep(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/sweep", payload, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    def list_cash_transactions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/cash-transactions", headers=headers, params=params
        )

    # ---- LinkedCard ----
    def create_linked_card(self, payload, headers):
        return self._request("POST", "/linked-cards", payload, headers)

    def get_linked_card(self, card_id, headers):
        return self._request("GET", f"/linked-cards/{card_id}", headers=headers)

    def list_linked_cards(self, headers, params=None):
        return self._request("GET", "/linked-cards", headers=headers, params=params)

    def update_linked_card(self, card_id, payload, headers):
        return self._request("PATCH", f"/linked-cards/{card_id}", payload, headers)

    # ---- RoundUpAccrual ----
    def create_roundup_accrual(self, payload, headers):
        return self._request("POST", "/roundup-accruals", payload, headers)

    def get_roundup_accrual(self, accrual_id, headers):
        return self._request("GET", f"/roundup-accruals/{accrual_id}", headers=headers)

    def list_roundup_accruals(self, headers, params=None):
        return self._request("GET", "/roundup-accruals", headers=headers, params=params)

    def cancel_roundup_accrual(self, accrual_id, headers):
        return self._request("POST", f"/roundup-accruals/{accrual_id}/cancel", {}, headers)

    # ---- RecurringContribution ----
    def create_recurring_contribution(self, payload, headers):
        return self._request("POST", "/recurring-contributions", payload, headers)

    def get_recurring_contribution(self, rc_id, headers):
        return self._request("GET", f"/recurring-contributions/{rc_id}", headers=headers)

    def list_recurring_contributions(self, headers, params=None):
        return self._request("GET", "/recurring-contributions", headers=headers, params=params)

    def cancel_recurring_contribution(self, rc_id, headers):
        return self._request("POST", f"/recurring-contributions/{rc_id}/cancel", {}, headers)

    # ---- Bucket ----
    def create_bucket(self, payload, headers):
        return self._request("POST", "/buckets", payload, headers)

    def get_bucket(self, bucket_id, headers):
        return self._request("GET", f"/buckets/{bucket_id}", headers=headers)

    def list_buckets(self, headers, params=None):
        return self._request("GET", "/buckets", headers=headers, params=params)

    def freeze_bucket(self, bucket_id, headers):
        return self._request("POST", f"/buckets/{bucket_id}/freeze", {}, headers)

    def unfreeze_bucket(self, bucket_id, headers):
        return self._request("POST", f"/buckets/{bucket_id}/unfreeze", {}, headers)

    def close_bucket(self, bucket_id, headers):
        return self._request("POST", f"/buckets/{bucket_id}/close", {}, headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/submit", payload, headers)

    def settle_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/settle", payload or {}, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reject", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # ---- TaxLot ----
    def get_tax_lot(self, lot_id, headers):
        return self._request("GET", f"/tax-lots/{lot_id}", headers=headers)

    def list_tax_lots(self, headers, params=None):
        return self._request("GET", "/tax-lots", headers=headers, params=params)

    # ---- FoundMoneyReward ----
    def create_found_money_reward(self, payload, headers):
        return self._request("POST", "/found-money-rewards", payload, headers)

    def get_found_money_reward(self, reward_id, headers):
        return self._request("GET", f"/found-money-rewards/{reward_id}", headers=headers)

    def list_found_money_rewards(self, headers, params=None):
        return self._request("GET", "/found-money-rewards", headers=headers, params=params)

    def confirm_found_money_reward(self, reward_id, headers):
        return self._request("POST", f"/found-money-rewards/{reward_id}/confirm", {}, headers)

    def reverse_found_money_reward(self, reward_id, headers):
        return self._request("POST", f"/found-money-rewards/{reward_id}/reverse", {}, headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def redeem_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/redeem", payload, headers)

    def release_redemption(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/release-redemption", {}, headers)

    def qualify_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/qualify", {}, headers)

    def expire_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/expire", {}, headers)

    def revoke_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/revoke", {}, headers)

    # ---- Test-driving capabilities ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_lot_valuation(self, lot_id, payload, headers):
        return self._request("POST", f"/_lots/{lot_id}/set_valuation", payload, headers)

    # ---- Raw helpers for negative/auth tests ----
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload=None, headers=None):
        return self._request("POST", path, payload or {}, headers)


api_client = ApiClient()
