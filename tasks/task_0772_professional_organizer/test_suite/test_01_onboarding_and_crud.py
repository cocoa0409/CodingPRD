"""Onboarding, CRUD, validation, listing, and envelope compliance.

Every test here translates one corner-design (breadth) instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_client, assert_project, assert_maintenance_plan,
    is_valid_uuid, assert_version_incremented,
    create_client_payload, create_project_payload,
    new_client, new_organizer, new_project, new_active_project, new_session,
    TEST_USERS, NON_EXISTENT_UUID,
)

OM = TEST_USERS["operations_manager_headers"]


def test_create_client_returns_201_with_fields(api):
    """PRD §3.1: "A client record is created with a full_name, a contact email, a
    home_address, and optional access_notes (free-text entry instructions that
    default to an empty string when omitted)."

    Design: Corner/entities/client_create_returns_201_with_fields
    """
    res = api.create_client(create_client_payload(full_name="Ann"), OM)
    client = validate_success(res, 201)
    assert_client(client)
    assert client["full_name"] == "Ann"
    assert is_valid_uuid(client["id"]), "id must be a non-empty UUID"


def test_create_client_missing_full_name_returns_422(api):
    """PRD §2.10: "the request body is validated for well-formedness — required
    fields present, enum values legal, numeric ranges honored, and, for sessions,
    scheduled_end strictly later than scheduled_start; any violation is
    ERR_VALIDATION at HTTP 422."

    Design: Corner/entities/client_missing_required_full_name_returns_422
    """
    payload = create_client_payload()
    del payload["full_name"]
    res = api.create_client(payload, OM)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_project_defaults_applied_when_optional_omitted(api):
    """PRD §3.2: "When billing_mode is PROJECT, a flat_price_cents fixed labor price
    applies (defaulting to 0 and ignored entirely under HOURLY)."
    PRD §3.2: "The optional move/downsizing add-on is captured by
    move_addon_requested (default false) and move_box_count, the number of packing
    boxes, which must be zero or greater and defaults to 0."

    Design: Corner/entities/project_defaults_applied_when_optional_omitted
    """
    client = new_client()
    organizer = new_organizer()
    payload = create_project_payload(client["id"], organizer["id"],
                                     billing_mode="HOURLY", scope_rooms=["Room"])
    res = api.create_project(payload, OM)
    project = validate_success(res, 201)
    assert project["flat_price_cents"] == 0
    assert project["move_addon_requested"] is False
    assert project["move_box_count"] == 0
    assert project["status"] == "SCOPING"


def test_get_nonexistent_project_returns_404(api):
    """PRD §2.9: "the system validates path identifiers left to right and rejects
    the first one that does not resolve, returning the not-found error specific to
    that resource type: ERR_CLIENT_NOT_FOUND, ERR_ORGANIZER_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_SESSION_NOT_FOUND, ERR_ITEM_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_INVOICE_NOT_FOUND, or ERR_PLAN_NOT_FOUND."

    Design: Corner/entities/project_get_nonexistent_returns_404
    """
    res = api.get_project(NON_EXISTENT_UUID, OM)
    validate_error(res, "ERR_PROJECT_NOT_FOUND", expected_status=404)


def test_project_bad_enum_billing_mode_returns_422(api):
    """PRD §2.10: "the request body is validated for well-formedness — required
    fields present, enum values legal, numeric ranges honored, and, for sessions,
    scheduled_end strictly later than scheduled_start; any violation is
    ERR_VALIDATION at HTTP 422."

    Design: Corner/entities/project_bad_enum_billing_mode_returns_422
    """
    client = new_client()
    organizer = new_organizer()
    payload = create_project_payload(client["id"], organizer["id"],
                                     billing_mode="SUBSCRIPTION", scope_rooms=["Room"])
    res = api.create_project(payload, OM)
    validate_error(res, "ERR_VALIDATION")


def test_session_end_before_start_returns_422(api):
    """PRD §3.3: "scheduled_end must be strictly after scheduled_start, or the
    request is rejected as ERR_VALIDATION."

    Design: Corner/entities/session_end_before_start_returns_422
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    payload = {
        "project_id": project["id"],
        "organizer_id": organizer["id"],
        "scheduled_start": "2026-03-02T12:00:00Z",
        "scheduled_end": "2026-03-02T09:00:00Z",
    }
    from test_helpers import make_organizer_headers
    res = api.create_session(payload, make_organizer_headers(organizer["id"]))
    validate_error(res, "ERR_VALIDATION")


def test_project_body_fk_client_not_found_returns_404(api):
    """PRD §2.9: "Foreign keys supplied in a request body — such as client_id and
    lead_organizer_id when creating a project, or project_id and organizer_id when
    creating a session — are likewise checked against existing records, and an
    unresolved reference is rejected with the corresponding not-found error
    (ERR_CLIENT_NOT_FOUND, ERR_ORGANIZER_NOT_FOUND, or ERR_PROJECT_NOT_FOUND)."

    Design: Corner/entities/project_body_fk_client_not_found_returns_404
    """
    organizer = new_organizer()
    payload = create_project_payload(NON_EXISTENT_UUID, organizer["id"],
                                     billing_mode="HOURLY", scope_rooms=["Room"])
    res = api.create_project(payload, OM)
    validate_error(res, "ERR_CLIENT_NOT_FOUND", expected_status=404)


def test_maintenance_plan_visits_per_year_computed(api):
    """PRD §3.9: "its visits_per_year is derived from the cadence: MONTHLY yields 12
    visits per year, QUARTERLY yields 4, and BIANNUAL yields 2."
    PRD §3.9: "The plan is created in DRAFT status, and its visits_per_year is
    derived from the cadence..."

    Design: Corner/entities/maintenance_plan_visits_per_year_computed
    """
    client = new_client()
    organizer = new_organizer()
    project = new_project(client["id"], organizer["id"], billing_mode="HOURLY", scope_rooms=["Room"])
    res = api.create_maintenance_plan(
        {"project_id": project["id"], "cadence": "QUARTERLY", "monthly_fee_cents": 9900}, OM)
    plan = validate_success(res, 201)
    assert_maintenance_plan(plan)
    assert plan["visits_per_year"] == 4
    assert plan["status"] == "DRAFT"


def test_projects_list_pagination_limit_has_more(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; when omitted
    it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100."
    PRD §2.3: "Every list response includes limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    Design: Corner/endpoints/projects_list_pagination_limit_has_more
    """
    client = new_client()
    organizer = new_organizer()
    new_project(client["id"], organizer["id"], title="P1", billing_mode="HOURLY", scope_rooms=["Room"])
    new_project(client["id"], organizer["id"], title="P2", billing_mode="HOURLY", scope_rooms=["Room"])
    res = api.list_projects(OM, params={"client_id": client["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_sessions_filtered_by_project(api):
    """PRD §4 (Endpoint Definitions): "GET | /sessions | List sessions; filter by
    project, organizer, or status"
    PRD §2.3: "all list endpoints return their resources sorted by creation
    timestamp (created_at) in ascending order."

    Design: Corner/endpoints/sessions_filtered_by_project_reverse_reachability
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    session = new_session(project["id"], organizer["id"],
                          "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")
    res = api.list_sessions(OM, params={"project_id": project["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["id"] == session["id"]


def test_project_version_increments_on_activate(api):
    """PRD §3.2: "A successful activation enables the creation of sessions, inventory
    items, and product lines against the project, and increments the project's
    version by one."
    PRD §2.4: "version starts at its initial value and increments by one on every
    mutation of the resource, including mutations to computed ledger fields."

    Design: Corner/cross_cutting/project_version_increments_on_activate
    """
    client = new_client()
    organizer = new_organizer()
    payload = create_project_payload(client["id"], organizer["id"],
                                     billing_mode="HOURLY", scope_rooms=["Room"])
    created = validate_success(api.create_project(payload, OM), 201)
    activated = validate_success(api.activate_project(created["id"], OM), 200)
    assert activated["status"] == "ACTIVE"
    assert_version_incremented(activated["version"], created["version"])


def test_response_envelope_success_shape_on_get(api):
    """PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The api_request_id is a server-generated unique identifier for the
    request that starts with req_."

    Design: Corner/consistency_model/response_envelope_success_shape_on_get
    """
    client = new_client()
    res = api.get_client(client["id"], OM)
    assert res.status_code == 200
    body = res.json()
    assert body["response_type"] == "object"
    assert "api_request_id" in body["meta"]
    assert body["data"]["id"] == client["id"]
