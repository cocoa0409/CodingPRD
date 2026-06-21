"""Access control and request-validation claims: RBAC role gating, missing auth,
body FK resolution, catalog eligibility (category mismatch, retired type), and
FK-filtered listing.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_repair_ticket_payload, create_service_type_payload,
    create_service_line_payload, create_parts_order_payload,
    TEST_USERS, make_customer_headers, make_technician_headers,
    set_clock, create_customer, create_service_type, create_technician,
    create_ticket, add_item, add_service_line,
    MISSING_UUID,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]


# ── Corner: RBAC ─────────────────────────────────────────────────────────
def test_customer_cannot_intake_ticket(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "| POST | `/repair-tickets` | Create (intake) a RepairTicket | FrontDeskClerk |"

    Design: Corner/rbac/customer_cannot_intake_ticket
    """
    customer = create_customer()
    res = api.create_repair_ticket(
        create_repair_ticket_payload(customer["id"]), make_customer_headers(customer["id"])
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)


def test_technician_cannot_create_service_type(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "| POST | `/service-types` | Create a ServiceType | ShopManager |"

    Design: Corner/rbac/technician_cannot_create_service_type
    """
    tech = create_technician(skills=["SHOE"])
    res = api.create_service_type(
        create_service_type_payload(code="SHOE_SOLE_RBAC", item_category="SHOE"),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)


# ── Corner: missing auth context ─────────────────────────────────────────
def test_missing_auth_context_rejected(api):
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/validations/missing_auth_context_unauthenticated
    """
    res = api.list_repair_tickets({})  # no X-User-ID / X-User-Role headers
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT", 401)


# ── Corner: body FK not found on ticket create ───────────────────────────
def test_ticket_create_unresolved_customer_fk(api):
    """PRD §2.10: "When a create request carries foreign-key references in its body ... each reference must resolve to an existing resource ... an unresolved or cross-ticket reference is rejected with `ERR_FK_NOT_FOUND`."

    Design: Corner/errors/fk_not_found_on_ticket_create_bad_customer
    """
    res = api.create_repair_ticket(create_repair_ticket_payload(MISSING_UUID), FRONT_DESK)
    validate_error(res, "ERR_FK_NOT_FOUND", 422)


# ── Corner: service-line catalog eligibility ─────────────────────────────
def test_service_line_category_mismatch_rejected(api):
    """PRD §2.7: "When a service line is added, the chosen service type's `item_category` must match the `item_category` of the item the service is performed on, and the service type must still be active; a mismatch or a retired type is rejected with `ERR_INVALID_REQUEST`".

    Design: Corner/entities/service_line_category_mismatch_rejected
    """
    set_clock()
    customer = create_customer()
    st_watch = create_service_type(item_category="WATCH", base_price_cents=1500,
                                   standard_turnaround_days=1, warranty_days=90)
    tech = create_technician(skills=["SHOE", "WATCH"])
    ticket = create_ticket(customer["id"])
    item_shoe = add_item(ticket["id"], item_category="SHOE")
    res = api.create_service_line(
        create_service_line_payload(ticket["id"], item_shoe["id"], st_watch["id"]),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", 400)


def test_service_line_with_retired_type_rejected(api):
    """PRD §3.1: "A manager may later retire a service type, which flips `active` to false; a retired type stays in the catalog and on existing lines but may no longer be added to new service lines."
    PRD §3.2: "The chosen service type must be active and its `item_category` must match the referenced item's `item_category`; otherwise the create is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/service_line_retired_type_rejected
    """
    set_clock()
    customer = create_customer()
    st = create_service_type(item_category="SHOE", base_price_cents=4000,
                             standard_turnaround_days=3, warranty_days=90)
    validate_success(api.retire_service_type(st["id"], SHOP_MANAGER), 200)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    res = api.create_service_line(
        create_service_line_payload(ticket["id"], item["id"], st["id"]),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", 400)


# ── Corner: FK-filtered parts listing ────────────────────────────────────
def test_list_parts_orders_filtered_by_ticket(api):
    """PRD §2.10: "The system uses a flat resource topology: every collection sits at the top level, and parent-child relationships are expressed as foreign-key fields filtered through query parameters rather than through deep URL nesting."
    PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_parts_orders_filtered_by_ticket
    """
    set_clock()
    customer = create_customer()
    st = create_service_type(item_category="SHOE", base_price_cents=4000,
                             standard_turnaround_days=3, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    validate_success(
        api.create_parts_order(
            create_parts_order_payload(ticket["id"], line["id"], 500, 1),
            make_technician_headers(tech["id"]),
        ),
        201,
    )
    data, meta = validate_paginated(api.list_parts_orders(TECHNICIAN, params={"ticket_id": ticket["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
