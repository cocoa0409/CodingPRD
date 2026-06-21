"""State-machine transitions and cascading side effects: SafeNote revision
cycle, OptionGrant branching terminals, exercise-settle depth-3 cascade,
valuation-approve supersede cascade, and assorted valid/invalid transitions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_active_vested_grant,
    setup_computed_waterfall,
    create_cap_table,
    create_security_class,
    create_shareholder,
    create_effective_valuation,
    create_option_pool,
    create_active_grant,
    create_grant,
    create_outstanding_note,
    create_safe_note,
    set_clock,
    issue_shares,
    api_client,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ============================================================================
# Difficulty/non_linear_state_machine/safe_note_revision_cycle_draft_negotiating
# ============================================================================

def test_safe_note_revise_cycles_back_to_draft(api):
    """PRD §3.10: "Before binding, a note moves through a revision cycle driven
    by an `Administrator`: submitting terms advances it `DRAFT → NEGOTIATING`,
    and revising sends it back `NEGOTIATING → DRAFT` (a revise increments the
    note's `version`)."

    DRAFT → submit-terms → NEGOTIATING → revise → DRAFT.

    Design: Difficulty/non_linear_state_machine/safe_note_revision_cycle_draft_negotiating
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    ang = create_shareholder(ct["id"], legal_name="Angel", holder_type="INVESTOR",
                             email="a@cy.com")
    note = create_safe_note(ct["id"], ang["id"], instrument_type="SAFE",
                            principal_cents=500_000, discount_pct=0.10)
    get_success_data(api.submit_terms_safe_note(note["id"], ADMIN))
    data = validate_success(api.revise_safe_note(note["id"], ADMIN), 200)
    assert data["status"] == "DRAFT", f"expected DRAFT after revise, got {data['status']}"


def test_safe_note_resubmit_reenters_negotiating(api):
    """PRD §3.10: "submitting terms advances it `DRAFT → NEGOTIATING`, and
    revising sends it back `NEGOTIATING → DRAFT`."

    After a revise back to DRAFT, submit-terms re-enters NEGOTIATING (cycle).

    Design: Difficulty/non_linear_state_machine/safe_note_revision_cycle_draft_negotiating
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    ang = create_shareholder(ct["id"], legal_name="Angel", holder_type="INVESTOR",
                             email="a@cy2.com")
    note = create_safe_note(ct["id"], ang["id"], instrument_type="SAFE",
                            principal_cents=500_000, discount_pct=0.10)
    get_success_data(api.submit_terms_safe_note(note["id"], ADMIN))
    get_success_data(api.revise_safe_note(note["id"], ADMIN))
    data = validate_success(api.submit_terms_safe_note(note["id"], ADMIN), 200)
    assert data["status"] == "NEGOTIATING", (
        f"expected NEGOTIATING after resubmit, got {data['status']}"
    )


# ============================================================================
# Difficulty/non_linear_state_machine/option_grant_branching_active_to_cancelled_vs_exercised
# ============================================================================

def test_active_grant_cancel_branch_returns_shares_to_pool(api):
    """PRD §3.6: "A valid `ACTIVE → CANCELLED` cancellation is a compensating
    action that returns the full grant to the pool: the pool's `allocated_shares`
    falls by `share_count`, its `available_shares` is recomputed, the pool flips
    `EXHAUSTED → ACTIVE` if shares were freed."

    ACTIVE grant of 1000 on a 1000-share pool → cancel → pool available back to 1000.

    Design: Difficulty/non_linear_state_machine/option_grant_branching_active_to_cancelled_vs_exercised
    """
    set_clock("2026-06-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@br.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=200,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=1000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=1000, strike_price_cents=200,
                                grant_date="2020-01-01T00:00:00Z")
    data = validate_success(api.cancel_option_grant(grant["id"], ADMIN), 200)
    assert data["status"] == "CANCELLED", f"expected CANCELLED, got {data['status']}"
    pool_after = validate_success(api.get_option_pool(pool["id"], ADMIN), 200)
    assert pool_after["available_shares"] == 1000, (
        f"expected pool available 1000 (returned), got {pool_after['available_shares']}"
    )


def test_active_grant_exercised_branch_does_not_return_shares(api):
    """PRD §3.8: "If, after settling, the grant's `exercised_shares` has reached
    its `share_count`, the grant transitions `ACTIVE → EXERCISED` automatically."

    PRD §3.5: allocated_shares counts grants in ACTIVE or EXERCISED status, so a
    fully-exercised grant keeps its pool allocation (available stays 0).

    Design: Difficulty/non_linear_state_machine/option_grant_branching_active_to_cancelled_vs_exercised
    """
    set_clock("2026-06-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@br2.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=200,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=1000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=1000, strike_price_cents=200,
                                grant_date="2020-01-01T00:00:00Z")
    ex = get_success_data(api.create_exercise({
        "cap_table_id": ct["id"], "option_grant_id": grant["id"], "share_count": 1000,
    }, ADMIN))
    get_success_data(api.settle_exercise(ex["id"], ADMIN))
    grant_after = validate_success(api.get_option_grant(grant["id"], ADMIN), 200)
    assert grant_after["status"] == "EXERCISED", (
        f"expected EXERCISED, got {grant_after['status']}"
    )
    pool_after = validate_success(api.get_option_pool(pool["id"], ADMIN), 200)
    assert pool_after["available_shares"] == 0, (
        f"expected pool available 0 (not returned), got {pool_after['available_shares']}"
    )


# ============================================================================
# Difficulty/transitive_cascade/exercise_settle_depth3_grant_class_table
# ============================================================================

def test_exercise_settle_cascades_grant_class_table(api):
    """PRD §3.8: "Settling moves the exercise `PENDING → SETTLED` and triggers a
    three-level cascade: the grant's `exercised_shares` rises by the exercise's
    `share_count`; the grant's target security class has its `shares_outstanding`
    raised by the same amount; and that in turn recomputes the cap table's
    `issued_shares` and `fully_diluted_shares`."

    Settle 1000 → grant.exercised_shares==1000, class.shares_outstanding==1000,
    table.issued_shares==1000.

    Design: Difficulty/transitive_cascade/exercise_settle_depth3_grant_class_table
    """
    env = setup_active_vested_grant(fmv_per_share_cents=100, strike_price_cents=100,
                                    share_count=1000, clock="2026-06-01T00:00:00Z")
    ex = get_success_data(api.create_exercise({
        "cap_table_id": env["ct"]["id"], "option_grant_id": env["grant"]["id"],
        "share_count": 1000,
    }, ADMIN))
    get_success_data(api.settle_exercise(ex["id"], ADMIN))
    grant = validate_success(api.get_option_grant(env["grant"]["id"], ADMIN), 200)
    assert grant["exercised_shares"] == 1000, f"link1: got {grant['exercised_shares']}"
    cls = validate_success(api.get_security_class(env["common"]["id"], ADMIN), 200)
    assert cls["shares_outstanding"] == 1000, f"link2: got {cls['shares_outstanding']}"
    ct = validate_success(api.get_cap_table(env["ct"]["id"], ADMIN), 200)
    assert ct["issued_shares"] == 1000, f"link3: got {ct['issued_shares']}"


def test_exercise_settle_grant_reaches_exercised_status(api):
    """PRD §3.8: "If, after settling, the grant's `exercised_shares` has reached
    its `share_count`, the grant transitions `ACTIVE → EXERCISED` automatically."

    A full-share settle drives the originating grant from ACTIVE to EXERCISED —
    the terminal end of the settle cascade chain.

    Design: Difficulty/transitive_cascade/exercise_settle_depth3_grant_class_table
    """
    env = setup_active_vested_grant(fmv_per_share_cents=100, strike_price_cents=100,
                                    share_count=1000, clock="2026-06-01T00:00:00Z")
    ex = get_success_data(api.create_exercise({
        "cap_table_id": env["ct"]["id"], "option_grant_id": env["grant"]["id"],
        "share_count": 1000,
    }, ADMIN))
    get_success_data(api.settle_exercise(ex["id"], ADMIN))
    grant = validate_success(api.get_option_grant(env["grant"]["id"], ADMIN), 200)
    assert grant["status"] == "EXERCISED", (
        f"expected grant EXERCISED after full settle, got {grant['status']}"
    )


# ============================================================================
# Difficulty/transitive_cascade/valuation_approve_depth2_supersede_then_fd_reprice
# ============================================================================

def test_valuation_approve_supersedes_prior_effective(api):
    """PRD §3.4: "Approval transitions the valuation `DRAFT → EFFECTIVE` and, as a
    cascade, supersedes the cap table's prior `EFFECTIVE` valuation if one exists:
    that earlier valuation transitions `EFFECTIVE → SUPERSEDED` and its
    `superseded_by_id` is set to the newly effective valuation's id, leaving at
    most one `EFFECTIVE` valuation per cap table at any time."

    Approving V2 supersedes V1: V1.status==SUPERSEDED, V1.superseded_by_id==V2.id,
    V2.status==EFFECTIVE.

    Design: Difficulty/transitive_cascade/valuation_approve_depth2_supersede_then_fd_reprice
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    v1 = get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 200,
        "valuation_date": "2024-01-01T00:00:00Z", "expires_at": "2024-12-31T00:00:00Z",
    }, ADMIN))
    get_success_data(api.approve_valuation(v1["id"], APPROVER))
    v2 = get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 400,
        "valuation_date": "2025-01-01T00:00:00Z", "expires_at": "2025-12-31T00:00:00Z",
    }, ADMIN))
    v2_data = validate_success(api.approve_valuation(v2["id"], APPROVER), 200)
    assert v2_data["status"] == "EFFECTIVE", f"expected V2 EFFECTIVE, got {v2_data['status']}"
    v1_after = validate_success(api.get_valuation(v1["id"], APPROVER), 200)
    assert v1_after["status"] == "SUPERSEDED", (
        f"expected V1 SUPERSEDED, got {v1_after['status']}"
    )
    assert v1_after["superseded_by_id"] == v2["id"], (
        f"expected superseded_by_id == V2, got {v1_after['superseded_by_id']}"
    )


def test_valuation_approve_leaves_at_most_one_effective(api):
    """PRD §3.4: "Approval transitions the valuation `DRAFT → EFFECTIVE` and, as a
    cascade, supersedes the cap table's prior `EFFECTIVE` valuation if one exists
    ... leaving at most one `EFFECTIVE` valuation per cap table at any time."

    After approving V2, exactly one valuation (V2) is EFFECTIVE; the listing shows
    V1 SUPERSEDED and V2 EFFECTIVE.

    Design: Difficulty/transitive_cascade/valuation_approve_depth2_supersede_then_fd_reprice
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    v1 = get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 200,
        "valuation_date": "2024-01-01T00:00:00Z", "expires_at": "2024-12-31T00:00:00Z",
    }, ADMIN))
    get_success_data(api.approve_valuation(v1["id"], APPROVER))
    v2 = get_success_data(api.create_valuation({
        "cap_table_id": ct["id"], "fmv_per_share_cents": 400,
        "valuation_date": "2025-01-01T00:00:00Z", "expires_at": "2025-12-31T00:00:00Z",
    }, ADMIN))
    get_success_data(api.approve_valuation(v2["id"], APPROVER))
    rows = get_success_data(api.list_valuations(APPROVER, params={"cap_table_id": ct["id"], "limit": 100}))
    effective = [r for r in rows if r["status"] == "EFFECTIVE"]
    assert len(effective) == 1, f"expected exactly one EFFECTIVE valuation, got {len(effective)}"
    assert effective[0]["id"] == v2["id"], f"expected V2 EFFECTIVE, got {effective[0]['id']}"


# ============================================================================
# Corner/state_machines/cancel_grant_from_cancelled_returns_invalid_state
# ============================================================================

def test_cancel_already_cancelled_grant_rejected(api):
    """PRD §3.1: "A transition requested from the wrong starting state — for
    example, dissolving a table that is already `LOCKED`, or unlocking one that is
    `OPEN` — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    A DRAFT grant cancelled to CANCELLED, then cancelled again → ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_grant_from_cancelled_returns_invalid_state
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@id.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=10_000)
    grant = create_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                         share_count=1000, strike_price_cents=100,
                         grant_date="2025-01-01T00:00:00Z")
    get_success_data(api.cancel_option_grant(grant["id"], ADMIN))
    resp = api.cancel_option_grant(grant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ============================================================================
# Corner/state_machines/dissolve_blocked_by_active_grant_returns_invalid_state
# ============================================================================

def test_dissolve_blocked_by_active_grant(api):
    """PRD §3.6: "Recall from §3.1 that a cap table cannot be dissolved while any
    grant remains `ACTIVE`."

    PRD §3.1: dissolution "is permitted only when no option grant on the table is
    in `ACTIVE` status" and a wrong-state transition is "rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/dissolve_blocked_by_active_grant_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@dis.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=10_000)
    create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                        share_count=1000, strike_price_cents=100,
                        grant_date="2020-01-01T00:00:00Z")
    resp = api.dissolve_cap_table(ct["id"], APPROVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ============================================================================
# Corner/state_machines/note_repay_path_from_outstanding
# ============================================================================

def test_outstanding_note_repaid_mints_no_shares(api):
    """PRD §3.10: "a `BoardApprover` may either repay the note
    (`OUTSTANDING → REPAID`, the note-only path where principal and accrued
    interest are returned and no shares are minted) or convert it."

    Repaying an OUTSTANDING NOTE → status REPAID; converted_share_count stays 0.

    Design: Corner/state_machines/note_repay_path_from_outstanding
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    sh = create_shareholder(ct["id"], legal_name="Lender", holder_type="INVESTOR",
                            email="l@rp.com")
    note = create_outstanding_note(ct["id"], sh["id"], instrument_type="NOTE",
                                   principal_cents=1_000_000, interest_rate_pct=0.08)
    data = validate_success(api.repay_safe_note(note["id"], APPROVER), 200)
    assert data["status"] == "REPAID", f"expected REPAID, got {data['status']}"
    assert data["converted_share_count"] == 0, (
        f"expected converted_share_count 0, got {data['converted_share_count']}"
    )


# ============================================================================
# Corner/state_machines/liquidation_recompute_clears_distributions
# ============================================================================

def test_liquidation_recompute_clears_distributions_and_reverts_to_draft(api):
    """PRD §3.12: "From `COMPUTED`, the approver may recompute — which deletes
    every waterfall distribution row for the event and returns it to `DRAFT` so
    the allocation can be re-run."

    recompute → event DRAFT and the distributions list is empty.

    Design: Corner/state_machines/liquidation_recompute_clears_distributions
    """
    env = setup_computed_waterfall(
        classes=[
            {"key": "C", "name": "Common", "class_type": "COMMON", "oip": 0,
             "pref_multiple": 0, "senior_to": None, "shares": 100},
        ],
        proceeds_cents=1_000_000, email_suffix="rc",
    )
    data = validate_success(api.recompute_liquidation_event(env["event"]["id"], APPROVER), 200)
    assert data["status"] == "DRAFT", f"expected DRAFT after recompute, got {data['status']}"
    rows = get_success_data(api.list_event_distributions(env["event"]["id"], AUDITOR))
    assert len(rows) == 0, f"expected 0 distributions after recompute, got {len(rows)}"


# ============================================================================
# Corner/state_machines/blackout_lift_then_overlap_allowed
# ============================================================================

def test_lifted_blackout_window_no_longer_blocks_overlap(api):
    """PRD §3.11: "An `Administrator` may lift a scheduled window, transitioning
    it `SCHEDULED → LIFTED`; a lifted window no longer participates in overlap
    checks, freeing its interval."

    Lift window 1, then create an overlapping window 2 → accepted (201).

    Design: Corner/state_machines/blackout_lift_then_overlap_allowed
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    w1 = get_success_data(api.create_blackout_window({
        "cap_table_id": ct["id"], "reason": "PRE_EARNINGS",
        "starts_at": "2025-01-01T00:00:00Z", "ends_at": "2025-02-01T00:00:00Z",
    }, ADMIN))
    get_success_data(api.lift_blackout_window(w1["id"], ADMIN))
    data = validate_success(api.create_blackout_window({
        "cap_table_id": ct["id"], "reason": "ACQUISITION",
        "starts_at": "2025-01-15T00:00:00Z", "ends_at": "2025-02-15T00:00:00Z",
    }, ADMIN), 201)
    assert data["status"] == "SCHEDULED", f"expected SCHEDULED, got {data['status']}"
