"""Corner-queue breadth: entity creation/defaults, not-found, required fields,
system fields, listing envelope, pagination limit, and RBAC/auth denials.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_finance_officer_headers,
    create_approved_disbursement,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]
SCREENER = TEST_USERS["screener_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ==========================================================================
# Entities
# ==========================================================================
def test_create_intended_parent_returns_201_with_defaults(api):
    """PRD §3.1: "The record is created in `DRAFT` intake status with
    psychological clearance `PENDING`." PRD §2.4: "The `version` starts at its
    initial value on creation".

    Design: Corner/entities/create_intended_parent_returns_201_with_defaults
    """
    data = validate_success(
        api.create_intended_parent(f.create_intended_parent_payload(budget_cents=5_000_000), CM),
        expected_status=201)
    assert data["intake_status"] == "DRAFT"
    assert data["psych_clearance"] == "PENDING"
    assert data["version"] == 1


def test_get_carrier_not_found_returns_404(api):
    """PRD §2.5: "the system validates each identifier from left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier that does
    not correspond to an existing resource."

    Design: Corner/entities/get_carrier_not_found_returns_404
    """
    resp = api.get_carrier(NON_EXISTENT_UUID, CM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_intended_parent_missing_budget_returns_invalid_request(api):
    """PRD §3.1: "A `CaseManager` registers an **intended parent** by supplying
    a `legal_name`, a two-letter uppercase US `state_code` of residence, and a
    `budget_cents` figure". PRD §3.10: "A malformed body — a missing required
    field, an invalid enum, negative cents, or a bad `decision` value — is
    reported as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_intended_parent_missing_required_field_returns_invalid_request
    """
    resp = api.create_intended_parent({"legal_name": "IP Bad", "state_code": "CA"}, CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_system_fields_ignored_on_create_carrier(api):
    """PRD §3.1: "The carrier is created in `DRAFT` with `psych_clearance`
    `PENDING`." PRD §2.4: "Every entity in the system carries a server-minted
    `id` ... The `version` starts at its initial value on creation".

    Design: Corner/entities/system_fields_ignored_on_create_carrier
    """
    data = validate_success(api.create_carrier(f.create_carrier_payload(), CM), expected_status=201)
    assert data["intake_status"] == "DRAFT"
    assert data["version"] == 1


def test_list_intended_parents_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_intended_parents_paginated_envelope
    """
    get_success_data(api.create_intended_parent(f.create_intended_parent_payload(legal_name="IP L1"), CM))
    get_success_data(api.create_intended_parent(
        f.create_intended_parent_payload(legal_name="IP L2", state_code="NY"), CM))
    data, meta = validate_paginated(api.list_intended_parents(CM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the range from 1 to 100 inclusive, or a
    negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`."

    Design: Corner/errors/pagination_limit_out_of_range_validation_limit
    """
    resp = api.list_intended_parents(CM, params={"limit": 101, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)


# ==========================================================================
# RBAC / auth
# ==========================================================================
def test_screener_cannot_create_intended_parent_forbidden(api):
    """PRD §2.1: "When the headers are present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`." PRD §4 routing: `POST /intended-parents` is authorized for
    `CaseManager` only.

    Design: Corner/rbac/screener_cannot_create_intended_parent_forbidden
    """
    resp = api.create_intended_parent(f.create_intended_parent_payload(legal_name="IP RB"), SCREENER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_intended_parents({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_casemanager_cannot_release_disbursement_forbidden(api):
    """PRD §2.1: "A `FinanceOfficer` governs escrow deposits handling and
    disbursement release and is deliberately kept separate from disbursement
    approval." PRD §4 routing: `POST /journeys/{id}/disbursements/{did}/release`
    is authorized for `FinanceOfficer`.

    Design: Corner/rbac/casemanager_cannot_release_disbursement_forbidden
    """
    ctx = create_approved_disbursement(approver_user_id="cm-rb2")
    jr_id = ctx["journey"]["id"]
    resp = api.release_disbursement(jr_id, ctx["disbursement"]["id"], CM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    refreshed = validate_success(api.get_disbursement(ctx["disbursement"]["id"], FO))
    assert refreshed["status"] == "APPROVED"


def test_segregation_of_duties_same_user_release_forbidden(api):
    """PRD §2.8: "The subsequent release must be performed by a `FinanceOfficer`
    whose `X-User-ID` differs from that recorded approver. A release where the
    acting officer's identifier equals the recorded approver is rejected with
    `ERR_SEGREGATION_OF_DUTIES`, preventing any single person from both
    authorizing and paying out the same funds."

    Design: Corner/rbac/segregation_of_duties_same_user_release_forbidden
    """
    ctx = create_approved_disbursement(approver_user_id="shared-uid")
    jr_id = ctx["journey"]["id"]
    same_user_officer = make_finance_officer_headers("shared-uid")
    resp = api.release_disbursement(jr_id, ctx["disbursement"]["id"], same_user_officer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    refreshed = validate_success(api.get_disbursement(ctx["disbursement"]["id"], FO))
    assert refreshed["status"] == "APPROVED"
