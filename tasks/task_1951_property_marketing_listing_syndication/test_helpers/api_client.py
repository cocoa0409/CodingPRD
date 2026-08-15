"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    # --- Listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def patch_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/listings/{listing_id}", payload, headers)

    def submit_review(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/submit-review", {}, headers)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/activate", {}, headers)

    def revise_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/revise", {}, headers)

    def mark_under_contract(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/mark-under-contract", {}, headers)

    def reactivate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/reactivate", {}, headers)

    def close_sold(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/close-sold", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/withdraw", {}, headers)

    def relist_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/relist", payload, headers)

    def get_relist_quote(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/relist-quote", headers=headers, params=params)

    def list_relist_requests(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/relist-requests", headers=headers, params=params)

    def get_listing_summary(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}/summary", headers=headers)

    def list_listing_events(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/events", headers=headers, params=params)

    # --- Media assets ---
    def create_media_asset(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/media-assets", payload, headers)

    def list_media_assets(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/media-assets", headers=headers, params=params)

    def mark_media_ready(self, media_id, headers):
        return self._request("POST", f"/media-assets/{media_id}/mark-ready", {}, headers)

    def set_primary_media(self, media_id, headers):
        return self._request("POST", f"/media-assets/{media_id}/set-primary", {}, headers)

    def archive_media_asset(self, media_id, headers):
        return self._request("POST", f"/media-assets/{media_id}/archive", {}, headers)

    # --- Compliance reviews ---
    def list_compliance_reviews(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/compliance-reviews", headers=headers, params=params)

    def decide_compliance_review(self, review_id, payload, headers):
        return self._request("POST", f"/compliance-reviews/{review_id}/decision", payload, headers)

    # --- Portal accounts & blackout windows ---
    def create_portal_account(self, payload, headers):
        return self._request("POST", "/portal-accounts", payload, headers)

    def list_portal_accounts(self, headers, params=None):
        return self._request("GET", "/portal-accounts", headers=headers, params=params)

    def get_portal_account(self, portal_id, headers):
        return self._request("GET", f"/portal-accounts/{portal_id}", headers=headers)

    def suspend_portal_account(self, portal_id, headers):
        return self._request("POST", f"/portal-accounts/{portal_id}/suspend", {}, headers)

    def resume_portal_account(self, portal_id, headers):
        return self._request("POST", f"/portal-accounts/{portal_id}/resume", {}, headers)

    def create_blackout_window(self, portal_id, payload, headers):
        return self._request("POST", f"/portal-accounts/{portal_id}/blackout-windows", payload, headers)

    def list_blackout_windows(self, portal_id, headers, params=None):
        return self._request("GET", f"/portal-accounts/{portal_id}/blackout-windows", headers=headers, params=params)

    def list_portal_feed_subscriptions(self, portal_id, headers, params=None):
        return self._request("GET", f"/portal-accounts/{portal_id}/feed-subscriptions", headers=headers, params=params)

    # --- Feed subscriptions ---
    def create_feed_subscription(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/feed-subscriptions", payload, headers)

    def list_listing_feed_subscriptions(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/feed-subscriptions", headers=headers, params=params)

    def get_feed_subscription(self, subscription_id, headers):
        return self._request("GET", f"/feed-subscriptions/{subscription_id}", headers=headers)

    def pause_feed_subscription(self, subscription_id, headers):
        return self._request("POST", f"/feed-subscriptions/{subscription_id}/pause", {}, headers)

    def resume_feed_subscription(self, subscription_id, headers):
        return self._request("POST", f"/feed-subscriptions/{subscription_id}/resume", {}, headers)

    def list_subscription_jobs(self, subscription_id, headers, params=None):
        return self._request("GET", f"/feed-subscriptions/{subscription_id}/jobs", headers=headers, params=params)

    # --- Feed events (syndication jobs) ---
    def list_listing_feed_events(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/feed-events", headers=headers, params=params)

    def ack_feed_event(self, job_id, headers):
        return self._request("POST", f"/feed-events/{job_id}/ack", {}, headers)

    def fail_feed_event(self, job_id, payload, headers):
        return self._request("POST", f"/feed-events/{job_id}/fail", payload, headers)

    # --- Price changes ---
    def create_price_change(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/price-changes", payload, headers)

    # --- Showing windows & feedback ---
    def create_showing_window(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/showing-windows", payload, headers)

    def list_showing_windows(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/showing-windows", headers=headers, params=params)

    def get_showing_window(self, window_id, headers):
        return self._request("GET", f"/showing-windows/{window_id}", headers=headers)

    def create_feedback(self, window_id, payload, headers):
        return self._request("POST", f"/showing-windows/{window_id}/feedback", payload, headers)

    def get_window_feedback(self, window_id, headers):
        return self._request("GET", f"/showing-windows/{window_id}/feedback", headers=headers)

    def list_listing_feedbacks(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/feedbacks", headers=headers, params=params)

    def exclude_feedback(self, feedback_id, headers):
        return self._request("POST", f"/feedbacks/{feedback_id}/exclude", {}, headers)

    # --- Administrative (logical clock & sweep) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/_sweeps/run", {}, headers)


api_client = ApiClient()
