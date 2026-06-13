"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD contract using
the framework's generic format validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_BILLING = {"CURRENT", "PAST_DUE", "ON_HOLD"}
_ROSTER = {"ACTIVE", "RAMP_DOWN", "REMOVED"}
_CATEGORY = {"SHIRT", "PANT", "JACKET", "COVERALL"}
_LIFECYCLE = {"IN_STOCK", "ASSIGNED", "RETIRED", "LOST"}
_WASH_LOC = {"AT_PLANT", "AT_CUSTOMER", "IN_SOIL", "IN_WASH"}
_ASG_STATUS = {"ASSIGNED", "RETURNED", "LOST", "DAMAGED"}
_VISIT_STATUS = {"SCHEDULED", "PICKED_UP", "DELIVERED", "RECONCILED"}
_CHARGE_TYPE = {"RENTAL", "SHORTAGE", "LOSS", "DAMAGE", "EMBLEM_SETUP"}
_SHIRT = {"XS", "S", "M", "L", "XL", "XXL"}
_DAY = {"MON", "TUE", "WED", "THU", "FRI"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and only increments"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["service_day"] in _DAY
    assert isinstance(data["shortage_grace_units"], int) and data["shortage_grace_units"] >= 0
    assert data["billing_status"] in _BILLING
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0
    assert isinstance(data["active_wearer_count"], int) and data["active_wearer_count"] >= 0


def assert_wearer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["shirt_size"] in _SHIRT
    assert isinstance(data["pant_size"], int) and 28 <= data["pant_size"] <= 48
    assert data["roster_status"] in _ROSTER
    assert isinstance(data["assigned_garment_count"], int) and data["assigned_garment_count"] >= 0
    assert isinstance(data["locker_label"], str) and len(data["locker_label"]) > 0


def assert_garment_type(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in _CATEGORY
    for f in ("weekly_rate_cents", "replacement_cost_cents", "emblem_setup_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative int"


def assert_garment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("garment_type_id", "")), "garment_type_id must be a UUID"
    assert isinstance(data["tag_code"], str) and len(data["tag_code"]) > 0
    assert data["lifecycle_status"] in _LIFECYCLE
    assert data["wash_location"] in _WASH_LOC
    assert isinstance(data["soil_strikes"], int) and data["soil_strikes"] >= 0


def assert_wash_station(data: dict):
    _assert_common(data)
    assert isinstance(data["station_code"], str) and len(data["station_code"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("garment_id", "")), "garment_id must be a UUID"
    assert is_valid_uuid(data.get("wearer_id", "")), "wearer_id must be a UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["status"] in _ASG_STATUS


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["route_code"], str) and len(data["route_code"]) > 0
    assert data["service_day"] in _DAY
    assert isinstance(data["driver_user_id"], str) and len(data["driver_user_id"]) > 0


def assert_route_stop(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["stop_sequence"], int) and data["stop_sequence"] >= 1
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert 0 <= data["window_start_min"] < data["window_end_min"] <= 1440


def assert_service_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("route_stop_id", "")), "route_stop_id must be a UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["week_index"], int) and data["week_index"] >= 0
    assert data["status"] in _VISIT_STATUS
    assert isinstance(data["expected_soil_count"], int) and data["expected_soil_count"] >= 0
    assert isinstance(data["actual_soil_count"], int) and data["actual_soil_count"] >= 0
    assert isinstance(data["provisional_charge_cents"], int)
    assert isinstance(data["finalized_charge_cents"], int)


def assert_service_charge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["charge_type"] in _CHARGE_TYPE
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["paid"], bool)
