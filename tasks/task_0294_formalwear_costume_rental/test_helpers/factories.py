"""Payload factories — one per entity, input fields only.

Field names are exact per the Formalwear & Costume Rental PRD. Each factory
provides PRD-faithful defaults and accepts **overrides.
"""
import itertools

from .constants import CATALOG_DEFAULTS

# Monotonic counter so generated emails are unique per process run.
_email_seq = itertools.count(1)


def unique_email(prefix: str = "cust") -> str:
    return f"{prefix}{next(_email_seq)}@example.com"


def create_catalog_payload(**overrides) -> dict:
    """POST /catalogs input: style_name, category, daily_rate_cents, deposit_cents,
    replacement_value_cents, waiver_daily_rate_cents, cleaning_buffer_days,
    late_fee_daily_rate_cents."""
    defaults = {
        "style_name": "Test Tux",
        "category": "FORMALWEAR",
        "daily_rate_cents": CATALOG_DEFAULTS["daily_rate_cents"],
        "deposit_cents": CATALOG_DEFAULTS["deposit_cents"],
        "replacement_value_cents": CATALOG_DEFAULTS["replacement_value_cents"],
        "waiver_daily_rate_cents": CATALOG_DEFAULTS["waiver_daily_rate_cents"],
        "cleaning_buffer_days": CATALOG_DEFAULTS["cleaning_buffer_days"],
        "late_fee_daily_rate_cents": CATALOG_DEFAULTS["late_fee_daily_rate_cents"],
    }
    defaults.update(overrides)
    return defaults


def create_garment_unit_payload(catalog_id: str, size_code: str = "M", **overrides) -> dict:
    """POST /garment-units input: catalog_id, size_code."""
    defaults = {"catalog_id": catalog_id, "size_code": size_code}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """POST /customers input: full_name, email."""
    defaults = {"full_name": "Test Customer", "email": unique_email()}
    defaults.update(overrides)
    return defaults


def create_measurement_profile_payload(chest_cm: int = 100, waist_cm: int = 84,
                                       inseam_cm: int = 80, **overrides) -> dict:
    """POST /customers/{id}/measurement-profiles input: chest_cm, waist_cm, inseam_cm."""
    defaults = {"chest_cm": chest_cm, "waist_cm": waist_cm, "inseam_cm": inseam_cm}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(customer_id: str, catalog_id: str,
                               requested_size_code: str = "M",
                               event_date_iso: str = "2026-09-06T00:00:00Z",
                               pickup_window_start_iso: str = "2026-09-01T09:00:00Z",
                               return_window_end_iso: str = "2026-09-05T09:00:00Z",
                               **overrides) -> dict:
    """POST /reservations input: customer_id, catalog_id, requested_size_code,
    event_date_iso, pickup_window_start_iso, return_window_end_iso,
    party_order_id?, damage_waiver_opted?."""
    defaults = {
        "customer_id": customer_id,
        "catalog_id": catalog_id,
        "requested_size_code": requested_size_code,
        "event_date_iso": event_date_iso,
        "pickup_window_start_iso": pickup_window_start_iso,
        "return_window_end_iso": return_window_end_iso,
        "damage_waiver_opted": False,
    }
    defaults.update(overrides)
    return defaults


def create_alteration_payload(reservation_id: str, kind: str = "HEM",
                              fee_cents: int = 4000, **overrides) -> dict:
    """POST /alterations input: reservation_id, kind, fee_cents."""
    defaults = {"reservation_id": reservation_id, "kind": kind, "fee_cents": fee_cents}
    defaults.update(overrides)
    return defaults


def create_fit_check_payload(reservation_id: str, measurement_profile_id: str,
                             **overrides) -> dict:
    """POST /fit-checks input: reservation_id, measurement_profile_id."""
    defaults = {"reservation_id": reservation_id, "measurement_profile_id": measurement_profile_id}
    defaults.update(overrides)
    return defaults


def create_party_order_payload(coordinator_customer_id: str,
                               event_date_iso: str = "2026-09-06T00:00:00Z",
                               required_member_count: int = 1, **overrides) -> dict:
    """POST /party-orders input: coordinator_customer_id, event_date_iso,
    required_member_count."""
    defaults = {
        "coordinator_customer_id": coordinator_customer_id,
        "event_date_iso": event_date_iso,
        "required_member_count": required_member_count,
    }
    defaults.update(overrides)
    return defaults


def return_payload(returned_at_iso: str, disposition: str = "CLEAN", **overrides) -> dict:
    """POST /reservations/{id}/return input: returned_at_iso, disposition."""
    defaults = {"returned_at_iso": returned_at_iso, "disposition": disposition}
    defaults.update(overrides)
    return defaults


def waive_fee_payload(waive_amount_cents: int, expected_settlement_version: int,
                      **overrides) -> dict:
    """POST /settlements/{id}/waive-fee input: waive_amount_cents,
    expected_settlement_version."""
    defaults = {
        "waive_amount_cents": waive_amount_cents,
        "expected_settlement_version": expected_settlement_version,
    }
    defaults.update(overrides)
    return defaults


def retire_payload(expected_garment_unit_version: int, **overrides) -> dict:
    """POST /garment-units/{id}/retire input: expected_garment_unit_version."""
    defaults = {"expected_garment_unit_version": expected_garment_unit_version}
    defaults.update(overrides)
    return defaults
