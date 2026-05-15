"""LimitAdjustmentRequest workflow — PRD §3.3."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    approve_adjustment,
    assert_limit_adjustment_request,
    create_pending_adjustment,
    make_risk_officer_headers,
    make_trader_headers,
    reject_adjustment,
    request_revision_adjustment,
    set_clock,
    setup_trader_with_limits,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_limit_adjustment_payload,
    patch_limit_adjustment_payload,
)


# ===========================================================================
# Create / PENDING status — PRD §3.3
# ===========================================================================
def test_create_adjustment_returns_pending(api):
    """PRD §3.3: "The request is created in `PENDING` status, with
    `requester_trader_id` copied from the caller's `X-User-ID` (which MUST
    equal the target limit's `trader_id`) and `approver_user_id` left null
    until a decision is recorded."

    Claim: a fresh request has status=PENDING, requester_trader_id ==
    trader.id, approver_user_id is null.
    """
    ctx = setup_trader_with_limits()
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
    )
    assert_limit_adjustment_request(req)
    assert req["status"] == "PENDING"
    assert req["requester_trader_id"] == ctx["trader"]["id"]
    assert req["approver_user_id"] is None


def test_expires_at_in_past_rejected_at_creation(api):
    """PRD §3.3: "a non-future `expires_at` at creation time is rejected
    with `ERR_EXPIRES_IN_PAST` (HTTP 422)."

    Claim: expires_at in the past → ERR_EXPIRES_IN_PAST, 422.
    """
    ctx = setup_trader_with_limits()
    res = api.create_limit_adjustment(
        create_limit_adjustment_payload(
            limit_id=ctx["intraday_limit"]["id"],
            requested_delta_usd=1_000_000.00,
            expires_at=TEST_DEFAULTS["EXPIRES_PAST"],
        ),
        ctx["trader_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_EXPIRES_IN_PAST.value, expected_status=422,
    )


# ===========================================================================
# Approve — PRD §3.3
# ===========================================================================
def test_approve_applies_temporary_override_to_limit(api):
    """PRD §3.3: "On a successful approval, the request's
    `requested_delta_usd` is added to the target
    `Limit.temporary_override_usd`, `Limit.utilization_pct` is recomputed
    against the new effective cap, the `approver_user_id` is set to the
    officer's `X-User-ID`."

    Claim: after approval the Limit.temporary_override_usd carries the
    delta and the request's approver_user_id is set.
    """
    ctx = setup_trader_with_limits(intraday_cap=5_000_000.00)
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
        requested_delta_usd=2_000_000.00,
    )
    approved = approve_adjustment(req["id"])
    assert approved["status"] == "APPROVED"
    assert approved["approver_user_id"], "approver_user_id must be recorded"
    # Verify the Limit row reflects the override.
    data = validate_success(
        api.list_limits(ctx["trader"]["id"], ctx["trader_headers"]), 200,
    )
    rows = data if isinstance(data, list) else (data.get("limits") or data)
    rows = rows if isinstance(rows, list) else [rows]
    intraday = next(r for r in rows if r["bucket"] == "INTRADAY")
    assert intraday["temporary_override_usd"] == 2_000_000.00


def test_self_approval_rejected_segregation(api):
    """PRD §3.3: "the officer's `X-User-ID` does NOT equal
    `requester_trader_id` (segregation of duties — self-approval is
    rejected with `ERR_SEGREGATION_VIOLATION`)."

    Claim: a RiskOfficer call whose X-User-ID equals the
    requester_trader_id is rejected with ERR_SEGREGATION_VIOLATION (403).

    Setup: opaque RiskOfficer header where X-User-ID == trader.id (which
    PRD §2.1 allows because RiskOfficer is opaque — it doesn't have to be
    an existing entity id, only NOT equal the requester's id).
    """
    ctx = setup_trader_with_limits()
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
    )
    spoofed = make_risk_officer_headers(ctx["trader"]["id"])
    res = api.approve_limit_adjustment(req["id"], spoofed)
    validate_error(
        res, ApiErrorId.ERR_SEGREGATION_VIOLATION.value, expected_status=403,
    )


def test_approve_expired_at_approval_time_rejected(api):
    """PRD §3.3: "a request whose `expires_at` has slipped past during the
    wait is rejected at approval time with `ERR_EXPIRES_IN_PAST`."

    Claim: clock advance past expires_at, then /approve → ERR_EXPIRES_IN_PAST.
    """
    set_clock("2026-05-13T10:00:00.000Z")
    ctx = setup_trader_with_limits(clock_iso="2026-05-13T10:00:00.000Z")
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
        expires_at="2026-05-13T11:00:00.000Z",
    )
    # Advance clock past expires_at.
    set_clock("2026-05-13T11:30:00.000Z")
    res = api.approve_limit_adjustment(
        req["id"],
        # Different X-User-ID from trader.id (opaque RiskOfficer).
        make_risk_officer_headers("ro-distinct"),
    )
    validate_error(
        res, ApiErrorId.ERR_EXPIRES_IN_PAST.value, expected_status=422,
    )


# ===========================================================================
# Reject — PRD §3.3
# ===========================================================================
def test_reject_transitions_to_rejected(api):
    """PRD §3.3: "Rejection transitions `PENDING` to `REJECTED` and likewise
    requires that the rejecter's `X-User-ID` differs from
    `requester_trader_id`; no side effect on the limit ensues, only an
    audit row."

    Claim: /reject on PENDING → status=REJECTED and Limit unchanged.
    """
    ctx = setup_trader_with_limits()
    initial_override = ctx["intraday_limit"]["temporary_override_usd"]
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
        requested_delta_usd=500_000.00,
    )
    rejected = reject_adjustment(req["id"])
    assert rejected["status"] == "REJECTED"
    # Limit unchanged.
    data = validate_success(
        api.list_limits(ctx["trader"]["id"], ctx["trader_headers"]), 200,
    )
    rows = data if isinstance(data, list) else (data.get("limits") or data)
    rows = rows if isinstance(rows, list) else [rows]
    intraday = next(r for r in rows if r["bucket"] == "INTRADAY")
    assert intraday["temporary_override_usd"] == initial_override


# ===========================================================================
# Revision cycle — PRD §3.3
# ===========================================================================
def test_revision_cycle_pending_to_revision_to_pending_to_approved(api):
    """PRD §3.3: "Sending the request back for revision transitions
    `PENDING` to `REVISION_REQUESTED`; ... From `REVISION_REQUESTED`, only
    the original requester (matched by `X-User-ID == requester_trader_id`)
    may resubmit, supplying updated `requested_delta_usd`, `justification`
    or `expires_at` and the entity's `version` for OCC; the request
    returns to `PENDING` and the cycle continues."

    Claim: the cycle PENDING → REVISION_REQUESTED → PENDING → APPROVED
    succeeds, and version increments at each transition.

    # difficulty: non_linear_state_machine/limit_adjustment_revision_cycle
    """
    ctx = setup_trader_with_limits()
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
        justification="initial",
    )
    v1 = req["version"]
    revision = request_revision_adjustment(req["id"])
    assert revision["status"] == "REVISION_REQUESTED"
    assert revision["version"] > v1
    v2 = revision["version"]
    # Trader resubmits via PATCH.
    res = api.patch_limit_adjustment(
        req["id"],
        patch_limit_adjustment_payload(
            version=v2, justification="vol-rev",
        ),
        make_trader_headers(ctx["trader"]["id"]),
    )
    resubmitted = validate_success(res, 200)
    assert resubmitted["status"] == "PENDING"
    assert resubmitted["version"] > v2
    final = approve_adjustment(req["id"])
    assert final["status"] == "APPROVED"


def test_resubmit_by_non_requester_rejected(api):
    """PRD §3.3: "From `REVISION_REQUESTED`, only the original requester
    (matched by `X-User-ID == requester_trader_id`) may resubmit".

    Claim: a PATCH attempted by a *different* trader id → either
    ERR_FORBIDDEN (priority 2 role check passes but ownership is
    requester-bound) or ERR_NOT_FOUND/SEGREGATION_VIOLATION. PRD names
    'only the original requester ... may resubmit', so the request is
    refused.

    PRD-faithful: any 403/404/409 outcome surfaces the right idea. We accept
    one of those three.
    """
    ctx = setup_trader_with_limits()
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
    )
    request_revision_adjustment(req["id"])
    # Make ANOTHER trader with a real id, and try to patch.
    ctx2 = setup_trader_with_limits()
    headers = make_trader_headers(ctx2["trader"]["id"])
    res = api.patch_limit_adjustment(
        req["id"],
        patch_limit_adjustment_payload(version=2, justification="hijack"),
        headers,
    )
    assert res.status_code in (403, 404, 409), (
        f"PRD §3.3: only requester may resubmit; got {res.status_code}"
    )


# ===========================================================================
# Already-decided sequential — PRD §3.3 / §2.11
# ===========================================================================
def test_second_approve_after_reject_returns_already_decided(api):
    """PRD §3.3: "Once a request leaves `PENDING`, it is terminal for the
    purposes of the approve/reject lane — a second concurrent decision
    finds the request already decided and is rejected with
    `ERR_REQUEST_ALREADY_DECIDED` (HTTP 409)."

    Claim: /reject then /approve on the same request → second call returns
    ERR_REQUEST_ALREADY_DECIDED.

    PRD §2.9 priority: state precedes other checks; PRD §3.3 names this
    specific code for the "already decided" condition.
    """
    ctx = setup_trader_with_limits()
    req = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
    )
    reject_adjustment(req["id"])
    res = api.approve_limit_adjustment(
        req["id"], make_risk_officer_headers("ro-second"),
    )
    validate_error(
        res, ApiErrorId.ERR_REQUEST_ALREADY_DECIDED.value, expected_status=409,
    )
