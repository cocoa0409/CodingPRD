"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "JURISDICTION": "US-CA-12",
    "CATEGORY": "OTHER",
    "GOAL": 10,
    "CAMPAIGN_GOAL_CENTS": 100000,
}

_email_counter = [0]


def unique_email(prefix: str = "user") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_user_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test User",
        "jurisdiction": DEFAULTS["JURISDICTION"],
    }
    defaults.update(overrides)
    return defaults


def create_petition_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Petition",
        "summary": "A short summary",
        "body": "The full petition body text.",
        "category": DEFAULTS["CATEGORY"],
        "goal": DEFAULTS["GOAL"],
    }
    defaults.update(overrides)
    return defaults


def set_target_payload(expected_petition_version, **overrides) -> dict:
    defaults = {
        "name": "Decision Maker",
        "title": "Office Title",
        "office": "Governing Body",
        "expected_petition_version": expected_petition_version,
    }
    defaults.update(overrides)
    return defaults


def edit_petition_payload(expected_petition_version, **overrides) -> dict:
    defaults = {"expected_petition_version": expected_petition_version}
    defaults.update(overrides)
    return defaults


def create_representative_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Jane Official",
        "office": "Assembly",
        "jurisdiction": DEFAULTS["JURISDICTION"],
        "contact_email": "jane@gov.example",
    }
    defaults.update(overrides)
    return defaults


def sign_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_comment_payload(**overrides) -> dict:
    defaults = {"body": "A comment body"}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {"goal_cents": DEFAULTS["CAMPAIGN_GOAL_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_donation_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_promotion_payload(petition_id, placement_tier, window_start, window_end, **overrides) -> dict:
    defaults = {
        "petition_id": petition_id,
        "placement_tier": placement_tier,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_meeting_payload(petition_id, target_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "petition_id": petition_id,
        "target_id": target_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults
