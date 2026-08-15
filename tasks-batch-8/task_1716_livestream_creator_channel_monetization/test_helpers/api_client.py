"""API client: one method per endpoint defined in the PRD (endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and ops checkpoint (PlatformAdmin test-driving endpoints)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def ops_run(self, headers):
        return self._request("POST", "/api/ops/run", {}, headers)

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------
    def create_channel(self, payload, headers):
        return self._request("POST", "/api/channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/api/channels/{channel_id}", headers=headers)

    def update_payout_settings(self, channel_id, payload, headers):
        return self._request("PATCH", f"/api/channels/{channel_id}/payout-settings",
                             payload, headers)

    # ------------------------------------------------------------------
    # Tax forms
    # ------------------------------------------------------------------
    def submit_tax_form(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/tax-forms",
                             payload, headers)

    def get_tax_form(self, tax_form_id, headers):
        return self._request("GET", f"/api/tax-forms/{tax_form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/api/tax-forms", headers=headers, params=params)

    def transition_tax_form(self, tax_form_id, payload, headers):
        return self._request("POST", f"/api/tax-forms/{tax_form_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Revenue events
    # ------------------------------------------------------------------
    def ingest_revenue_event(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/revenue-events",
                             payload, headers)

    def get_revenue_event(self, revenue_event_id, headers):
        return self._request("GET", f"/api/revenue-events/{revenue_event_id}",
                             headers=headers)

    def list_revenue_events(self, headers, params=None):
        return self._request("GET", "/api/revenue-events", headers=headers, params=params)

    def reverse_revenue_event(self, revenue_event_id, payload, headers):
        return self._request("POST", f"/api/revenue-events/{revenue_event_id}/reverse",
                             payload, headers)

    # ------------------------------------------------------------------
    # Payouts
    # ------------------------------------------------------------------
    def open_payout(self, channel_id, headers):
        return self._request("POST", f"/api/channels/{channel_id}/payouts", {}, headers)

    def list_payouts(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/payouts",
                             headers=headers, params=params)

    def transition_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Subscription tiers
    # ------------------------------------------------------------------
    def create_tier(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/tiers",
                             payload, headers)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/api/tiers/{tier_id}", headers=headers)

    def list_tiers(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/tiers",
                             headers=headers, params=params)

    def transition_tier(self, tier_id, payload, headers):
        return self._request("POST", f"/api/tiers/{tier_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Viewers
    # ------------------------------------------------------------------
    def create_viewer(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/viewers",
                             payload, headers)

    def get_viewer(self, viewer_id, headers):
        return self._request("GET", f"/api/viewers/{viewer_id}", headers=headers)

    def list_viewers(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/viewers",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    def create_subscription(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/subscriptions",
                             payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}",
                             headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def transition_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Perk grants
    # ------------------------------------------------------------------
    def list_perk_grants(self, subscription_id, headers, params=None):
        return self._request("GET", f"/api/subscriptions/{subscription_id}/perk-grants",
                             headers=headers, params=params)

    def transition_perk_grant(self, perk_grant_id, payload, headers):
        return self._request("POST", f"/api/perk-grants/{perk_grant_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Moderators
    # ------------------------------------------------------------------
    def create_moderator(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/moderators",
                             payload, headers)

    def get_moderator(self, moderator_id, headers):
        return self._request("GET", f"/api/moderators/{moderator_id}", headers=headers)

    def list_moderators(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/moderators",
                             headers=headers, params=params)

    def transition_moderator(self, moderator_id, payload, headers):
        return self._request("POST", f"/api/moderators/{moderator_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Moderation actions
    # ------------------------------------------------------------------
    def create_moderation_action(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/moderation-actions",
                             payload, headers)

    def get_moderation_action(self, moderation_action_id, headers):
        return self._request("GET", f"/api/moderation-actions/{moderation_action_id}",
                             headers=headers)

    def list_moderation_actions(self, headers, params=None):
        return self._request("GET", "/api/moderation-actions",
                             headers=headers, params=params)

    def reverse_moderation_action(self, moderation_action_id, payload, headers):
        return self._request("POST",
                             f"/api/moderation-actions/{moderation_action_id}/reverse",
                             payload, headers)

    # ------------------------------------------------------------------
    # Content strikes
    # ------------------------------------------------------------------
    def create_strike(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/strikes",
                             payload, headers)

    def list_strikes(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/strikes",
                             headers=headers, params=params)

    def appeal_strike(self, strike_id, payload, headers):
        return self._request("POST", f"/api/strikes/{strike_id}/appeal",
                             payload, headers)

    def resolve_strike_appeal(self, strike_id, payload, headers):
        return self._request("POST", f"/api/strikes/{strike_id}/resolve-appeal",
                             payload, headers)

    # ------------------------------------------------------------------
    # Sponsorship deals
    # ------------------------------------------------------------------
    def create_deal(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/deals",
                             payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/api/deals/{deal_id}", headers=headers)

    def list_deals(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/deals",
                             headers=headers, params=params)

    def transition_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/api/deals/{deal_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Deliverables
    # ------------------------------------------------------------------
    def create_deliverable(self, deal_id, payload, headers):
        return self._request("POST", f"/api/deals/{deal_id}/deliverables",
                             payload, headers)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/api/deliverables/{deliverable_id}",
                             headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/api/deliverables", headers=headers, params=params)

    def transition_deliverable(self, deliverable_id, payload, headers):
        return self._request("POST", f"/api/deliverables/{deliverable_id}/transition",
                             payload, headers)

    def reschedule_deliverable(self, deliverable_id, payload, headers):
        return self._request("POST", f"/api/deliverables/{deliverable_id}/reschedule",
                             payload, headers)

    # ------------------------------------------------------------------
    # Stream sessions
    # ------------------------------------------------------------------
    def create_stream(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/streams",
                             payload, headers)

    def get_stream(self, stream_id, headers):
        return self._request("GET", f"/api/streams/{stream_id}", headers=headers)

    def list_streams(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/streams",
                             headers=headers, params=params)

    def transition_stream(self, stream_id, payload, headers):
        return self._request("POST", f"/api/streams/{stream_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Simulcast grants
    # ------------------------------------------------------------------
    def create_simulcast_grant(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/simulcast-grants",
                             payload, headers)

    def list_simulcast_grants(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/simulcast-grants",
                             headers=headers, params=params)

    def transition_simulcast_grant(self, simulcast_grant_id, payload, headers):
        return self._request("POST",
                             f"/api/simulcast-grants/{simulcast_grant_id}/transition",
                             payload, headers)


api_client = ApiClient()
