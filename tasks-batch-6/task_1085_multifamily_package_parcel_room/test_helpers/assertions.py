"""Entity assertions and domain invariant checkers for the Parcel Room API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
_LOCKER_STATUSES = ["AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE"]
_PACKAGE_STATUSES = ["LOGGED", "AWAITING_PICKUP", "HELD", "PICKED_UP",
                     "RETURN_INITIATED", "RETURNED", "DISPOSED"]
_RETURN_STATUSES = ["DROPPED_OFF", "AWAITING_CARRIER", "REJECTED", "PICKED_UP"]
_RESIDENT_STATUSES = ["ACTIVE", "HOLD", "MOVED_OUT"]
_CHARGE_STATUSES = ["OUTSTANDING", "COLLECTED", "WAIVED"]


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities with the standard field set)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version is int >= 1"


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["occupancy_posture"] in _POSTURES, f"bad posture {data.get('occupancy_posture')!r}"
    assert isinstance(data["occupied_locker_count"], int) and data["occupied_locker_count"] >= 0
    assert isinstance(data["in_service_locker_count"], int) and data["in_service_locker_count"] >= 0
    assert isinstance(data["uncollected_fee_cents"], int) and data["uncollected_fee_cents"] >= 0
    assert isinstance(data["return_staging_count"], int) and data["return_staging_count"] >= 0


def assert_locker_bank(data: dict):
    _assert_common(data)
    assert data["storage_class"] in ("AMBIENT", "REFRIGERATED")
    assert isinstance(data["nominal_locker_count"], int) and data["nominal_locker_count"] >= 0
    assert isinstance(data["available_locker_count"], int) and data["available_locker_count"] >= 0
    assert data["available_locker_count"] <= data["nominal_locker_count"]


def assert_locker(data: dict):
    _assert_common(data)
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE", "OVERSIZE")
    assert data["storage_class"] in ("AMBIENT", "REFRIGERATED")
    assert data["status"] in _LOCKER_STATUSES
    if data["status"] != "OCCUPIED":
        assert data.get("current_package_id") in (None, ""), \
            "current_package_id must be null unless OCCUPIED"


def assert_shelf(data: dict):
    _assert_common(data)
    assert data["storage_class"] in ("AMBIENT", "REFRIGERATED")
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["occupied_count"], int) and 0 <= data["occupied_count"] <= data["capacity"]


def assert_resident(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in _RESIDENT_STATUSES
    assert 0.0 <= data["loyalty_discount_pct"] < 1.0


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["scac"], str) and len(data["scac"]) > 0


def assert_package(data: dict):
    _assert_common(data)
    assert data["status"] in _PACKAGE_STATUSES
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE", "OVERSIZE")
    assert data["storage_type"] in ("AMBIENT", "COLD", "PERISHABLE")
    assert data["storage_mode"] in ("NONE", "LOCKER", "SHELF")
    assert isinstance(data["is_oversize"], bool)
    assert data["is_oversize"] == (data["size_class"] == "OVERSIZE"), \
        "is_oversize must be true iff size_class == OVERSIZE"
    assert isinstance(data["notify_count"], int) and data["notify_count"] >= 0
    assert is_iso8601_timestamp(data.get("intake_at", "")), "intake_at must be ISO 8601"
    assert isinstance(data["provisional_fee_cents"], int) and data["provisional_fee_cents"] >= 0


def assert_retail_return(data: dict):
    _assert_common(data)
    assert data["status"] in _RETURN_STATUSES
    assert is_iso8601_timestamp(data.get("dropped_off_at", "")), "dropped_off_at must be ISO 8601"


def assert_storage_charge(data: dict):
    _assert_common(data)
    assert data["charge_type"] == "HOLDING_FEE"
    assert data["status"] in _CHARGE_STATUSES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["basis"], str)


def assert_notification(data: dict):
    """Notification is immutable: id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("INITIAL", "REMINDER", "MOVE_OUT_HOLD", "RETURN_NOTICE", "DISPOSED_NOTICE")


def assert_ledger_consistent(property_data: dict, outstanding_charge_sum: int):
    """PRD §2.7 invariant: uncollected_fee_cents equals the sum of OUTSTANDING HOLDING_FEE
    amounts across the property's packages."""
    assert property_data["uncollected_fee_cents"] == outstanding_charge_sum, (
        f"uncollected_fee_cents {property_data['uncollected_fee_cents']} != "
        f"sum of OUTSTANDING charges {outstanding_charge_sum}"
    )
