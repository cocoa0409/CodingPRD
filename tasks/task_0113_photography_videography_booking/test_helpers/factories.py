"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional input fields (those carrying a PRD default —
SessionPackage.requires_model_release / .active, Contract.includes_model_release)
are omitted unless explicitly overridden.
"""
import itertools

_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    """Each test runs against an empty DB, but within one test we may register
    several participants; this keeps emails distinct under the uniqueness rule."""
    return f"{prefix}{next(_counter)}@studio.test"


def create_client_payload(**overrides) -> dict:
    """Required: email, full_name, phone."""
    payload = {
        "email": _unique_email("client"),
        "full_name": "Test Client",
        "phone": "555-0100",
    }
    payload.update(overrides)
    return payload


def create_photographer_payload(**overrides) -> dict:
    """Required: email, full_name, skills (non-empty), hourly_rate_cents (>= 0)."""
    payload = {
        "email": _unique_email("photog"),
        "full_name": "Test Photographer",
        "skills": ["PHOTO"],
        "hourly_rate_cents": 7000,
    }
    payload.update(overrides)
    return payload


def create_session_package_payload(**overrides) -> dict:
    """Required: name, session_type, tier, base_fee_cents (> 0),
    included_shoot_hours (> 0), overage_hourly_rate_cents (>= 0),
    included_edited_images (>= 0), deposit_pct (0 < x <= 1).
    Optional (PRD defaults): requires_model_release (false), active (true)."""
    payload = {
        "name": "Portrait Basic",
        "session_type": "PORTRAIT",
        "tier": "BASIC",
        "base_fee_cents": 100000,
        "included_shoot_hours": 2,
        "overage_hourly_rate_cents": 12000,
        "included_edited_images": 30,
        "deposit_pct": 0.30,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(client_id, package_id, lead_photographer_id,
                           requested_shoot_hours=2, **overrides) -> dict:
    """Required: client_id, package_id, lead_photographer_id, requested_shoot_hours (> 0)."""
    payload = {
        "client_id": client_id,
        "package_id": package_id,
        "lead_photographer_id": lead_photographer_id,
        "requested_shoot_hours": requested_shoot_hours,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(booking_id, kind, amount_cents, **overrides) -> dict:
    """Required: booking_id, kind (DEPOSIT/BALANCE/REFUND), amount_cents (> 0)."""
    payload = {
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(booking_id, **overrides) -> dict:
    """Required: booking_id. Optional (PRD default false): includes_model_release."""
    payload = {"booking_id": booking_id}
    payload.update(overrides)
    return payload


def create_shoot_schedule_payload(booking_id, start_utc, end_utc, **overrides) -> dict:
    """Required: booking_id, start_utc, end_utc (end > start)."""
    payload = {
        "booking_id": booking_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    payload.update(overrides)
    return payload


def reschedule_payload(new_start_utc, new_end_utc, reason, **overrides) -> dict:
    """Required: new_start_utc, new_end_utc, reason
    (WEATHER/CLIENT_REQUEST/PHOTOGRAPHER_REQUEST)."""
    payload = {
        "new_start_utc": new_start_utc,
        "new_end_utc": new_end_utc,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def second_shooter_assignment_payload(photographer_id, expected_shoot_schedule_version,
                                      **overrides) -> dict:
    """Required: photographer_id, expected_shoot_schedule_version (OCC, PRD §2.6)."""
    payload = {
        "photographer_id": photographer_id,
        "expected_shoot_schedule_version": expected_shoot_schedule_version,
    }
    payload.update(overrides)
    return payload


def create_gallery_payload(booking_id, **overrides) -> dict:
    """Required: booking_id."""
    payload = {"booking_id": booking_id}
    payload.update(overrides)
    return payload


def upload_gallery_payload(delivered_image_count, **overrides) -> dict:
    """Required: delivered_image_count (>= 1 on upload)."""
    payload = {"delivered_image_count": delivered_image_count}
    payload.update(overrides)
    return payload


def proof_selection_payload(selected_image_count, **overrides) -> dict:
    """Required: selected_image_count (>= 1)."""
    payload = {"selected_image_count": selected_image_count}
    payload.update(overrides)
    return payload


def add_on_order_payload(line_kind, quantity, unit_price_cents,
                         expected_booking_version, **overrides) -> dict:
    """Required: line_kind (PRINT/ALBUM), quantity (>= 1), unit_price_cents (> 0),
    expected_booking_version (OCC, PRD §2.6)."""
    payload = {
        "line_kind": line_kind,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "expected_booking_version": expected_booking_version,
    }
    payload.update(overrides)
    return payload


def cancel_add_on_order_payload(expected_booking_version, **overrides) -> dict:
    """Required: expected_booking_version (OCC, PRD §2.6)."""
    payload = {"expected_booking_version": expected_booking_version}
    payload.update(overrides)
    return payload


def license_grant_payload(usage_scope, territory, term_months, **overrides) -> dict:
    """Required: usage_scope (PERSONAL/COMMERCIAL/EDITORIAL/EXCLUSIVE),
    territory (LOCAL/NATIONAL/WORLDWIDE), term_months (>= 0; 0 = perpetual)."""
    payload = {
        "usage_scope": usage_scope,
        "territory": territory,
        "term_months": term_months,
    }
    payload.update(overrides)
    return payload
