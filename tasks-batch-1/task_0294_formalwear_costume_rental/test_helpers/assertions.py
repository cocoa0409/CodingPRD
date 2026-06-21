"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the response structure against the PRD
contract using the framework's generic format helpers.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_SIZE_CODES = ["XS", "S", "M", "L", "XL", "XXL"]


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities with common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_catalog(data: dict):
    _assert_common(data)
    assert isinstance(data["style_name"], str) and len(data["style_name"]) > 0
    assert data["category"] in ("FORMALWEAR", "COSTUME")
    for f in ("daily_rate_cents", "deposit_cents", "replacement_value_cents",
              "waiver_daily_rate_cents", "cleaning_buffer_days", "late_fee_daily_rate_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be an int >= 0"
    assert isinstance(data["active_unit_count"], int) and data["active_unit_count"] >= 0


def assert_garment_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("catalog_id", "")), "catalog_id must be a valid UUID"
    assert data["size_code"] in _SIZE_CODES
    assert data["condition_grade"] in ("GRADE_A", "GRADE_B", "GRADE_C")
    assert data["status"] in ("AVAILABLE", "RESERVED", "OUT", "IN_CLEANING", "RETIRED")
    assert isinstance(data["damage_strike_count"], int) and data["damage_strike_count"] >= 0
    # available_from_iso is null until ever rented, else an ISO timestamp.
    afi = data.get("available_from_iso")
    assert afi is None or is_iso8601_timestamp(afi), "available_from_iso null or ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    for f in ("deposit_held_cents", "balance_owed_cents", "open_strike_count"):
        assert isinstance(data[f], int), f"{f} must be an integer"
        assert data[f] >= 0, f"{f} must be >= 0"


def assert_measurement_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    for f in ("chest_cm", "waist_cm", "inseam_cm"):
        assert isinstance(data[f], int) and data[f] > 0, f"{f} must be a positive int"
    assert data["recommended_size_code"] in _SIZE_CODES


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("catalog_id", "")), "catalog_id must be a valid UUID"
    assert data["requested_size_code"] in _SIZE_CODES
    assert data["status"] in (
        "PENDING", "CONFIRMED", "PICKED_UP", "RETURNED", "OVERDUE", "SETTLED", "CANCELLED")
    assert isinstance(data["damage_waiver_opted"], bool)
    # garment_unit_id is null while PENDING, a UUID once allocated.
    gid = data.get("garment_unit_id")
    assert gid is None or is_valid_uuid(gid), "garment_unit_id null or UUID"


def assert_alteration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a valid UUID"
    assert data["kind"] in ("HEM", "TAKE_IN", "LET_OUT")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ("REQUESTED", "COMPLETED", "CANCELLED")


def assert_party_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("coordinator_customer_id", "")), \
        "coordinator_customer_id must be a valid UUID"
    assert isinstance(data["required_member_count"], int) and data["required_member_count"] >= 1
    assert isinstance(data["confirmed_member_count"], int) and data["confirmed_member_count"] >= 0
    assert data["posture"] in ("FORMING", "READY", "LOCKED", "DISSOLVED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a valid UUID"
    assert data["disposition"] in ("CLEAN", "DAMAGED", "LOST")
    for f in ("late_days", "late_fee_cents", "damage_fee_cents", "waiver_credit_cents",
              "net_charge_cents", "deposit_refund_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
        assert data[f] >= 0, f"{f} must be >= 0"


def assert_fit_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a valid UUID"
    assert is_valid_uuid(data.get("measurement_profile_id", "")), \
        "measurement_profile_id must be a valid UUID"
    assert data["verdict"] in ("PASS", "NEEDS_ALTERATION", "FAIL")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: carries ONLY id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "LedgerEntry is append-only: no updated_at"
    assert "version" not in data, "LedgerEntry is append-only: no version"
    assert data["entry_type"] in (
        "DEPOSIT_HOLD", "DEPOSIT_RELEASE", "DEPOSIT_CAPTURE", "FEE_CHARGE", "FEE_WAIVE")
    assert isinstance(data["amount_cents"], int)


def assert_deposit_conserved(ledger_entries: list):
    """PRD §2.9 invariant over a single reservation's lifecycle: the DEPOSIT_HOLD
    magnitude equals the sum of the matching DEPOSIT_RELEASE magnitude and
    DEPOSIT_CAPTURE magnitude."""
    hold = sum(e["amount_cents"] for e in ledger_entries if e["entry_type"] == "DEPOSIT_HOLD")
    release = sum(abs(e["amount_cents"]) for e in ledger_entries
                  if e["entry_type"] == "DEPOSIT_RELEASE")
    capture = sum(abs(e["amount_cents"]) for e in ledger_entries
                  if e["entry_type"] == "DEPOSIT_CAPTURE")
    assert hold == release + capture, (
        f"deposit not conserved: hold {hold} != release {release} + capture {capture}")
    return hold, release, capture
