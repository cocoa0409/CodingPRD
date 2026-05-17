"""Tests for the authentication header contract, response envelope
shape, plan CRUD basics, and pagination defaults (PRD §2.1, §2.2,
§2.3, §2.4, §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    assert_plan,
    build_user_headers,
    create_and_activate_plan,
    create_draft_plan,
    create_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
def test_missing_both_auth_headers_rejected(api):
    """PRD §2.1: "A request that omits either header, or whose header
    values are malformed, is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Claim: a POST with no X-User-ID and no X-User-Role -> 400
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={"Content-Type": "application/json"},
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        expected_status=400,
    )


def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "A request that omits either header, or whose header
    values are malformed, is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Claim: missing X-User-ID alone -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={
            "X-User-Role": "PlanAdministrator",
            "Content-Type": "application/json",
        },
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        expected_status=400,
    )


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "A request that omits either header, or whose header
    values are malformed, is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Claim: missing X-User-Role alone -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={
            "X-User-ID": "some-id",
            "Content-Type": "application/json",
        },
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        expected_status=400,
    )


def test_unauthorized_role_for_plan_create_rejected(api):
    """PRD §2.1: "A request that presents valid headers but invokes an
    endpoint the role is not authorized to use is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Claim: POST /plans by PayrollProcessor -> ERR_INSUFFICIENT_PERMISSIONS
    (PRD §4: POST /plans authorized for PlanAdministrator only).
    """
    res = api.create_plan(
        create_plan_payload(),
        TEST_USERS["payroll_headers"],
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


# ===========================================================================
# Envelope — PRD §2.2
# ===========================================================================
def test_success_envelope_shape(api, admin_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body".

    Claim: response carries meta.api_request_id, meta.api_request_timestamp,
    response_type, and data.
    """
    res = api.create_plan(create_plan_payload(), admin_headers)
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body
    assert "response_type" in body
    assert "data" in body
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert body["response_type"] == "object"


def test_error_envelope_shape(api, admin_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow
    this standard envelope format".

    Claim: error payload has meta, response_type=='error', and
    data with error_id and message.
    """
    res = api.get_plan(NON_EXISTENT_UUID, admin_headers)
    assert 400 <= res.status_code < 500
    body = res.json()
    assert "meta" in body
    assert body.get("response_type") == "error"
    err = body["data"]
    assert isinstance(err.get("error_id"), str)
    assert isinstance(err.get("message"), str)
    assert err["message"].strip() != ""


# ===========================================================================
# Plan CRUD — PRD §3.1
# ===========================================================================
def test_create_plan_starts_in_draft_status(api, admin_headers):
    """PRD §3.1: "The newly created plan starts with status of DRAFT
    and current_vesting_epoch of zero."

    Claim: a freshly created plan returns status=='DRAFT' and
    current_vesting_epoch==0.
    """
    res = api.create_plan(create_plan_payload(), admin_headers)
    plan = validate_success(res, 201)
    assert_plan(plan)
    assert plan["status"] == "DRAFT"
    assert plan["current_vesting_epoch"] == 0


def test_create_plan_default_rmd_age_73(api, admin_headers):
    """PRD §2.11: "When the client omits rmd_age at create time, the
    server applies a default of 73."

    Claim: omitting rmd_age yields rmd_age == 73.
    """
    payload = create_plan_payload()
    payload.pop("rmd_age", None)
    res = api.create_plan(payload, admin_headers)
    plan = validate_success(res, 201)
    assert plan["rmd_age"] == 73


def test_create_tiered_plan_missing_brackets_rejected(api, admin_headers):
    """PRD §2.11: "A plan whose configuration is inconsistent with its
    declared formula (for example, TIERED with an empty bracket list)
    is rejected at create time with ERR_INVALID_PLAN_CONFIG."

    Claim: TIERED + empty tiered_brackets -> ERR_INVALID_PLAN_CONFIG.
    """
    payload = create_plan_payload(
        match_formula_type="TIERED",
        tiered_brackets=[],
    )
    res = api.create_plan(payload, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_PLAN_CONFIG.value,
        expected_status=400,
    )


def test_create_graded_plan_wrong_length_rejected(api, admin_headers):
    """PRD §2.11: "graded_percentages — an array of exactly seven
    integers each in the closed range zero through one hundred,
    strictly non-decreasing across positions zero through six, and
    terminating at exactly 100 in position six ... Configurations
    that violate any of these structural rules are rejected with
    ERR_INVALID_PLAN_CONFIG."

    Claim: GRADED with a 6-element array -> ERR_INVALID_PLAN_CONFIG.
    """
    payload = create_plan_payload(
        vesting_schedule_type="GRADED",
        cliff_years=None,
        graded_percentages=[0, 20, 40, 60, 80, 100],  # length 6
    )
    res = api.create_plan(payload, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_PLAN_CONFIG.value,
        expected_status=400,
    )


def test_create_graded_plan_terminal_not_100_rejected(api, admin_headers):
    """PRD §2.11: graded_percentages "terminating at exactly 100 in
    position six ... Configurations that violate any of these
    structural rules are rejected with ERR_INVALID_PLAN_CONFIG."

    Claim: GRADED whose [6] != 100 -> ERR_INVALID_PLAN_CONFIG.
    """
    payload = create_plan_payload(
        vesting_schedule_type="GRADED",
        cliff_years=None,
        graded_percentages=[0, 0, 20, 40, 60, 80, 90],  # ends at 90
    )
    res = api.create_plan(payload, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_PLAN_CONFIG.value,
        expected_status=400,
    )


def test_get_nonexistent_plan_returns_404_plan_not_found(api, admin_headers):
    """PRD §2.5: "The first identifier that does not resolve to an
    existing resource determines the rejection code: ERR_PLAN_NOT_FOUND".

    Claim: GET /plans/{non-existent-uuid} -> 404 ERR_PLAN_NOT_FOUND.
    """
    res = api.get_plan(NON_EXISTENT_UUID, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_PLAN_NOT_FOUND.value,
        expected_status=404,
    )


def test_activate_nondraft_plan_rejected_plan_not_draft(api, admin_headers):
    """PRD §3.1: "An attempt to activate a plan whose current status
    is anything other than DRAFT is rejected with ERR_PLAN_NOT_DRAFT."

    Claim: activating an already-ACTIVE plan -> ERR_PLAN_NOT_DRAFT.
    """
    plan = create_and_activate_plan()
    res = api.activate_plan(plan["id"], None, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_PLAN_NOT_DRAFT.value,
        expected_status=409,
    )


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
def test_list_plans_default_pagination(api, admin_headers):
    """PRD §2.3: "The limit parameter caps the number of items returned
    and defaults to 10 when omitted, with a minimum of 1 and a maximum
    of 100. The offset parameter is the number of rows to skip from
    the beginning of the result set and defaults to 0."

    Claim: list without params returns limit==10, offset==0.
    """
    # Create one plan so list is non-empty.
    create_draft_plan()
    data, meta = validate_paginated(api.list_plans(admin_headers))
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_list_plans_respects_limit_one(api, admin_headers):
    """PRD §2.3: limit caps the number of returned items.

    Claim: limit=1 yields at most 1 item; has_more is True when the
    server holds more than one plan.
    """
    # Create three plans.
    for _ in range(3):
        create_draft_plan()
    data, meta = validate_paginated(
        api.list_plans(admin_headers, params={"limit": 1}),
    )
    assert len(data) == 1
    assert meta["limit"] == 1
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True


def test_list_plans_offset_past_end(api, admin_headers):
    """PRD §2.3: offset skips rows.

    Claim: a very large offset returns no rows and has_more=False.
    """
    create_draft_plan()
    data, meta = validate_paginated(
        api.list_plans(admin_headers, params={"offset": 99999}),
    )
    assert len(data) == 0
    assert meta["has_more"] is False


# ===========================================================================
# Common fields — PRD §2.4
# ===========================================================================
def test_plan_carries_version_one_or_zero(api, admin_headers):
    """PRD §2.4: "version (integer): monotonic counter starting at 1
    (or 0, per the implementation's chosen initial value, as long as it
    strictly increases) and incremented by exactly one on every
    mutation of the resource."

    Claim: a newly created plan carries an integer version field.
    """
    res = api.create_plan(create_plan_payload(), admin_headers)
    plan = validate_success(res, 201)
    assert isinstance(plan["version"], int)
    assert plan["version"] in (0, 1)


def test_plan_version_increments_on_activate(api, admin_headers):
    """PRD §2.4: "version ... incremented by exactly one on every
    mutation of the resource."

    Claim: activate (DRAFT -> ACTIVE) increments version by one.
    """
    res = api.create_plan(create_plan_payload(), admin_headers)
    plan = validate_success(res, 201)
    old_v = plan["version"]
    res2 = api.activate_plan(plan["id"], None, admin_headers)
    activated = validate_success(res2, 200)
    assert activated["version"] == old_v + 1
