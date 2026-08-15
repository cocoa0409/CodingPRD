"""Access-control claims: auth header enforcement, role denials on exclusive
operations, entity-backed self-action checks, and segregation of duties."""
from test_helpers import (
    ABSENT_UUID,
    AUD1,
    FC1,
    SEC1,
    SEC2,
    ApiErrorId,
    appoint_officer,
    create_draft_entity,
    create_jurisdiction_j1,
    create_officer,
    draft_resolution,
    fetch_entity_version,
    make_officer_headers,
    setup_base_entity,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_request_missing_auth_headers_returns_400(api):
    """PRD 2.1: "Every request must carry two mandatory HTTP headers:
    `X-User-ID` and `X-User-Role`."
    PRD 2.1: "A request with a missing or malformed header, or with an
    unrecognized role name, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/request_missing_auth_headers_returns_400
    """
    response = api.list_entities()  # no X-User-ID / X-User-Role at all
    validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert response.status_code == 400


def test_filing_coordinator_cannot_adopt_resolution(api):
    """PRD 4: POST /api/resolutions/{resolutionId}/adopt is authorized for
    CorporateSecretary only.
    PRD 2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/filing_coordinator_cannot_adopt_resolution
    """
    j1 = create_jurisdiction_j1()
    entity = create_draft_entity(j1["id"], legal_name="RBAC Corp", authorized_shares=None)
    resolution = draft_resolution(entity["id"], "AUTHORIZE_FORMATION", {}, "2025-06-15")
    validate_success(api.submit_resolution(resolution["id"], FC1))

    response = api.adopt_resolution(
        resolution["id"], {"expected_entity_version": entity["version"]}, FC1
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    current = validate_success(api.get_resolution(resolution["id"], FC1))
    assert current["status"] == "SUBMITTED"


def test_compliance_auditor_cannot_create_entity(api):
    """PRD 4: POST /api/entities is authorized for CorporateSecretary only.
    PRD 2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/compliance_auditor_cannot_create_entity
    """
    j1 = create_jurisdiction_j1()

    response = api.create_entity(
        {
            "legal_name": "Auditbait Corp",
            "entity_type": "CORPORATION",
            "formation_jurisdiction_id": j1["id"],
            "formation_date": "2025-06-15",
        },
        AUD1,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    rows, meta = validate_paginated(api.list_entities(SEC1))
    assert meta["total_count"] == 0


def test_officer_cannot_resign_another_officers_appointment(api):
    """PRD 3.5: "An `AuthorizedOfficer` may resign an appointment by presenting
    `X-User-ID` equal to the appointment's `officer_id`."
    PRD 3.5: "a resignation attempt by a user other than the holder is rejected
    with `ERR_FORBIDDEN_ACTOR`."

    Design: Corner/rbac/officer_cannot_resign_another_officers_appointment
    """
    ctx = setup_base_entity(legal_name="Twochair Corp")
    entity = ctx["entity"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appointment = appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")
    appoint_officer(entity["id"], o2["id"], office_title="CFO")

    # O2 is a genuine officer, but not the holder of O1's appointment.
    response = api.resign_officer_appointment(
        appointment["id"], make_officer_headers(o2["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ACTOR)

    current = validate_success(api.get_officer_appointment(appointment["id"], SEC1))
    assert current["status"] == "APPOINTED"


def test_sod_drafter_cannot_adopt_own_resolution(api):
    """PRD 3.4: "Third, the adopter must differ from the drafter; a match is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.4: "Adoption sets `adopted_by_user_id`, transitions the resolution to
    `ADOPTED`, and increments the parent entity's `version`."

    Design: Corner/rbac/sod_drafter_cannot_adopt_own_resolution
    """
    j1 = create_jurisdiction_j1()
    entity = create_draft_entity(j1["id"], legal_name="Sod Corp", authorized_shares=None)
    # The same secretary both drafts and submits this resolution.
    resolution = draft_resolution(
        entity["id"], "AUTHORIZE_FORMATION", {}, "2025-06-15", drafter=SEC1
    )
    validate_success(api.submit_resolution(resolution["id"], SEC1))

    version = fetch_entity_version(entity["id"])
    own = api.adopt_resolution(resolution["id"], {"expected_entity_version": version}, SEC1)
    validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    current = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert current["status"] == "SUBMITTED"
    assert fetch_entity_version(entity["id"]) == version, (
        "the rejected adoption did not bump the entity version"
    )

    # A different secretary adopts against the same (still current) version.
    adopted = validate_success(
        api.adopt_resolution(resolution["id"], {"expected_entity_version": version}, SEC2)
    )
    assert adopted["status"] == "ADOPTED"
    assert adopted["adopted_by_user_id"] == "sec-02"


def test_role_denied_before_existence_on_adopt(api):
    """PRD 2.10: "Authentication and role checks come first (priorities 1 and
    2). Existence checks on path and body identifiers come next (priority 3)."
    PRD 4: POST /api/resolutions/{resolutionId}/adopt is authorized for
    CorporateSecretary only.

    Design: Corner/validations/role_denied_before_existence_on_adopt
    """
    j1 = create_jurisdiction_j1()
    entity = create_draft_entity(j1["id"], legal_name="Order Corp", authorized_shares=None)

    # FilingCoordinator may not adopt at all; the nonexistent resolution id
    # never gets a chance to produce a 404.
    response = api.adopt_resolution(
        ABSENT_UUID, {"expected_entity_version": entity["version"]}, FC1
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert response.status_code == 403
