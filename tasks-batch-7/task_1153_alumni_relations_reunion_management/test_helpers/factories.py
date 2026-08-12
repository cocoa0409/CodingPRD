"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "FULL_NAME": "Test Alumnus",
    "CLASS_YEAR": 2001,
    "DEGREE_CODE": "BA",
    "EVENT_TITLE": "Class of 2001 25th Reunion",
    "EVENT_DATE": "2026-09-01T18:00:00Z",
    "QUORUM": 1,
    "COMMITTEE_NAME": "Reunion Committee",
    "TIER_NAME": "Standard",
    "BASE_PRICE_CENTS": 1000,
    "TIER_CAPACITY": 0,
    "SALES_START": "2026-05-01T00:00:00Z",
    "SALES_END": "2026-09-01T00:00:00Z",
    "EARLY_BIRD_PCT": 0,
    "GROUP_NAME": "Regional Chapter",
    "GROUP_KIND": "REGIONAL_CHAPTER",
    "ANNUAL_BUDGET_CENTS": 100000,
    "PROGRAM_TITLE": "Chapter Mixer",
    "VENUE_START": "2026-06-15T18:00:00Z",
    "VENUE_END": "2026-06-15T20:00:00Z",
    "BUDGET_ALLOCATED_CENTS": 10000,
    "CAMPAIGN_NAME": "Reunion Fund",
    "GOAL_CENTS": 100000,
    "MATCHING_BPS": 0,
    "LEAD_SOURCE": "SOCIAL_MEDIA",
    "LEAD_DETAIL": "Possible social profile",
    "LEAD_CONFIDENCE": 80,
    "PUBLICATION_TITLE": "Memory Book",
    "CLASS_NOTES_BODY": "Class notes...",
}

_email_counter = [0]


def _unique_email(prefix: str = "alum") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_record_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "primary_email": _unique_email(),
        "class_year": DEFAULTS["CLASS_YEAR"],
        "degree_code": DEFAULTS["DEGREE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_research_case_payload(alumni_id: str, **overrides) -> dict:
    defaults = {
        "alumni_id": alumni_id,
        "lead_source": DEFAULTS["LEAD_SOURCE"],
        "lead_detail": DEFAULTS["LEAD_DETAIL"],
        "lead_confidence": DEFAULTS["LEAD_CONFIDENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_log_lead_payload(**overrides) -> dict:
    defaults = {
        "lead_source": DEFAULTS["LEAD_SOURCE"],
        "lead_detail": DEFAULTS["LEAD_DETAIL"],
        "lead_confidence": DEFAULTS["LEAD_CONFIDENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "class_year": DEFAULTS["CLASS_YEAR"],
        "title": DEFAULTS["EVENT_TITLE"],
        "event_date": DEFAULTS["EVENT_DATE"],
        "committee_quorum_required": DEFAULTS["QUORUM"],
    }
    defaults.update(overrides)
    return defaults


def create_committee_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["COMMITTEE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_membership_payload(alumni_id: str, role: str = "MEMBER", **overrides) -> dict:
    defaults = {"alumni_id": alumni_id, "role": role}
    defaults.update(overrides)
    return defaults


def create_ticket_tier_payload(expected_event_version, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TIER_NAME"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "capacity": DEFAULTS["TIER_CAPACITY"],
        "sales_start": DEFAULTS["SALES_START"],
        "sales_end": DEFAULTS["SALES_END"],
        "early_bird_discount_pct": DEFAULTS["EARLY_BIRD_PCT"],
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(tier_id: str, alumni_id: str, **overrides) -> dict:
    defaults = {"tier_id": tier_id, "alumni_id": alumni_id}
    defaults.update(overrides)
    return defaults


def create_group_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GROUP_NAME"],
        "kind": DEFAULTS["GROUP_KIND"],
        "annual_budget_cents": DEFAULTS["ANNUAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(leader_id: str, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PROGRAM_TITLE"],
        "venue_slot_start": DEFAULTS["VENUE_START"],
        "venue_slot_end": DEFAULTS["VENUE_END"],
        "budget_allocated_cents": DEFAULTS["BUDGET_ALLOCATED_CENTS"],
        "leader_id": leader_id,
    }
    defaults.update(overrides)
    return defaults


def create_preference_payload(channel: str = "EMAIL", **overrides) -> dict:
    defaults = {"channel": channel, "opt_in": True}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPAIGN_NAME"],
        "goal_cents": DEFAULTS["GOAL_CENTS"],
        "matching_multiplier_bps": DEFAULTS["MATCHING_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(alumni_id: str, amount_cents: int = 5000, **overrides) -> dict:
    defaults = {"alumni_id": alumni_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_publication_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PUBLICATION_TITLE"],
        "class_notes_body": DEFAULTS["CLASS_NOTES_BODY"],
    }
    defaults.update(overrides)
    return defaults
