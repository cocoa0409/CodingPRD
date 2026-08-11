"""Registration defaults, uniqueness, auto-created booking assignment, listing (PRD 2.3, 3.1, 3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_agent,
    assert_move_order,
    create_agent,
    create_customer,
    create_order_payload,
    create_published_tariff,
    get_success_data,
    make_booking_agent_headers,
    register_order,
    setup_network,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


def test_agent_creation_applies_defaults(api):
    """PRD section 3.1: "an optional `commission_tier` of `STANDARD`, `PREFERRED`,
    or `PREMIER` that defaults to `STANDARD` and later drives the revenue-split
    bonus of §3.8. A new agent begins with `status` `ACTIVE`, a `quality_score`
    of 100, and a `ytd_linehaul_share_cents` ledger of 0."
    PRD section 2.5: "All time-dependent rules read a logical clock maintained by
    the server, whose startup default is exactly 2026-05-01T00:00:00Z; before any
    operator intervention the clock reads this default."

    Design: Corner/entities/agent_creation_applies_defaults
    """
    # commission_tier deliberately omitted from the payload.
    payload = {
        "legal_name": "Solo Agent",
        "agent_code": "SA01",
        "capabilities": ["BOOKING"],
        "home_market": "Fresno",
    }
    created = validate_success(api.create_agent(payload, ADMIN), expected_status=201)
    assert_agent(created)
    agent = validate_success(api.get_agent(created["id"], ADMIN))
    assert agent["commission_tier"] == "STANDARD", "commission_tier default must be STANDARD"
    assert agent["quality_score"] == 100, "quality_score must start at 100"
    assert agent["ytd_linehaul_share_cents"] == 0, "ytd ledger must start at 0"
    assert agent["status"] == "ACTIVE"
    assert agent["created_at"].startswith("2026-05-01T00:00:00"), (
        f"created_at must be stamped from the default logical clock, got {agent['created_at']}"
    )


def test_agent_creation_rejected_duplicate_code(api):
    """PRD section 3.1: "A `VanLineAdmin` registers each network agent with its
    `legal_name`, a unique `agent_code` of four to eight characters (a code already
    on file is rejected with `ERR_DUPLICATE_AGENT_CODE`, HTTP 409), a non-empty
    `capabilities` list drawn from `BOOKING`, `ORIGIN`, `HAULING`, and
    `DESTINATION`, the agent's `home_market`, and an optional `commission_tier` of
    `STANDARD`, `PREFERRED`, or `PREMIER` that defaults to `STANDARD` and later
    drives the revenue-split bonus of §3.8."

    Design: Corner/entities/agent_creation_rejected_duplicate_code
    """
    first = create_agent(agent_code="DUP1", legal_name="First")
    assert_agent(first)

    resp = api.create_agent(
        {
            "legal_name": "Second",
            "agent_code": "DUP1",
            "capabilities": ["HAULING"],
            "home_market": "Tulsa",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGENT_CODE)

    data, meta = validate_paginated(api.list_agents(ADMIN))
    assert meta["total_count"] == 1, f"expected exactly 1 agent, got {meta['total_count']}"
    assert data[0]["id"] == first["id"]


def test_order_registration_creates_booking_assignment(api):
    """PRD section 3.2: "Registration also auto-creates the order's `BOOKING`
    assignment in `CONFIRMED` status, naming the registering agent through the
    caller's `X-User-ID` and snapshotting its `split_pct` at that moment."
    PRD section 3.2: "On creation the order receives a sequential `order_number`
    in the VL-000001 style — a registration number used for identity only and
    never consulted by any decision — and lands in `REGISTERED` with
    `billing_status` `UNBILLED`."

    Design: Corner/endpoints/order_registration_creates_booking_assignment
    """
    ctx = setup_network()
    order = register_order(ctx, pricing_mode="BINDING", mileage=900)
    assert_move_order(order)
    assert order["status"] == "REGISTERED"
    assert order["billing_status"] == "UNBILLED"

    data, meta = validate_paginated(
        api.list_agent_assignments(ADMIN, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 1, (
        f"registration must auto-create exactly one assignment, got {meta['total_count']}"
    )
    booking = data[0]
    assert booking["role"] == "BOOKING"
    assert booking["status"] == "CONFIRMED"
    assert booking["agent_id"] == ctx["booking_agent"]["id"]


def test_order_list_filtered_by_customer_fk(api):
    """PRD section 2.3: "Each list endpoint additionally accepts equality filters
    drawn from the resource's own fields. ... The order list accepts `customer_id`,
    `tariff_id`, `authoritative_weight_ticket_id`, and `status`."

    Design: Corner/entities/order_list_filtered_by_customer_fk
    """
    ctx = setup_network()
    cust_b = create_customer()
    order = register_order(ctx, pricing_mode="BINDING", mileage=900)

    data_a, meta_a = validate_paginated(
        api.list_orders(ADMIN, params={"customer_id": ctx["customer"]["id"]})
    )
    assert meta_a["total_count"] == 1
    assert data_a[0]["id"] == order["id"]

    data_b, meta_b = validate_paginated(
        api.list_orders(ADMIN, params={"customer_id": cust_b["id"]})
    )
    assert meta_b["total_count"] == 0
    assert data_b == []
    assert meta_b["has_more"] is False


def test_get_missing_order_returns_not_found(api):
    """PRD section 2.10: "Existence — path-template resources are validated left
    to right, and body-referenced identifiers (such as `customer_id`, `tariff_id`,
    `agent_id`, `warehouse_id`, `claim_id`, and `revenue_statement_id`) must
    resolve to existing resources; the first missing identifier, scanning the path
    from left to right, yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_missing_order_returns_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_envelope_and_pagination_defaults(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items returned;
    when omitted it defaults to 10, and it is bounded below by 1 and above by 100.
    The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD section 2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."

    Design: Corner/endpoints/list_envelope_and_pagination_defaults
    """
    create_agent(["BOOKING"], legal_name="Solo")
    resp = api.list_agents(ADMIN)
    body = resp.json()
    assert body.get("response_type") == "array", (
        f"list response_type must be 'array', got {body.get('response_type')!r}"
    )
    data, meta = validate_paginated(resp)
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert isinstance(meta["api_request_timestamp"], str) and meta["api_request_timestamp"]
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
