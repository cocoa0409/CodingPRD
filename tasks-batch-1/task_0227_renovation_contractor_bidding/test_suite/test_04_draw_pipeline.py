"""Draw pipeline and disputes: sequential milestone gating, sequence-slot
uniqueness, the escrow-availability gate on approval, the final-draw retainage
release cascade, the dispute branching machine (UPHELD/OVERTURNED) and its
multi-hop cascades, compensating invariants, lien-waiver rules, and change orders.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    create_homeowner,
    create_qualified_contractor,
    create_draft_project,
    open_project,
    create_submitted_bid,
    award_bid,
    get_project_escrow,
    fund_escrow,
    setup_in_progress_project,
    setup_approved_draw,
    setup_disputed_draw,
    request_draw,
    approve_draw,
    file_unconditional_waiver,
    pay_draw,
    request_approve_pay_draw,
    propose_change_order,
    current_bid_version,
    approve_change_order,
    make_homeowner_headers,
    make_contractor_headers,
)
from test_helpers import TEST_USERS


_TWO_MS = [{"sequence": 1, "release_pct": 0.40}, {"sequence": 2, "release_pct": 0.60}]


# ───────────────────────── Milestone sequence-slot uniqueness ──────────────
def test_milestone_duplicate_sequence_rejected(api):
    """PRD §3.2: "If a homeowner tries to add a milestone whose `sequence` ordinal
    is already occupied by an existing milestone on that project, the request is
    rejected with `ERR_MILESTONE_SEQUENCE_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/milestone_sequence_slot_collision_point_uniqueness
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    project = get_success_data(api.create_project(
        {"homeowner_id": homeowner["id"], "title": "MileProj", "budget_cap_cents": 1_000_000,
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL", "min_rating": 0},
        ho))
    validate_success(api.create_milestone(
        project["id"], {"sequence": 1, "title": "P1", "release_pct": 0.50}, ho), 201)
    res = api.create_milestone(
        project["id"], {"sequence": 1, "title": "P1-dup", "release_pct": 0.50}, ho)
    validate_error(res, "ERR_MILESTONE_SEQUENCE_TAKEN")


def test_milestone_duplicate_sequence_leaves_single_milestone(api):
    """PRD §3.2: "If a homeowner tries to add a milestone whose `sequence` ordinal
    is already occupied by an existing milestone on that project, the request is
    rejected with `ERR_MILESTONE_SEQUENCE_TAKEN`."

    The rejected duplicate must not be persisted: only the original milestone
    remains on the project.

    Design: Difficulty/resource_temporal_overlap/milestone_sequence_slot_collision_point_uniqueness
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    project = get_success_data(api.create_project(
        {"homeowner_id": homeowner["id"], "title": "MileProj2", "budget_cap_cents": 1_000_000,
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL", "min_rating": 0},
        ho))
    validate_success(api.create_milestone(
        project["id"], {"sequence": 1, "title": "P1", "release_pct": 0.50}, ho), 201)
    api.create_milestone(
        project["id"], {"sequence": 1, "title": "P1-dup", "release_pct": 0.50}, ho)
    listing = validate_success(api.list_milestones(project["id"], ho), 200)
    assert len(listing) == 1, listing


# ───────────────────────── Sequential draw gating ──────────────────────────
def test_draw_for_higher_milestone_while_lower_pending_rejected(api):
    """PRD §3.6: "The request is admissible only when the project is `IN_PROGRESS`,
    and only for the lowest-`sequence` milestone of the project that is still in
    `PENDING` status; requesting a draw against any other milestone — including
    skipping ahead — is rejected with `ERR_MILESTONE_OUT_OF_ORDER`."

    Design: Difficulty/resource_temporal_overlap/draw_sequential_adjacency_gating_next_slot_only
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m2 = ctx["milestones"][1]
    res = api.create_draw(
        {"project_id": ctx["project"]["id"], "milestone_id": m2["id"],
         "conditional_waiver_amount_cents": 360_000},
        make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, "ERR_MILESTONE_OUT_OF_ORDER")


def test_draw_out_of_order_leaves_milestones_pending(api):
    """PRD §3.6: "requesting a draw against any other milestone — including
    skipping ahead — is rejected with `ERR_MILESTONE_OUT_OF_ORDER`."

    No draw is created and both milestones stay PENDING after the rejected
    skip-ahead request.

    Design: Difficulty/resource_temporal_overlap/draw_sequential_adjacency_gating_next_slot_only
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1, m2 = ctx["milestones"]
    api.create_draw(
        {"project_id": ctx["project"]["id"], "milestone_id": m2["id"],
         "conditional_waiver_amount_cents": 360_000},
        make_contractor_headers(ctx["contractor"]["id"]))
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    listing = validate_success(api.list_milestones(ctx["project"]["id"], ho), 200)
    by_id = {m["id"]: m for m in listing}
    assert by_id[m1["id"]]["status"] == "PENDING", by_id[m1["id"]]
    assert by_id[m2["id"]]["status"] == "PENDING", by_id[m2["id"]]


# ───────────────────────── Escrow-availability gate on approval ────────────
def test_draw_approval_at_exact_available_boundary_succeeds(api):
    """PRD §3.6: "Approving it requires that the draw be in `REQUESTED` status and
    that the escrow's `available_cents` be at least the draw's `gross_amount_cents`;
    if the escrow cannot cover the gross amount the approval is rejected with
    `ERR_INSUFFICIENT_ESCROW`."

    After draw1 (seq1) is paid, available == 360000; draw2 (seq2 final) has gross
    360000, exactly meeting the >= boundary, so approval succeeds.

    Design: Difficulty/cross_entity_state_dependency/draw_approve_requires_escrow_available_funds
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1, m2 = ctx["milestones"]
    request_approve_pay_draw(ctx, m1, 216_000)  # leaves available 360000
    draw2 = request_draw(ctx, m2, 360_000)      # final, retainage 0, gross 360000
    approved2 = approve_draw(ctx, draw2)
    assert approved2["status"] == "APPROVED", approved2
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    assert escrow["available_cents"] == 360_000, escrow  # final retainage 0


def test_draw_approval_below_available_rejected(api):
    """PRD §3.6: "if the escrow cannot cover the gross amount the approval is
    rejected with `ERR_INSUFFICIENT_ESCROW`."
    PRD §3.7: "On approval, the change order moves from `PROPOSED` to `APPROVED`,
    the project's `contract_value_cents` is increased by the `delta_cents`."

    After draw1 (seq1, 0.40) is paid, available == 360000. A +300000 change order
    raises contract_value to 900000, so draw2 (final, 0.60) computes gross 540000
    > available 360000, and approval is rejected.

    Design: Difficulty/cross_entity_state_dependency/draw_approve_requires_escrow_available_funds
    """
    ctx = setup_in_progress_project(
        contract_value_cents=600_000, milestones=_TWO_MS, budget_cap_cents=1_000_000)
    m1, m2 = ctx["milestones"]
    request_approve_pay_draw(ctx, m1, 216_000)  # available now 360000

    co = propose_change_order(ctx, 300_000)
    approve_change_order(ctx, co, current_bid_version(ctx))  # contract_value -> 900000

    # draw2 final: gross round(900000*0.60)=540000, retainage 0, net 540000.
    draw2 = request_draw(ctx, m2, 540_000)
    res = api.approve_draw(draw2["id"], make_homeowner_headers(ctx["homeowner"]["id"]))
    validate_error(res, "ERR_INSUFFICIENT_ESCROW")


# ───────────────────────── Final-draw retainage release cascade ────────────
def test_final_draw_pay_marks_draw_and_milestone_paid(api):
    """PRD §3.6: "Paying an approved draw moves it from `APPROVED` to the terminal
    `PAID` state, moves its milestone from `APPROVED` to the terminal `PAID` state,
    and moves the draw's `net_release_cents` within the escrow out of
    `available_cents` and into `released_cents`."

    Design: Difficulty/transitive_cascade/final_draw_pay_cascade_releases_retainage_depth3
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1, m2 = ctx["milestones"]
    request_approve_pay_draw(ctx, m1, 216_000)
    draw2 = request_draw(ctx, m2, 360_000)
    approve_draw(ctx, draw2)
    file_unconditional_waiver(ctx, draw2, 360_000)
    paid2 = pay_draw(ctx, draw2)
    assert paid2["status"] == "PAID", paid2

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    listing = validate_success(api.list_milestones(ctx["project"]["id"], ho), 200)
    by_id = {m["id"]: m for m in listing}
    assert by_id[m2["id"]]["status"] == "PAID", by_id[m2["id"]]


def test_final_draw_pay_releases_accumulated_retainage(api):
    """PRD §3.6: "If — and only if — the paid draw is the one against the
    final-sequence milestone, the retainage that has been accumulating is released
    at this moment: the entire `retained_cents` balance is added to
    `released_cents` and `retained_cents` is reset to zero."

    draw1 paid (released 216000, retained 24000); paying the final draw2 (net
    360000) releases its net plus the 24000 retainage: released
    216000+360000+24000 == 600000, retained 0, available 0.

    Design: Difficulty/transitive_cascade/final_draw_pay_cascade_releases_retainage_depth3
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1, m2 = ctx["milestones"]
    request_approve_pay_draw(ctx, m1, 216_000)
    draw2 = request_draw(ctx, m2, 360_000)
    approve_draw(ctx, draw2)
    file_unconditional_waiver(ctx, draw2, 360_000)
    pay_draw(ctx, draw2)

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    assert escrow["retained_cents"] == 0, escrow
    assert escrow["released_cents"] == 600_000, escrow
    assert escrow["available_cents"] == 0, escrow


# ───────────────────────── Dispute branching machine ───────────────────────
def test_dispute_overturned_rejects_draw_and_returns_retainage(api):
    """PRD §3.9: "When the resolution is `OVERTURNED`, the draw is unwound: the
    disputed draw's `status` becomes the terminal `REJECTED`, its milestone's
    `status` returns to `PENDING`, the draw's `CONDITIONAL` lien waiver is voided
    to `VOIDED`, and — if the draw had been `APPROVED` before the dispute froze it
    — the draw's `retainage_cents` is returned within the escrow from
    `retained_cents` back to `available_cents`, undoing the retainage hold that
    approval had created."

    Design: Difficulty/non_linear_state_machine/draw_branching_disputed_to_approved_or_rejected
    """
    ctx, draw, dispute = setup_disputed_draw(contract_value_cents=600_000)
    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"resolution": "OVERTURNED"},
        TEST_USERS["platform_admin_headers"]), 200)
    assert resolved["status"] == "RESOLVED", resolved

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    draw_after = validate_success(api.get_draw(draw["id"], ho), 200)
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    assert draw_after["status"] == "REJECTED", draw_after
    assert escrow["retained_cents"] == 0, escrow
    assert escrow["available_cents"] == 600_000, escrow


def test_dispute_upheld_restores_approved_draw(api):
    """PRD §3.9: "When the resolution is `UPHELD`, the contractor's position
    stands: the disputed draw's `status` is restored to `APPROVED` and its
    milestone's `status` is restored to `APPROVED`."

    The OTHER branch of the disputed-draw machine: UPHELD restores APPROVED.

    Design: Difficulty/non_linear_state_machine/draw_branching_disputed_to_approved_or_rejected
    """
    ctx, draw, dispute = setup_disputed_draw(contract_value_cents=600_000)
    validate_success(api.resolve_dispute(
        dispute["id"], {"resolution": "UPHELD"},
        TEST_USERS["platform_admin_headers"]), 200)

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    draw_after = validate_success(api.get_draw(draw["id"], ho), 200)
    assert draw_after["status"] == "APPROVED", draw_after


# ───────────────────────── Dispute OVERTURNED depth-3 cascade ──────────────
def test_overturn_resolves_dispute_rejects_draw_resets_milestone(api):
    """PRD §3.9: "Resolving moves the dispute from `OPEN` to the terminal
    `RESOLVED` state, records the supplied outcome in `resolution`, and returns the
    project's `status` from `DISPUTED` back to `IN_PROGRESS`."
    PRD §3.9: "When the resolution is `OVERTURNED`, the draw is unwound: the
    disputed draw's `status` becomes the terminal `REJECTED`, its milestone's
    `status` returns to `PENDING`."

    Design: Difficulty/transitive_cascade/dispute_overturn_cascade_draw_milestone_escrow_depth3
    """
    ctx, draw, dispute = setup_disputed_draw(contract_value_cents=600_000)
    m1 = ctx["milestones"][0]
    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"resolution": "OVERTURNED"},
        TEST_USERS["platform_admin_headers"]), 200)
    assert resolved["status"] == "RESOLVED", resolved
    assert resolved["resolution"] == "OVERTURNED", resolved

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    draw_after = validate_success(api.get_draw(draw["id"], ho), 200)
    assert draw_after["status"] == "REJECTED", draw_after
    listing = validate_success(api.list_milestones(ctx["project"]["id"], ho), 200)
    m1_after = next(m for m in listing if m["id"] == m1["id"])
    assert m1_after["status"] == "PENDING", m1_after


def test_overturn_returns_retainage_and_restores_project_in_progress(api):
    """PRD §3.9: "the draw's `retainage_cents` is returned within the escrow from
    `retained_cents` back to `available_cents`, undoing the retainage hold that
    approval had created."
    PRD §3.9: "and returns the project's `status` from `DISPUTED` back to
    `IN_PROGRESS`."

    Design: Difficulty/transitive_cascade/dispute_overturn_cascade_draw_milestone_escrow_depth3
    """
    ctx, draw, dispute = setup_disputed_draw(contract_value_cents=600_000)
    validate_success(api.resolve_dispute(
        dispute["id"], {"resolution": "OVERTURNED"},
        TEST_USERS["platform_admin_headers"]), 200)

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    assert escrow["retained_cents"] == 0, escrow
    assert escrow["available_cents"] == 600_000, escrow
    assert project["status"] == "IN_PROGRESS", project


# ───────────────────────── Compensating invariants ─────────────────────────
def test_escrow_funds_conserved_after_approve_then_overturn(api):
    """PRD §2.6: "`available_cents`, which is always equal to `funded_cents` minus
    `released_cents` minus `retained_cents`."
    PRD §3.9: "the draw's `retainage_cents` is returned within the escrow from
    `retained_cents` back to `available_cents`, undoing the retainage hold that
    approval had created."

    After approve (retainage held) then OVERTURNED (retainage returned), total
    money is conserved: funded 600000 == available 600000 + released 0 +
    retained 0.

    Design: Difficulty/compensating_invariant/escrow_funds_conserved_on_approve_then_overturn
    """
    ctx, draw, dispute = setup_disputed_draw(contract_value_cents=600_000)
    validate_success(api.resolve_dispute(
        dispute["id"], {"resolution": "OVERTURNED"},
        TEST_USERS["platform_admin_headers"]), 200)

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    assert escrow["funded_cents"] == 600_000, escrow
    assert escrow["available_cents"] == 600_000, escrow
    assert escrow["released_cents"] == 0, escrow
    assert escrow["retained_cents"] == 0, escrow
    assert escrow["funded_cents"] == (
        escrow["available_cents"] + escrow["released_cents"] + escrow["retained_cents"]
    )


def test_escrow_retainage_held_after_approval(api):
    """PRD §3.6: "On approval, the draw moves from `REQUESTED` to `APPROVED`, its
    milestone moves from `DRAW_REQUESTED` to `APPROVED`, and the draw's
    `retainage_cents` is moved within the escrow out of `available_cents` and into
    `retained_cents`."

    Forward leg of the conservation pair: after approving the non-final draw, the
    24000 retainage is held in retained_cents and available drops accordingly, but
    funded == available + released + retained still holds.

    Design: Difficulty/compensating_invariant/escrow_funds_conserved_on_approve_then_overturn
    """
    ctx, draw = setup_approved_draw(contract_value_cents=600_000)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    assert escrow["retained_cents"] == 24_000, escrow
    assert escrow["available_cents"] == 576_000, escrow
    assert escrow["funded_cents"] == (
        escrow["available_cents"] + escrow["released_cents"] + escrow["retained_cents"]
    )


def test_conditional_waiver_voided_on_draw_reject(api):
    """PRD §3.6: "The homeowner may instead reject a requested draw: rejection
    moves the draw from `REQUESTED` to the terminal `REJECTED` state, returns its
    milestone from `DRAW_REQUESTED` back to `PENDING` so the draw can be
    re-requested, and voids the draw's `CONDITIONAL` lien waiver by moving that
    waiver's `status` to `VOIDED`."

    Design: Difficulty/compensating_invariant/conditional_waiver_count_conserved_on_request_then_reject
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1 = ctx["milestones"][0]
    draw = request_draw(ctx, m1, 216_000)
    waiver_id = draw["lien_waiver_id"]
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    rejected = validate_success(api.reject_draw(draw["id"], ho), 200)
    assert rejected["status"] == "REJECTED", rejected

    waiver = validate_success(api.get_lien_waiver(waiver_id, ho), 200)
    assert waiver["status"] == "VOIDED", waiver
    listing = validate_success(api.list_milestones(ctx["project"]["id"], ho), 200)
    m1_after = next(m for m in listing if m["id"] == m1["id"])
    assert m1_after["status"] == "PENDING", m1_after


def test_collected_conditional_waiver_count_zero_after_reject(api):
    """PRD §3.6: "voids the draw's `CONDITIONAL` lien waiver by moving that
    waiver's `status` to `VOIDED`."

    Conserved quantity: the count of COLLECTED CONDITIONAL waivers on the project
    returns to zero after the request+reject pair.

    Design: Difficulty/compensating_invariant/conditional_waiver_count_conserved_on_request_then_reject
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1 = ctx["milestones"][0]
    draw = request_draw(ctx, m1, 216_000)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    api.reject_draw(draw["id"], ho)

    listing = validate_success(
        api.list_lien_waivers(ho, params={"project_id": ctx["project"]["id"]}), 200)
    collected_conditional = [
        w for w in listing
        if w["waiver_type"] == "CONDITIONAL" and w["status"] == "COLLECTED"
    ]
    assert len(collected_conditional) == 0, collected_conditional


# ───────────────────────── Lien waiver mismatch (queue B) ──────────────────
def test_draw_request_with_wrong_conditional_waiver_amount_rejected(api):
    """PRD §3.6: "A draw request must be accompanied by a conditional lien waiver:
    the `conditional_waiver_amount_cents` supplied with the request must equal the
    draw's computed `net_release_cents`, otherwise the request is rejected with
    `ERR_LIEN_WAIVER_REQUIRED`."

    Correct net for the seq1 (0.40) draw is 216000; supplying 999999 is rejected
    and no draw is created (milestone stays PENDING).

    Design: Corner/validations/lien_waiver_amount_mismatch_on_draw_request
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, milestones=_TWO_MS)
    m1 = ctx["milestones"][0]
    res = api.create_draw(
        {"project_id": ctx["project"]["id"], "milestone_id": m1["id"],
         "conditional_waiver_amount_cents": 999_999},
        make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, "ERR_LIEN_WAIVER_REQUIRED")
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    listing = validate_success(api.list_milestones(ctx["project"]["id"], ho), 200)
    m1_after = next(m for m in listing if m["id"] == m1["id"])
    assert m1_after["status"] == "PENDING", m1_after


# ───────────────────────── Dispute UPHELD (queue B) ────────────────────────
def test_dispute_uphold_restores_approved_and_keeps_retainage(api):
    """PRD §3.9: "When the resolution is `UPHELD`, the contractor's position
    stands: the disputed draw's `status` is restored to `APPROVED` and its
    milestone's `status` is restored to `APPROVED`."
    PRD §3.9: "Resolving moves the dispute from `OPEN` to the terminal `RESOLVED`
    state, records the supplied outcome in `resolution`, and returns the project's
    `status` from `DISPUTED` back to `IN_PROGRESS`."

    UPHELD leaves the retainage held (no return), unlike OVERTURNED.

    Design: Corner/state_machines/dispute_uphold_restores_approved_branch
    """
    ctx, draw, dispute = setup_disputed_draw(contract_value_cents=600_000)
    m1 = ctx["milestones"][0]
    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"resolution": "UPHELD"},
        TEST_USERS["platform_admin_headers"]), 200)
    assert resolved["resolution"] == "UPHELD", resolved
    assert resolved["status"] == "RESOLVED", resolved

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    draw_after = validate_success(api.get_draw(draw["id"], ho), 200)
    listing = validate_success(api.list_milestones(ctx["project"]["id"], ho), 200)
    m1_after = next(m for m in listing if m["id"] == m1["id"])
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    assert draw_after["status"] == "APPROVED", draw_after
    assert m1_after["status"] == "APPROVED", m1_after
    assert escrow["retained_cents"] == 24_000, escrow
    assert project["status"] == "IN_PROGRESS", project


# ───────────────────────── Change orders (queue B) ─────────────────────────
def test_change_order_reject_sets_rejected(api):
    """PRD §3.7: "Rejecting a proposed change order moves it from `PROPOSED` to the
    terminal `REJECTED` state and requires only that the project be `IN_PROGRESS`."

    Design: Corner/endpoints/change_order_reject_sets_rejected
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000)
    co = propose_change_order(ctx, 50_000)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    rejected = validate_success(api.reject_change_order(co["id"], ho), 200)
    assert rejected["status"] == "REJECTED", rejected
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    assert project["contract_value_cents"] == 600_000, project


def test_change_order_approval_over_budget_rejected(api):
    """PRD §3.7: "the project's `contract_value_cents` plus the change order's
    `delta_cents` must not exceed the project's `budget_cap_cents` ... Either bound
    being violated is reported as `ERR_BUDGET_EXCEEDED`."

    contract_value 600000, budget_cap 620000; a +50000 change order would make
    650000 > 620000 and is rejected; contract_value and the change order are
    unchanged.

    Design: Corner/errors/change_order_budget_exceeded
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, budget_cap_cents=620_000)
    co = propose_change_order(ctx, 50_000)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    res = api.approve_change_order(
        co["id"], {"expected_bid_version": current_bid_version(ctx)}, ho)
    validate_error(res, "ERR_BUDGET_EXCEEDED")
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    co_after = validate_success(api.get_change_order(co["id"], ho), 200)
    assert project["contract_value_cents"] == 600_000, project
    assert co_after["status"] == "PROPOSED", co_after


def test_second_change_order_with_stale_bid_version_rejected(api):
    """PRD §2.9: "The approval request must carry `expected_bid_version`, and the
    value must equal the awarded bid's current `version`. Because each approved
    change order adjusts the contract value and advances the awarded bid's
    `version`, a second approval still carrying the older version is stale and is
    rejected with `ERR_STALE_BID_VERSION` (HTTP 412)."

    Two change orders; the first approval bumps Bid.version; the second approval
    still carries the pre-first version and is stale (only CO1 applied -> 610000).

    Design: Corner/cross_cutting_complexity_layers/occ_change_order_stale_bid_version_explicit
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000, budget_cap_cents=1_000_000)
    co1 = propose_change_order(ctx, 10_000)
    co2 = propose_change_order(ctx, 20_000)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    pre_version = current_bid_version(ctx)
    approve_change_order(ctx, co1, pre_version)  # bumps Bid.version

    res = api.approve_change_order(co2["id"], {"expected_bid_version": pre_version}, ho)
    validate_error(res, "ERR_STALE_BID_VERSION")
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    co2_after = validate_success(api.get_change_order(co2["id"], ho), 200)
    assert project["contract_value_cents"] == 610_000, project
    assert co2_after["status"] == "PROPOSED", co2_after
