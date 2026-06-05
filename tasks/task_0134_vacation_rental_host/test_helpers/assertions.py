"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the shape of a returned resource against the
PRD's field contract. Domain invariant helpers assert money-conservation and
boundary rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ListingStatus, CancellationTier, ChannelName, ChannelConnectionStatus,
    CalendarBlockSource, CalendarBlockStatus, ScreeningStatus,
    ScreeningFailureReason, BookingStatus, SecurityDepositStatus,
    DamageClaimStatus, PayoutStatus, ImportStatus, HostPayoutMethod,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_host(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert data["payout_method"] in [m.value for m in HostPayoutMethod]


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["govt_id_verified"], bool)
    assert isinstance(data["prior_cancellations"], int) and data["prior_cancellations"] >= 0
    assert isinstance(data["chargeback_flag"], bool)


def assert_listing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["host_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["base_nightly_rate_cents"], int) and data["base_nightly_rate_cents"] > 0
    assert isinstance(data["cleaning_fee_cents"], int) and data["cleaning_fee_cents"] >= 0
    assert isinstance(data["pet_fee_cents"], int) and data["pet_fee_cents"] >= 0
    assert isinstance(data["tax_rate_bps"], int) and 0 <= data["tax_rate_bps"] <= 2000
    assert isinstance(data["min_nights"], int) and data["min_nights"] >= 1
    assert isinstance(data["gap_nights"], int) and data["gap_nights"] >= 0
    assert data["cancellation_tier"] in [t.value for t in CancellationTier]
    assert isinstance(data["security_deposit_cents"], int) and data["security_deposit_cents"] >= 0
    assert isinstance(data["platform_commission_bps"], int) and 0 <= data["platform_commission_bps"] <= 3000
    assert isinstance(data["payout_delay_days"], int) and data["payout_delay_days"] >= 0
    assert isinstance(data["calendar_version"], int) and data["calendar_version"] >= 1
    assert data["status"] in [s.value for s in ListingStatus]


def assert_rate_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["listing_id"])
    assert isinstance(data["label"], str)
    assert isinstance(data["seasonal_multiplier_bps"], int)
    assert isinstance(data["weekend_multiplier_bps"], int)


def assert_channel_connection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["listing_id"])
    assert data["channel"] in [c.value for c in ChannelName]
    assert data["status"] in [s.value for s in ChannelConnectionStatus]
    assert isinstance(data["pending_sync_count"], int) and data["pending_sync_count"] >= 0


def assert_calendar_block(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["listing_id"])
    assert data["source"] in [s.value for s in CalendarBlockSource]
    assert data["status"] in [s.value for s in CalendarBlockStatus]


def assert_screening_result(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["guest_id"])
    assert data["status"] in [s.value for s in ScreeningStatus]
    assert data["failure_reason"] in [r.value for r in ScreeningFailureReason]


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["guest_id"])
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["pets_count"], int) and data["pets_count"] >= 0
    assert isinstance(data["nightly_subtotal_cents"], int)
    assert isinstance(data["fees_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["cancellation_tier_snapshot"] in [t.value for t in CancellationTier]
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert data["status"] in [s.value for s in BookingStatus]


def assert_security_deposit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["authorized_cents"], int) and data["authorized_cents"] >= 0
    assert isinstance(data["held_cents"], int) and data["held_cents"] >= 0
    assert data["status"] in [s.value for s in SecurityDepositStatus]


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["security_deposit_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["approved_cents"], int) and data["approved_cents"] >= 0
    assert data["status"] in [s.value for s in DamageClaimStatus]


def assert_payout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["host_id"])
    assert isinstance(data["estimated_cents"], int) and data["estimated_cents"] >= 0
    assert isinstance(data["actual_cents"], int) and data["actual_cents"] >= 0
    assert data["status"] in [s.value for s in PayoutStatus]


def assert_imported_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["channel_connection_id"])
    assert isinstance(data["external_ref"], str)
    assert data["import_status"] in [s.value for s in ImportStatus]


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_deposit_balance_conserved(deposit: dict):
    """held_cents == authorized_cents - sum(approved_cents of APPROVED claims).
    Caller passes a fully resolved deposit; this checks the basic floor/ceiling
    invariants that must always hold (PRD §3.7)."""
    assert deposit["held_cents"] >= 0, "held_cents must never go negative"
    assert deposit["held_cents"] <= deposit["authorized_cents"], \
        "held_cents must never exceed authorized_cents"
