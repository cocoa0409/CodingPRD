"""Fund register basics, response envelope, auth and existence checks."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    assert_fund,
    create_fund_payload,
    create_contribution_payload,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
GIFT = TEST_USERS["gift_officer_headers"]


def test_fund_creation_applies_system_defaults(api):
    """PRD §3.1: "The new fund begins in `PENDING_AGREEMENT` with `cash_balance`
    at 0.00 and `invested_units` at 0.0000."
    PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."

    Design: Corner/entities/fund_creation_defaults_and_system_fields
    """
    resp = api.create_fund(
        create_fund_payload(fund_type="DONOR_ADVISED", endowed=False), ADMIN
    )
    data = validate_success(resp, 201)
    assert_fund(data)
    assert data["status"] == "PENDING_AGREEMENT"
    assert float(data["cash_balance"]) == 0.00
    assert float(data["invested_units"]) == 0.0000
    assert is_valid_uuid(data["id"])
    assert isinstance(data["version"], int)


def test_get_missing_fund_returns_not_found(api):
    """PRD §2.6: "Each identifier in the path is confirmed to exist before the
    next is examined, and the request is rejected with a 404 carrying
    `ERR_NOT_FOUND` at the first identifier that does not resolve."

    Design: Corner/entities/fund_not_found_returns_404
    """
    resp = api.get_fund(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_fund_list_pagination_envelope(api):
    """PRD §2.3: "List responses carry four pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/fund_list_pagination_envelope
    """
    validate_success(api.create_fund(create_fund_payload(), ADMIN), 201)
    validate_success(api.create_fund(create_fund_payload(), ADMIN), 201)

    resp = api.list_funds(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    data2, meta2 = validate_paginated(api.list_funds(ADMIN, params={"limit": 1, "offset": 1}))
    assert len(data2) == 1
    assert meta2["has_more"] is False
    assert data2[0]["id"] != data[0]["id"]


def test_duplicate_fund_name_rejected(api):
    """PRD §3.1: "Fund names are unique across the foundation; a duplicate
    `fund_name` is rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409)."

    Design: Corner/entities/fund_name_uniqueness_enforced
    """
    validate_success(
        api.create_fund(create_fund_payload(fund_name="Dup Fund"), ADMIN), 201
    )
    resp = api.create_fund(
        create_fund_payload(fund_name="Dup Fund", fund_type="SCHOLARSHIP", endowed=True),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION)


def test_contribution_with_unknown_fund_reference_rejected(api):
    """PRD §2.6: "A creation payload that references a `fund_id`, `grantee_id`,
    advisor id, `member_id`, `application_id`, or a list of
    `winner_application_ids` that does not correspond to an existing resource is
    rejected with a 404 carrying `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/body_fk_reference_must_exist
    """
    resp = api.create_contribution(
        create_contribution_payload(fund_id=NON_EXISTENT_UUID, declared_value=100.00),
        GIFT,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_request_without_user_context_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a role name
    outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = api.list_funds(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


def test_role_not_permitted_on_endpoint_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/role_forbidden_for_endpoint
    """
    resp = api.create_fund(
        create_fund_payload(fund_name="Nope"), TEST_USERS["applicant_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_nested_path_validated_left_to_right(api):
    """PRD §2.6: "Requests that target nested resources are validated strictly
    left to right along the path."
    PRD §2.6: "Each identifier in the path is confirmed to exist before the next
    is examined, and the request is rejected with a 404 carrying `ERR_NOT_FOUND`
    at the first identifier that does not resolve."

    Design: Corner/validations/path_existence_checked_left_to_right
    """
    resp = api.list_fund_advisors(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_error_envelope_shape(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/error_envelope_shape
    """
    resp = api.get_fund(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
