"""Security: user-context headers, role authorization, ownership, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_client,
    create_client_account_payload,
    create_filing_request,
    create_filing_request_payload,
    create_ready_request,
    create_draft_attempt,
    get_filing,
    get_request,
    make_client_manager_headers,
    make_filing_reviewer_headers,
    make_filing_specialist_headers,
    seed_jurisdiction_profile,
    setup_client_world,
    submit_intake,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_missing_user_context_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting a role name the
    platform does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/missing_auth_header_returns_400
    """
    seed_jurisdiction_profile()
    resp = api.create_client_account(create_client_account_payload(name="No Headers Inc"),
                                     None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_rbac_client_manager_cannot_create_request(api):
    """PRD §2.1: "Performing an operation outside one's role is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/filing-requests` | Intake a filing request | FilingSpecialist |"

    Design: Corner/rbac/rbac_client_manager_cannot_create_request
    """
    world = setup_client_world()
    payload = create_filing_request_payload(
        client_id=world["client"]["id"],
        debtor_id=world["debtor"]["id"],
        secured_party_id=world["secured_party"]["id"],
    )
    resp = api.create_filing_request(
        payload, make_client_manager_headers(world["client"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_rbac_specialist_cannot_approve(api):
    """PRD §2.1: "Performing an operation outside one's role is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/filing-requests/{id}/approve-preparation` | Approve preparation
    and snapshot the quoted fee | FilingReviewer |"

    Design: Corner/rbac/rbac_specialist_cannot_approve
    """
    world = setup_client_world()
    request = create_filing_request(world["client"], world["debtor"], world["secured_party"])
    submit_intake(request["id"], user_id="spec-1")
    resp = api.approve_preparation(request["id"], make_filing_specialist_headers("spec-2"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_request(request["id"])["status"] == "IN_REVIEW", (
        "a denied approval must not move the request"
    )


def test_rbac_officer_cannot_submit(api):
    """PRD §2.1: "Performing an operation outside one's role is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/filings/{id}/submit` | Submit a DRAFT attempt to the filing
    office | FilingSpecialist |"

    Design: Corner/rbac/rbac_officer_cannot_submit
    """
    world = setup_client_world()
    request = create_ready_request(
        world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    resp = api.submit_filing(attempt["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_filing(attempt["id"])["effectiveness_status"] == "DRAFT", (
        "a denied submission must leave the attempt in DRAFT"
    )


def test_client_manager_cross_client_denied(api, admin_headers):
    """PRD §2.1: "Concretely, a `ClientManager` calling any endpoint beneath a client
    path must present an `X-User-ID` equal to the client identifier in that path, or
    the call fails with `ERR_CLIENT_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/client_manager_cross_client_denied
    """
    client_a = create_client("Client A")
    client_b = create_client("Client B")
    resp = api.create_debtor(
        client_b["id"],
        {"debtor_type": "ORGANIZATION", "legal_name": "Intruder Corp",
         "jurisdiction_of_formation": "DE"},
        make_client_manager_headers(client_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_OWNERSHIP_MISMATCH)
    _, meta = validate_paginated(api.list_debtors(client_b["id"], admin_headers))
    assert meta["total_count"] == 0, f"nothing may be created cross-client, got {meta}"


def test_segregation_of_duties_same_user_approve(api):
    """PRD §3.3: "Segregation of duties is enforced at this boundary: the approver's
    `X-User-ID` must differ from the request's `intake_submitted_by_user_id`, or
    approval fails with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "The submitting operator's `X-User-ID` is recorded on the request as
    `intake_submitted_by_user_id`, anchoring the segregation-of-duties check at
    approval."

    Design: Corner/rbac/segregation_of_duties_same_user_approve
    """
    world = setup_client_world()
    request = create_filing_request(world["client"], world["debtor"], world["secured_party"])
    # Intake submitted by a FilingReviewer (the capability is shared) as rev-1.
    submit_intake(request["id"], user_id="rev-1", role="FilingReviewer")
    resp = api.approve_preparation(request["id"], make_filing_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_request(request["id"])["status"] == "IN_REVIEW"
    approved = validate_success(
        api.approve_preparation(request["id"], make_filing_reviewer_headers("rev-2")),
        expected_status=200)
    assert approved["status"] == "READY"
    assert approved["intake_submitted_by_user_id"] == "rev-1", (
        "the intake submitter's user id must be recorded on the request"
    )
