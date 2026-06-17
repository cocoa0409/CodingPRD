"""Wage-step determination (hours vs competency variant), the at-or-below
threshold boundary, the OJT-approve cascade chain, and completion eligibility.

Covers the dual_variant_calc (wage), boundary_precision_check (wage threshold),
transitive_cascade (depth-3), compensating_invariant (OJT hours), and the
completion-eligibility corner.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    assert_agreement,
    WAGE_LADDER_4,
    create_sponsor,
    create_qualified_journeyworker,
    create_apprentice,
    create_active_program,
    create_active_agreement,
    setup_active_agreement,
    log_ojt_entry,
    log_and_approve_ojt,
    record_rti,
    submit_attainment,
    submit_and_approve_attainment,
    AGENCY,
    COORD,
)
from test_helpers.test_users import make_sponsor_headers


# ===========================================================================
# Difficulty: dual_variant_calc / wage_step_hours_vs_competency_variant_diverges
# ===========================================================================
def test_hours_based_wage_step_reflects_approved_ojt_hours(api):
    """PRD §3.7: "For an `HOURS_BASED` program - and likewise for a `HYBRID`
    program - the current wage step is the highest `step_number` among all steps
    whose `ojt_hours_threshold` is less than or equal to the agreement's
    `ojt_hours_completed`; because the comparison is at-or-below, exactly meeting
    a threshold reaches that step, and if no step qualifies the step is 1."
    PRD §3.7: "Whenever `current_wage_step` changes, `current_hourly_wage_cents`
    is recomputed by multiplying `base_journeyworker_wage_cents` by the selected
    step's `wage_pct` and rounding half-up to the nearest whole cent, per §2.7."

    Under HOURS_BASED with 8 approved OJT hours, step 2 (threshold 8) is reached:
    wage = round(4000 * 0.65) = 2600c.

    Design: Difficulty/dual_variant_calc/wage_step_hours_vs_competency_variant_diverges
    """
    sc = setup_active_agreement(
        completion_type="HOURS_BASED", wage_ladder=WAGE_LADDER_4,
        milestones=[{}],
    )
    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    submit_and_approve_attainment(
        sc.sponsor_id, sc.agreement_id,
        _first_milestone_id(api, sc.program_id, sc.sponsor_id),
    )
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["current_wage_step"] == 2, f"hours-based step expected 2, got {agr['current_wage_step']}"
    assert agr["current_hourly_wage_cents"] == 2600, f"expected 2600c, got {agr['current_hourly_wage_cents']}"


def test_competency_based_wage_step_reflects_approved_milestones(api):
    """PRD §3.7: "For a `COMPETENCY_BASED` program, the current wage step is the
    agreement's `milestones_attained_count` clamped into the range from 1 up to
    the highest `step_number` defined for the program - each approved milestone
    advances one step, with a floor of 1 and a ceiling at the top step."

    Identical data (8 approved OJT hours + 1 approved milestone) under
    COMPETENCY_BASED yields step = clamp(1, 1, 4) = 1, wage round(4000*0.50)=2000c
    -- diverging from the HOURS_BASED step-2/2600c result on the same inputs.

    Design: Difficulty/dual_variant_calc/wage_step_hours_vs_competency_variant_diverges
    """
    sc = setup_active_agreement(
        completion_type="COMPETENCY_BASED", wage_ladder=WAGE_LADDER_4,
        milestones=[{}],
    )
    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    submit_and_approve_attainment(
        sc.sponsor_id, sc.agreement_id,
        _first_milestone_id(api, sc.program_id, sc.sponsor_id),
    )
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["current_wage_step"] == 1, f"competency step expected 1, got {agr['current_wage_step']}"
    assert agr["current_hourly_wage_cents"] == 2000, f"expected 2000c, got {agr['current_hourly_wage_cents']}"


# ===========================================================================
# Difficulty: boundary_precision_check / wage_step_threshold_exact_boundary_inclusive
# ===========================================================================
def test_wage_step_below_threshold_stays_at_step_one(api):
    """PRD §3.7: "the current wage step is the highest `step_number` among all
    steps whose `ojt_hours_threshold` is less than or equal to the agreement's
    `ojt_hours_completed`; because the comparison is at-or-below, exactly meeting
    a threshold reaches that step, and if no step qualifies the step is 1."

    With 7 approved hours and a step-2 threshold of 8, no higher step qualifies:
    current_wage_step == 1.

    Design: Difficulty/boundary_precision_check/wage_step_threshold_exact_boundary_inclusive
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50), (2, 8, 0.65)])
    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 480, 900, 7)
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["ojt_hours_completed"] == 7
    assert agr["current_wage_step"] == 1, f"7h should stay at step 1, got {agr['current_wage_step']}"


def test_wage_step_at_exact_threshold_reaches_next_step(api):
    """PRD §3.7: "because the comparison is at-or-below, exactly meeting a
    threshold reaches that step, and if no step qualifies the step is 1."

    Exactly 8 approved hours reaches the step-2 threshold of 8: current_wage_step
    == 2, wage round(4000*0.65)=2600c.

    Design: Difficulty/boundary_precision_check/wage_step_threshold_exact_boundary_inclusive
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50), (2, 8, 0.65)])
    # 7 hours on day 1, +1 hour on day 2 (non-overlapping) -> cumulative 8.
    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 480, 900, 7, work_date="2026-02-01")
    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 480, 540, 1, work_date="2026-02-02")
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["ojt_hours_completed"] == 8
    assert agr["current_wage_step"] == 2, f"8h should reach step 2, got {agr['current_wage_step']}"
    assert agr["current_hourly_wage_cents"] == 2600


# ===========================================================================
# Difficulty: transitive_cascade / ojt_approve_cascade_hours_step_wage_eligibility_depth3
# ===========================================================================
def test_ojt_approve_cascades_hours_then_step_then_wage(api):
    """PRD §3.4: "On approval the entry's `credited_hours` are added to the
    agreement's `ojt_hours_completed`, and the cascade chain runs in order: the
    wage step is recomputed, the hourly wage snapshot is recomputed from the new
    step, and completion eligibility is recomputed."
    PRD §3.7: "Whenever `current_wage_step` changes, `current_hourly_wage_cents`
    is recomputed by multiplying `base_journeyworker_wage_cents` by the selected
    step's `wage_pct` and rounding half-up to the nearest whole cent, per §2.7."

    A single approve of an 8-hour entry drives ojt_hours_completed 0->8, then
    current_wage_step 1->2, then current_hourly_wage_cents 2000->2600.

    Design: Difficulty/transitive_cascade/ojt_approve_cascade_hours_step_wage_eligibility_depth3
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=WAGE_LADDER_4)
    before = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert before["current_wage_step"] == 1
    assert before["current_hourly_wage_cents"] == 2000

    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["ojt_hours_completed"] == 8
    assert agr["current_wage_step"] == 2
    assert agr["current_hourly_wage_cents"] == 2600


def test_ojt_approve_recomputes_completion_eligibility(api):
    """PRD §3.4: "the cascade chain runs in order: the wage step is recomputed,
    the hourly wage snapshot is recomputed from the new step, and completion
    eligibility is recomputed."
    PRD §3.7: "For an `HOURS_BASED` program, eligibility is the hours condition
    and the instruction condition both holding; milestones are ignored."

    With RTI already satisfied, approving enough OJT hours flips
    completion_eligible from false to true via the cascade's final hop.

    Design: Difficulty/transitive_cascade/ojt_approve_cascade_hours_step_wage_eligibility_depth3
    """
    sc = setup_active_agreement(
        completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50)],
        ojt_hours_required=16, rti_hours_required=8,
    )
    record_rti(sc.sponsor_id, sc.agreement_id, 8)
    mid = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert mid["completion_eligible"] is False, "RTI alone must not make it eligible"

    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 0, 600, 16)
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["ojt_hours_completed"] == 16
    assert agr["completion_eligible"] is True


# ===========================================================================
# Difficulty: compensating_invariant / ojt_hours_conserved_approve_then_reopen
# ===========================================================================
def test_ojt_hours_conserved_after_approve_then_reopen(api):
    """PRD §3.4: "Reopening is the compensating action for approval: it subtracts
    the entry's `credited_hours` back out of the agreement's `ojt_hours_completed`,
    restoring the prior total, and then re-runs the identical downstream cascade
    - wage step, then wage snapshot, then completion eligibility - so the
    agreement's derived state never drifts."

    Approve (+8 -> step 2) then reopen (-8 -> step 1) returns the conserved hour
    total to 0 and the wage step to 1.

    Design: Difficulty/compensating_invariant/ojt_hours_conserved_approve_then_reopen
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50), (2, 8, 0.65)])
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    validate_success(api.approve_ojt_entry(entry["id"], COORD))
    after_approve = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert after_approve["ojt_hours_completed"] == 8
    assert after_approve["current_wage_step"] == 2

    validate_success(api.reopen_ojt_entry(entry["id"], COORD))
    after_reopen = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert after_reopen["ojt_hours_completed"] == 0, "reopen must restore the prior hour total"
    assert after_reopen["current_wage_step"] == 1, "reopen must restore the prior wage step"


def test_ojt_approve_reopen_restores_wage_snapshot(api):
    """PRD §3.4: "Reopening is the compensating action for approval: it subtracts
    the entry's `credited_hours` back out of the agreement's `ojt_hours_completed`,
    restoring the prior total, and then re-runs the identical downstream cascade -
    wage step, then wage snapshot, then completion eligibility - so the agreement's
    derived state never drifts."
    PRD §3.7: "Whenever `current_wage_step` changes, `current_hourly_wage_cents`
    is recomputed by multiplying `base_journeyworker_wage_cents` by the selected
    step's `wage_pct` and rounding half-up to the nearest whole cent, per §2.7."

    The conserved hour total also restores the wage snapshot: approve drives the
    wage to 2600c (step 2); reopen restores it to 2000c (step 1).

    Design: Difficulty/compensating_invariant/ojt_hours_conserved_approve_then_reopen
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50), (2, 8, 0.65)])
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    validate_success(api.approve_ojt_entry(entry["id"], COORD))
    after_approve = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert after_approve["current_hourly_wage_cents"] == 2600

    validate_success(api.reopen_ojt_entry(entry["id"], COORD))
    after_reopen = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert after_reopen["current_hourly_wage_cents"] == 2000, "reopen must restore the prior wage snapshot"


def test_reopened_entry_returns_to_pending(api):
    """PRD §3.4: "A coordinator may reopen an approved entry for correction,
    moving it `APPROVED -> PENDING` (the entry must be `APPROVED`, otherwise
    `ERR_OJT_ENTRY_NOT_APPROVED`)."

    After approve then reopen, the OJT entry itself is back in PENDING (a cycle,
    not a terminal pipeline).

    Design: Difficulty/non_linear_state_machine/ojt_entry_approve_reopen_cycle
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50), (2, 8, 0.65)])
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    approved = validate_success(api.approve_ojt_entry(entry["id"], COORD))
    assert approved["status"] == "APPROVED"
    reopened = validate_success(api.reopen_ojt_entry(entry["id"], COORD))
    assert reopened["status"] == "PENDING", f"reopen must return entry to PENDING, got {reopened['status']}"


def test_ojt_approve_reopen_clears_credited_hours(api):
    """PRD §3.4: "Reopening is the compensating action for approval: it subtracts
    the entry's `credited_hours` back out of the agreement's `ojt_hours_completed`,
    restoring the prior total."

    The agreement hour total returns to 0 after the approve/reopen cycle.

    Design: Difficulty/non_linear_state_machine/ojt_entry_approve_reopen_cycle
    """
    sc = setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=[(1, 0, 0.50), (2, 8, 0.65)])
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 960, 8)
    validate_success(api.approve_ojt_entry(entry["id"], COORD))
    validate_success(api.reopen_ojt_entry(entry["id"], COORD))
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["ojt_hours_completed"] == 0


# ===========================================================================
# Corner: calculations / completion_eligibility_hybrid_requires_all_three
# ===========================================================================
def test_hybrid_eligibility_false_until_milestone_approved(api):
    """PRD §3.7: "For a `HYBRID` program, all three must hold: hours, instruction,
    and competency together."
    PRD §3.7: "The competency condition holds when the count of `APPROVED`
    milestone attainments covering the program's milestones marked
    `required_for_completion` equals the total number of milestones that carry
    `required_for_completion` set to true - that is, every mandatory competency
    has an approved attainment."

    With hours and RTI met but the required milestone not yet approved,
    completion_eligible stays false under HYBRID.

    Design: Corner/calculations/completion_eligibility_hybrid_requires_all_three
    """
    sc = setup_active_agreement(
        completion_type="HYBRID", wage_ladder=[(1, 0, 0.50)],
        milestones=[{"required_for_completion": True}],
        ojt_hours_required=16, rti_hours_required=8,
    )
    log_and_approve_ojt(sc.sponsor_id, sc.agreement_id, 0, 600, 16)
    record_rti(sc.sponsor_id, sc.agreement_id, 8)
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["completion_eligible"] is False, "HYBRID requires the milestone too"


# ===========================================================================
# Helpers
# ===========================================================================
def _first_milestone_id(api, program_id, sponsor_id):
    milestones = get_success_data(
        api.list_milestones(make_sponsor_headers(sponsor_id), params={"program_id": program_id})
    )
    return milestones[0]["id"]
