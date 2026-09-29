"""Payload factories — one per resource, carrying only client-supplied input fields."""

from .constants import TEST_DEFAULTS


def association_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["ASSOCIATION_NAME"],
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
    }
    payload.update(overrides)
    return payload


def member_payload(association_id, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "full_name": "Ana Reyes",
        "email": "ana@example.com",
        "dues_paid_through": TEST_DEFAULTS["FUTURE_DUES_DATE"],
    }
    payload.update(overrides)
    return payload


def contractor_payload(association_id, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "company_name": "NorthPeak Inspections",
        "insurance_expires_on": "2027-01-31",
    }
    payload.update(overrides)
    return payload


def lockbox_payload(association_id, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "serial_number": "LB-0001",
        "model": "LB_PRO",
        "replacement_cost_cents": TEST_DEFAULTS["LB_PRO_COST_CENTS"],
        "in_service_since": TEST_DEFAULTS["IN_SERVICE_SINCE"],
    }
    payload.update(overrides)
    return payload


def listing_payload(association_id, listing_agent_id, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "listing_agent_id": listing_agent_id,
        "address_line": "12 Pine St",
        "mls_number": "MLS-1001",
    }
    payload.update(overrides)
    return payload


def placement_payload(lockbox_id, listing_id, **overrides) -> dict:
    payload = {"lockbox_id": lockbox_id, "listing_id": listing_id}
    payload.update(overrides)
    return payload


def credential_payload(member_id, expected_member_version, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "credential_type": "KEY_APP",
        "expires_at": TEST_DEFAULTS["CREDENTIAL_EXPIRES_AT"],
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def grant_payload(
    listing_id, lockbox_id, expected_listing_version, **overrides
) -> dict:
    payload = {
        "listing_id": listing_id,
        "lockbox_id": lockbox_id,
        "grant_type": "INSPECTOR",
        "window_start": "2026-08-06T14:00:00Z",
        "window_end": "2026-08-06T16:00:00Z",
        "expected_listing_version": expected_listing_version,
    }
    payload.update(overrides)
    return payload


def showing_payload(listing_id, showing_member_id, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "showing_member_id": showing_member_id,
        "window_start": "2026-08-07T10:00:00Z",
        "window_end": "2026-08-07T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def access_attempt_payload(lockbox_id, actor_type="UNKNOWN", **overrides) -> dict:
    payload = {"lockbox_id": lockbox_id, "actor_type": actor_type}
    payload.update(overrides)
    return payload


def incident_review_payload(association_id, window_start, window_end, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload
