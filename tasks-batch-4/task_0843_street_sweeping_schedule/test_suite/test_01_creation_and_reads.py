"""Creation defaults, not-found / validation errors, listing, and filtered reads.

Translates queue B (Corner) entity and endpoint instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_route, assert_citation,
    create_route_payload, create_block_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_verified_block, set_clock, issue_citation,
)

DISPATCHER = TEST_USERS["route_dispatcher_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


def test_create_route_returns_201_with_defaults(api):
    """PRD §3.1: "A route's `status` may be supplied at creation and is otherwise `ACTIVE`"
    PRD §3.1: "Every route also exposes the derived counter `completed_block_count`, which starts at 0"
    PRD §2.4: "`version` — an integer that begins at creation and increments by one on every mutation of the resource."

    Design: Corner/entities/create_route_returns_201_with_defaults
    """
    res = api.create_route(create_route_payload(name="Elm Loop", zone_code="Z2", sweep_weekday="WED"), DISPATCHER)
    route = validate_success(res, 201)
    assert_route(route)
    assert route["status"] == "ACTIVE", f"status should default to ACTIVE, got {route['status']}"
    assert route["completed_block_count"] == 0
    assert route["version"] == 1


def test_get_block_not_found_returns_404(api):
    """PRD §2.9: "every resource referenced by a path identifier or a body foreign key must exist, validated left-to-right in the order the identifiers appear."
    PRD §2.9: "The first missing reference determines the error: `ERR_ROUTE_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`"

    Design: Corner/entities/get_block_not_found_returns_404
    """
    res = api.get_block(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(res, "ERR_BLOCK_NOT_FOUND", expected_status=404)


def test_create_block_missing_required_field_returns_422(api):
    """PRD §2.9: "the body must carry all required fields with valid types and enum values, else `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_block_missing_required_field_returns_422
    """
    route = validate_success(api.create_route(create_route_payload(), DISPATCHER), 201)
    payload = create_block_payload(route["id"])
    del payload["restriction_end_local"]
    res = api.create_block(payload, DISPATCHER)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_create_block_with_missing_route_returns_404(api):
    """PRD §2.9: "The first missing reference determines the error: `ERR_ROUTE_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`"

    Design: Corner/entities/create_block_with_missing_route_returns_404
    """
    payload = create_block_payload(NON_EXISTENT_UUID)
    res = api.create_block(payload, DISPATCHER)
    validate_error(res, "ERR_ROUTE_NOT_FOUND", expected_status=404)


def test_citation_amount_due_is_server_computed_provisional(api):
    """PRD §3.7: "The **provisional** fine is computed at issuance and stored in `amount_due_cents`: because a freshly issued citation has a `days_late` pinned to 0, its `late_fee_cents` is 0 and only the base and repeat multiplier apply."
    PRD §3.7: "It begins from a base fine of 6,000 cents (`BASE_FINE_CENTS`, i.e. $60.00) plus a late-fee component `late_fee_cents`."

    Design: Corner/entities/citation_computed_amount_ignores_client_supplied_value
    """
    route, block = setup_verified_block()
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    cit = issue_citation(block["id"], plate="CMP001", scanned_at_utc="2026-03-10T08:30:00Z")
    assert cit["amount_due_cents"] == 6000
    assert cit["status"] == "ISSUED"


def test_list_blocks_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_blocks_pagination_envelope
    """
    route = validate_success(api.create_route(create_route_payload(), DISPATCHER), 201)
    validate_success(api.create_block(create_block_payload(route["id"], block_label="A"), DISPATCHER), 201)

    data, meta = validate_paginated(
        api.list_blocks(DISPATCHER, params={"route_id": route["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


def test_get_citations_filtered_by_block(api):
    """PRD §3.7: "Citations may be listed and filtered by block, sweep event, plate, or status."

    Design: Corner/endpoints/get_citations_filtered_by_block
    """
    route, block = setup_verified_block()
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    cit = issue_citation(block["id"], plate="LST001", scanned_at_utc="2026-03-10T08:30:00Z")

    data, meta = validate_paginated(api.list_citations(OFFICER, params={"block_id": block["id"]}))
    assert meta["total_count"] == 1
    assert any(c["id"] == cit["id"] for c in data), "filtered list must contain the issued citation"
