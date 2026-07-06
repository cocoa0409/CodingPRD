"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/activate", {}, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/reinstate", {}, headers)

    def churn_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/churn", {}, headers)

    def close_cycle(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/cycles/close", {}, headers)

    def get_churn_quote(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}/churn-quote", headers=headers)

    def create_analytics_snapshot(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/analytics-snapshots", payload, headers)

    # ---- Retainer Packages ----
    def create_retainer_package(self, payload, headers):
        return self._request("POST", "/retainer-packages", payload, headers)

    def list_retainer_packages(self, headers, params=None):
        return self._request("GET", "/retainer-packages", headers=headers, params=params)

    def get_retainer_package(self, package_id, headers):
        return self._request("GET", f"/retainer-packages/{package_id}", headers=headers)

    def activate_retainer_package(self, package_id, headers):
        return self._request("POST", f"/retainer-packages/{package_id}/activate", {}, headers)

    # ---- Channels ----
    def create_channel(self, payload, headers):
        return self._request("POST", "/channels", payload, headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", "/channels", headers=headers, params=params)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    def connect_channel(self, channel_id, headers):
        return self._request("POST", f"/channels/{channel_id}/connect", {}, headers)

    def go_live_channel(self, channel_id, headers):
        return self._request("POST", f"/channels/{channel_id}/go-live", {}, headers)

    def disconnect_channel(self, channel_id, headers):
        return self._request("POST", f"/channels/{channel_id}/disconnect", {}, headers)

    # ---- Content Items ----
    def create_content_item(self, payload, headers):
        return self._request("POST", "/content-items", payload, headers)

    def list_content_items(self, headers, params=None):
        return self._request("GET", "/content-items", headers=headers, params=params)

    def get_content_item(self, content_item_id, headers):
        return self._request("GET", f"/content-items/{content_item_id}", headers=headers)

    def submit_content_item(self, content_item_id, headers):
        return self._request("POST", f"/content-items/{content_item_id}/submit", {}, headers)

    def request_changes_content_item(self, content_item_id, headers, payload=None):
        return self._request("POST", f"/content-items/{content_item_id}/request-changes", payload or {}, headers)

    def resubmit_content_item(self, content_item_id, headers):
        return self._request("POST", f"/content-items/{content_item_id}/resubmit", {}, headers)

    def approve_content_item(self, content_item_id, headers):
        return self._request("POST", f"/content-items/{content_item_id}/approve", {}, headers)

    def schedule_content_item(self, content_item_id, payload, headers):
        return self._request("POST", f"/content-items/{content_item_id}/schedule", payload, headers)

    def unschedule_content_item(self, content_item_id, headers):
        return self._request("POST", f"/content-items/{content_item_id}/unschedule", {}, headers)

    def publish_content_item(self, content_item_id, headers):
        return self._request("POST", f"/content-items/{content_item_id}/publish", {}, headers)

    def archive_content_item(self, content_item_id, headers):
        return self._request("POST", f"/content-items/{content_item_id}/archive", {}, headers)

    # ---- Content Targets ----
    def create_content_target(self, payload, headers):
        return self._request("POST", "/content-targets", payload, headers)

    def list_content_targets(self, headers, params=None):
        return self._request("GET", "/content-targets", headers=headers, params=params)

    def get_content_target(self, target_id, headers):
        return self._request("GET", f"/content-targets/{target_id}", headers=headers)

    # ---- Schedule Slots ----
    def list_schedule_slots(self, headers, params=None):
        return self._request("GET", "/schedule-slots", headers=headers, params=params)

    def get_schedule_slot(self, slot_id, headers):
        return self._request("GET", f"/schedule-slots/{slot_id}", headers=headers)

    # ---- Boost Campaigns ----
    def create_boost_campaign(self, payload, headers):
        return self._request("POST", "/boost-campaigns", payload, headers)

    def list_boost_campaigns(self, headers, params=None):
        return self._request("GET", "/boost-campaigns", headers=headers, params=params)

    def get_boost_campaign(self, boost_id, headers):
        return self._request("GET", f"/boost-campaigns/{boost_id}", headers=headers)

    def reserve_boost_campaign(self, boost_id, payload, headers):
        return self._request("POST", f"/boost-campaigns/{boost_id}/reserve", payload, headers)

    def launch_boost_campaign(self, boost_id, headers):
        return self._request("POST", f"/boost-campaigns/{boost_id}/launch", {}, headers)

    def record_spend_boost_campaign(self, boost_id, payload, headers):
        return self._request("POST", f"/boost-campaigns/{boost_id}/record-spend", payload, headers)

    def complete_boost_campaign(self, boost_id, headers):
        return self._request("POST", f"/boost-campaigns/{boost_id}/complete", {}, headers)

    def cancel_boost_campaign(self, boost_id, headers):
        return self._request("POST", f"/boost-campaigns/{boost_id}/cancel", {}, headers)

    # ---- Ledger ----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ---- Conversations ----
    def create_conversation(self, payload, headers):
        return self._request("POST", "/conversations", payload, headers)

    def list_conversations(self, headers, params=None):
        return self._request("GET", "/conversations", headers=headers, params=params)

    def get_conversation(self, conversation_id, headers):
        return self._request("GET", f"/conversations/{conversation_id}", headers=headers)

    def assign_conversation(self, conversation_id, headers):
        return self._request("POST", f"/conversations/{conversation_id}/assign", {}, headers)

    def escalate_conversation(self, conversation_id, headers, payload=None):
        return self._request("POST", f"/conversations/{conversation_id}/escalate", payload or {}, headers)

    def resolve_conversation(self, conversation_id, headers):
        return self._request("POST", f"/conversations/{conversation_id}/resolve", {}, headers)

    # ---- Engagement Messages ----
    def create_message(self, payload, headers):
        return self._request("POST", "/messages", payload, headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/messages", headers=headers, params=params)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/messages/{message_id}", headers=headers)

    # ---- Influencer Collabs ----
    def create_influencer_collab(self, payload, headers):
        return self._request("POST", "/influencer-collabs", payload, headers)

    def list_influencer_collabs(self, headers, params=None):
        return self._request("GET", "/influencer-collabs", headers=headers, params=params)

    def get_influencer_collab(self, collab_id, headers):
        return self._request("GET", f"/influencer-collabs/{collab_id}", headers=headers)

    def counter_influencer_collab(self, collab_id, payload, headers):
        return self._request("POST", f"/influencer-collabs/{collab_id}/counter", payload, headers)

    def accept_influencer_collab(self, collab_id, headers):
        return self._request("POST", f"/influencer-collabs/{collab_id}/accept", {}, headers)

    def mark_delivered_influencer_collab(self, collab_id, headers):
        return self._request("POST", f"/influencer-collabs/{collab_id}/mark-delivered", {}, headers)

    def close_influencer_collab(self, collab_id, headers):
        return self._request("POST", f"/influencer-collabs/{collab_id}/close", {}, headers)

    def cancel_influencer_collab(self, collab_id, headers):
        return self._request("POST", f"/influencer-collabs/{collab_id}/cancel", {}, headers)

    def get_settlement_quote(self, collab_id, headers):
        return self._request("GET", f"/influencer-collabs/{collab_id}/settlement-quote", headers=headers)

    # ---- UGC Assets ----
    def create_ugc_asset(self, payload, headers):
        return self._request("POST", "/ugc-assets", payload, headers)

    def list_ugc_assets(self, headers, params=None):
        return self._request("GET", "/ugc-assets", headers=headers, params=params)

    def get_ugc_asset(self, asset_id, headers):
        return self._request("GET", f"/ugc-assets/{asset_id}", headers=headers)

    def clear_rights_ugc_asset(self, asset_id, headers):
        return self._request("POST", f"/ugc-assets/{asset_id}/clear-rights", {}, headers)

    def reject_ugc_asset(self, asset_id, headers):
        return self._request("POST", f"/ugc-assets/{asset_id}/reject", {}, headers)

    # ---- Analytics ----
    def list_analytics_snapshots(self, headers, params=None):
        return self._request("GET", "/analytics-snapshots", headers=headers, params=params)

    def get_analytics_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/analytics-snapshots/{snapshot_id}", headers=headers)


api_client = ApiClient()
