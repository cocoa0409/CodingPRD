"""API client: one method per endpoint defined in the Creator Membership PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Creators ----
    def create_creator(self, payload, headers):
        return self._request("POST", "/creators", payload, headers)

    def list_creators(self, headers, params=None):
        return self._request("GET", "/creators", headers=headers, params=params)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"/creators/{creator_id}", headers=headers)

    # ---- Tiers ----
    def create_tier(self, payload, headers):
        return self._request("POST", "/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/tiers", headers=headers, params=params)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/tiers/{tier_id}", headers=headers)

    def publish_tier(self, tier_id, headers, payload=None):
        return self._request("POST", f"/tiers/{tier_id}/publish", payload or {}, headers)

    def retire_tier(self, tier_id, headers, payload=None):
        return self._request("POST", f"/tiers/{tier_id}/retire", payload or {}, headers)

    # ---- Patrons ----
    def create_patron(self, payload, headers):
        return self._request("POST", "/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    # ---- Pledges ----
    def create_pledge(self, payload, headers):
        return self._request("POST", "/pledges", payload, headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def pause_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/pause", payload, headers)

    def resume_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/resume", payload, headers)

    def upgrade_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/upgrade", payload, headers)

    def cancel_pledge(self, pledge_id, headers, payload=None):
        return self._request("POST", f"/pledges/{pledge_id}/cancel", payload or {}, headers)

    def reactivate_pledge(self, pledge_id, headers, payload=None):
        return self._request("POST", f"/pledges/{pledge_id}/reactivate", payload or {}, headers)

    # ---- Charges ----
    def create_charge(self, payload, headers):
        return self._request("POST", "/charges", payload, headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def settle_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/settle", payload, headers)

    def refund_charge(self, charge_id, headers, payload=None):
        return self._request("POST", f"/charges/{charge_id}/refund", payload or {}, headers)

    # ---- Posts ----
    def create_post(self, payload, headers):
        return self._request("POST", "/posts", payload, headers)

    def list_posts(self, headers, params=None):
        return self._request("GET", "/posts", headers=headers, params=params)

    def get_post(self, post_id, headers):
        return self._request("GET", f"/posts/{post_id}", headers=headers)

    def publish_post(self, post_id, headers, payload=None):
        return self._request("POST", f"/posts/{post_id}/publish", payload or {}, headers)

    def request_post_access(self, post_id, payload, headers):
        return self._request("POST", f"/posts/{post_id}/access", payload, headers)

    # ---- PostAccess ----
    def list_post_accesses(self, headers, params=None):
        return self._request("GET", "/post-accesses", headers=headers, params=params)

    def get_post_access(self, access_id, headers):
        return self._request("GET", f"/post-accesses/{access_id}", headers=headers)

    # ---- Conversations ----
    def create_conversation(self, payload, headers):
        return self._request("POST", "/conversations", payload, headers)

    def list_conversations(self, headers, params=None):
        return self._request("GET", "/conversations", headers=headers, params=params)

    def get_conversation(self, conversation_id, headers):
        return self._request("GET", f"/conversations/{conversation_id}", headers=headers)

    def close_conversation(self, conversation_id, headers, payload=None):
        return self._request("POST", f"/conversations/{conversation_id}/close", payload or {}, headers)

    # ---- Messages ----
    def create_message(self, payload, headers):
        return self._request("POST", "/messages", payload, headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/messages", headers=headers, params=params)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/messages/{message_id}", headers=headers)

    # ---- Payouts ----
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def mark_payout_paid(self, payout_id, headers, payload=None):
        return self._request("POST", f"/payouts/{payout_id}/mark-paid", payload or {}, headers)

    def reverse_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/payouts/{payout_id}/reverse", payload or {}, headers)

    # ---- Win-back offers ----
    def create_win_back_offer(self, payload, headers):
        return self._request("POST", "/win-back-offers", payload, headers)

    def list_win_back_offers(self, headers, params=None):
        return self._request("GET", "/win-back-offers", headers=headers, params=params)

    def get_win_back_offer(self, offer_id, headers):
        return self._request("GET", f"/win-back-offers/{offer_id}", headers=headers)

    # ---- Administrative: clock + billing cycle ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_billing_cycle(self, headers, payload=None):
        return self._request("POST", "/_billing/run-cycle", payload or {}, headers)


api_client = ApiClient()
