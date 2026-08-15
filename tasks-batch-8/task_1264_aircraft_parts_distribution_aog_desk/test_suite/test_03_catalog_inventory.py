"""Catalog registration and serialized inventory rules."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_part, create_unit,
    create_part_payload, create_inventory_unit_payload, TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_part_rotable_core_value_coupling(api):
    """PRD §3.2: "Rotables must declare a positive `core_value_cents` deposit;
    for non-rotables the core value must be exactly zero, which is also its
    default when omitted."
    PRD §2.11: "Malformed payloads — a missing required field, an invalid enum
    value, a non-positive quantity, a malformed timestamp, or a forbidden field
    combination — are rejected with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/part_rotable_core_value_coupling
    """
    res1 = api.create_part(
        create_part_payload(
            part_number="PN-BAD1", rotable=True, list_price_cents=1000,
            core_value_cents=0,
        ),
        WAREHOUSE,
    )
    validate_error(res1, "ERR_INVALID_REQUEST", expected_status=400)

    res2 = api.create_part(
        create_part_payload(
            part_number="PN-BAD2", rotable=False, list_price_cents=1000,
            core_value_cents=500,
        ),
        WAREHOUSE,
    )
    validate_error(res2, "ERR_INVALID_REQUEST", expected_status=400)


def test_unit_serial_unique_per_part_only(api):
    """PRD §3.2: "Serialized stock arrives as InventoryUnit records carrying
    the parent `part_id`, a `serial_number` unique within that part (a
    duplicate is refused with `ERR_DUPLICATE_SERIAL`)".

    Design: Corner/entities/unit_serial_unique_per_part_only
    """
    p1 = create_part(part_number="PN-S1")
    p2 = create_part(part_number="PN-S2")
    validate_success(
        api.create_inventory_unit(
            create_inventory_unit_payload(p1["id"], serial_number="SN-SHARED"),
            WAREHOUSE,
        ),
        201,
    )

    dup = api.create_inventory_unit(
        create_inventory_unit_payload(p1["id"], serial_number="SN-SHARED"),
        WAREHOUSE,
    )
    validate_error(dup, "ERR_DUPLICATE_SERIAL", expected_status=409)

    cross = validate_success(
        api.create_inventory_unit(
            create_inventory_unit_payload(p2["id"], serial_number="SN-SHARED"),
            WAREHOUSE,
        ),
        201,
    )
    assert cross["part_id"] == p2["id"]


def test_unit_trace_downgrade_rejected(api):
    """PRD §3.2: "the new level must rank at or above the current rank per
    §2.7 — a downgrade is rejected with `ERR_INVALID_REQUEST` — and a
    successful certification increments the unit's `version` by 1."

    Design: Corner/entities/unit_trace_downgrade_rejected
    """
    part = create_part(part_number="PN-TD")
    unit = create_unit(part["id"], serial_number="SN-TD1",
                       trace_doc_level="DUAL_RELEASE")
    res = api.certify_trace(unit["id"], {"trace_doc_level": "FAA_8130"}, COMPLIANCE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    after = validate_success(api.get_inventory_unit(unit["id"], WAREHOUSE))
    assert after["trace_doc_level"] == "DUAL_RELEASE"


def test_inventory_units_filtered_list_and_pagination_shape(api):
    """PRD §3.2: "The inventory collection pages with `limit` and `offset` and
    filters by `part_id`, `status`, `condition`, and `reserved_by_request_id`."
    PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/inventory_units_filtered_list_and_pagination_shape
    """
    p1 = create_part(part_number="PN-F1")
    p2 = create_part(part_number="PN-F2")
    create_unit(p1["id"], serial_number="SN-F1")
    create_unit(p1["id"], serial_number="SN-F2")
    create_unit(p2["id"], serial_number="SN-F3")

    data, meta = validate_paginated(
        api.list_inventory_units(
            WAREHOUSE, params={"part_id": p1["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(data) == 1
    assert all(row["part_id"] == p1["id"] for row in data)
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
