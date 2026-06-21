"""API client: one method per endpoint defined in PRD §4.

All endpoints are mounted under `/snap` (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/snap"


class ApiClient(GenericApiClient):
    # ─── Households ─────────────────────────────────────────
    def create_household(self, payload, headers):
        return self._request("POST", f"{PREFIX}/households", payload, headers)

    def get_household(self, hh_id, headers):
        return self._request("GET", f"{PREFIX}/households/{hh_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/households", headers=headers, params=params)

    def patch_household(self, hh_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/households/{hh_id}", payload, headers)

    def suspend_household(self, hh_id, headers):
        return self._request("POST", f"{PREFIX}/households/{hh_id}/suspend", {}, headers)

    def reinstate_household(self, hh_id, headers):
        return self._request("POST", f"{PREFIX}/households/{hh_id}/reinstate", {}, headers)

    def terminate_household(self, hh_id, payload, headers):
        return self._request("POST", f"{PREFIX}/households/{hh_id}/terminate", payload, headers)

    # ─── HouseholdMembers ───────────────────────────────────
    def create_household_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/household-members", payload, headers)

    def get_household_member(self, m_id, headers):
        return self._request("GET", f"{PREFIX}/household-members/{m_id}", headers=headers)

    def list_household_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/household-members", headers=headers, params=params)

    def patch_household_member(self, m_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/household-members/{m_id}", payload, headers)

    # ─── Applications ───────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/submit", {}, headers)

    def approve_application(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/approve", payload, headers)

    def deny_application(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/deny", payload, headers)

    # ─── EBTCards ───────────────────────────────────────────
    def get_ebt_card(self, card_id, headers):
        return self._request("GET", f"{PREFIX}/ebt-cards/{card_id}", headers=headers)

    def list_ebt_cards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ebt-cards", headers=headers, params=params)

    def activate_ebt_card(self, card_id, headers):
        return self._request("POST", f"{PREFIX}/ebt-cards/{card_id}/activate", {}, headers)

    def suspend_ebt_card(self, card_id, headers):
        return self._request("POST", f"{PREFIX}/ebt-cards/{card_id}/suspend", {}, headers)

    def reinstate_ebt_card(self, card_id, headers):
        return self._request("POST", f"{PREFIX}/ebt-cards/{card_id}/reinstate", {}, headers)

    def replace_ebt_card(self, card_id, headers):
        return self._request("POST", f"{PREFIX}/ebt-cards/{card_id}/replace", {}, headers)

    # ─── MonthlyAllotments ──────────────────────────────────
    def create_monthly_allotment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/monthly-allotments", payload, headers)

    def get_monthly_allotment(self, ma_id, headers):
        return self._request("GET", f"{PREFIX}/monthly-allotments/{ma_id}", headers=headers)

    def list_monthly_allotments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/monthly-allotments", headers=headers, params=params)

    def issue_monthly_allotment(self, ma_id, payload, headers):
        return self._request("POST", f"{PREFIX}/monthly-allotments/{ma_id}/issue", payload, headers)

    def adjust_monthly_allotment(self, ma_id, headers):
        return self._request("POST", f"{PREFIX}/monthly-allotments/{ma_id}/adjust", {}, headers)

    # ─── EligibleItemCategories ─────────────────────────────
    def create_eligible_item_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligible-item-categories", payload, headers)

    def get_eligible_item_category(self, cat_id, headers):
        return self._request("GET", f"{PREFIX}/eligible-item-categories/{cat_id}", headers=headers)

    def list_eligible_item_categories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/eligible-item-categories", headers=headers, params=params)

    # ─── PurchaseTransactions ───────────────────────────────
    def create_purchase_transaction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/purchase-transactions", payload, headers)

    def get_purchase_transaction(self, tx_id, headers):
        return self._request("GET", f"{PREFIX}/purchase-transactions/{tx_id}", headers=headers)

    def list_purchase_transactions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/purchase-transactions", headers=headers, params=params)

    def settle_purchase_transaction(self, tx_id, headers):
        return self._request("POST", f"{PREFIX}/purchase-transactions/{tx_id}/settle", {}, headers)

    def reverse_purchase_transaction(self, tx_id, headers):
        return self._request("POST", f"{PREFIX}/purchase-transactions/{tx_id}/reverse", {}, headers)

    # ─── FraudFlags ─────────────────────────────────────────
    def get_fraud_flag(self, ff_id, headers):
        return self._request("GET", f"{PREFIX}/fraud-flags/{ff_id}", headers=headers)

    def list_fraud_flags(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fraud-flags", headers=headers, params=params)

    def create_fraud_flag(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fraud-flags", payload, headers)

    def claim_fraud_flag(self, ff_id, headers):
        return self._request("POST", f"{PREFIX}/fraud-flags/{ff_id}/claim", {}, headers)

    def substantiate_fraud_flag(self, ff_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fraud-flags/{ff_id}/substantiate", payload, headers)

    def dismiss_fraud_flag(self, ff_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fraud-flags/{ff_id}/dismiss", payload, headers)

    # ─── ABAWDWaivers ───────────────────────────────────────
    def create_abawd_waiver(self, payload, headers):
        return self._request("POST", f"{PREFIX}/abawd-waivers", payload, headers)

    def get_abawd_waiver(self, w_id, headers):
        return self._request("GET", f"{PREFIX}/abawd-waivers/{w_id}", headers=headers)

    def list_abawd_waivers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/abawd-waivers", headers=headers, params=params)

    def approve_abawd_waiver(self, w_id, payload, headers):
        return self._request("POST", f"{PREFIX}/abawd-waivers/{w_id}/approve", payload, headers)

    def deny_abawd_waiver(self, w_id, payload, headers):
        return self._request("POST", f"{PREFIX}/abawd-waivers/{w_id}/deny", payload, headers)

    def revoke_abawd_waiver(self, w_id, headers):
        return self._request("POST", f"{PREFIX}/abawd-waivers/{w_id}/revoke", {}, headers)

    # ─── EmergencyAllotmentProclamations ────────────────────
    def create_emergency_allotment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/emergency-allotments", payload, headers)

    def get_emergency_allotment(self, p_id, headers):
        return self._request("GET", f"{PREFIX}/emergency-allotments/{p_id}", headers=headers)

    def list_emergency_allotments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/emergency-allotments", headers=headers, params=params)

    def activate_emergency_allotment(self, p_id, headers):
        return self._request("POST", f"{PREFIX}/emergency-allotments/{p_id}/activate", {}, headers)

    # ─── System clock (test-only) ───────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", f"{PREFIX}/_clock", headers=headers)


api_client = ApiClient()
