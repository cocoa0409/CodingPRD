"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Channels ---
    def create_channel(self, payload, headers):
        return self._request("POST", "/v1/channels", payload, headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", "/v1/channels", headers=headers, params=params)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/v1/channels/{channel_id}", headers=headers)

    def channel_go_live(self, channel_id, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/go-live", {}, headers)

    def channel_suspend(self, channel_id, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/suspend", {}, headers)

    def channel_resume(self, channel_id, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/resume", {}, headers)

    def channel_take_offline(self, channel_id, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/take-offline", {}, headers)

    def channel_archive(self, channel_id, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/archive", {}, headers)

    def channel_run_ops(self, channel_id, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/run-ops", {}, headers)

    # --- Content assets ---
    def create_content_asset(self, payload, headers):
        return self._request("POST", "/v1/content-assets", payload, headers)

    def list_content_assets(self, headers, params=None):
        return self._request("GET", "/v1/content-assets", headers=headers, params=params)

    def get_content_asset(self, content_id, headers):
        return self._request("GET", f"/v1/content-assets/{content_id}", headers=headers)

    def content_mark_available(self, content_id, headers):
        return self._request("POST", f"/v1/content-assets/{content_id}/mark-available", {}, headers)

    def content_pull(self, content_id, headers):
        return self._request("POST", f"/v1/content-assets/{content_id}/pull", {}, headers)

    def content_reinstate(self, content_id, headers):
        return self._request("POST", f"/v1/content-assets/{content_id}/reinstate", {}, headers)

    def content_archive(self, content_id, headers):
        return self._request("POST", f"/v1/content-assets/{content_id}/archive", {}, headers)

    # --- Rights grants ---
    def create_rights_grant(self, payload, headers):
        return self._request("POST", "/v1/rights-grants", payload, headers)

    def list_rights_grants(self, headers, params=None):
        return self._request("GET", "/v1/rights-grants", headers=headers, params=params)

    def get_rights_grant(self, grant_id, headers):
        return self._request("GET", f"/v1/rights-grants/{grant_id}", headers=headers)

    def grant_activate(self, grant_id, headers):
        return self._request("POST", f"/v1/rights-grants/{grant_id}/activate", {}, headers)

    def grant_revoke(self, grant_id, headers):
        return self._request("POST", f"/v1/rights-grants/{grant_id}/revoke", {}, headers)

    # --- Playlist loops / entries / breaks ---
    def create_playlist_loop(self, payload, headers):
        return self._request("POST", "/v1/playlist-loops", payload, headers)

    def list_playlist_loops(self, headers, params=None):
        return self._request("GET", "/v1/playlist-loops", headers=headers, params=params)

    def get_playlist_loop(self, loop_id, headers):
        return self._request("GET", f"/v1/playlist-loops/{loop_id}", headers=headers)

    def loop_add_entry(self, loop_id, payload, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/entries", payload, headers)

    def list_playlist_entries(self, headers, params=None):
        return self._request("GET", "/v1/playlist-entries", headers=headers, params=params)

    def get_playlist_entry(self, entry_id, headers):
        return self._request("GET", f"/v1/playlist-entries/{entry_id}", headers=headers)

    def delete_playlist_entry(self, entry_id, headers):
        return self._request("DELETE", f"/v1/playlist-entries/{entry_id}", headers=headers)

    def loop_add_ad_break(self, loop_id, payload, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/ad-breaks", payload, headers)

    def list_ad_breaks(self, headers, params=None):
        return self._request("GET", "/v1/ad-breaks", headers=headers, params=params)

    def get_ad_break(self, break_id, headers):
        return self._request("GET", f"/v1/ad-breaks/{break_id}", headers=headers)

    def delete_ad_break(self, break_id, headers):
        return self._request("DELETE", f"/v1/ad-breaks/{break_id}", headers=headers)

    def loop_validate(self, loop_id, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/validate", {}, headers)

    def loop_revert_to_draft(self, loop_id, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/revert-to-draft", {}, headers)

    def loop_lock(self, loop_id, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/lock", {}, headers)

    def loop_unlock(self, loop_id, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/unlock", {}, headers)

    def loop_publish(self, loop_id, payload, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/publish", payload, headers)

    def loop_archive(self, loop_id, headers):
        return self._request("POST", f"/v1/playlist-loops/{loop_id}/archive", {}, headers)

    # --- Fill decisions ---
    def break_decision_run(self, break_id, payload, headers):
        return self._request("POST", f"/v1/ad-breaks/{break_id}/decision-runs", payload, headers)

    def break_mark_aired(self, break_id, headers):
        return self._request("POST", f"/v1/ad-breaks/{break_id}/mark-aired", {}, headers)

    def break_reconcile(self, break_id, headers):
        return self._request("POST", f"/v1/ad-breaks/{break_id}/reconcile", {}, headers)

    def list_fill_decisions(self, headers, params=None):
        return self._request("GET", "/v1/fill-decisions", headers=headers, params=params)

    def get_fill_decision(self, decision_id, headers):
        return self._request("GET", f"/v1/fill-decisions/{decision_id}", headers=headers)

    def fill_decision_void(self, decision_id, headers):
        return self._request("POST", f"/v1/fill-decisions/{decision_id}/void", {}, headers)

    # --- Ad campaigns ---
    def create_ad_campaign(self, payload, headers):
        return self._request("POST", "/v1/ad-campaigns", payload, headers)

    def list_ad_campaigns(self, headers, params=None):
        return self._request("GET", "/v1/ad-campaigns", headers=headers, params=params)

    def get_ad_campaign(self, campaign_id, headers):
        return self._request("GET", f"/v1/ad-campaigns/{campaign_id}", headers=headers)

    def campaign_activate(self, campaign_id, headers):
        return self._request("POST", f"/v1/ad-campaigns/{campaign_id}/activate", {}, headers)

    def campaign_pause(self, campaign_id, headers):
        return self._request("POST", f"/v1/ad-campaigns/{campaign_id}/pause", {}, headers)

    def campaign_resume(self, campaign_id, headers):
        return self._request("POST", f"/v1/ad-campaigns/{campaign_id}/resume", {}, headers)

    def campaign_complete(self, campaign_id, headers):
        return self._request("POST", f"/v1/ad-campaigns/{campaign_id}/complete", {}, headers)

    def campaign_adjust_budget(self, campaign_id, payload, headers):
        return self._request("POST", f"/v1/ad-campaigns/{campaign_id}/adjust-budget", payload, headers)

    # --- Ad creatives ---
    def create_ad_creative(self, payload, headers):
        return self._request("POST", "/v1/ad-creatives", payload, headers)

    def list_ad_creatives(self, headers, params=None):
        return self._request("GET", "/v1/ad-creatives", headers=headers, params=params)

    def get_ad_creative(self, creative_id, headers):
        return self._request("GET", f"/v1/ad-creatives/{creative_id}", headers=headers)

    def creative_approve(self, creative_id, headers):
        return self._request("POST", f"/v1/ad-creatives/{creative_id}/approve", {}, headers)

    def creative_reject(self, creative_id, payload, headers):
        return self._request("POST", f"/v1/ad-creatives/{creative_id}/reject", payload, headers)

    def creative_resubmit(self, creative_id, headers):
        return self._request("POST", f"/v1/ad-creatives/{creative_id}/resubmit", {}, headers)

    def creative_retire(self, creative_id, headers):
        return self._request("POST", f"/v1/ad-creatives/{creative_id}/retire", {}, headers)

    # --- House ads ---
    def create_house_ad(self, payload, headers):
        return self._request("POST", "/v1/house-ads", payload, headers)

    def list_house_ads(self, headers, params=None):
        return self._request("GET", "/v1/house-ads", headers=headers, params=params)

    def get_house_ad(self, house_ad_id, headers):
        return self._request("GET", f"/v1/house-ads/{house_ad_id}", headers=headers)

    def house_ad_patch(self, house_ad_id, payload, headers):
        return self._request("PATCH", f"/v1/house-ads/{house_ad_id}", payload, headers)

    # --- Distributor platforms ---
    def create_distributor_platform(self, payload, headers):
        return self._request("POST", "/v1/distributor-platforms", payload, headers)

    def list_distributor_platforms(self, headers, params=None):
        return self._request("GET", "/v1/distributor-platforms", headers=headers, params=params)

    def get_distributor_platform(self, platform_id, headers):
        return self._request("GET", f"/v1/distributor-platforms/{platform_id}", headers=headers)

    def platform_patch(self, platform_id, payload, headers):
        return self._request("PATCH", f"/v1/distributor-platforms/{platform_id}", payload, headers)

    # --- Distribution agreements ---
    def create_distribution_agreement(self, payload, headers):
        return self._request("POST", "/v1/distribution-agreements", payload, headers)

    def list_distribution_agreements(self, headers, params=None):
        return self._request("GET", "/v1/distribution-agreements", headers=headers, params=params)

    def get_distribution_agreement(self, agreement_id, headers):
        return self._request("GET", f"/v1/distribution-agreements/{agreement_id}", headers=headers)

    def agreement_patch(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/v1/distribution-agreements/{agreement_id}", payload, headers)

    # --- Revenue reports ---
    def create_revenue_report(self, payload, headers):
        return self._request("POST", "/v1/revenue-reports", payload, headers)

    def list_revenue_reports(self, headers, params=None):
        return self._request("GET", "/v1/revenue-reports", headers=headers, params=params)

    def get_revenue_report(self, report_id, headers):
        return self._request("GET", f"/v1/revenue-reports/{report_id}", headers=headers)

    def report_generate_provisional(self, report_id, headers):
        return self._request("POST", f"/v1/revenue-reports/{report_id}/generate-provisional", {}, headers)

    def report_recompute(self, report_id, payload, headers):
        return self._request("POST", f"/v1/revenue-reports/{report_id}/recompute", payload, headers)

    def report_finalize(self, report_id, headers):
        return self._request("POST", f"/v1/revenue-reports/{report_id}/finalize", {}, headers)

    def report_dispute(self, report_id, payload, headers):
        return self._request("POST", f"/v1/revenue-reports/{report_id}/dispute", payload, headers)

    def report_refinalize(self, report_id, headers):
        return self._request("POST", f"/v1/revenue-reports/{report_id}/refinalize", {}, headers)

    def report_settle(self, report_id, headers):
        return self._request("POST", f"/v1/revenue-reports/{report_id}/settle", {}, headers)

    # --- Viewership events ---
    def create_viewership_event(self, payload, headers):
        return self._request("POST", "/v1/viewership-events", payload, headers)

    def list_viewership_events(self, headers, params=None):
        return self._request("GET", "/v1/viewership-events", headers=headers, params=params)

    def get_viewership_event(self, event_id, headers):
        return self._request("GET", f"/v1/viewership-events/{event_id}", headers=headers)

    # --- Channel-day snapshots ---
    def create_snapshot_computation(self, channel_id, payload, headers):
        return self._request("POST", f"/v1/channels/{channel_id}/snapshot-computations", payload, headers)

    def list_channel_day_snapshots(self, headers, params=None):
        return self._request("GET", "/v1/channel-day-snapshots", headers=headers, params=params)

    def get_channel_day_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/v1/channel-day-snapshots/{snapshot_id}", headers=headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/v1/_clock/set-current-utc", payload, headers)


api_client = ApiClient()
