"""Prioritization-pool and PSH-referral depth tests: the MATCHED↔ACTIVE re-queue cycle,
the accept/decline branch fork, the enroll→house cascade, caseload conservation, and the
two validation-precedence / cross-entity guards on referral creation.

Every test translates exactly one instance from the difficulty design index (queue A).
"""
from test_helpers import (
    validate_success, validate_error,
    create_referral_payload, create_prioritization_entry_payload,
    new_client, new_active_consent, new_pool_entry, new_navigator, new_referral,
    setup_active_pooled_client, setup_pending_referral, setup_accepted_referral,
    make_navigator_headers,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


# ─── non_linear_state_machine / nlsm_prioritization_requeue_cycle ──────────────
def test_decline_requeues_pool_entry_to_active(api):
    """PRD §3.6: "Declining a `PENDING` referral moves it `PENDING → DECLINED` and re-queues
    the pool entry, driving `MATCHED → ACTIVE` (its `matched_referral_id` cleared to null and
    its `rank_score` recomputed as it returns to the pool)."

    Design: Difficulty/non_linear_state_machine/nlsm_prioritization_requeue_cycle
    """
    ctx = setup_pending_referral(max_caseload=3)
    nav_headers = make_navigator_headers(ctx["navigator"]["id"])
    declined = validate_success(api.decline_referral(ctx["referral"]["id"], nav_headers), 200)
    assert declined["status"] == "DECLINED"

    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "ACTIVE", "declined referral must re-queue the pool entry"
    assert pe["matched_referral_id"] is None


def test_requeued_entry_can_be_rematched(api):
    """PRD §3.6: "On success the referral is `PENDING` and its pool entry moves
    `ACTIVE → MATCHED`, recording the new referral's `id` in the entry's `matched_referral_id`."

    Design: Difficulty/non_linear_state_machine/nlsm_prioritization_requeue_cycle
    """
    ctx = setup_pending_referral(max_caseload=3)
    nav = ctx["navigator"]
    nav_headers = make_navigator_headers(nav["id"])
    api.decline_referral(ctx["referral"]["id"], nav_headers)

    ref2 = new_referral(ctx["client"]["id"], ctx["pool_entry"]["id"], nav["id"])
    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "MATCHED"
    assert pe["matched_referral_id"] == ref2["id"]


# ─── non_linear_state_machine / nlsm_referral_branching_accept_vs_decline ──────
def test_accept_branch_increments_caseload_and_keeps_matched(api):
    """PRD §3.6: "A `PENDING` referral moves to `ACCEPTED` only if the navigator's
    `current_caseload` is below their `max_caseload`; otherwise the request is rejected with
    `ERR_CASELOAD_FULL`. Acceptance increases the navigator's `current_caseload` by one."

    Design: Difficulty/non_linear_state_machine/nlsm_referral_branching_accept_vs_decline
    """
    ctx = setup_pending_referral(max_caseload=2)
    nav = ctx["navigator"]
    accepted = validate_success(
        api.accept_referral(ctx["referral"]["id"], make_navigator_headers(nav["id"])), 200)
    assert accepted["status"] == "ACCEPTED"

    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "MATCHED"
    nav_after = validate_success(api.get_housing_navigator(nav["id"], ADMIN), 200)
    assert nav_after["current_caseload"] == 1


def test_decline_branch_requeues_pool_without_caseload_change(api):
    """PRD §3.6: "Declining a `PENDING` referral moves it `PENDING → DECLINED` and re-queues
    the pool entry, driving `MATCHED → ACTIVE` (its `matched_referral_id` cleared to null and
    its `rank_score` recomputed as it returns to the pool). Because the referral was never
    accepted, the caseload is unchanged."

    Design: Difficulty/non_linear_state_machine/nlsm_referral_branching_accept_vs_decline
    """
    ctx = setup_pending_referral(max_caseload=2)
    nav = ctx["navigator"]
    declined = validate_success(
        api.decline_referral(ctx["referral"]["id"], make_navigator_headers(nav["id"])), 200)
    assert declined["status"] == "DECLINED"

    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "ACTIVE"
    nav_after = validate_success(api.get_housing_navigator(nav["id"], ADMIN), 200)
    assert nav_after["current_caseload"] == 0


# ─── transitive_cascade / casc_enroll_house_client_depth2 ──────────────────────
def test_enroll_cascades_pool_and_client_to_housed(api):
    """PRD §3.6: "Enrolling an `ACCEPTED` referral moves it `ACCEPTED → ENROLLED`. This
    cascades: the pool entry moves `MATCHED → HOUSED`, the client moves `ACTIVE → HOUSED`
    and leaves the pool, and the navigator's `current_caseload` decrements by one as the
    referral leaves `ACCEPTED` for `ENROLLED`."

    Design: Difficulty/transitive_cascade/casc_enroll_house_client_depth2
    """
    ctx = setup_accepted_referral(max_caseload=2, self_report_points=12)
    nav = ctx["navigator"]
    enrolled = validate_success(
        api.enroll_referral(ctx["referral"]["id"], make_navigator_headers(nav["id"])), 200)
    assert enrolled["status"] == "ENROLLED"

    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "HOUSED"
    client = validate_success(api.get_client(ctx["client"]["id"], ADMIN), 200)
    assert client["status"] == "HOUSED"


def test_enroll_decrements_navigator_caseload(api):
    """PRD §3.6: "the navigator's `current_caseload` decrements by one as the referral
    leaves `ACCEPTED` for `ENROLLED`."

    Design: Difficulty/transitive_cascade/casc_enroll_house_client_depth2
    """
    ctx = setup_accepted_referral(max_caseload=2, self_report_points=12)
    nav = ctx["navigator"]
    api.enroll_referral(ctx["referral"]["id"], make_navigator_headers(nav["id"]))

    nav_after = validate_success(api.get_housing_navigator(nav["id"], ADMIN), 200)
    assert nav_after["current_caseload"] == 0


# ─── compensating_invariant / comp_navigator_caseload_conserved_accept_decline ─
def test_accept_then_decline_restores_caseload_to_zero(api):
    """PRD §3.6: "It begins at zero, rises by one when a referral is accepted, and falls by
    one both when an accepted referral is declined and when an accepted referral is enrolled
    — so a forward accept paired with its compensating decline leaves the caseload where it
    started."

    Design: Difficulty/compensating_invariant/comp_navigator_caseload_conserved_accept_decline
    """
    ctx = setup_accepted_referral(max_caseload=2)
    nav = ctx["navigator"]
    api.decline_referral(ctx["referral"]["id"], make_navigator_headers(nav["id"]))

    nav_after = validate_success(api.get_housing_navigator(nav["id"], ADMIN), 200)
    assert nav_after["current_caseload"] == 0


def test_decline_from_accepted_requeues_pool_entry(api):
    """PRD §3.6: "Declining an `ACCEPTED` referral moves it `ACCEPTED → DECLINED`, decrements
    the navigator's `current_caseload` by one to compensate for the earlier acceptance, and
    re-queues the pool entry `MATCHED → ACTIVE` (clearing `matched_referral_id` and
    recomputing `rank_score`)."

    Design: Difficulty/compensating_invariant/comp_navigator_caseload_conserved_accept_decline
    """
    ctx = setup_accepted_referral(max_caseload=2)
    nav = ctx["navigator"]
    declined = validate_success(
        api.decline_referral(ctx["referral"]["id"], make_navigator_headers(nav["id"])), 200)
    assert declined["status"] == "DECLINED"

    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "ACTIVE"


# ─── priority_pair_validation_conflict / pconf_referral_invalidstate_over_assessment
def test_referral_against_deferred_entry_reports_invalid_state(api):
    """PRD §2.5: "When more than one rule could fire, the earliest rule in the following
    order wins, and its error is the one returned — a later, more specific failure must never
    mask an earlier one."
    PRD §2.5: "For any state-transition endpoint, the target resource must be in a state from
    which the transition is legal, or the request fails with `ERR_INVALID_STATE` (409)."
    PRD §3.6: "Creating a referral requires the pool entry to be `ACTIVE` and the client to
    have a `COMPLETED` `Assessment`; a client with no completed assessment is rejected with
    `ERR_ASSESSMENT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/pconf_referral_invalidstate_over_assessment
    """
    client = new_client(full_name="Della Def", dob="1994-12-12")
    new_active_consent(client["id"])
    pe = new_pool_entry(client["id"], ADMIN)
    nav = new_navigator(max_caseload=2)
    nav_headers = make_navigator_headers(nav["id"])
    validate_success(api.defer_prioritization_entry(
        pe["id"], {"deferred_until": "2026-04-01"}, nav_headers), 200)

    res = api.create_referral(create_referral_payload(
        client["id"], pe["id"], nav["id"], "Maple PSH"), nav_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_referral_against_deferred_entry_leaves_entry_deferred(api):
    """PRD §3.6: "A `HousingNavigator` may defer an `ACTIVE` pool entry until a later date by
    supplying `deferred_until`; the entry moves `ACTIVE → DEFERRED` and is excluded from
    matching until the logical clock reaches that date."

    Design: Difficulty/priority_pair_validation_conflict/pconf_referral_invalidstate_over_assessment
    """
    client = new_client(full_name="Della Def", dob="1994-12-12")
    new_active_consent(client["id"])
    pe = new_pool_entry(client["id"], ADMIN)
    nav = new_navigator(max_caseload=2)
    nav_headers = make_navigator_headers(nav["id"])
    api.defer_prioritization_entry(pe["id"], {"deferred_until": "2026-04-01"}, nav_headers)

    api.create_referral(create_referral_payload(
        client["id"], pe["id"], nav["id"], "Maple PSH"), nav_headers)

    after = validate_success(api.get_prioritization_entry(pe["id"], ADMIN), 200)
    assert after["status"] == "DEFERRED", "a rejected referral must not match the deferred entry"


# ─── cross_entity_state_dependency / xdep_referral_requires_completed_assessment
def test_referral_without_completed_assessment_rejected(api):
    """PRD §3.6: "Creating a referral requires the pool entry to be `ACTIVE` and the client
    to have a `COMPLETED` `Assessment`; a client with no completed assessment is rejected
    with `ERR_ASSESSMENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/xdep_referral_requires_completed_assessment
    """
    client = new_client(full_name="Pat NoAssess", dob="1990-04-04")
    new_active_consent(client["id"])
    pe = new_pool_entry(client["id"], ADMIN)
    nav = new_navigator(max_caseload=2)

    res = api.create_referral(create_referral_payload(
        client["id"], pe["id"], nav["id"], "Maple PSH"), make_navigator_headers(nav["id"]))
    validate_error(res, "ERR_ASSESSMENT_REQUIRED", expected_status=409)


def test_referral_rejected_leaves_pool_entry_active(api):
    """PRD §3.6: "On success the referral is `PENDING` and its pool entry moves
    `ACTIVE → MATCHED`, recording the new referral's `id` in the entry's `matched_referral_id`."

    Design: Difficulty/cross_entity_state_dependency/xdep_referral_requires_completed_assessment
    """
    client = new_client(full_name="Pat NoAssess", dob="1990-04-04")
    new_active_consent(client["id"])
    pe = new_pool_entry(client["id"], ADMIN)
    nav = new_navigator(max_caseload=2)

    api.create_referral(create_referral_payload(
        client["id"], pe["id"], nav["id"], "Maple PSH"), make_navigator_headers(nav["id"]))

    after = validate_success(api.get_prioritization_entry(pe["id"], ADMIN), 200)
    assert after["status"] == "ACTIVE", "an assessment-blocked referral must not match the entry"
