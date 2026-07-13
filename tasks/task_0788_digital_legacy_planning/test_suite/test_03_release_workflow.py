"""The release workflow: verify gating, voting branches, quorum, grant preconditions,
and the deputy-revoke cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_owner_headers, make_deputy_headers, ADMIN_HEADERS,
    setup_release_approved, setup_release_verified_multi_deputy, setup_plan_pending_release,
    set_clock, create_plan, create_subscription, activate_subscription, fail_payment,
    create_and_accept_deputy, mark_life_status, create_release_request,
    create_vault_item, seal_vault_item, verify_release_request, approve_release_request,
)


# --------------------------------------------------------------------------- #
# release_request_verified_branch_to_denied  (Difficulty/non_linear_state_machine)
# --------------------------------------------------------------------------- #
def test_reject_vote_denies_verified_request(api):
    """PRD 3.6: "A single `REJECT` vote vetoes the request, moving it directly from
    `VERIFIED` to `DENIED`."

    Design: Difficulty/non_linear_state_machine/release_request_verified_branch_to_denied
    """
    ctx = setup_release_verified_multi_deputy(api, num_deputies=1)
    d0, rr_id = ctx["deputy_ids"][0], ctx["rr_id"]
    resp = api.approve_release_request(rr_id, {"decision": "REJECT"}, make_deputy_headers(d0))
    data = validate_success(resp, 200)
    assert data["status"] == "DENIED", f"expected DENIED, got {data['status']}"


def test_reject_vote_leaves_approval_count_zero(api):
    """PRD 3.6: "Each `APPROVE` vote appends the deputy to `approver_deputy_ids` and
    increments the distinct-approver count `approval_count`; the request moves from
    `VERIFIED` to `APPROVED` the instant `approval_count` reaches or exceeds
    `required_approvals` (the boundary is inclusive — exactly meeting the quorum approves)."

    Design: Difficulty/non_linear_state_machine/release_request_verified_branch_to_denied
    """
    ctx = setup_release_verified_multi_deputy(api, num_deputies=1)
    d0, rr_id = ctx["deputy_ids"][0], ctx["rr_id"]
    data = validate_success(
        api.approve_release_request(rr_id, {"decision": "REJECT"}, make_deputy_headers(d0)), 200)
    assert data["approval_count"] == 0, f"REJECT must not count as approval, got {data['approval_count']}"


# --------------------------------------------------------------------------- #
# deputy_revoke_denies_pending_request_depth2  (Difficulty/transitive_cascade)
# --------------------------------------------------------------------------- #
def test_revoke_deputy_moves_deputy_to_revoked(api):
    """PRD 3.3: "An owner may revoke a deputy from either `INVITED` or `ACCEPTED`, moving
    it to the terminal `REVOKED` state; revocation frees the deputy's seat (seat accounting
    recomputes) and, as a cascade, moves every release request in `PENDING` or `VERIFIED`
    status whose `requested_by_deputy_id` is this deputy to `DENIED`."

    Design: Difficulty/transitive_cascade/deputy_revoke_denies_pending_request_depth2
    """
    ctx = setup_plan_pending_release(api, life_status="DECEASED")
    resp = api.revoke_deputy(ctx["deputy_id"], make_owner_headers(ctx["plan_id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "REVOKED", f"expected REVOKED, got {data['status']}"


def test_revoke_deputy_cascades_pending_request_to_denied(api):
    """PRD 3.3: "revocation frees the deputy's seat (seat accounting recomputes) and, as a
    cascade, moves every release request in `PENDING` or `VERIFIED` status whose
    `requested_by_deputy_id` is this deputy to `DENIED`."

    Design: Difficulty/transitive_cascade/deputy_revoke_denies_pending_request_depth2
    """
    ctx = setup_plan_pending_release(api, life_status="DECEASED")
    api.revoke_deputy(ctx["deputy_id"], make_owner_headers(ctx["plan_id"]))
    rr = validate_success(api.get_release_request(ctx["rr_id"], ADMIN_HEADERS), 200)
    assert rr["status"] == "DENIED", f"pending request expected DENIED, got {rr['status']}"


# --------------------------------------------------------------------------- #
# release_verify_requires_plan_deceased  (Difficulty/cross_entity_state_dependency)
# --------------------------------------------------------------------------- #
def test_verify_on_death_request_rejected_when_plan_active(api):
    """PRD 3.6: "An administrator verifies a pending request, but only when the plan's
    `life_status` actually satisfies the asserted trigger: an `ON_DEATH` request requires
    the plan to be `DECEASED`, and an `ON_INCAPACITY` request requires the plan to be
    `INCAPACITATED` or `DECEASED`. A verify attempted against an unsatisfied life status is
    rejected with `ERR_RELEASE_NOT_TRIGGERED`."

    Design: Difficulty/cross_entity_state_dependency/release_verify_requires_plan_deceased
    """
    ctx = setup_plan_pending_release(api, life_status=None)  # plan stays ACTIVE
    resp = api.verify_release_request(ctx["rr_id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_TRIGGERED)


def test_verify_succeeds_once_plan_is_deceased(api):
    """PRD 3.6: "an `ON_DEATH` request requires the plan to be `DECEASED`"
    PRD 3.6: "Verification pins the approval quorum and sets an expiry: `required_approvals`
    is fixed at verify time to the number of accepted deputies on the plan multiplied by
    one-half, rounded up to the next whole number, with a floor of 1 (so at least one
    approval is always required), and `expires_at` is set to the current clock plus 14 days."

    Design: Difficulty/cross_entity_state_dependency/release_verify_requires_plan_deceased
    """
    ctx = setup_plan_pending_release(api, life_status=None)
    mark_life_status(api, ctx["plan_id"], "DECEASED")
    data = validate_success(api.verify_release_request(ctx["rr_id"], ADMIN_HEADERS), 200)
    assert data["status"] == "VERIFIED", f"expected VERIFIED, got {data['status']}"
    assert data["required_approvals"] == 1, f"one accepted deputy -> floor 1, got {data['required_approvals']}"


# --------------------------------------------------------------------------- #
# empty_release_set_boundary_on_grant  (Difficulty/boundary_precision_check)
# --------------------------------------------------------------------------- #
def test_grant_with_no_sealed_in_scope_item_rejected(api):
    """PRD 3.6: "Granting requires that at least one `SEALED` vault item exists on the plan
    whose `kind` is in the request's `scope_kinds`; if there is nothing eligible to release,
    the grant is rejected with `ERR_NOTHING_TO_RELEASE`."

    Design: Difficulty/boundary_precision_check/empty_release_set_boundary_on_grant
    """
    ctx = setup_release_approved(api, create_asset=False, scope_kinds=("ASSET",))
    resp = api.grant_release_request(ctx["rr_id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_RELEASE)


def test_grant_with_one_sealed_in_scope_item_succeeds(api):
    """PRD 3.6: "Granting requires that at least one `SEALED` vault item exists on the plan
    whose `kind` is in the request's `scope_kinds`; if there is nothing eligible to release,
    the grant is rejected with `ERR_NOTHING_TO_RELEASE`."

    Design: Difficulty/boundary_precision_check/empty_release_set_boundary_on_grant
    """
    ctx = setup_release_approved(api, create_asset=True, gross_value_cents=10000,
                                 liability_cents=0, distribution_basis="NET",
                                 allocations=(100,), scope_kinds=("ASSET",))
    data = validate_success(api.grant_release_request(ctx["rr_id"], ADMIN_HEADERS), 200)
    assert data["status"] == "GRANTED", f"one eligible item -> GRANTED, got {data['status']}"


# --------------------------------------------------------------------------- #
# state_beats_fiscal_on_grant  (Difficulty/priority_pair_validation_conflict)
# --------------------------------------------------------------------------- #
def _deceased_plan_pastdue_pending_rr(api):
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    sub = create_subscription(api, plan_id, tier="PLUS")
    activate_subscription(api, plan_id, sub["id"])
    fail_payment(api, sub["id"])  # ACTIVE -> PAST_DUE
    deputy = create_and_accept_deputy(api, plan_id, access_scope=["ASSET"])
    mark_life_status(api, plan_id, "DECEASED")
    rr = create_release_request(api, plan_id, deputy["id"], scope_kinds=("ASSET",))
    return plan_id, rr["id"]


def test_grant_pending_request_returns_state_error_before_fiscal(api):
    """PRD 2.8: "When multiple checks could reject a request, they are evaluated in a fixed
    priority order so that the returned error is deterministic."
    PRD 3.6: "a grant attempted from any state other than `APPROVED` (or the quorum-pending
    `VERIFIED` case just described) is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_grant
    """
    _plan_id, rr_id = _deceased_plan_pastdue_pending_rr(api)
    resp = api.grant_release_request(rr_id, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_grant_leaves_request_pending(api):
    """PRD 2.8: "Sixth, for state-transition endpoints, the target must be in a state from
    which the requested transition is defined, otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_grant
    """
    _plan_id, rr_id = _deceased_plan_pastdue_pending_rr(api)
    api.grant_release_request(rr_id, ADMIN_HEADERS)
    rr = validate_success(api.get_release_request(rr_id, ADMIN_HEADERS), 200)
    assert rr["status"] == "PENDING", f"rejected grant must not transition, got {rr['status']}"


# --------------------------------------------------------------------------- #
# duplicate_deputy_vote_rejected  (Corner/validations)
# --------------------------------------------------------------------------- #
def test_duplicate_deputy_vote_rejected(api):
    """PRD 3.6: "A deputy may vote only once on a given request; a second vote by the same
    deputy is rejected with `ERR_DUPLICATE_APPROVAL`."

    Design: Corner/validations/duplicate_deputy_vote_rejected
    """
    ctx = setup_release_verified_multi_deputy(api, num_deputies=3)  # required_approvals = 2
    d0, rr_id = ctx["deputy_ids"][0], ctx["rr_id"]
    approve_release_request(api, d0, rr_id, decision="APPROVE")  # count 1, still VERIFIED
    resp = api.approve_release_request(rr_id, {"decision": "APPROVE"}, make_deputy_headers(d0))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPROVAL)


# --------------------------------------------------------------------------- #
# grant_before_quorum_returns_quorum_not_met  (Corner/errors)
# Isolated so only the quorum check can fail (a sealed in-scope item exists and the
# subscription is not PAST_DUE), per the validation-priority isolation guidance.
# --------------------------------------------------------------------------- #
def test_grant_before_quorum_rejected(api):
    """PRD 3.6: "If an administrator attempts to grant a request that is `VERIFIED` but has
    not yet reached its quorum (its `approval_count` is below `required_approvals`), the
    grant is rejected with `ERR_QUORUM_NOT_MET`; a grant attempted from any state other than
    `APPROVED` (or the quorum-pending `VERIFIED` case just described) is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/errors/grant_before_quorum_returns_quorum_not_met
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")  # TRIALING, not PAST_DUE
    d_ids = []
    for i, role in enumerate(["EXECUTOR", "HEALTHCARE_PROXY", "GUARDIAN"]):
        dep = create_and_accept_deputy(api, plan_id, deputy_role=role, access_scope=["ASSET"],
                                       full_name=f"D {i}", email=f"d{i}@x.com")
        d_ids.append(dep["id"])
    item = create_vault_item(api, plan_id, kind="ASSET", category="estate", title="House",
                             secret_ref="vault://house", gross_value_cents=10000,
                             liability_cents=0, distribution_basis="NET")
    seal_vault_item(api, plan_id, item["id"])  # a SEALED in-scope item exists
    mark_life_status(api, plan_id, "DECEASED")
    rr = create_release_request(api, plan_id, d_ids[0], scope_kinds=("ASSET",))
    verify_release_request(api, rr["id"])          # required_approvals = ceil(3*0.5) = 2
    approve_release_request(api, d_ids[0], rr["id"], decision="APPROVE")  # count 1 < 2
    resp = api.grant_release_request(rr["id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
