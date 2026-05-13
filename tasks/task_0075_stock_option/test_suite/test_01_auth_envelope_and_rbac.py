"""Authentication, RBAC, response envelope, and pagination (PRD §2.1–§2.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_and_activate_plan,
    create_option_plan_payload,
    setup_plan_batch_grantee,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Missing or invalid user-context headers (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [
    {},
    {"X-User-ID": "test-user-1"},
    {"X-User-Role": "PlanAdministrator"},
    {"X-User-ID": "", "X-User-Role": "PlanAdministrator"},
    {"X-User-ID": "test-user-1", "X-User-Role": ""},
])
def test_missing_or_empty_user_context_headers_rejected(api, headers):
    """PRD §2.1: "A request missing either header, or carrying an empty
    value in either header, is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
    """
    res = api.create_option_plan(create_option_plan_payload(), headers)
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
    )


# ---------------------------------------------------------------------------
# Role authorization (PRD §2.1, §4)
# ---------------------------------------------------------------------------
def test_plan_creation_requires_plan_administrator(api,
                                                   board_secretary_headers):
    """PRD §2.1: "If both headers are present but the role is not
    authorized for the requested endpoint per the RBAC matrix in §4,
    the request is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    PRD §4: POST /option-plans Authorized Role(s): PlanAdministrator.
    """
    res = api.create_option_plan(
        create_option_plan_payload(), board_secretary_headers,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_board_approve_rejects_plan_administrator(api,
                                                  plan_admin_headers,
                                                  board_secretary_headers,
                                                  shareholder_registrar_headers):
    """PRD §4: POST /grants/{grantId}/board-approve Authorized Role(s):
    BoardSecretary.
    PRD §2.1: "If both headers are present but the role is not authorized
    for the requested endpoint per the RBAC matrix in §4, the request is
    rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    from test_helpers import create_grant_payload
    grant_res = api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"]),
        plan_admin_headers,
    )
    grant = validate_success(grant_res, expected_status=201)
    res = api.board_approve_grant(grant["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_shareholder_approve_rejects_board_secretary(api,
                                                     plan_admin_headers,
                                                     board_secretary_headers):
    """PRD §4: POST /grants/{grantId}/shareholder-approve
    Authorized Role(s): ShareholderRegistrar.
    PRD §2.1: "If both headers are present but the role is not authorized
    for the requested endpoint per the RBAC matrix in §4, the request is
    rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    from test_helpers import create_grant_payload
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"]), plan_admin_headers,
    ), expected_status=201)
    validate_success(
        api.board_approve_grant(grant["id"], board_secretary_headers),
        expected_status=200,
    )
    res = api.shareholder_approve_grant(grant["id"], board_secretary_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# Standard envelopes (PRD §2.2)
# ---------------------------------------------------------------------------
def test_success_envelope_has_meta_and_data(api, plan_admin_headers):
    """PRD §2.2: success envelope has meta (api_request_id,
    api_request_timestamp), response_type ('object'|'array'), and data."""
    res = api.create_option_plan(
        create_option_plan_payload(), plan_admin_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body
    assert "response_type" in body
    assert body["response_type"] == "object"
    assert "data" in body
    assert body["meta"]["api_request_id"].startswith("req_")


def test_error_envelope_carries_error_id_and_message(api):
    """PRD §2.2: error envelope carries response_type='error' and
    data with error_id and message."""
    res = api.create_option_plan(create_option_plan_payload(), {})
    assert res.status_code == 400
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == (
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value
    )
    assert isinstance(body["data"]["message"], str)
    assert len(body["data"]["message"]) > 0


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def test_list_pagination_meta_fields(api, plan_admin_headers):
    """PRD §2.3: list responses carry limit, offset, total_count, has_more."""
    for _ in range(3):
        create_and_activate_plan()

    res = api.list_option_plans(plan_admin_headers, params={"limit": 2})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert isinstance(meta["total_count"], int)
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_list_limit_default_is_ten(api, plan_admin_headers):
    """PRD §2.3: "limit defaults to 10 and must lie between 1 and 100 inclusive."""
    res = api.list_option_plans(plan_admin_headers)
    _, meta = validate_paginated(res)
    assert meta["limit"] == 10


def test_offset_beyond_total_returns_empty_page(api, plan_admin_headers):
    """PRD §2.3: list endpoints accept offset; out-of-range offset yields
    empty data with has_more=false."""
    res = api.list_option_plans(
        plan_admin_headers, params={"offset": 9999, "limit": 5},
    )
    data, meta = validate_paginated(res)
    assert data == []
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# NOT FOUND (PRD §2.6)
# ---------------------------------------------------------------------------
def test_get_nonexistent_plan_returns_not_found(api, plan_admin_headers):
    """PRD §2.6: "Where a path contains multiple resource ids ... the
    outer id is resolved first; if it does not refer to any persisted row
    the response is ERR_NOT_FOUND."
    """
    res = api.get_option_plan(NON_EXISTENT_UUID, plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_nested_outer_id_not_found_does_not_examine_inner(api,
                                                           plan_admin_headers):
    """PRD §2.6: "if it does not refer to any persisted row the response
    is ERR_NOT_FOUND and the inner ids are not examined."
    """
    res = api.list_grant_batches(NON_EXISTENT_UUID, plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Grantee identity (PRD §2.1) — entity_backed
# ---------------------------------------------------------------------------
def test_grantee_identity_must_match_hr_employee_id(api, plan_admin_headers):
    """PRD §2.1: "When X-User-Role is Grantee, the X-User-ID equals the
    hr_employee_id of exactly one persisted Grantee row; ownership checks
    on any resource that references a Grantee ... compare the resource's
    foreign-key chain back to the Grantee row whose hr_employee_id equals
    X-User-ID. A grantee may only sign their own grant agreements..."
    """
    from test_helpers import (
        create_grant_and_drive_to_live,
        setup_plan_batch_grantee,
    )
    plan, batch, grantee = setup_plan_batch_grantee()
    # Drive grant up to SHAREHOLDER_APPROVED.
    from test_helpers import create_grant_payload, sign_agreement_payload
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], TEST_USERS["board_secretary_headers"]
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], TEST_USERS["shareholder_registrar_headers"]
    ), expected_status=200)

    # Attempt sign-agreement with a wrong-grantee X-User-ID.
    wrong_headers = build_user_headers("not-the-grantee", "Grantee")
    res = api.sign_agreement(
        grant["id"], wrong_headers, sign_agreement_payload(),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
