"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
  - Host.platform_fee_bps is optional (defaults 1500); all other host inputs required.
  - Spot.overstay_grace_minutes is optional (defaults 15); all other spot inputs required.
  - All Driver / PricingEvent / Booking / TransferOffer / ViolationRecord inputs required.
"""
import itertools

from .constants import TEST_DEFAULTS

# Monotonic counter so default emails are unique within a single test process.
_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_seq)}@example.com"


def create_host_payload(**overrides) -> dict:
    """POST /hosts. platform_fee_bps optional (omit to exercise the default)."""
    defaults = {
        "email": _uniq("host"),
        "display_name": "Test Host",
        "payout_account_ref": "pa_test",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    """POST /drivers."""
    defaults = {
        "email": _uniq("driver"),
        "display_name": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def topup_payload(amount_cents: int, **overrides) -> dict:
    """POST /drivers/{id}/wallet/topup."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_spot_payload(host_id: str, **overrides) -> dict:
    """POST /spots. overstay_grace_minutes optional (omit to exercise the default 15)."""
    defaults = {
        "host_id": host_id,
        "title": "Test Spot",
        "zone_code": "Z-TEST",
        "base_hourly_cents": TEST_DEFAULTS["BASE_HOURLY_CENTS"],
        "base_daily_cents": TEST_DEFAULTS["BASE_DAILY_CENTS"],
        "monthly_flat_cents": TEST_DEFAULTS["MONTHLY_FLAT_CENTS"],
        "availability_start": TEST_DEFAULTS["AVAILABILITY_START"],
        "availability_end": TEST_DEFAULTS["AVAILABILITY_END"],
        "overstay_grace_minutes": TEST_DEFAULTS["OVERSTAY_GRACE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_pricing_event_payload(zone_code: str, window_start: str, window_end: str,
                                 surge_multiplier_bps: int, **overrides) -> dict:
    """POST /pricing-events."""
    defaults = {
        "zone_code": zone_code,
        "window_start": window_start,
        "window_end": window_end,
        "surge_multiplier_bps": surge_multiplier_bps,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(spot_id: str, driver_id: str, rate_kind: str,
                           start_at: str, end_at: str, expected_spot_version: int,
                           **overrides) -> dict:
    """POST /bookings."""
    defaults = {
        "spot_id": spot_id,
        "driver_id": driver_id,
        "rate_kind": rate_kind,
        "start_at": start_at,
        "end_at": end_at,
        "expected_spot_version": expected_spot_version,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_offer_payload(booking_id: str, to_driver_id: str,
                                  expected_booking_version: int, **overrides) -> dict:
    """POST /transfer-offers."""
    defaults = {
        "booking_id": booking_id,
        "to_driver_id": to_driver_id,
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(booking_id: str, violation_kind: str, base_points: int,
                             **overrides) -> dict:
    """POST /violations."""
    defaults = {
        "booking_id": booking_id,
        "violation_kind": violation_kind,
        "base_points": base_points,
    }
    defaults.update(overrides)
    return defaults


def reverse_payout_payload(expected_booking_version: int, **overrides) -> dict:
    """POST /bookings/{id}/reverse-payout."""
    defaults = {"expected_booking_version": expected_booking_version}
    defaults.update(overrides)
    return defaults


def redeem_payload(qr_token: str, **overrides) -> dict:
    """POST /access-passes/redeem."""
    defaults = {"qr_token": qr_token}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc."""
    return {"to_iso8601": to_iso8601}
