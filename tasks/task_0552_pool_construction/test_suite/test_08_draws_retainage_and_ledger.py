"""Progress draws: OCC on create, dual-variant eligibility, retainage rounding,
funding preconditions, the money boundary, and validation precedence at FUND."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_draw_request_payload,
    setup_permitted_project_with_gate, setup_permitted_project_with_started_gate,
    setup_provisional_final_divergence, setup_gate_inspection_pending,
    setup_retainage_two_draws, setup_approved_draw_gate_in_progress,
    setup_approved_draw_at_boundary, setup_passed_gate_draw_requested,
)


# ─── Optimistic concurrency on draw create (PRD §2.5) ─────────────────────
def test_second_draw_with_stale_version_rejected(api, builder_headers):
    """PRD §2.5: "Before the draw is created, the server compares expected_pool_project_version to
    the project's current version."
    PRD §2.5: "the request is rejected with ERR_STALE_PROJECT_VERSION (HTTP 412), and the client
    must re-read the project before retrying so that it is not billing against a stale view of the
    fundable ceiling."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_draw_create
    """
    project, gate = setup_permitted_project_with_gate()
    pv1 = validate_success(api.get_pool_project(project["id"], builder_headers), 200)["version"]
    draw1 = validate_success(api.create_draw_request(
        create_draw_request_payload(project["id"], gate["id"], 40000, pv1), builder_headers), 201)
    assert draw1["status"] == "REQUESTED"
    # The first create already bumped the project version, so pv1 is now stale.
    res2 = api.create_draw_request(
        create_draw_request_payload(project["id"], gate["id"], 40000, pv1), builder_headers)
    validate_error(res2, ApiErrorId.ERR_STALE_PROJECT_VERSION)


def test_correct_version_creates_draw_and_bumps_project(api, builder_headers):
    """PRD §3.7: "On creation the draw's status is REQUESTED, its forward-looking
    provisional_eligible_cents is snapshotted (see below), and the project's version is
    incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_bumps_project_version
    """
    project, gate = setup_permitted_project_with_started_gate()  # gate IN_PROGRESS
    pv1 = validate_success(api.get_pool_project(project["id"], builder_headers), 200)["version"]
    draw = validate_success(api.create_draw_request(
        create_draw_request_payload(project["id"], gate["id"], 100000, pv1), builder_headers), 201)
    assert draw["status"] == "REQUESTED"
    assert draw["provisional_eligible_cents"] == 50000  # 0.5 * 100000, capped at requested
    pv2 = validate_success(api.get_pool_project(project["id"], builder_headers), 200)["version"]
    assert pv2 == pv1 + 1


# ─── Dual-variant eligibility: provisional vs final (PRD §3.7) ────────────
def test_provisional_snapshot_uses_in_progress_factor(api, builder_headers):
    """PRD §3.7: "At draw creation this is snapshotted forward-looking into
    provisional_eligible_cents, so a gate that is only IN_PROGRESS or INSPECTION_PENDING still
    yields a positive provisional amount (half or four-fifths of its budget)."

    Design: Difficulty/dual_variant_calc/draw_provisional_vs_final_divergence
    """
    project, gate, draw = setup_provisional_final_divergence()  # draw created at IN_PROGRESS
    assert draw["provisional_eligible_cents"] == 50000  # 0.5 * 100000


def test_final_eligible_at_fund_diverges_from_provisional(api, builder_headers):
    """PRD §3.7: "At funding the eligibility is recomputed in its final form: because the gate must
    be PASSED, its completion factor is 1.0 and the final eligible_cents therefore equals the gate's
    budget_cents (still capped at requested_cents and floored at zero) — which differs from
    provisional_eligible_cents whenever the draw had been created before the gate passed."
    PRD §3.7: "The draw's retainage_cents is 10% of its eligible_cents, rounded half-up to whole
    cents on that single draw line, and its net_disbursed_cents is eligible_cents minus
    retainage_cents".

    Design: Difficulty/dual_variant_calc/draw_provisional_vs_final_divergence
    """
    project, gate, draw = setup_provisional_final_divergence()  # gate now PASSED, draw APPROVED
    funded = validate_success(api.transition_draw_request(draw["id"], {"action": "FUND"},
                                                         builder_headers), 200)
    assert funded["eligible_cents"] == 100000       # factor 1.0 at FUND
    assert funded["net_disbursed_cents"] == 90000   # 100000 - 10% retainage
    assert funded["provisional_eligible_cents"] != funded["eligible_cents"]


# ─── Combinatorial eligibility: nested min against requested (PRD §3.7) ───
def test_provisional_min_binds_on_requested(api, builder_headers):
    """PRD §3.7: "The eligible amount is then the phase-earned amount but never below zero and
    never above requested_cents — that is, it is the smaller of phase-earned and requested_cents,
    floored at zero."

    Design: Difficulty/combinatorial_formula/draw_fundable_nested_min_mode_a
    """
    project, gate, inspection = setup_gate_inspection_pending()  # gate INSPECTION_PENDING, budget 100000
    pv1 = validate_success(api.get_pool_project(project["id"], builder_headers), 200)["version"]
    # phase_earned = round(100000 * 0.8) = 80000; requested 60000 -> min binds on requested.
    draw = validate_success(api.create_draw_request(
        create_draw_request_payload(project["id"], gate["id"], 60000, pv1), builder_headers), 201)
    assert draw["provisional_eligible_cents"] == 60000


def test_provisional_min_binds_on_phase_earned(api, builder_headers):
    """PRD §3.7: "Eligibility is computed from the referenced gate's budget and a completion factor
    keyed on the gate's status: a PENDING gate earns a factor of 0.0, an IN_PROGRESS gate 0.5, an
    INSPECTION_PENDING gate 0.8, a PASSED gate 1.0, and a FAILED gate 0.0."

    Design: Difficulty/combinatorial_formula/draw_fundable_nested_min_mode_a
    """
    project, gate, inspection = setup_gate_inspection_pending()
    pv1 = validate_success(api.get_pool_project(project["id"], builder_headers), 200)["version"]
    # phase_earned = round(100000 * 0.8) = 80000; requested 100000 -> min binds on phase_earned.
    draw = validate_success(api.create_draw_request(
        create_draw_request_payload(project["id"], gate["id"], 100000, pv1), builder_headers), 201)
    assert draw["provisional_eligible_cents"] == 80000


# ─── Retainage per-line rounding (PRD §3.7) ───────────────────────────────
def test_retainage_rounded_per_draw_line(api, builder_headers):
    """PRD §3.7: "The draw's retainage_cents is 10% of its eligible_cents, rounded half-up to whole
    cents on that single draw line, and its net_disbursed_cents is eligible_cents minus
    retainage_cents".

    Design: Difficulty/combinatorial_formula/retainage_per_line_rounding_mode_b
    """
    project, draw1, draw2 = setup_retainage_two_draws()  # both eligible 12345
    validate_success(api.transition_draw_request(draw2["id"], {"action": "FUND"}, builder_headers), 200)
    dr1 = validate_success(api.get_draw_request(draw1["id"], builder_headers), 200)
    dr2 = validate_success(api.get_draw_request(draw2["id"], builder_headers), 200)
    # round_half_up(12345 * 0.10) = round_half_up(1234.5) = 1235, per line.
    assert dr1["retainage_cents"] == 1235
    assert dr2["retainage_cents"] == 1235


def test_retainage_held_sums_individually_rounded_lines(api, builder_headers):
    """PRD §3.7: "retainage_held_cents is the sum of the individually-rounded retainage_cents over
    all funded draws whose retainage_released is still false — and the per-line rounding matters:
    each draw's retainage is rounded to whole cents first and only then summed, never summed and
    rounded once, because the two orders can differ by a cent when several draws round the same way."

    Design: Difficulty/combinatorial_formula/retainage_per_line_rounding_mode_b
    """
    project, draw1, draw2 = setup_retainage_two_draws()
    validate_success(api.transition_draw_request(draw2["id"], {"action": "FUND"}, builder_headers), 200)
    # 1235 + 1235 = 2470 (per-line), not round(24690 * 0.10) = 2469.
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["retainage_held_cents"] == 2470


# ─── Cross-entity dependency: FUND requires the gate PASSED (PRD §3.7) ────
def test_fund_requires_gate_passed(api, builder_headers):
    """PRD §3.7: "Funding runs three checks in order: the draw must be in APPROVED status, else
    ERR_INVALID_STATE; the referenced gate must be PASSED, else ERR_PHASE_NOT_PASSED; and the
    resulting net disbursement must not exceed the project's amount_remaining_cents, else
    ERR_DRAW_EXCEEDS_CONTRACT, which is checked last."

    Design: Difficulty/cross_entity_state_dependency/draw_fund_requires_phase_passed
    """
    project, gate, draw = setup_approved_draw_gate_in_progress()  # gate IN_PROGRESS, draw APPROVED
    res = api.transition_draw_request(draw["id"], {"action": "FUND"}, builder_headers)
    validate_error(res, ApiErrorId.ERR_PHASE_NOT_PASSED)


def test_fund_succeeds_when_gate_passed(api, builder_headers):
    """PRD §3.7: "the referenced gate must be PASSED, else ERR_PHASE_NOT_PASSED".

    Design: Difficulty/cross_entity_state_dependency/draw_fund_requires_phase_passed
    """
    project, gate, draw = setup_approved_draw_at_boundary(contract_price_cents=500000)  # gate PASSED
    funded = validate_success(api.transition_draw_request(draw["id"], {"action": "FUND"},
                                                         builder_headers), 200)
    assert funded["status"] == "FUNDED"


# ─── Fiscal contract-ceiling boundary at FUND (PRD §3.7) ──────────────────
def test_fund_net_exceeds_remaining_rejected(api, builder_headers):
    """PRD §3.7: "the resulting net disbursement must not exceed the project's
    amount_remaining_cents, else ERR_DRAW_EXCEEDS_CONTRACT, which is checked last."

    Design: Corner/validations/draw_fund_exceeds_contract_reject_strict
    """
    project, gate, draw = setup_approved_draw_at_boundary(contract_price_cents=89999)
    # net 90000 > remaining 89999 -> strict rejection.
    res = api.transition_draw_request(draw["id"], {"action": "FUND"}, builder_headers)
    validate_error(res, ApiErrorId.ERR_DRAW_EXCEEDS_CONTRACT)


def test_fund_net_equals_remaining_inclusive_succeeds(api, builder_headers):
    """PRD §3.7: "the resulting net disbursement must not exceed the project's
    amount_remaining_cents, else ERR_DRAW_EXCEEDS_CONTRACT, which is checked last."

    Design: Difficulty/boundary_precision_check/draw_net_equals_remaining_inclusive_boundary
    """
    project, gate, draw = setup_approved_draw_at_boundary(contract_price_cents=90000)
    # net 90000 == remaining 90000 -> "must not exceed" is inclusive, so funding is allowed.
    funded = validate_success(api.transition_draw_request(draw["id"], {"action": "FUND"},
                                                         builder_headers), 200)
    assert funded["status"] == "FUNDED"
    assert funded["net_disbursed_cents"] == 90000


def test_fund_boundary_final_amounts(api, builder_headers):
    """PRD §3.7: "the final eligible_cents therefore equals the gate's budget_cents (still capped at
    requested_cents and floored at zero)".
    PRD §3.7: "The draw's retainage_cents is 10% of its eligible_cents, rounded half-up to whole
    cents on that single draw line, and its net_disbursed_cents is eligible_cents minus
    retainage_cents".

    Design: Difficulty/boundary_precision_check/draw_net_equals_remaining_inclusive_boundary
    """
    project, gate, draw = setup_approved_draw_at_boundary(contract_price_cents=90000)
    funded = validate_success(api.transition_draw_request(draw["id"], {"action": "FUND"},
                                                         builder_headers), 200)
    assert funded["eligible_cents"] == 100000
    assert funded["retainage_cents"] == 10000
    assert funded["net_disbursed_cents"] == 90000


# ─── Validation precedence: state check outranks fiscal (PRD §2.6, §3.7) ──
def test_fund_state_check_outranks_fiscal(api, builder_headers):
    """PRD §3.7: "Funding runs three checks in order: the draw must be in APPROVED status, else
    ERR_INVALID_STATE; the referenced gate must be PASSED, else ERR_PHASE_NOT_PASSED; and the
    resulting net disbursement must not exceed the project's amount_remaining_cents, else
    ERR_DRAW_EXCEEDS_CONTRACT, which is checked last."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_beats_fiscal
    """
    # Draw left REQUESTED (violates state) AND net 90000 > remaining 50000 (violates fiscal).
    project, gate, draw = setup_passed_gate_draw_requested(contract_price_cents=50000)
    res = api.transition_draw_request(draw["id"], {"action": "FUND"}, builder_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_fund_state_error_leaves_draw_unchanged(api, builder_headers):
    """PRD §2.6: "for a transition endpoint, the target resource is in a state from which the
    requested transition is legal, else ERR_INVALID_STATE (409)."
    PRD §2.6: "the draw-funding contract ceiling and the project-close punch-list rule, yielding
    ERR_DRAW_EXCEEDS_CONTRACT or ERR_OPEN_PUNCH_ITEMS (both 409), checked last of all."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_beats_fiscal
    """
    project, gate, draw = setup_passed_gate_draw_requested(contract_price_cents=50000)
    res = api.transition_draw_request(draw["id"], {"action": "FUND"}, builder_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_draw_request(draw["id"], builder_headers), 200)
    assert after["status"] == "REQUESTED"
