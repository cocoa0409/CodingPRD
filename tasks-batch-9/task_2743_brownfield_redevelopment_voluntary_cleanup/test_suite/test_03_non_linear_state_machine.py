"""
State machines that are not a single line from start to finish.

The assessment phase runs a bounded revision cycle that terminates in rejection rather
than looping forever, the liability protection carries two dimensions that advance
independently of one another, and the remedial action plan forks into two review
branches that must both land before the join can be taken.
"""

from test_helpers import (
    add_assessment_phase,
    add_finding,
    add_plan,
    approve_plan,
    assert_fields,
    assert_number,
    assert_pins_match,
    assert_sweep_counters,
    assert_weight_conservation,
    close_comment,
    impose_obligation,
    review_phase,
    run_sweep,
    stage_enrolled,
    stage_inquiry,
    stage_phase_i,
    stage_plan,
    stage_protection,
    stage_registry,
    stage_site,
    submit_phase,
    submit_plan,
    technical_review,
)

REVISION_COMMENTS = (
    "Historical use narrative incomplete.",
    "Interview records still missing.",
    "Third pass still deficient; record rejected.",
)


def _phase_awaiting_review(api):
    """A parcel with an open protection and one PHASE_I phase carrying a finding."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    phase = add_assessment_phase(world)
    add_finding(world, phase)
    return world, phase


# ─── assessment_phase_revision_cycle_terminates_in_rejection ───────────────────


def test_the_third_revision_decision_rejects_instead_of_returning_for_rework(api):
    """
    The cycle is bounded: the third decision terminalises the phase.

    "When a revision decision arrives on a phase whose `review_round` has reached 3, the
    phase is not returned for rework: it moves `UNDER_REVIEW → REJECTED` instead,
    recording `reviewed_by_user_id` and incrementing `version`."

    Design: Difficulty/non_linear_state_machine/assessment_phase_revision_cycle_terminates_in_rejection
    """
    world, phase = _phase_awaiting_review(api)

    decided = None
    for comment in REVISION_COMMENTS:
        submit_phase(world, phase)
        decided = review_phase(
            world, phase, "REQUEST_REVISION", review_comment=comment
        )

    # The rejection clause names only ``reviewed_by_user_id`` among the fields it
    # records, so the comment is not asserted on this landing.
    assert_fields(
        decided,
        status="REJECTED",
        review_round=3,
        reviewed_by_user_id="reviewer-alpha",
    )


def test_the_first_two_rounds_return_the_phase_for_rework(api):
    """
    While the counter is low the phase cycles back to the consultant.

    "A revision may be requested while `review_round` is 2 or less, and the phase then
    moves `UNDER_REVIEW → REVISION_REQUESTED`, recording both `reviewed_by_user_id` and
    the `review_comment` and incrementing the phase's `version` by 1."

    Design: Difficulty/non_linear_state_machine/assessment_phase_revision_cycle_terminates_in_rejection
    """
    world, phase = _phase_awaiting_review(api)

    for expected_round in (1, 2):
        submitted = submit_phase(world, phase)
        assert_fields(submitted, status="UNDER_REVIEW", review_round=expected_round)
        returned = review_phase(
            world,
            phase,
            "REQUEST_REVISION",
            review_comment=REVISION_COMMENTS[expected_round - 1],
        )
        assert_fields(
            returned,
            status="REVISION_REQUESTED",
            review_round=expected_round,
            reviewed_by_user_id="reviewer-alpha",
            review_comment=REVISION_COMMENTS[expected_round - 1],
        )


def test_the_rejection_reaches_the_protection_and_leaves_the_parcel_unscreened(api):
    """
    A rejected inquiry marks the defence file deficient and screens nothing.

    "When such a decision lands and the site has a liability protection record, that
    protection's `inquiry_state` becomes `AAI_DEFICIENT`, its `bfpp_status` is
    recomputed, and its `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/assessment_phase_revision_cycle_terminates_in_rejection
    """
    world, phase = _phase_awaiting_review(api)

    for comment in REVISION_COMMENTS:
        submit_phase(world, phase)
        review_phase(world, phase, "REQUEST_REVISION", review_comment=comment)

    protection = world.read_protection()
    assert_fields(
        protection,
        inquiry_state="AAI_DEFICIENT",
        bfpp_status="NOT_ESTABLISHED",
        obligation_state="OBLIGATIONS_NONE",
    )
    assert_fields(world.read_site(), delineation_status="NONE", cleanup_posture="OPEN")


# ─── liability_protection_parallel_dimensions_advance_independently ─────────────

DUTIES = (
    ("REASONABLE_STEPS", "Maintain fencing, signage and stormwater controls."),
    ("LAND_USE_RESTRICTION_COMPLIANCE", "Honour the commercial-only land use restriction."),
    ("INSTITUTIONAL_CONTROL_MAINTENANCE", "Inspect and maintain the depressurisation system."),
    ("ACCESS_AND_COOPERATION", "Provide agency access on 24 hours notice."),
    ("NOTIFICATION", "Report any newly discovered contamination within 30 days."),
)


def _protection_with_five_duties(api, due_date="2028-06-30"):
    """
    A parcel still under contract, with a complete inquiry and one duty per category.

    Title is deliberately never taken, so the inquiry can age past its expiry and the
    sweep's staleness rule stays reachable.
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(world)
    stage_inquiry(world)
    for category, description in DUTIES:
        world.obligations[category] = impose_obligation(
            world,
            obligation_category=category,
            description=description,
            due_date=due_date,
            recurrence_days=90,
        )
    return world


def test_both_dimensions_read_independently_once_the_file_is_populated(api):
    """
    A complete inquiry and five current duties are recorded side by side.

    "The BFPP defence is the reason a redeveloper touches a contaminated parcel at all,
    and the system models it as a single record per parcel carrying **two independent
    state dimensions** plus a derived verdict."

    Design: Difficulty/non_linear_state_machine/liability_protection_parallel_dimensions_advance_independently
    """
    world = _protection_with_five_duties(api)

    protection = world.read_protection()
    assert_fields(
        protection,
        inquiry_state="AAI_COMPLETE",
        obligation_state="CURRENT",
        bfpp_status="NOT_ESTABLISHED",
        obligations_total_weight=20,
        current_weight=20,
        satisfied_weight=0,
        at_risk_weight=0,
        lapsed_weight=0,
    )
    assert_number(protection["compliance_pct"], "1.0000", "compliance_pct")
    assert_weight_conservation(protection)


def test_the_sweep_stales_the_inquiry_without_touching_the_duties(api):
    """
    An expired inquiry on an unclosed deal moves alone.

    "A protection whose `inquiry_state` is `AAI_COMPLETE` moves to `AAI_STALE` when the
    sweep's `as_of_date` is strictly later than `aai_expires_on` **and** the parcel is still
    `UNDER_CONTRACT` — an inquiry that has aged past a year while the deal has not closed no
    longer supports the defence."

    Design: Difficulty/non_linear_state_machine/liability_protection_parallel_dimensions_advance_independently
    """
    world = _protection_with_five_duties(api)
    assert_fields(world.read_protection(), aai_expires_on="2027-07-20")

    result = run_sweep(world, "2027-07-21")
    assert_sweep_counters(
        result,
        stale_inquiry_count=1,
        at_risk_count=0,
        lapsed_count=0,
        forfeited_protection_count=0,
        frozen_site_count=0,
    )

    protection = world.read_protection()
    assert_fields(
        protection,
        inquiry_state="AAI_STALE",
        obligation_state="CURRENT",
        bfpp_status="NOT_ESTABLISHED",
        current_weight=20,
        at_risk_weight=0,
    )
    assert_number(protection["compliance_pct"], "1.0000", "compliance_pct")


def test_the_sweep_moves_the_duties_without_touching_the_stale_inquiry(api):
    """
    A later run advances the obligation dimension only; the inquiry has already moved.

    "A duty in `CURRENT` whose `due_date` is between 0 and 30 days after the
    `as_of_date` inclusive moves `CURRENT → AT_RISK`"

    Design: Difficulty/non_linear_state_machine/liability_protection_parallel_dimensions_advance_independently
    """
    world = _protection_with_five_duties(api)
    run_sweep(world, "2027-07-21")

    result = run_sweep(world, "2028-06-10")
    assert_sweep_counters(
        result,
        at_risk_count=5,
        lapsed_count=0,
        stale_inquiry_count=0,
        forfeited_protection_count=0,
        frozen_site_count=0,
    )

    protection = world.read_protection()
    assert_fields(
        protection,
        inquiry_state="AAI_STALE",
        obligation_state="AT_RISK",
        bfpp_status="NOT_ESTABLISHED",
        obligations_total_weight=20,
        current_weight=0,
        at_risk_weight=20,
        lapsed_weight=0,
    )
    assert_number(protection["compliance_pct"], "0.5000", "compliance_pct")
    assert_weight_conservation(protection)
    assert_fields(world.read_site(), cleanup_posture="OPEN")


# ─── remedial_action_plan_fork_join_branches_advance_independently ──────────────

DESIGN_TOTAL_CENTS = 115210677


def _submitted_plan_with_sibling(api):
    """
    A submitted remedy plus a second draft remedy filed on the same enrollment.

    The sibling is filed after the first plan has left ``DRAFT``, so it is still a draft
    when the join is taken and the approval cascade has something to withdraw.
    """
    world = stage_enrolled(api)
    stage_plan(world)
    submitted = submit_plan(world)
    enrollment = world.read_enrollment()
    sibling = add_plan(world, expected_vcp_enrollment_version=enrollment["version"])
    return world, submitted, sibling


def test_submission_forks_the_two_branches_into_their_initial_states(api):
    """
    One request opens the comment period and leaves the technical branch unstarted.

    "It forks the review into two independent branches, setting `technical_review_state`
    to `NOT_STARTED` and `public_comment_state` to `OPEN`."

    Design: Difficulty/non_linear_state_machine/remedial_action_plan_fork_join_branches_advance_independently
    """
    world = stage_enrolled(api)
    stage_plan(world)

    submitted = submit_plan(world)
    assert_fields(
        submitted,
        status="UNDER_TECHNICAL_REVIEW",
        technical_review_state="NOT_STARTED",
        public_comment_state="OPEN",
        total_estimate_cents=DESIGN_TOTAL_CENTS,
    )
    assert_pins_match(submitted["pinned_cleanup_goal_versions"], world.read_goals())


def test_the_technical_branch_moves_alone_and_touches_no_cost_figure(api):
    """
    Passing the technical branch leaves the comment period open and the money alone.

    "A passing decision sets `technical_review_state` to `PASSED`, moves the plan
    `UNDER_TECHNICAL_REVIEW → PUBLIC_COMMENT`, and increments the plan's `version` by 1.
    It touches **no** cost figure whatsoever; that asymmetry against the other branch is
    deliberate."

    Design: Difficulty/non_linear_state_machine/remedial_action_plan_fork_join_branches_advance_independently
    """
    world = stage_enrolled(api)
    stage_plan(world)
    submit_plan(world)

    passed = technical_review(world, decision="PASS")
    assert_fields(
        passed,
        status="PUBLIC_COMMENT",
        technical_review_state="PASSED",
        public_comment_state="OPEN",
        direct_cost_cents=89787402,
        escalation_cents=11313213,
        oversight_cents=4000000,
        total_estimate_cents=DESIGN_TOTAL_CENTS,
    )


def test_the_comment_branch_moves_alone_and_leaves_the_status_where_it_was(api):
    """
    Closing the comment period advances only the branch dimension.

    "The plan's `status` stays `PUBLIC_COMMENT` throughout — only the branch dimension
    moves — and, mirroring the technical branch's refusal to touch cost figures, this
    branch touches no technical field."

    Design: Difficulty/non_linear_state_machine/remedial_action_plan_fork_join_branches_advance_independently
    """
    world = stage_enrolled(api)
    stage_plan(world)
    submit_plan(world)
    technical_review(world, decision="PASS")

    closed_branch = close_comment(world, public_comment_count=7)
    assert_fields(
        closed_branch,
        status="PUBLIC_COMMENT",
        technical_review_state="PASSED",
        public_comment_state="CLOSED",
        public_comment_count=7,
        total_estimate_cents=DESIGN_TOTAL_CENTS,
    )


def test_the_join_approves_and_cascades_to_the_control_enrollment_and_sibling(api):
    """
    With both branches landed the approval reaches three neighbouring aggregates.

    "Approval records `approved_by_user_id` and `approved_at`, then cascades: every site
    control on this plan whose `status` is `PROPOSED` becomes `APPROVED` with its
    `next_certification_due_on` recomputed and its `version` incremented by 1; the parent
    enrollment moves `ENROLLED → REMEDY_APPROVED` with its `version` incremented by 1;
    and every **other** remedial action plan on the same enrollment whose `status` is
    `DRAFT` or `REVISION_REQUESTED` becomes `WITHDRAWN` with its `version` incremented by
    1."

    Design: Difficulty/non_linear_state_machine/remedial_action_plan_fork_join_branches_advance_independently
    """
    world, _submitted, sibling = _submitted_plan_with_sibling(api)
    technical_review(world, decision="PASS")
    close_comment(world)

    approved = approve_plan(world)
    assert_fields(
        approved,
        status="APPROVED",
        technical_review_state="PASSED",
        public_comment_state="CLOSED",
        approved_by_user_id="reviewer-alpha",
    )
    assert_pins_match(approved["pinned_cleanup_goal_versions"], world.read_goals())

    assert_fields(
        world.read_control(),
        status="APPROVED",
        next_certification_due_on="2027-04-01",
    )
    assert_fields(world.read_enrollment(), status="REMEDY_APPROVED")
    assert_fields(world.read_plan(sibling), status="WITHDRAWN")
