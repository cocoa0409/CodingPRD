"""Alterations: half-open construction windows, the decision-time recheck, the
GFA envelope aggregate, the compensating revocation and the casualty block."""

from test_helpers import (
    ERR_CROSS_ENTITY_BLOCKED,
    ERR_GFA_ENVELOPE_EXCEEDED,
    ERR_INTERVAL_OVERLAP,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
    assert_envelope_conserved,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    validate_error,
    validate_success,
)

REVOKE = {"reason_code": "PERMIT_WITHDRAWN"}
WINDOW_A = ("2027-01-01T00:00:00Z", "2027-06-01T00:00:00Z")
WINDOW_B = ("2027-06-01T00:00:00Z", "2027-09-01T00:00:00Z")
WINDOW_D = ("2027-03-01T00:00:00Z", "2027-04-01T00:00:00Z")


def _apply(api, env, requested_gfa_sqft, window, estimated_cost_cents=1000000,
           expected_status=201):
    return validate_success(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(
                requested_gfa_sqft=requested_gfa_sqft,
                construction_window_start=window[0],
                construction_window_end=window[1],
                estimated_cost_cents=estimated_cost_cents,
            ),
            make_ground_tenant_headers(env["lessee_id"]),
        ),
        expected_status=expected_status,
    )


def _two_overlapping_submissions(api):
    """A (10000 sqft, 2027-01-01 to 2027-06-01) and D (5000 sqft, 2027-03-01 to
    2027-04-01) both sit in SUBMITTED with windows that overlap each other."""
    env = fx.standard_lease(api, "PIER-61")
    alt_a = _apply(api, env, 10000, WINDOW_A)
    alt_d = _apply(api, env, 5000, WINDOW_D, 200000)
    assert alt_a["status"] == "SUBMITTED" and alt_d["status"] == "SUBMITTED"
    return env, alt_a, alt_d


def test_creation_only_screens_against_already_approved_windows(api):
    """PRD §3.5: "The window must start strictly before it ends, and it is validated half-open against every other window already approved on that lease, with a genuine intersection refused as `ERR_INTERVAL_OVERLAP` and touching endpoints permitted."

    Design: Difficulty/resource_temporal_overlap/construction_windows_touch_is_allowed_overlap_by_one_second_is_not_and_the_recheck_bites_at_decision
    """
    env, alt_a, _alt_d = _two_overlapping_submissions(api)

    approved = validate_success(
        api.decide_alteration(alt_a["id"], f.decision_payload("APPROVE"),
                              make_asset_manager_headers("am-1"))
    )
    assert approved["status"] == "APPROVED"
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=10000, gfa_unallocated_sqft=190000)
    assert_envelope_conserved(lease)

    # A window that merely touches the approved one at the shared instant.
    alt_b = _apply(api, env, 10000, WINDOW_B, 300000)
    approved_b = validate_success(
        api.decide_alteration(alt_b["id"], f.decision_payload("APPROVE"),
                              make_asset_manager_headers("am-1"))
    )
    assert approved_b["status"] == "APPROVED"
    assert fx.read_lease(api, env["lease_id"])["gfa_allocated_sqft"] == 20000


def test_a_window_biting_one_second_into_an_approved_window_is_refused(api):
    """PRD §2.9: "Two windows on the same lease that merely touch, where one window's end instant equals the next window's start instant, do **not** overlap and are both permitted; any genuine intersection between a proposed window and an already-approved window on the same lease is refused with `ERR_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/construction_windows_touch_is_allowed_overlap_by_one_second_is_not_and_the_recheck_bites_at_decision
    """
    env, alt_a, _alt_d = _two_overlapping_submissions(api)
    validate_success(
        api.decide_alteration(alt_a["id"], f.decision_payload("APPROVE"),
                              make_asset_manager_headers("am-1"))
    )

    validate_error(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(
                requested_gfa_sqft=1000,
                construction_window_start="2027-05-31T23:59:59Z",
                construction_window_end="2027-07-01T00:00:00Z",
                estimated_cost_cents=100000,
            ),
            make_ground_tenant_headers(env["lessee_id"]),
        ),
        ERR_INTERVAL_OVERLAP,
        expected_status=409,
    )


def test_the_interval_recheck_bites_at_decision_time_then_a_revocation_frees_it(api):
    """PRD §3.5: "The construction window must still not overlap another window on the lease that is in `APPROVED`."

    Design: Difficulty/resource_temporal_overlap/construction_windows_touch_is_allowed_overlap_by_one_second_is_not_and_the_recheck_bites_at_decision
    """
    env, alt_a, alt_d = _two_overlapping_submissions(api)
    manager = make_asset_manager_headers("am-1")
    validate_success(
        api.decide_alteration(alt_a["id"], f.decision_payload("APPROVE"), manager)
    )

    # D was perfectly legal when it was submitted; A is now APPROVED.
    validate_error(
        api.decide_alteration(alt_d["id"], f.decision_payload("APPROVE"), manager),
        ERR_INTERVAL_OVERLAP,
        expected_status=409,
    )
    still_submitted = validate_success(
        api.get_alteration(alt_d["id"], make_asset_manager_headers("am-1"))
    )
    assert still_submitted["status"] == "SUBMITTED"
    assert fx.read_lease(api, env["lease_id"])["gfa_allocated_sqft"] == 10000

    revoked = validate_success(
        api.revoke_alteration_approval(alt_a["id"], dict(REVOKE), manager)
    )
    assert revoked["status"] == "APPROVAL_REVOKED"
    assert fx.read_lease(api, env["lease_id"])["gfa_allocated_sqft"] == 0

    now_approved = validate_success(
        api.decide_alteration(alt_d["id"], f.decision_payload("APPROVE"), manager)
    )
    assert now_approved["status"] == "APPROVED"
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=5000, gfa_unallocated_sqft=195000)
    assert_envelope_conserved(lease)


def _two_approved_alterations(api):
    """A at 150000 sqft and B at 40000 sqft both APPROVED in non-overlapping
    windows, so 190000 of the 200000 sqft envelope is committed."""
    env = fx.standard_lease(api, "PIER-64")
    manager = make_asset_manager_headers("am-1")
    alt_a = _apply(api, env, 150000, WINDOW_A)
    validate_success(
        api.decide_alteration(alt_a["id"], f.decision_payload("APPROVE"), manager)
    )
    alt_b = _apply(api, env, 40000,
                   ("2027-07-01T00:00:00Z", "2027-12-01T00:00:00Z"), 400000)
    validate_success(
        api.decide_alteration(alt_b["id"], f.decision_payload("APPROVE"), manager)
    )
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=190000, gfa_unallocated_sqft=10000)
    return env, alt_a, alt_b


def test_a_second_revocation_cannot_mint_envelope_capacity(api):
    """PRD §2.8: "The source entity must sit in a state for which the operation is declared. Every action endpoint carries this check, and a violation yields `ERR_INVALID_STATE` (HTTP 409) — including a repeat of an action already applied and any attempted move out of a terminal state."

    Design: Difficulty/compensating_invariant/revoked_alteration_returns_envelope_once_and_a_second_revoke_cannot_mint_capacity
    """
    env, alt_a, _alt_b = _two_approved_alterations(api)
    manager = make_asset_manager_headers("am-1")

    revoked = validate_success(
        api.revoke_alteration_approval(alt_a["id"], dict(REVOKE), manager)
    )
    assert revoked["status"] == "APPROVAL_REVOKED"
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=40000, gfa_unallocated_sqft=160000)
    assert_envelope_conserved(lease)
    version = lease["version"]

    validate_error(
        api.revoke_alteration_approval(alt_a["id"], dict(REVOKE), manager),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    after = fx.read_lease(api, env["lease_id"])
    assert after["gfa_allocated_sqft"] == 40000
    assert after["version"] == version
    assert_envelope_conserved(after)


def test_the_released_window_is_reusable_but_the_aggregate_still_binds(api):
    """PRD §3.5: "It is entirely possible for each of several requests to fit individually while the collection exceeds the envelope, which is exactly what this check catches."

    Design: Difficulty/compensating_invariant/revoked_alteration_returns_envelope_once_and_a_second_revoke_cannot_mint_capacity
    """
    env, alt_a, _alt_b = _two_approved_alterations(api)
    manager = make_asset_manager_headers("am-1")
    validate_success(
        api.revoke_alteration_approval(alt_a["id"], dict(REVOKE), manager)
    )

    # The revoked request released its window, so the same dates are free again.
    alt_c = _apply(api, env, 170000, WINDOW_A, 1700000)
    assert alt_c["status"] == "SUBMITTED"

    validate_error(
        api.decide_alteration(alt_c["id"], f.decision_payload("APPROVE"), manager),
        ERR_GFA_ENVELOPE_EXCEEDED,
        expected_status=409,
    )
    still = validate_success(api.get_alteration(alt_c["id"], manager))
    assert still["status"] == "SUBMITTED"
    assert fx.read_lease(api, env["lease_id"])["gfa_allocated_sqft"] == 40000


def test_the_envelope_cap_is_inclusive_after_the_restoration(api):
    """PRD §2.10: "The **development envelope** of a lease satisfies `gfa_allocated_sqft` plus `gfa_unallocated_sqft` equal to `total_permitted_gfa_sqft` at all times."

    Design: Difficulty/compensating_invariant/revoked_alteration_returns_envelope_once_and_a_second_revoke_cannot_mint_capacity
    """
    env, alt_a, _alt_b = _two_approved_alterations(api)
    manager = make_asset_manager_headers("am-1")
    validate_success(
        api.revoke_alteration_approval(alt_a["id"], dict(REVOKE), manager)
    )

    alt_d = _apply(api, env, 160000,
                   ("2028-01-01T00:00:00Z", "2028-06-01T00:00:00Z"), 1600000)
    approved = validate_success(
        api.decide_alteration(alt_d["id"], f.decision_payload("APPROVE"), manager)
    )
    assert approved["status"] == "APPROVED"
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=200000, gfa_unallocated_sqft=0)
    assert_envelope_conserved(lease)


def _approved_150000_plus_a_60000_application(api):
    """150000 sqft already committed, leaving 50000; a 60000 sqft request sits in
    a touching window so only the aggregate rule can bite."""
    env = fx.standard_lease(api, "PIER-53")
    alt_1 = _apply(api, env, 150000, WINDOW_A)
    validate_success(
        api.decide_alteration(alt_1["id"], f.decision_payload("APPROVE"),
                              make_asset_manager_headers("am-1"))
    )
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=150000, gfa_unallocated_sqft=50000)
    alt_2 = _apply(api, env, 60000,
                   ("2027-06-01T00:00:00Z", "2027-12-01T00:00:00Z"), 2000000)
    return env, alt_1, alt_2


def test_the_authorisation_check_outranks_the_envelope_aggregate(api):
    """PRD §2.8: "The role in `X-User-Role` must appear in the endpoint's authorised-role list; otherwise `ERR_UNAUTHORIZED`."

    Design: Difficulty/priority_pair_validation_conflict/alteration_decision_unauthorized_role_beats_the_gfa_envelope_aggregate
    """
    env, _alt_1, alt_2 = _approved_150000_plus_a_60000_application(api)
    version = fx.lease_version(api, env["lease_id"])

    validate_error(
        api.decide_alteration(alt_2["id"], f.decision_payload("APPROVE"),
                              make_accountant_headers("acct-1")),
        ERR_UNAUTHORIZED,
        expected_status=403,
    )
    unchanged = validate_success(
        api.get_alteration(alt_2["id"], make_asset_manager_headers("am-1"))
    )
    assert unchanged["status"] == "SUBMITTED"
    lease = fx.read_lease(api, env["lease_id"])
    assert lease["gfa_allocated_sqft"] == 150000
    assert lease["version"] == version


def test_with_an_authorised_role_the_envelope_aggregate_surfaces(api):
    """PRD §3.5: "And the envelope must accommodate the work: `requested_gfa_sqft` may not exceed the lease's `gfa_unallocated_sqft` — equivalently, the sum of `requested_gfa_sqft` across the lease's already-approved requests plus this one's may not exceed `total_permitted_gfa_sqft` — with the refusal `ERR_GFA_ENVELOPE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/alteration_decision_unauthorized_role_beats_the_gfa_envelope_aggregate
    """
    env, _alt_1, alt_2 = _approved_150000_plus_a_60000_application(api)

    validate_error(
        api.decide_alteration(alt_2["id"], f.decision_payload("APPROVE"),
                              make_asset_manager_headers("am-1")),
        ERR_GFA_ENVELOPE_EXCEEDED,
        expected_status=409,
    )
    still = validate_success(
        api.get_alteration(alt_2["id"], make_asset_manager_headers("am-1"))
    )
    assert still["status"] == "SUBMITTED"
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=150000, gfa_unallocated_sqft=50000)


def _open_casualty_and_a_pending_alteration(api):
    """A COSMETIC 10000 sqft request in SUBMITTED and a CASUALTY loss event in
    REPORTED whose 1000000 damage is far below the termination threshold."""
    env = fx.standard_lease(api, "PIER-59")
    fx.file_insurance(api, env["lease_id"])
    alt = _apply(api, env, 10000, WINDOW_A)
    event = fx.reported_loss_event(
        api, env["lease_id"],
        headers=make_ground_tenant_headers(env["lessee_id"]),
        event_type="CASUALTY", scope_code="PARTIAL",
        occurred_at="2026-07-15T00:00:00Z",
        damage_estimate_cents=1000000, damaged_area_sqft=500,
    )
    assert event["status"] == "REPORTED"
    return env, alt, event


def test_approval_is_blocked_while_a_casualty_sits_in_reported(api):
    """PRD §3.5: "Approval is additionally blocked while any `CASUALTY` loss event on the lease sits in `REPORTED` or `ADJUSTED`, refused with `ERR_CROSS_ENTITY_BLOCKED`, because the lessor will not consent to new work while the consequences of a fire are still unsettled."

    Design: Difficulty/cross_entity_state_dependency/alteration_approval_blocked_until_the_casualty_election_is_made
    """
    env, alt, _event = _open_casualty_and_a_pending_alteration(api)
    version = fx.lease_version(api, env["lease_id"])

    validate_error(
        api.decide_alteration(alt["id"], f.decision_payload("APPROVE"),
                              make_asset_manager_headers("am-1")),
        ERR_CROSS_ENTITY_BLOCKED,
        expected_status=409,
    )
    blocked = validate_success(
        api.get_alteration(alt["id"], make_asset_manager_headers("am-1"))
    )
    assert blocked["status"] == "SUBMITTED"
    assert blocked["decided_by_user_id"] is None
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=0, gfa_unallocated_sqft=200000,
                  version=version)


def test_an_adjusted_casualty_is_still_an_unsettled_casualty(api):
    """PRD §3.8: "Adjustment writes all three supplied values and moves the event `REPORTED → ADJUSTED`."

    Design: Difficulty/cross_entity_state_dependency/alteration_approval_blocked_until_the_casualty_election_is_made
    """
    env, alt, event = _open_casualty_and_a_pending_alteration(api)
    manager = make_asset_manager_headers("am-1")

    adjusted = validate_success(
        api.adjust_loss_event(
            event["id"], f.adjust_payload(800000, "BONUS_VALUE", 500), manager
        )
    )
    assert_fields(adjusted, status="ADJUSTED",
                  distributable_pool_cents=800000, rent_abatement_bps=500)

    validate_error(
        api.decide_alteration(alt["id"], f.decision_payload("APPROVE"), manager),
        ERR_CROSS_ENTITY_BLOCKED,
        expected_status=409,
    )
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=0, gfa_unallocated_sqft=200000)


def test_electing_restoration_unblocks_the_identical_approval(api):
    """PRD §3.8: "The event moves `ADJUSTED → RESTORATION_ELECTED`, and the lease's tenancy axis is left completely untouched — this is the branch that preserves the tenancy."

    Design: Difficulty/cross_entity_state_dependency/alteration_approval_blocked_until_the_casualty_election_is_made
    """
    env, alt, event = _open_casualty_and_a_pending_alteration(api)
    manager = make_asset_manager_headers("am-1")
    validate_success(
        api.adjust_loss_event(
            event["id"], f.adjust_payload(800000, "BONUS_VALUE", 500), manager
        )
    )

    elected = validate_success(
        api.elect_loss_outcome(
            event["id"], f.election_payload("RESTORE"),
            make_ground_tenant_headers(env["lessee_id"]),
        )
    )
    assert elected["status"] == "RESTORATION_ELECTED"
    assert fx.read_lease(api, env["lease_id"])["lease_status"] == "ACTIVE"

    approved = validate_success(
        api.decide_alteration(alt["id"], f.decision_payload("APPROVE"), manager)
    )
    assert_fields(approved, status="APPROVED", decided_by_user_id="am-1")
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=10000, gfa_unallocated_sqft=190000)
    assert_envelope_conserved(lease)
