"""Fleet registry: bus creation defaults, reads, pagination, retirement guards."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_bus,
    bus_version,
    create_bus_payload,
    create_work_order_payload,
    get_success_data,
    new_bus,
    new_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_bus_create_applies_defaults_and_system_fields(api, fleet_manager_headers):
    """PRD §3.1: "At registration the bus's `odometer_miles` is seeded from
    `initial_odometer_miles`, its `service_status` is set to `ACTIVE`, its
    `availability_status` to `AVAILABLE`, its `last_overhaul_miles` to 0, its
    `last_pm_a_miles`, `last_pm_b_miles`, and `last_pm_c_miles` to 0, and
    `last_pm_a_date`, `last_pm_b_date`, and `last_pm_c_date` to `in_service_date`."
    PRD §2.4: "**`version`** (integer): a system-managed integer starting at 1
    and incremented on every mutation."

    Design: Corner/entities/bus_create_applies_defaults_and_system_fields
    """
    payload = create_bus_payload(
        fleet_number="D1", vin="VIND1", initial_odometer_miles=12_345
    )
    bus = validate_success(api.create_bus(payload, fleet_manager_headers), 201)
    assert_bus(bus)
    assert bus["version"] == 1, f"new bus version must be 1, got {bus['version']}"
    assert bus["service_status"] == "ACTIVE"
    assert bus["availability_status"] == "AVAILABLE"
    assert bus["odometer_miles"] == 12_345
    assert bus["hold_reasons"] == [], f"new bus must have no holds: {bus['hold_reasons']}"
    assert bus["last_overhaul_miles"] == 0
    assert bus["last_pm_a_miles"] == 0
    assert bus["last_pm_a_date"] == payload["in_service_date"]


def test_bus_get_nonexistent_id_not_found(api, fleet_manager_headers):
    """PRD §2.11: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
    the first identifier that does not resolve to an existing resource, before
    any later identifier is consulted."

    Design: Corner/entities/bus_get_nonexistent_id_not_found
    """
    res = api.get_bus(NON_EXISTENT_UUID, fleet_manager_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_bus_list_pagination_defaults(api, fleet_manager_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10, has a minimum of 1, and has a maximum of 100.
    The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "Every paginated list response includes the fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    response envelope."

    Design: Corner/entities/bus_list_pagination_defaults
    """
    for i in range(12):
        new_bus(fleet_number=f"L{i + 1:02d}", vin=f"VINL{i + 1:02d}",
                initial_odometer_miles=0)

    page1, meta1 = validate_paginated(api.list_buses(fleet_manager_headers))
    assert len(page1) == 10, f"default page must hold 10 items, got {len(page1)}"
    assert meta1["limit"] == 10 and meta1["offset"] == 0
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_buses(fleet_manager_headers, params={"limit": 5, "offset": 10})
    )
    assert len(page2) == 2, f"last page must hold the final 2 buses, got {len(page2)}"
    assert meta2["has_more"] is False


def test_retire_with_open_work_order_rejected(api, fleet_manager_headers):
    """PRD §3.1: "Retirement is blocked while any work order for the bus is in
    a non-terminal state (`ERR_OPEN_WORK_ORDERS_EXIST`)."

    Design: Corner/validations/retire_with_open_work_order_rejected
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    new_work_order(bus["id"])

    res = api.retire_bus(bus["id"], {"retirement_reason": "age"}, fleet_manager_headers)
    validate_error(res, ApiErrorId.ERR_OPEN_WORK_ORDERS_EXIST)
    after = get_success_data(api.get_bus(bus["id"], fleet_manager_headers))
    assert after["service_status"] == "ACTIVE", "bus must remain ACTIVE after rejection"


def test_work_order_create_on_retired_bus_rejected(api, fleet_manager_headers):
    """PRD §3.3: "The referenced bus must not be `RETIRED` (`ERR_BUS_RETIRED`)."

    The OCC version presented is fresh, so the rejection is the business gate,
    not a stale-version artifact.

    Design: Corner/validations/work_order_create_on_retired_bus_rejected
    """
    bus = new_bus(model_year=2010, in_service_date="2012-01-01",
                  initial_odometer_miles=400_000,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2013-01-01")
    validate_success(
        api.retire_bus(bus["id"], {"retirement_reason": "end of life"},
                       fleet_manager_headers)
    )
    fresh_version = bus_version(bus["id"])
    bus_after = get_success_data(api.get_bus(bus["id"], fleet_manager_headers))
    assert bus_after["service_status"] == "RETIRED"

    payload = create_work_order_payload(bus["id"], fresh_version)
    res = api.create_work_order(payload, fx.SUP)
    validate_error(res, ApiErrorId.ERR_BUS_RETIRED)
