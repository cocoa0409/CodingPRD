"""Validation-precedence, quota-boundary, and business-rule rejection tests.

Covers state-beats-business and capability-beats-availability precedence; the annual
incident-quota boundary (success at limit-1, failure at limit); the provider-availability
cross-entity dependency on offer dispatch; and the membership-active / dispatch-cap /
claim-target / pagination business rejections.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_dispatching_call, setup_plan_member_provider,
    create_call, create_offer, create_provider,
    set_clock, create_plan, create_member,
    ApiErrorId, TEST_USERS, make_member_headers, make_provider_headers,
)

OP = TEST_USERS["dispatch_operator_headers"]


def _drive_to_completed(api, member_id, provider_id):
    """Open a TOW call for member, dispatch+accept+start+complete it. Returns call id."""
    call = create_call(member_id, "TOW")
    offer = create_offer(call["id"], provider_id, call["version"])
    validate_success(api.accept_offer(call["id"], offer["id"], make_provider_headers(provider_id)))
    validate_success(api.start_call(call["id"], make_provider_headers(provider_id)))
    validate_success(api.complete_call(call["id"], {"final_towed_miles": 20}, make_provider_headers(provider_id)))
    return call["id"]


def _drive_to_assigned(api, member_id, provider_id):
    call = create_call(member_id, "TOW")
    offer = create_offer(call["id"], provider_id, call["version"])
    validate_success(api.accept_offer(call["id"], offer["id"], make_provider_headers(provider_id)))
    return call["id"]


def _drive_to_en_route(api, member_id, provider_id):
    cid = _drive_to_assigned(api, member_id, provider_id)
    validate_success(api.start_call(cid, make_provider_headers(provider_id)))
    return cid


# =========================================================================
# Queue A — priority_pair_validation_conflict
# =========================================================================
def test_complete_assigned_call_at_quota_returns_invalid_state_not_annual(api):
    """PRD §2.9: "State legality comes fifth: an operation attempted from a state in
    which the transition is not defined yields `ERR_INVALID_STATE`. Only after these
    five gates do the domain-specific business rules described throughout §3 run"

    annual_limit=1; member already at the limit (1 COMPLETED). A second call is only
    ASSIGNED (not EN_ROUTE) when completion is attempted: the state check (fifth)
    fires before the annual fiscal business rule.

    Design: Difficulty/priority_pair_validation_conflict/complete_state_beats_annual_fiscal
    """
    ctx = setup_plan_member_provider(plan_overrides={"tier": "BASIC", "annual_service_limit": 1, "priority_weight": 5})
    mid = ctx["member"]["id"]
    pid = ctx["provider"]["id"]
    _drive_to_completed(api, mid, pid)            # member now at the limit (used=1)
    call2_id = _drive_to_assigned(api, mid, pid)  # second call only ASSIGNED, not EN_ROUTE
    resp = api.complete_call(call2_id, {"final_towed_miles": 20}, make_provider_headers(pid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_offer_to_busy_incapable_provider_returns_capability_mismatch(api):
    """PRD §3.7: "Among these business rules the capability check precedes the
    provider-availability check, which precedes the outstanding-offer check, which
    precedes the attempts-cap check, which precedes the version check."

    The target provider both lacks the TOW capability AND is ON_JOB (unavailable):
    the capability check outranks availability, so ERR_CAPABILITY_MISMATCH is returned.

    Design: Difficulty/priority_pair_validation_conflict/offer_capability_safety_beats_provider_unavailable_referential
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"])
    # JUMP-only provider, made busy on a JUMP call so it is ON_JOB (unavailable).
    jprov = create_provider(company_name="Jump Only", current_lat=0.0, current_lng=0.05,
                            capabilities=["JUMP"], rating=4.0)
    jcall = create_call(member["id"], "JUMP")
    joffer = create_offer(jcall["id"], jprov["id"], jcall["version"])
    validate_success(api.accept_offer(jcall["id"], joffer["id"], make_provider_headers(jprov["id"])))
    # Now a TOW call dispatched to that JUMP-only, ON_JOB provider.
    tcall = create_call(member["id"], "TOW")
    resp = api.create_offer(tcall["id"],
                            {"provider_id": jprov["id"], "expected_service_call_version": tcall["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISMATCH.value)


def test_offline_incapable_provider_offer_returns_capability_mismatch(api):
    """PRD §3.7: "The target provider must be capable of the requested service: if the
    provider's `capabilities` do not include the call's `service_type`, the dispatch is
    rejected with `ERR_CAPABILITY_MISMATCH`. The target provider must be available: if
    its `status` is not `AVAILABLE`, the dispatch is rejected with
    `ERR_PROVIDER_UNAVAILABLE`."

    A second capability-beats-availability assertion: a provider that both lacks the TOW
    capability AND is OFFLINE (unavailable) is rejected with the higher-priority
    capability error, not the availability error.

    Design: Difficulty/priority_pair_validation_conflict/offer_capability_safety_beats_provider_unavailable_referential
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"])
    jprov = create_provider(company_name="Jump Only", current_lat=0.0, current_lng=0.05,
                            capabilities=["JUMP"], rating=4.0)
    validate_success(api.provider_go_offline(jprov["id"], make_provider_headers(jprov["id"])))
    tcall = create_call(member["id"], "TOW")
    resp = api.create_offer(tcall["id"],
                            {"provider_id": jprov["id"], "expected_service_call_version": tcall["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISMATCH.value)


# =========================================================================
# Queue A — boundary_precision_check (annual quota)
# =========================================================================
def test_complete_at_limit_minus_one_succeeds_and_reaches_limit(api):
    """PRD §3.8: "The boundary is inclusive of success up to the limit: a member who
    has used one fewer than the limit completes successfully and is brought exactly to
    the limit, whereas a member already at the limit is rejected."

    annual_limit=2, used=1 (== limit-1): completion succeeds and brings used to 2.

    Design: Difficulty/boundary_precision_check/annual_limit_boundary_used_equals_limit_minus_one_succeeds
    """
    ctx = setup_plan_member_provider(plan_overrides={"annual_service_limit": 2})
    mid = ctx["member"]["id"]
    pid = ctx["provider"]["id"]
    _drive_to_completed(api, mid, pid)            # used = 1
    call2_id = _drive_to_en_route(api, mid, pid)  # second call EN_ROUTE
    data = validate_success(api.complete_call(call2_id, {"final_towed_miles": 20}, make_provider_headers(pid)))
    assert data["status"] == "COMPLETED", f"expected COMPLETED at limit-1, got {data['status']}"
    member = validate_success(api.get_member(mid, OP))
    assert member["services_used_this_year"] == 2, \
        f"used should reach limit 2, got {member['services_used_this_year']}"


def test_dispatch_candidate_radius_boundary_includes_at_or_below_fifty(api):
    """PRD §3.6: "the haversine distance from the provider's current location to the
    call's breakdown location is no greater than the maximum dispatch radius of 50
    miles"

    NEAR provider at 48.365mi (<=50) is included; FAR provider at 51.820mi (>50) is
    excluded — the empty-vs-nonempty edge of the radius filter.

    Design: Difficulty/boundary_precision_check/dispatch_candidates_radius_boundary_at_or_below_fifty_miles_included
    """
    from test_helpers import make_call_for_candidates, add_provider_with_shift
    ctx = make_call_for_candidates(service_type="JUMP")
    near = add_provider_with_shift(0.0, 0.70, ["JUMP"], 4.0, "Near Co")
    add_provider_with_shift(0.0, 0.75, ["JUMP"], 4.0, "Far Co")
    data, meta = _candidates(api, ctx["call"]["id"])
    assert len(data) == 1, f"only NEAR (<=50mi) should be eligible, got {len(data)}"
    assert data[0]["id"] == near["id"], "the included candidate must be the NEAR provider"


def test_complete_below_limit_keeps_completion_open(api):
    """PRD §3.8: "the member's `services_used_this_year` must be strictly fewer than the
    plan's `annual_service_limit` at the moment of completion."

    A second boundary assertion: with annual_limit=2 and used=0 (strictly below), the
    first completion succeeds and the used count advances to 1, still below the limit.

    Design: Difficulty/boundary_precision_check/annual_limit_boundary_used_equals_limit_minus_one_succeeds
    """
    ctx = setup_plan_member_provider(plan_overrides={"annual_service_limit": 2})
    mid = ctx["member"]["id"]
    pid = ctx["provider"]["id"]
    call_id = _drive_to_en_route(api, mid, pid)
    data = validate_success(api.complete_call(call_id, {"final_towed_miles": 20}, make_provider_headers(pid)))
    assert data["status"] == "COMPLETED", f"expected COMPLETED below limit, got {data['status']}"
    member = validate_success(api.get_member(mid, OP))
    assert member["services_used_this_year"] == 1, \
        f"used should advance to 1, got {member['services_used_this_year']}"


def test_dispatch_candidate_radius_boundary_excludes_above_fifty(api):
    """PRD §3.6: "When no provider satisfies the eligibility filter, the ranked pool is
    the empty list, and the operator's recourse is to abandon the call."

    The exclusion side of the radius edge: a lone FAR provider at 51.820mi (>50) is
    excluded, leaving an empty ranked pool.

    Design: Difficulty/boundary_precision_check/dispatch_candidates_radius_boundary_at_or_below_fifty_miles_included
    """
    from test_helpers import make_call_for_candidates, add_provider_with_shift
    ctx = make_call_for_candidates(service_type="JUMP")
    add_provider_with_shift(0.0, 0.75, ["JUMP"], 4.0, "Far Co")
    data, meta = _candidates(api, ctx["call"]["id"])
    assert len(data) == 0, f"FAR (>50mi) provider must be excluded, got {len(data)} candidates"


def _candidates(api, call_id):
    from test_helpers import validate_paginated
    resp = api.get_dispatch_candidates(call_id, OP)
    return validate_paginated(resp)


# =========================================================================
# Queue A — cross_entity_state_dependency (offer requires provider available)
# =========================================================================
def test_offer_dispatch_to_offline_provider_rejected(api):
    """PRD §3.7: "The target provider must be available: if its `status` is not
    `AVAILABLE`, the dispatch is rejected with `ERR_PROVIDER_UNAVAILABLE`."

    A TOW-capable provider that has gone OFFLINE: the call's offer dispatch depends on
    provider state and is rejected.

    Design: Difficulty/cross_entity_state_dependency/offer_dispatch_requires_provider_available_call_depends_on_provider
    """
    ctx = setup_plan_member_provider()
    pid = ctx["provider"]["id"]
    validate_success(api.provider_go_offline(pid, make_provider_headers(pid)))
    call = create_call(ctx["member"]["id"], "TOW")
    resp = api.create_offer(call["id"],
                            {"provider_id": pid, "expected_service_call_version": call["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_UNAVAILABLE.value)


def test_call_transition_depends_on_provider_availability(api):
    """PRD §3.7: "The target provider must be available: if its `status` is not
    `AVAILABLE`, the dispatch is rejected with `ERR_PROVIDER_UNAVAILABLE`."

    A second assertion of the ServiceCall -> ServiceProvider dependency: dispatching to
    an OFFLINE provider (which lacks no capability) is still rejected.

    Design: Difficulty/cross_entity_state_dependency/offer_dispatch_requires_provider_available_call_depends_on_provider
    """
    ctx = setup_plan_member_provider(provider_overrides={"capabilities": ["TOW", "JUMP"]})
    pid = ctx["provider"]["id"]
    validate_success(api.provider_go_offline(pid, make_provider_headers(pid)))
    call = create_call(ctx["member"]["id"], "TOW")
    resp = api.create_offer(call["id"],
                            {"provider_id": pid, "expected_service_call_version": call["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_UNAVAILABLE.value)


# =========================================================================
# Queue B — validations (business rejections)
# =========================================================================
def test_create_call_for_suspended_member_rejected(api):
    """PRD §3.2: "Before a service call may be created, the requesting member's
    `status` must be `ACTIVE`; a call requested for a member whose status is not
    `ACTIVE` is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`."

    Design: Corner/validations/create_call_for_suspended_member_returns_membership_not_active
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"], full_name="Sus Member")
    validate_success(api.suspend_member(member["id"], OP))
    resp = api.create_service_call(
        {"member_id": member["id"], "service_type": "JUMP", "breakdown_lat": 0.0, "breakdown_lng": 0.0},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_dispatch_limit_reached_after_three_attempts(api):
    """PRD §3.7: "The call must not have exhausted its re-offer budget:
    `dispatch_attempts` must be strictly fewer than the cap of three before another
    offer is created, and otherwise the dispatch is rejected with
    `ERR_DISPATCH_LIMIT_REACHED`."

    Three decline-then-reoffer cycles bring dispatch_attempts to 3; the fourth dispatch
    is rejected.

    Design: Corner/validations/dispatch_limit_reached_after_max_attempts
    """
    ctx = setup_dispatching_call()
    cid = ctx["call"]["id"]
    pid = ctx["provider"]["id"]
    v = ctx["call"]["version"]
    for _ in range(3):
        offer = create_offer(cid, pid, v)
        validate_success(api.decline_offer(cid, offer["id"], make_provider_headers(pid)))
        v = validate_success(api.get_service_call(cid, OP))["version"]
    resp = api.create_offer(cid, {"provider_id": pid, "expected_service_call_version": v}, OP)
    validate_error(resp, ApiErrorId.ERR_DISPATCH_LIMIT_REACHED.value)


def test_complete_over_annual_limit_rejected(api):
    """PRD §3.8: "A member whose used count has already reached the limit is rejected
    with `ERR_ANNUAL_LIMIT_EXCEEDED`."

    annual_limit=1; member already has one COMPLETED call. Completing a second
    EN_ROUTE call is rejected.

    Design: Corner/validations/annual_limit_exceeded_on_complete_failure_path
    """
    ctx = setup_plan_member_provider(plan_overrides={"tier": "BASIC", "annual_service_limit": 1, "priority_weight": 5})
    mid = ctx["member"]["id"]
    pid = ctx["provider"]["id"]
    _drive_to_completed(api, mid, pid)            # used = 1 (at limit)
    call2_id = _drive_to_en_route(api, mid, pid)  # second call EN_ROUTE
    resp = api.complete_call(call2_id, {"final_towed_miles": 20}, make_provider_headers(pid))
    validate_error(resp, ApiErrorId.ERR_ANNUAL_LIMIT_EXCEEDED.value)


def test_claim_against_other_members_call_rejected(api):
    """PRD §3.10: "a claim whose `service_call_id` references a call not owned by the
    filing member, or whose `claimed_amount_cents` is below 1, is rejected with
    `ERR_INVALID_CLAIM_TARGET`."

    Member A owns a COMPLETED call; member B files a claim against it.

    Design: Corner/validations/claim_against_other_members_call_returns_invalid_claim_target
    """
    ctx = setup_plan_member_provider()
    plan_id = ctx["plan"]["id"]
    mem_a = ctx["member"]["id"]
    pid = ctx["provider"]["id"]
    mem_b = create_member(plan_id, full_name="Member B")["id"]
    call_id = _drive_to_completed(api, mem_a, pid)
    resp = api.create_claim(
        {"member_id": mem_b, "service_call_id": call_id, "claimed_amount_cents": 1000},
        make_member_headers(mem_b),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_TARGET.value)


def test_list_members_invalid_pagination_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    GET /members?limit=0 is below the minimum of 1.

    Design: Corner/validations/list_members_invalid_pagination_returns_error
    """
    resp = api.list_members(OP, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)
