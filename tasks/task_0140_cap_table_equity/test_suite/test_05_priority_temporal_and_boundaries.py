"""Validation-priority conflicts, resource temporal-overlap geometry (closed
valuation windows vs half-open blackout windows), and the 30-day 83(b) boundary.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_administrator_headers,
    make_board_approver_headers,
    create_cap_table,
    create_security_class,
    create_shareholder,
    create_effective_valuation,
    create_option_pool,
    create_grant,
    create_active_grant,
    set_clock,
    api_client,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]


# ============================================================================
# Difficulty/priority_pair_validation_conflict/state_vs_fiscal_grant_approve_terminal_and_pool
# ============================================================================

def test_state_error_beats_pool_insufficient_on_cancelled_grant(api):
    """PRD §3.6: "A grant may be approved only from `DRAFT` and only while the cap
    table is `OPEN`." PRD §4: "Every request must satisfy the authentication,
    authorization, and existence checks of §2 before any business rule is
    evaluated; the order in which the remaining validations fire is described
    alongside each workflow in §3."

    PRD §3.1: "A transition requested from the wrong starting state — for example,
    dissolving a table that is already `LOCKED`, or unlocking one that is `OPEN` —
    is rejected with `ERR_INVALID_STATE` (HTTP 409)." A CANCELLED grant whose
    share_count also exceeds the pool returns the state error, not the pool error.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_grant_approve_terminal_and_pool
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@pr.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=500)
    grant = create_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                         share_count=1000, strike_price_cents=100,
                         grant_date="2025-01-01T00:00:00Z")
    get_success_data(api.cancel_option_grant(grant["id"], ADMIN))
    resp = api.approve_option_grant(grant["id"], APPROVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_vs_fiscal_conflict_leaves_grant_cancelled(api):
    """PRD §3.1: "A transition requested from the wrong starting state — for
    example, dissolving a table that is already `LOCKED`, or unlocking one that is
    `OPEN` — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    When the state error wins over the pool error, no state change occurs: the
    grant stays CANCELLED (it never transitions to ACTIVE).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_grant_approve_terminal_and_pool
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@pr2.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=500)
    grant = create_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                         share_count=1000, strike_price_cents=100,
                         grant_date="2025-01-01T00:00:00Z")
    get_success_data(api.cancel_option_grant(grant["id"], ADMIN))
    api.approve_option_grant(grant["id"], APPROVER)
    grant_after = validate_success(api.get_option_grant(grant["id"], ADMIN), 200)
    assert grant_after["status"] == "CANCELLED", (
        f"expected grant still CANCELLED, got {grant_after['status']}"
    )


# ============================================================================
# Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_grant_approve_sod_and_pool
# ============================================================================

def test_segregation_of_duties_beats_pool_insufficient(api):
    """PRD §3.6: "The approving `BoardApprover`'s `X-User-ID` must differ from the
    `Administrator` who drafted the grant; an attempt by the same user to both
    draft and approve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD §2.1: roles are checked before business rules. Same-user draft+approve on
    an over-allocated pool returns the SoD error, not the pool error.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_grant_approve_sod_and_pool
    """
    drafter = make_administrator_headers("drafter-1")
    ct = get_success_data(api.create_cap_table(
        {"company_name": "SodCo", "authorized_shares": 10_000_000}, drafter))
    common = get_success_data(api.create_security_class({
        "cap_table_id": ct["id"], "name": "Common", "class_type": "COMMON",
        "original_issue_price_cents": 0, "liquidation_pref_multiple": 0,
    }, drafter))
    sh = get_success_data(api.create_shareholder({
        "cap_table_id": ct["id"], "legal_name": "Emp", "holder_type": "EMPLOYEE",
        "email": "e@sod.com",
    }, drafter))
    val = get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 100,
        "valuation_date": "2025-01-01T00:00:00Z", "expires_at": "2025-12-31T00:00:00Z",
    }, drafter))
    get_success_data(api.approve_valuation(val["id"], make_board_approver_headers("approver-1")))
    pool = get_success_data(api.create_option_pool({
        "cap_table_id": ct["id"], "authorized_shares": 500,
    }, drafter))
    grant = get_success_data(api.create_option_grant({
        "cap_table_id": ct["id"], "option_pool_id": pool["id"], "shareholder_id": sh["id"],
        "security_class_id": common["id"], "valuation_id": val["id"], "share_count": 1000,
        "strike_price_cents": 100, "grant_date": "2025-01-01T00:00:00Z",
        "vesting_months": 48, "cliff_months": 12,
    }, drafter))
    # Same user "drafter-1" attempts the approval as BoardApprover.
    resp = api.approve_option_grant(grant["id"], make_board_approver_headers("drafter-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_segregation_of_duties_allows_different_approver(api):
    """PRD §3.6: "The approving `BoardApprover`'s `X-User-ID` must differ from the
    `Administrator` who drafted the grant."

    The gate is specifically same-vs-different user: a grant drafted by
    "drafter-1" approves cleanly when a different user approves it.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_grant_approve_sod_and_pool
    """
    drafter = make_administrator_headers("drafter-1")
    ct = get_success_data(api.create_cap_table(
        {"company_name": "SodOkCo", "authorized_shares": 10_000_000}, drafter))
    common = get_success_data(api.create_security_class({
        "cap_table_id": ct["id"], "name": "Common", "class_type": "COMMON",
        "original_issue_price_cents": 0, "liquidation_pref_multiple": 0,
    }, drafter))
    sh = get_success_data(api.create_shareholder({
        "cap_table_id": ct["id"], "legal_name": "Emp", "holder_type": "EMPLOYEE",
        "email": "e@sodok.com",
    }, drafter))
    val = get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 100,
        "valuation_date": "2025-01-01T00:00:00Z", "expires_at": "2025-12-31T00:00:00Z",
    }, drafter))
    get_success_data(api.approve_valuation(val["id"], make_board_approver_headers("approver-1")))
    # Pool large enough that the fiscal check passes, isolating the SoD gate.
    pool = get_success_data(api.create_option_pool({
        "cap_table_id": ct["id"], "authorized_shares": 100_000,
    }, drafter))
    grant = get_success_data(api.create_option_grant({
        "cap_table_id": ct["id"], "option_pool_id": pool["id"], "shareholder_id": sh["id"],
        "security_class_id": common["id"], "valuation_id": val["id"], "share_count": 1000,
        "strike_price_cents": 100, "grant_date": "2025-01-01T00:00:00Z",
        "vesting_months": 48, "cliff_months": 12,
    }, drafter))
    data = validate_success(
        api.approve_option_grant(grant["id"], make_board_approver_headers("approver-2")), 200)
    assert data["status"] == "ACTIVE", f"expected ACTIVE with different approver, got {data['status']}"


# ============================================================================
# Difficulty/resource_temporal_overlap/valuation_window_closed_overlap_adjacency_conflicts
# ============================================================================

def test_valuation_window_adjacency_conflicts_closed_semantics(api):
    """PRD §3.4: "a new valuation is rejected with `ERR_VALUATION_WINDOW_OVERLAP`
    (HTTP 409) if its window overlaps the window of any non-`SUPERSEDED`
    valuation already on the same cap table, and because the interval is closed,
    two windows that merely touch at a shared endpoint — one ending exactly when
    the other begins — are considered to conflict."

    Existing [2024-01-01, 2024-12-31]; new [2024-12-31, 2025-12-31] touches at
    2024-12-31 → ERR_VALUATION_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/valuation_window_closed_overlap_adjacency_conflicts
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 200,
        "valuation_date": "2024-01-01T00:00:00Z", "expires_at": "2024-12-31T00:00:00Z",
    }, ADMIN))
    resp = api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 300,
        "valuation_date": "2024-12-31T00:00:00Z", "expires_at": "2025-12-31T00:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALUATION_WINDOW_OVERLAP.value)


def test_valuation_window_disjoint_accepted(api):
    """PRD §3.4: "a new valuation is rejected with `ERR_VALUATION_WINDOW_OVERLAP`
    (HTTP 409) if its window overlaps the window of any non-`SUPERSEDED`
    valuation already on the same cap table."

    A strictly-later window that does not touch the existing one is accepted —
    the overlap rule only fires on actual overlap/adjacency, not on disjoint
    windows.

    Design: Difficulty/resource_temporal_overlap/valuation_window_closed_overlap_adjacency_conflicts
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 200,
        "valuation_date": "2024-01-01T00:00:00Z", "expires_at": "2024-12-31T00:00:00Z",
    }, ADMIN))
    data = validate_success(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 300,
        "valuation_date": "2025-01-02T00:00:00Z", "expires_at": "2025-12-31T00:00:00Z",
    }, ADMIN), 201)
    assert data["status"] == "DRAFT", f"expected DRAFT (disjoint accepted), got {data['status']}"


# ============================================================================
# Difficulty/resource_temporal_overlap/blackout_window_halfopen_adjacency_allowed
# ============================================================================

def test_blackout_window_adjacency_allowed_half_open(api):
    """PRD §3.11: "a blackout interval `[starts_at, ends_at)` is **half-open**: a
    new window is rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409) only when it
    strictly overlaps a `SCHEDULED` window already on the same cap table, and two
    windows that merely abut — one ending exactly when the next begins — do *not*
    conflict."

    Existing [2025-01-01, 2025-02-01); new [2025-02-01, 2025-03-01) abuts at
    2025-02-01 → accepted (201).

    Design: Difficulty/resource_temporal_overlap/blackout_window_halfopen_adjacency_allowed
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    get_success_data(api.create_blackout_window({
        "cap_table_id": ct["id"], "reason": "PRE_EARNINGS",
        "starts_at": "2025-01-01T00:00:00Z", "ends_at": "2025-02-01T00:00:00Z",
    }, ADMIN))
    data = validate_success(api.create_blackout_window({
        "cap_table_id": ct["id"], "reason": "ACQUISITION",
        "starts_at": "2025-02-01T00:00:00Z", "ends_at": "2025-03-01T00:00:00Z",
    }, ADMIN), 201)
    assert data["status"] == "SCHEDULED", f"expected SCHEDULED, got {data['status']}"


def test_blackout_window_strict_overlap_rejected_half_open(api):
    """PRD §3.11: "a new window is rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409)
    only when it strictly overlaps a `SCHEDULED` window already on the same cap
    table."

    Existing [2025-01-01, 2025-02-01); new [2025-01-15, 2025-02-15) strictly
    overlaps → ERR_BLACKOUT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/blackout_window_halfopen_adjacency_allowed
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    get_success_data(api.create_blackout_window({
        "cap_table_id": ct["id"], "reason": "PRE_EARNINGS",
        "starts_at": "2025-01-01T00:00:00Z", "ends_at": "2025-02-01T00:00:00Z",
    }, ADMIN))
    resp = api.create_blackout_window({
        "cap_table_id": ct["id"], "reason": "ACQUISITION",
        "starts_at": "2025-01-15T00:00:00Z", "ends_at": "2025-02-15T00:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_OVERLAP.value)


# ============================================================================
# Difficulty/boundary_precision_check/section_83b_filing_boundary_day_30_vs_31
# ============================================================================

def _settled_early_exercise(ct_id, grant_id, share_count=500):
    ex = get_success_data(api_client.create_exercise({
        "cap_table_id": ct_id, "option_grant_id": grant_id, "share_count": share_count,
    }, ADMIN))
    get_success_data(api_client.settle_exercise(ex["id"], ADMIN))
    return ex


def test_83b_filed_exactly_30_days_accepted(api):
    """PRD §3.9: "From `PENDING`, if the `filed_date` is on or before the
    `exercise_date` plus 30 days — the boundary at exactly 30 days counts as
    on-time — the election transitions to `ACCEPTED`."

    exercise_date 2025-01-01, filed 2025-01-31 (+30 days, inclusive) → ACCEPTED.

    Design: Difficulty/boundary_precision_check/section_83b_filing_boundary_day_30_vs_31
    """
    set_clock("2025-01-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@el.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2024-06-01T00:00:00Z",
                                     expires_at="2030-06-01T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=10000, strike_price_cents=100,
                                grant_date="2025-01-01T00:00:00Z",
                                early_exercise_allowed=True)
    ex = _settled_early_exercise(ct["id"], grant["id"])
    el = get_success_data(api.create_section_83b_election({
        "cap_table_id": ct["id"], "exercise_id": ex["id"],
        "filed_date": "2025-01-31T00:00:00Z",
    }, ADMIN))
    data = validate_success(api.process_section_83b_election(el["id"], ADMIN), 200)
    assert data["status"] == "ACCEPTED", f"expected ACCEPTED at +30d, got {data['status']}"


def test_83b_filed_31_days_rejected_late(api):
    """PRD §3.9: "if the `filed_date` falls strictly later than 30 days after the
    `exercise_date`, the same adjudication transitions it to `REJECTED_LATE`."

    exercise_date 2025-01-01, filed 2025-02-01 (+31 days) → REJECTED_LATE.

    Design: Difficulty/boundary_precision_check/section_83b_filing_boundary_day_30_vs_31
    """
    set_clock("2025-01-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@el2.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2024-06-01T00:00:00Z",
                                     expires_at="2030-06-01T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=10000, strike_price_cents=100,
                                grant_date="2025-01-01T00:00:00Z",
                                early_exercise_allowed=True)
    ex = _settled_early_exercise(ct["id"], grant["id"])
    el = get_success_data(api.create_section_83b_election({
        "cap_table_id": ct["id"], "exercise_id": ex["id"],
        "filed_date": "2025-02-01T00:00:00Z",
    }, ADMIN))
    data = validate_success(api.process_section_83b_election(el["id"], ADMIN), 200)
    assert data["status"] == "REJECTED_LATE", f"expected REJECTED_LATE at +31d, got {data['status']}"
