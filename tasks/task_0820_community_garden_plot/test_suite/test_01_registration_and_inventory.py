"""Registration, garden/plot inventory, listing, and inventory-level RBAC."""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_gardener_headers,
    create_garden_payload, create_plot_payload, create_gardener_payload,
    ApiErrorId, NON_EXISTENT_UUID,
)

MANAGER = TEST_USERS["manager_headers"]


def test_create_gardener_populates_default_standing_and_ledger(api):
    """PRD §3.1: "A freshly registered gardener starts with `tenure_seasons` at 0,
    `standing` of `GOOD` (the standing field ranges over `GOOD`, `PROBATION`, and
    `SUSPENDED`), `strike_count` at 0, and `balance_owed_cents` at 0."

    Design: Corner/entities/create_gardener_returns_all_default_fields
    """
    resp = api.create_gardener(create_gardener_payload(full_name="New Gardener"), MANAGER)
    data = validate_success(resp, 201)
    assert data["standing"] == "GOOD"
    assert data["tenure_seasons"] == 0
    assert data["strike_count"] == 0
    assert data["balance_owed_cents"] == 0


def test_gardener_missing_email_rejected_as_validation(api):
    """PRD §3.5: a second reading "is rejected during body validation with
    `ERR_VALIDATION` (HTTP 422), the same code that rejects a missing field, a bad
    enum, or an out-of-range value such as a `period_index` outside 1 through 3 or a
    negative `gallons_used`."
    PRD §3.1: "Gardeners register with a `full_name` and an `email`."

    Design: Corner/entities/gardener_missing_required_email_returns_validation
    """
    resp = api.create_gardener({"full_name": "No Email"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_gardener_duplicate_email_rejected(api):
    """PRD §3.1: "The email must be unique across all gardeners; a second registration
    reusing an existing address is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/entities/gardener_duplicate_email_returns_conflict
    """
    api.create_gardener(create_gardener_payload(full_name="First", email="dup@example.com"), MANAGER)
    resp = api.create_gardener(create_gardener_payload(full_name="Second", email="dup@example.com"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value, 409)


def test_get_unknown_plot_returns_not_found(api):
    """PRD §2.8: "Existence checks follow, resolving every referenced entity and
    returning the appropriate not-found error (for example `ERR_GARDEN_NOT_FOUND`,
    `ERR_PLOT_NOT_FOUND`, `ERR_GARDENER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COMPLIANCE_CASE_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`,
    or `ERR_TOOL_LOAN_NOT_FOUND`, each HTTP 404)."

    Design: Corner/entities/plot_get_nonexistent_returns_not_found
    """
    resp = api.get_plot(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_PLOT_NOT_FOUND.value, 404)


def test_new_garden_initializes_plot_rollups_to_zero(api):
    """PRD §3.1: "A newly created garden begins with `total_plots` and
    `available_plot_count` both at zero — these are computed roll-ups the system
    maintains, never client input."

    Design: Corner/entities/garden_system_fields_generated_on_create
    """
    resp = api.create_garden(create_garden_payload(name="Fresh Garden"), MANAGER)
    data = validate_success(resp, 201)
    assert data["total_plots"] == 0
    assert data["available_plot_count"] == 0


def test_total_plots_derived_after_two_plot_creates(api):
    """PRD §3.1: "Adding a plot increments the owning garden's `total_plots` and,
    because the new plot is available, its `available_plot_count` as well."

    Design: Corner/entities/garden_total_plots_derived_after_plot_creates
    """
    garden = validate_success(api.create_garden(create_garden_payload(name="Count Garden"), MANAGER), 201)
    gid = garden["id"]
    validate_success(api.create_plot(create_plot_payload(gid, size="SMALL", label="P-1"), MANAGER), 201)
    validate_success(api.create_plot(create_plot_payload(gid, size="LARGE", label="P-2"), MANAGER), 201)
    data = validate_success(api.get_garden(gid, MANAGER), 200)
    assert data["total_plots"] == 2
    assert data["available_plot_count"] == 2


def test_list_plots_pagination_meta_reports_total_and_has_more(api):
    """PRD §2.3: "For list responses, the `meta` object additionally carries `limit`,
    `offset`, `total_count` (the total number of matching rows before pagination), and
    `has_more` (true when rows remain beyond the current window)."

    Design: Corner/endpoints/list_plots_pagination_envelope
    """
    garden = validate_success(api.create_garden(create_garden_payload(name="Page Garden"), MANAGER), 201)
    gid = garden["id"]
    validate_success(api.create_plot(create_plot_payload(gid, size="SMALL", label="PG-1"), MANAGER), 201)
    validate_success(api.create_plot(create_plot_payload(gid, size="SMALL", label="PG-2"), MANAGER), 201)
    resp = api.list_plots(MANAGER, params={"garden_id": gid, "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_garden_tool_collection_lists_the_garden_tools(api):
    """PRD §3.1: "The tools of a garden can be listed, optionally filtered by
    `category`, through the garden's tool collection."

    Design: Corner/endpoints/reverse_reach_tools_by_garden_subresource
    """
    garden = validate_success(api.create_garden(create_garden_payload(name="Shed Garden"), MANAGER), 201)
    gid = garden["id"]
    tool = validate_success(api.create_tool({"garden_id": gid, "name": "Rake 1", "category": "HAND"}, MANAGER), 201)
    resp = api.list_garden_tools(gid, MANAGER)
    data, _ = validate_paginated(resp)
    assert any(t["id"] == tool["id"] for t in data), "garden tool collection must contain the created tool"


def test_gardener_cannot_create_plot(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or a gardener attempts to act on a resource they
    do not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/gardener_cannot_create_plot_returns_unauthorized
    """
    garden = validate_success(api.create_garden(create_garden_payload(name="RBAC Garden"), MANAGER), 201)
    gardener = validate_success(api.create_gardener(create_gardener_payload(full_name="Role Tester"), MANAGER), 201)
    resp = api.create_plot(
        create_plot_payload(garden["id"], size="SMALL", label="X-1"),
        make_gardener_headers(gardener["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
