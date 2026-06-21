"""Listing / reverse-reachability, RBAC denial, and immediate-consistency tests."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_call_with_live_offer, setup_completed_call, setup_depot_with_reservation,
    set_clock, create_plan, create_member, create_provider, create_call, create_shift,
    file_claim,
    ApiErrorId, TEST_USERS, make_member_headers, make_provider_headers,
)

OP = TEST_USERS["dispatch_operator_headers"]


# =========================================================================
# Queue B — endpoints (listing / reverse-reachability)
# =========================================================================
def test_list_service_calls_paginated_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the four pagination
    fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count`
    reflects the total number of matching resources before the limit/offset window is
    applied and `has_more` indicates whether further pages remain."

    Design: Corner/endpoints/list_service_calls_paginated_envelope
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"])
    call = create_call(member["id"], "JUMP")
    data, meta = validate_paginated(api.list_service_calls(OP, params={"member_id": member["id"]}))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"
    assert data[0]["id"] == call["id"]


def test_list_offers_for_call_reverse_reachability(api):
    """PRD §4: endpoint "GET `/service-calls/{id}/offers` List offers made for a call".
    PRD §3.7: "The offer records `service_call_id`, `provider_id`, the computed
    `offer_distance_miles` (haversine from the provider's current location to the
    breakdown), and the computed `eta_minutes` (§2.5)."

    Design: Corner/endpoints/list_offers_for_call_reverse_reachability
    """
    ctx = setup_call_with_live_offer()
    data, meta = validate_paginated(api.list_call_offers(ctx["call"]["id"], OP))
    assert data[0]["id"] == ctx["offer"]["id"]
    assert data[0]["service_call_id"] == ctx["call"]["id"]


def test_list_members_by_plan_reverse_reachability(api):
    """PRD §3.2: "operators may list members filtered by `plan_id` or `status`."

    Design: Corner/endpoints/list_members_by_plan_reverse_reachability
    """
    plan = create_plan()
    member = create_member(plan["id"])
    data, meta = validate_paginated(api.list_members(OP, params={"plan_id": plan["id"]}))
    assert data[0]["id"] == member["id"]
    assert data[0]["plan_id"] == plan["id"]


def test_list_bay_reservations_by_call_reverse_reachability(api):
    """PRD §3.4: "Reservations are listable under a depot, filterable by `status` and by
    `service_call_id`, and the same reservations are reachable beneath their tow call by
    `service_call_id`."

    Design: Corner/endpoints/list_bay_reservations_by_call_reverse_reachability
    """
    ctx = setup_depot_with_reservation(bay_count=3, cleanup_buffer_minutes=0)
    data, meta = validate_paginated(
        api.list_depot_bay_reservations(ctx["depot"]["id"], OP, params={"service_call_id": ctx["call"]["id"]})
    )
    assert data[0]["id"] == ctx["reservation"]["id"]
    assert data[0]["service_call_id"] == ctx["call"]["id"]


def test_list_provider_shifts_reverse_reachability(api):
    """PRD §3.3: "A provider's shifts are listable (reverse lookup by `provider_id`)
    with an optional `status` filter."

    Design: Corner/endpoints/list_provider_shifts_reverse_reachability
    """
    set_clock("2026-06-01T07:00:00Z")
    prov = create_provider()
    shift = create_shift(prov["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    data, meta = validate_paginated(api.list_shifts(prov["id"], OP))
    assert data[0]["id"] == shift["id"]
    assert data[0]["provider_id"] == prov["id"]


def test_list_provider_offers_reverse_reachability(api):
    """PRD §4: endpoint "GET `/service-providers/{id}/offers` List offers ever sent to
    this provider".
    PRD §3.7: "The offer records `service_call_id`, `provider_id`"

    Design: Corner/endpoints/list_provider_offers_reverse_reachability
    """
    ctx = setup_call_with_live_offer()
    data, meta = validate_paginated(api.list_provider_offers(ctx["provider"]["id"], OP))
    assert data[0]["id"] == ctx["offer"]["id"]
    assert data[0]["provider_id"] == ctx["provider"]["id"]


def test_list_claims_by_member_reverse_reachability(api):
    """PRD §3.10: "Claims are fetchable by the owning member or an operator and listable
    filtered by `member_id`, `service_call_id`, or `status`."

    Design: Corner/endpoints/list_claims_by_member_reverse_reachability
    """
    ctx = setup_completed_call(final_towed_miles=20)
    claim = file_claim(ctx["member"]["id"], ctx["call"]["id"], 1500)
    data, meta = validate_paginated(api.list_claims(OP, params={"member_id": ctx["member"]["id"]}))
    assert data[0]["id"] == claim["id"]
    assert data[0]["member_id"] == ctx["member"]["id"]


# =========================================================================
# Queue B — rbac
# =========================================================================
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one of
    these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_membership_plan(
        {"tier": "PLUS", "annual_service_limit": 4, "per_incident_mileage_cap_miles": 5,
         "overage_rate_cents_per_mile": 200, "priority_weight": 20,
         "covered_service_types": ["TOW"], "base_service_fee_cents": 0},
        {},  # no auth headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_member_cannot_create_plan_forbidden_role(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.1: "creation is reserved to the operator."

    Design: Corner/rbac/member_cannot_create_plan_forbidden_role
    """
    plan = create_plan()
    member = create_member(plan["id"])
    resp = api.create_membership_plan(
        {"tier": "BASIC", "annual_service_limit": 2, "per_incident_mileage_cap_miles": 3,
         "overage_rate_cents_per_mile": 300, "priority_weight": 5,
         "covered_service_types": ["JUMP"], "base_service_fee_cents": 9000},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_member_cannot_cancel_another_members_call_not_owner(api):
    """PRD §2.1: "ownership checks on any resource that references a member compare that
    resource's member reference to `X-User-ID` — a member may act only on its own
    service calls and its own reimbursement claims."
    PRD §2.1: "When an operation requires resource ownership and the acting member or
    provider does not own the targeted resource, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/member_cannot_cancel_another_members_call_not_owner
    """
    plan = create_plan()
    mem_a = create_member(plan["id"], full_name="Member A")
    mem_b = create_member(plan["id"], full_name="Member B")
    call = create_call(mem_a["id"], "JUMP")
    resp = api.cancel_call(call["id"], make_member_headers(mem_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_wrong_provider_cannot_accept_offer_not_owner(api):
    """PRD §2.1: "ownership checks compare the relevant provider reference (the offer's
    provider, the call's assigned provider, or the shift's provider) to `X-User-ID`."

    A provider that is not the offer's provider attempts to accept it.

    Design: Corner/rbac/wrong_provider_cannot_accept_offer_not_owner
    """
    ctx = setup_call_with_live_offer()
    other = create_provider(company_name="Prov Two", current_lat=0.0, current_lng=0.05,
                            capabilities=["TOW"], rating=4.6)
    resp = api.accept_offer(ctx["call"]["id"], ctx["offer"]["id"], make_provider_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# =========================================================================
# Queue B — consistency_model (immediate)
# =========================================================================
def test_complete_reflects_balance_and_quota_immediately(api):
    """PRD §3.8: "On a successful completion the system increments
    `services_used_this_year` by one, adds `member_out_of_pocket_cents` to the member's
    `outstanding_balance_cents`"

    A same-request follow-up GET reflects services_used_this_year=1 and
    outstanding_balance_cents=3000 immediately.

    Design: Corner/consistency_model/complete_response_reflects_balance_and_quota_immediately
    """
    ctx = setup_completed_call(final_towed_miles=20)
    member = validate_success(api.get_member(ctx["member"]["id"], OP))
    assert member["services_used_this_year"] == 1, \
        f"expected used 1 immediately, got {member['services_used_this_year']}"
    assert member["outstanding_balance_cents"] == 3000, \
        f"expected balance 3000 immediately, got {member['outstanding_balance_cents']}"
