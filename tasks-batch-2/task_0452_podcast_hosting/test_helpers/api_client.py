"""API client: one method per endpoint defined in the PRD (Podcast Hosting & Monetization API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ── Actors ──────────────────────────────────────────────────────────────
    def create_publisher(self, payload, headers):
        return self._request("POST", "/publishers", payload, headers)

    def create_advertiser(self, payload, headers):
        return self._request("POST", "/advertisers", payload, headers)

    def create_listener(self, payload, headers):
        return self._request("POST", "/listeners", payload, headers)

    # ── Show ────────────────────────────────────────────────────────────────
    def create_show(self, payload, headers):
        return self._request("POST", "/shows", payload, headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/shows", headers=headers, params=params)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def activate_show(self, show_id, headers):
        return self._request("POST", f"/shows/{show_id}/activate", headers=headers)

    def suspend_show(self, show_id, headers):
        return self._request("POST", f"/shows/{show_id}/suspend", headers=headers)

    def archive_show(self, show_id, headers):
        return self._request("POST", f"/shows/{show_id}/archive", headers=headers)

    # ── Episode ─────────────────────────────────────────────────────────────
    def create_episode(self, payload, headers):
        return self._request("POST", "/episodes", payload, headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/episodes", headers=headers, params=params)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def schedule_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/schedule", payload, headers)

    def publish_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/publish", headers=headers)

    def unpublish_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/unpublish", headers=headers)

    def delete_episode(self, episode_id, headers):
        return self._request("DELETE", f"/episodes/{episode_id}", headers=headers)

    # ── MediaAsset ──────────────────────────────────────────────────────────
    def create_media_asset(self, payload, headers):
        return self._request("POST", "/media-assets", payload, headers)

    def list_media_assets(self, headers, params=None):
        return self._request("GET", "/media-assets", headers=headers, params=params)

    def get_media_asset(self, asset_id, headers):
        return self._request("GET", f"/media-assets/{asset_id}", headers=headers)

    def transcode_start(self, asset_id, headers):
        return self._request("POST", f"/media-assets/{asset_id}/transcode-start", headers=headers)

    def transcode_result(self, asset_id, payload, headers):
        return self._request("POST", f"/media-assets/{asset_id}/transcode-result", payload, headers)

    # ── Feed ────────────────────────────────────────────────────────────────
    def create_feed(self, payload, headers):
        return self._request("POST", "/feeds", payload, headers)

    def list_feeds(self, headers, params=None):
        return self._request("GET", "/feeds", headers=headers, params=params)

    def get_feed(self, feed_id, headers):
        return self._request("GET", f"/feeds/{feed_id}", headers=headers)

    def disable_feed(self, feed_id, headers):
        return self._request("POST", f"/feeds/{feed_id}/disable", headers=headers)

    def enable_feed(self, feed_id, headers):
        return self._request("POST", f"/feeds/{feed_id}/enable", headers=headers)

    # ── Subscription ────────────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def activate_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/subscriptions/{subscription_id}/activate", payload or {}, headers)

    def mark_subscription_past_due(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/mark-past-due", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    # ── Distribution ────────────────────────────────────────────────────────
    def create_distribution(self, payload, headers):
        return self._request("POST", "/distributions", payload, headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/distributions", headers=headers, params=params)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/distributions/{distribution_id}", headers=headers)

    def approve_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/approve", headers=headers)

    def reject_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/reject", headers=headers)

    def remove_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/remove", headers=headers)

    # ── AdCampaign ──────────────────────────────────────────────────────────
    def create_ad_campaign(self, payload, headers):
        return self._request("POST", "/ad-campaigns", payload, headers)

    def list_ad_campaigns(self, headers, params=None):
        return self._request("GET", "/ad-campaigns", headers=headers, params=params)

    def get_ad_campaign(self, campaign_id, headers):
        return self._request("GET", f"/ad-campaigns/{campaign_id}", headers=headers)

    def activate_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/activate", headers=headers)

    def pause_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/pause", headers=headers)

    def complete_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/complete", headers=headers)

    # ── AdPlacement ─────────────────────────────────────────────────────────
    def create_ad_placement(self, payload, headers):
        return self._request("POST", "/ad-placements", payload, headers)

    def list_ad_placements(self, headers, params=None):
        return self._request("GET", "/ad-placements", headers=headers, params=params)

    def get_ad_placement(self, placement_id, headers):
        return self._request("GET", f"/ad-placements/{placement_id}", headers=headers)

    def insert_ad_placement(self, placement_id, headers):
        return self._request("POST", f"/ad-placements/{placement_id}/insert", headers=headers)

    def reconcile_ad_placement(self, placement_id, headers):
        return self._request("POST", f"/ad-placements/{placement_id}/reconcile", headers=headers)

    def cancel_ad_placement(self, placement_id, headers):
        return self._request("POST", f"/ad-placements/{placement_id}/cancel", headers=headers)

    # ── DownloadEvent ───────────────────────────────────────────────────────
    def create_download_event(self, payload, headers):
        return self._request("POST", "/download-events", payload, headers)

    def list_download_events(self, headers, params=None):
        return self._request("GET", "/download-events", headers=headers, params=params)

    def get_download_event(self, event_id, headers):
        return self._request("GET", f"/download-events/{event_id}", headers=headers)

    # ── PayoutStatement ─────────────────────────────────────────────────────
    def create_payout_statement(self, payload, headers):
        return self._request("POST", "/payout-statements", payload, headers)

    def list_payout_statements(self, headers, params=None):
        return self._request("GET", "/payout-statements", headers=headers, params=params)

    def get_payout_statement(self, statement_id, headers):
        return self._request("GET", f"/payout-statements/{statement_id}", headers=headers)

    def finalize_payout_statement(self, statement_id, headers):
        return self._request("POST", f"/payout-statements/{statement_id}/finalize", headers=headers)

    def pay_payout_statement(self, statement_id, headers):
        return self._request("POST", f"/payout-statements/{statement_id}/pay", headers=headers)

    def void_payout_statement(self, statement_id, headers):
        return self._request("POST", f"/payout-statements/{statement_id}/void", headers=headers)


api_client = ApiClient()
