"""Queue B (breadth) — list-endpoint pagination envelope, FK reverse-lookup
listings, and the 404 error-id matrix across every resource family.
"""
from test_helpers import (
    api_client, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_project, run_pipeline, create_claim,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]


def test_pagination_limit_offset(api, purchasing_agent_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter skips a number of items from the front of the result set
    and defaults to 0."
    PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."
    Three projects paged two-at-a-time: page 1 has two rows and more to come;
    page 2 has the last row and no more.

    Design: Corner/endpoints/pagination_limit_offset
    """
    for name in ("P-N2A", "P-N2B", "P-N2C"):
        create_project(name=name, hotel_name="H", brand_program="INDIE_SOFT",
                       total_budget_cents=1_000_000)

    page_1, meta_1 = validate_paginated(
        api_client.list_projects(
            purchasing_agent_headers, params={"limit": 2, "offset": 0}
        )
    )
    assert len(page_1) == 2
    assert meta_1["total_count"] == 3
    assert meta_1["has_more"] is True

    page_2, meta_2 = validate_paginated(
        api_client.list_projects(
            purchasing_agent_headers, params={"limit": 2, "offset": 2}
        )
    )
    assert len(page_2) == 1
    assert meta_2["total_count"] == 3
    assert meta_2["has_more"] is False


def test_fk_reverse_lists(api):
    """PRD §4: the endpoint table provides "List bids for a spec", "List purchase
    orders of a project", and "List damage/shortage claims of a line" as reverse
    lookups keyed by the parent id.
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources
    sorted by `created_at` in ascending order."
    Each reverse-lookup list returns exactly the children created against the
    parent id.

    Design: Corner/endpoints/fk_reverse_lists
    """
    scenario = run_pipeline(
        name="P-N3", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
        }],
        receipts=[[(0, 40, 2)]],
    )
    spec = scenario["specs"][0]
    bid = scenario["bids"][0]
    po = scenario["po"]
    line = scenario["lines"][0]
    claim = create_claim(line["id"], claim_type="DAMAGE", quantity=1,
                         claimed_credit_cents=10000)

    bids, meta = validate_paginated(
        api_client.list_spec_item_bids(spec["id"], PA)
    )
    assert meta["total_count"] == 1
    assert [b["id"] for b in bids] == [bid["id"]]

    pos, meta = validate_paginated(
        api_client.list_project_purchase_orders(scenario["project"]["id"], PA)
    )
    assert meta["total_count"] == 1
    assert [p["id"] for p in pos] == [po["id"]]

    claims, meta = validate_paginated(
        api_client.list_po_line_damage_claims(line["id"], PA)
    )
    assert meta["total_count"] == 1
    assert [c["id"] for c in claims] == [claim["id"]]
    assert claims[0]["status"] == "OPEN"


def test_not_found_matrix(api, purchasing_agent_headers):
    """PRD §2.7: "For any endpoint whose path contains resource identifiers — path
    parameters such as `projectId`, `budgetLineId`, `specItemId`, `bidId`,
    `purchaseOrderId`, `poLineId`, `shipmentId`, `receivingEventId`,
    `damageClaimId`, `roomId`, `installationWindowId`, `installationTaskId`,
    `changeOrderId`, or a bare `id` — the server validates existence left to right
    and rejects immediately with the 404 error corresponding to the first
    identifier that does not resolve: `ERR_PROJECT_NOT_FOUND`,
    `ERR_BUDGET_LINE_NOT_FOUND`, `ERR_SPEC_ITEM_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
    `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_PO_LINE_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_RECEIVING_EVENT_NOT_FOUND`,
    `ERR_DAMAGE_CLAIM_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
    `ERR_INSTALLATION_WINDOW_NOT_FOUND`, `ERR_INSTALLATION_TASK_NOT_FOUND`, or
    `ERR_CHANGE_ORDER_NOT_FOUND`."
    Every resource family resolves a well-formed but nonexistent id to its own
    404 error id.

    Design: Corner/errors/not_found_matrix
    """
    h = purchasing_agent_headers
    cases = [
        (api_client.get_budget_line, ApiErrorId.ERR_BUDGET_LINE_NOT_FOUND),
        (api_client.get_spec_item, ApiErrorId.ERR_SPEC_ITEM_NOT_FOUND),
        (api_client.get_bid, ApiErrorId.ERR_BID_NOT_FOUND),
        (api_client.get_purchase_order, ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND),
        (api_client.get_po_line, ApiErrorId.ERR_PO_LINE_NOT_FOUND),
        (api_client.get_shipment, ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
        (api_client.get_receiving_event,
         ApiErrorId.ERR_RECEIVING_EVENT_NOT_FOUND),
        (api_client.get_damage_claim, ApiErrorId.ERR_DAMAGE_CLAIM_NOT_FOUND),
        (api_client.get_room, ApiErrorId.ERR_ROOM_NOT_FOUND),
        (api_client.get_installation_window,
         ApiErrorId.ERR_INSTALLATION_WINDOW_NOT_FOUND),
        (api_client.get_installation_task,
         ApiErrorId.ERR_INSTALLATION_TASK_NOT_FOUND),
        (api_client.get_change_order, ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND),
    ]
    for getter, expected_error in cases:
        res = getter(NON_EXISTENT_UUID, h)
        validate_error(res, expected_error, expected_status=404)
