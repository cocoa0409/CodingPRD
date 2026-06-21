"""Resource creation, retrieval, required-field validation, uniqueness, and listing.

Covers queue B: entities section instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    NON_EXISTENT_UUID,
    assert_project,
    assert_project_ledger_invariants,
    create_client_payload,
    create_project_payload,
    create_ffe_item_payload,
    create_room_payload,
    create_selection_payload,
    create_client,
    create_project,
    create_room,
    create_ffe_item,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / create_project_returns_201_with_initial_ledger
# ─────────────────────────────────────────────────────────────────────────────
def test_create_project_returns_201_with_initial_ledger(api):
    """PRD §3.2: "A freshly created project enters status BRIEFING with posture OPEN.
    Its ledger fields are initialized to zero and its budget_status is computed from
    that starting point."
    PRD §3.6: "The project's committed_cents is the sum of order_subtotal_cents over
    every procurement order of the project whose status is ORDERED, IN_TRANSIT, or
    DELIVERED." (a freshly created project has no orders, so committed_cents == 0)
    PRD §2.4: "an integer version that begins at its initial value and increments by
    one on every mutation."

    Note: design_fee_cents is NOT asserted at creation. PRD §3.9 defines the FLAT
    provisional fee as "simply flat_fee_cents" shown "while the project's status is
    anything other than CLOSED", and §2.8 states the derived ledger fields "always
    reflect current reality" — a PRD-faithful implementation may therefore derive
    design_fee_cents = flat_fee_cents immediately at creation. The "initialized to
    zero" prose does not uniquely determine design_fee_cents == 0 at creation, so that
    assertion is omitted (PRD-First unique-derivability).

    Design: Corner/entities/create_project_returns_201_with_initial_ledger
    """
    client = create_client(email="ann.c1@x.com")
    res = api.create_project(
        create_project_payload(client["id"], client_name="Ann", brief_summary="studio",
                               budget_cents=5000000, fee_model="FLAT", flat_fee_cents=200000), ADMIN)
    project = validate_success(res, 201)
    assert_project(project)
    assert project["status"] == "BRIEFING", project["status"]
    assert project["posture"] == "OPEN", project["posture"]
    assert project["committed_cents"] == 0, project["committed_cents"]
    assert project["version"] == 1, project["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / get_project_not_found_returns_404
# ─────────────────────────────────────────────────────────────────────────────
def test_get_project_not_found_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected immediately with ERR_NOT_FOUND, before any
    identifier further to the right is examined."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    res = api.get_project(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / create_project_missing_budget_returns_422
# ─────────────────────────────────────────────────────────────────────────────
def test_create_project_missing_budget_returns_422(api):
    """PRD §2.6: "on every create or modify operation, required body fields must be
    present, correctly typed, and within their declared constraints ... with
    violations reported as ERR_INVALID_REQUEST."
    PRD §3.2: "the budget_cents (the total approved budget, which must be strictly
    greater than zero)"

    Design: Corner/entities/create_project_missing_budget_returns_422
    """
    client = create_client(email="bo.c1@x.com")
    payload = {
        "client_name": "Bo",
        "client_user_id": client["id"],
        "brief_summary": "x",
        "fee_model": "FLAT",
        "flat_fee_cents": 100,
    }
    res = api.create_project(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / create_project_fee_model_fields_inconsistent_returns_422
# ─────────────────────────────────────────────────────────────────────────────
def test_create_project_fee_model_fields_inconsistent_returns_422(api):
    """PRD §3.2: "When fee_model is HOURLY, hourly_rate_cents must be present and
    greater than zero while flat_fee_cents and markup_pct must be zero."
    PRD §3.2: "A fee-field set that does not satisfy the rule for its model is rejected
    with ERR_FEE_MODEL_FIELDS (HTTP 422); this is distinct from a generic
    malformed-body rejection and fires specifically on fee-field inconsistency."

    Design: Corner/entities/create_project_fee_model_fields_inconsistent_returns_422
    """
    client = create_client(email="cy.c1@x.com")
    payload = {
        "client_name": "Cy",
        "client_user_id": client["id"],
        "brief_summary": "x",
        "budget_cents": 100000,
        "fee_model": "HOURLY",
        "flat_fee_cents": 5000,  # inconsistent: HOURLY requires hourly_rate_cents, others 0
    }
    res = api.create_project(payload, ADMIN)
    validate_error(res, "ERR_FEE_MODEL_FIELDS")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / selection_unit_cost_snapshot_ignores_input
# ─────────────────────────────────────────────────────────────────────────────
def test_selection_unit_cost_is_snapshot_of_catalog_price(api):
    """PRD §3.4: "At creation, the selection pins the catalog price: unit_cost_cents
    is snapshotted from the chosen item's list_unit_cost_cents at that moment, so
    later catalog edits never disturb a selection already made."
    PRD §3.4: "That line net is the snapshotted unit cost multiplied by the quantity,
    multiplied by one minus the trade discount fraction, with the product rounded to
    whole cents using round-half-up."

    Design: Corner/entities/selection_unit_cost_snapshot_ignores_input
    """
    client = create_client(email="dot.c1@x.com")
    project = create_project(client["id"], client_name="Dot", budget_cents=10000000)
    ffe = create_ffe_item(sku="SN-A", name="Stool", category="FURNITURE",
                          list_unit_cost_cents=10000, lead_time_days=1)
    room = create_room(project["id"], name="R1")
    # Supply a bogus unit_cost_cents in the body; it must be ignored (system-sourced).
    payload = create_selection_payload(room["id"], ffe["id"], quantity=4,
                                       trade_discount_pct=0.10, spec_note="x")
    payload["unit_cost_cents"] = 999999
    sel = validate_success(api.create_selection(project["id"], payload, DESIGNER), 201)
    assert sel["unit_cost_cents"] == 10000, sel["unit_cost_cents"]
    # line_net = round(10000 * 4 * 0.90) = 36000.
    assert sel["line_net_cents"] == 36000, sel["line_net_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / ffe_item_duplicate_sku_returns_409
# ─────────────────────────────────────────────────────────────────────────────
def test_ffe_item_duplicate_sku_returns_409(api):
    """PRD §3.1: "The sku must be unique across the catalog, and a duplicate is
    rejected with ERR_DUPLICATE."

    Design: Corner/entities/ffe_item_duplicate_sku_returns_409
    """
    validate_success(api.create_ffe_item(
        create_ffe_item_payload(sku="DUP-1", name="A", category="DECOR",
                                list_unit_cost_cents=500, lead_time_days=1), ADMIN), 201)
    res = api.create_ffe_item(
        create_ffe_item_payload(sku="DUP-1", name="B", category="DECOR",
                                list_unit_cost_cents=600, lead_time_days=1), ADMIN)
    validate_error(res, "ERR_DUPLICATE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / room_duplicate_name_within_project_returns_409
# ─────────────────────────────────────────────────────────────────────────────
def test_room_duplicate_name_within_project_returns_409(api):
    """PRD §3.3: "The room name must be unique within its project, compared
    case-sensitively, and a clash is rejected with ERR_DUPLICATE"

    Design: Corner/entities/room_duplicate_name_within_project_returns_409
    """
    client = create_client(email="ed.c1@x.com")
    project = create_project(client["id"], client_name="Ed", budget_cents=10000000)
    validate_success(api.create_room(
        project["id"], create_room_payload(name="Kitchen"), DESIGNER), 201)
    res = api.create_room(
        project["id"], create_room_payload(name="Kitchen", scope_note="s2"), DESIGNER)
    validate_error(res, "ERR_DUPLICATE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — entities / list_projects_pagination_envelope
# ─────────────────────────────────────────────────────────────────────────────
def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned"
    PRD §2.3: "Every list response carries the pagination bookkeeping inside the meta
    object: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    client = create_client(email="fi.c1@x.com")
    create_project(client["id"], client_name="Fi", brief_summary="a", budget_cents=100000, flat_fee_cents=100)
    create_project(client["id"], client_name="Fi", brief_summary="b", budget_cents=100000, flat_fee_cents=100)
    data, meta = validate_paginated(
        api.list_projects(ADMIN, params={"client_user_id": client["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)
