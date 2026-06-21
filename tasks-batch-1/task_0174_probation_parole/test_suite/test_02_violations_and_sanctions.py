"""Violation adjudication, the sanction matrix, the sustain cascade, and the
appeal compensation invariant.

Difficulty queue: combinatorial_formula (sanction matrix),
non_linear_state_machine (violation fork-join), transitive_cascade (sustain),
compensating_invariant (appeal restores points).
Corner queue: state_machines (mark-missed side effect).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_officer_headers, make_judge_headers,
    create_officer, open_supervisee, add_draft_assessment, adopt_assessment,
    setup_active_supervisee, file_violation, sustain_violation, file_and_sustain,
)


def _active_proband(api, ordered_term_months=36):
    """ACTIVE PROBATION supervisee with a high adopted level. Returns
    (officer, supervisee_id, officer_headers)."""
    officer, sup = setup_active_supervisee(
        level_total=30, supervision_type="PROBATION",
        ordered_term_months=ordered_term_months,
    )
    return officer, sup["id"], make_officer_headers(officer["id"])


# ─── Difficulty: combinatorial_formula / sanction_matrix_class_x_tier ───
def test_sanction_matrix_felony_then_misdemeanor_jail_shock(api):
    """PRD §3.5: "in the third tier (9 through 11), the sanction_type is JAIL_SHOCK
    and the imposed_days is computed as the post-sustain cumulative total minus 9,
    multiplied by 2 (so a total of 9 yields 0 days, 10 yields 2 days, and 11
    yields 4 days)."
    PRD §3.5: "a FELONY 6 points, ... a MISDEMEANOR 4 points"

    FELONY (6) then MISDEMEANOR (4) reaches cumulative 10 -> JAIL_SHOCK, 2 days.

    Design: Difficulty/combinatorial_formula/sanction_matrix_class_x_tier_nonlinear_selection
    """
    officer, sup_id, oh = _active_proband(api)
    file_and_sustain(sup_id, officer["id"], "FELONY")  # cumulative 6
    v_mis = file_violation(sup_id, officer["id"], "MISDEMEANOR")

    validate_success(api.sustain_violation(sup_id, v_mis["id"], make_judge_headers()), 200)

    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 10

    sanctions, _ = _sanctions_for(api, sup_id, v_mis["id"], oh)
    assert len(sanctions) >= 1
    s = sanctions[-1]
    assert s["sanction_type"] == "JAIL_SHOCK"
    assert s["imposed_days"] == 2


def test_sanction_matrix_first_felony_curfew_imposition(api):
    """PRD §3.5: "in the second tier (5 through 8), the sanction_type is
    CURFEW_IMPOSITION when the violation class is MISDEMEANOR or FELONY"
    PRD §3.5: "a FELONY 6 points"

    A single FELONY (cumulative 6, tier 2) yields CURFEW_IMPOSITION, not the
    JAIL_SHOCK that the FELONY+MISDEMEANOR pair produces — the matrix is a
    non-linear function of class x tier.

    Design: Difficulty/combinatorial_formula/sanction_matrix_class_x_tier_nonlinear_selection
    """
    officer, sup_id, oh = _active_proband(api)
    v_fel = file_violation(sup_id, officer["id"], "FELONY")
    validate_success(api.sustain_violation(sup_id, v_fel["id"], make_judge_headers()), 200)

    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 6

    sanctions, _ = _sanctions_for(api, sup_id, v_fel["id"], oh)
    assert len(sanctions) >= 1
    s = sanctions[-1]
    assert s["sanction_type"] == "CURFEW_IMPOSITION"
    assert s["imposed_days"] == 0


def _sanctions_for(api, sup_id, v_id, headers):
    from test_helpers import validate_paginated
    return validate_paginated(
        api.list_sanctions_for_violation(sup_id, v_id, headers)
    )


# ─── Difficulty: non_linear_state_machine / violation_branching_fork_join ───
def test_violation_sustain_branch_assigns_points(api):
    """PRD §3.5: "First, the violation is assigned points according to its class: a
    TECHNICAL violation is worth 2 points"
    PRD §3.5: "the supervisee's cumulative_violation_points is recomputed as the
    exact sum of points across all of that supervisee's violations currently in
    SUSTAINED status"

    The SUSTAINED branch assigns points and bumps cumulative.

    Design: Difficulty/non_linear_state_machine/violation_branching_fork_join_sustain_vs_dismiss
    """
    officer, sup_id, oh = _active_proband(api, ordered_term_months=24)
    v = file_violation(sup_id, officer["id"], "TECHNICAL")
    sustained = validate_success(
        api.sustain_violation(sup_id, v["id"], make_judge_headers()), 200
    )
    assert sustained["status"] == "SUSTAINED"
    assert sustained["points"] == 2
    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 2


def test_violation_dismiss_branch_assigns_no_points(api):
    """PRD §3.5: "A SupervisingJudge dismisses a FILED violation, moving it to the
    terminal DISMISSED status; dismissal assigns no points and makes no change to
    the supervisee's cumulative total"

    The DISMISSED branch is divergent from SUSTAINED: no points, no cumulative
    change — a true fork.

    Design: Difficulty/non_linear_state_machine/violation_branching_fork_join_sustain_vs_dismiss
    """
    officer, sup_id, oh = _active_proband(api, ordered_term_months=24)
    v = file_violation(sup_id, officer["id"], "TECHNICAL")
    dismissed = validate_success(
        api.dismiss_violation(sup_id, v["id"], make_judge_headers()), 200
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["points"] == 0
    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 0


# ─── Difficulty: transitive_cascade / sustain_cascade_points_sanction_revocation ──
def test_sustain_cascade_to_revocation_pending(api):
    """PRD §3.5: "when the matrix selects a revocation referral and the supervisee
    was ACTIVE, the sanction's creation flips the supervisee's status from ACTIVE
    to REVOCATION_PENDING."
    PRD §3.5: "If the violation's class is ABSCOND, or the post-sustain total
    reaches the fourth tier (12 or more), the sanction_type is REVOCATION_REFERRAL
    with imposed_days of 0."

    Two FELONIES (6 + 6 = 12) -> tier 4 -> REVOCATION_REFERRAL sanction -> flips
    the supervisee to REVOCATION_PENDING. Depth-3 cascade.

    Design: Difficulty/transitive_cascade/sustain_cascade_points_sanction_revocation_pending
    """
    officer, sup_id, oh = _active_proband(api)
    file_and_sustain(sup_id, officer["id"], "FELONY")  # cumulative 6
    v2 = file_violation(sup_id, officer["id"], "FELONY")

    sustained = validate_success(
        api.sustain_violation(sup_id, v2["id"], make_judge_headers()), 200
    )
    assert sustained["status"] == "SUSTAINED"

    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 12
    assert sup_after["status"] == "REVOCATION_PENDING"

    sanctions, _ = _sanctions_for(api, sup_id, v2["id"], oh)
    assert any(s["sanction_type"] == "REVOCATION_REFERRAL" for s in sanctions)


def test_sustain_cascade_recomputes_cumulative_points(api):
    """PRD §3.5: "Second, the supervisee's cumulative_violation_points is
    recomputed as the exact sum of points across all of that supervisee's
    violations currently in SUSTAINED status"

    After two sustained FELONIES the cumulative is exactly 12 (6+6) — the ledger
    sync (depth-1) of the sustain cascade.

    Design: Difficulty/transitive_cascade/sustain_cascade_points_sanction_revocation_pending
    """
    officer, sup_id, oh = _active_proband(api)
    file_and_sustain(sup_id, officer["id"], "FELONY")
    v2 = file_violation(sup_id, officer["id"], "FELONY")
    validate_success(api.sustain_violation(sup_id, v2["id"], make_judge_headers()), 200)
    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 12


# ─── Difficulty: compensating_invariant / appeal_restores_cumulative_points ──
def test_appeal_restores_cumulative_points(api):
    """PRD §3.5: "it subtracts that violation's points from the supervisee's
    cumulative_violation_points (equivalently, the cumulative is recomputed over
    the remaining SUSTAINED violations and so falls by exactly those points)"

    Sustaining a FELONY adds 6; appealing it subtracts the same 6 -> cumulative 0.

    Design: Difficulty/compensating_invariant/appeal_restores_cumulative_violation_points
    """
    officer, sup_id, oh = _active_proband(api)
    v = file_violation(sup_id, officer["id"], "FELONY")
    validate_success(api.sustain_violation(sup_id, v["id"], make_judge_headers()), 200)
    mid = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert mid["cumulative_violation_points"] == 6

    appealed = validate_success(
        api.appeal_violation(sup_id, v["id"], oh), 200
    )
    assert appealed["status"] == "APPEALED"
    sup_after = validate_success(api.get_supervisee(sup_id, oh), 200)
    assert sup_after["cumulative_violation_points"] == 0


def test_appeal_vacates_attached_sanction(api):
    """PRD §3.5: "any Sanction tied to the appealed violation transitions to
    VACATED."

    Appealing a sustained FELONY vacates the sanction the matrix created.

    Design: Difficulty/compensating_invariant/appeal_restores_cumulative_violation_points
    """
    officer, sup_id, oh = _active_proband(api)
    v = file_violation(sup_id, officer["id"], "FELONY")
    validate_success(api.sustain_violation(sup_id, v["id"], make_judge_headers()), 200)
    sanctions, _ = _sanctions_for(api, sup_id, v["id"], oh)
    assert len(sanctions) >= 1

    validate_success(api.appeal_violation(sup_id, v["id"], oh), 200)
    sanctions_after, _ = _sanctions_for(api, sup_id, v["id"], oh)
    assert all(s["status"] == "VACATED" for s in sanctions_after)


# ─── Corner: state_machines / mark_missed_side_effect_files_technical_violation ──
def test_mark_missed_auto_files_technical_violation(api):
    """PRD §3.4: "Marking a check-in missed moves it to MISSED and, as a
    cross-entity side effect, auto-creates a Violation of class TECHNICAL filed by
    the acting officer ... in FILED status"

    Design: Corner/state_machines/mark_missed_side_effect_files_technical_violation
    """
    from test_helpers import set_clock, add_check_in, validate_paginated
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-05-06T08:30:00.000Z", officer["id"])
    ci = add_check_in(sup["id"], officer["id"], "2026-05-06T09:00:00.000Z",
                      window_minutes=60)
    set_clock("2026-05-06T10:30:00.000Z", officer["id"])
    missed = validate_success(api.mark_missed_check_in(sup["id"], ci["id"], oh), 200)
    assert missed["status"] == "MISSED"

    vios, _ = validate_paginated(
        api.list_violations(sup["id"], oh, params={"status": "FILED"})
    )
    assert any(v["violation_class"] == "TECHNICAL" for v in vios)
