"""Dispatch-loop cycles, acceptance/cancel cascades, and offer-dispatch OCC tests.

Covers the DISPATCHING self-loop (decline-then-reoffer), the depth-3 accept cascade
(offer -> call -> provider), the depth-2 cancel compensation, offer idempotency and
outstanding-offer blocking, and the service-call version OCC token on dispatch.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_dispatching_call, setup_call_with_live_offer, setup_assigned_call,
    create_offer, create_provider,
    ApiErrorId, TEST_USERS, make_member_headers, make_provider_headers,
)

OP = TEST_USERS["dispatch_operator_headers"]


# =========================================================================
# Queue A — non_linear_state_machine (service-call cyclic re-dispatch)
# =========================================================================
def test_decline_returns_call_to_dispatching_and_reoffer_increments_attempts(api):
    """PRD §3.7: "the offered provider may decline it: the offer moves to `DECLINED`,
    the call stays in `DISPATCHING` and is thereby freed for the next offer, and no
    provider state changes."
    PRD §3.7: "Creating the offer increments the call's `dispatch_attempts` by one and
    increments the call's `version` by one."

    After decline, a second offer is dispatched, proving the DISPATCHING self-loop;
    dispatch_attempts reaches 2.

    Design: Difficulty/non_linear_state_machine/service_call_cyclic_redispatch_loop_decline_then_reoffer
    """
    ctx = setup_call_with_live_offer()
    pid = ctx["provider"]["id"]
    cid = ctx["call"]["id"]
    validate_success(api.decline_offer(cid, ctx["offer"]["id"], make_provider_headers(pid)))
    call_after = validate_success(api.get_service_call(cid, OP))
    assert call_after["status"] == "DISPATCHING", f"decline must keep DISPATCHING, got {call_after['status']}"
    offer2 = validate_success(
        api.create_offer(cid, {"provider_id": pid,
                               "expected_service_call_version": call_after["version"]}, OP),
        201,
    )
    final = validate_success(api.get_service_call(cid, OP))
    assert final["status"] == "DISPATCHING", f"second offer must keep DISPATCHING, got {final['status']}"
    assert final["dispatch_attempts"] == 2, f"expected 2 attempts, got {final['dispatch_attempts']}"
    assert offer2["status"] == "OFFERED", f"second offer should be OFFERED, got {offer2['status']}"


def test_redispatch_loop_second_offer_is_live(api):
    """PRD §3.7: "Dispatch is an offer-and-resolve cycle that keeps a call in
    `DISPATCHING` while operators try providers one at a time."

    A second case re-confirms the self-loop: after a decline the freshly dispatched
    offer is OFFERED on a still-DISPATCHING call.

    Design: Difficulty/non_linear_state_machine/service_call_cyclic_redispatch_loop_decline_then_reoffer
    """
    ctx = setup_call_with_live_offer()
    pid = ctx["provider"]["id"]
    cid = ctx["call"]["id"]
    validate_success(api.decline_offer(cid, ctx["offer"]["id"], make_provider_headers(pid)))
    v1 = validate_success(api.get_service_call(cid, OP))["version"]
    offer2 = validate_success(
        api.create_offer(cid, {"provider_id": pid, "expected_service_call_version": v1}, OP), 201,
    )
    assert offer2["status"] == "OFFERED"
    assert offer2["service_call_id"] == cid


# =========================================================================
# Queue A — transitive_cascade (accept depth-3)
# =========================================================================
def test_accept_offer_drives_depth3_cascade_to_provider_on_job(api):
    """PRD §3.7: "acceptance drives a three-hop cascade in which the offer first moves
    to `ACCEPTED`; because of that, the call moves from `DISPATCHING` to `ASSIGNED`
    and its `assigned_provider_id` is set to the offer's provider; and because of that,
    the now-assigned provider moves to `ON_JOB` and its `active_call_id` is set to this
    call."

    Design: Difficulty/transitive_cascade/accept_offer_depth3_offer_to_call_to_provider
    """
    ctx = setup_call_with_live_offer()
    pid = ctx["provider"]["id"]
    cid = ctx["call"]["id"]
    offer = validate_success(api.accept_offer(cid, ctx["offer"]["id"], make_provider_headers(pid)))
    assert offer["status"] == "ACCEPTED", f"hop1: offer should be ACCEPTED, got {offer['status']}"
    call = validate_success(api.get_service_call(cid, OP))
    assert call["status"] == "ASSIGNED", f"hop2: call should be ASSIGNED, got {call['status']}"
    assert call["assigned_provider_id"] == pid, "hop2: assigned_provider_id must be the offer's provider"
    provider = validate_success(api.get_service_provider(pid, OP))
    assert provider["status"] == "ON_JOB", f"hop3: provider should be ON_JOB, got {provider['status']}"
    assert provider["active_call_id"] == cid, "hop3: active_call_id must be this call"


def test_accept_offer_only_branch_that_mutates_provider(api):
    """PRD §3.7: "The offered provider may accept it, which is the only branch that
    mutates provider state"

    A second assertion of the accept cascade: the provider transitions to ON_JOB with
    active_call_id set, confirming the divergent acceptance branch.

    Design: Difficulty/transitive_cascade/accept_offer_depth3_offer_to_call_to_provider
    """
    ctx = setup_assigned_call()
    provider = validate_success(api.get_service_provider(ctx["provider"]["id"], OP))
    assert provider["status"] == "ON_JOB"
    assert provider["active_call_id"] == ctx["call"]["id"]


# =========================================================================
# Queue A — transitive_cascade (cancel depth-2 compensation)
# =========================================================================
def test_cancel_assigned_call_releases_provider_depth2(api):
    """PRD §3.9: "When the call is in `ASSIGNED`, cancellation drives a two-hop cascade:
    the call moves to `CANCELLED` and its `assigned_provider_id` is cleared, and because
    of that the previously assigned provider is released back to `AVAILABLE` with its
    `active_call_id` cleared — a compensating action that returns the held provider to
    the pool."

    Design: Difficulty/transitive_cascade/cancel_assigned_call_depth2_call_to_provider_release
    """
    ctx = setup_assigned_call()
    cid = ctx["call"]["id"]
    pid = ctx["provider"]["id"]
    call = validate_success(api.cancel_call(cid, make_member_headers(ctx["member"]["id"])))
    assert call["status"] == "CANCELLED", f"hop1: call should be CANCELLED, got {call['status']}"
    assert call["assigned_provider_id"] is None, "hop1: assigned_provider_id must be cleared"
    provider = validate_success(api.get_service_provider(pid, OP))
    assert provider["status"] == "AVAILABLE", f"hop2: provider should be AVAILABLE, got {provider['status']}"
    assert provider["active_call_id"] is None, "hop2: active_call_id must be cleared"


def test_cancel_assigned_call_compensation_distinct_from_accept(api):
    """PRD §3.9: "A member may cancel its own call while it is still being arranged.
    Cancellation is permitted from either `DISPATCHING` or `ASSIGNED`, and only by the
    call's own member."

    A second assertion: cancelling an ASSIGNED call leaves the call CANCELLED while the
    provider returns to the pool (AVAILABLE).

    Design: Difficulty/transitive_cascade/cancel_assigned_call_depth2_call_to_provider_release
    """
    ctx = setup_assigned_call()
    validate_success(api.cancel_call(ctx["call"]["id"], make_member_headers(ctx["member"]["id"])))
    provider = validate_success(api.get_service_provider(ctx["provider"]["id"], OP))
    assert provider["status"] == "AVAILABLE"


# =========================================================================
# Queue B — state_machines / OCC corners
# =========================================================================
def test_second_accept_on_accepted_offer_returns_invalid_state(api):
    """PRD §3.7: "Acceptance is permitted only when the offer is in `OFFERED`, the
    acting provider is the offer's provider, the parent call is still `DISPATCHING`,
    and the provider's `status` is `AVAILABLE`"

    Re-accepting an already-ACCEPTED offer (no longer OFFERED) is rejected.

    Design: Corner/state_machines/accept_offer_idempotency_second_accept_returns_invalid_state
    """
    ctx = setup_assigned_call()
    resp = api.accept_offer(ctx["call"]["id"], ctx["offer"]["id"], make_provider_headers(ctx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_second_dispatch_while_offer_outstanding_rejected(api):
    """PRD §3.7: "There must be no live offer already outstanding on the call: if a
    `DispatchOffer` in `OFFERED` status already exists for this call, the dispatch is
    rejected with `ERR_OFFER_ALREADY_OUTSTANDING`, because only one offer may be live
    at a time."

    Design: Corner/state_machines/offer_already_outstanding_blocks_second_dispatch
    """
    ctx = setup_call_with_live_offer()
    prov2 = create_provider(company_name="Bee Tow", current_lat=0.0, current_lng=0.05,
                            capabilities=["TOW"], rating=4.6)
    v1 = validate_success(api.get_service_call(ctx["call"]["id"], OP))["version"]
    resp = api.create_offer(ctx["call"]["id"],
                            {"provider_id": prov2["id"], "expected_service_call_version": v1}, OP)
    validate_error(resp, ApiErrorId.ERR_OFFER_ALREADY_OUTSTANDING.value)


def test_stale_call_version_on_offer_dispatch_rejected(api):
    """PRD §2.7: "if they differ — for example because another operator already
    dispatched an offer and thereby advanced the call's version — the dispatch is
    rejected with `ERR_STALE_CALL_VERSION` and an HTTP 412 status, preventing the
    operator from over-issuing a second live offer on top of one it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_call_version_on_offer_dispatch_rejected
    """
    ctx = setup_dispatching_call()
    cid = ctx["call"]["id"]
    pid = ctx["provider"]["id"]
    v0 = ctx["call"]["version"]
    offer1 = create_offer(cid, pid, v0)  # bumps version
    validate_success(api.decline_offer(cid, offer1["id"], make_provider_headers(pid)))
    resp = api.create_offer(cid, {"provider_id": pid, "expected_service_call_version": v0}, OP)
    validate_error(resp, ApiErrorId.ERR_STALE_CALL_VERSION.value)


def test_correct_call_version_on_offer_dispatch_succeeds_and_bumps_version(api):
    """PRD §2.7: "The server compares it against the call's current `version`. If they
    match, the dispatch proceeds"
    PRD §3.7: "Creating the offer increments the call's `dispatch_attempts` by one and
    increments the call's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_call_version_on_offer_dispatch_succeeds_and_bumps_version
    """
    ctx = setup_dispatching_call()
    cid = ctx["call"]["id"]
    offer = validate_success(
        api.create_offer(cid, {"provider_id": ctx["provider"]["id"],
                               "expected_service_call_version": ctx["call"]["version"]}, OP),
        201,
    )
    assert offer["status"] == "OFFERED", f"expected OFFERED, got {offer['status']}"
    call = validate_success(api.get_service_call(cid, OP))
    assert call["dispatch_attempts"] == 1, f"expected 1 attempt, got {call['dispatch_attempts']}"
    assert call["version"] == ctx["call"]["version"] + 1, \
        f"version should advance by 1, got {call['version']} from {ctx['call']['version']}"
