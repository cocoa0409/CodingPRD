"""Queue B (breadth) — attic stock: the computed target with its clamps, the
transfer gates (pool sufficiency before the target cap), and OCC on the line
version.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    run_pipeline, get_spec, get_po_line, current_po_line_version,
    setup_received_pipeline_with_window,
    advance_po_to_ready_to_ship, create_consolidating_shipment_with_po,
    transition_shipment, create_and_post_receiving_event,
    TEST_USERS,
)

WR = TEST_USERS["warehouse_receiver_headers"]


def test_attic_target_clamps_and_transfer_gate(api):
    """PRD §3.7: "Otherwise, the raw target is the spec's `attic_target_pct`
    multiplied by the line's `qty_installed`, doubled when the spec's
    `is_critical` flag is true, and rounded up to a whole unit; the target is then
    clamped — raised to `attic_min_qty` when the raw value falls below it, and
    capped at `attic_max_qty` when it exceeds it."
    PRD §3.8: "then — only after pool sufficiency passes — the resulting
    `qty_attic` must not exceed the spec's `attic_target_qty`, else
    `ERR_ATTIC_TARGET_EXCEEDED` (422), with equality against the target allowed."
    Critical spec, 30 installed, pct 0.05, min 2, max 10: raw =
    ceil(30 x 0.05 x 2) = 3 within the clamps; an IN of 4 breaches the target
    while 3 lands exactly on it.

    Design: Corner/calculations/attic_target_clamps_and_transfer_gate
    """
    scenario = setup_received_pipeline_with_window(
        line_qty=50, line_unit_price=10000, cube=10, received=50,
        spec_overrides={
            "is_critical": True, "attic_target_pct": 0.05,
            "attic_min_qty": 2, "attic_max_qty": 10,
        },
        floor_number=5, room_number="R-501", room_type="GUEST_KING",
        start_date="2026-07-06", end_date="2026-07-09", crew_count=1,
        task_quantities=(30,), start_window=True, complete_tasks=True,
    )
    line_id = scenario["lines"][0]["id"]

    spec = get_spec(scenario["specs"][0]["id"])
    assert spec["attic_target_qty"] == 3, (
        f"raw ceil(30 x 0.05 x 2) = 3 within clamps 2..10; got "
        f"{spec['attic_target_qty']}"
    )

    res = api_client.create_attic_transfer(
        line_id,
        {"direction": "IN", "quantity": 4,
         "expected_po_line_version": current_po_line_version(line_id)},
        WR,
    )
    validate_error(res, ApiErrorId.ERR_ATTIC_TARGET_EXCEEDED,
                   expected_status=422)

    movement = validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "IN", "quantity": 3,
             "expected_po_line_version": current_po_line_version(line_id)},
            WR,
        ),
        201,
    )
    assert movement["resulting_attic"] == 3

    line = get_po_line(line_id)
    assert line["qty_installable"] == 17
    assert line["qty_attic"] == 3
    assert line["qty_installed"] == 30


def test_attic_pool_guards(api):
    """PRD §3.8: "For `IN`, the quantity must not exceed the line's
    `qty_installable`, else `ERR_INSUFFICIENT_INSTALLABLE` (422); then — only
    after pool sufficiency passes — the resulting `qty_attic` must not exceed the
    spec's `attic_target_qty`, else `ERR_ATTIC_TARGET_EXCEEDED` (422), with
    equality against the target allowed. For `OUT` and `WRITE_OFF`, the quantity
    must not exceed the line's `qty_attic`, else `ERR_INSUFFICIENT_ATTIC` (422)."
    With installable 5 / attic 0 and a target cap of 10 that never interferes:
    IN 6 fails on the pool, IN 2 succeeds, OUT 3 fails on the attic pool.

    Design: Corner/errors/attic_pool_guards
    """
    scenario = run_pipeline(
        name="P-R9", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Dresser", "brand_standard_ref": "MS-DR",
            "quantity_per_room": 1, "room_count": 5,
            "unit_budget_cents": 10000, "unit_price_cents": 10000,
            "lead_time_days": 7,
            "quantity_ordered": 5, "declared_cube_m3": 3,
            "spec_overrides": {"attic_min_qty": 10, "attic_max_qty": 40},
        }],
        receipts=[[(0, 5, 0)]],
    )
    line_id = scenario["lines"][0]["id"]

    res = api_client.create_attic_transfer(
        line_id,
        {"direction": "IN", "quantity": 6,
         "expected_po_line_version": current_po_line_version(line_id)},
        WR,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INSTALLABLE,
                   expected_status=422)

    movement = validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "IN", "quantity": 2,
             "expected_po_line_version": current_po_line_version(line_id)},
            WR,
        ),
        201,
    )
    assert movement["resulting_attic"] == 2
    assert movement["resulting_installable"] == 3

    res = api_client.create_attic_transfer(
        line_id,
        {"direction": "OUT", "quantity": 3,
         "expected_po_line_version": current_po_line_version(line_id)},
        WR,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_ATTIC, expected_status=422)

    line = get_po_line(line_id)
    assert line["qty_attic"] == 2
    assert line["qty_installable"] == 3


def test_occ_stale_line_version_on_attic_transfer(api):
    """PRD §2.6: "Second, recording an attic stock movement against a PO line
    requires the request body to carry `expected_po_line_version`, a non-optional
    field holding the line `version` the requester last observed. Receiving posts
    and installation-task completions silently change the line's pools and bump
    its version, so a transfer computed from a stale pool view must not apply
    blindly. If `expected_po_line_version` does not equal the line's current
    `version`, the transfer is rejected with `ERR_STALE_PO_LINE_VERSION` (HTTP
    412). No other endpoint takes a version field."
    The version read at line creation is stale once seal and the receiving post
    each advance it; the same transfer succeeds after a fresh read.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_line_version_on_attic_transfer
    """
    scenario = run_pipeline(
        name="P-X2", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Dresser", "brand_standard_ref": "MS-DR",
            "quantity_per_room": 1, "room_count": 50,
            "unit_budget_cents": 10000, "unit_price_cents": 10000,
            "lead_time_days": 7,
            "quantity_ordered": 50, "declared_cube_m3": 10,
            "spec_overrides": {"attic_min_qty": 10, "attic_max_qty": 40},
        }],
        attach=False, seal=False, depart=False,
    )
    line_id = scenario["lines"][0]["id"]
    stale_version = scenario["lines"][0]["version"]

    # Seal and receipt each advance the line version after the read.
    advance_po_to_ready_to_ship(scenario["po"]["id"])
    shipment = create_consolidating_shipment_with_po(
        scenario["project"]["id"], scenario["po"]["id"], "CARR"
    )
    transition_shipment(shipment["id"], "SEALED")
    transition_shipment(shipment["id"], "IN_TRANSIT")
    create_and_post_receiving_event(
        shipment["id"],
        [{"po_line_id": line_id, "qty_received": 50, "qty_damaged": 0}],
    )

    res = api_client.create_attic_transfer(
        line_id,
        {"direction": "IN", "quantity": 5,
         "expected_po_line_version": stale_version},
        WR,
    )
    validate_error(res, ApiErrorId.ERR_STALE_PO_LINE_VERSION,
                   expected_status=412)

    fresh_version = current_po_line_version(line_id)
    assert fresh_version > stale_version

    movement = validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "IN", "quantity": 5,
             "expected_po_line_version": fresh_version},
            WR,
        ),
        201,
    )
    assert movement["resulting_attic"] == 5
    assert movement["resulting_installable"] == 45

    rows, meta = validate_paginated(
        api_client.list_po_line_attic_movements(line_id, WR)
    )
    assert meta["total_count"] == 1, (
        "the rejected stale transfer must not persist a movement row"
    )
