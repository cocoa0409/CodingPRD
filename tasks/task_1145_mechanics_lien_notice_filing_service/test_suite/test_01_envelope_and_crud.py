"""Envelope shape, resource creation defaults, and reachability reads (PRD §2.2-§2.4, §3.1-§3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_company,
    assert_project,
    create_company,
    create_project,
    make_customer_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import create_company_payload, create_project_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]

MISSING_PROJECT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_company_creation_defaults_and_system_fields():
    """PRD §3.1: "the account starts life with a `prepaid_balance_cents` of zero
    and an `open_notice_count` of zero."

    Design: Corner/entities/company_creation_defaults_and_system_fields
    """
    res = api.create_company(
        create_company_payload(name="Corner Co", contact_email="cc@x.com"),
        _PLATFORM_ADMIN,
    )
    company = validate_success(res, 201)
    assert_company(company)
    assert company["prepaid_balance_cents"] == 0
    assert company["open_notice_count"] == 0


def test_company_create_missing_required_name_returns_400():
    """PRD §2.10: "a request whose payload is malformed — a missing required
    field, an unknown field, or an invalid enumeration or format value — is
    rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/company_create_missing_required_name_returns_400
    """
    res = api.create_company({"contact_email": "x@x.com"}, _PLATFORM_ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_project_creation_initial_state():
    """PRD §3.2: "The new project's `company_id` is taken from the caller's
    `X-User-ID`, its `research_status` starts at `UNRESEARCHED`, its
    `lien_posture` starts at `CLEAR`, and both of its open counters start at zero."
    PRD §3.3: "The project's `first_furnishing_date` is the earliest `start_date`
    among them, or null when no `ACTIVE` span exists."

    Design: Corner/entities/project_creation_initial_state
    """
    company = create_company(name="P Co")
    res = api.create_project(
        create_project_payload(name="P1", contract_value_cents=1000),
        make_customer_admin_headers(company["id"]),
    )
    project = validate_success(res, 201)
    assert_project(project)
    assert project["research_status"] == "UNRESEARCHED"
    assert project["lien_posture"] == "CLEAR"
    assert project["open_notice_count"] == 0
    assert project["open_lien_count"] == 0
    assert project["first_furnishing_date"] is None
    assert project["last_furnishing_date"] is None
    assert project["company_id"] == company["id"]


def test_project_get_not_found_returns_404():
    """PRD §2.10: "every identifier in the path is resolved left to right, and
    every foreign-key identifier in the body must exist, else `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/project_get_not_found_returns_404
    """
    res = api.get_project(MISSING_PROJECT_ID, _PLATFORM_ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_project_create_computed_field_input_ignored():
    """PRD §2.10: "a request whose payload is malformed — a missing required
    field, an unknown field, or an invalid enumeration or format value — is
    rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD §3.2: "A project's `lien_posture` is computed, never set directly"

    Design: Corner/entities/project_create_computed_field_input_ignored
    """
    company = create_company(name="CI Co")
    payload = create_project_payload(name="CI", contract_value_cents=1000)
    payload["lien_posture"] = "ENCUMBERED"
    res = api.create_project(payload, make_customer_admin_headers(company["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_fk_reverse_reachability_lists():
    """PRD §4: "GET | `/lien/projects/{id}/parties` | List parties of a project"
    and "GET | `/lien/parties/{id}/notices` | List notice orders addressed to
    this party".

    Design: Corner/entities/fk_reverse_reachability_lists
    """
    from test_helpers import create_party

    company = create_company(name="FK Co")
    project = create_project(company["id"], name="FK Job", contract_value_cents=1000)
    party = create_party(project["id"], company["id"], "OWNER", verify=False)

    parties, meta = validate_paginated(
        api.list_project_parties(project["id"], _OPS_AGENT)
    )
    assert meta["total_count"] == 1
    assert parties[0]["id"] == party["id"]

    notices, meta = validate_paginated(
        api.list_party_notices(party["id"], _OPS_AGENT)
    )
    assert notices == []
    assert meta["total_count"] == 0


def test_company_projects_pagination_limit_offset():
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return" and "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order."

    Design: Corner/endpoints/company_projects_pagination_limit_offset
    """
    company = create_company(name="PG Co")
    p1 = create_project(company["id"], name="P1", contract_value_cents=100)
    p2 = create_project(company["id"], name="P2", contract_value_cents=100)

    page1, meta1 = validate_paginated(
        api.list_company_projects(
            company["id"], _OPS_AGENT, params={"limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1 and page1[0]["id"] == p1["id"]
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_company_projects(
            company["id"], _OPS_AGENT, params={"limit": 1, "offset": 1}
        )
    )
    assert len(page2) == 1 and page2[0]["id"] == p2["id"]
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False


def test_success_envelope_shape_on_object_and_list():
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources." and "Pagination-related fields in
    `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list
    endpoints."

    Design: Corner/endpoints/success_envelope_shape_on_object_and_list
    """
    company = create_company(name="EV Co")
    project = create_project(company["id"], name="EV Job", contract_value_cents=100)

    res = api.get_project(project["id"], _OPS_AGENT)
    body = res.json()
    assert res.status_code == 200
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)

    res = api.list_company_projects(company["id"], _OPS_AGENT)
    body = res.json()
    assert res.status_code == 200
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in body["meta"], f"missing pagination meta field {field}"


def test_error_envelope_shape_on_failure():
    """PRD §2.2: error responses carry "response_type": "error" and a data
    object with "error_id" and "message", where "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    res = api.get_project(MISSING_PROJECT_ID, _OPS_AGENT)
    body = res.json()
    assert res.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
