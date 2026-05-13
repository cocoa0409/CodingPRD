"""Option Plan lifecycle: create / activate / close / clock (PRD §3.1)."""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_option_plan_payload,
    advance_clock_by_seconds,
    assert_option_plan,
    clock_advance_payload,
    create_and_activate_plan,
    create_and_open_batch,
    create_grant_payload,
    create_option_plan_payload,
    register_grantee,
    validate_error,
    validate_success,
)


def test_create_option_plan_returns_draft_with_zero_reserved(api,
                                                              plan_admin_headers):
    """PRD §3.1: "The plan is created in DRAFT with status set to DRAFT,
    pool_reserved_options initialized to zero, and current_clock_ts left
    unset."
    """
    res = api.create_option_plan(
        create_option_plan_payload(
            pool_total_options=5000, jurisdiction_code="US",
        ),
        plan_admin_headers,
    )
    plan = validate_success(res, expected_status=201)
    assert_option_plan(plan)
    assert plan["status"] == "DRAFT"
    assert plan["pool_total_options"] == 5000
    assert plan["pool_reserved_options"] == 0
    assert plan["jurisdiction_code"] == "US"


def test_activate_plan_transitions_to_active(api, plan_admin_headers):
    """PRD §3.1: "Activation by the same administrator transitions the
    plan from DRAFT to ACTIVE..."
    """
    create_res = api.create_option_plan(
        create_option_plan_payload(), plan_admin_headers,
    )
    plan = validate_success(create_res, expected_status=201)
    res = api.activate_option_plan(
        plan["id"], plan_admin_headers, activate_option_plan_payload(),
    )
    activated = validate_success(res, expected_status=200)
    assert activated["status"] == "ACTIVE"
    assert activated["current_clock_ts"] is not None


def test_activate_rejects_zero_pool_total(api, plan_admin_headers):
    """PRD §3.1: "Activation by the same administrator ... is only
    allowed when pool_total_options is at least one — otherwise
    ERR_INVALID_REQUEST is returned."
    """
    # pool_total_options must be a positive integer at creation per
    # PRD §3.1, but the activation check fires when the value would be
    # <1 at activation time.
    res = api.create_option_plan(
        create_option_plan_payload(pool_total_options=0),
        plan_admin_headers,
    )
    # Server rejects either at create (negative pool) or at activate.
    if res.status_code == 422:
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
    else:
        plan = validate_success(res, expected_status=201)
        act_res = api.activate_option_plan(
            plan["id"], plan_admin_headers,
            activate_option_plan_payload(),
        )
        validate_error(act_res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_close_blocked_by_pending_grant(api, plan_admin_headers,
                                        board_secretary_headers):
    """PRD §3.1: "an administrator transitioning the plan from ACTIVE to
    CLOSED is rejected with ERR_PENDING_GRANTS_EXIST if any grant under
    the plan is currently in DRAFT, BOARD_APPROVED, or SHAREHOLDER_APPROVED."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    # Grant in DRAFT — close must fail.
    res = api.close_option_plan(plan["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_PENDING_GRANTS_EXIST.value)
    assert grant["status"] == "DRAFT"


def test_close_blocked_by_board_approved_grant(api, plan_admin_headers,
                                                board_secretary_headers):
    """PRD §3.1: "rejected with ERR_PENDING_GRANTS_EXIST if any grant
    under the plan is currently in DRAFT, BOARD_APPROVED, or
    SHAREHOLDER_APPROVED."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    res = api.close_option_plan(plan["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_PENDING_GRANTS_EXIST.value)


def test_close_empty_plan_succeeds(api, plan_admin_headers):
    """PRD §3.1: "After a successful close, every SCHEDULED-or-OPEN
    exercise window under the plan is flipped to CLOSED..."
    A plan with no grants/applications can close.
    """
    plan = create_and_activate_plan()
    res = api.close_option_plan(plan["id"], plan_admin_headers)
    closed = validate_success(res, expected_status=200)
    assert closed["status"] == "CLOSED"


def test_clock_advance_moves_current_clock_ts_forward(api,
                                                       plan_admin_headers):
    """PRD §3.1: "the administrator-only clock-advance capability, which
    adds a supplied by_seconds integer to current_clock_ts..."
    """
    plan = create_and_activate_plan()
    before_ts = plan["current_clock_ts"]
    res = api.advance_clock(
        plan["id"], clock_advance_payload(3600), plan_admin_headers,
    )
    after = validate_success(res, expected_status=200)
    before = _dt.datetime.fromisoformat(
        before_ts.replace("Z", "+00:00"),
    )
    after_dt = _dt.datetime.fromisoformat(
        after["current_clock_ts"].replace("Z", "+00:00"),
    )
    assert (after_dt - before).total_seconds() == 3600


def test_pool_remaining_equals_total_minus_reserved(api, plan_admin_headers):
    """PRD §3.1: "pool_remaining_options is pool_total_options minus
    pool_reserved_options; both fields are recomputed on read..."
    """
    plan = create_and_activate_plan(pool_total_options=10_000)
    assert plan["pool_remaining_options"] == (
        plan["pool_total_options"] - plan["pool_reserved_options"]
    )


def test_version_increments_on_activate(api, plan_admin_headers):
    """PRD §2.4: "Resources ... carry ... an integer version that begins
    at 1 and increments by exactly one on every successful state-changing
    mutation."
    """
    res = api.create_option_plan(
        create_option_plan_payload(), plan_admin_headers,
    )
    plan = validate_success(res, expected_status=201)
    initial_version = plan["version"]
    activated = validate_success(api.activate_option_plan(
        plan["id"], plan_admin_headers,
    ), expected_status=200)
    assert activated["version"] == initial_version + 1


def test_version_mismatch_rejected_on_supplied_version(api,
                                                       plan_admin_headers):
    """PRD §2.5: "When present, the server compares it to the row's
    current version before applying the mutation; on mismatch the
    request is rejected with ERR_VERSION_MISMATCH and no side effects fire."
    """
    res = api.create_option_plan(
        create_option_plan_payload(), plan_admin_headers,
    )
    plan = validate_success(res, expected_status=201)
    payload = activate_option_plan_payload()
    payload["version"] = plan["version"] + 99
    res = api.activate_option_plan(plan["id"], plan_admin_headers, payload)
    validate_error(res, ApiErrorId.ERR_VERSION_MISMATCH.value)
