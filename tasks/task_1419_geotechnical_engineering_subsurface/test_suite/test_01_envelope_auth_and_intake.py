"""Response envelope, authentication, client intake, and project read paths."""
from test_helpers import (
    FA,
    MISSING_ID,
    PM,
    SE,
    ApiErrorId,
    api_client,
    assert_boring,
    assert_project,
    create_approved_plan,
    create_client_and_project,
    add_boring,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_client_missing_contact_email_rejected(api):
    """PRD section 3.1: "A `FirmAdmin` opens a commercial relationship by
    creating a Client with the organization's `name` and primary
    `contact_email`."
    PRD section 2.9: "4. **Body well-formedness** — required fields are
    present, enum values are in range, and numbers are in domain:
    `recovery_pct` between 0 and 100 inclusive, `refusal_depth_ft` strictly
    less than the boring's `planned_depth_ft`, `claimed_amount_cents`
    non-negative, and so on (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/create_client_missing_required_field_returns_invalid_request
    """
    resp = api.create_client({"name": "No Contact LLC"}, FA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_new_project_starts_draft_with_posture_open(api):
    """PRD section 3.1: "A new Project starts in `DRAFT` with `posture` equal
    to `OPEN`, `additional_committed_cents` at zero, `claims_exposure_cents`
    at zero, and `testing_invoice_cents` at zero."
    PRD section 2.10: "Several resources expose computed rollups that the
    server maintains as child records change; clients never write them
    directly."

    (The computed rollup is asserted on an ordinary create; whether a stray
    `posture` key in the request body is ignored or rejected is a design
    space the PRD leaves open and is deliberately not exercised.)

    Design: Corner/entities/project_computed_posture_input_ignored
    """
    _client, project = create_client_and_project()
    assert_project(project)
    assert project["status"] == "DRAFT"
    assert project["posture"] == "OPEN", (
        f"A fresh project's computed posture must be OPEN, got {project['posture']}"
    )
    assert project["additional_committed_cents"] == 0
    assert project["claims_exposure_cents"] == 0
    assert project["testing_invoice_cents"] == 0


def test_get_project_not_found_returns_404(api):
    """PRD section 2.5: "Each identifier must resolve to an existing resource
    before the next is examined; the first identifier that does not resolve
    aborts the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and no later
    identifier or body validation is evaluated for that request."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    resp = api.get_project(MISSING_ID, PM)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_get_boring_not_found_error_envelope(api):
    """PRD section 2.5: "the first identifier that does not resolve aborts
    the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)".
    PRD section 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" and "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/get_boring_not_found_returns_404
    """
    resp = api.get_boring(MISSING_ID, SE)
    error = validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    assert resp.status_code == 404
    assert isinstance(error["message"], str) and error["message"].strip()
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_create_client_without_auth_headers_unauthenticated(api):
    """PRD section 2.1: "A request whose headers are missing, or whose
    `X-User-Role` value is not one of these ten names, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/create_client_missing_auth_headers_unauthenticated
    """
    resp = api.create_client({"name": "NoAuth", "contact_email": "n@x.com"},
                             headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_list_borings_pagination_envelope(api):
    """PRD section 2.3: "`limit` caps the number of items returned: it
    defaults to 10, accepts a minimum of 1, and a maximum of 100. `offset`
    skips a number of items from the front of the result set and defaults to
    0. Every list response sorts by `created_at` in ascending order, and its
    envelope `meta` carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_borings_pagination_envelope
    """
    _client, project = create_client_and_project()
    plan = create_approved_plan(project, planned_boring_count=2,
                                planned_total_footage_ft=60)
    add_boring(plan["id"], boring_no="B-1")
    add_boring(plan["id"], boring_no="B-2")

    resp1 = api.list_borings(
        SE, params={"boring_plan_id": plan["id"], "limit": 1, "offset": 0})
    page1, meta1 = validate_paginated(resp1)
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    assert len(page1) == 1
    assert resp1.json()["response_type"] == "array"
    assert resp1.json()["meta"]["api_request_id"].startswith("req_")
    assert_boring(page1[0])

    resp2 = api.list_borings(
        SE, params={"boring_plan_id": plan["id"], "limit": 1, "offset": 1})
    page2, meta2 = validate_paginated(resp2)
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]
    # created_at ascending across the two pages.
    assert page1[0]["created_at"] <= page2[0]["created_at"]
