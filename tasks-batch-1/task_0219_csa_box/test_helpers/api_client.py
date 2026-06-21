"""API client: one method per endpoint defined in the PRD (CSA Box API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Season ───────────────────────────────────────────────────────────
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/seasons", headers=headers, params=params)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/open", {}, headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/close", {}, headers)

    def promote_waitlist(self, season_id, payload, headers):
        return self._request("POST", f"/seasons/{season_id}/promote-waitlist", payload, headers)

    # ─── PickupSite ───────────────────────────────────────────────────────
    def create_pickup_site(self, payload, headers):
        return self._request("POST", "/pickup-sites", payload, headers)

    def get_pickup_site(self, site_id, headers):
        return self._request("GET", f"/pickup-sites/{site_id}", headers=headers)

    def list_pickup_sites(self, headers, params=None):
        return self._request("GET", "/pickup-sites", headers=headers, params=params)

    # ─── ShareType ────────────────────────────────────────────────────────
    def create_share_type(self, payload, headers):
        return self._request("POST", "/share-types", payload, headers)

    def get_share_type(self, share_type_id, headers):
        return self._request("GET", f"/share-types/{share_type_id}", headers=headers)

    def list_share_types(self, headers, params=None):
        return self._request("GET", "/share-types", headers=headers, params=params)

    # ─── AddOn ────────────────────────────────────────────────────────────
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    # ─── Member ───────────────────────────────────────────────────────────
    def create_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # ─── Subscription ─────────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def confirm_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/confirm", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    # ─── SubscriptionAddOn (junction) ─────────────────────────────────────
    def create_subscription_add_on(self, payload, headers):
        return self._request("POST", "/subscription-add-ons", payload, headers)

    def delete_subscription_add_on(self, sao_id, headers):
        return self._request("DELETE", f"/subscription-add-ons/{sao_id}", headers=headers)

    def list_subscription_add_ons_for_subscription(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/add-ons", headers=headers, params=params)

    def get_subscription_add_on(self, sao_id, headers):
        return self._request("GET", f"/subscription-add-ons/{sao_id}", headers=headers)

    def list_subscription_add_ons(self, headers, params=None):
        return self._request("GET", "/subscription-add-ons", headers=headers, params=params)

    # ─── WeeklyBox ────────────────────────────────────────────────────────
    def list_subscription_weekly_boxes(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/weekly-boxes", headers=headers, params=params)

    def get_weekly_box(self, box_id, headers):
        return self._request("GET", f"/weekly-boxes/{box_id}", headers=headers)

    def list_weekly_boxes(self, headers, params=None):
        return self._request("GET", "/weekly-boxes", headers=headers, params=params)

    def pack_weekly_box(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/pack", {}, headers)

    def deliver_weekly_box(self, box_id, headers):
        return self._request("POST", f"/weekly-boxes/{box_id}/deliver", {}, headers)

    # ─── VacationHold ─────────────────────────────────────────────────────
    def create_vacation_hold(self, payload, headers):
        return self._request("POST", "/vacation-holds", payload, headers)

    def get_vacation_hold(self, hold_id, headers):
        return self._request("GET", f"/vacation-holds/{hold_id}", headers=headers)

    def list_vacation_holds(self, headers, params=None):
        return self._request("GET", "/vacation-holds", headers=headers, params=params)

    def list_subscription_vacation_holds(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/vacation-holds", headers=headers, params=params)

    def release_vacation_hold(self, hold_id, headers):
        return self._request("POST", f"/vacation-holds/{hold_id}/release", {}, headers)

    # ─── WaitlistEntry ────────────────────────────────────────────────────
    def create_waitlist_entry(self, payload, headers=None):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, wl_id, headers):
        return self._request("GET", f"/waitlist-entries/{wl_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def accept_waitlist_entry(self, wl_id, headers):
        return self._request("POST", f"/waitlist-entries/{wl_id}/accept", {}, headers)

    def decline_waitlist_entry(self, wl_id, headers):
        return self._request("POST", f"/waitlist-entries/{wl_id}/decline", {}, headers)

    # ─── WorkShareShift ───────────────────────────────────────────────────
    def create_work_share_shift(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/work-share-shifts", payload, headers)

    def list_work_share_shifts(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/work-share-shifts", headers=headers, params=params)

    def get_work_share_shift(self, shift_id, headers):
        return self._request("GET", f"/work-share-shifts/{shift_id}", headers=headers)

    def complete_work_share_shift(self, shift_id, headers):
        return self._request("POST", f"/work-share-shifts/{shift_id}/complete", {}, headers)

    def mark_no_show_work_share_shift(self, shift_id, headers):
        return self._request("POST", f"/work-share-shifts/{shift_id}/mark-no-show", {}, headers)

    # ─── LedgerEntry / Payments ───────────────────────────────────────────
    def list_ledger_entries(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/ledger-entries", headers=headers, params=params)

    def create_payment(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/payments", payload, headers)

    # ─── Clock (test-driving) ─────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
