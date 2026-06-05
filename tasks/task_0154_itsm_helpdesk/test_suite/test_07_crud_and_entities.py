"""Corner queue B — entities section: creation defaults, not-found, required
fields, FK resolution, computed counters, listing/pagination, unique tags.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    fixtures as fx,
    factories as F,
    test_users as U,
    ApiErrorId,
)
from test_helpers.constants import MISSING_UUID


# ===========================================================================
# Corner/entities/create_ticket_minimal_fields_returns_201_with_defaults
# ===========================================================================
def test_open_ticket_minimal_fields_defaults_from_category():
    """PRD §3.2: "On a normal open, the ticket is created with lifecycle_state
    NEW; its requester_id is set from the caller's X-User-ID; its
    assignment_group_id is copied from the category's default_assignment_group_id;
    its effective priority is the supplied value or, when absent, the category's
    default_priority; ... its sla_state is RUNNING."

    Design: Corner/entities/create_ticket_minimal_fields_returns_201_with_defaults
    """
    _, group, category = fx.setup_catalog(default_priority="P3")
    resp = api_client.create_ticket(
        {"short_description": "Need help", "category_id": category["id"]},
        U.requester("req-c1"),
    )
    data = validate_success(resp, expected_status=201)

    assert data["priority"] == "P3"
    assert data["lifecycle_state"] == "NEW"
    assert data["sla_state"] == "RUNNING"
    assert data["assignment_group_id"] == group["id"]
    assert data["reopen_count"] == 0


# ===========================================================================
# Corner/entities/get_ticket_not_found_returns_404
# ===========================================================================
def test_get_ticket_unknown_id_returns_not_found():
    """PRD §2.5: "The same ERR_NOT_FOUND governs any /{id} path whose target does
    not exist."

    Design: Corner/entities/get_ticket_not_found_returns_404
    """
    resp = api_client.get_ticket(MISSING_UUID, U.agent("agent-c"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# ===========================================================================
# Corner/entities/create_category_missing_required_field_returns_validation
# ===========================================================================
def test_create_category_missing_default_priority_returns_validation():
    """PRD §3.2: "A create call missing a required field or sending it with the
    wrong type is rejected with ERR_VALIDATION."

    Design: Corner/entities/create_category_missing_required_field_returns_validation
    """
    policy, group, _ = fx.setup_catalog()
    resp = api_client.create_category(
        {
            "name": "Bad",
            "sla_policy_id": policy["id"],
            "default_assignment_group_id": group["id"],
        },
        U.platform_admin(),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


# ===========================================================================
# Corner/entities/create_ticket_with_bad_category_fk_returns_fk_not_found
# ===========================================================================
def test_open_ticket_unresolvable_category_returns_fk_not_found():
    """PRD §2.5: "Whenever a create or link operation carries a reference — a
    category_id, sla_policy_id, assignment_group_id, ticket_id,
    change_request_id, problem_id, asset_id, or kb_article_id — the referenced
    resource must already exist, or the request is rejected with
    ERR_FK_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_ticket_with_bad_category_fk_returns_fk_not_found
    """
    resp = api_client.create_ticket(
        {"short_description": "Orphan", "category_id": MISSING_UUID},
        U.requester("req-c2"),
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value, expected_status=404)


# ===========================================================================
# Corner/entities/ticket_computed_queue_depth_reflects_open_tickets
# ===========================================================================
def test_group_queue_depth_counts_open_tickets():
    """PRD §3.1: "its queue_depth starts at zero and is thereafter a computed
    count of the tickets sitting in it whose lifecycle_state is one of NEW,
    ASSIGNED, IN_PROGRESS, PENDING_CHANGE, or ON_HOLD."

    Design: Corner/entities/ticket_computed_queue_depth_reflects_open_tickets
    """
    _, group, category = fx.setup_catalog(default_priority="P3")
    fx.open_ticket(category["id"], requester_id="req-c3")
    fx.open_ticket(category["id"], requester_id="req-c3")

    data = validate_success(api_client.get_assignment_group(group["id"], U.agent("agent-c")))
    assert data["queue_depth"] == 2


# ===========================================================================
# Corner/entities/list_tickets_paginated_envelope_has_total_count_and_has_more
# ===========================================================================
def test_list_tickets_pagination_reports_total_and_has_more():
    """PRD §2.3: "the pagination fields reported in the meta object are limit,
    offset, total_count, and has_more, where total_count is the number of
    resources matching the query before the page window is applied and has_more is
    true when the window does not reach the end of the result set."

    Design: Corner/entities/list_tickets_paginated_envelope_has_total_count_and_has_more
    """
    _, _, category = fx.setup_catalog(default_priority="P3")
    fx.open_ticket(category["id"], requester_id="req-c4")
    fx.open_ticket(category["id"], requester_id="req-c4")

    resp = api_client.list_tickets(
        U.agent("agent-c"), params={"limit": 1, "category_id": category["id"]}
    )
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Corner/entities/create_asset_duplicate_tag_returns_duplicate_asset_tag
# ===========================================================================
def test_create_asset_duplicate_tag_rejected():
    """PRD §3.1: "Assets are registered with a unique asset_tag and a kind of
    SERVER, LAPTOP, NETWORK_DEVICE, or APPLICATION; a duplicate asset_tag is
    rejected with ERR_DUPLICATE_ASSET_TAG."

    Design: Corner/entities/create_asset_duplicate_tag_returns_duplicate_asset_tag
    """
    fx.create_asset(asset_tag="DUP-1", kind="SERVER")
    resp = api_client.create_asset({"asset_tag": "DUP-1", "kind": "LAPTOP"}, U.platform_admin())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET_TAG.value, expected_status=409)
