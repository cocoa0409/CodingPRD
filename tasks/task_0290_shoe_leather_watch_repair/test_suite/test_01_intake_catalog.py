"""Intake, catalog, and customer CRUD claims.

Covers the entities-section corner instances (customer create / validation,
service-type system fields, service-line snapshot, ticket not-found, listing)
plus the ticket version-increment difficulty instance.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_customer, assert_service_type, assert_service_line,
    create_customer_payload, create_service_type_payload,
    create_repair_ticket_payload, create_ticket_item_payload,
    create_service_line_payload,
    TEST_USERS, make_technician_headers,
    create_customer, create_service_type, create_technician, create_ticket,
    add_item, MISSING_UUID,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


def test_create_customer_minimal_defaults(api):
    """PRD §3.1: "A customer is created with `status` of `ACTIVE`".
    PRD §3.1: "a `notify_channel` preference that defaults to `EMAIL` and may instead be `SMS`".
    PRD §2.4: "the `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource."

    Design: Corner/entities/create_customer_minimal_required_fields
    """
    res = api.create_customer(
        create_customer_payload(full_name="Mina Min", email="mina_minimal@x.com", phone="555-1000"),
        FRONT_DESK,
    )
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["status"] == "ACTIVE"
    assert cust["notify_channel"] == "EMAIL"
    assert cust["version"] == 1


def test_create_customer_missing_email_rejected(api):
    """PRD §3.1: "A `FrontDeskClerk` (or a `ShopManager`) registers **customers**, each with a `full_name`, an `email` that is unique across all customers, a `phone` used for SMS notifications".
    PRD §2.9: "sixth, request shape, enum/type/range validity, and catalog eligibility (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_customer_missing_email_invalid_request
    """
    payload = create_customer_payload(full_name="No Email", phone="555-1001")
    del payload["email"]
    res = api.create_customer(payload, FRONT_DESK)
    validate_error(res, "ERR_INVALID_REQUEST", 400)


def test_duplicate_customer_email_conflict(api):
    """PRD §3.1: "A duplicate `email` on creation is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/duplicate_customer_email_conflict
    """
    first = api.create_customer(
        create_customer_payload(full_name="First", email="dup_email@x.com", phone="555-1002"),
        FRONT_DESK,
    )
    validate_success(first, 201)
    res = api.create_customer(
        create_customer_payload(full_name="Second", email="dup_email@x.com", phone="555-1003"),
        FRONT_DESK,
    )
    validate_error(res, "ERR_DUPLICATE_KEY", 409)


def test_get_ticket_not_found(api):
    """PRD §2.9: "third, existence of every resource named by a path identifier (the not-found family, e.g. `ERR_TICKET_NOT_FOUND`".

    Design: Corner/entities/get_ticket_not_found
    """
    res = api.get_repair_ticket(MISSING_UUID, FRONT_DESK)
    validate_error(res, "ERR_TICKET_NOT_FOUND", 404)


def test_service_type_active_is_server_set(api):
    """PRD §3.1: "A new service type is born with its `active` flag true."

    Design: Corner/entities/service_type_create_system_fields_generated
    """
    res = api.create_service_type(
        create_service_type_payload(code="SHOE_SOLE_SYS", name="Sole Replacement",
                                    item_category="SHOE", base_price_cents=4000,
                                    standard_turnaround_days=3, warranty_days=90),
        SHOP_MANAGER,
    )
    st = validate_success(res, 201)
    assert_service_type(st)
    assert st["active"] is True


def test_service_line_quoted_price_snapshot(api):
    """PRD §3.2: "On creation the line takes status `QUOTED` and snapshots its `quoted_price_cents` from the service type's `base_price_cents` at that moment, freezing the price against later catalog changes."

    Design: Corner/entities/service_line_quoted_price_snapshot_computed
    """
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE")
    ticket = create_ticket(customer["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    tech = create_technician(skills=["SHOE"])
    res = api.create_service_line(
        create_service_line_payload(ticket["id"], item["id"], st["id"]),
        make_technician_headers(tech["id"]),
    )
    line = validate_success(res, 201)
    assert_service_line(line)
    assert line["quoted_price_cents"] == 4000
    assert line["status"] == "QUOTED"


def test_list_tickets_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_tickets_pagination_envelope
    """
    customer = create_customer()
    create_ticket(customer["id"])
    data, meta = validate_paginated(api.list_repair_tickets(SHOP_MANAGER))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1
    assert "has_more" in meta


# ── Difficulty: ticket version increments on mutation (≥2 tests) ──────────
def test_fresh_ticket_starts_at_version_one(api):
    """PRD §2.4: "the `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/ticket_version_increments_on_mutation
    """
    customer = create_customer()
    res = api.create_repair_ticket(create_repair_ticket_payload(customer["id"]), FRONT_DESK)
    ticket = validate_success(res, 201)
    assert ticket["version"] == 1


def test_patch_ticket_increments_version_by_one(api):
    """PRD §2.4: "the `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource."
    PRD §2.8: "Whenever an operation changes the `RepairTicket` ... the ticket's `version` increments by one and its `updated_at` refreshes."

    Design: Corner/cross_cutting_complexity_layers/ticket_version_increments_on_mutation
    """
    customer = create_customer()
    tech = create_technician(skills=["SHOE"])
    res = api.create_repair_ticket(create_repair_ticket_payload(customer["id"]), FRONT_DESK)
    ticket = validate_success(res, 201)
    assert ticket["version"] == 1
    patched = validate_success(
        api.patch_repair_ticket(ticket["id"], {"assigned_technician_id": tech["id"]}, FRONT_DESK),
        200,
    )
    assert patched["version"] == 2
