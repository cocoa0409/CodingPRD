"""A thin domain wrapper over the generic HTTP client.

Every method is one row of the contract's endpoint table. Methods return the
raw response object so callers decide whether the call is expected to succeed
(``validate_success``) or to be refused (``validate_error``).
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from . import constants as C


class AdvocacyClient:
    """Domain-named calls against the grassroots advocacy service."""

    def __init__(self, base_url: Optional[str] = None):
        self._client = GenericApiClient(base_url)

    # ------------------------------------------------------------------
    # Escape hatch for the handful of cases that need a raw call
    # ------------------------------------------------------------------

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                headers: Optional[Dict[str, str]] = None,
                params: Optional[Dict[str, Any]] = None):
        return self._client._request(method, path, payload=payload,
                                    headers=headers, params=params)

    def get_raw(self, path: str, headers=None, params=None):
        return self._client.get(path, headers=headers, params=params)

    def post_raw(self, path: str, payload=None, headers=None):
        return self._client.post(path, json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers=None):
        """Park the service's logical clock at a chosen instant."""
        return self._client.post(C.CLOCK_SET_PATH,
                                 json={"current_utc": current_utc},
                                 headers=headers)

    # ------------------------------------------------------------------
    # Campaign
    # ------------------------------------------------------------------

    def create_campaign(self, payload, headers=None):
        return self._client.post(C.CAMPAIGNS, json=payload, headers=headers)

    def list_campaigns(self, headers=None, params=None):
        return self._client.get(C.CAMPAIGNS, headers=headers, params=params)

    def get_campaign(self, campaign_id, headers=None):
        return self._client.get(C.campaign_path(campaign_id), headers=headers)

    def launch_campaign(self, campaign_id, payload=None, headers=None):
        return self._client.post(C.campaign_launch_path(campaign_id),
                                 json=payload if payload is not None else {},
                                 headers=headers)

    def close_campaign(self, campaign_id, payload=None, headers=None):
        return self._client.post(C.campaign_close_path(campaign_id),
                                 json=payload if payload is not None else {},
                                 headers=headers)

    def override_posture(self, campaign_id, payload, headers=None):
        return self._client.post(C.campaign_posture_overrides_path(campaign_id),
                                 json=payload, headers=headers)

    def resolve_message_test(self, campaign_id, payload, headers=None):
        return self._client.post(
            C.campaign_message_test_resolutions_path(campaign_id),
            json=payload, headers=headers)

    def get_outcome_report(self, campaign_id, headers=None):
        return self._client.get(C.campaign_outcome_report_path(campaign_id),
                                headers=headers)

    def list_campaign_milestones(self, campaign_id, headers=None, params=None):
        return self._client.get(C.campaign_milestones_path(campaign_id),
                                headers=headers, params=params)

    def list_campaign_partners(self, campaign_id, headers=None, params=None):
        return self._client.get(C.campaign_partners_path(campaign_id),
                                headers=headers, params=params)

    # ------------------------------------------------------------------
    # Milestone
    # ------------------------------------------------------------------

    def create_milestone(self, payload, headers=None):
        return self._client.post(C.MILESTONES, json=payload, headers=headers)

    def list_milestones(self, headers=None, params=None):
        return self._client.get(C.MILESTONES, headers=headers, params=params)

    def get_milestone(self, milestone_id, headers=None):
        return self._client.get(C.milestone_path(milestone_id), headers=headers)

    def reschedule_milestone(self, milestone_id, payload, headers=None):
        return self._client.post(C.milestone_reschedule_path(milestone_id),
                                 json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Legislator
    # ------------------------------------------------------------------

    def create_legislator(self, payload, headers=None):
        return self._client.post(C.LEGISLATORS, json=payload, headers=headers)

    def list_legislators(self, headers=None, params=None):
        return self._client.get(C.LEGISLATORS, headers=headers, params=params)

    def get_legislator(self, legislator_id, headers=None):
        return self._client.get(C.legislator_path(legislator_id), headers=headers)

    def update_stance(self, legislator_id, payload, headers=None):
        return self._client.post(C.legislator_stance_updates_path(legislator_id),
                                 json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Supporter
    # ------------------------------------------------------------------

    def create_supporter(self, payload, headers=None):
        return self._client.post(C.SUPPORTERS, json=payload, headers=headers)

    def list_supporters(self, headers=None, params=None):
        return self._client.get(C.SUPPORTERS, headers=headers, params=params)

    def get_supporter(self, supporter_id, headers=None):
        return self._client.get(C.supporter_path(supporter_id), headers=headers)

    def list_supporter_consent_events(self, supporter_id, headers=None, params=None):
        return self._client.get(C.supporter_consent_events_path(supporter_id),
                                headers=headers, params=params)

    def list_supporter_spokesperson_profiles(self, supporter_id, headers=None,
                                             params=None):
        return self._client.get(
            C.supporter_spokesperson_profiles_path(supporter_id),
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Consent events
    # ------------------------------------------------------------------

    def create_consent_event(self, payload, headers=None):
        return self._client.post(C.CONSENT_EVENTS, json=payload, headers=headers)

    def list_consent_events(self, headers=None, params=None):
        return self._client.get(C.CONSENT_EVENTS, headers=headers, params=params)

    def get_consent_event(self, consent_event_id, headers=None):
        return self._client.get(C.consent_event_path(consent_event_id),
                                headers=headers)

    # ------------------------------------------------------------------
    # Segment
    # ------------------------------------------------------------------

    def create_segment(self, payload, headers=None):
        return self._client.post(C.SEGMENTS, json=payload, headers=headers)

    def list_segments(self, headers=None, params=None):
        return self._client.get(C.SEGMENTS, headers=headers, params=params)

    def get_segment(self, segment_id, headers=None):
        return self._client.get(C.segment_path(segment_id), headers=headers)

    def refresh_segment(self, segment_id, payload=None, headers=None):
        return self._client.post(C.segment_refresh_path(segment_id),
                                 json=payload if payload is not None else {},
                                 headers=headers)

    # ------------------------------------------------------------------
    # Message variant
    # ------------------------------------------------------------------

    def create_variant(self, payload, headers=None):
        return self._client.post(C.MESSAGE_VARIANTS, json=payload, headers=headers)

    def list_variants(self, headers=None, params=None):
        return self._client.get(C.MESSAGE_VARIANTS, headers=headers, params=params)

    def get_variant(self, variant_id, headers=None):
        return self._client.get(C.variant_path(variant_id), headers=headers)

    def submit_variant(self, variant_id, payload, headers=None):
        return self._client.post(C.variant_submit_path(variant_id),
                                 json=payload, headers=headers)

    def review_variant(self, variant_id, payload, headers=None):
        return self._client.post(C.variant_review_decisions_path(variant_id),
                                 json=payload, headers=headers)

    def lock_variant(self, variant_id, payload=None, headers=None):
        return self._client.post(C.variant_lock_path(variant_id),
                                 json=payload if payload is not None else {},
                                 headers=headers)

    def reopen_variant(self, variant_id, payload, headers=None):
        return self._client.post(C.variant_reopen_path(variant_id),
                                 json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Coalition partner
    # ------------------------------------------------------------------

    def create_partner(self, payload, headers=None):
        return self._client.post(C.COALITION_PARTNERS, json=payload, headers=headers)

    def list_partners(self, headers=None, params=None):
        return self._client.get(C.COALITION_PARTNERS, headers=headers, params=params)

    def get_partner(self, partner_id, headers=None):
        return self._client.get(C.partner_path(partner_id), headers=headers)

    def withdraw_partner(self, partner_id, payload, headers=None):
        return self._client.post(C.partner_withdraw_path(partner_id),
                                 json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Partner endorsement
    # ------------------------------------------------------------------

    def create_endorsement(self, payload, headers=None):
        return self._client.post(C.PARTNER_ENDORSEMENTS, json=payload,
                                 headers=headers)

    def list_endorsements(self, headers=None, params=None):
        return self._client.get(C.PARTNER_ENDORSEMENTS, headers=headers,
                                params=params)

    def get_endorsement(self, endorsement_id, headers=None):
        return self._client.get(C.endorsement_path(endorsement_id), headers=headers)

    def revoke_endorsement(self, endorsement_id, payload=None, headers=None):
        return self._client.post(C.endorsement_revoke_path(endorsement_id),
                                 json=payload if payload is not None else {},
                                 headers=headers)

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def create_activation(self, payload, headers=None):
        return self._client.post(C.ACTIVATIONS, json=payload, headers=headers)

    def list_activations(self, headers=None, params=None):
        return self._client.get(C.ACTIVATIONS, headers=headers, params=params)

    def get_activation(self, activation_id, headers=None):
        return self._client.get(C.activation_path(activation_id), headers=headers)

    def clear_activation(self, activation_id, payload, headers=None):
        return self._client.post(C.activation_clear_path(activation_id),
                                 json=payload, headers=headers)

    def block_activation(self, activation_id, payload, headers=None):
        return self._client.post(C.activation_block_path(activation_id),
                                 json=payload, headers=headers)

    def start_send(self, activation_id, payload=None, headers=None):
        return self._client.post(C.activation_start_send_path(activation_id),
                                 json=payload if payload is not None else {},
                                 headers=headers)

    def complete_activation(self, activation_id, payload, headers=None):
        return self._client.post(C.activation_complete_path(activation_id),
                                 json=payload, headers=headers)

    def abort_activation(self, activation_id, payload, headers=None):
        return self._client.post(C.activation_abort_path(activation_id),
                                 json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Action record
    # ------------------------------------------------------------------

    def create_action_record(self, payload, headers=None):
        return self._client.post(C.ACTION_RECORDS, json=payload, headers=headers)

    def list_action_records(self, headers=None, params=None):
        return self._client.get(C.ACTION_RECORDS, headers=headers, params=params)

    def get_action_record(self, action_record_id, headers=None):
        return self._client.get(C.action_record_path(action_record_id),
                                headers=headers)

    def acknowledge_action(self, action_record_id, payload, headers=None):
        return self._client.post(C.action_acknowledge_path(action_record_id),
                                 json=payload, headers=headers)

    def thank_action(self, action_record_id, payload, headers=None):
        return self._client.post(C.action_thank_path(action_record_id),
                                 json=payload, headers=headers)

    def dispute_action(self, action_record_id, payload, headers=None):
        return self._client.post(C.action_dispute_path(action_record_id),
                                 json=payload, headers=headers)

    def resolve_dispute(self, action_record_id, payload, headers=None):
        return self._client.post(
            C.action_dispute_resolutions_path(action_record_id),
            json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Spokesperson
    # ------------------------------------------------------------------

    def create_spokesperson(self, payload, headers=None):
        return self._client.post(C.SPOKESPERSONS, json=payload, headers=headers)

    def list_spokespersons(self, headers=None, params=None):
        return self._client.get(C.SPOKESPERSONS, headers=headers, params=params)

    def get_spokesperson(self, spokesperson_id, headers=None):
        return self._client.get(C.spokesperson_path(spokesperson_id),
                                headers=headers)

    def advance_training(self, spokesperson_id, payload, headers=None):
        return self._client.post(
            C.spokesperson_training_advancements_path(spokesperson_id),
            json=payload, headers=headers)

    # ------------------------------------------------------------------
    # District meeting
    # ------------------------------------------------------------------

    def create_meeting(self, payload, headers=None):
        return self._client.post(C.DISTRICT_MEETINGS, json=payload, headers=headers)

    def list_meetings(self, headers=None, params=None):
        return self._client.get(C.DISTRICT_MEETINGS, headers=headers, params=params)

    def get_meeting(self, meeting_id, headers=None):
        return self._client.get(C.meeting_path(meeting_id), headers=headers)

    def respond_to_meeting(self, meeting_id, payload, headers=None):
        return self._client.post(C.meeting_response_path(meeting_id),
                                 json=payload, headers=headers)

    def complete_meeting(self, meeting_id, payload, headers=None):
        return self._client.post(C.meeting_complete_path(meeting_id),
                                 json=payload, headers=headers)
