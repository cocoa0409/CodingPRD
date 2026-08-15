"""Payload factories — one per creatable resource, input fields only.

Field names follow the PRD exactly. Optional fields are omitted unless the
caller supplies them, so server-side defaults stay observable in tests.
"""

from .constants import TEST_DEFAULTS


def create_channel_payload(handle="test_channel", display_name=None,
                           home_platform="TWITCH", **overrides) -> dict:
    defaults = {
        "handle": handle,
        "display_name": display_name or f"{handle} display",
        "home_platform": home_platform,
    }
    defaults.update(overrides)
    return defaults


def payout_settings_payload(expected_channel_version, **overrides) -> dict:
    defaults = {"expected_channel_version": expected_channel_version}
    defaults.update(overrides)
    return defaults


def submit_tax_form_payload(expected_channel_version, form_type="W9",
                            legal_name="Test Creator LLC",
                            tax_id_last4="1234", **overrides) -> dict:
    defaults = {
        "form_type": form_type,
        "legal_name": legal_name,
        "tax_id_last4": tax_id_last4,
        "expected_channel_version": expected_channel_version,
    }
    defaults.update(overrides)
    return defaults


def revenue_event_payload(kind="TIP", gross_cents=100_000, platform_fee_bps=0,
                          occurred_at="2026-08-03T01:00:00Z", **overrides) -> dict:
    defaults = {
        "kind": kind,
        "gross_cents": gross_cents,
        "platform_fee_bps": platform_fee_bps,
        "occurred_at": occurred_at,
    }
    defaults.update(overrides)
    return defaults


def create_tier_payload(tier_code="TIER_1",
                        monthly_price_cents=TEST_DEFAULTS["TIER_PRICE_CENTS"],
                        revenue_share_bps=TEST_DEFAULTS["TIER_REVENUE_SHARE_BPS"],
                        perk_inventory_total=2, **overrides) -> dict:
    defaults = {
        "tier_code": tier_code,
        "monthly_price_cents": monthly_price_cents,
        "revenue_share_bps": revenue_share_bps,
        "perk_inventory_total": perk_inventory_total,
    }
    defaults.update(overrides)
    return defaults


def create_viewer_payload(handle="viewer_one", **overrides) -> dict:
    defaults = {"handle": handle}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(viewer_id, tier_id, **overrides) -> dict:
    defaults = {"viewer_id": viewer_id, "tier_id": tier_id}
    defaults.update(overrides)
    return defaults


def create_moderator_payload(moderator_handle="mod_one", scopes=None,
                             **overrides) -> dict:
    defaults = {
        "moderator_handle": moderator_handle,
        "scopes": scopes if scopes is not None else ["TIMEOUT"],
    }
    defaults.update(overrides)
    return defaults


def moderation_action_payload(viewer_id, action_kind="TIMEOUT", reason="violation",
                              duration_minutes=None, **overrides) -> dict:
    defaults = {
        "viewer_id": viewer_id,
        "action_kind": action_kind,
        "reason": reason,
    }
    if duration_minutes is not None:
        defaults["duration_minutes"] = duration_minutes
    defaults.update(overrides)
    return defaults


def create_strike_payload(policy_code="COPYRIGHT", severity="MINOR",
                          evidence_ref="clip://evidence", **overrides) -> dict:
    defaults = {
        "policy_code": policy_code,
        "severity": severity,
        "evidence_ref": evidence_ref,
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(sponsor_ref, title="Sponsorship", category="OTHER",
                        total_value_cents=TEST_DEFAULTS["DEAL_VALUE_CENTS"],
                        flight_start=TEST_DEFAULTS["DEAL_FLIGHT_START"],
                        flight_end=TEST_DEFAULTS["DEAL_FLIGHT_END"],
                        required_deliverable_count=1, **overrides) -> dict:
    defaults = {
        "sponsor_ref": sponsor_ref,
        "title": title,
        "category": category,
        "total_value_cents": total_value_cents,
        "flight_start": flight_start,
        "flight_end": flight_end,
        "required_deliverable_count": required_deliverable_count,
    }
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(kind="AD_READ", due_at="2026-08-20T00:00:00Z",
                               stream_id=None, **overrides) -> dict:
    defaults = {"kind": kind, "due_at": due_at}
    if stream_id is not None:
        defaults["stream_id"] = stream_id
    defaults.update(overrides)
    return defaults


def create_stream_payload(title="Stream",
                          scheduled_start="2026-08-10T10:00:00Z",
                          scheduled_end="2026-08-10T11:00:00Z",
                          simulcast=None, **overrides) -> dict:
    defaults = {
        "title": title,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if simulcast is not None:
        defaults["simulcast"] = simulcast
    defaults.update(overrides)
    return defaults


def create_simulcast_grant_payload(platform="KICK",
                                   window_start="2026-08-01T00:00:00Z",
                                   window_end="2026-08-31T00:00:00Z",
                                   exclusive=None, **overrides) -> dict:
    defaults = {
        "platform": platform,
        "window_start": window_start,
        "window_end": window_end,
    }
    if exclusive is not None:
        defaults["exclusive"] = exclusive
    defaults.update(overrides)
    return defaults
