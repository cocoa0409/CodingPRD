"""Entity assertions and domain invariant checkers for the Wine-Storage Cellar API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_member(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["membership_tier"] in ("STANDARD", "PREMIUM", "RESERVE")
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["wallet_balance_cents"], int)


def assert_locker(data: dict):
    _common(data)
    assert data["size_tier"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["climate_zone"] in ("RED", "WHITE", "SPARKLING")
    assert isinstance(data["capacity_bottles"], int) and data["capacity_bottles"] >= 1
    assert data["occupancy_status"] in ("VACANT", "PARTIAL", "FULL")
    assert data["climate_status"] in ("NOMINAL", "BREACH")
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "FROZEN", "MAINTENANCE", "RETIRED")
    assert_locker_occupancy_invariant(data)


def assert_locker_occupancy_invariant(data: dict):
    """occupied + reserved + free == capacity at all times (PRD 2.8)."""
    occ = data["occupied_bottles"]
    res = data["reserved_bottles"]
    free = data["free_bottles"]
    cap = data["capacity_bottles"]
    assert occ + res + free == cap, (
        f"occupancy invariant broken: {occ}+{res}+{free} != {cap}"
    )


def assert_bottle(data: dict):
    _common(data)
    assert isinstance(data["wine_name"], str) and data["wine_name"]
    assert isinstance(data["vintage_year"], int)
    assert data["format_ml"] in (375, 750, 1500, 3000)
    assert data["provenance_status"] in ("DOCUMENTED", "UNVERIFIED", "DISPUTED")
    assert data["drink_window_status"] in ("TOO_YOUNG", "IN_WINDOW", "PAST_PEAK")
    assert data["status"] in ("STORED", "WITHDRAWN", "IN_TRANSIT", "CONSIGNED", "SOLD", "DELIVERED")
    assert isinstance(data["appraised_value_cents"], int)


def assert_appraisal(data: dict):
    _common(data)
    assert data["method"] in ("MARKET_COMPARABLE", "REPLACEMENT_COST")
    assert isinstance(data["assessed_value_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_insurance_policy(data: dict):
    _common(data)
    assert data["coverage_tier"] in ("BASIC", "FULL")
    assert isinstance(data["insured_value_cents"], int)
    assert isinstance(data["premium_cents"], int)
    assert data["status"] in ("QUOTED", "BOUND", "LAPSED", "CANCELLED")


def assert_movement_request(data: dict):
    _common(data)
    assert data["request_type"] in ("INTAKE", "WITHDRAWAL")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED")


def assert_delivery_order(data: dict):
    _common(data)
    assert isinstance(data["bottle_ids"], list)
    assert data["status"] in ("SCHEDULED", "DELIVERED", "CANCELLED")


def assert_consignment(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "LISTED", "OFFERED", "COUNTERED", "ACCEPTED", "SETTLED", "WITHDRAWN"
    )


def assert_waitlist_entry(data: dict):
    _common(data)
    assert data["requested_size_tier"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["requested_climate_zone"] in ("RED", "WHITE", "SPARKLING")
    assert data["status"] in ("WAITING", "OFFERED", "FULFILLED", "EXPIRED", "CANCELLED")


def assert_maintenance_window(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_ledger_entry(data: dict):
    _append_only(data)
    assert data["entry_type"] in ("DEBIT", "CREDIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["signed_amount_cents"], int)


def assert_climate_reading(data: dict):
    _append_only(data)
    assert isinstance(data["in_band"], bool)
