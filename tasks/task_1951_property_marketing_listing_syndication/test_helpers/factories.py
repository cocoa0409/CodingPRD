"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_license_counter = itertools.count(1)
_portal_counter = itertools.count(1)


def create_agent_payload(**overrides) -> dict:
    n = next(_license_counter)
    defaults = {
        "full_name": "Ann Agent",
        "license_number": f"LIC-{n}",
        "email": f"agent{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(agent_id, complete=True, **overrides) -> dict:
    """Required intake fields per PRD §3.1; `complete=True` also fills the five
    fields that are optional at intake but required before submit-review."""
    defaults = {
        "agent_id": agent_id,
        "address_line1": "1 Main St",
        "city": "Austin",
        "state_code": "TX",
        "postal_code": "78701",
        "property_type": "CONDO",
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "listing_expires_on": TEST_DEFAULTS["LISTING_EXPIRES_ON"],
    }
    if complete:
        defaults.update({
            "bedrooms": 2,
            "bathrooms": 2,
            "square_feet": 1200,
            "marketing_remarks": "Bright corner unit",
            "mls_number": "MLS-1",
        })
    defaults.update(overrides)
    return defaults


def create_media_asset_payload(kind="PHOTO", **overrides) -> dict:
    defaults = {
        "kind": kind,
        "file_url": "https://cdn.example.com/x.jpg",
        "file_bytes": TEST_DEFAULTS["PHOTO_FILE_BYTES"],
    }
    if kind == "PHOTO":
        defaults.update({
            "width_px": TEST_DEFAULTS["PHOTO_WIDTH_PX"],
            "height_px": TEST_DEFAULTS["PHOTO_HEIGHT_PX"],
        })
    defaults.update(overrides)
    return defaults


def create_portal_account_payload(**overrides) -> dict:
    n = next(_portal_counter)
    payload = {"portal_name": f"Portal-{n}"}
    # Optional tuning fields are sent only when given a concrete value,
    # so server-side defaults (PRD §3.5) remain observable.
    for key in ("sla_seconds", "discount_pct", "rounding_increment_cents"):
        value = overrides.pop(key, None)
        if value is not None:
            payload[key] = value
    payload.update(overrides)
    return payload


def create_blackout_window_payload(starts_at, ends_at, reason=None, **overrides) -> dict:
    payload = {"starts_at": starts_at, "ends_at": ends_at}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_feed_subscription_payload(portal_account_id, **overrides) -> dict:
    payload = {"portal_account_id": portal_account_id}
    payload.update(overrides)
    return payload


def create_decision_payload(outcome, flagged_terms=None, notes=None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if flagged_terms is not None:
        payload["flagged_terms"] = flagged_terms
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def create_patch_listing_payload(expected_listing_version, **fields) -> dict:
    payload = {"expected_listing_version": expected_listing_version}
    payload.update(fields)
    return payload


def create_price_change_payload(new_price_cents, expected_listing_version,
                                change_reason=None, **overrides) -> dict:
    payload = {
        "new_price_cents": new_price_cents,
        "expected_listing_version": expected_listing_version,
    }
    if change_reason is not None:
        payload["change_reason"] = change_reason
    payload.update(overrides)
    return payload


def create_showing_window_payload(starts_at, ends_at, **overrides) -> dict:
    payload = {"starts_at": starts_at, "ends_at": ends_at}
    payload.update(overrides)
    return payload


def create_feedback_payload(rating, comment=None, **overrides) -> dict:
    payload = {"rating": rating}
    if comment is not None:
        payload["comment"] = comment
    payload.update(overrides)
    return payload


def create_relist_payload(new_list_price_cents=None, new_marketing_remarks=None,
                          **overrides) -> dict:
    payload = {}
    if new_list_price_cents is not None:
        payload["new_list_price_cents"] = new_list_price_cents
    if new_marketing_remarks is not None:
        payload["new_marketing_remarks"] = new_marketing_remarks
    payload.update(overrides)
    return payload
