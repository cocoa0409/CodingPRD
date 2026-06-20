"""Entity creation: required fields, defaults, uniqueness constraints, enum
validation, not-found, system-minted fields, and the assigned-unit listing filter.

Covers queue-B section: entities and endpoints (listing) corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# entities / create_property_missing_state_code_returns_invalid_request
# --------------------------------------------------------------------------- #
def test_create_property_missing_state_code_rejected(api):
    """PRD §3.1: "A `PropertyManager` bootstraps the system by creating a
    `Property`, supplying its `name` and `state_code`, and optionally its
    `recovery_cap_pct` and `common_area_pct`"
    PRD §3.12: "Then the request body is validated for well-formedness —
    required fields present, amounts and percentages in range, enumerations valid
    — yielding `ERR_INVALID_REQUEST` on a malformed body."

    Design: Corner/entities/create_property_missing_state_code_returns_invalid_request
    """
    validate_error(
        api.create_property({"name": "NoState"}, PM),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# --------------------------------------------------------------------------- #
# entities / create_property_applies_recovery_cap_and_common_area_defaults
# --------------------------------------------------------------------------- #
def test_create_property_applies_percentage_defaults(api):
    """PRD §2.7: "a `recovery_cap_pct` (defaulting to 0.85) that expresses the
    maximum fraction of a vendor bill the state permits a landlord to recover
    from tenants, and a `common_area_pct` (defaulting to 0.10) that expresses the
    fraction of every vendor bill that must be reserved as non-recoverable
    common-area cost."
    PRD §3.1: "A new property starts with `integrity_status` of `OK` and a null
    `current_period_label`."

    Design: Corner/entities/create_property_applies_recovery_cap_and_common_area_defaults
    """
    data = validate_success(
        api.create_property({"name": "Defaults", "state_code": "CA"}, PM),
        expected_status=201,
    )
    assert data["recovery_cap_pct"] == 0.85
    assert data["common_area_pct"] == 0.10
    assert data["integrity_status"] == "OK"
    assert data["current_period_label"] is None


# --------------------------------------------------------------------------- #
# entities / create_meter_duplicate_serial_returns_duplicate_serial
# --------------------------------------------------------------------------- #
def test_create_meter_duplicate_serial_rejected(api):
    """PRD §3.1: "A `Meter` is a submeter created under a `property_id` and a
    `utility_id`, identified by a `serial_number` that must be unique per
    property; reusing a serial is rejected with `ERR_DUPLICATE_SERIAL`."

    Design: Corner/entities/create_meter_duplicate_serial_returns_duplicate_serial
    """
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    fx.create_meter(prop["id"], util["id"], serial_number="DUP")
    validate_error(
        api.create_meter(
            {"property_id": prop["id"], "utility_id": util["id"], "serial_number": "DUP"}, PM
        ),
        ApiErrorId.ERR_DUPLICATE_SERIAL.value,
    )


# --------------------------------------------------------------------------- #
# entities / create_unit_duplicate_number_returns_duplicate_unit_number
# --------------------------------------------------------------------------- #
def test_create_unit_duplicate_number_rejected(api):
    """PRD §3.1: "Each `Unit` carries a `unit_number` label that must be unique
    among the property's non-archived units — reusing a number is rejected with
    `ERR_DUPLICATE_UNIT_NUMBER`"

    Design: Corner/entities/create_unit_duplicate_number_returns_duplicate_unit_number
    """
    prop = fx.create_property(state_code="CA")
    fx.create_unit(prop["id"], unit_number="101")
    validate_error(
        api.create_unit(
            {"property_id": prop["id"], "unit_number": "101", "square_feet": 750}, PM
        ),
        ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER.value,
    )


# --------------------------------------------------------------------------- #
# entities / create_utility_invalid_allocation_method_enum_returns_invalid_request
# --------------------------------------------------------------------------- #
def test_create_utility_invalid_allocation_method_rejected(api):
    """PRD §3.1: "its `allocation_method`, which is either `CONSUMPTION` for
    submeter-driven billing or `RUBS` for occupant-ratio billing"
    PRD §3.12: "Then the request body is validated for well-formedness —
    required fields present, amounts and percentages in range, enumerations valid
    — yielding `ERR_INVALID_REQUEST` on a malformed body."

    Design: Corner/entities/create_utility_invalid_allocation_method_enum_returns_invalid_request
    """
    prop = fx.create_property(state_code="CA")
    validate_error(
        api.create_utility(
            {
                "property_id": prop["id"], "utility_type": "WATER",
                "allocation_method": "AVERAGE", "unit_of_measure": "GAL",
            },
            PM,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# --------------------------------------------------------------------------- #
# entities / get_meter_nonexistent_id_returns_not_found
# --------------------------------------------------------------------------- #
def test_get_meter_nonexistent_returns_not_found(api):
    """PRD §2.5: "A request that names a resource identifier in its path must
    resolve that identifier to an existing resource, and where a path or body
    names more than one identifier the system validates them left-to-right,
    rejecting the request with `ERR_NOT_FOUND` at the first identifier that does
    not correspond to an existing resource."

    Design: Corner/entities/get_meter_nonexistent_id_returns_not_found
    """
    validate_error(api.get_meter(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_NOT_FOUND.value)


# --------------------------------------------------------------------------- #
# entities / assign_meter_to_missing_unit_returns_unit_not_found
# --------------------------------------------------------------------------- #
def test_assign_meter_to_missing_unit_returns_unit_not_found(api):
    """PRD §3.2: "Before recording the assignment the system confirms the target
    unit exists and is not `ARCHIVED`, rejecting otherwise with
    `ERR_UNIT_NOT_FOUND`."

    Design: Corner/entities/assign_meter_to_missing_unit_returns_unit_not_found
    """
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    meter = fx.create_meter(prop["id"], util["id"], serial_number="AM1")
    validate_error(
        api.assign_meter(
            meter["id"],
            {"unit_id": NON_EXISTENT_UUID, "effective_from": "2026-06-01T00:00:00Z"},
            PM,
        ),
        ApiErrorId.ERR_UNIT_NOT_FOUND.value,
    )
    after = get_success_data(api.get_meter(meter["id"], PM))
    assert after["status"] == "UNASSIGNED"


# --------------------------------------------------------------------------- #
# entities / system_fields_id_created_version_generated_on_create
# --------------------------------------------------------------------------- #
def test_created_property_has_system_minted_fields(api):
    """PRD §2.4: "carries a system-managed `id` formatted as a UUID with no type
    prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three
    fractional digits."
    PRD §2.4: "All of these resources additionally carry an `updated_at`
    timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every
    modification, and a `version` integer that begins at the resource's first
    persisted value and increments by one on every mutation."

    Design: Corner/entities/system_fields_id_created_version_generated_on_create
    """
    data = validate_success(
        api.create_property({"name": "Sysfields", "state_code": "TX"}, PM),
        expected_status=201,
    )
    assert is_valid_uuid(data["id"])
    assert "_" not in data["id"]  # UUID with no type prefix
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


# --------------------------------------------------------------------------- #
# endpoints / list_meters_filtered_by_assigned_unit_reverse_reachability
# --------------------------------------------------------------------------- #
def test_list_meters_filtered_by_assigned_unit(api):
    """PRD §2.5: "listing meters by `property_id`, `utility_id`,
    `assigned_unit_id`, and `status`"
    PRD §2.5: "All such filter parameters are optional."

    Design: Corner/endpoints/list_meters_filtered_by_assigned_unit_reverse_reachability
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="LST1")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "LSTS1")
    resp = api.list_meters(PM, params={"assigned_unit_id": unit["id"]})
    data, meta = validate_paginated(resp)
    ids = [m["id"] for m in data]
    assert meter["id"] in ids
    assert all(k in meta for k in ("limit", "offset", "total_count", "has_more"))
