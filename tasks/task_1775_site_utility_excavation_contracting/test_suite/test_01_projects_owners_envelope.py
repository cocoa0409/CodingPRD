"""Project/owner registry basics, response envelope, auth entry gate, audit trail."""

from test_helpers import (
    FOREMAN,
    INSPECTOR,
    NON_EXISTENT_UUID,
    OPS_ADMIN,
    PROJECT_MANAGER,
    SAFETY_OFFICER,
    ApiErrorId,
    assert_audit_event,
    assert_project,
    build_user_headers,
    create_locate_ticket,
    create_project,
    get_project,
    project_payload,
    utility_owner_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_project_creation_applies_server_defaults(api):
    """PRD §3.1: "A new project starts in `ACTIVE` status with `work_posture`
    `CLEAR`, an `approved_co_total_cents` of zero, and no `closed_at` timestamp."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by one on every mutation."
    PRD §2.5: "Before any client interaction the server clock reads exactly
    2026-08-01T00:00:00Z, and it never silently falls back to the host's wall
    clock."

    Design: Corner/entities/project_creation_applies_defaults
    """
    response = api.create_project(
        project_payload(
            name="P-ENT", contract_ref="C-100", soil_class_default="SOIL_B",
            contingency_cents=100_000_000, single_co_cap_cents=5_000_000,
        ),
        PROJECT_MANAGER,
    )
    project = validate_success(response, 201)
    assert_project(project)
    assert project["status"] == "ACTIVE"
    assert project["work_posture"] == "CLEAR"
    assert project["approved_co_total_cents"] == 0
    assert project["version"] == 1
    assert project.get("closed_at") in (None,)
    # The logical clock pins the creation timestamps (3 fractional digits).
    assert project["created_at"] == "2026-08-01T00:00:00.000Z"
    assert project["updated_at"] == "2026-08-01T00:00:00.000Z"


def test_get_missing_segment_returns_not_found(api):
    """PRD §2.10: "Fourth, every identifier in the path and every foreign key
    referenced in the body must name an existing resource, else
    `ERR_NOT_FOUND`; whether an existing reference is scoped to the wrong
    project is deliberately deferred to a later step."

    Design: Corner/entities/get_missing_segment_not_found
    """
    response = api.get_pipe_segment(NON_EXISTENT_UUID, INSPECTOR)
    error = validate_error(response, ApiErrorId.ERR_NOT_FOUND, 404)
    assert error["message"].strip()


def test_create_project_missing_required_field_rejected(api):
    """PRD §2.10: "Third, the request body itself must be well-formed — every
    required field present, types correct, enum values in range, numeric
    fields positive where required, and a proposed shutdown's duration within
    the owning utility's per-window cap — or the request fails with
    `ERR_VALIDATION`."
    PRD §3.1: "A `ProjectManager` then creates the project itself, supplying a
    display `name`, the `contract_ref` job number, a `soil_class_default` of
    `SOIL_A`, `SOIL_B`, or `SOIL_C` as the site's default classification, and
    the two fiscal controls: `contingency_cents`, the owner-funded pool
    available for change orders, and `single_co_cap_cents`, the
    provisional-price ceiling on any individual change order."

    Design: Corner/entities/create_project_missing_required_field
    """
    payload = project_payload(name="P-BAD", contract_ref="C-101")
    del payload["contingency_cents"]
    response = api.create_project(payload, PROJECT_MANAGER)
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)

    listing, meta = validate_paginated(api.list_projects(PROJECT_MANAGER))
    assert meta["total_count"] == 0, f"rejected create persisted: {listing}"


def test_create_owner_with_undeclared_owner_type_rejected(api):
    """PRD §2.10: "Third, the request body itself must be well-formed — every
    required field present, types correct, enum values in range, numeric
    fields positive where required, and a proposed shutdown's duration within
    the owning utility's per-window cap — or the request fails with
    `ERR_VALIDATION`."
    PRD §3.1: "recording its `name`, its `owner_type` — one of `WATER`,
    `SEWER`, `GAS`, `ELECTRIC`, or `TELECOM` — and two scheduling parameters"

    Design: Corner/entities/create_owner_invalid_enum_rejected
    """
    response = api.create_utility_owner(
        utility_owner_payload(
            name="Bad Co", owner_type="PLUMBING",
            min_notice_hours=24, max_shutdown_hours=8,
        ),
        OPS_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_utility_owner_list_pagination_envelope(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, and it must lie between 1 and 100 inclusive. `offset`
    skips a number of items from the front of the result set and defaults to
    0. Unless a specific list documents a different ordering, list endpoints
    return resources sorted by `created_at` in ascending order. The `meta`
    object of every list response carries the four pagination fields `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/owners_list_pagination
    """
    for name, owner_type in (("O1", "WATER"), ("O2", "GAS"), ("O3", "ELECTRIC")):
        response = api.create_utility_owner(
            utility_owner_payload(
                name=name, owner_type=owner_type,
                min_notice_hours=24, max_shutdown_hours=8,
            ),
            OPS_ADMIN,
        )
        validate_success(response, 201)

    page1, meta1 = validate_paginated(
        api.list_utility_owners(FOREMAN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_utility_owners(FOREMAN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_audit_events_append_only_shape(api):
    """PRD §2.4: "An audit event carries only `id` and `created_at` from the
    common set; it has no `updated_at` and no `version`, because it is
    immutable once written."
    PRD §2.4: "Every successful mutation in the system — user action or system
    transition — appends one audit event per mutated resource, and a project's
    full audit history is retrievable in chronological order as described in
    §3.1."

    Design: Corner/entities/audit_events_append_only
    """
    project = create_project(name="P-AUD", contract_ref="C-104")
    ticket = create_locate_ticket(project["id"], ticket_number="T-1")
    validate_success(api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))

    events, meta = validate_paginated(
        api.list_audit_events(project["id"], PROJECT_MANAGER)
    )
    assert meta["total_count"] == 3, (
        f"expected 3 events (project create, ticket create, submit), "
        f"got {meta['total_count']}"
    )
    for event in events:
        assert_audit_event(event)
        assert event["project_id"] == project["id"]
    created = [event["created_at"] for event in events]
    assert created == sorted(created), "events must be chronological"


def test_audit_trail_entity_type_filter(api):
    """PRD §3.1: "Every mutation that touches a resource scoped to the project
    — including system-driven transitions — appends to the project's audit
    trail, and the trail is retrievable per project in `created_at` ascending
    order, optionally narrowed by `entity_type`."
    PRD §2.4: "Each audit event records the `project_id` scoping the mutation,
    the caller's `actor_role` and `actor_user_id`, the `action` performed (the
    HTTP method and path template of the mutation), the `entity_type` and
    `entity_id` of the mutated resource, and a human-readable `detail`
    summarizing what changed"

    Design: Corner/endpoints/audit_trail_records_mutations
    """
    project = create_project(name="P-AUD2", contract_ref="C-500")
    ticket = create_locate_ticket(project["id"], ticket_number="T-1")
    validate_success(api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))

    events, meta = validate_paginated(
        api.list_audit_events(
            project["id"], SAFETY_OFFICER, params={"entity_type": "LocateTicket"}
        )
    )
    assert meta["total_count"] == 2
    for event in events:
        assert_audit_event(event)
        assert event["entity_type"] == "LocateTicket"
        assert event["entity_id"] == ticket["id"]
        assert event["actor_role"] == "ProjectManager"
    assert events[0]["action"] == "POST /site-utility/locate-tickets"
    assert "/submit" in events[1]["action"]
    created = [event["created_at"] for event in events]
    assert created == sorted(created), "events must be created_at ascending"


def test_response_envelope_shape_for_success_and_error(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/endpoints/response_envelope_shape
    """
    project = create_project(name="P-ENV", contract_ref="C-501")

    ok = api.get_project(project["id"], FOREMAN)
    assert ok.status_code == 200
    body = ok.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "object"
    assert body["data"]["id"] == project["id"]

    missing = api.get_project(NON_EXISTENT_UUID, FOREMAN)
    error = validate_error(missing, ApiErrorId.ERR_NOT_FOUND, 404)
    err_body = missing.json()
    assert err_body["response_type"] == "error"
    assert error["message"].strip()
    assert set(err_body["meta"].keys()) == {
        "api_request_id", "api_request_timestamp"
    }


def test_unauthenticated_unknown_role_rejected(api):
    """PRD §2.1: "A request that is missing either header, or whose role
    header does not name one of these six roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_unknown_role
    """
    response = api.create_project(
        project_payload(name="P-NOAUTH", contract_ref="C-400"),
        build_user_headers("anon-1", "Anonymous"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_foreman_cannot_create_project(api):
    """PRD §2.1: "A request whose role is not permitted to perform the
    attempted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /site-utility/projects is authorized for ProjectManager only.

    Design: Corner/rbac/foreman_cannot_create_project
    """
    response = api.create_project(
        project_payload(name="P-RB1", contract_ref="C-700"), FOREMAN
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    _, meta = validate_paginated(api.list_projects(PROJECT_MANAGER))
    assert meta["total_count"] == 0
