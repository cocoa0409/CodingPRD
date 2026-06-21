"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PERFORMER_AVAILABILITY = {"AVAILABLE", "ON_HOLD", "BOOKED", "INACTIVE"}
ACT_TYPES = {"DJ", "BAND", "SOLO_MUSICIAN", "EMCEE", "DUO"}
GENRES = {"HOUSE", "HIP_HOP", "TOP_40", "JAZZ", "ROCK", "COUNTRY", "LATIN", "CLASSICAL", "MULTI_GENRE"}
PACKAGE_TIERS = {"BASIC", "STANDARD", "PREMIUM"}
PACKAGE_STATUSES = {"ACTIVE", "RETIRED"}
EQUIPMENT_CATEGORIES = {"SOUND", "LIGHTING", "STAGING", "FX"}
BOOKING_STATUSES = {
    "INQUIRY", "HOLD", "CONTRACT_SENT", "NEGOTIATING", "CONFIRMED",
    "PERFORMING", "PERFORMED", "SETTLED", "CANCELLED",
}
PAYMENT_KINDS = {"DEPOSIT", "BALANCE", "ADJUSTMENT"}
CAPTURE_STATUSES = {"AUTHORIZED", "CAPTURED", "VOID"}
SETTLEMENT_STATUSES = {"UNSETTLED", "SETTLED", "REFUNDED"}
REFUND_DESTINATIONS = {"ORIGINAL", "STORE_CREDIT"}
LIST_TYPES = {"REQUEST", "DO_NOT_PLAY"}
SONG_STATUSES = {"ACCEPTED", "CONFLICTED"}
CONTRACT_STATUSES = {"ISSUED", "SIGNED", "DECLINED", "SUPERSEDED"}
BACKUP_STATUSES = {"OFFERED", "ACCEPTED", "DECLINED", "PROMOTED", "EXPIRED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_performer(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["stage_name"], str) and len(data["stage_name"]) > 0
    assert data["act_type"] in ACT_TYPES, f"bad act_type {data['act_type']!r}"
    assert data["genre"] in GENRES, f"bad genre {data['genre']!r}"
    assert isinstance(data["base_set_rate_cents"], int) and data["base_set_rate_cents"] >= 0
    assert isinstance(data["overtime_rate_cents_per_15min"], int) and data["overtime_rate_cents_per_15min"] >= 0
    assert data["availability_status"] in PERFORMER_AVAILABILITY
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100, "reliability_score floored at 0, capped at 100"
    assert isinstance(data["lifetime_completed_sets"], int) and data["lifetime_completed_sets"] >= 0


def assert_travel_zone(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0
    assert isinstance(data["base_travel_fee_cents"], int) and data["base_travel_fee_cents"] >= 0
    assert isinstance(data["per_mile_fee_cents"], int) and data["per_mile_fee_cents"] >= 0
    assert isinstance(data["surge_multiplier_bps"], int) and data["surge_multiplier_bps"] >= 10000


def assert_package(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in PACKAGE_TIERS
    assert isinstance(data["flat_package_fee_cents"], int) and data["flat_package_fee_cents"] >= 0
    assert isinstance(data["included_set_minutes"], int) and data["included_set_minutes"] >= 30
    assert isinstance(data["deposit_pct_bps"], int) and 0 <= data["deposit_pct_bps"] <= 10000
    assert data["status"] in PACKAGE_STATUSES


def assert_equipment(data: dict):
    _assert_mutable_common(data)
    assert data["category"] in EQUIPMENT_CATEGORIES
    assert isinstance(data["unit_fee_cents"], int) and data["unit_fee_cents"] >= 0


def assert_client(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0


def assert_booking(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in BOOKING_STATUSES
    for f in (
        "quote_total_cents", "final_total_cents", "overtime_cents",
        "deposit_required_cents", "amount_paid_cents", "balance_due_cents",
        "cancellation_fee_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_payment(data: dict):
    _assert_mutable_common(data)
    assert data["kind"] in PAYMENT_KINDS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["capture_status"] in CAPTURE_STATUSES
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert data["refund_destination"] in REFUND_DESTINATIONS


def assert_song_request(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["list_type"] in LIST_TYPES
    assert data["status"] in SONG_STATUSES


def assert_contract(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["quoted_total_cents"], int)
    assert data["status"] in CONTRACT_STATUSES


def assert_backup_assignment(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert data["status"] in BACKUP_STATUSES


def assert_blackout_window(data: dict):
    """BlackoutWindow is immutable: carries only id + created_at."""
    _assert_common(data)
    assert "version" not in data, "BlackoutWindow must not carry a version field"
    assert "updated_at" not in data, "BlackoutWindow must not carry an updated_at field"
