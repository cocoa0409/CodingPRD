"""List/pagination envelope, audit-trail retention and filtering, auth floor (PRD §2.1, §2.3, §2.10)."""
from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    assert_audit_event,
    build_user_headers,
    create_account,
    create_order,
    create_security,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_pagination_limit_offset_and_status_filter(api, auditor_headers):
    """PRD §2.3: "List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a caller can always tell how many rows exist and whether another page follows."
    PRD §2.3: "List results are sorted by `created_at` ascending unless a specific endpoint states otherwise — the one exception in this system is a block's fill listing, which sorts by `fill_seq` ascending (§3.6)."
    PRD §3.4: "Orders are listed with optional `account_id`, `security_id`, `block_id`, and `status` filters, and fetched individually by id; each order also exposes its computed `allocated_qty` and `avg_executed_price_cents` once allocation begins (§3.7)."

    Design: Corner/endpoints/pagination_limit_offset_and_status_filter
    """
    account = create_account()
    security = create_security()
    order1 = create_order(account["id"], security["id"], order_qty=10)
    validate_success(api.compliance_check_order(order1["id"], COMPLIANCE))
    order2 = create_order(account["id"], security["id"], order_qty=20)
    validate_success(api.compliance_check_order(order2["id"], COMPLIANCE))
    order3 = create_order(account["id"], security["id"], order_qty=30)

    page1, meta1 = validate_paginated(api.list_orders(auditor_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_orders(auditor_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["id"] == order3["id"]

    approved, meta3 = validate_paginated(api.list_orders(auditor_headers, params={"status": "APPROVED"}))
    assert meta3["total_count"] == 2
    assert [row["id"] for row in approved] == [order1["id"], order2["id"]], (
        "created_at ascending order puts the earlier approval first"
    )
    for row in approved:
        assert row["status"] == "APPROVED"


def test_audit_trail_retention_and_filter(api, auditor_headers):
    """PRD §2.10: "Every mutation in the system appends an AuditEvent."
    PRD §2.10: "The trail is append-only and retained indefinitely; it can be paged and filtered by `entity_type` and `entity_id`."
    PRD §2.10: "An audit event records `entity_type`, a polymorphic entity-type tag such as Order, AllocationPlan, or SettlementInstruction that is an identity label rather than a foreign key; `entity_id`, the mutated resource's id, likewise an identity only and not a join key; `action`, a machine tag such as ORDER_CREATED, BLOCK_ROUTED, or PLAN_POSTED; `actor_role` and `actor_user_id`, taken from the mutating request's headers, or the literal string "system" for automatic transitions such as escalations, budget exhaustion, and settlement bubble-ups; and `detail`, a structured summary of the mutation including from/to states and key fields."
    PRD §3.4: "Creation runs no compliance evaluation at all: the order lands in `PENDING_COMPLIANCE` with `allocated_qty` zero, writes `ORDER_CREATED`, and waits."
    PRD §3.4: "A clean order transitions `PENDING_COMPLIANCE → APPROVED` and writes `ORDER_COMPLIANCE_APPROVED`."

    Design: Corner/endpoints/audit_trail_retention_and_filter
    """
    account = create_account()
    security = create_security()
    order = validate_success(
        api.create_order(
            {"account_id": account["id"], "security_id": security["id"],
             "side": "BUY", "order_qty": 10, "order_type": "MARKET"},
            build_user_headers("trader-9", "Trader"),
        ),
        201,
    )
    validate_success(
        api.compliance_check_order(order["id"], build_user_headers("co-3", "ComplianceOfficer"))
    )

    events, meta = validate_paginated(
        api.list_audit_events(auditor_headers, params={"entity_type": "Order", "entity_id": order["id"]})
    )
    assert meta["total_count"] == 2, (
        f"Exactly ORDER_CREATED and ORDER_COMPLIANCE_APPROVED exist for the order, got {meta['total_count']}"
    )
    for event in events:
        assert_audit_event(event)
    assert [events[0]["action"], events[1]["action"]] == ["ORDER_CREATED", "ORDER_COMPLIANCE_APPROVED"], (
        f"created_at ascending order, got {[e['action'] for e in events]}"
    )
    assert events[0]["actor_role"] == "Trader" and events[0]["actor_user_id"] == "trader-9"
    assert events[1]["actor_role"] == "ComplianceOfficer" and events[1]["actor_user_id"] == "co-3"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.list_orders(NO_AUTH_HEADERS)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_auditor_read_only_enforced(api, auditor_headers):
    """PRD §2.1: "`Auditor` — read-only; queries every resource plus the audit trail."
    PRD §2.1: "A recognized role that is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "Every role may call every read endpoint — all single-resource retrievals and all listings."

    Design: Corner/rbac/auditor_read_only_enforced
    """
    account = create_account()
    security = create_security()

    res = api.create_order(
        {"account_id": account["id"], "security_id": security["id"],
         "side": "BUY", "order_qty": 10, "order_type": "MARKET"},
        auditor_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    fetched = validate_success(api.get_account(account["id"], auditor_headers))
    assert fetched["status"] == "ACTIVE"
