"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    BIG_BUDGET_CENTS,
    DEFAULT_EXPECTED_CLOSE_PRICE_CENTS,
)


def team_payload(**overrides) -> dict:
    defaults = {"name": "Alpha", "market": "Austin", "timezone": "America/Chicago"}
    defaults.update(overrides)
    return defaults


def agent_payload(team_id, license_number, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "display_name": "Agent",
        "license_number": license_number,
        "max_active_leads": 5,
    }
    defaults.update(overrides)
    return defaults


def routing_policy_payload(team_id, mode="ROUND_ROBIN", **overrides) -> dict:
    defaults = {"team_id": team_id, "mode": mode}
    defaults.update(overrides)
    return defaults


def lead_source_payload(team_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "name": "Zillow",
        "type": "PORTAL",
        "cost_per_lead_cents": 0,
        "monthly_budget_cents": BIG_BUDGET_CENTS,
    }
    defaults.update(overrides)
    return defaults


def lead_payload(team_id, source_id, contact_phone, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "source_id": source_id,
        "contact_name": "Buyer",
        "contact_phone": contact_phone,
        "contact_email": "buyer@x.com",
        "expected_close_price_cents": DEFAULT_EXPECTED_CLOSE_PRICE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def engagement_event_payload(event_type, occurred_at, **overrides) -> dict:
    defaults = {"type": event_type, "occurred_at": occurred_at}
    defaults.update(overrides)
    return defaults


def nurture_campaign_payload(team_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "name": "Cold Drip",
        "temperature_target": "COLD",
        "steps": [{"offset_days": 1, "channel": "EMAIL"}],
    }
    defaults.update(overrides)
    return defaults


def nurture_enrollment_payload(campaign_id, lead_id, **overrides) -> dict:
    defaults = {"campaign_id": campaign_id, "lead_id": lead_id}
    defaults.update(overrides)
    return defaults


def referral_partner_payload(team_id, **overrides) -> dict:
    defaults = {"team_id": team_id, "name": "Pat", "fee_bps": 2500}
    defaults.update(overrides)
    return defaults


def split_agreement_payload(team_id, agent_a_id, agent_b_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "agent_a_id": agent_a_id,
        "agent_b_id": agent_b_id,
        "a_share_bps": 5000,
        "b_share_bps": 5000,
        "effective_from": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def deal_payload(lead_id, gross_commission_cents, **overrides) -> dict:
    defaults = {"lead_id": lead_id, "gross_commission_cents": gross_commission_cents}
    defaults.update(overrides)
    return defaults


def time_off_payload(starts_at, ends_at, reason="time off", **overrides) -> dict:
    defaults = {"starts_at": starts_at, "ends_at": ends_at, "reason": reason}
    defaults.update(overrides)
    return defaults


def import_stats_payload(**fields) -> dict:
    """Any subset of the backfillable production counters (PRD §3.1)."""
    return dict(fields)
