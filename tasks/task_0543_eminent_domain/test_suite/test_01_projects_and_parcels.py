"""Project creation, parcel creation/validation, listing, and role gating."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_project, assert_parcel,
    ApiErrorId, NON_EXISTENT_UUID,
    create_project_payload, create_parcel_payload,
    TEST_USERS,
    create_project, create_parcel, add_fee_owner, clear_ownership,
    create_finalized_appraisal, open_negotiation,
    setup_cleared_appraised_parcel,
)

AGENT = TEST_USERS["right_of_way_agent_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


def test_create_project_initializes_ledger_to_zero(api):
    """PRD §3.1: "On creation the project's `committed_cents`, `disbursed_cents`,
    and `acquired_area_sqft` all begin at zero and `available_cents` equals the
    full `total_budget_cents`".

    Design: Corner/entities/create_project_returns_all_fields
    """
    resp = api.create_project(
        create_project_payload(total_budget_cents=50_000_000), ADMIN)
    data = validate_success(resp, 201)
    assert_project(data)
    assert data["committed_cents"] == 0
    assert data["disbursed_cents"] == 0
    assert data["acquired_area_sqft"] == 0
    assert data["available_cents"] == 50_000_000


def test_get_parcel_unknown_id_returns_not_found(api):
    """PRD §2.8: "the system validates their existence in strict left-to-right
    order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the *first*
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_parcel_not_found_returns_404
    """
    resp = api.get_parcel(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_parcel_missing_take_type_returns_validation(api):
    """PRD §2.11: "Body well-formedness — required fields present, enum values
    valid, and numeric constraints satisfied, else `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_parcel_missing_required_field_returns_validation
    """
    project = create_project(api=api)
    payload = create_parcel_payload(project["id"])
    payload.pop("take_type")
    resp = api.create_parcel(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_parcel_take_area_exceeds_total_returns_validation(api):
    """PRD §3.1: "A create in which the take area exceeds the total area is
    malformed and rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_parcel_take_area_exceeds_total_returns_validation
    """
    project = create_project(api=api)
    resp = api.create_parcel(create_parcel_payload(
        project["id"], total_area_sqft=4_000, take_area_sqft=5_000), AGENT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_list_parcels_returns_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_parcels_pagination_envelope
    """
    project = create_project(api=api)
    create_parcel(project["id"], apn="APN-19a", api=api)
    create_parcel(project["id"], apn="APN-19b", api=api)
    resp = api.list_parcels(project["id"], AGENT, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_limit_zero_returns_invalid(api):
    """PRD §2.3: "A `limit` or `offset` outside these ranges is rejected with
    `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_range_returns_invalid
    """
    project = create_project(api=api)
    resp = api.list_parcels(project["id"], AGENT, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID)


def test_appraiser_cannot_create_parcel(api):
    """PRD §2.1: "If the header is present and recognized but the acting role is
    not permitted to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/appraiser_cannot_create_parcel
    """
    project = create_project(api=api)
    resp = api.create_parcel(create_parcel_payload(project["id"]), APPRAISER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_role_header_returns_unauthenticated(api, anon_headers):
    """PRD §2.1: "If `X-User-Role` is missing or does not name a recognized role,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_project(create_project_payload(), anon_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_clear_ownership_advances_research_dimension_only(api):
    """PRD §3.2: "Clearing ownership research is a `RightOfWayAgent` action that
    advances the parcel's `research_status` from `RESEARCHING` to
    `OWNERSHIP_CLEARED`."
    PRD §3.1: "These two tracks live on the same parcel row but evolve
    separately; neither is derived from the other."

    Design: Difficulty/non_linear_state_machine/parcel_parallel_research_and_acquisition_dimensions
    """
    ctx = setup_cleared_appraised_parcel(clear=False, finalize=True, api=api)
    parcel_id = ctx["parcel"]["id"]
    clear_ownership(parcel_id, api=api)
    parcel = validate_success(api.get_parcel(parcel_id, AGENT))
    assert parcel["research_status"] == "OWNERSHIP_CLEARED"
    assert parcel["acquisition_status"] == "PENDING"


def test_open_negotiation_advances_acquisition_dimension_only(api):
    """PRD §3.4: "Opening a negotiation advances the parcel's `acquisition_status`
    from `PENDING` to `IN_NEGOTIATION`".
    PRD §3.1: "These two tracks live on the same parcel row but evolve
    separately; neither is derived from the other."

    Design: Difficulty/non_linear_state_machine/parcel_parallel_research_and_acquisition_dimensions
    """
    ctx = setup_cleared_appraised_parcel(clear=False, finalize=True, api=api)
    parcel_id = ctx["parcel"]["id"]
    clear_ownership(parcel_id, api=api)
    open_negotiation(parcel_id, api=api)
    parcel = validate_success(api.get_parcel(parcel_id, AGENT))
    assert parcel["acquisition_status"] == "IN_NEGOTIATION"
    assert parcel["research_status"] == "OWNERSHIP_CLEARED"
