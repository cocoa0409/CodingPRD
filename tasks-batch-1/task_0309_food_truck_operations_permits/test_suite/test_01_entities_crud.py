"""Entity creation, defaults, required fields, not-found, immutability, and listing.

Queue B: entities-section corner instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_commissary, create_truck,
    api_client, TEST_USERS, make_operator_truck_headers,
    create_commissary_payload, create_truck_payload, create_menu_item_payload,
    create_utility_log_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_commissary_returns_201_with_defaults(api):
    """PRD §3.1: "A new commissary opens with its `status` field set to `ACTIVE`, and its
    `docked_truck_count` starts at 0."

    POST /commissaries with name+state_code returns 201 with status ACTIVE and
    docked_truck_count 0.

    Design: Corner/entities/create_commissary_returns_201_with_defaults
    """
    res = api.create_commissary(create_commissary_payload(name="West Kitchen", state_code="CA"), DISPATCHER)
    commissary = validate_success(res, 201)
    assert commissary["status"] == "ACTIVE"
    assert commissary["docked_truck_count"] == 0


def test_get_truck_not_found_returns_404(api):
    """PRD §2.6: "a missing commissary yields `ERR_COMMISSARY_NOT_FOUND`, a missing truck
    `ERR_TRUCK_NOT_FOUND` ... All of these carry HTTP 404."

    GET /trucks/{nonexistent-uuid} returns ERR_TRUCK_NOT_FOUND.

    Design: Corner/entities/get_truck_not_found_returns_404
    """
    res = api.get_truck(NONEXISTENT, DISPATCHER)
    validate_error(res, "ERR_TRUCK_NOT_FOUND")


def test_create_menu_item_missing_required_field_rejected(api):
    """PRD §3.5: "An OperatorTruck adds a menu item under its own truck by supplying the
    truck_id, a per-truck-unique sku, the display name, a list unit_price_cents (non-negative),
    and a par_units target."
    PRD §3.9: "request well-formedness: required fields present ... any of which fails with
    ERR_INVALID_REQUEST."

    POST /menu-items missing unit_price_cents is rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/create_menu_item_missing_required_field_returns_invalid_request
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    h = make_operator_truck_headers(truck["id"])
    payload = create_menu_item_payload(truck["id"])
    del payload["unit_price_cents"]
    res = api.create_menu_item(payload, h)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_truck_bad_commissary_fk_returns_404(api):
    """PRD §2.6: "Foreign-key references supplied in a request body are likewise checked for
    existence; an unknown reference yields the not-found error for the referenced resource type
    ... a missing commissary yields ERR_COMMISSARY_NOT_FOUND."

    POST /trucks with a commissary_id that does not exist returns ERR_COMMISSARY_NOT_FOUND.

    Design: Corner/entities/create_truck_bad_commissary_fk_returns_404
    """
    res = api.create_truck(create_truck_payload(NONEXISTENT), DISPATCHER)
    validate_error(res, "ERR_COMMISSARY_NOT_FOUND")


def test_utility_log_immutable_no_version_field(api):
    """PRD §2.4: "A UtilityLog is an append-only event record: it carries only id and created_at.
    It has neither updated_at nor version, because it is never modified after it is written."

    A created GENERATOR utility log carries id + created_at but no version/updated_at, and is
    re-readable by id.

    Design: Corner/entities/utility_log_immutable_no_version_field
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    h = make_operator_truck_headers(truck["id"])
    res = api.create_utility_log(
        create_utility_log_payload(truck["id"], "GENERATOR", generator_delta_hours=2), h)
    log = validate_success(res, 201)
    assert "version" not in log, "append-only UtilityLog must not carry version"
    assert "updated_at" not in log, "append-only UtilityLog must not carry updated_at"
    again = validate_success(api.get_utility_log(log["id"], DISPATCHER), 200)
    assert again["id"] == log["id"]


def test_list_commissaries_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of every list response carries the `limit`, `offset`,
    `total_count`, and `has_more` pagination fields."

    With two commissaries and limit=1, the paginated list reports total_count 2 and has_more
    true.

    Design: Corner/entities/list_commissaries_pagination_envelope
    """
    create_commissary(name="K1")
    create_commissary(name="K2")
    data, meta = validate_paginated(api.list_commissaries(DISPATCHER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
