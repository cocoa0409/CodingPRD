"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

VALID_SITTER_STATUSES = {"APPLIED", "BG_CHECK_PENDING", "ACTIVE", "SUSPENDED", "DEACTIVATED"}
VALID_SITTER_TIERS = {"BRONZE", "SILVER", "GOLD"}
VALID_BG_STATUSES = {"PENDING", "CLEARED", "FLAGGED"}
VALID_BG_PROVIDERS = {"CHECKR", "ACCURATE", "FIRST_ADVANTAGE"}
VALID_PET_SPECIES = {"DOG", "CAT"}
VALID_EC_RELATIONSHIPS = {"SPOUSE", "PARENT", "FRIEND", "VET", "NEIGHBOR", "OTHER"}
VALID_MG_STATUSES = {"SCHEDULED", "COMPLETED_APPROVED", "COMPLETED_DECLINED", "NO_SHOW", "CANCELLED"}
VALID_BOOKING_SERVICE_TYPES = {"WALK_30MIN", "WALK_60MIN", "BOARDING_OVERNIGHT", "DAYCARE"}
VALID_BOOKING_TIMES = {"STANDARD", "PEAK", "OVERNIGHT"}
VALID_BOOKING_CADENCE = {"NONE", "WEEKLY", "BIWEEKLY"}
VALID_BOOKING_STATUSES = {
    "REQUESTED", "CONFIRMED", "KEY_RECEIVED", "IN_PROGRESS",
    "COMPLETED", "CANCELLED", "REJECTED", "EMERGENCY_TERMINATED",
}
VALID_KH_METHODS = {"LOCKBOX", "IN_PERSON", "SMART_LOCK"}
VALID_KH_STATUSES = {"PENDING", "RECEIVED", "RETURNED", "LOST"}
VALID_IC_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "PAID", "DENIED", "WITHDRAWN"}


def assert_common_fields(data: dict):
    """Assert id, created_at, updated_at, version on entities that carry the
    common-fields tetrad (every entity except GpsTrack)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_owner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_sitter(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert data["status"] in VALID_SITTER_STATUSES, f"unknown sitter status: {data['status']}"
    assert data["tier"] in VALID_SITTER_TIERS
    assert isinstance(data["tier_score"], int) and 0 <= data["tier_score"] <= 100
    assert isinstance(data["total_completed_bookings"], int) and data["total_completed_bookings"] >= 0
    assert isinstance(data["total_rating_sum"], int)
    assert isinstance(data["total_rating_count"], int)
    assert isinstance(data["claim_count"], int)
    assert isinstance(data["pending_payout_cents"], int) and data["pending_payout_cents"] >= 0
    # suspended_at may be null when never suspended or after reinstatement.
    if data.get("suspended_at") is not None:
        assert is_iso8601_timestamp(data["suspended_at"])


def assert_background_check(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["sitter_id"])
    assert data["provider"] in VALID_BG_PROVIDERS
    assert data["status"] in VALID_BG_STATUSES


def assert_pet(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert isinstance(data["name"], str)
    assert data["species"] in VALID_PET_SPECIES
    assert data["weight_kg"] > 0


def assert_emergency_contact(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert isinstance(data["full_name"], str)
    assert data["relationship"] in VALID_EC_RELATIONSHIPS
    assert isinstance(data["priority"], int) and 1 <= data["priority"] <= 3


def assert_meet_and_greet(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert is_valid_uuid(data["sitter_id"])
    assert is_valid_uuid(data["pet_id"])
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert data["status"] in VALID_MG_STATUSES


def assert_booking(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert is_valid_uuid(data["sitter_id"])
    assert is_valid_uuid(data["pet_id"])
    assert data["service_type"] in VALID_BOOKING_SERVICE_TYPES
    assert data["time_of_day"] in VALID_BOOKING_TIMES
    assert data["recurring_cadence"] in VALID_BOOKING_CADENCE
    assert data["status"] in VALID_BOOKING_STATUSES
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["booking_quote_cents"], int) and data["booking_quote_cents"] >= 0
    assert isinstance(data["provisional_sitter_payout_cents"], int) and data["provisional_sitter_payout_cents"] >= 0
    assert isinstance(data["final_sitter_payout_cents"], int) and data["final_sitter_payout_cents"] >= 0


def assert_key_handoff(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["method"] in VALID_KH_METHODS
    assert data["status"] in VALID_KH_STATUSES


def assert_gps_track(data: dict):
    """GpsTrack is append-only (common_fields: false). It carries only id and
    created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "GpsTrack must NOT carry updated_at (append-only)"
    assert "version" not in data, "GpsTrack must NOT carry version (append-only)"
    assert is_valid_uuid(data["booking_id"])
    assert -90 <= data["latitude"] <= 90
    assert -180 <= data["longitude"] <= 180
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_insurance_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["sitter_id_snapshot"])
    assert data["sitter_tier_snapshot"] in VALID_SITTER_TIERS
    assert data["status"] in VALID_IC_STATUSES
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] > 0
    assert isinstance(data["provisional_payout_cents"], int) and data["provisional_payout_cents"] >= 0
    assert isinstance(data["final_payout_cents"], int) and data["final_payout_cents"] >= 0


# ---- Domain invariants -------------------------------------------------------

def assert_owner_wallet_non_negative(owner: dict):
    """The PRD declares Owner.wallet_credit_cents must never go negative."""
    assert owner["wallet_credit_cents"] >= 0, (
        f"Owner.wallet_credit_cents must be >= 0, got {owner['wallet_credit_cents']}"
    )


def assert_sitter_pending_non_negative(sitter: dict):
    """The PRD declares Sitter.pending_payout_cents must never go negative."""
    assert sitter["pending_payout_cents"] >= 0, (
        f"Sitter.pending_payout_cents must be >= 0, got {sitter['pending_payout_cents']}"
    )


def assert_version_advanced(new_version: int, old_version: int, by: int = 1):
    """A version field must advance by exactly `by` after a single state-changing
    write. PRD §2.4: 'an integer version field that starts at 1 on creation and
    increments by exactly 1 on every mutation that changes the row.'"""
    assert new_version == old_version + by, (
        f"version must increment by {by}: old={old_version}, new={new_version}"
    )
