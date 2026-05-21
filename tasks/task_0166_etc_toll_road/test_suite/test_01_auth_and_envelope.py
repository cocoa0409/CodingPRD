"""Authentication, role validity, and response-envelope tests.

PRD §2.1 governs header presence and role validation; PRD §2.2 fixes
the envelope shape.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_account_payload,
    create_account,
    create_toll_event_payload,
    is_iso8601_timestamp,
    make_account_holder_headers,
    setup_account_with_vehicle,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# PRD §2.1 — Missing headers
# ---------------------------------------------------------------------------
def test_missing_x_user_id_header_rejected(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_MISSING_AUTH`."

    Claim: a POST /accounts with X-User-Role but no X-User-ID → 401
    ERR_MISSING_AUTH.
    """
    res = api.create_account(create_account_payload(),
                             {"X-User-Role": "AgencyAdmin"})
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


def test_missing_x_user_role_header_rejected(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_MISSING_AUTH`."

    Claim: a POST /accounts with X-User-ID but no X-User-Role → 401
    ERR_MISSING_AUTH.
    """
    res = api.create_account(create_account_payload(),
                             {"X-User-ID": "anyone"})
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


def test_both_headers_missing_rejected(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_MISSING_AUTH`."

    Claim: a POST /accounts with no auth headers → 401 ERR_MISSING_AUTH.
    """
    res = api.create_account(create_account_payload(), {})
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


# ---------------------------------------------------------------------------
# PRD §2.1 — Invalid role
# ---------------------------------------------------------------------------
def test_invalid_role_string_rejected(api):
    """PRD §2.1: "A request whose `X-User-Role` value is not one of
    these three exact strings is rejected with `ERR_INVALID_ROLE`."

    Claim: X-User-Role = "Hacker" (not one of AccountHolder /
    AgencyAdmin / GantryOperator) → 401 ERR_INVALID_ROLE.
    """
    headers = {"X-User-ID": "anyone", "X-User-Role": "Hacker"}
    res = api.create_account(create_account_payload(), headers)
    validate_error(res, "ERR_INVALID_ROLE", expected_status=401)


# ---------------------------------------------------------------------------
# PRD §2.1 — Forbidden by role
# ---------------------------------------------------------------------------
def test_account_holder_cannot_create_account(api):
    """PRD §4 reserves POST /accounts to AgencyAdmin. PRD §2.1: "A
    request whose role is valid but not authorized for the endpoint in
    question (see §4) is rejected with `ERR_FORBIDDEN`."

    Claim: AccountHolder calling POST /accounts → 403 ERR_FORBIDDEN.
    """
    res = api.create_account(create_account_payload(),
                             TEST_USERS["account_holder_headers"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_gantry_operator_cannot_create_account(api):
    """PRD §4 reserves POST /accounts to AgencyAdmin. PRD §2.1: "A
    request whose role is valid but not authorized for the endpoint in
    question (see §4) is rejected with `ERR_FORBIDDEN`."

    Claim: GantryOperator calling POST /accounts → 403 ERR_FORBIDDEN.
    """
    res = api.create_account(create_account_payload(),
                             TEST_USERS["gantry_operator_headers"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_account_holder_cannot_create_toll_event(api):
    """PRD §4: POST /toll-events is reserved to GantryOperator. PRD
    §2.1: "A request whose role is valid but not authorized for the
    endpoint in question (see §4) is rejected with `ERR_FORBIDDEN`."

    Claim: AccountHolder calling POST /toll-events → 403 ERR_FORBIDDEN.
    """
    payload = create_toll_event_payload(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=100,
    )
    res = api.create_toll_event(payload, TEST_USERS["account_holder_headers"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_gantry_operator_cannot_void_toll_event(api):
    """PRD §4: POST /toll-events/{toll_event_id}/void is authorized for
    AgencyAdmin only.
    PRD §2.1: "A request whose role is valid but not authorized for
    the endpoint in question (see §4) is rejected with `ERR_FORBIDDEN`."

    Claim: GantryOperator calling void → 403 ERR_FORBIDDEN.
    """
    res = api.void_toll_event(NON_EXISTENT_UUID,
                              TEST_USERS["gantry_operator_headers"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------------
# PRD §2.1 — AccountHolder ownership cross-account
# ---------------------------------------------------------------------------
def test_account_holder_cannot_read_other_account(api):
    """PRD §2.1: "ownership checks on any resource that references an
    `Account` compare the resource's `account_id` field (directly, or
    through its parent `Violation` in the case of a `Fine`) to
    `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."

    Claim: AccountHolder with X-User-ID = A1.id reads /accounts/A2.id
    → 403 ERR_FORBIDDEN.
    """
    a1 = create_account()
    a2 = create_account()
    res = api.get_account(a2["id"], make_account_holder_headers(a1["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_account_holder_can_read_own_account(api):
    """PRD §2.1: "When `X-User-Role` is `AccountHolder`, `X-User-ID`
    is the `id` of the acting `Account`; ownership checks on any
    resource that references an `Account` compare the resource's
    `account_id` field (directly, or through its parent `Violation`
    in the case of a `Fine`) to `X-User-ID`, and a mismatch is
    rejected with `ERR_FORBIDDEN`."

    Claim: AccountHolder reading their own /accounts/{id} succeeds.
    """
    a = create_account()
    res = api.get_account(a["id"], make_account_holder_headers(a["id"]))
    data = validate_success(res, expected_status=200)
    assert data["id"] == a["id"]


# ---------------------------------------------------------------------------
# PRD §2.2 — Response envelope
# ---------------------------------------------------------------------------
def test_success_envelope_shape(api):
    """PRD §2.2: success envelope carries meta.api_request_id starting
    with 'req_', meta.api_request_timestamp as ISO 8601 UTC with three
    fractional digits, response_type 'object' for single, and data
    holding the resource.

    Claim: POST /accounts response envelope conforms to §2.2.
    """
    res = api.create_account(create_account_payload(),
                             TEST_USERS["agency_admin_headers"])
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body
    assert "data" in body
    assert body["response_type"] == "object"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_error_envelope_shape(api):
    """PRD §2.2: error envelope carries response_type 'error' and
    data.error_id / data.message.

    Claim: ERR_MISSING_AUTH response envelope conforms to §2.2.
    """
    res = api.create_account(create_account_payload(), {})
    assert res.status_code == 401
    body = res.json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]
    assert body["data"]["error_id"] == "ERR_MISSING_AUTH"


# ---------------------------------------------------------------------------
# PRD §2.5 — Left-to-right path resolution
# ---------------------------------------------------------------------------
def test_path_resolution_account_missing_first(api):
    """PRD §2.5: "If `account_id` cannot be located the request is
    rejected with `ERR_NOT_FOUND` before `transponder_id` is consulted."

    Claim: POST /accounts/{nonexistent}/transponders/{nonexistent}/bind
    → 404 ERR_NOT_FOUND.
    """
    res = api.bind_transponder(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        {"vehicle_id": NON_EXISTENT_UUID},
        TEST_USERS["agency_admin_headers"],
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_path_resolution_transponder_missing_second(api):
    """PRD §2.5: "only after the account is confirmed does the server
    look up the transponder."

    Claim: real account + nonexistent transponder → 404 ERR_NOT_FOUND.
    """
    a = create_account()
    res = api.bind_transponder(
        a["id"], NON_EXISTENT_UUID,
        {"vehicle_id": NON_EXISTENT_UUID},
        TEST_USERS["agency_admin_headers"],
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
