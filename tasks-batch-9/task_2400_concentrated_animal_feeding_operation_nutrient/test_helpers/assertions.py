"""Reusable assertion helpers: envelope and record shape, quantity precision,
and the two conserved ledgers.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

TOLERANCE = 0.005

# Fields every mutable record carries.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# The two immutable registers carry only these.
REGISTER_FIELDS = ("id", "created_at")


# ---------------------------------------------------------------------------
# Quantities
# ---------------------------------------------------------------------------
def assert_quantity(actual, expected, label="value"):
    """A 2-decimal quantity equals ``expected``."""
    assert actual is not None, f"{label} is missing"
    assert abs(float(actual) - float(expected)) < TOLERANCE, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimals(actual, label="value"):
    """A quantity carries no more than 2 decimal places."""
    assert actual is not None, f"{label} is missing"
    scaled = float(actual) * 100
    assert abs(scaled - round(scaled)) < 1e-6, (
        f"{label}: {actual} carries more than 2 decimal places"
    )


def assert_four_decimals(actual, label="value"):
    """A quantity carries no more than 4 decimal places."""
    assert actual is not None, f"{label} is missing"
    scaled = float(actual) * 10000
    assert abs(scaled - round(scaled)) < 1e-6, (
        f"{label}: {actual} carries more than 4 decimal places"
    )


def assert_whole_gallons(actual, label="value"):
    assert float(actual) == int(float(actual)), (
        f"{label}: {actual} is not a whole number of gallons"
    )


def assert_multiple_of_hundred(actual, label="rate"):
    assert float(actual) % 100 == 0, f"{label}: {actual} is not a whole 100 gallons"


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------
def assert_common_fields(record, label="record"):
    """A mutable record carries a UUID id, both timestamps and a version."""
    for name in COMMON_FIELDS:
        assert name in record, f"{label} is missing {name}"
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"{label}.created_at is not ISO 8601: {record['created_at']}"
    )
    assert is_iso8601_timestamp(record["updated_at"]), (
        f"{label}.updated_at is not ISO 8601: {record['updated_at']}"
    )
    assert isinstance(record["version"], int), f"{label}.version is not an integer"
    assert record["version"] >= 1, f"{label}.version must start at 1"


def assert_immutable_register(record, label="record"):
    """An immutable register carries id and created_at and nothing else of that kind."""
    for name in REGISTER_FIELDS:
        assert name in record, f"{label} is missing {name}"
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"{label}.created_at is not ISO 8601: {record['created_at']}"
    )
    assert "updated_at" not in record, f"{label} must not carry updated_at"
    assert "version" not in record, f"{label} must not carry version"


def assert_fields_present(record, names, label="record"):
    missing = [n for n in names if n not in record]
    assert not missing, f"{label} is missing fields: {missing}"


# ---------------------------------------------------------------------------
# Operation
# ---------------------------------------------------------------------------
def assert_operation_sizing(
    operation,
    animal_units,
    size_class,
    permit_required,
    design_annual_manure_gallons,
    daily_production_gallons,
):
    assert_quantity(operation["animal_units"], animal_units, "animal_units")
    assert operation["size_class"] == size_class, (
        f"size_class: expected {size_class}, got {operation['size_class']}"
    )
    assert operation["permit_required"] is permit_required, (
        f"permit_required: expected {permit_required}, got {operation['permit_required']}"
    )
    assert_quantity(
        operation["design_annual_manure_gallons"],
        design_annual_manure_gallons,
        "design_annual_manure_gallons",
    )
    assert_quantity(
        operation["daily_production_gallons"],
        daily_production_gallons,
        "daily_production_gallons",
    )


def assert_posture(operation, posture, findings=None, discharges=None):
    assert operation["compliance_posture"] == posture, (
        f"compliance_posture: expected {posture}, got {operation['compliance_posture']}"
    )
    if findings is not None:
        assert operation["open_finding_count"] == findings, (
            f"open_finding_count: expected {findings}, "
            f"got {operation['open_finding_count']}"
        )
    if discharges is not None:
        assert operation["open_discharge_incident_count"] == discharges, (
            f"open_discharge_incident_count: expected {discharges}, "
            f"got {operation['open_discharge_incident_count']}"
        )


# ---------------------------------------------------------------------------
# Field nutrient budget: the field allowance ledger
# ---------------------------------------------------------------------------
def assert_budget_ledger(budget, applied=None, remaining=None, total=None):
    """applied + remaining always equals allowable_total_gallons."""
    if total is not None:
        assert_quantity(budget["allowable_total_gallons"], total, "allowable_total_gallons")
    if applied is not None:
        assert_quantity(budget["applied_gallons_to_date"], applied, "applied_gallons_to_date")
    if remaining is not None:
        assert_quantity(budget["remaining_gallons"], remaining, "remaining_gallons")
    assert_quantity(
        float(budget["applied_gallons_to_date"]) + float(budget["remaining_gallons"]),
        float(budget["allowable_total_gallons"]),
        "applied + remaining vs allowable_total_gallons",
    )


def assert_budget_rates(
    budget,
    crop_n_need=None,
    legume_credit=None,
    adjusted_n_need=None,
    crop_p_removal=None,
    p_allowance=None,
    allowable_n_rate=None,
    allowable_p_rate=None,
    binding_basis=None,
    allowable_rate=None,
):
    pairs = (
        ("crop_n_need_lbs", crop_n_need),
        ("legume_credit_lbs", legume_credit),
        ("adjusted_n_need_lbs", adjusted_n_need),
        ("crop_p_removal_lbs", crop_p_removal),
        ("p_allowance_lbs", p_allowance),
        ("allowable_n_rate_gal_per_acre", allowable_n_rate),
        ("allowable_p_rate_gal_per_acre", allowable_p_rate),
        ("allowable_rate_gal_per_acre", allowable_rate),
    )
    for name, expected in pairs:
        if expected is not None:
            assert_quantity(budget[name], expected, name)
    if binding_basis is not None:
        assert budget["binding_basis"] == binding_basis, (
            f"binding_basis: expected {binding_basis}, got {budget['binding_basis']}"
        )


# ---------------------------------------------------------------------------
# Manure storage: the volume balance
# ---------------------------------------------------------------------------
def assert_storage_balance(
    storage,
    intake=None,
    precipitation=None,
    outflow=None,
    current=None,
    committed=None,
    available=None,
    days=None,
):
    """intake + precipitation - outflow == current_volume, and
    operating_capacity - current_volume - committed == available_capacity."""
    pairs = (
        ("cumulative_intake_gallons", intake),
        ("precipitation_adjustment_gallons", precipitation),
        ("cumulative_outflow_gallons", outflow),
        ("current_volume_gallons", current),
        ("committed_outflow_gallons", committed),
        ("available_capacity_gallons", available),
    )
    for name, expected in pairs:
        if expected is not None:
            assert_quantity(storage[name], expected, name)
    if days is not None:
        assert storage["days_of_storage_available"] == days, (
            f"days_of_storage_available: expected {days}, "
            f"got {storage['days_of_storage_available']}"
        )
    assert_quantity(
        float(storage["cumulative_intake_gallons"])
        + float(storage["precipitation_adjustment_gallons"])
        - float(storage["cumulative_outflow_gallons"]),
        float(storage["current_volume_gallons"]),
        "intake + precipitation - outflow vs current_volume_gallons",
    )
    assert_quantity(
        float(storage["operating_capacity_gallons"])
        - float(storage["current_volume_gallons"])
        - float(storage["committed_outflow_gallons"]),
        float(storage["available_capacity_gallons"]),
        "operating capacity less volume less commitments vs available_capacity_gallons",
    )


def assert_storage_capacities(storage, design=None, reserve=None, operating=None):
    if design is not None:
        assert_quantity(storage["design_capacity_gallons"], design, "design_capacity_gallons")
    if reserve is not None:
        assert_quantity(
            storage["freeboard_reserve_gallons"], reserve, "freeboard_reserve_gallons"
        )
    if operating is not None:
        assert_quantity(
            storage["operating_capacity_gallons"], operating, "operating_capacity_gallons"
        )


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
def assert_state(record, key, expected, label=None):
    label = label or key
    actual = record.get(key)
    expected_value = getattr(expected, "value", expected)
    assert actual == expected_value, (
        f"{label}: expected {expected_value}, got {actual}"
    )


def assert_version_unchanged(before, after, label="record"):
    assert before["version"] == after["version"], (
        f"{label}.version changed: {before['version']} -> {after['version']}"
    )


def assert_null(record, *keys):
    for key in keys:
        assert record.get(key, "__missing__") is None, (
            f"{key}: expected null, got {record.get(key)}"
        )


def assert_not_null(record, *keys):
    for key in keys:
        assert record.get(key) is not None, f"{key}: expected a value, got null"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def assert_pagination(pagination, limit=None, offset=None, total=None):
    if limit is not None:
        assert pagination["limit"] == limit, (
            f"pagination.limit: expected {limit}, got {pagination['limit']}"
        )
    if offset is not None:
        assert pagination["offset"] == offset, (
            f"pagination.offset: expected {offset}, got {pagination['offset']}"
        )
    if total is not None:
        assert pagination["total"] == total, (
            f"pagination.total: expected {total}, got {pagination['total']}"
        )


def assert_ordered_by_created_at(items):
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"items are not in ascending created_at order: {stamps}"
