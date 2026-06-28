"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Merchant -----
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    def disable_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/disable", {}, headers)

    # ----- Offer -----
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    # ----- Member -----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def verify_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/verify", {}, headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    def list_member_ledger_entries(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/ledger-entries", headers=headers, params=params)

    def get_member_bonus_streak(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/bonus-streak", headers=headers)

    # ----- LedgerEntry -----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ----- ClickThrough -----
    def create_clickthrough(self, payload, headers):
        return self._request("POST", "/clickthroughs", payload, headers)

    def get_clickthrough(self, click_id, headers):
        return self._request("GET", f"/clickthroughs/{click_id}", headers=headers)

    def list_clickthroughs(self, headers, params=None):
        return self._request("GET", "/clickthroughs", headers=headers, params=params)

    # ----- ReceiptScan -----
    def create_receipt_scan(self, payload, headers):
        return self._request("POST", "/receipt-scans", payload, headers)

    def get_receipt_scan(self, scan_id, headers):
        return self._request("GET", f"/receipt-scans/{scan_id}", headers=headers)

    def list_receipt_scans(self, headers, params=None):
        return self._request("GET", "/receipt-scans", headers=headers, params=params)

    def start_review_receipt_scan(self, scan_id, headers):
        return self._request("POST", f"/receipt-scans/{scan_id}/start-review", {}, headers)

    def approve_receipt_scan(self, scan_id, payload, headers):
        return self._request("POST", f"/receipt-scans/{scan_id}/approve", payload, headers)

    def reject_receipt_scan(self, scan_id, payload, headers):
        return self._request("POST", f"/receipt-scans/{scan_id}/reject", payload, headers)

    # ----- RewardClaim -----
    def create_reward_claim(self, payload, headers):
        return self._request("POST", "/reward-claims", payload, headers)

    def get_reward_claim(self, claim_id, headers):
        return self._request("GET", f"/reward-claims/{claim_id}", headers=headers)

    def list_reward_claims(self, headers, params=None):
        return self._request("GET", "/reward-claims", headers=headers, params=params)

    def mature_reward_claim(self, claim_id, headers):
        return self._request("POST", f"/reward-claims/{claim_id}/mature", {}, headers)

    # ----- ReturnEvent -----
    def create_return_event(self, payload, headers):
        return self._request("POST", "/return-events", payload, headers)

    def list_return_events(self, headers, params=None):
        return self._request("GET", "/return-events", headers=headers, params=params)

    def get_return_event(self, event_id, headers):
        return self._request("GET", f"/return-events/{event_id}", headers=headers)

    # ----- CashOut -----
    def create_cashout(self, payload, headers):
        return self._request("POST", "/cashouts", payload, headers)

    def get_cashout(self, cashout_id, headers):
        return self._request("GET", f"/cashouts/{cashout_id}", headers=headers)

    def list_cashouts(self, headers, params=None):
        return self._request("GET", "/cashouts", headers=headers, params=params)

    def process_cashout(self, cashout_id, headers):
        return self._request("POST", f"/cashouts/{cashout_id}/process", {}, headers)

    def settle_cashout(self, cashout_id, payload, headers):
        return self._request("POST", f"/cashouts/{cashout_id}/settle", payload, headers)

    def retry_cashout(self, cashout_id, headers):
        return self._request("POST", f"/cashouts/{cashout_id}/retry", {}, headers)

    # ----- Referral -----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def reward_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/reward", {}, headers)

    # ----- Logical clock (test-driving) -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
