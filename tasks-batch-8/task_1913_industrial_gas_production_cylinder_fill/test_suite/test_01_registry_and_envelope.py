"""Registry, derived defaults, uniqueness, and list envelope rules (PRD §2, §3.1, §3.2)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_cylinder,
    assert_telemetry_reading,
    create_cylinder_payload,
    create_test_cylinder,
    create_test_plant,
    create_test_tank,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def test_cylinder_created_with_derived_defaults(api):
    """PRD §3.2: "The cylinder's `water_capacity_liters` is derived from its size —
    10 liters for `SMALL`, 50 for `STANDARD`, 100 for `LARGE` — and any
    client-supplied value is ignored. A new cylinder enters `IN_STOCK` with both
    `current_fill_lot_id` and `last_fill_lot_id` null."
    PRD §3.2: "The `hydro_due_date` is computed by adding the retest interval for
    the cylinder's `service_gas` to its `last_hydro_date` — 6 months for `CO2`,
    12 months for every other gas — with the day clamped to the target month's
    last day when the computed day does not exist in that month."

    Design: Corner/entities/cylinder_created_with_derived_defaults
    """
    res = api.create_cylinder(
        create_cylinder_payload(
            serial_number="SN-EN1", size_code="STANDARD", service_gas="O2",
            last_hydro_date="2025-09-01",
        ),
        OP,
    )
    cyl = validate_success(res, 201)
    assert_cylinder(cyl)
    assert cyl["water_capacity_liters"] == 50, "STANDARD size derives 50 liters"
    assert cyl["hydro_due_date"] == "2026-09-01", "O2 retest interval is 12 months"
    assert cyl["hydro_status"] == "COMPLIANT", (
        "due 2026-09-01 is more than 30 days past the 2026-08-01 clock"
    )
    assert cyl["status"] == "IN_STOCK"
    assert cyl["version"] == 1
    assert cyl["current_fill_lot_id"] is None
    assert cyl["last_fill_lot_id"] is None


def test_cylinder_duplicate_serial_rejected(api):
    """PRD §3.2: "Serial numbers are globally unique across every cylinder ever
    registered, including cylinders later marked `LOST` or `RETIRED`; a duplicate
    is rejected with `ERR_DUPLICATE_CYLINDER_SERIAL`."

    Design: Corner/entities/cylinder_duplicate_serial_rejected
    """
    first = create_test_cylinder(
        serial_number="SN-EN2", size_code="SMALL", service_gas="N2"
    )
    assert first["status"] == "IN_STOCK"
    res = api.create_cylinder(
        create_cylinder_payload(
            serial_number="SN-EN2", size_code="LARGE", service_gas="O2"
        ),
        OP,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CYLINDER_SERIAL.value)


def test_cylinder_duplicate_serial_rejected_after_retirement(api):
    """PRD §3.2: "Serial numbers are globally unique across every cylinder ever
    registered, including cylinders later marked `LOST` or `RETIRED`; a duplicate
    is rejected with `ERR_DUPLICATE_CYLINDER_SERIAL`."
    PRD §3.2: "a `QualityManager` may decommission an in-plant cylinder with a
    `disposition` of `LOST` or `RETIRED`, permitted only from `IN_STOCK` or
    `QUARANTINED`; both dispositions are terminal states for the asset."

    Design: Corner/entities/cylinder_duplicate_serial_rejected
    """
    QM = TEST_USERS["quality_manager_headers"]
    first = create_test_cylinder(serial_number="SN-EN2R", service_gas="AR")
    retired = validate_success(
        api.decommission_cylinder(first["id"], {"disposition": "RETIRED"}, QM), 200
    )
    assert retired["status"] == "RETIRED"
    res = api.create_cylinder(
        create_cylinder_payload(serial_number="SN-EN2R", service_gas="HE"), OP
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CYLINDER_SERIAL.value)


def test_cylinder_invalid_enum_value_rejected(api):
    """PRD §2.8: "Required fields are present, types are correct, every enum
    member is one of the declared values, exactly-one field pairs carry exactly
    one side, reading levels lie within owner capacity, `period_start` is not
    after `period_end`, and route window bounds hold (start hour between 0 and 23
    inclusive, end hour between 1 and 24 inclusive, end strictly after start).
    Failure: `ERR_INVALID_REQUEST` or, for an undeclared enum member,
    `ERR_INVALID_ENUM_VALUE` (both HTTP 400)."

    Design: Corner/entities/cylinder_invalid_enum_value_rejected
    """
    res = api.create_cylinder(
        create_cylinder_payload(serial_number="SN-EN3", size_code="HUGE"), OP
    )
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)


def test_tank_missing_required_field_rejected(api):
    """PRD §3.1: "cryogenic storage tanks are registered with the owning
    `plant_id`, a `product_code` drawn from `O2`, `N2`, `AR`, `CO2`, `H2`, or
    `HE`, a `capacity_liters` greater than zero, an `initial_level_liters`
    between zero and capacity inclusive, and an informational
    `reorder_point_liters` low-level threshold, likewise between zero and
    capacity inclusive."
    PRD §2.8: "Required fields are present, types are correct ... Failure:
    `ERR_INVALID_REQUEST` or, for an undeclared enum member,
    `ERR_INVALID_ENUM_VALUE` (both HTTP 400)."

    Design: Corner/entities/tank_missing_required_field_rejected
    """
    plant = create_test_plant(plant_name="P-EN4")
    payload = {
        "plant_id": plant["id"],
        "product_code": "O2",
        "initial_level_liters": 100,
        "reorder_point_liters": 10,
    }
    res = api.create_tank(payload, PM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_fill_lot_with_unknown_tank_returns_not_found(api):
    """PRD §2.9: "the server validates identifiers in a strict left-to-right
    order — path identifiers first, then body foreign-key fields in their
    declaration order — and rejects the request with `ERR_NOT_FOUND` at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/fk_reference_not_found_returns_404
    """
    res = api.create_fill_lot(
        {
            "tank_id": NON_EXISTENT_UUID,
            "product_code": "O2",
            "target_fill_pressure_bar": 200,
        },
        OP,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_telemetry_reading_immutable_no_version(api):
    """PRD §2.5: "One resource family is exempt from the full set: telemetry
    readings are immutable, append-only records and carry only `id` and
    `created_at`; both `updated_at` and `version` are absent from them."

    Design: Corner/entities/telemetry_reading_immutable_no_version
    """
    plant, tank = (
        create_test_plant(plant_name="P-EN6"),
        None,
    )
    tank = create_test_tank(plant["id"])
    res = api.create_telemetry_reading(
        {
            "tank_id": tank["id"],
            "measured_level_liters": 4900,
            "measured_at": "2026-08-01T00:00:00Z",
            "source": "MANUAL_DIP",
        },
        OP,
    )
    reading = validate_success(res, 201)
    assert_telemetry_reading(reading)
    fetched = validate_success(api.get_telemetry_reading(reading["id"], OP), 200)
    assert_telemetry_reading(fetched)
    assert fetched["measured_level_liters"] == 4900
    assert fetched["tank_id"] == tank["id"]


def test_tank_computed_level_input_ignored(api):
    """PRD §3.1: "Registration seeds an `INITIAL_LOAD` telemetry reading measured
    at the creation clock time with `measured_level_liters` equal to the supplied
    initial level; the tank enters `IN_SERVICE` with `reserved_liters` at zero,
    `drawn_liters` at zero, and its `low_level_flag` computed."
    PRD §3.1: "For a storage tank, `current_level_liters` is the governing
    reading's level minus `drawn_liters`, recomputed on every reading and on
    every fill or blend draw; whenever a new reading becomes the governing one,
    `drawn_liters` resets to zero, because the physical draw is now reflected in
    the measurement."

    Design: Corner/entities/tank_computed_level_input_ignored
    """
    plant = create_test_plant(plant_name="P-EN7")
    payload = {
        "plant_id": plant["id"],
        "product_code": "O2",
        "capacity_liters": 10000,
        "initial_level_liters": 5000,
        "reorder_point_liters": 500,
        "current_level_liters": 1,
    }
    tank = validate_success(api.create_tank(payload, PM), 201)
    assert tank["current_level_liters"] == pytest.approx(5000.0, abs=0.01), (
        "current level must derive from the seeded INITIAL_LOAD reading, not the "
        "client-supplied value"
    )
    assert tank["reserved_liters"] == 0
    assert tank["drawn_liters"] == 0
    assert tank["status"] == "IN_SERVICE"


def test_cylinder_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips that many items from the start of the result set and defaults
    to 0. Unless otherwise specified, every list endpoint returns resources
    sorted by `created_at` in ascending order. The `meta` object of a list
    response carries four pagination fields: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/cylinder_list_pagination_envelope
    """
    for suffix in ("A", "B", "C"):
        create_test_cylinder(serial_number=f"SN-EN8-{suffix}", service_gas="N2",
                             size_code="SMALL")

    data, meta = validate_paginated(
        api.list_cylinders(OP, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    data, meta = validate_paginated(
        api.list_cylinders(OP, params={"limit": 2, "offset": 2})
    )
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    data, meta = validate_paginated(api.list_cylinders(OP))
    assert len(data) == 3
    assert meta["limit"] == 10, "limit defaults to 10 when not supplied"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
