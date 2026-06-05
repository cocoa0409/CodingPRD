"""Entity CRUD corner cases: participant creation defaults, duplicate email, account
not-found, missing required field, account creation-time computed defaults, and listing
envelope.

Translates Corner/entities instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    create_participant_payload, create_account_payload,
    setup_plan_year_and_participant,
    assert_participant, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_create_participant_returns_201_with_defaults(api):
    """PRD §2.4: "a `version` integer that starts at 1 and increments by one on every
    mutation to the resource."
    PRD §3.1: "`marital_status`, which is one of `SINGLE`, `MARRIED_JOINT`, or
    `MARRIED_SEPARATE` and defaults to `SINGLE`, and `hdhp_covered`, a flag that is `true`
    when the participant is enrolled in a High-Deductible Health Plan and defaults to
    `false`."

    Design: Corner/entities/create_participant_returns_201_with_system_fields
    """
    resp = api.create_participant(
        create_participant_payload(email="new@x.com", full_name="New P",
                                   birth_date="1991-02-03"),
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_participant(data)
    assert data["version"] == 1
    assert data["marital_status"] == "SINGLE"
    assert data["hdhp_covered"] is False


def test_duplicate_participant_email_returns_conflict(api):
    """PRD §3.1: "The `email` must be unique across all participants; a collision is rejected
    with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/entities/duplicate_participant_email_returns_conflict
    """
    validate_success(api.create_participant(
        create_participant_payload(email="dup@x.com", full_name="First",
                                   birth_date="1990-01-01"), ADMIN), expected_status=201)
    resp = api.create_participant(
        create_participant_payload(email="dup@x.com", full_name="Second",
                                   birth_date="1991-01-01"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_get_account_not_found_returns_404(api):
    """PRD §2.8: "the server validates each path segment from left to right and rejects the
    request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not
    resolve to an existing resource."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_create_account_missing_elected_amount_returns_invalid_request(api):
    """PRD §2.10: "a request missing a required field, carrying an invalid enum value,
    supplying a non-positive amount where a positive integer is required, or supplying an OCC
    version field of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
    """
    py, p = setup_plan_year_and_participant(
        clock=None, participant_overrides={"hdhp_covered": True})
    resp = api.create_account(
        {"participant_id": p["id"], "plan_year_id": py["id"], "account_type": "HSA"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_account_creation_seeds_pending_clear_and_zero_balances(api):
    """PRD §3.2: "A freshly opened account begins with `funding_status` of `PENDING` and
    `compliance_hold` of `CLEAR`."
    PRD §3.3: "The account's `contributed_cents` is the sum of `amount_cents` over its
    `POSTED` contributions (reversed ones excluded)."

    A just-opened HSA (no contributions) reports PENDING/CLEAR and zero balances.

    Design: Corner/entities/account_computed_fields_ignore_client_input
    """
    py, p = setup_plan_year_and_participant(
        clock=None, participant_overrides={"hdhp_covered": True})
    resp = api.create_account(
        create_account_payload(p["id"], py["id"], "HSA",
                               coverage_tier="SELF_ONLY", elected_amount_cents=437500),
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["funding_status"] == "PENDING"
    assert data["compliance_hold"] == "CLEAR"
    assert data["available_balance_cents"] == 0
    assert data["contributed_cents"] == 0
    assert data["reimbursed_cents"] == 0


def test_list_accounts_returns_pagination_envelope(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/list_accounts_pagination_envelope
    """
    py, p = setup_plan_year_and_participant(clock=None)
    validate_success(api.create_account(
        create_account_payload(p["id"], py["id"], "HEALTH_FSA",
                               elected_amount_cents=100000), ADMIN), expected_status=201)
    resp = api.list_accounts(ADMIN, params={"participant_id": p["id"],
                                            "limit": 10, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
