"""Scenario builders that drive the API up to a chosen precondition.

Every test starts against an empty store, so each of these builders composes
preconditions out of nothing but published endpoints. They are arranged in
tiers, cheapest first:

* state progression — park the clock, raise a campaign, launch it
* entity hierarchy — legislators, supporters, segments, partners, variants
* lifecycle shortcuts — a variant already LOCKED, a wave already SENDING
* accumulation targeting — enough actions or touches to sit on a threshold
* terminal states — a closed campaign, an aborted wave, a withdrawn partner

Builders use ``get_success_data`` rather than the strict success validator so
that a setup failure reports itself as a setup problem rather than masquerading
as the assertion under test. Every builder accepts ``**overrides`` that are
forwarded to the underlying payload factory.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import AdvocacyClient
from .test_users import (
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
    make_partner_delegate_headers,
    make_supporter_headers,
)
from .types import (
    APPROVAL_CLEARED,
    CHANNEL_EMAIL,
    MILESTONE_FLOOR_VOTE,
    PARTNER_TIER_ANCHOR,
    REVIEW_DECISION_APPROVE,
    TRAINING_CERTIFIED,
    TRAINING_TRAINED,
)


# --------------------------------------------------------------------------
# Tier 1: clock and campaign state progression
# --------------------------------------------------------------------------

def park_clock(client: AdvocacyClient, current_utc: str = C.CLOCK_DEFAULT_UTC) -> str:
    """Park the service's logical clock at an exact instant.

    Returns the instant the service reports as current afterwards.
    """
    data = get_success_data(
        client.set_clock(current_utc, headers=make_campaign_director_headers()))
    return data["current_utc"]


def create_draft_campaign(client: AdvocacyClient, **overrides: Any) -> Dict[str, Any]:
    """Raise a campaign and leave it in its initial pre-launch state."""
    return get_success_data(
        client.create_campaign(F.campaign_payload(**overrides),
                               headers=make_campaign_director_headers()))


def add_legislator(client: AdvocacyClient, campaign_id: str,
                   **overrides: Any) -> Dict[str, Any]:
    """Register one target legislator under a campaign."""
    return get_success_data(
        client.create_legislator(F.legislator_payload(campaign_id, **overrides),
                                 headers=make_campaign_director_headers()))


def launch_campaign(client: AdvocacyClient, campaign_id: str) -> Dict[str, Any]:
    """Move a campaign into its active phase."""
    return get_success_data(
        client.launch_campaign(campaign_id,
                               headers=make_campaign_director_headers()))


def create_active_campaign(client: AdvocacyClient,
                           clock: str = C.CLOCK_DEFAULT_UTC,
                           legislator_overrides: Optional[Dict[str, Any]] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """Park the clock, raise a campaign with one legislator, and launch it.

    Returns ``{"clock", "campaign", "campaign_id", "legislator",
    "legislator_id"}``.
    """
    parked = park_clock(client, clock)
    campaign = create_draft_campaign(client, **overrides)
    legislator = add_legislator(client, campaign["id"],
                               **(legislator_overrides or {}))
    launched = launch_campaign(client, campaign["id"])
    return {
        "clock": parked,
        "campaign": launched,
        "campaign_id": campaign["id"],
        "legislator": legislator,
        "legislator_id": legislator["id"],
    }


def close_campaign(client: AdvocacyClient, campaign_id: str) -> Dict[str, Any]:
    """Bring a campaign to its terminal closed state."""
    return get_success_data(
        client.close_campaign(campaign_id,
                              headers=make_campaign_director_headers()))


def override_posture(client: AdvocacyClient, campaign_id: str,
                     posture_override: str, **overrides: Any) -> Dict[str, Any]:
    """Record a director's standing posture override on a campaign."""
    return get_success_data(
        client.override_posture(
            campaign_id,
            F.posture_override_payload(posture_override, **overrides),
            headers=make_campaign_director_headers()))


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy
# --------------------------------------------------------------------------

def add_supporter(client: AdvocacyClient, campaign_id: str,
                  channels: Optional[List[str]] = None,
                  with_phone: bool = False,
                  **overrides: Any) -> Dict[str, Any]:
    """Enrol a supporter with consent captured for the channels named."""
    channels = [CHANNEL_EMAIL] if channels is None else list(channels)
    needs_phone = with_phone or any(ch in ("SMS", "PHONE") for ch in channels)
    if needs_phone:
        payload = F.supporter_payload_with_phone(
            campaign_id, initial_consent_channels=channels, **overrides)
    else:
        payload = F.supporter_payload(
            campaign_id, initial_consent_channels=channels, **overrides)
    return get_success_data(
        client.create_supporter(payload,
                               headers=make_field_organizer_headers()))


def add_supporters(client: AdvocacyClient, campaign_id: str, count: int,
                   channels: Optional[List[str]] = None,
                   district_code: str = "HD-14",
                   **overrides: Any) -> List[Dict[str, Any]]:
    """Enrol several distinctly named supporters in one district."""
    supporters = []
    for index in range(1, count + 1):
        supporters.append(add_supporter(
            client, campaign_id, channels=channels,
            full_name=f"Sup {index}",
            email=f"s{index}@example.org",
            district_code=district_code,
            phone=f"+1555010000{index}",
            consent_source_reference=f"web-form-{index}",
            **overrides))
    return supporters


def add_segment(client: AdvocacyClient, campaign_id: str,
                **overrides: Any) -> Dict[str, Any]:
    """Define a targeting segment over a campaign's supporters."""
    return get_success_data(
        client.create_segment(F.segment_payload(campaign_id, **overrides),
                              headers=make_message_strategist_headers()))


def refresh_segment(client: AdvocacyClient, segment_id: str) -> Dict[str, Any]:
    """Recompute a segment's membership snapshot."""
    return get_success_data(
        client.refresh_segment(segment_id,
                               headers=make_message_strategist_headers()))


def add_milestone(client: AdvocacyClient, campaign_id: str,
                  window_start: str, window_end: str,
                  kind: str = MILESTONE_FLOOR_VOTE,
                  **overrides: Any) -> Dict[str, Any]:
    """Place a legislative milestone on a campaign's calendar."""
    return get_success_data(
        client.create_milestone(
            F.milestone_payload(campaign_id, window_start, window_end,
                                kind=kind, **overrides),
            headers=make_campaign_director_headers()))


def add_partner(client: AdvocacyClient, campaign_id: str,
                tier: str = PARTNER_TIER_ANCHOR,
                org_name: str = "Anchor Housing Alliance",
                **overrides: Any) -> Dict[str, Any]:
    """Admit one coalition partner to a campaign."""
    return get_success_data(
        client.create_partner(
            F.partner_payload(campaign_id, org_name=org_name, tier=tier,
                              **overrides),
            headers=make_campaign_director_headers()))


def add_partners(client: AdvocacyClient, campaign_id: str,
                 tiers: List[str]) -> List[Dict[str, Any]]:
    """Admit several partners, one per tier named, in order."""
    partners = []
    for index, tier in enumerate(tiers, start=1):
        partners.append(add_partner(
            client, campaign_id, tier=tier,
            org_name=f"{tier.title()} Org {index}",
            branding_asset_ref=f"brand/{tier.lower()}-{index}.svg"))
    return partners


def withdraw_partner(client: AdvocacyClient, partner_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Record a partner's withdrawal from a coalition."""
    return get_success_data(
        client.withdraw_partner(partner_id,
                               F.partner_withdraw_payload(**overrides),
                               headers=make_campaign_director_headers()))


# --------------------------------------------------------------------------
# Tier 2b: consent log
# --------------------------------------------------------------------------

def append_consent(client: AdvocacyClient, supporter_id: str, channel: str,
                   action: str, **overrides: Any) -> Dict[str, Any]:
    """Append one entry to a supporter's consent log."""
    return get_success_data(
        client.create_consent_event(
            F.consent_event_payload(supporter_id, channel, action, **overrides),
            headers=make_field_organizer_headers()))


def grant_consent(client: AdvocacyClient, supporter_id: str, channel: str,
                  **overrides: Any) -> Dict[str, Any]:
    """Record a grant of consent on one channel or on every channel."""
    return append_consent(client, supporter_id, channel, "GRANT", **overrides)


def revoke_consent(client: AdvocacyClient, supporter_id: str, channel: str,
                   **overrides: Any) -> Dict[str, Any]:
    """Record a withdrawal of consent on one channel or on every channel."""
    return append_consent(client, supporter_id, channel, "REVOKE", **overrides)


def suppress_supporter(client: AdvocacyClient, supporter_id: str) -> Dict[str, Any]:
    """Withdraw consent across every channel at once."""
    return revoke_consent(client, supporter_id, "ALL")


def read_supporter(client: AdvocacyClient, supporter_id: str) -> Dict[str, Any]:
    """Read a supporter as an operator who may see the whole record."""
    return get_success_data(
        client.get_supporter(supporter_id,
                             headers=make_field_organizer_headers()))


def read_campaign(client: AdvocacyClient, campaign_id: str) -> Dict[str, Any]:
    """Read a campaign as its director."""
    return get_success_data(
        client.get_campaign(campaign_id,
                            headers=make_campaign_director_headers()))


def read_legislator(client: AdvocacyClient, legislator_id: str) -> Dict[str, Any]:
    """Read a legislator as the campaign's director."""
    return get_success_data(
        client.get_legislator(legislator_id,
                             headers=make_campaign_director_headers()))


def read_variant(client: AdvocacyClient, variant_id: str) -> Dict[str, Any]:
    """Read a message variant as its strategist."""
    return get_success_data(
        client.get_variant(variant_id,
                           headers=make_message_strategist_headers()))


def read_segment(client: AdvocacyClient, segment_id: str) -> Dict[str, Any]:
    """Read a segment as the campaign's director."""
    return get_success_data(
        client.get_segment(segment_id,
                           headers=make_campaign_director_headers()))


def read_activation(client: AdvocacyClient, activation_id: str) -> Dict[str, Any]:
    """Read a wave as the campaign's director."""
    return get_success_data(
        client.get_activation(activation_id,
                              headers=make_campaign_director_headers()))


def read_action_record(client: AdvocacyClient, record_id: str) -> Dict[str, Any]:
    """Read an action record as the field organizer who files them."""
    return get_success_data(
        client.get_action_record(record_id,
                                headers=make_field_organizer_headers()))


def read_partner(client: AdvocacyClient, partner_id: str) -> Dict[str, Any]:
    """Read a coalition partner as the campaign's director."""
    return get_success_data(
        client.get_partner(partner_id,
                           headers=make_campaign_director_headers()))


def read_endorsement(client: AdvocacyClient, endorsement_id: str) -> Dict[str, Any]:
    """Read a partner endorsement as the campaign's director."""
    return get_success_data(
        client.get_endorsement(endorsement_id,
                              headers=make_campaign_director_headers()))


def read_spokesperson(client: AdvocacyClient, spokesperson_id: str) -> Dict[str, Any]:
    """Read a spokesperson profile as the field organizer who curates it."""
    return get_success_data(
        client.get_spokesperson(spokesperson_id,
                                headers=make_field_organizer_headers()))


def read_meeting(client: AdvocacyClient, meeting_id: str) -> Dict[str, Any]:
    """Read a district meeting as the campaign's director."""
    return get_success_data(
        client.get_meeting(meeting_id,
                           headers=make_campaign_director_headers()))


def read_milestone(client: AdvocacyClient, milestone_id: str) -> Dict[str, Any]:
    """Read a milestone as the campaign's director."""
    return get_success_data(
        client.get_milestone(milestone_id,
                             headers=make_campaign_director_headers()))


def read_outcome_report(client: AdvocacyClient, campaign_id: str) -> Dict[str, Any]:
    """Read a campaign's rolled-up outcome report."""
    return get_success_data(
        client.get_outcome_report(campaign_id,
                                 headers=make_campaign_director_headers()))


# --------------------------------------------------------------------------
# Tier 3: message variant lifecycle shortcuts
# --------------------------------------------------------------------------

def add_variant(client: AdvocacyClient, campaign_id: str,
                **overrides: Any) -> Dict[str, Any]:
    """Draft a message variant."""
    return get_success_data(
        client.create_variant(F.variant_payload(campaign_id, **overrides),
                              headers=make_message_strategist_headers()))


def submit_variant(client: AdvocacyClient, variant_id: str,
                   author_user_id: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """Send a drafted variant into compliance review."""
    headers = (make_message_strategist_headers(author_user_id)
               if author_user_id else make_message_strategist_headers())
    return get_success_data(
        client.submit_variant(variant_id,
                             F.variant_submit_payload(**overrides),
                             headers=headers))


def review_variant(client: AdvocacyClient, variant_id: str,
                   decision: str = REVIEW_DECISION_APPROVE,
                   reviewer_user_id: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """Record a compliance decision on a variant under review."""
    headers = (make_compliance_officer_headers(reviewer_user_id)
               if reviewer_user_id else make_compliance_officer_headers())
    return get_success_data(
        client.review_variant(variant_id,
                             F.review_decision_payload(decision, **overrides),
                             headers=headers))


def create_approved_variant(client: AdvocacyClient, campaign_id: str,
                            **overrides: Any) -> Dict[str, Any]:
    """Draft, submit and approve a variant in one step."""
    variant = add_variant(client, campaign_id, **overrides)
    submit_variant(client, variant["id"])
    return review_variant(client, variant["id"], REVIEW_DECISION_APPROVE)


def endorse_variant(client: AdvocacyClient, partner_id: str, variant_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    """Have one partner's delegate endorse a variant at its current revision.

    The delegate re-reads the variant first so that the endorsement pins the
    revision it actually reviewed.
    """
    seen = get_success_data(
        client.get_variant(variant_id,
                           headers=make_partner_delegate_headers(partner_id)))
    return get_success_data(
        client.create_endorsement(
            F.endorsement_payload(partner_id, variant_id, seen["version"],
                                  **overrides),
            headers=make_partner_delegate_headers(partner_id)))


def lock_variant(client: AdvocacyClient, variant_id: str) -> Dict[str, Any]:
    """Freeze an approved and quorum-backed variant for sending."""
    return get_success_data(
        client.lock_variant(variant_id,
                            headers=make_message_strategist_headers()))


def create_locked_variant(client: AdvocacyClient, campaign_id: str,
                          partner_id: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """Carry a variant all the way to LOCKED, minting a partner if needed.

    Returns ``{"variant", "variant_id", "partner", "partner_id",
    "endorsement", "endorsement_id"}``.
    """
    approved = create_approved_variant(client, campaign_id, **overrides)
    partner = None
    if partner_id is None:
        partner = add_partner(client, campaign_id)
        partner_id = partner["id"]
    endorsement = endorse_variant(client, partner_id, approved["id"])
    locked = lock_variant(client, approved["id"])
    return {
        "variant": locked,
        "variant_id": locked["id"],
        "partner": partner,
        "partner_id": partner_id,
        "endorsement": endorsement,
        "endorsement_id": endorsement["id"],
    }


# --------------------------------------------------------------------------
# Tier 3b: activation lifecycle shortcuts
# --------------------------------------------------------------------------

DEFAULT_WINDOW_START = "2026-08-05T09:00:00Z"
DEFAULT_WINDOW_END = "2026-08-05T17:00:00Z"
DEFAULT_INSIDE_WINDOW = "2026-08-05T10:00:00Z"


def add_activation(client: AdvocacyClient, campaign_id: str, segment_id: str,
                   variant_id: str,
                   window_start: str = DEFAULT_WINDOW_START,
                   window_end: str = DEFAULT_WINDOW_END,
                   channel: str = CHANNEL_EMAIL,
                   min_viable_reach: int = 1,
                   segment_version: Optional[int] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """Schedule a send wave, re-reading the segment to pin its revision."""
    if segment_version is None:
        segment_version = read_segment(client, segment_id)["version"]
    return get_success_data(
        client.create_activation(
            F.activation_payload(campaign_id, segment_id, variant_id,
                                 window_start, window_end, segment_version,
                                 channel=channel,
                                 min_viable_reach=min_viable_reach,
                                 **overrides),
            headers=make_campaign_director_headers()))


def clear_activation(client: AdvocacyClient, activation_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Record compliance clearance on a scheduled wave."""
    return get_success_data(
        client.clear_activation(activation_id,
                               F.activation_clear_payload(**overrides),
                               headers=make_compliance_officer_headers()))


def block_activation(client: AdvocacyClient, activation_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Block a scheduled wave on compliance grounds."""
    return get_success_data(
        client.block_activation(activation_id,
                               F.activation_block_payload(**overrides),
                               headers=make_compliance_officer_headers()))


def start_send(client: AdvocacyClient, activation_id: str) -> Dict[str, Any]:
    """Begin sending a cleared wave. The clock must sit inside its window."""
    return get_success_data(
        client.start_send(activation_id,
                          headers=make_campaign_director_headers()))


def complete_activation(client: AdvocacyClient, activation_id: str,
                        delivered_count: int, bounced_count: int = 0,
                        **overrides: Any) -> Dict[str, Any]:
    """Close out a sending wave with its delivery tallies."""
    return get_success_data(
        client.complete_activation(
            activation_id,
            F.activation_complete_payload(delivered_count, bounced_count,
                                          **overrides),
            headers=make_campaign_director_headers()))


def abort_activation(client: AdvocacyClient, activation_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Abandon a wave before or during sending."""
    return get_success_data(
        client.abort_activation(activation_id,
                               F.activation_abort_payload(**overrides),
                               headers=make_campaign_director_headers()))


def create_cleared_wave(client: AdvocacyClient, campaign_id: str, segment_id: str,
                        variant_id: str, **overrides: Any) -> Dict[str, Any]:
    """Schedule a wave and take it through compliance clearance."""
    activation = add_activation(client, campaign_id, segment_id, variant_id,
                                **overrides)
    clear_activation(client, activation["id"])
    return read_activation(client, activation["id"])


def create_sending_wave(client: AdvocacyClient, campaign_id: str, segment_id: str,
                        variant_id: str,
                        inside_window: str = DEFAULT_INSIDE_WINDOW,
                        **overrides: Any) -> Dict[str, Any]:
    """Take a wave to the point where delivery is under way."""
    activation = add_activation(client, campaign_id, segment_id, variant_id,
                                **overrides)
    clear_activation(client, activation["id"])
    park_clock(client, inside_window)
    return start_send(client, activation["id"])


def create_sent_wave(client: AdvocacyClient, campaign_id: str, segment_id: str,
                     variant_id: str, delivered_count: int,
                     bounced_count: int = 0,
                     inside_window: str = DEFAULT_INSIDE_WINDOW,
                     **overrides: Any) -> Dict[str, Any]:
    """Take a wave all the way through to a completed delivery."""
    sending = create_sending_wave(client, campaign_id, segment_id, variant_id,
                                  inside_window=inside_window, **overrides)
    return complete_activation(client, sending["id"], delivered_count,
                               bounced_count)


# --------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# --------------------------------------------------------------------------

def log_action(client: AdvocacyClient, supporter_id: str,
               channel: str = CHANNEL_EMAIL, **overrides: Any) -> Dict[str, Any]:
    """File one constituent action against a supporter."""
    return get_success_data(
        client.create_action_record(
            F.action_record_payload(supporter_id, channel=channel, **overrides),
            headers=make_field_organizer_headers()))


def log_actions(client: AdvocacyClient, supporter_id: str, count: int,
                channel: str = CHANNEL_EMAIL,
                **overrides: Any) -> List[Dict[str, Any]]:
    """File several actions in succession against one supporter."""
    return [log_action(client, supporter_id, channel=channel, **overrides)
            for _ in range(count)]


def acknowledge_action(client: AdvocacyClient, record_id: str,
                       **overrides: Any) -> Dict[str, Any]:
    """Acknowledge a matched action."""
    return get_success_data(
        client.acknowledge_action(record_id,
                                 F.acknowledge_payload(**overrides),
                                 headers=make_field_organizer_headers()))


def thank_action(client: AdvocacyClient, record_id: str,
                 thank_channel: str = CHANNEL_EMAIL,
                 **overrides: Any) -> Dict[str, Any]:
    """Close the thank-you loop on an acknowledged action."""
    return get_success_data(
        client.thank_action(record_id,
                            F.thank_payload(thank_channel, **overrides),
                            headers=make_field_organizer_headers()))


def acknowledge_and_thank(client: AdvocacyClient, record_id: str,
                          thank_channel: str = CHANNEL_EMAIL) -> Dict[str, Any]:
    """Take one action record through acknowledgement to thanks."""
    acknowledge_action(client, record_id)
    return thank_action(client, record_id, thank_channel)


def dispute_action(client: AdvocacyClient, record_id: str,
                   filer_user_id: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """Raise a dispute against an action record."""
    headers = (make_field_organizer_headers(filer_user_id)
               if filer_user_id else make_field_organizer_headers())
    return get_success_data(
        client.dispute_action(record_id, F.dispute_payload(**overrides),
                             headers=headers))


def resolve_dispute(client: AdvocacyClient, record_id: str, outcome: str,
                    resolver_user_id: Optional[str] = None,
                    **overrides: Any) -> Dict[str, Any]:
    """Settle a disputed action record one way or the other."""
    headers = (make_compliance_officer_headers(resolver_user_id)
               if resolver_user_id else make_compliance_officer_headers())
    return get_success_data(
        client.resolve_dispute(record_id,
                               F.dispute_resolution_payload(outcome, **overrides),
                               headers=headers))


def consume_touches(client: AdvocacyClient, campaign_id: str, segment_id: str,
                    variant_id: str, supporter_count: int, rounds: int,
                    channel: str = CHANNEL_EMAIL) -> List[Dict[str, Any]]:
    """Burn a chosen number of touches per supporter by sending full waves.

    Each round schedules, clears, sends and completes one wave over the whole
    segment, moving one reserved touch per supporter into the consumed column.
    """
    waves = []
    windows = [
        ("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z", "2026-08-05T09:30:00Z"),
        ("2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z", "2026-08-06T09:30:00Z"),
        ("2026-08-07T09:00:00Z", "2026-08-07T10:00:00Z", "2026-08-07T09:30:00Z"),
        ("2026-08-08T09:00:00Z", "2026-08-08T10:00:00Z", "2026-08-08T09:30:00Z"),
        ("2026-08-09T09:00:00Z", "2026-08-09T10:00:00Z", "2026-08-09T09:30:00Z"),
    ]
    for index in range(rounds):
        start, end, inside = windows[index]
        waves.append(create_sent_wave(
            client, campaign_id, segment_id, variant_id,
            delivered_count=supporter_count,
            window_start=start, window_end=end, inside_window=inside,
            channel=channel, min_viable_reach=1))
    return waves


# --------------------------------------------------------------------------
# Tier 4b: spokesperson and meeting readiness
# --------------------------------------------------------------------------

def add_spokesperson(client: AdvocacyClient, supporter_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Open a spokesperson profile over an existing supporter."""
    return get_success_data(
        client.create_spokesperson(
            F.spokesperson_payload(supporter_id, **overrides),
            headers=make_field_organizer_headers()))


def advance_training(client: AdvocacyClient, spokesperson_id: str, to_level: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Advance a spokesperson one rung up the training ladder."""
    return get_success_data(
        client.advance_training(
            spokesperson_id,
            F.training_advancement_payload(to_level, **overrides),
            headers=make_field_organizer_headers()))


def create_certified_spokesperson(client: AdvocacyClient, supporter_id: str,
                                  **overrides: Any) -> Dict[str, Any]:
    """Open a profile with public story consent and certify it.

    Certification requires the story to be publishable, so the profile is
    opened with public publication consent.
    """
    overrides.setdefault("publication_consent", "PUBLIC")
    profile = add_spokesperson(client, supporter_id, **overrides)
    advance_training(client, profile["id"], TRAINING_TRAINED)
    return advance_training(client, profile["id"], TRAINING_CERTIFIED)


def add_meeting(client: AdvocacyClient, campaign_id: str, legislator_id: str,
                spokesperson_id: str, window_start: str, window_end: str,
                **overrides: Any) -> Dict[str, Any]:
    """Request a district meeting led by a certified spokesperson."""
    return get_success_data(
        client.create_meeting(
            F.meeting_payload(campaign_id, legislator_id, spokesperson_id,
                              window_start, window_end, **overrides),
            headers=make_field_organizer_headers()))


def respond_to_meeting(client: AdvocacyClient, meeting_id: str, decision: str,
                       **overrides: Any) -> Dict[str, Any]:
    """Record the legislative office's answer to a meeting request."""
    return get_success_data(
        client.respond_to_meeting(meeting_id,
                                 F.meeting_response_payload(decision, **overrides),
                                 headers=make_campaign_director_headers()))


def complete_meeting(client: AdvocacyClient, meeting_id: str,
                     attendee_count: int, **overrides: Any) -> Dict[str, Any]:
    """Close out a confirmed meeting with its attendance."""
    return get_success_data(
        client.complete_meeting(meeting_id,
                               F.meeting_complete_payload(attendee_count,
                                                          **overrides),
                               headers=make_field_organizer_headers()))


def create_held_meeting(client: AdvocacyClient, campaign_id: str,
                        legislator_id: str, spokesperson_id: str,
                        window_start: str, window_end: str,
                        attendee_count: int = 4,
                        **overrides: Any) -> Dict[str, Any]:
    """Request, confirm and hold a district meeting in one step."""
    meeting = add_meeting(client, campaign_id, legislator_id, spokesperson_id,
                          window_start, window_end, **overrides)
    respond_to_meeting(client, meeting["id"], "CONFIRM")
    return complete_meeting(client, meeting["id"], attendee_count)


# --------------------------------------------------------------------------
# Tier 5: composed worlds
# --------------------------------------------------------------------------

def create_sendable_world(client: AdvocacyClient,
                          supporter_count: int = 1,
                          channels: Optional[List[str]] = None,
                          channel: str = CHANNEL_EMAIL,
                          clock: str = C.CLOCK_DEFAULT_UTC,
                          partner_tiers: Optional[List[str]] = None,
                          legislator_overrides: Optional[Dict[str, Any]] = None,
                          campaign_overrides: Optional[Dict[str, Any]] = None,
                          variant_overrides: Optional[Dict[str, Any]] = None,
                          segment_overrides: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
    """Build an active campaign that is ready to schedule its first wave.

    Produces one legislator, the requested supporters, a segment gated on the
    send channel, one coalition partner per tier named, and a variant carried
    all the way to LOCKED with the first partner's endorsement pinning it.

    Returns a dictionary of the ids and rows the callers need: ``campaign_id``,
    ``legislator_id``, ``supporters``, ``supporter_ids``, ``segment_id``,
    ``variant_id``, ``partners``, ``partner_ids``, ``endorsement_id``.
    """
    channels = [channel] if channels is None else list(channels)
    world = create_active_campaign(
        client, clock=clock,
        legislator_overrides=legislator_overrides,
        **(campaign_overrides or {}))
    campaign_id = world["campaign_id"]

    supporters = add_supporters(client, campaign_id, supporter_count,
                                channels=channels)

    segment = add_segment(client, campaign_id,
                          rule_required_channel=channel,
                          **(segment_overrides or {}))

    partners = add_partners(client, campaign_id,
                            partner_tiers or [PARTNER_TIER_ANCHOR])

    variant_kwargs = dict(variant_overrides or {})
    variant_kwargs.setdefault("channel_scope", [channel])
    locked = create_locked_variant(client, campaign_id,
                                   partner_id=partners[0]["id"],
                                   **variant_kwargs)

    world.update({
        "supporters": supporters,
        "supporter_ids": [s["id"] for s in supporters],
        "segment": segment,
        "segment_id": segment["id"],
        "partners": partners,
        "partner_ids": [p["id"] for p in partners],
        "variant": locked["variant"],
        "variant_id": locked["variant_id"],
        "endorsement": locked["endorsement"],
        "endorsement_id": locked["endorsement_id"],
        "channel": channel,
    })
    return world


def create_blocked_wave_world(client: AdvocacyClient, **overrides: Any
                              ) -> Dict[str, Any]:
    """Build a world holding exactly one blocked wave.

    A single blocked wave is the condition that narrows a campaign's posture
    without freezing it outright.
    """
    world = create_sendable_world(client, **overrides)
    activation = add_activation(client, world["campaign_id"],
                                world["segment_id"], world["variant_id"],
                                channel=world["channel"])
    block_activation(client, activation["id"])
    world["activation"] = read_activation(client, activation["id"])
    world["activation_id"] = activation["id"]
    return world


def create_open_wave_world(client: AdvocacyClient, **overrides: Any
                           ) -> Dict[str, Any]:
    """Build a world holding one scheduled, not yet sent wave."""
    world = create_sendable_world(client, **overrides)
    activation = add_activation(client, world["campaign_id"],
                                world["segment_id"], world["variant_id"],
                                channel=world["channel"],
                                min_viable_reach=1)
    world["activation"] = activation
    world["activation_id"] = activation["id"]
    return world


def create_cleared_wave_world(client: AdvocacyClient, **overrides: Any
                              ) -> Dict[str, Any]:
    """Build a world holding one wave already cleared by compliance."""
    world = create_open_wave_world(client, **overrides)
    clear_activation(client, world["activation_id"])
    world["activation"] = read_activation(client, world["activation_id"])
    assert world["activation"]["approval_state"] == APPROVAL_CLEARED
    return world


def create_action_history_world(client: AdvocacyClient, action_count: int = 1,
                                channel: str = CHANNEL_EMAIL,
                                **overrides: Any) -> Dict[str, Any]:
    """Build an active campaign with a legislator, a supporter and some actions."""
    overrides.setdefault("channels", [channel])
    world = create_active_campaign(
        client, **{k: v for k, v in overrides.items()
                   if k not in ("channels", "supporter_count")})
    supporters = add_supporters(client, world["campaign_id"],
                                overrides.get("supporter_count", 1),
                                channels=overrides["channels"])
    records = []
    for supporter in supporters:
        records.extend(log_actions(client, supporter["id"], action_count,
                                   channel=channel))
    world.update({
        "supporters": supporters,
        "supporter_ids": [s["id"] for s in supporters],
        "records": records,
        "record_ids": [r["id"] for r in records],
    })
    return world
