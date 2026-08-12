"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq_email(prefix="user"):
    return f"{prefix}{next(_counter)}@example.com"


DEFAULTS = {
    "GROUP_NAME": "Test Neighborhood Group",
    "ZIP_CODE": "98101",
    "POST_TITLE": "Test Item",
    "POST_CATEGORY": "OTHER",
    "CLAIM_MODE": "FIRST_COME",
    "POST_EXPIRES_AT": "2026-06-10T00:00:00Z",
    "ZONE": "MAPLE",
    "KEYWORD": "chair",
    "REPORT_CATEGORY": "SPAM",
    "TARGET_TYPE": "MEMBER",
}


def create_member_payload(**overrides) -> dict:
    defaults = {"email": _uniq_email(), "display_name": "Test Member"}
    defaults.update(overrides)
    return defaults


def create_group_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GROUP_NAME"],
        "zip_code": DEFAULTS["ZIP_CODE"],
        "join_policy": "OPEN",
        "capacity": 150,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(group_id: str, **overrides) -> dict:
    defaults = {"group_id": group_id}
    defaults.update(overrides)
    return defaults


def create_gift_post_payload(group_id: str, **overrides) -> dict:
    defaults = {
        "group_id": group_id,
        "title": DEFAULTS["POST_TITLE"],
        "category": DEFAULTS["POST_CATEGORY"],
        "claim_mode": DEFAULTS["CLAIM_MODE"],
        "expires_at": DEFAULTS["POST_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(post_id: str, **overrides) -> dict:
    defaults = {"post_id": post_id}
    defaults.update(overrides)
    return defaults


def create_pickup_plan_payload(
    claim_id: str,
    window_start: str = "2026-05-11T10:00:00Z",
    window_end: str = "2026-05-11T11:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "claim_id": claim_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_wishlist_payload(group_id: str, **overrides) -> dict:
    defaults = {"group_id": group_id, "keyword": DEFAULTS["KEYWORD"]}
    defaults.update(overrides)
    return defaults


def create_curb_alert_payload(group_id: str, **overrides) -> dict:
    defaults = {
        "group_id": group_id,
        "zone": DEFAULTS["ZONE"],
        "starts_at": "2026-05-12T09:00:00Z",
        "ends_at": "2026-05-12T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(group_id: str, target_id: str, **overrides) -> dict:
    defaults = {
        "group_id": group_id,
        "target_type": DEFAULTS["TARGET_TYPE"],
        "target_id": target_id,
        "category": DEFAULTS["REPORT_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def resolve_report_action_payload(**overrides) -> dict:
    defaults = {"resolution": "ACTION", "action_type": "STRIKE", "severity_points": 1}
    defaults.update(overrides)
    return defaults
