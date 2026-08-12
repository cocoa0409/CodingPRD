"""Queue B (breadth) — entity creation defaults, computed/system fields,
not-found and malformed-body behavior, and the append-only attic movement row.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_ffe_project, assert_spec_item, assert_attic_stock_movement,
    create_project_payload, create_spec_item_payload,
    create_project, run_pipeline, current_po_line_version,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
WR = TEST_USERS["warehouse_receiver_headers"]


def test_project_creation_defaults_and_envelope(api, purchasing_agent_headers):
    """PRD §3.1: "A new project starts in `PLANNING` status with
    `procurement_posture` `OPEN` and all aggregates — `committed_cents`,
    `actual_spend_cents`, `sunk_fees_cents` — at zero."
    PRD §3.1: "Two optional knobs complete the envelope:
    `unallocated_contingency_cents`, the contingency not yet drawn into any budget
    line, defaults to 0 and must be at least 0 and no more than
    `total_budget_cents`; and `default_crew_capacity_per_floor_day`, the maximum
    summed crew count allowed across overlapping installation windows on one floor
    per calendar day, defaults to 8 and must be at least 1."
    PRD §2.4: "`version` (integer): starts at 1 at creation and increments by one
    on every mutation, again including cascaded mutations."

    Design: Corner/entities/project_creation_defaults_and_envelope
    """
    res = api_client.create_project(
        create_project_payload(
            name="P-E1", hotel_name="Hotel A", brand_program="MARQUEE_SELECT",
            total_budget_cents=10_000_000,
        ),
        purchasing_agent_headers,
    )
    project = validate_success(res, 201)
    assert_ffe_project(project)
    assert project["status"] == "PLANNING"
    assert project["procurement_posture"] == "OPEN"
    assert project["unallocated_contingency_cents"] == 0
    assert project["default_crew_capacity_per_floor_day"] == 8
    assert project["committed_cents"] == 0
    assert project["actual_spend_cents"] == 0
    assert project["sunk_fees_cents"] == 0
    assert project["version"] == 1


def test_spec_computed_and_system_fields(api, purchasing_agent_headers):
    """PRD §3.2: "The derived `total_qty` is the product of `quantity_per_room`
    and `room_count`."
    PRD §3.2: "Procurement parameters round out the spec: `required_lead_days`,
    the latest acceptable vendor lead time before a penalty applies in bid
    evaluation, defaults to 21 and must be at least 0; `is_critical` defaults to
    false and marks a critical-path item whose attic raw target is doubled;
    `attic_target_pct`, the fraction of installed quantity targeted as attic
    spares, defaults to 0.05 and must be greater than 0 and at most 1;
    `attic_min_qty` defaults to 0; and `attic_max_qty` defaults to 9999 and must
    be at least `attic_min_qty`. A new spec starts `DRAFT` with
    `attic_target_qty` at zero."

    Design: Corner/entities/spec_computed_and_system_fields
    """
    project = create_project(
        name="P-E2", hotel_name="H", brand_program="INDIE_SOFT",
        total_budget_cents=5_000_000,
    )
    res = api_client.create_spec_item(
        create_spec_item_payload(
            project["id"], category="LIGHTING", description="Sconce",
            brand_standard_ref="IS-SC", quantity_per_room=2, room_count=20,
            unit_budget_cents=8000,
        ),
        purchasing_agent_headers,
    )
    spec = validate_success(res, 201)
    assert_spec_item(spec)
    assert spec["total_qty"] == 40
    assert spec["attic_target_qty"] == 0, (
        "with no PO line the attic target is zero"
    )
    assert spec["required_lead_days"] == 21
    assert spec["is_critical"] is False
    assert spec["attic_target_pct"] == 0.05
    assert spec["attic_min_qty"] == 0
    assert spec["attic_max_qty"] == 9999
    assert spec["status"] == "DRAFT"
    assert spec["version"] == 1


def test_project_not_found_returns_404(api, purchasing_agent_headers):
    """PRD §2.7: "the server validates existence left to right and rejects
    immediately with the 404 error corresponding to the first identifier that does
    not resolve: `ERR_PROJECT_NOT_FOUND`, `ERR_BUDGET_LINE_NOT_FOUND`"

    Design: Corner/entities/project_not_found_returns_404
    """
    res = api_client.get_project(NON_EXISTENT_UUID, purchasing_agent_headers)
    validate_error(res, ApiErrorId.ERR_PROJECT_NOT_FOUND, expected_status=404)


def test_missing_required_total_budget_returns_400(api, purchasing_agent_headers):
    """PRD §2.8: "Malformed bodies — a missing required field, a wrong type, an
    enum value outside its declared set, a non-positive quantity, an
    `unallocated_contingency_cents` exceeding `total_budget_cents`, or a missing
    `approved_credit_cents` on a credit resolution — are rejected with
    `ERR_INVALID_REQUEST` (400)."
    Omitting the required total_budget_cents rejects the create and persists no
    project.

    Design: Corner/entities/missing_required_total_budget_returns_400
    """
    res = api_client.create_project(
        {"name": "P-E4", "hotel_name": "H", "brand_program": "MARQUEE_SELECT"},
        purchasing_agent_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    projects, meta = validate_paginated(
        api_client.list_projects(purchasing_agent_headers)
    )
    assert projects == [] and meta["total_count"] == 0


def test_invalid_brand_program_enum_returns_400(api, purchasing_agent_headers):
    """PRD §2.8: "Malformed bodies — a missing required field, a wrong type, an
    enum value outside its declared set, a non-positive quantity, an
    `unallocated_contingency_cents` exceeding `total_budget_cents`, or a missing
    `approved_credit_cents` on a credit resolution — are rejected with
    `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "the `brand_program` it is flagged under — one of `MARQUEE_SELECT`,
    `MARQUEE_LUXE`, or `INDIE_SOFT`"
    NOT_A_BRAND is outside the declared set.

    Design: Corner/entities/invalid_brand_program_enum_returns_400
    """
    res = api_client.create_project(
        create_project_payload(
            name="P-E5", brand_program="NOT_A_BRAND",
            total_budget_cents=1_000_000,
        ),
        purchasing_agent_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_attic_movements_are_immutable_events(api):
    """PRD §2.4: "The one exception is the attic stock movement record, which is
    an append-only event: it carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from it, it is immutable after creation,
    and no update endpoint exists for it."
    PRD §3.8: "Each accepted movement appends an immutable attic stock movement
    row that records `resulting_installable` and `resulting_attic` — the line's
    two pools immediately after the move — and bumps the line's `version`. The
    movement history of a line is readable through its attic-movements listing."
    After one IN 1 transfer on a 50-good-unit line, the listing holds exactly the
    one movement with pools 49 / 1.

    Design: Corner/entities/attic_movements_are_immutable_events
    """
    scenario = run_pipeline(
        name="P-E6", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Dresser", "brand_standard_ref": "MS-DR",
            "quantity_per_room": 1, "room_count": 50,
            "unit_budget_cents": 10000, "unit_price_cents": 10000,
            "lead_time_days": 7,
            "quantity_ordered": 50, "declared_cube_m3": 10,
            "spec_overrides": {"attic_min_qty": 5, "attic_max_qty": 40},
        }],
        receipts=[[(0, 50, 0)]],
    )
    line_id = scenario["lines"][0]["id"]

    movement = validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "IN", "quantity": 1,
             "expected_po_line_version": current_po_line_version(line_id)},
            WR,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api_client.list_po_line_attic_movements(line_id, WR)
    )
    assert meta["total_count"] == 1 and len(rows) == 1
    row = rows[0]
    assert row["id"] == movement["id"]
    assert_attic_stock_movement(row)
    assert row["direction"] == "IN"
    assert row["quantity"] == 1
    assert row["resulting_installable"] == 49
    assert row["resulting_attic"] == 1
