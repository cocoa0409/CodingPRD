"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Creator calls are entity-backed by Channel, Moderator
calls by Moderator, and Sponsor-privileged calls carry X-User-ID equal to the
deal's sponsor_ref. Every helper builds per-instance headers from the real
entity ids via the make_* builders; ownership-gated calls never fall back to
the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    APPEALS_OFFICER_ID,
    SEPTEMBER_CLOCK_ISO,
    SPONSOR_ACME_ID,
    TEST_DEFAULTS,
    TRUST_AGENT_ISSUER_ID,
)
from .factories import (
    create_channel_payload,
    create_deal_payload,
    create_deliverable_payload,
    create_moderator_payload,
    create_simulcast_grant_payload,
    create_stream_payload,
    create_strike_payload,
    create_subscription_payload,
    create_tier_payload,
    create_viewer_payload,
    moderation_action_payload,
    revenue_event_payload,
    submit_tax_form_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeals_officer_headers,
    make_creator_headers,
    make_moderator_headers,
    make_sponsor_headers,
    make_trust_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_agent_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and ops checkpoint
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Move the logical clock. Returns the reported current_utc payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_ops():
    """Advance the ops checkpoint. Returns the run summary payload."""
    return get_success_data(api_client.ops_run(ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and transitions
# ---------------------------------------------------------------------------

def create_channel(handle="test_channel", home_platform="TWITCH",
                   payout_schedule=None, payout_threshold_cents=None,
                   display_name=None):
    """Onboard a channel (born RESTRICTED, version 1). Returns the channel."""
    payload = create_channel_payload(handle=handle, display_name=display_name,
                                     home_platform=home_platform)
    if payout_schedule is not None:
        payload["payout_schedule"] = payout_schedule
    if payout_threshold_cents is not None:
        payload["payout_threshold_cents"] = payout_threshold_cents
    return get_success_data(api_client.create_channel(payload, ADMIN))


def get_channel(channel_id):
    return get_success_data(api_client.get_channel(channel_id, ADMIN))


def submit_tax_form(channel, form_type="W9", legal_name="Test Creator LLC",
                    tax_id_last4="1234"):
    """Submit a tax form as the channel's owner, threading the channel's
    current version for the OCC guard. Returns the new (SUBMITTED) form."""
    payload = submit_tax_form_payload(channel["version"], form_type=form_type,
                                      legal_name=legal_name,
                                      tax_id_last4=tax_id_last4)
    return get_success_data(
        api_client.submit_tax_form(channel["id"], payload,
                                   make_creator_headers(channel["id"])))


def verify_tax_form(tax_form_id, agent_headers=None):
    return get_success_data(api_client.transition_tax_form(
        tax_form_id, {"action": "VERIFY"}, agent_headers or TRUST))


def reject_tax_form(tax_form_id, rejection_reason="illegible", agent_headers=None):
    return get_success_data(api_client.transition_tax_form(
        tax_form_id, {"action": "REJECT", "rejection_reason": rejection_reason},
        agent_headers or TRUST))


def ingest_revenue_event(channel_id, kind="TIP", gross_cents=100_000,
                         platform_fee_bps=0, occurred_at="2026-08-03T01:00:00Z",
                         reverses_event_id=None):
    """Ingest a revenue event platform-side. Returns the event."""
    payload = revenue_event_payload(kind=kind, gross_cents=gross_cents,
                                    platform_fee_bps=platform_fee_bps,
                                    occurred_at=occurred_at)
    if reverses_event_id is not None:
        payload["reverses_event_id"] = reverses_event_id
    return get_success_data(api_client.ingest_revenue_event(channel_id, payload, ADMIN))


def get_revenue_event(event_id):
    return get_success_data(api_client.get_revenue_event(event_id, ADMIN))


def list_revenue_events(params=None):
    return get_success_data(api_client.list_revenue_events(ADMIN, params=params))


def create_tier(channel_id, tier_code="TIER_1",
                monthly_price_cents=TEST_DEFAULTS["TIER_PRICE_CENTS"],
                revenue_share_bps=TEST_DEFAULTS["TIER_REVENUE_SHARE_BPS"],
                perk_inventory_total=2):
    return get_success_data(api_client.create_tier(
        channel_id,
        create_tier_payload(tier_code=tier_code,
                            monthly_price_cents=monthly_price_cents,
                            revenue_share_bps=revenue_share_bps,
                            perk_inventory_total=perk_inventory_total),
        make_creator_headers(channel_id)))


def create_viewer(channel_id, handle="viewer_one"):
    return get_success_data(api_client.create_viewer(
        channel_id, create_viewer_payload(handle=handle), ADMIN))


def create_subscription(channel_id, viewer_id, tier_id):
    return get_success_data(api_client.create_subscription(
        channel_id, create_subscription_payload(viewer_id, tier_id), ADMIN))


def list_perk_grants(subscription_id, channel_id):
    data, _meta = validate_paginated(api_client.list_perk_grants(
        subscription_id, make_creator_headers(channel_id)))
    return data


def create_moderator(channel_id, moderator_handle="mod_one", scopes=None):
    return get_success_data(api_client.create_moderator(
        channel_id,
        create_moderator_payload(moderator_handle=moderator_handle, scopes=scopes),
        make_creator_headers(channel_id)))


def accept_moderator(moderator_id):
    """The invitee accepts their own invite (self-identity checked)."""
    return get_success_data(api_client.transition_moderator(
        moderator_id, {"action": "ACCEPT"}, make_moderator_headers(moderator_id)))


def issue_moderation_action(channel_id, viewer_id, action_kind="TIMEOUT",
                            duration_minutes=600, reason="violation",
                            headers=None):
    """Issue an enforcement action; defaults to the channel owner as issuer."""
    payload = moderation_action_payload(viewer_id, action_kind=action_kind,
                                        reason=reason,
                                        duration_minutes=duration_minutes)
    return get_success_data(api_client.create_moderation_action(
        channel_id, payload, headers or make_creator_headers(channel_id)))


def issue_strike(channel_id, policy_code="COPYRIGHT", severity="MINOR",
                 evidence_ref="clip://evidence", issuer_user_id=TRUST_AGENT_ISSUER_ID):
    """Issue a content strike as a TrustAgent. Returns the strike."""
    return get_success_data(api_client.create_strike(
        channel_id,
        create_strike_payload(policy_code=policy_code, severity=severity,
                              evidence_ref=evidence_ref),
        make_trust_agent_headers(issuer_user_id)))


def appeal_strike(strike_id, channel_id, statement="appeal"):
    return get_success_data(api_client.appeal_strike(
        strike_id, {"statement": statement}, make_creator_headers(channel_id)))


def resolve_strike(strike_id, outcome="UPHELD", resolution_note="reviewed",
                   officer_user_id=APPEALS_OFFICER_ID):
    return get_success_data(api_client.resolve_strike_appeal(
        strike_id, {"outcome": outcome, "resolution_note": resolution_note},
        make_appeals_officer_headers(officer_user_id)))


def create_deal(channel_id, sponsor_ref=SPONSOR_ACME_ID, title="Sponsorship",
                category="OTHER",
                total_value_cents=TEST_DEFAULTS["DEAL_VALUE_CENTS"],
                flight_start=TEST_DEFAULTS["DEAL_FLIGHT_START"],
                flight_end=TEST_DEFAULTS["DEAL_FLIGHT_END"],
                required_deliverable_count=1):
    return get_success_data(api_client.create_deal(
        channel_id,
        create_deal_payload(sponsor_ref=sponsor_ref, title=title, category=category,
                            total_value_cents=total_value_cents,
                            flight_start=flight_start, flight_end=flight_end,
                            required_deliverable_count=required_deliverable_count),
        make_creator_headers(channel_id)))


def transition_deal(deal_id, action, headers):
    return get_success_data(
        api_client.transition_deal(deal_id, {"action": action}, headers))


def create_deliverable(deal_id, channel_id, kind="AD_READ",
                       due_at="2026-08-20T00:00:00Z", stream_id=None):
    return get_success_data(api_client.create_deliverable(
        deal_id,
        create_deliverable_payload(kind=kind, due_at=due_at, stream_id=stream_id),
        make_creator_headers(channel_id)))


def create_stream(channel_id, title="Stream",
                  scheduled_start="2026-08-10T10:00:00Z",
                  scheduled_end="2026-08-10T11:00:00Z", simulcast=None):
    return get_success_data(api_client.create_stream(
        channel_id,
        create_stream_payload(title=title, scheduled_start=scheduled_start,
                              scheduled_end=scheduled_end, simulcast=simulcast),
        make_creator_headers(channel_id)))


def start_stream(stream_id, channel_id):
    return get_success_data(api_client.transition_stream(
        stream_id, {"action": "START"}, make_creator_headers(channel_id)))


def end_stream(stream_id, channel_id, peak_viewers=100, avg_viewers=90):
    return get_success_data(api_client.transition_stream(
        stream_id, {"action": "END", "peak_viewers": peak_viewers,
                    "avg_viewers": avg_viewers},
        make_creator_headers(channel_id)))


def create_simulcast_grant(channel_id, platform="KICK",
                           window_start="2026-08-01T00:00:00Z",
                           window_end="2026-08-31T00:00:00Z", exclusive=None):
    return get_success_data(api_client.create_simulcast_grant(
        channel_id,
        create_simulcast_grant_payload(platform=platform,
                                       window_start=window_start,
                                       window_end=window_end, exclusive=exclusive),
        make_creator_headers(channel_id)))


def approve_grant(grant_id):
    return get_success_data(api_client.transition_simulcast_grant(
        grant_id, {"action": "APPROVE"}, ADMIN))


def open_payout(channel_id):
    """Open a payout as the channel owner. Returns the SCHEDULED payout."""
    return get_success_data(
        api_client.open_payout(channel_id, make_creator_headers(channel_id)))


def transition_payout_admin(payout_id, action, failure_reason=None):
    payload = {"action": action}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    return get_success_data(api_client.transition_payout(payout_id, payload, ADMIN))


def transition_payout_owner(payout_id, channel_id, action):
    return get_success_data(api_client.transition_payout(
        payout_id, {"action": action}, make_creator_headers(channel_id)))


# ---------------------------------------------------------------------------
# Tier 2: channel composites (verified tax form, cleared balances)
# ---------------------------------------------------------------------------

def create_verified_channel(handle="verified_channel", form_type="W9",
                            home_platform="TWITCH", payout_threshold_cents=None,
                            legal_name="Verified LLC", tax_id_last4="1234"):
    """Channel + tax form VERIFIED by a TrustAgent. Posture STANDARD (no
    strikes). Returns (channel refetched, tax_form)."""
    channel = create_channel(handle=handle, home_platform=home_platform,
                             payout_threshold_cents=payout_threshold_cents)
    form = submit_tax_form(channel, form_type=form_type, legal_name=legal_name,
                           tax_id_last4=tax_id_last4)
    verify_tax_form(form["id"])
    return get_channel(channel["id"]), form


def setup_channel_with_cleared_events(handle, events, form_type="W9",
                                      payout_threshold_cents=None,
                                      ingest_clock="2026-08-03T00:00:00Z",
                                      settle_clock=SEPTEMBER_CLOCK_ISO):
    """Verified channel whose given August events are ingested and then settled
    to CLEARED by an ops run at the next month boundary.

    events: list of dicts accepted by ingest_revenue_event (kind, gross_cents,
    platform_fee_bps, occurred_at).
    Returns (channel refetched, tax_form, list of created revenue events).
    """
    channel, form = create_verified_channel(
        handle, form_type=form_type,
        payout_threshold_cents=payout_threshold_cents)
    set_clock(ingest_clock)
    created = [ingest_revenue_event(channel["id"], **event) for event in events]
    set_clock(settle_clock)
    run_ops()
    return get_channel(channel["id"]), form, created


def setup_channel_with_open_payout(handle, gross_cents=100_000, platform_fee_bps=0,
                                   form_type="W9", payout_threshold_cents=None):
    """Verified channel with one cleared TIP and an open (SCHEDULED) payout.
    Returns (channel refetched, payout)."""
    channel, _form, _events = setup_channel_with_cleared_events(
        handle,
        [{"kind": "TIP", "gross_cents": gross_cents,
          "platform_fee_bps": platform_fee_bps,
          "occurred_at": "2026-08-03T01:00:00Z"}],
        form_type=form_type, payout_threshold_cents=payout_threshold_cents)
    payout = open_payout(channel["id"])
    return get_channel(channel["id"]), payout


# ---------------------------------------------------------------------------
# Tier 3: deal / deliverable / stream lifecycles
# ---------------------------------------------------------------------------

def setup_active_deal(channel, sponsor_ref=SPONSOR_ACME_ID, category="OTHER",
                      total_value_cents=TEST_DEFAULTS["DEAL_VALUE_CENTS"],
                      flight_start=TEST_DEFAULTS["DEAL_FLIGHT_START"],
                      flight_end=TEST_DEFAULTS["DEAL_FLIGHT_END"],
                      required_deliverable_count=1, title="Sponsorship"):
    """DRAFT -> PROPOSED -> ACCEPTED -> ACTIVE. Sets the logical clock to
    flight_start before activation (activation requires the clock inside the
    closed flight interval). Returns the ACTIVE deal."""
    deal = create_deal(channel["id"], sponsor_ref=sponsor_ref, title=title,
                       category=category, total_value_cents=total_value_cents,
                       flight_start=flight_start, flight_end=flight_end,
                       required_deliverable_count=required_deliverable_count)
    transition_deal(deal["id"], "PROPOSE", make_creator_headers(channel["id"]))
    transition_deal(deal["id"], "ACCEPT", make_sponsor_headers(sponsor_ref))
    set_clock(flight_start)
    transition_deal(deal["id"], "ACTIVATE", make_creator_headers(channel["id"]))
    return get_success_data(api_client.get_deal(deal["id"], ADMIN))


def create_ended_stream(channel_id, title="Stream",
                        scheduled_start="2026-08-15T10:00:00Z",
                        scheduled_end="2026-08-15T11:00:00Z",
                        peak_viewers=100, avg_viewers=90, simulcast=None):
    """Schedule a stream, START it at its scheduled start, END it at its
    scheduled end. Returns the ENDED stream."""
    stream = create_stream(channel_id, title=title,
                           scheduled_start=scheduled_start,
                           scheduled_end=scheduled_end, simulcast=simulcast)
    set_clock(scheduled_start)
    start_stream(stream["id"], channel_id)
    set_clock(scheduled_end)
    end_stream(stream["id"], channel_id, peak_viewers=peak_viewers,
               avg_viewers=avg_viewers)
    return get_success_data(api_client.get_stream(stream["id"], ADMIN))


def setup_deal_with_deliverable(channel, sponsor_ref=SPONSOR_ACME_ID,
                                kind="AD_READ", due_at="2026-08-20T00:00:00Z",
                                **deal_overrides):
    """ACTIVE deal plus one SCHEDULED deliverable. Returns (deal, deliverable)."""
    deal = setup_active_deal(channel, sponsor_ref=sponsor_ref, **deal_overrides)
    deliverable = create_deliverable(deal["id"], channel["id"], kind=kind,
                                     due_at=due_at)
    return deal, deliverable


# ---------------------------------------------------------------------------
# Tier 4: subscription / perk and moderation composites
# ---------------------------------------------------------------------------

def setup_subscription_with_perk(channel_id, tier_code="TIER_1",
                                 monthly_price_cents=TEST_DEFAULTS["TIER_PRICE_CENTS"],
                                 revenue_share_bps=TEST_DEFAULTS["TIER_REVENUE_SHARE_BPS"],
                                 perk_inventory_total=2, viewer_handle="viewer_one"):
    """Tier + viewer + ACTIVE subscription with its cycle-1 PENDING MERCH grant.
    Returns (tier, viewer, subscription, perk_grant)."""
    tier = create_tier(channel_id, tier_code=tier_code,
                       monthly_price_cents=monthly_price_cents,
                       revenue_share_bps=revenue_share_bps,
                       perk_inventory_total=perk_inventory_total)
    viewer = create_viewer(channel_id, handle=viewer_handle)
    subscription = create_subscription(channel_id, viewer["id"], tier["id"])
    grants = list_perk_grants(subscription["id"], channel_id)
    assert len(grants) == 1, f"expected the cycle-1 MERCH grant, got {grants!r}"
    return tier, viewer, subscription, grants[0]


def create_active_moderator(channel_id, moderator_handle="mod_one",
                            scopes=None):
    """Invite + self-accept. Returns the ACTIVE moderator."""
    moderator = create_moderator(channel_id, moderator_handle=moderator_handle,
                                 scopes=scopes)
    return accept_moderator(moderator["id"])
