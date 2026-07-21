"""Program setup, funding-source creation, not-found, RBAC, and pagination.

Every test translates exactly one non-stub instance from the corner design
index (queue B).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
)
from test_helpers.factories import (
    create_program_payload, create_funding_source_payload,
    create_income_limit_payload,
)
from test_helpers.assertions import assert_program, assert_funding_source, assert_funding_source_ledger_invariant

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]


def test_create_program_returns_open_status(api):
    """PRD 3.1: "A new program opens in `OPEN` status, which accepts applications."
    PRD 3.1: "an AMI ceiling `ami_limit_pct` expressed as a whole-number percent
    of Area Median Income between 1 and 120 (so a value of 80 admits households
    at or below 80% AMI)".

    Design: Corner/entities/create_program_returns_open_status
    """
    resp = api.create_program(create_program_payload(ami_limit_pct=80), PROGRAM_ADMIN)
    data = validate_success(resp, 201)
    assert_program(data)
    assert data["status"] == "OPEN", f"new program must open OPEN, got {data['status']}"
    assert data["ami_limit_pct"] == 80


def test_create_program_missing_field_returns_invalid_request(api):
    """PRD 2.8: "then structural validity of the body (`ERR_INVALID_REQUEST` —
    required fields present, enum values valid members, integer amounts within
    their declared ranges)".

    Design: Corner/entities/create_program_missing_field_returns_invalid_request
    """
    payload = create_program_payload()
    payload.pop("max_assistance_cents")
    resp = api.create_program(payload, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_funding_source_initializes_ledger(api):
    """PRD 3.5: "A new source opens `ACTIVE` with `available_cents` equal to its
    `total_appropriation_cents` and `reserved_cents` and `disbursed_cents` both
    at zero."

    Design: Corner/entities/create_funding_source_initializes_ledger
    """
    resp = api.create_funding_source(
        create_funding_source_payload(total_appropriation_cents=10_000_000), PROGRAM_ADMIN
    )
    data = validate_success(resp, 201)
    assert_funding_source(data)
    assert data["available_cents"] == 10_000_000
    assert data["reserved_cents"] == 0
    assert data["disbursed_cents"] == 0
    assert data["status"] == "ACTIVE"
    assert_funding_source_ledger_invariant(data)


def test_get_applicant_not_found_returns_404(api):
    """PRD 2.8: "The first identifier that does not resolve produces that
    resource's specific not-found error — for example a missing program yields
    `ERR_PROGRAM_NOT_FOUND`, a missing applicant `ERR_APPLICANT_NOT_FOUND`".

    Design: Corner/entities/get_applicant_not_found_returns_404
    """
    resp = api.get_applicant(NON_EXISTENT_UUID, CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value)


def test_duplicate_income_limit_returns_error(api):
    """PRD 3.1: "At most one income-limit row may exist for a given program and
    household size; an attempt to define a second row for the same pair is
    rejected with `ERR_DUPLICATE_INCOME_LIMIT` (HTTP 409)."

    Design: Corner/validations/duplicate_income_limit_returns_error
    """
    program = validate_success(api.create_program(create_program_payload(), PROGRAM_ADMIN), 201)
    validate_success(
        api.create_income_limit(program["id"], create_income_limit_payload(household_size=4), PROGRAM_ADMIN), 201
    )
    resp = api.create_income_limit(
        program["id"], create_income_limit_payload(household_size=4, ami_100_income_cents=11_000_000), PROGRAM_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INCOME_LIMIT.value)


def test_applicant_cannot_create_program_returns_unauthorized(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)." Program creation is a ProgramAdmin-only
    operation per the Section 4 endpoint table.

    Design: Corner/endpoints/applicant_cannot_create_program_returns_unauthorized
    """
    from test_helpers import make_applicant_headers
    resp = api.create_program(create_program_payload(), make_applicant_headers("some-applicant"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of
    the roles enumerated here, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/endpoints/missing_role_header_returns_unauthenticated
    """
    resp = api.list_funding_sources(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_programs_pagination_envelope(api):
    """PRD 2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_programs_pagination_envelope
    """
    validate_success(api.create_program(create_program_payload(name="P1"), PROGRAM_ADMIN), 201)
    validate_success(
        api.create_program(create_program_payload(name="P2", ami_limit_pct=60, recapture_model="DECLINING_BALANCE"), PROGRAM_ADMIN),
        201,
    )
    resp = api.list_programs(PROGRAM_ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1
