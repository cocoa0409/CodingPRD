"""
Declared initial states, the transitions that fire automatically, and the ones refused.

Several records in this programme are never observable in their nominal first state
because a follow-on transition fires inside the creating request, and several triggers
that look harmless are refused purely because the target is sitting in the wrong state.
The tests below pin each freshly created record to its declared starting values, walk the
two-step submissions and the multi-level approval cascades, and take each refusal at the
exact state where it bites.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
)

from test_helpers import (
    ERR_APPROVED_PLAN_EXISTS,
    ERR_INVALID_AWARD_STATE,
    ERR_INVALID_ENROLLMENT_STATE,
    ERR_INVALID_PHASE_STATE,
    ERR_NO_FINDINGS,
    ERR_SITE_ALREADY_ACQUIRED,
    REVIEWER_ALPHA,
    REVIEWER_BETA,
    acquisition_payload,
    add_assessment_phase,
    add_award,
    add_control,
    add_enrollment,
    add_event,
    add_finding,
    add_plan,
    assert_fields,
    assert_instant,
    assert_number,
    certify_control,
    close_comment,
    decide_award,
    decide_eligibility,
    funding_decision_payload,
    phase_review_payload,
    set_clock,
    stage_acquisition,
    stage_approved,
    stage_assessed,
    stage_enrolled,
    stage_goals,
    stage_plan,
    stage_protection,
    stage_quote,
    stage_registry,
    stage_site,
    submit_plan,
    technical_review,
    withdrawal_payload,
)

# ─── entities_start_in_declared_initial_states_after_create ─────────────────────


def _a_parcel_ready_for_its_remedy(api):
    """
    The chain through both approved assessments, both goals and an accepted application.

    The enrollment is kept in two pieces — the create response and the response to the
    eligibility decision — because the create response is the only place the automatic
    follow-on transition can be observed.
    """
    world = stage_assessed(api)
    stage_goals(world)
    world.application = add_enrollment(world)
    world.enrollment = decide_eligibility(world, world.application, "ENROLL")
    world.enrollment_version = world.enrollment["version"]
    return world


def test_a_filed_remedy_starts_in_draft_with_both_branches_not_started(api):
    """
    Neither review branch has begun, nothing is pinned and nobody has approved anything.

    "A newly filed plan sits in `DRAFT` with `technical_review_state` `NOT_STARTED`,
    `public_comment_state` `NOT_STARTED`, `revision_round` zero,
    `pinned_cleanup_goal_versions` an empty array, `approved_by_user_id` null and
    `approved_at` null."

    Design: Corner/state_machines/entities_start_in_declared_initial_states_after_create
    """
    world = _a_parcel_ready_for_its_remedy(api)

    plan = add_plan(world)
    assert_fields(
        plan,
        status="DRAFT",
        technical_review_state="NOT_STARTED",
        public_comment_state="NOT_STARTED",
        public_comment_count=0,
        revision_round=0,
        pinned_cleanup_goal_versions=[],
        approved_by_user_id=None,
        approved_at=None,
        version=1,
    )


def test_a_proposed_control_starts_with_no_certification_history(api):
    """
    The first inspection deadline is set from the coverage start, before any inspection.

    "A newly proposed control sits in `PROPOSED` with `impairment_count` zero,
    `last_certified_on` null, `impaired_since` null, and `next_certification_due_on`
    derived as `coverage_from` advanced by `inspection_interval_days`."

    Design: Corner/state_machines/entities_start_in_declared_initial_states_after_create
    """
    world = _a_parcel_ready_for_its_remedy(api)
    world.plan = add_plan(world)

    control = add_control(world)
    assert_fields(
        control,
        status="PROPOSED",
        control_class="ENGINEERING",
        impairment_count=0,
        last_certified_on=None,
        impaired_since=None,
        coverage_from="2027-01-01",
        next_certification_due_on="2027-04-01",
        version=1,
    )


def test_a_filed_funding_application_starts_undecided(api):
    """
    Filing an application reserves nothing: no money is allocated and no reviewer named.

    "A new application sits in `APPLIED` with `allocated_cents` zero and
    `decided_by_user_id` null."

    Design: Corner/state_machines/entities_start_in_declared_initial_states_after_create
    """
    world = _a_parcel_ready_for_its_remedy(api)

    award = add_award(world)
    assert_fields(
        award,
        status="APPLIED",
        allocated_cents=0,
        decided_by_user_id=None,
        program_code="OH-BROWNFIELD-CLEANUP",
        funding_kind="GRANT",
        version=1,
    )


def test_a_scheduled_analysis_starts_pending(api):
    """
    Reserving the bench records no result and no verdict, only the reservation.

    "A newly scheduled event sits in `SCHEDULED` with `result_status` `PENDING`,
    `result_value_ugl` null and `control_condition` null."

    Design: Corner/state_machines/entities_start_in_declared_initial_states_after_create
    """
    world = _a_parcel_ready_for_its_remedy(api)

    event = add_event(world)
    assert_fields(
        event,
        status="SCHEDULED",
        result_status="PENDING",
        result_value_ugl=None,
        control_condition=None,
        event_type="SAMPLING",
        laboratory_id=world.laboratory["id"],
        cleanup_goal_id=world.goal_restricted["id"],
        version=1,
    )


def test_an_application_is_never_observable_before_eligibility_review(api):
    """
    The create response already carries the follow-on state, not the nominal first one.

    "A new enrollment starts with `reverted_completion_count` at zero, `enrolled_on`
    null, `eligibility_decided_by_user_id` null and `completion_requested_at` null, and
    its status advances `APPLIED → ELIGIBILITY_REVIEW` automatically inside the creating
    request, changing nothing but `status` and `updated_at`, so no client observes an
    enrollment resting in `APPLIED`."

    Design: Corner/state_machines/entities_start_in_declared_initial_states_after_create
    """
    world = stage_assessed(api)
    stage_goals(world)

    application = add_enrollment(world)
    assert_fields(
        application,
        status="ELIGIBILITY_REVIEW",
        reverted_completion_count=0,
        enrolled_on=None,
        eligibility_decided_by_user_id=None,
        completion_requested_at=None,
        program_track="RESTRICTED_CLOSURE",
        version=1,
    )


# ─── submit_assessment_phase_advances_to_under_review_with_side_effects ──────────

SUBMITTED_AT = "2026-08-01T00:00:00Z"


def _a_draft_phase_carrying_one_exceedance(api):
    """A screening-tier phase with a single soil-vapour result 96 times its threshold."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    world.phase_i = add_assessment_phase(world, phase_type="PHASE_I")
    world.phase_i_finding = add_finding(world, world.phase_i)
    return world


def test_one_submit_leaves_the_phase_in_under_review(api):
    """
    Two transitions fire in the one request, so the resting state skips the middle one.

    "The status movement is a two-step within one request: the phase advances `DRAFT →
    SUBMITTED` and then, automatically and in the same request, `SUBMITTED →
    UNDER_REVIEW`."

    Design: Corner/state_machines/submit_assessment_phase_advances_to_under_review_with_side_effects
    """
    world = _a_draft_phase_carrying_one_exceedance(api)

    submitted = get_success_data(
        world.api.submit_assessment_phase(world.phase_i["id"], world.consult_headers)
    )
    assert_fields(
        submitted,
        status="UNDER_REVIEW",
        review_round=1,
        findings_count=1,
        reviewed_by_user_id=None,
        # created (1) -> the one finding recorded (2) -> this submission (3)
        version=3,
    )
    assert_instant(submitted["submitted_at"], SUBMITTED_AT, "submitted_at")
    assert_number(submitted["max_exceedance_factor"], "96.00", "max_exceedance_factor")

    assert_fields(world.read_site(), delineation_status="NONE")


def test_a_phase_with_no_findings_cannot_be_submitted(api):
    """
    A phase with nothing analytical in it has nothing for the agency to review.

    "The phase must carry at least one finding, so `findings_count` must be 1 or more — a
    phase with no findings is refused with `ERR_NO_FINDINGS`."

    Design: Corner/state_machines/submit_assessment_phase_with_no_findings_rejected
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    phase = add_assessment_phase(world, phase_type="PHASE_I")
    assert_fields(phase, status="DRAFT", findings_count=0)

    response = world.api.submit_assessment_phase(phase["id"], world.consult_headers)
    validate_error(response, ERR_NO_FINDINGS, 422)

    assert_fields(
        get_success_data(world.api.get_assessment_phase(phase["id"], world.consult_headers)),
        status="DRAFT",
        review_round=0,
        submitted_at=None,
        version=1,
    )


def test_a_draft_phase_cannot_be_reviewed(api):
    """
    The review endpoint acts on a phase in review, and a phase never submitted is not.

    "**State-machine precondition** — the target entity's current state permits the
    requested trigger, else the entity-specific state error."

    Design: Corner/state_machines/review_assessment_phase_still_in_draft_rejected
    """
    world = _a_draft_phase_carrying_one_exceedance(api)

    response = world.api.review_assessment_phase(
        world.phase_i["id"],
        phase_review_payload(decision="APPROVE", review_comment="Premature approval attempt."),
        REVIEWER_ALPHA,
    )
    validate_error(response, ERR_INVALID_PHASE_STATE, 409)

    assert_fields(
        get_success_data(
            world.api.get_assessment_phase(world.phase_i["id"], world.consult_headers)
        ),
        status="DRAFT",
        reviewed_by_user_id=None,
    )
    assert_fields(world.read_site(), delineation_status="NONE")
    assert_fields(world.read_protection(), inquiry_state="AAI_PENDING")


# ─── denied_funding_award_terminal_state_rejects_second_decision ─────────────────


def test_a_denied_application_refuses_a_second_decision(api):
    """
    Refusal is the end of the application, and a different reviewer cannot reopen it.

    "Awarding or denying an already decided application, or rescinding one that is not
    `AWARDED`, is refused with `ERR_INVALID_AWARD_STATE`."

    Design: Corner/state_machines/denied_funding_award_terminal_state_rejects_second_decision
    """
    world = stage_registry(api)
    stage_site(world)
    application = add_award(world)

    denied = decide_award(
        world, application, "DENY", decision_note="Programme oversubscribed."
    )
    assert_fields(
        denied, status="DENIED", allocated_cents=0, decided_by_user_id="reviewer-alpha"
    )

    response = world.api.decide_funding_award(
        application["id"],
        funding_decision_payload(
            decision="AWARD", decision_note="Reconsideration attempt."
        ),
        REVIEWER_BETA,
    )
    validate_error(response, ERR_INVALID_AWARD_STATE, 409)

    assert_fields(
        world.read_award(application),
        status="DENIED",
        allocated_cents=0,
        decided_by_user_id="reviewer-alpha",
    )


# ─── second_site_acquisition_rejected_as_already_acquired ────────────────────────


def test_a_second_acquisition_is_refused_and_the_first_date_stands(api):
    """
    Taking title happens once; a later date does not overwrite the closing already filed.

    "Only the owning redeveloper may record it, and only once — a second attempt on a
    parcel already `ACQUIRED` is refused with `ERR_SITE_ALREADY_ACQUIRED`."

    Design: Corner/state_machines/second_site_acquisition_rejected_as_already_acquired
    """
    world = stage_registry(api)
    stage_site(world)
    stage_acquisition(world)
    assert_fields(world.site, acquisition_status="ACQUIRED", acquisition_date="2026-10-15")

    response = world.api.record_acquisition(
        world.site["id"], acquisition_payload("2026-10-20"), world.redev_headers
    )
    validate_error(response, ERR_SITE_ALREADY_ACQUIRED, 409)

    assert_fields(
        world.read_site(), acquisition_status="ACQUIRED", acquisition_date="2026-10-15"
    )


# ─── plan_approval_cascades_control_approval_and_enrollment_remedy_approved ──────

APPROVED_AT = "2026-12-10T00:00:00Z"
PUBLIC_COMMENT_COUNT = 7


def test_approval_cascades_into_the_control_and_the_enrollment(api):
    """
    One approval call moves three records, and only one of them is the plan itself.

    "Approval records `approved_by_user_id` and `approved_at`, then cascades: every site
    control on this plan whose `status` is `PROPOSED` becomes `APPROVED` with its
    `next_certification_due_on` recomputed and its `version` incremented by 1; the parent
    enrollment moves `ENROLLED → REMEDY_APPROVED` with its `version` incremented by 1; and
    every **other** remedial action plan on the same enrollment whose `status` is `DRAFT`
    or `REVISION_REQUESTED` becomes `WITHDRAWN` with its `version` incremented by 1."

    Design: Corner/state_machines/plan_approval_cascades_control_approval_and_enrollment_remedy_approved
    """
    world = stage_approved(api)

    assert_fields(world.plan, status="APPROVED", approved_by_user_id="reviewer-alpha")
    assert_instant(world.plan["approved_at"], APPROVED_AT, "approved_at")
    assert_fields(
        world.read_control(), status="APPROVED", next_certification_due_on="2027-04-01"
    )
    assert_fields(world.read_enrollment(), status="REMEDY_APPROVED")


def test_the_submitted_remedy_pinned_both_goal_versions_in_creation_order(api):
    """
    The pins survive approval and name each goal once, oldest first.

    "It captures `pinned_cleanup_goal_versions` — one entry per cleanup goal on the site,
    each holding that goal's `cleanup_goal_id` and its current `version` as
    `pinned_version`, the entries ordered by the goal's `created_at` ascending."

    Design: Corner/state_machines/plan_approval_cascades_control_approval_and_enrollment_remedy_approved
    """
    world = stage_approved(api)

    restricted = world.read_goal(world.goal_restricted)
    unrestricted = world.read_goal(world.goal_unrestricted)
    assert world.read_plan()["pinned_cleanup_goal_versions"] == [
        {"cleanup_goal_id": restricted["id"], "pinned_version": restricted["version"]},
        {"cleanup_goal_id": unrestricted["id"], "pinned_version": unrestricted["version"]},
    ], "the two goals are pinned in the order they were derived"


def test_closing_the_comment_period_stores_the_count_and_advances_only_that_branch(api):
    """
    The comment branch moves on its own while the plan's own status stays put.

    "Closing stores `public_comment_count`, advances `public_comment_state` `OPEN →
    CLOSED`, and increments the plan's `version` by 1."

    Design: Corner/state_machines/plan_approval_cascades_control_approval_and_enrollment_remedy_approved
    """
    world = stage_enrolled(api)
    stage_plan(world)
    world.plan = submit_plan(world)
    passed = technical_review(world, decision="PASS")
    assert_fields(passed, status="PUBLIC_COMMENT", technical_review_state="PASSED")

    closed = close_comment(world, public_comment_count=PUBLIC_COMMENT_COUNT)
    assert_fields(
        closed,
        status="PUBLIC_COMMENT",
        technical_review_state="PASSED",
        public_comment_state="CLOSED",
        public_comment_count=PUBLIC_COMMENT_COUNT,
        version=passed["version"] + 1,
    )


# ─── first_control_pass_certification_bubbles_enrollment_to_implementation ───────

IN_SERVICE_CLOCK = "2027-01-15T00:00:00Z"
CERTIFICATION_DATE = "2027-01-15"
NEXT_DUE_ON = "2027-04-15"


def _an_approved_control_on_its_first_inspection_day(api):
    """An approved remedy with the clock standing inside the control's coverage."""
    world = stage_approved(api)
    set_clock(world.api, IN_SERVICE_CLOCK)
    return world


def test_the_first_passing_certification_puts_the_control_into_service(api):
    """
    The control's own transition drags the enrollment forward with it.

    "The first passing certification on a control belonging to a plan drives the parent
    enrollment `REMEDY_APPROVED → IMPLEMENTATION`."

    Design: Corner/state_machines/first_control_pass_certification_bubbles_enrollment_to_implementation
    """
    world = _an_approved_control_on_its_first_inspection_day(api)
    assert_fields(world.read_enrollment(), status="REMEDY_APPROVED")

    certified = certify_control(
        world, condition="PASS", certification_date=CERTIFICATION_DATE
    )
    assert_fields(certified, status="OPERATING", impaired_since=None, impairment_count=0)
    assert_fields(
        world.read_enrollment(), status="IMPLEMENTATION", reverted_completion_count=0
    )
    assert_fields(world.read_site(), cleanup_posture="OPEN", impaired_control_count=0)


def test_the_certification_sets_the_next_due_date_from_the_interval(api):
    """
    The next deadline is measured from the inspection just filed, not from the coverage.

    "In every case `last_certified_on` is set to the supplied `certification_date` and
    `next_certification_due_on` is recomputed as `last_certified_on` advanced by
    `inspection_interval_days`, and the control's `version` increments by 1."

    Design: Corner/state_machines/first_control_pass_certification_bubbles_enrollment_to_implementation
    """
    world = _an_approved_control_on_its_first_inspection_day(api)
    before = world.read_control()

    certified = certify_control(
        world, condition="PASS", certification_date=CERTIFICATION_DATE
    )
    assert_fields(
        certified,
        last_certified_on=CERTIFICATION_DATE,
        next_certification_due_on=NEXT_DUE_ON,
        inspection_interval_days=90,
        version=before["version"] + 1,
    )


# ─── technical_revision_request_cancels_quoted_policy_and_voids_comment_branch ───

REVISION_COMMENT = "Groundwater capture zone under-designed."


def _a_submitted_remedy_with_an_outstanding_quote(api):
    """
    A remedy in technical review with one priced but unbound cost cap against it.

    The quote is struck against the submitted plan version, so it is the version the
    revision request has to invalidate.
    """
    world = stage_enrolled(api)
    stage_plan(world)
    world.plan = submit_plan(world)
    stage_quote(world)
    return world


def _request_a_revision(world):
    """Send the remedy back to the consultant on the technical branch."""
    return technical_review(
        world, decision="REQUEST_REVISION", review_comment=REVISION_COMMENT
    )


def test_a_revision_request_voids_the_comment_branch_and_the_pins(api):
    """
    The comment period the submission opened is discarded along with the goal pins.

    "When issued, the plan moves `UNDER_TECHNICAL_REVIEW → REVISION_REQUESTED`,
    `revision_round` increments by 1, `public_comment_state` resets to `NOT_STARTED` and
    `public_comment_count` resets to zero because the comment period is void,
    `pinned_cleanup_goal_versions` is cleared to an empty array, and every cost-cap policy
    on this plan whose `status` is `QUOTED` becomes `CANCELLED` with its `version`
    incremented by 1."

    Design: Corner/state_machines/technical_revision_request_cancels_quoted_policy_and_voids_comment_branch
    """
    world = _a_submitted_remedy_with_an_outstanding_quote(api)
    assert len(world.plan["pinned_cleanup_goal_versions"]) == 2, (
        "the submission pinned both goals"
    )

    returned = _request_a_revision(world)
    assert_fields(
        returned,
        status="REVISION_REQUESTED",
        revision_round=1,
        technical_review_state="NOT_STARTED",
        public_comment_state="NOT_STARTED",
        public_comment_count=0,
        pinned_cleanup_goal_versions=[],
    )


def test_a_revision_request_cancels_the_outstanding_quote(api):
    """
    The carrier's price dies with the plan it was struck against, history intact.

    "When issued, the plan moves `UNDER_TECHNICAL_REVIEW → REVISION_REQUESTED`,
    `revision_round` increments by 1, `public_comment_state` resets to `NOT_STARTED` and
    `public_comment_count` resets to zero because the comment period is void,
    `pinned_cleanup_goal_versions` is cleared to an empty array, and every cost-cap policy
    on this plan whose `status` is `QUOTED` becomes `CANCELLED` with its `version`
    incremented by 1."

    Design: Corner/state_machines/technical_revision_request_cancels_quoted_policy_and_voids_comment_branch
    """
    world = _a_submitted_remedy_with_an_outstanding_quote(api)
    quoted = world.read_policy()
    assert_fields(quoted, status="QUOTED", bound_at=None)

    _request_a_revision(world)

    cancelled = world.read_policy()
    assert_fields(
        cancelled,
        status="CANCELLED",
        bound_at=None,
        underwriting_estimate_cents=quoted["underwriting_estimate_cents"],
        attachment_point_cents=quoted["attachment_point_cents"],
        limit_cents=quoted["limit_cents"],
        premium_cents=quoted["premium_cents"],
        version=quoted["version"] + 1,
    )
    assert_fields(world.read_control(), status="PROPOSED")


# ─── withdraw_enrollment_with_approved_plan_rejected ────────────────────────────

WITHDRAWAL_REASON = "Buyer walked away from the transaction."


def test_withdrawal_is_barred_once_the_remedy_is_approved(api):
    """
    The owner's exit closes the moment the agency has approved a remedy for the parcel.

    "Withdrawal is the owner's exit, available only from `ENROLLED` and only while no plan
    on the enrollment has reached `APPROVED` — an attempt against an approved remedy is
    refused with `ERR_APPROVED_PLAN_EXISTS`."

    Design: Corner/state_machines/withdraw_enrollment_with_approved_plan_rejected
    """
    world = stage_approved(api)

    response = world.api.withdraw_enrollment(
        world.enrollment["id"],
        world.redev_headers,
        withdrawal_payload(withdrawal_reason=WITHDRAWAL_REASON),
    )
    # Approval cascades the enrollment ENROLLED -> REMEDY_APPROVED, so the same
    # request violates both the state precondition and the approved-plan bar; the
    # contract names the approved-plan refusal without saying it pre-empts the
    # state-machine tier, so either 409 is a faithful reading.
    assert response.status_code == 409, response.text
    validate_error_is_one_of(
        response, [ERR_APPROVED_PLAN_EXISTS, ERR_INVALID_ENROLLMENT_STATE]
    )

    assert_fields(world.read_enrollment(), status="REMEDY_APPROVED")
    assert_fields(world.read_plan(), status="APPROVED")
    assert_fields(world.read_control(), status="APPROVED")
