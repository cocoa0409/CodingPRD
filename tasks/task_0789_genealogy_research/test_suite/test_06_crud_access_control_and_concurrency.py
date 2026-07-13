"""Corner-coverage tests: creation/defaults/system-fields, not-found and validation
errors, RBAC/ownership, filtered reverse-lookups, and optimistic concurrency."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_researcher_headers, make_client_headers, TEST_USERS, NON_EXISTENT_UUID,
    create_active_project, provision_client, provision_researcher, create_draft_project,
    create_person, create_completed_search, add_citation, create_submitted_deliverable,
    api_client,
)
from test_helpers.factories import (
    create_client_payload, create_researcher_payload, create_person_payload,
    create_milestone_payload,
)

PM = TEST_USERS["project_manager_headers"]


# ==========================================================================
# Corner / entities
# ==========================================================================
def test_project_creation_returns_201_draft_version_1():
    """PRD §3.1: "A newly opened project begins in `status` `DRAFT`."
    PRD §2.4: "`version` is an integer that begins at 1 when the resource is created
    and increments by exactly 1 on each mutation."

    Design: Corner/entities/project_creation_returns_201_with_fields
    """
    client = provision_client()
    researcher = provision_researcher()
    resp = api_client.create_project(
        {"client_id": client["id"], "lead_researcher_id": researcher["id"],
         "title": "New request", "objective": "Trace maternal line",
         "package_type": "HOURLY", "package_price_cents": 0, "budget_hours": 5}, PM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["package_type"] == "HOURLY"


def test_person_get_nonexistent_returns_not_found():
    """PRD §2.5: "the first missing reference yields the corresponding not-found
    error (for example, an unknown project yields `ERR_PROJECT_NOT_FOUND`, an
    unknown person yields `ERR_PERSON_NOT_FOUND`, and so on for each entity, all
    HTTP 404)."

    Design: Corner/entities/person_get_nonexistent_returns_not_found
    """
    resp = api_client.get_person(NON_EXISTENT_UUID, PM)
    validate_error(resp, "ERR_PERSON_NOT_FOUND")


def test_project_create_missing_package_type_returns_validation():
    """PRD §2.5: "Malformed payloads — a missing required field, a value of the
    wrong type, or an enum value outside its permitted set — are rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/project_create_missing_required_field_returns_invalid_request
    """
    client = provision_client()
    researcher = provision_researcher()
    # package_type is a required commercial term (§3.1) — omit it.
    resp = api_client.create_project(
        {"client_id": client["id"], "lead_researcher_id": researcher["id"],
         "title": "No package", "objective": "obj",
         "package_price_cents": 1000, "budget_hours": 5}, PM)
    validate_error(resp, "ERR_VALIDATION")


def test_client_create_omitting_tier_defaults_to_standard():
    """PRD §3.1: "optionally a billing `tier`; when omitted, `tier` defaults to
    `STANDARD`, the only other permitted value being `PREMIUM`."

    Design: Corner/entities/client_create_omitting_tier_applies_default_standard
    """
    resp = api_client.create_client(
        {"name": "Default Tier", "email": "dt-corner@example.com"}, PM)
    data = validate_success(resp, expected_status=201)
    assert data["tier"] == "STANDARD", f"omitted tier must default to STANDARD, got {data['tier']}"


def test_person_system_fields_generated_on_create():
    """PRD §2.4: "`version` is an integer that begins at 1 when the resource is
    created and increments by exactly 1 on each mutation."
    PRD §3.4: "A new person begins with `verification_status` `DRAFT`."

    Design: Corner/entities/person_system_fields_generated_on_create
    """
    client, researcher, project = create_active_project()
    resp = api_client.create_person(
        create_person_payload(project_id=project["id"], full_name="Ada Fresh"),
        make_researcher_headers(researcher["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["version"] == 1
    assert data["verification_status"] == "DRAFT"


def test_person_self_referential_parent_reverse_lookup():
    """PRD §3.4: "Genealogical descent is expressed by two self-referential parent
    links, `father_id` and `mother_id`, each a nullable reference to another person;
    the list endpoint for persons can be filtered by either link to walk the tree."
    PRD §2.3: "`total_count` (the number of records matching the filter before the
    page window is applied)".

    Design: Corner/entities/person_self_referential_parent_fk_reverse_lookup
    """
    client, researcher, project = create_active_project()
    father = create_person(project["id"], researcher["id"], full_name="Father Node")
    child = create_person(project["id"], researcher["id"], full_name="Child Node",
                          father_id=father["id"])
    resp = api_client.list_persons(PM, params={"father_id": father["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly one child, got {meta['total_count']}"
    assert any(p["id"] == child["id"] for p in data), "child must be discoverable by father_id filter"


def test_person_create_with_unknown_project_returns_not_found():
    """PRD §2.5: "the first missing reference yields the corresponding not-found
    error (for example, an unknown project yields `ERR_PROJECT_NOT_FOUND`, an
    unknown person yields `ERR_PERSON_NOT_FOUND`, and so on for each entity, all
    HTTP 404)."

    Design: Corner/entities/person_create_with_unknown_project_returns_not_found
    """
    researcher = provision_researcher()
    resp = api_client.create_person(
        create_person_payload(project_id=NON_EXISTENT_UUID, full_name="Orphan"),
        make_researcher_headers(researcher["id"]))
    validate_error(resp, "ERR_PROJECT_NOT_FOUND")


# ==========================================================================
# Corner / endpoints
# ==========================================================================
def test_citations_reverse_lookup_by_person():
    """PRD §2.3: "`total_count` (the number of records matching the filter before
    the page window is applied)".
    PRD §3.4: "A citation supplies the `record_search_id` that produced it, the
    `person_id` it supports".

    Design: Corner/endpoints/citations_reverse_lookup_by_person_filtered_list
    """
    client, researcher, project = create_active_project()
    person = create_person(project["id"], researcher["id"], full_name="Cited Person")
    search = create_completed_search(project["id"], researcher["id"], search_terms="x")
    citation = add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                            source_type="VITAL_RECORD", citation_text="Birth")
    resp = api_client.list_citations(PM, params={"person_id": person["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly one citation, got {meta['total_count']}"
    assert any(c["id"] == citation["id"] for c in data), "citation must be found by person_id filter"


# ==========================================================================
# Corner / errors + rbac
# ==========================================================================
def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    three recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/auth_missing_header_returns_unauthenticated
    """
    resp = api_client.create_client({"name": "Ghost", "email": "ghost@example.com"}, {})
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_client_creating_researcher_returns_unauthorized():
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/client_creating_researcher_returns_unauthorized
    """
    client = provision_client()
    resp = api_client.create_researcher(
        create_researcher_payload(name="Sneaky", hourly_rate_cents=1),
        make_client_headers(client["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_non_owner_client_accept_deliverable_returns_forbidden():
    """PRD §2.1: "a `Client` may accept or request revision on a deliverable only
    when the deliverable's owning project names that same client, i.e. the project's
    `client_id` equals `X-User-ID`; otherwise the request is rejected with
    `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403)."

    Design: Corner/errors/non_owner_client_accept_deliverable_returns_forbidden
    """
    owner = provision_client(name="Owner A")
    other = provision_client(name="Other B")
    researcher = provision_researcher()
    project = create_draft_project(owner["id"], researcher["id"])
    project = get_success_data(api_client.activate_project(project["id"], PM))
    deliverable = create_submitted_deliverable(project["id"], researcher["id"],
                                               deliverable_type="RESEARCH_REPORT")
    resp = api_client.accept_deliverable(deliverable["id"], make_client_headers(other["id"]))
    validate_error(resp, "ERR_FORBIDDEN_NOT_OWNER")


def test_researcher_cannot_create_milestone_returns_unauthorized():
    """PRD §3.9: "Billing is organized as `Milestone` records created by a project
    manager."
    PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/researcher_cannot_create_milestone_returns_unauthorized
    """
    client, researcher, project = create_active_project()
    resp = api_client.create_milestone(
        create_milestone_payload(project_id=project["id"], title="M", amount_cents=1000,
                                 sequence_no=1),
        make_researcher_headers(researcher["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


# ==========================================================================
# Corner / cross_cutting_complexity_layers (optimistic concurrency)
# ==========================================================================
def test_reconfigure_stale_project_version_returns_412():
    """PRD §2.6: "The server compares this value against the project's current
    `version`: if another writer has advanced the project's `version` since the
    client last read it, the reconfigure is rejected with `ERR_STALE_PROJECT_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/reconfigure_stale_project_version_returns_412
    """
    client = provision_client()
    researcher = provision_researcher()
    project = create_draft_project(client["id"], researcher["id"])
    original_version = project["version"]
    # First reconfigure succeeds and advances the version.
    get_success_data(api_client.reconfigure_project(
        project["id"], {"expected_project_version": original_version, "budget_hours": 12}, PM))
    # Second reconfigure still carrying the original (now stale) version is rejected.
    resp = api_client.reconfigure_project(
        project["id"], {"expected_project_version": original_version, "budget_hours": 15}, PM)
    validate_error(resp, "ERR_STALE_PROJECT_VERSION")


def test_reconfigure_with_current_version_succeeds_and_bumps_version():
    """PRD §2.6: "Only when `expected_project_version` matches the current `version`
    is the update applied (and the `version` then incremented)."
    PRD §3.2: "a successful reconfigure updates whichever of `package_type`,
    `budget_hours`, `package_price_cents`, and `priority` are supplied and leaves
    the others untouched."

    Design: Corner/cross_cutting_complexity_layers/reconfigure_with_current_version_succeeds_and_bumps_version
    """
    client = provision_client()
    researcher = provision_researcher()
    project = create_draft_project(client["id"], researcher["id"])
    resp = api_client.reconfigure_project(
        project["id"], {"expected_project_version": project["version"], "budget_hours": 20}, PM)
    data = validate_success(resp, expected_status=200)
    assert data["budget_hours"] == 20, f"budget_hours must update to 20, got {data['budget_hours']}"
    assert data["version"] == 2, f"version must increment 1 -> 2, got {data['version']}"
