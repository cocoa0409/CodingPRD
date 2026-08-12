"""Queue B (breadth) — role-based access denials, the authentication-before-
existence pipeline order, project-scoped uniqueness, and cross-project
referential integrity.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_project, add_budget_line, create_spec, submit_spec,
    create_approved_spec, create_bid, sample_decide, award,
    propose_change_order, current_project_version,
    create_procurement_project, create_po, add_po_line, create_room,
    advance_po_to_ready_to_ship, create_shipment, transition_shipment,
    attach_po_to_shipment, create_receiving_event_payload,
    create_awarded_spec, create_po_with_lines,
    create_project_payload, create_spec_item_payload,
    create_window,
    TEST_USERS,
    make_purchasing_agent_headers,
)

PA = TEST_USERS["purchasing_agent_headers"]
VEN = TEST_USERS["vendor_headers"]
IM = TEST_USERS["installation_manager_headers"]
PA_1 = make_purchasing_agent_headers("pa-1")


def test_rbac_role_denials(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint — or for
    the specific transition target on a shared transition endpoint — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); for example, a `Vendor` attempting an
    award, a `PurchasingAgent` attempting a brand review or a change-order
    decision, or a `Vendor` attempting to resolve a claim."
    PRD §4: the endpoint table lists `PurchasingAgent` as the only authorized role
    for creating projects and spec items, and `BrandApprover` for brand review.
    Four wrong-role calls are each rejected 403 and mutate nothing.

    Design: Corner/roles/rbac_role_denials
    """
    project = create_project(
        name="P-B1", hotel_name="H", brand_program="MARQUEE_SELECT",
        total_budget_cents=5_000_000, unallocated_contingency_cents=100000,
    )
    budget_line = add_budget_line(project["id"], "FURNITURE", 1_000_000)
    spec = create_spec(
        project["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000,
    )
    submit_spec(spec["id"])
    change_order = propose_change_order(
        project["id"],
        [{"budget_line_id": budget_line["id"], "delta_cents": 10000}],
        title="CO rbac", proposer_headers=PA_1,
    )
    version = current_project_version(project["id"])

    res = api_client.create_project(
        create_project_payload(name="P-BAD", total_budget_cents=1000), VEN
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    res = api_client.brand_review_spec_item(
        spec["id"], {"decision": "APPROVE"}, PA
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    res = api_client.create_spec_item(
        create_spec_item_payload(
            project["id"], category="DECOR", description="Art",
            brand_standard_ref="X", quantity_per_room=1, room_count=1,
            unit_budget_cents=100,
        ),
        VEN,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    res = api_client.apply_change_order(
        change_order["id"], {"expected_project_version": version}, PA
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    spec_after = validate_success(api_client.get_spec_item(spec["id"], PA))
    assert spec_after["status"] == "SUBMITTED"
    co_after = validate_success(api_client.get_change_order(change_order["id"], PA))
    assert co_after["status"] == "PROPOSED"


def test_missing_auth_header_beats_not_found(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside
    these six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."
    PRD §2.8: "Every write request passes through a fixed, prioritized validation
    cascade; a failure at an earlier stage masks all later stages."
    With no auth headers, a nonexistent spec id fails authentication before
    existence; with a valid role the same id resolves to the spec-specific 404.

    Design: Corner/validations/missing_auth_header_beats_not_found
    """
    res = api_client.brand_review_spec_item(
        NON_EXISTENT_UUID, {"decision": "APPROVE"}, headers={}
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        expected_status=400,
    )

    res = api_client.brand_review_spec_item(
        NON_EXISTENT_UUID, {"decision": "APPROVE"},
        TEST_USERS["brand_approver_headers"],
    )
    validate_error(res, ApiErrorId.ERR_SPEC_ITEM_NOT_FOUND, expected_status=404)


def test_duplicate_category_and_room_uniqueness(api):
    """PRD §3.1: "The category is unique per project: a second line in the same
    category is rejected with `ERR_DUPLICATE_BUDGET_CATEGORY`."
    PRD §3.7: "An `InstallationManager` registers each room with its `project_id`,
    the `floor_number` it sits on (at least 1), a `room_number` unique within the
    project — a duplicate is rejected with `ERR_DUPLICATE_ROOM` — and a
    `room_type` of `GUEST_KING`, `GUEST_DOUBLE`, `SUITE`, `CORRIDOR`, or `LOBBY`."
    Both uniqueness rules are project-scoped: the same room number on a different
    project is allowed.

    Design: Corner/errors/duplicate_category_and_room_uniqueness
    """
    p1 = create_project(name="P-R1a", hotel_name="H",
                        brand_program="MARQUEE_SELECT",
                        total_budget_cents=5_000_000)
    p2 = create_project(name="P-R1b", hotel_name="H",
                        brand_program="MARQUEE_SELECT",
                        total_budget_cents=5_000_000)
    add_budget_line(p1["id"], "FURNITURE", 1_000_000)
    create_room(p1["id"], floor_number=1, room_number="R-1", room_type="SUITE")

    res = api_client.create_budget_line(
        {"project_id": p1["id"], "category": "FURNITURE",
         "budgeted_cents": 500000},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BUDGET_CATEGORY,
                   expected_status=409)

    res = api_client.create_room(
        {"project_id": p1["id"], "floor_number": 2, "room_number": "R-1",
         "room_type": "SUITE"},
        IM,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ROOM, expected_status=409)

    created = validate_success(
        api_client.create_room(
            {"project_id": p2["id"], "floor_number": 2, "room_number": "R-1",
             "room_type": "SUITE"},
            IM,
        ),
        201,
    )
    assert created["project_id"] == p2["id"]


def test_cross_project_attach_and_foreign_line_receipt(api):
    """PRD §3.5: "a purchase order named by `purchase_order_id` may be attached
    while the shipment is `CONSOLIDATING` — checked first, else
    `ERR_SHIPMENT_NOT_CONSOLIDATING` — and while the PO itself is `READY_TO_SHIP`
    — checked second, else `ERR_PO_NOT_READY_TO_SHIP`; the two must belong to the
    same project, else `ERR_CROSS_PROJECT_REFERENCE`."
    PRD §3.5: "The shipment must be `IN_TRANSIT` at creation, else
    `ERR_SHIPMENT_NOT_IN_TRANSIT`, and every entry's line must belong to a PO
    attached to that shipment, else `ERR_LINE_NOT_ON_SHIPMENT`."
    Project A's PO cannot attach to project B's shipment, and a receiving event
    may not name a line whose PO was never attached to the event's shipment.

    Design: Corner/errors/cross_project_attach_and_foreign_line_receipt
    """
    p1 = create_procurement_project(
        name="P-R2a", total_budget_cents=10_000_000, budgeted_cents=8_000_000,
    )["project"]
    spec_1, _bid_1 = create_awarded_spec(
        p1["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000, unit_price_cents=15000, lead_time_days=14,
    )
    po_1, lines_1 = create_po_with_lines(
        p1["id"], [{"spec": spec_1, "quantity_ordered": 40,
                    "declared_cube_m3": 10}],
    )
    advance_po_to_ready_to_ship(po_1["id"])

    p2 = create_project(name="P-R2b", hotel_name="H",
                        brand_program="MARQUEE_SELECT",
                        total_budget_cents=5_000_000)
    shipment_2 = create_shipment(p2["id"], "CARR-P2")
    transition_shipment(shipment_2["id"], "CONSOLIDATING")

    res = api_client.attach_purchase_order(
        shipment_2["id"], {"purchase_order_id": po_1["id"]}, PA
    )
    validate_error(res, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE,
                   expected_status=409)

    # Back in P1: attach properly, seal, depart; a second PO's line is never
    # attached to the shipment.
    shipment_1 = create_shipment(p1["id"], "CARR-P1")
    transition_shipment(shipment_1["id"], "CONSOLIDATING")
    attach_po_to_shipment(shipment_1["id"], po_1["id"])

    spec_2, _bid_2 = create_awarded_spec(
        p1["id"], category="FURNITURE", description="Coat hook",
        brand_standard_ref="MS-CH", quantity_per_room=1, room_count=1,
        unit_budget_cents=1000, unit_price_cents=1000, lead_time_days=3,
    )
    _po_2, lines_2 = create_po_with_lines(
        p1["id"], [{"spec": spec_2, "quantity_ordered": 1,
                    "declared_cube_m3": 1}],
    )

    transition_shipment(shipment_1["id"], "SEALED")
    transition_shipment(shipment_1["id"], "IN_TRANSIT")

    res = api_client.create_receiving_event(
        create_receiving_event_payload(
            shipment_1["id"],
            [{"po_line_id": lines_2[0]["id"], "qty_received": 1,
              "qty_damaged": 0}],
        ),
        TEST_USERS["warehouse_receiver_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LINE_NOT_ON_SHIPMENT,
                   expected_status=409)

    events, meta = validate_paginated(
        api_client.list_shipment_receiving_events(shipment_1["id"], PA)
    )
    assert events == [] and meta["total_count"] == 0, (
        "the rejected receiving event must not be persisted"
    )


def test_window_invalid_dates_returns_422(api, installation_manager_headers):
    """PRD §3.7: "Installation windows are planned per floor: `project_id`,
    `floor_number` (at least 1), a `start_date` and an `end_date` as ISO 8601
    dates forming a **half-open interval** — the `end_date` is the day after the
    last work day — and a `crew_count` (at least 1), the crews booked per calendar
    day of the window. The `end_date` must be strictly after the `start_date`;
    otherwise creation fails with `ERR_INVALID_WINDOW_DATES` (422)."
    An empty half-open interval (end_date == start_date) creates no window.

    Design: Corner/errors/window_invalid_dates_returns_422
    """
    project = create_project(name="P-R5", hotel_name="H",
                             brand_program="MARQUEE_SELECT",
                             total_budget_cents=5_000_000)
    res = api_client.create_installation_window(
        {"project_id": project["id"], "floor_number": 1,
         "start_date": "2026-07-01", "end_date": "2026-07-01",
         "crew_count": 1},
        installation_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW_DATES,
                   expected_status=422)

    windows, meta = validate_paginated(
        api_client.list_project_installation_windows(project["id"], PA)
    )
    assert windows == [] and meta["total_count"] == 0
