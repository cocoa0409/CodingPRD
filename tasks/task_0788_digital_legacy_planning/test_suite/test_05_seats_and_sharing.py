"""Seat accounting, seat conservation, subscription-gated sharing, and temporal overlap
guards for shares and deputy terms."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, assert_seat_invariant,
    make_owner_headers,
    set_clock, create_plan, create_subscription, activate_subscription,
    create_deputy, create_and_accept_deputy, get_plan, create_vault_item,
    create_active_share, setup_active_paid_plan,
)


# --------------------------------------------------------------------------- #
# seat_limit_boundary_on_deputy_create  (Difficulty/boundary_precision_check)
# --------------------------------------------------------------------------- #
def test_second_deputy_on_free_plan_hits_seat_limit(api):
    """PRD 3.3: "First, seat capacity: adding a seat-consuming deputy is rejected with
    `ERR_SEAT_LIMIT_REACHED` when `seats_used` already equals or exceeds `seat_limit`."

    Design: Difficulty/boundary_precision_check/seat_limit_boundary_on_deputy_create
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="FREE")  # seat_limit 1
    create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ACCOUNT"],
                  full_name="D A", email="da@x.com")  # seats_used 1
    resp = api.create_deputy(
        {"plan_id": plan_id, "full_name": "D B", "email": "db@x.com",
         "deputy_role": "HEALTHCARE_PROXY", "access_scope": ["ACCOUNT"],
         "release_trigger": "ON_DEATH", "authority_start_at": "2026-06-01T00:00:00Z",
         "authority_end_at": "2027-06-01T00:00:00Z"}, make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_SEAT_LIMIT_REACHED)


def test_first_deputy_on_free_plan_below_limit_succeeds(api):
    """PRD 2.9: "The allowance, `seat_limit`, is granted by the subscription tier — `FREE`
    grants 1 seat, `PLUS` grants 5, and `FAMILY` grants 10 — and is treated as 0 when the
    plan has no subscription."

    Design: Difficulty/boundary_precision_check/seat_limit_boundary_on_deputy_create
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="FREE")  # seat_limit 1, seats_used 0
    resp = api.create_deputy(
        {"plan_id": plan_id, "full_name": "D A", "email": "da@x.com",
         "deputy_role": "EXECUTOR", "access_scope": ["ACCOUNT"],
         "release_trigger": "ON_DEATH", "authority_start_at": "2026-06-01T00:00:00Z",
         "authority_end_at": "2027-06-01T00:00:00Z"}, make_owner_headers(plan_id))
    data = validate_success(resp, 201)
    assert data["status"] == "INVITED", f"expected INVITED, got {data['status']}"


# --------------------------------------------------------------------------- #
# seat_conservation_add_then_revoke_deputy  (Difficulty/compensating_invariant)
# --------------------------------------------------------------------------- #
def test_seat_freed_after_deputy_revoke(api):
    """PRD 2.9: "The consumed seat count, `seats_used`, is the number of deputies on the
    plan whose status is `INVITED` or `ACCEPTED` and whose `consumes_seat` is true, plus the
    number of shares on the plan whose status is `ACTIVE`."
    PRD 3.3: "revocation frees the deputy's seat (seat accounting recomputes)"

    Design: Difficulty/compensating_invariant/seat_conservation_add_then_revoke_deputy
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")  # seat_limit 5
    deputy = create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ACCOUNT"],
                           full_name="D A", email="da@x.com")
    api.revoke_deputy(deputy["id"], make_owner_headers(plan_id))
    plan_after = get_plan(api, plan_id)
    assert plan_after["seats_used"] == 0, f"expected seats_used 0, got {plan_after['seats_used']}"
    assert plan_after["seats_available"] == 5, f"expected seats_available 5, got {plan_after['seats_available']}"


def test_seat_invariant_holds_before_and_after_revoke(api):
    """PRD 2.9: "The plan's `seats_available` is the seat limit minus seats used, but never
    below zero."

    Design: Difficulty/compensating_invariant/seat_conservation_add_then_revoke_deputy
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")  # seat_limit 5
    deputy = create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ACCOUNT"],
                           full_name="D A", email="da@x.com")
    before = get_plan(api, plan_id)
    assert before["seats_used"] == 1, f"expected seats_used 1, got {before['seats_used']}"
    assert before["seats_available"] == 4, f"expected seats_available 4, got {before['seats_available']}"
    assert_seat_invariant(before, 5)
    api.revoke_deputy(deputy["id"], make_owner_headers(plan_id))
    after = get_plan(api, plan_id)
    assert_seat_invariant(after, 5)


# --------------------------------------------------------------------------- #
# share_create_requires_active_paid_subscription  (Difficulty/cross_entity_state_dependency)
# --------------------------------------------------------------------------- #
def test_share_on_free_trialing_subscription_rejected(api):
    """PRD 3.7: "External sharing is a paid feature: creating a share requires the plan's
    subscription to be a paid tier (not `FREE`) and in `ACTIVE` status, otherwise the
    request is rejected with `ERR_SUBSCRIPTION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/share_create_requires_active_paid_subscription
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="FREE")  # FREE + TRIALING
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="photos", title="Photos",
                             secret_ref="vault://photos")
    resp = api.create_share(
        {"plan_id": plan_id, "vault_item_id": item["id"], "shared_with_email": "bob@x.com",
         "scope": "ITEM", "effective_at": "2026-06-01T00:00:00Z",
         "expires_at": "2026-07-01T00:00:00Z"}, make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED)


def test_share_on_active_paid_subscription_succeeds(api):
    """PRD 3.7: "A share is created in `ACTIVE` status and consumes a seat."
    PRD 3.7: "External sharing is a paid feature: creating a share requires the plan's
    subscription to be a paid tier (not `FREE`) and in `ACTIVE` status, otherwise the
    request is rejected with `ERR_SUBSCRIPTION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/share_create_requires_active_paid_subscription
    """
    ctx = setup_active_paid_plan(api, tier="PLUS")
    plan_id = ctx["plan_id"]
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="photos", title="Photos",
                             secret_ref="vault://photos")
    resp = api.create_share(
        {"plan_id": plan_id, "vault_item_id": item["id"], "shared_with_email": "bob@x.com",
         "scope": "ITEM", "effective_at": "2026-06-01T00:00:00Z",
         "expires_at": "2026-07-01T00:00:00Z"}, make_owner_headers(plan_id))
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"


# --------------------------------------------------------------------------- #
# share_window_overlap_half_open  (Difficulty/resource_temporal_overlap)
# --------------------------------------------------------------------------- #
def test_overlapping_share_window_rejected(api):
    """PRD 3.7: "Overlap is also guarded: for the same `vault_item_id` and
    `shared_with_email`, an existing `ACTIVE` share's half-open window from its
    `effective_at` up to its `expires_at` must not overlap the new window, though touching
    ends (where one window's end equals the other's start) are allowed; an overlap is
    rejected with `ERR_SHARE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/share_window_overlap_half_open
    """
    ctx = setup_active_paid_plan(api, tier="PLUS")
    plan_id = ctx["plan_id"]
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="photos", title="Photos",
                             secret_ref="vault://photos")
    create_active_share(api, plan_id, item["id"], shared_with_email="bob@x.com",
                        effective_at="2026-06-01T00:00:00Z", expires_at="2026-07-01T00:00:00Z")
    resp = api.create_share(
        {"plan_id": plan_id, "vault_item_id": item["id"], "shared_with_email": "bob@x.com",
         "scope": "ITEM", "effective_at": "2026-06-15T00:00:00Z",
         "expires_at": "2026-07-15T00:00:00Z"}, make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_SHARE_WINDOW_OVERLAP)


def test_touching_share_windows_allowed(api):
    """PRD 3.7: "though touching ends (where one window's end equals the other's start) are
    allowed; an overlap is rejected with `ERR_SHARE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/share_window_overlap_half_open
    """
    ctx = setup_active_paid_plan(api, tier="PLUS")
    plan_id = ctx["plan_id"]
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="photos", title="Photos",
                             secret_ref="vault://photos")
    create_active_share(api, plan_id, item["id"], shared_with_email="bob@x.com",
                        effective_at="2026-06-01T00:00:00Z", expires_at="2026-07-01T00:00:00Z")
    # New window starts exactly where the first ends -> touching, allowed.
    resp = api.create_share(
        {"plan_id": plan_id, "vault_item_id": item["id"], "shared_with_email": "bob@x.com",
         "scope": "ITEM", "effective_at": "2026-07-01T00:00:00Z",
         "expires_at": "2026-08-01T00:00:00Z"}, make_owner_headers(plan_id))
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"touching window should be accepted, got {data['status']}"


# --------------------------------------------------------------------------- #
# deputy_term_overlap_closed_buffer  (Difficulty/resource_temporal_overlap)
# --------------------------------------------------------------------------- #
def test_deputy_term_within_seven_day_buffer_rejected(api):
    """PRD 3.3: "Second, term overlap: for the same plan and `deputy_role`, an existing
    non-`REVOKED` deputy's closed term (from its `authority_start_at` through its
    `authority_end_at`) plus a seven-day buffer must not overlap the proposed term — the gap
    between terms of the same role must exceed seven days — and a violation is rejected with
    `ERR_DEPUTY_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/deputy_term_overlap_closed_buffer
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")
    create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ACCOUNT"],
                  full_name="D A", email="da@x.com",
                  authority_start_at="2026-06-01T00:00:00Z", authority_end_at="2026-06-30T00:00:00Z")
    resp = api.create_deputy(
        {"plan_id": plan_id, "full_name": "D B", "email": "db@x.com", "deputy_role": "EXECUTOR",
         "access_scope": ["ACCOUNT"], "release_trigger": "ON_DEATH",
         "authority_start_at": "2026-07-03T00:00:00Z", "authority_end_at": "2026-08-01T00:00:00Z"},
        make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_DEPUTY_TERM_OVERLAP)


def test_deputy_term_beyond_seven_day_buffer_allowed(api):
    """PRD 3.3: "the gap between terms of the same role must exceed seven days — and a
    violation is rejected with `ERR_DEPUTY_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/deputy_term_overlap_closed_buffer
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")
    create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ACCOUNT"],
                  full_name="D A", email="da@x.com",
                  authority_start_at="2026-06-01T00:00:00Z", authority_end_at="2026-06-30T00:00:00Z")
    # Second term starts 8 days after the first ends -> gap exceeds 7 days, allowed.
    resp = api.create_deputy(
        {"plan_id": plan_id, "full_name": "D B", "email": "db@x.com", "deputy_role": "EXECUTOR",
         "access_scope": ["ACCOUNT"], "release_trigger": "ON_DEATH",
         "authority_start_at": "2026-07-08T00:00:00Z", "authority_end_at": "2026-08-01T00:00:00Z"},
        make_owner_headers(plan_id))
    data = validate_success(resp, 201)
    assert data["status"] == "INVITED", f"expected INVITED, got {data['status']}"


# --------------------------------------------------------------------------- #
# subscription_cancel_revokes_active_shares  (Corner/state_machines)
# --------------------------------------------------------------------------- #
def test_cancel_subscription_revokes_active_shares(api):
    """PRD 3.7: "Cancellation also cascades: every `ACTIVE` share on the plan is moved to
    `REVOKED`."

    Design: Corner/state_machines/subscription_cancel_revokes_active_shares
    """
    ctx = setup_active_paid_plan(api, tier="PLUS")
    plan_id, sub_id = ctx["plan_id"], ctx["sub_id"]
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="photos", title="Photos",
                             secret_ref="vault://photos")
    share = create_active_share(api, plan_id, item["id"])
    validate_success(api.cancel_subscription(sub_id, make_owner_headers(plan_id)), 200)
    got = validate_success(api.get_share(share["id"], make_owner_headers(plan_id)), 200)
    assert got["status"] == "REVOKED", f"expected REVOKED, got {got['status']}"


# --------------------------------------------------------------------------- #
# share_cross_plan_item_returns_cross_plan_reference  (Corner/validations)
# --------------------------------------------------------------------------- #
def test_share_referencing_other_plans_item_rejected(api):
    """PRD 2.8: "A foreign key supplied in a body must belong to the same plan as the target
    resource — for example, a share's `vault_item_id` must sit under the same plan as the
    share's `plan_id`, and a release request's `requested_by_deputy_id` must serve the same
    plan — and a cross-plan reference is rejected with `ERR_CROSS_PLAN_REFERENCE` (HTTP 422)
    on share creation, release-request creation, and beneficiary creation."

    Design: Corner/validations/share_cross_plan_item_returns_cross_plan_reference
    """
    ctx_a = setup_active_paid_plan(api, tier="PLUS")
    plan_a = ctx_a["plan_id"]
    plan_b = create_plan(api, owner_full_name="Bee B", owner_email="b@x.com")["id"]
    item_y = create_vault_item(api, plan_b, kind="DOCUMENT", category="photos", title="Photos",
                               secret_ref="vault://photos")
    resp = api.create_share(
        {"plan_id": plan_a, "vault_item_id": item_y["id"], "shared_with_email": "bob@x.com",
         "scope": "ITEM", "effective_at": "2026-06-01T00:00:00Z",
         "expires_at": "2026-07-01T00:00:00Z"}, make_owner_headers(plan_a))
    validate_error(resp, ApiErrorId.ERR_CROSS_PLAN_REFERENCE)
