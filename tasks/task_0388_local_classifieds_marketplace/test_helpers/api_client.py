"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Members ----
    def create_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers=headers)

    def list_members(self, headers=None, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers=None):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def request_verification(self, member_id, headers=None):
        return self._request("POST", f"/members/{member_id}/request-verification", {}, headers=headers)

    def confirm_verification(self, member_id, payload, headers=None):
        return self._request("POST", f"/members/{member_id}/confirm-verification", payload, headers=headers)

    def suspend_member(self, member_id, headers=None):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers=headers)

    def reinstate_member(self, member_id, headers=None):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers=headers)

    def ban_member(self, member_id, headers=None):
        return self._request("POST", f"/members/{member_id}/ban", {}, headers=headers)

    def list_member_flags(self, member_id, headers=None, params=None):
        return self._request("GET", f"/members/{member_id}/flags", headers=headers, params=params)

    # ---- Categories ----
    def create_category(self, payload, headers=None):
        return self._request("POST", "/categories", payload, headers=headers)

    def list_categories(self, headers=None, params=None):
        return self._request("GET", "/categories", headers=headers, params=params)

    # ---- Listings ----
    def create_listing(self, payload, headers=None):
        return self._request("POST", "/listings", payload, headers=headers)

    def list_listings(self, headers=None, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers=None):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def patch_listing(self, listing_id, payload, headers=None):
        return self._request("PATCH", f"/listings/{listing_id}", payload, headers=headers)

    def publish_listing(self, listing_id, headers=None):
        return self._request("POST", f"/listings/{listing_id}/publish", {}, headers=headers)

    def renew_listing(self, listing_id, headers=None):
        return self._request("POST", f"/listings/{listing_id}/renew", {}, headers=headers)

    def expire_listing(self, listing_id, headers=None):
        return self._request("POST", f"/listings/{listing_id}/expire", {}, headers=headers)

    def remove_listing(self, listing_id, headers=None):
        return self._request("POST", f"/listings/{listing_id}/remove", {}, headers=headers)

    def list_listing_offers(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/offers", headers=headers, params=params)

    def list_listing_flags(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/flags", headers=headers, params=params)

    def list_listing_conversations(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/conversations", headers=headers, params=params)

    def list_listing_alerts(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/alerts", headers=headers, params=params)

    # ---- Conversations & Messages ----
    def create_conversation(self, payload, headers=None):
        return self._request("POST", "/conversations", payload, headers=headers)

    def list_conversations(self, headers=None, params=None):
        return self._request("GET", "/conversations", headers=headers, params=params)

    def get_conversation(self, conversation_id, headers=None):
        return self._request("GET", f"/conversations/{conversation_id}", headers=headers)

    def list_conversation_messages(self, conversation_id, headers=None, params=None):
        return self._request("GET", f"/conversations/{conversation_id}/messages", headers=headers, params=params)

    def list_conversation_offers(self, conversation_id, headers=None, params=None):
        return self._request("GET", f"/conversations/{conversation_id}/offers", headers=headers, params=params)

    def create_message(self, payload, headers=None):
        return self._request("POST", "/messages", payload, headers=headers)

    def list_messages(self, headers=None, params=None):
        return self._request("GET", "/messages", headers=headers, params=params)

    def get_message(self, message_id, headers=None):
        return self._request("GET", f"/messages/{message_id}", headers=headers)

    # ---- Offers ----
    def create_offer(self, payload, headers=None):
        return self._request("POST", "/offers", payload, headers=headers)

    def list_offers(self, headers=None, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers=None):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def counter_offer(self, offer_id, payload, headers=None):
        return self._request("POST", f"/offers/{offer_id}/counter", payload, headers=headers)

    def accept_offer(self, offer_id, payload, headers=None):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers=headers)

    def reject_offer(self, offer_id, headers=None):
        return self._request("POST", f"/offers/{offer_id}/reject", {}, headers=headers)

    def withdraw_offer(self, offer_id, headers=None):
        return self._request("POST", f"/offers/{offer_id}/withdraw", {}, headers=headers)

    def list_offer_meetups(self, offer_id, headers=None, params=None):
        return self._request("GET", f"/offers/{offer_id}/meetups", headers=headers, params=params)

    # ---- SafeTradeSpots ----
    def create_safe_trade_spot(self, payload, headers=None):
        return self._request("POST", "/safe-trade-spots", payload, headers=headers)

    def list_safe_trade_spots(self, headers=None, params=None):
        return self._request("GET", "/safe-trade-spots", headers=headers, params=params)

    def get_safe_trade_spot(self, spot_id, headers=None):
        return self._request("GET", f"/safe-trade-spots/{spot_id}", headers=headers)

    def list_spot_meetups(self, spot_id, headers=None, params=None):
        return self._request("GET", f"/safe-trade-spots/{spot_id}/meetups", headers=headers, params=params)

    # ---- Meetups ----
    def create_meetup(self, payload, headers=None):
        return self._request("POST", "/meetups", payload, headers=headers)

    def list_meetups(self, headers=None, params=None):
        return self._request("GET", "/meetups", headers=headers, params=params)

    def get_meetup(self, meetup_id, headers=None):
        return self._request("GET", f"/meetups/{meetup_id}", headers=headers)

    def confirm_meetup(self, meetup_id, headers=None):
        return self._request("POST", f"/meetups/{meetup_id}/confirm", {}, headers=headers)

    def complete_meetup(self, meetup_id, headers=None):
        return self._request("POST", f"/meetups/{meetup_id}/complete", {}, headers=headers)

    def cancel_meetup(self, meetup_id, headers=None):
        return self._request("POST", f"/meetups/{meetup_id}/cancel", {}, headers=headers)

    def no_show_meetup(self, meetup_id, headers=None):
        return self._request("POST", f"/meetups/{meetup_id}/no-show", {}, headers=headers)

    # ---- Flags / Moderation ----
    def create_flag(self, payload, headers=None):
        return self._request("POST", "/flags", payload, headers=headers)

    def list_flags(self, headers=None, params=None):
        return self._request("GET", "/flags", headers=headers, params=params)

    def get_flag(self, flag_id, headers=None):
        return self._request("GET", f"/flags/{flag_id}", headers=headers)

    def uphold_flag(self, flag_id, payload=None, headers=None):
        return self._request("POST", f"/flags/{flag_id}/uphold", payload or {}, headers=headers)

    def dismiss_flag(self, flag_id, payload=None, headers=None):
        return self._request("POST", f"/flags/{flag_id}/dismiss", payload or {}, headers=headers)

    # ---- Saved Searches & Alerts ----
    def create_saved_search(self, payload, headers=None):
        return self._request("POST", "/saved-searches", payload, headers=headers)

    def list_saved_searches(self, headers=None, params=None):
        return self._request("GET", "/saved-searches", headers=headers, params=params)

    def get_saved_search(self, saved_search_id, headers=None):
        return self._request("GET", f"/saved-searches/{saved_search_id}", headers=headers)

    def list_saved_search_alerts(self, saved_search_id, headers=None, params=None):
        return self._request("GET", f"/saved-searches/{saved_search_id}/alerts", headers=headers, params=params)

    # ---- Test-driving clock ----
    def clock_set(self, payload, headers=None):
        return self._request("POST", "/_clock/set", payload, headers=headers)

    def clock_advance(self, payload, headers=None):
        return self._request("POST", "/_clock/advance", payload, headers=headers)


api_client = ApiClient()
