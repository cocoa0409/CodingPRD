"""Compensating invariants (exercise reverse, grant cancel) and cross-entity
state dependencies (grant approval gated on cap-table state; exercise reverse
gated on accepted 83(b) election).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    assert_pool_conservation,
    setup_active_vested_grant,
    setup_settled_exercise,
    create_cap_table,
    create_security_class,
    create_shareholder,
    create_effective_valuation,
    create_option_pool,
    create_active_grant,
    create_grant,
    lock_cap_table,
    set_clock,
    api_client,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]


# ============================================================================
# Difficulty/compensating_invariant/exercise_reverse_conserves_issued_shares
# ============================================================================

def test_exercise_reverse_conserves_issued_shares(api):
    """PRD §3.8: "When a settled exercise is reversed, the depth-three cascade
    runs in reverse as a compensating action: the grant's `exercised_shares`
    falls by the exercise's `share_count`, the class's `shares_outstanding` falls
    by the same amount, and the cap table's `issued_shares` and
    `fully_diluted_shares` are recomputed, so that the net effect on
    `issued_shares` is zero relative to the pre-exercise state."

    Settle 1000 then reverse → issued_shares back to 0, class shares_outstanding 0.

    Design: Difficulty/compensating_invariant/exercise_reverse_conserves_issued_shares
    """
    env = setup_settled_exercise(share_count=1000, fmv_per_share_cents=100,
                                 strike_price_cents=100, clock="2026-06-01T00:00:00Z")
    get_success_data(api.reverse_exercise(env["exercise"]["id"], ADMIN))
    ct = validate_success(api.get_cap_table(env["ct"]["id"], ADMIN), 200)
    assert ct["issued_shares"] == 0, f"expected issued_shares 0 after reverse, got {ct['issued_shares']}"
    cls = validate_success(api.get_security_class(env["common"]["id"], ADMIN), 200)
    assert cls["shares_outstanding"] == 0, (
        f"expected shares_outstanding 0 after reverse, got {cls['shares_outstanding']}"
    )


def test_exercise_reverse_reverts_grant_to_active(api):
    """PRD §3.8: "If the grant had been driven to `EXERCISED`, it reverts to
    `ACTIVE`, and any Form 3921 that had been generated for the exercise is
    voided and its linkage cleared."

    A fully-exercised (EXERCISED) grant: reversing its exercise reverts grant to
    ACTIVE and the exercise to REVERSED.

    Design: Difficulty/compensating_invariant/exercise_reverse_conserves_issued_shares
    """
    env = setup_settled_exercise(share_count=1000, fmv_per_share_cents=100,
                                 strike_price_cents=100, clock="2026-06-01T00:00:00Z")
    ex_after = validate_success(api.reverse_exercise(env["exercise"]["id"], ADMIN), 200)
    assert ex_after["status"] == "REVERSED", f"expected REVERSED, got {ex_after['status']}"
    grant = validate_success(api.get_option_grant(env["grant"]["id"], ADMIN), 200)
    assert grant["status"] == "ACTIVE", f"expected grant ACTIVE after reverse, got {grant['status']}"


# ============================================================================
# Difficulty/compensating_invariant/grant_cancel_conserves_pool_authorized_shares
# ============================================================================

def test_grant_cancel_conserves_pool_allocated_to_zero(api):
    """PRD §3.6: "A valid `ACTIVE → CANCELLED` cancellation is a compensating
    action that returns the full grant to the pool: the pool's `allocated_shares`
    falls by `share_count`, its `available_shares` is recomputed."

    Pool authorized 5000, ACTIVE grant 2000, cancel → allocated 0.

    Design: Difficulty/compensating_invariant/grant_cancel_conserves_pool_authorized_shares
    """
    set_clock("2026-06-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@pc.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=5000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=2000, strike_price_cents=100,
                                grant_date="2020-01-01T00:00:00Z")
    get_success_data(api.cancel_option_grant(grant["id"], ADMIN))
    pool_after = validate_success(api.get_option_pool(pool["id"], ADMIN), 200)
    assert pool_after["allocated_shares"] == 0, (
        f"expected allocated 0 after cancel, got {pool_after['allocated_shares']}"
    )


def test_grant_cancel_restores_pool_available_to_authorized(api):
    """PRD §3.5: "`available_shares` is `authorized_shares` minus
    `allocated_shares`, floored at zero."

    After cancelling the only ACTIVE grant, available_shares returns to the full
    authorized reservation (5000), conserving authorized = allocated + available.

    Design: Difficulty/compensating_invariant/grant_cancel_conserves_pool_authorized_shares
    """
    set_clock("2026-06-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@pc2.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=5000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=2000, strike_price_cents=100,
                                grant_date="2020-01-01T00:00:00Z")
    get_success_data(api.cancel_option_grant(grant["id"], ADMIN))
    pool_after = validate_success(api.get_option_pool(pool["id"], ADMIN), 200)
    assert pool_after["available_shares"] == 5000, (
        f"expected available 5000 == authorized, got {pool_after['available_shares']}"
    )
    assert_pool_conservation(pool_after)


# ============================================================================
# Difficulty/cross_entity_state_dependency/grant_approve_requires_captable_open
# ============================================================================

def test_grant_approve_blocked_when_table_locked(api):
    """PRD §3.6: "A grant may be approved only from `DRAFT` and only while the cap
    table is `OPEN`." The PRD names no distinct error for the not-OPEN case at
    approval; every other "cap table is not OPEN" gate in the PRD — drafting a
    grant, issuing shares, executing a note — is rejected with `ERR_TABLE_NOT_OPEN`,
    so the PRD-faithful reading of the approval gate is the same family.

    Lock the table, then attempt approval → ERR_TABLE_NOT_OPEN; grant stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/grant_approve_requires_captable_open
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@gt.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                         share_count=1000, strike_price_cents=100,
                         grant_date="2025-01-01T00:00:00Z")
    lock_cap_table(ct["id"])
    resp = api.approve_option_grant(grant["id"], APPROVER)
    validate_error(resp, ApiErrorId.ERR_TABLE_NOT_OPEN.value)
    grant_after = validate_success(api.get_option_grant(grant["id"], ADMIN), 200)
    assert grant_after["status"] == "DRAFT", f"expected grant still DRAFT, got {grant_after['status']}"


def test_grant_approve_succeeds_after_table_unlocked(api):
    """PRD §3.6: "A grant may be approved only from `DRAFT` and only while the cap
    table is `OPEN`."

    The gate is specifically the cap table's OPEN state: locking blocks approval,
    but after unlocking the same DRAFT grant approves cleanly to ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/grant_approve_requires_captable_open
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@gt2.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                         share_count=1000, strike_price_cents=100,
                         grant_date="2025-01-01T00:00:00Z")
    locked = lock_cap_table(ct["id"])
    get_success_data(api.unlock_cap_table(
        ct["id"], {"expected_cap_table_version": locked["version"]}, APPROVER))
    data = validate_success(api.approve_option_grant(grant["id"], APPROVER), 200)
    assert data["status"] == "ACTIVE", f"expected ACTIVE after unlock, got {data['status']}"


# ============================================================================
# Difficulty/cross_entity_state_dependency/exercise_reverse_blocked_by_accepted_83b
# ============================================================================

def test_exercise_reverse_blocked_by_accepted_83b_election(api):
    """PRD §3.8: "A `SETTLED` exercise can be reversed only if no `ACCEPTED` 83(b)
    election references it; if one does, the reversal is rejected with
    `ERR_ELECTION_BLOCKS_REVERSE` (HTTP 409)."

    Settled early-exercise with an ACCEPTED 83(b) → reverse rejected; exercise
    stays SETTLED.

    Design: Difficulty/cross_entity_state_dependency/exercise_reverse_blocked_by_accepted_83b
    """
    set_clock("2025-01-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@rv.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2024-06-01T00:00:00Z",
                                     expires_at="2030-06-01T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=10000, strike_price_cents=100,
                                grant_date="2025-01-01T00:00:00Z",
                                early_exercise_allowed=True)
    ex = get_success_data(api.create_exercise({
        "cap_table_id": ct["id"], "option_grant_id": grant["id"], "share_count": 500,
    }, ADMIN))
    get_success_data(api.settle_exercise(ex["id"], ADMIN))
    el = get_success_data(api.create_section_83b_election({
        "cap_table_id": ct["id"], "exercise_id": ex["id"],
        "filed_date": "2025-01-15T00:00:00Z",
    }, ADMIN))
    get_success_data(api.process_section_83b_election(el["id"], ADMIN))
    resp = api.reverse_exercise(ex["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ELECTION_BLOCKS_REVERSE.value)
    ex_after = validate_success(api.get_exercise(ex["id"], ADMIN), 200)
    assert ex_after["status"] == "SETTLED", f"expected SETTLED (unchanged), got {ex_after['status']}"


def test_settled_exercise_without_accepted_83b_can_be_reversed(api):
    """PRD §3.8: "A `SETTLED` exercise can be reversed only if no `ACCEPTED` 83(b)
    election references it."

    The gate is specifically an ACCEPTED election: a SETTLED early-exercise with
    no election reverses cleanly to REVERSED.

    Design: Difficulty/cross_entity_state_dependency/exercise_reverse_blocked_by_accepted_83b
    """
    set_clock("2025-01-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@rv2.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2024-06-01T00:00:00Z",
                                     expires_at="2030-06-01T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=10000, strike_price_cents=100,
                                grant_date="2025-01-01T00:00:00Z",
                                early_exercise_allowed=True)
    ex = get_success_data(api.create_exercise({
        "cap_table_id": ct["id"], "option_grant_id": grant["id"], "share_count": 500,
    }, ADMIN))
    get_success_data(api.settle_exercise(ex["id"], ADMIN))
    data = validate_success(api.reverse_exercise(ex["id"], ADMIN), 200)
    assert data["status"] == "REVERSED", f"expected REVERSED, got {data['status']}"
