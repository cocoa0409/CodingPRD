"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fundraising"


class ApiClient(GenericApiClient):
    # ─── Campaign lifecycle ───────────────────────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{PREFIX}/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/campaigns", headers=headers, params=params)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/activate", {}, headers)

    def freeze_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/freeze", {}, headers)

    def unfreeze_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/unfreeze", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/close", {}, headers)

    def reconcile_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/reconcile", payload, headers)

    def disburse_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/disburse", payload, headers)

    def get_campaign_report(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/campaigns/{campaign_id}/report", headers=headers)

    # ─── PrizeTier ────────────────────────────────────────────────────────
    def create_prize_tier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prize-tiers", payload, headers)

    def list_prize_tiers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prize-tiers", headers=headers, params=params)

    def get_prize_tier(self, prize_tier_id, headers):
        return self._request("GET", f"{PREFIX}/prize-tiers/{prize_tier_id}", headers=headers)

    # ─── Seller ───────────────────────────────────────────────────────────
    def create_seller(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sellers", payload, headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sellers", headers=headers, params=params)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"{PREFIX}/sellers/{seller_id}", headers=headers)

    def get_seller_credit_forecast(self, seller_id, headers):
        return self._request("GET", f"{PREFIX}/sellers/{seller_id}/credit-forecast", headers=headers)

    def block_seller(self, seller_id, headers):
        return self._request("POST", f"{PREFIX}/sellers/{seller_id}/block", {}, headers)

    def unblock_seller(self, seller_id, headers):
        return self._request("POST", f"{PREFIX}/sellers/{seller_id}/unblock", {}, headers)

    # ─── Product ──────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    # ─── Order (parallel-dimension lifecycle) ─────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/pay", {}, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/confirm", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/cancel", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/refund", {}, headers)

    # ─── Pledge (cyclic lifecycle) ────────────────────────────────────────
    def create_pledge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pledges", payload, headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pledges", headers=headers, params=params)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"{PREFIX}/pledges/{pledge_id}", headers=headers)

    def record_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/pledges/{pledge_id}/record", payload, headers)

    def revise_pledge(self, pledge_id, headers):
        return self._request("POST", f"{PREFIX}/pledges/{pledge_id}/revise", {}, headers)

    def collect_pledge(self, pledge_id, headers):
        return self._request("POST", f"{PREFIX}/pledges/{pledge_id}/collect", {}, headers)

    def cancel_pledge(self, pledge_id, headers):
        return self._request("POST", f"{PREFIX}/pledges/{pledge_id}/cancel", {}, headers)

    # ─── Volunteer & Shift ────────────────────────────────────────────────
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"{PREFIX}/volunteers/{volunteer_id}", headers=headers)

    def create_shift(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"{PREFIX}/shifts/{shift_id}", headers=headers)

    def book_shift(self, shift_id, payload, headers):
        return self._request("POST", f"{PREFIX}/shifts/{shift_id}/book", payload, headers)

    def release_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/shifts/{shift_id}/release", {}, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/shifts/{shift_id}/cancel", {}, headers)

    # ─── Disbursement (read-back) ─────────────────────────────────────────
    def list_disbursements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"{PREFIX}/disbursements/{disbursement_id}", headers=headers)

    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
