"""Master data creation rules, entity shape, not-found handling, and the
list/pagination envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PM,
    TC,
    ApiErrorId,
    assert_turn,
    assert_unit,
    create_property,
    create_scope_item_payload,
    create_turn_payload,
    create_unit,
    open_turn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_unit_missing_square_feet_rejected(api):
    """PRD §3.1: "Units are created by a `PropertyManager` with a `property_id`
    placing them under an existing property, a `unit_number` label, and
    `square_feet`."
    PRD §2.8: "**Request shape** — required fields are present, types are valid,
    enum values are within their declared domains, unknown fields are rejected,
    an assignment's `end_date` falls after its `start_date`, a turn's
    `move_out_date` falls on or after its `notice_date`, and an inspection's
    `failed_scope_item_ids` is present and non-empty exactly when `result` is
    `FAIL` and absent or empty exactly when `result` is `PASS`; failure yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/unit_creation_missing_required_returns_invalid_request
    """
    prop = create_property()
    resp = api.create_unit({"property_id": prop["id"], "unit_number": "101"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_unit_created_with_initial_state_and_system_fields(api):
    """PRD §3.1: "A unit is born `OCCUPIED`, and its `status` thereafter cycles
    through `NOTICE` when a vacancy notice is recorded, `IN_TURN` while work
    proceeds, `READY` when the turn passes inspection, and back to `OCCUPIED`
    when the next resident moves in — a loop with no terminal state."
    PRD §2.4: "Every primary resource — Property, Unit, Turn, ScopeItem, Vendor,
    VendorAssignment, and LeaseCommitment — carries a standard set of
    system-managed fields" (id, created_at, updated_at, version).

    Design: Corner/entities/unit_created_with_initial_state_and_system_fields
    """
    prop = create_property()
    unit = validate_success(
        api.create_unit({"property_id": prop["id"], "unit_number": "101",
                         "square_feet": 800}, PM),
        201,
    )
    assert_unit(unit)
    assert unit["status"] == "OCCUPIED", "a unit is born OCCUPIED"
    assert unit["property_id"] == prop["id"]
    assert unit["unit_number"] == "101"
    assert unit["square_feet"] == 800


def test_turn_create_with_computed_field_rejected(api):
    """PRD §2.11: "Computed fields are never accepted from clients; they are
    maintained by the server and reconciled immediately as events occur."
    PRD §2.8: "**Request shape** — required fields are present, types are valid,
    enum values are within their declared domains, unknown fields are rejected,
    an assignment's `end_date` falls after its `start_date`, a turn's
    `move_out_date` falls on or after its `notice_date`, and an inspection's
    `failed_scope_item_ids` is present and non-empty exactly when `result` is
    `FAIL` and absent or empty exactly when `result` is `PASS`; failure yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/turn_create_computed_field_input_rejected
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    payload = create_turn_payload(unit["id"])
    payload["estimated_cost_cents"] = 999  # computed field: unknown on input
    resp = api.create_turn(payload, TC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    unit_after = validate_success(api.get_unit(unit["id"], PM))
    assert unit_after["status"] == "OCCUPIED", "no turn may be persisted"


def test_get_unit_not_found_returns_404(api):
    """PRD §2.10: "the server validates each identifier's existence sequentially
    from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404)
    at the first identifier that does not correspond to an existing resource."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_unit_not_found_returns_404
    """
    resp = api.get_unit(NON_EXISTENT_UUID, PM)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    assert error_data["error_id"] == "ERR_NOT_FOUND"
    assert error_data["message"].strip(), "error message must be non-empty"


def test_scope_item_invalid_category_enum_rejected(api):
    """PRD §3.2: "each item carrying `turn_id`, a `category` of `REPAIR`,
    `PAINT`, `CARPET`, `CLEAN`, `APPLIANCE`, `FIXTURE`, or `OTHER`, a free-text
    `description`, and an `estimated_cost_cents`."
    PRD §2.8: "**Request shape** — required fields are present, types are valid,
    enum values are within their declared domains, unknown fields are rejected,
    an assignment's `end_date` falls after its `start_date`, a turn's
    `move_out_date` falls on or after its `notice_date`, and an inspection's
    `failed_scope_item_ids` is present and non-empty exactly when `result` is
    `FAIL` and absent or empty exactly when `result` is `PASS`; failure yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/scope_item_invalid_enum_returns_invalid_request
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    payload = create_scope_item_payload(turn["id"], "REPAIR")
    payload["category"] = "DEEP_CLEAN"  # outside the declared enum
    resp = api.create_scope_item(payload, TC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_list_units_filter_and_pagination_envelope(api):
    """PRD §3.1: "Units can be listed with optional `property_id` and `status`
    filters, and fetched individually."
    PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the response envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_units_filter_and_pagination_envelope
    """
    prop = create_property()
    create_unit(prop["id"], unit_number="101", square_feet=800)
    create_unit(prop["id"], unit_number="102", square_feet=850)

    page1 = api.list_units(PM, params={"property_id": prop["id"], "limit": 1})
    data1, meta1 = validate_paginated(page1)
    assert len(data1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    full = api.list_units(PM, params={"property_id": prop["id"]})
    data_all, meta_all = validate_paginated(full)
    assert len(data_all) == 2
    assert meta_all["total_count"] == 2
    assert meta_all["has_more"] is False
    for unit in data_all:
        assert_unit(unit)
    body = full.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)


def test_turns_filtered_by_unit_and_empty_inspections(api):
    """PRD §4: "List turns, optionally filtered by unit and/or status".
    PRD §3.7: "the full inspection history of a turn can be listed."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources
    sorted by `created_at` in ascending order."

    Design: Corner/endpoints/turns_filtered_by_unit_reverse_reachable
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])

    data, meta = validate_paginated(
        api.list_turns(TC, params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1 and data[0]["id"] == turn["id"]
    assert_turn(data[0])

    insp = validate_success(api.list_inspections(turn["id"], TC))
    assert insp == [], "no inspections submitted yet: empty array, not an error"
