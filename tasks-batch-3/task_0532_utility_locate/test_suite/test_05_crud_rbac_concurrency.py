"""CRUD basics, listing, RBAC, ownership, header auth, optimistic concurrency, and versioning.

Covers the entities / rbac / cross_cutting_complexity_layers corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    register_excavator, register_member, register_tech, create_ticket, submit_ticket,
    first_notification, get_notification_for_member, post_response, dispatch, go_en_route,
    create_markout, complete_markout, current_ticket_version,
    setup_cleared_ticket, setup_marked_ticket, setup_submitted_ticket,
    make_excavator_headers, make_facility_owner_headers, make_locate_tech_headers,
    TEST_USERS, ApiErrorId, COVERING_POLYGON,
)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_locate_ticket_returns_201_with_intake_defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_create_ticket_intake_defaults(api):
    """PRD §3.2: "A freshly created ticket sits in `INTAKE` with a `response_posture` of `INTAKE`"
    PRD §3.2: "an optional `is_white_lined` flag (defaulting to false)"

    Design: Corner/entities/create_locate_ticket_returns_201_with_intake_defaults
    """
    exc = register_excavator()
    ticket = validate_success(
        api.create_locate_ticket(
            {"excavator_id": exc["id"], "ticket_type": "NORMAL",
             "dig_polygon": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
             "work_description": "trench"},
            make_excavator_headers(exc["id"]),
        ), 201,
    )
    assert ticket["status"] == "INTAKE"
    assert ticket["response_posture"] == "INTAKE"
    assert ticket["is_white_lined"] is False
    assert ticket["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/get_locate_ticket_not_found_returns_404
# ─────────────────────────────────────────────────────────────────────────────

def test_get_ticket_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing resource causes the
    request to be rejected immediately with the matching not-found error (`ERR_TICKET_NOT_FOUND`,
    ...)."

    Design: Corner/entities/get_locate_ticket_not_found_returns_404
    """
    exc = register_excavator()
    resp = api.get_locate_ticket(
        "00000000-0000-4000-8000-000000000000", make_excavator_headers(exc["id"])
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_ticket_missing_required_field_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_ticket_missing_ticket_type_rejected(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."
    PRD §3.2: "Creation supplies the `excavator_id` of the filer, a `ticket_type` of either
    `NORMAL` or `EMERGENCY`, the `dig_polygon` describing the dig site, a free-text
    `work_description`"

    Design: Corner/entities/create_ticket_missing_required_field_returns_invalid_request
    """
    exc = register_excavator()
    resp = api.create_locate_ticket(
        {"excavator_id": exc["id"],
         "dig_polygon": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
         "work_description": "no type"},
        make_excavator_headers(exc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/invalid_dig_polygon_geometry_returns_422
# ─────────────────────────────────────────────────────────────────────────────

def test_create_ticket_invalid_dig_polygon_rejected(api):
    """PRD §3.2: "the `dig_polygon` must be a valid rectangle, and a malformed box is rejected with
    `ERR_INVALID_GEOMETRY`."
    PRD §2.7: "A valid rectangle must have `max_x` strictly greater than `min_x` and `max_y`
    strictly greater than `min_y`."

    Design: Corner/entities/invalid_dig_polygon_geometry_returns_422
    """
    exc = register_excavator()
    resp = api.create_locate_ticket(
        {"excavator_id": exc["id"], "ticket_type": "NORMAL",
         "dig_polygon": {"min_x": 20, "min_y": 10, "max_x": 20, "max_y": 20},
         "work_description": "degenerate box"},
        make_excavator_headers(exc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_GEOMETRY)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_ticket_missing_excavator_fk_returns_404
# ─────────────────────────────────────────────────────────────────────────────

def test_create_ticket_unknown_excavator_fk_rejected(api):
    """PRD §2.6: "When a request carries one or more resource identifiers, whether in the URL path
    or as a foreign-key field in the body, the server validates them left to right and in order.
    The first identifier that does not resolve to an existing resource causes the request to be
    rejected immediately with the matching not-found error (..., `ERR_EXCAVATOR_NOT_FOUND`, ...)."

    Design: Corner/entities/create_ticket_missing_excavator_fk_returns_404
    """
    exc = register_excavator()
    resp = api.create_locate_ticket(
        {"excavator_id": "11111111-1111-4111-8111-111111111111", "ticket_type": "NORMAL",
         "dig_polygon": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
         "work_description": "bad fk"},
        make_excavator_headers(exc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EXCAVATOR_NOT_FOUND)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/list_tickets_pagination_envelope
# ─────────────────────────────────────────────────────────────────────────────

def test_list_tickets_pagination_envelope(api):
    """PRD §2.3: "List responses include the following fields inside the response envelope's `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_tickets_pagination_envelope
    """
    exc = register_excavator()
    exc_h = make_excavator_headers(exc["id"])
    for _ in range(2):
        validate_success(
            api.create_locate_ticket(
                {"excavator_id": exc["id"], "ticket_type": "NORMAL",
                 "dig_polygon": {"min_x": 1, "min_y": 1, "max_x": 2, "max_y": 2},
                 "work_description": "t"},
                exc_h,
            ), 201,
        )
    data, meta = validate_paginated(
        api.list_locate_tickets(exc_h, params={"excavator_id": exc["id"], "limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/computed_liability_input_ignored_on_create
# ─────────────────────────────────────────────────────────────────────────────

def test_damage_report_begins_filed(api):
    """PRD §3.8: "The report begins in `FILED`, and its computed `excavator_liability_cents` and
    `member_liability_cents` are not yet apportioned."

    Design: Corner/entities/computed_liability_input_ignored_on_create
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    dr = validate_success(
        api.create_damage_report(
            {"ticket_id": ticket["id"], "member_utility_id": mem["id"],
             "repair_cost_cents": 5000, "dug_within_marks": False},
            make_facility_owner_headers(mem["id"]),
        ), 201,
    )
    assert dr["status"] == "FILED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/excavator_cannot_post_positive_response
# ─────────────────────────────────────────────────────────────────────────────

def test_excavator_cannot_post_positive_response(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/excavator_cannot_post_positive_response
    """
    base = setup_submitted_ticket(ticket_type="EMERGENCY")
    resp = api.create_positive_response(
        {"notification_id": base["notification"]["id"], "outcome": "CLEAR"},
        make_excavator_headers(base["excavator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/wrong_owner_facility_cannot_answer_others_notification
# ─────────────────────────────────────────────────────────────────────────────

def test_wrong_owner_cannot_answer_notification(api):
    """PRD §3.4: "the acting `FacilityOwner` must own the notification's `member_utility_id`, or the
    request is rejected with `ERR_NOT_NOTIFICATION_OWNER`."

    Design: Corner/rbac/wrong_owner_facility_cannot_answer_others_notification
    """
    exc = register_excavator()
    mem_a = register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    mem_b = register_member(name="Water B", facility_type="WATER",
                            service_polygon={"min_x": 500, "min_y": 500, "max_x": 600, "max_y": 600})
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note_a = get_notification_for_member(ticket["id"], mem_a["id"])
    resp = api.create_positive_response(
        {"notification_id": note_a["id"], "outcome": "CLEAR"},
        make_facility_owner_headers(mem_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_NOTIFICATION_OWNER)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/missing_user_context_header_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a value the server cannot validate,
    is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    exc = register_excavator()
    resp = api.create_locate_ticket(
        {"excavator_id": exc["id"], "ticket_type": "NORMAL",
         "dig_polygon": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
         "work_description": "no auth"},
        {},  # no X-User-ID / X-User-Role headers
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/occ_stale_ticket_version_on_refresh_markout
# ─────────────────────────────────────────────────────────────────────────────

def test_refresh_stale_ticket_version_rejected(api):
    """PRD §2.11: "If that value does not match the ticket's current `version` — meaning another
    writer has already posted a refresh and advanced the ticket's version since the client last read
    it — the create is rejected with `ERR_STALE_TICKET_VERSION` (HTTP 412), because the client's
    view of which mark-out it may supersede is no longer current."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_ticket_version_on_refresh_markout
    """
    base = setup_marked_ticket()
    tid = base["ticket"]["id"]
    tech_id = base["tech"]["id"]
    current = current_ticket_version(tid, tech_id)
    resp = api.create_mark_out(
        {"assignment_id": base["assignment"]["id"], "ticket_id": tid, "marks_count": 4,
         "supersedes_markout_id": base["markout"]["id"], "expected_ticket_version": current - 1},
        make_locate_tech_headers(tech_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_TICKET_VERSION)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/version_increments_on_each_ticket_mutation
# ─────────────────────────────────────────────────────────────────────────────

def test_ticket_version_increments_on_submit(api):
    """PRD §2.4: "a `version` (an integer that starts at its initial value and increments by one on
    every mutation)."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_ticket_mutation
    """
    exc = register_excavator()
    register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = validate_success(
        api.create_locate_ticket(
            {"excavator_id": exc["id"], "ticket_type": "NORMAL",
             "dig_polygon": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
             "work_description": "trench", "is_white_lined": True},
            make_excavator_headers(exc["id"]),
        ), 201,
    )
    assert ticket["version"] == 1
    after = validate_success(api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200)
    assert after["version"] == 2
