"""Virgin sheet intake, lot certification, and certificate time rules (PRD §3.1, §2.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_material_lot,
    assert_material_allocation,
    create_cleanliness_certificate_payload,
    create_material_allocation_payload,
    create_material_lot_payload,
    create_order,
    create_certified_lot,
    create_lot,
    create_stock_spec,
    create_tool_payload,
    create_tool_prototype,
    get_allocation,
    get_lot,
    get_success_data,
    is_valid_uuid,
    issue_certificate,
    reserve_virgin,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["materials_planner_headers"]
_INSPECTOR = TEST_USERS["quality_inspector_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]
_ANY = TEST_USERS["any_headers"]


def test_lot_create_applies_computed_defaults(api):
    """PRD §3.1: "A new lot enters `QUARANTINE` with `allocated_kg` and
    `consumed_kg` both at zero."
    PRD §3.1: "`available_kg` is always exactly `quantity_kg` minus
    `allocated_kg` minus `consumed_kg`."

    Design: Corner/entities/lot_create_applies_computed_defaults
    """
    payload = create_material_lot_payload(
        lot_code="L-D1",
        resin_type="PETG",
        gauge_mm=1.500,
        cleanliness_grade_required="FOOD",
        quantity_kg=12.500,
        unit_cost_per_kg=11.25,
    )
    lot = validate_success(api.create_material_lot(payload, _PLANNER), 201)
    assert_material_lot(lot)
    assert lot["status"] == "QUARANTINE", f"new lot must enter QUARANTINE, got {lot['status']}"
    assert lot["allocated_kg"] == 0, f"allocated_kg must start at zero, got {lot['allocated_kg']}"
    assert lot["consumed_kg"] == 0, f"consumed_kg must start at zero, got {lot['consumed_kg']}"
    assert lot["available_kg"] == 12.500, (
        f"available_kg must equal quantity_kg on a fresh lot, got {lot['available_kg']}"
    )


def test_create_lot_ignores_client_supplied_system_fields(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix."

    Client-supplied system fields are ignored: the returned id is a
    server-minted UUID, not the client-supplied string, and the returned
    version is the server-managed integer, not the client-supplied 99.

    Design: Corner/entities/create_lot_ignores_client_supplied_version_input_ignored
    """
    payload = create_material_lot_payload(
        lot_code="L-D4",
        resin_type="ABS",
        gauge_mm=2.000,
        cleanliness_grade_required="INDUSTRIAL",
        quantity_kg=5.000,
        unit_cost_per_kg=8.00,
    )
    payload["id"] = "client-supplied-id"
    payload["version"] = 99
    lot = validate_success(api.create_material_lot(payload, _PLANNER), 201)
    assert_material_lot(lot)
    assert lot["id"] != "client-supplied-id", "server must mint its own id"
    assert is_valid_uuid(lot["id"]), f"id must be a server-minted UUID, got {lot['id']!r}"
    assert lot["version"] != 99, "client-supplied version must be ignored"


def test_tools_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/tools_list_pagination_envelope
    """
    get_success_data(api.create_tool(
        create_tool_payload(tool_code="T-D5A", part_number="P-D5A"),
        TEST_USERS["tooling_engineer_headers"],
    ))
    get_success_data(api.create_tool(
        create_tool_payload(
            tool_code="T-D5B", part_number="P-D5B", tool_type="TRIM_FIXTURE",
            min_gauge_mm=0.500, max_gauge_mm=2.000, cleanliness_grade="FOOD",
            prototype_cost=800.00,
        ),
        TEST_USERS["tooling_engineer_headers"],
    ))

    data, meta = validate_paginated(api.list_tools(_ANY, params={"limit": 1}))
    assert len(data) == 1, f"limit=1 must return exactly one row, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when a second row exists"
    assert meta["limit"] == 1 and meta["offset"] == 0


def test_certificate_inverted_window_returns_invalid_request(api):
    """PRD §2.9: "Range rules require `spec_min_wall_mm` no greater than
    `spec_nominal_wall_mm`, `expires_at` later than `issued_at`, `planned_end`
    later than `planned_start`, `scheduled_end` later than `scheduled_start`,
    and `max_gauge_mm` no less than `min_gauge_mm`."

    Design: Corner/entities/certificate_inverted_window_returns_invalid_request
    """
    lot = create_lot(lot_code="L-D6", quantity_kg=5.000, unit_cost_per_kg=8.00)
    payload = create_cleanliness_certificate_payload(
        "MATERIAL_LOT", lot["id"],
        grade="INDUSTRIAL",
        issued_at="2026-06-01T00:00:00Z",
        expires_at="2026-05-01T00:00:00Z",
    )
    res = api.create_cleanliness_certificate(payload, _INSPECTOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_certificate_expiry_half_open_boundary(api):
    """PRD §2.5: "A certificate is valid at logical time T when T falls in the
    half-open interval from `issued_at` (inclusive) to `expires_at` (exclusive):
    it becomes valid exactly at its issuance instant and is already invalid at
    exactly its expiry instant."
    PRD §3.5: "a cleanliness certificate must exist for the lot at a grade at
    least the order's grade regardless of its expiry (a rank failure is
    `ERR_GRADE_INCOMPATIBLE`) and that certificate must be currently valid at
    the logical time (otherwise `ERR_CERTIFICATE_INVALID`)"

    Design: Corner/calculations/certificate_expiry_half_open_boundary
    """
    lot = create_lot(lot_code="L-C1", quantity_kg=10.000, unit_cost_per_kg=10.00)
    issue_certificate(
        "MATERIAL_LOT", lot["id"], "INDUSTRIAL",
        issued_at="2026-04-01T00:00:00Z", expires_at="2026-06-01T00:00:00Z",
    )
    assert get_lot(lot["id"])["status"] == "CERTIFIED"
    tool = create_tool_prototype(tool_code="T-C1", part_number="P-C1")
    spec = create_stock_spec(spec_code="S-C1")
    order = create_order(tool, spec, order_code="O-C1", ordered_qty=50)

    # One second before expiry the certificate is still valid.
    set_logical_clock("2026-05-31T23:59:59Z")
    res_ok = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    alloc = validate_success(res_ok, 201)
    assert_material_allocation(alloc)
    assert alloc["status"] == "RESERVED"

    # At exactly expires_at the certificate is already invalid.
    set_logical_clock("2026-06-01T00:00:00Z")
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_CERTIFICATE_INVALID)


def test_lot_block_cascades_allocations_to_review(api):
    """PRD §3.1: "A `MaterialsPlanner` may block a lot after a contamination
    event; blocking requires the lot to be `CERTIFIED` — from any other status
    the attempt is rejected with `ERR_INVALID_LOT_STATE` — and it cascades:
    every allocation of that lot currently `RESERVED` flips to `REVIEW`, and
    the lot's `version` advances."

    Design: Corner/state_machines/lot_block_cascades_allocations_to_review
    """
    lot = create_certified_lot(lot_code="L-S6")
    tool = create_tool_prototype(tool_code="T-S6", part_number="P-S6")
    spec = create_stock_spec(spec_code="S-S6")
    order = create_order(tool, spec, order_code="O-S6", ordered_qty=50)
    alloc = reserve_virgin(order["id"], lot["id"], 2.000)
    assert alloc["status"] == "RESERVED"

    blocked = validate_success(api.block_material_lot(lot["id"], _PLANNER), 200)
    assert blocked["status"] == "BLOCKED", f"block must move lot to BLOCKED, got {blocked['status']}"

    alloc_after = get_allocation(alloc["id"])
    assert alloc_after["status"] == "REVIEW", (
        f"blocking the lot must flip its RESERVED allocation to REVIEW, got {alloc_after['status']}"
    )
