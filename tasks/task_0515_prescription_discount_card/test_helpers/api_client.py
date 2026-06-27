"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Member ──────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    # ─── Drug ──────────────────────────────────────────────────────────────
    def create_drug(self, payload, headers):
        return self._request("POST", "/drugs", payload, headers)

    def get_drug(self, drug_id, headers):
        return self._request("GET", f"/drugs/{drug_id}", headers=headers)

    def list_drugs(self, headers, params=None):
        return self._request("GET", "/drugs", headers=headers, params=params)

    # ─── Pharmacy ────────────────────────────────────────────────────────
    def create_pharmacy(self, payload, headers):
        return self._request("POST", "/pharmacies", payload, headers)

    def get_pharmacy(self, pharmacy_id, headers):
        return self._request("GET", f"/pharmacies/{pharmacy_id}", headers=headers)

    def list_pharmacies(self, headers, params=None):
        return self._request("GET", "/pharmacies", headers=headers, params=params)

    def suspend_pharmacy(self, pharmacy_id, headers):
        return self._request("POST", f"/pharmacies/{pharmacy_id}/suspend", {}, headers)

    def reactivate_pharmacy(self, pharmacy_id, headers):
        return self._request("POST", f"/pharmacies/{pharmacy_id}/reactivate", {}, headers)

    # ─── PriceQuote ────────────────────────────────────────────────────────
    def create_price_quote(self, payload, headers):
        return self._request("POST", "/price-quotes", payload, headers)

    def get_price_quote(self, quote_id, headers):
        return self._request("GET", f"/price-quotes/{quote_id}", headers=headers)

    def list_price_quotes(self, headers, params=None):
        return self._request("GET", "/price-quotes", headers=headers, params=params)

    def expire_price_quote(self, quote_id, headers):
        return self._request("POST", f"/price-quotes/{quote_id}/expire", {}, headers)

    # ─── PriceComparison ──────────────────────────────────────────────────
    def create_comparison(self, payload, headers):
        return self._request("POST", "/comparisons", payload, headers)

    def get_comparison(self, comparison_id, headers):
        return self._request("GET", f"/comparisons/{comparison_id}", headers=headers)

    def list_comparisons(self, headers, params=None):
        return self._request("GET", "/comparisons", headers=headers, params=params)

    def run_comparison(self, comparison_id, payload, headers):
        return self._request("POST", f"/comparisons/{comparison_id}/run", payload, headers)

    def create_insurance_estimate(self, comparison_id, payload, headers):
        return self._request("POST", f"/comparisons/{comparison_id}/insurance-estimate",
                             payload, headers)

    def get_insurance_estimate(self, estimate_id, headers):
        return self._request("GET", f"/insurance-estimates/{estimate_id}", headers=headers)

    def list_insurance_estimates(self, headers, params=None):
        return self._request("GET", "/insurance-estimates", headers=headers, params=params)

    # ─── DiscountCard ──────────────────────────────────────────────────────
    def create_discount_card(self, payload, headers):
        return self._request("POST", "/discount-cards", payload, headers)

    def get_discount_card(self, card_id, headers):
        return self._request("GET", f"/discount-cards/{card_id}", headers=headers)

    def list_discount_cards(self, headers, params=None):
        return self._request("GET", "/discount-cards", headers=headers, params=params)

    def void_discount_card(self, card_id, payload, headers):
        return self._request("POST", f"/discount-cards/{card_id}/void", payload, headers)

    # ─── Claim ──────────────────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reject", {}, headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reverse", payload, headers)

    # ─── CopayCard ────────────────────────────────────────────────────────
    def create_copay_card(self, payload, headers):
        return self._request("POST", "/copay-cards", payload, headers)

    def get_copay_card(self, card_id, headers):
        return self._request("GET", f"/copay-cards/{card_id}", headers=headers)

    def list_copay_cards(self, headers, params=None):
        return self._request("GET", "/copay-cards", headers=headers, params=params)

    def withdraw_copay_card(self, card_id, headers):
        return self._request("POST", f"/copay-cards/{card_id}/withdraw", {}, headers)

    # ─── CopayLink ────────────────────────────────────────────────────────
    def create_copay_link(self, payload, headers):
        return self._request("POST", "/copay-links", payload, headers)

    def get_copay_link(self, link_id, headers):
        return self._request("GET", f"/copay-links/{link_id}", headers=headers)

    def list_copay_links(self, headers, params=None):
        return self._request("GET", "/copay-links", headers=headers, params=params)

    def release_copay_link(self, link_id, payload, headers):
        return self._request("POST", f"/copay-links/{link_id}/release", payload, headers)

    # ─── GoldMembership ──────────────────────────────────────────────────
    def create_gold_membership(self, payload, headers):
        return self._request("POST", "/gold-memberships", payload, headers)

    def get_gold_membership(self, membership_id, headers):
        return self._request("GET", f"/gold-memberships/{membership_id}", headers=headers)

    def list_gold_memberships(self, headers, params=None):
        return self._request("GET", "/gold-memberships", headers=headers, params=params)

    def record_gold_payment(self, membership_id, headers):
        return self._request("POST", f"/gold-memberships/{membership_id}/record-payment",
                             {}, headers)

    def lapse_gold_membership(self, membership_id, headers):
        return self._request("POST", f"/gold-memberships/{membership_id}/lapse", {}, headers)

    def revoke_gold_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/gold-memberships/{membership_id}/revoke",
                             payload, headers)

    # ─── MailOrderFulfillment ────────────────────────────────────────────
    def create_mail_order(self, payload, headers):
        return self._request("POST", "/mail-orders", payload, headers)

    def get_mail_order(self, order_id, headers):
        return self._request("GET", f"/mail-orders/{order_id}", headers=headers)

    def list_mail_orders(self, headers, params=None):
        return self._request("GET", "/mail-orders", headers=headers, params=params)

    def ship_mail_order(self, order_id, headers):
        return self._request("POST", f"/mail-orders/{order_id}/ship", {}, headers)

    def deliver_mail_order(self, order_id, headers):
        return self._request("POST", f"/mail-orders/{order_id}/deliver", {}, headers)

    def cancel_mail_order(self, order_id, payload, headers):
        return self._request("POST", f"/mail-orders/{order_id}/cancel", payload, headers)

    # ─── TelehealthReferral ──────────────────────────────────────────────
    def create_telehealth_referral(self, payload, headers):
        return self._request("POST", "/telehealth-referrals", payload, headers)

    def get_telehealth_referral(self, referral_id, headers):
        return self._request("GET", f"/telehealth-referrals/{referral_id}", headers=headers)

    def list_telehealth_referrals(self, headers, params=None):
        return self._request("GET", "/telehealth-referrals", headers=headers, params=params)

    def schedule_telehealth_referral(self, referral_id, headers):
        return self._request("POST", f"/telehealth-referrals/{referral_id}/schedule", {}, headers)

    def complete_telehealth_referral(self, referral_id, headers):
        return self._request("POST", f"/telehealth-referrals/{referral_id}/complete", {}, headers)

    def cancel_telehealth_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/telehealth-referrals/{referral_id}/cancel",
                             payload, headers)


api_client = ApiClient()
