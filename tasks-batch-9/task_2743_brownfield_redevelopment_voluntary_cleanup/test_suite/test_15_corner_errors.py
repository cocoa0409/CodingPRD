"""
Every declared refusal has to be reachable, and each one has to name itself precisely.

A caller that gets a generic 404 cannot tell which segment of a compound reference failed, and
a caller that gets a generic conflict cannot tell which aggregate was in the wrong state. So
each resource kind carries its own not-found code and each aggregate its own wrong-state code.
The rest of this file walks the prerequisite gates — delineation, goals, basis phase, boundary
integrity, revision ceilings, attainment, coverage windows, closure scope and the attachment
point — and shows each of them refusing.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    CLOCK_EPOCH,
    ERR_ATTACHMENT_POINT_TOO_LOW,
    ERR_AWARD_NOT_FOUND,
    ERR_BASIS_PHASE_INELIGIBLE,
    ERR_CERTIFICATION_OUTSIDE_COVERAGE,
    ERR_CONTROL_NOT_FOUND,
    ERR_DELINEATION_REQUIRED,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_EVENT_ALREADY_REPORTED,
    ERR_EVENT_NOT_FOUND,
    ERR_FINDING_NOT_FOUND,
    ERR_GOALS_NOT_ATTAINED,
    ERR_GOAL_NOT_FOUND,
    ERR_INQUIRY_DEFICIENT,
    ERR_INVALID_CONTROL_STATE,
    ERR_INVALID_LETTER_STATE,
    ERR_INVALID_PLAN_STATE,
    ERR_LETTER_NOT_FOUND,
    ERR_MEDIA_NOT_DELINEATED,
    ERR_NO_CLEANUP_GOALS,
    ERR_OBLIGATION_NOT_FOUND,
    ERR_PARTY_NOT_FOUND,
    ERR_PHASE_I_NOT_APPROVED,
    ERR_PLAN_NOT_FOUND,
    ERR_PLAN_REVISION_LIMIT,
    ERR_POLICY_NOT_FOUND,
    ERR_RESULTS_BEFORE_WINDOW,
    ERR_UNRESTRICTED_SCOPE_NOT_SUPPORTED,
    LENDER,
    PROGRAM_ADMIN,
    REVIEWER_ALPHA,
    REVIEWER_BETA,
    add_assessment_phase,
    add_control,
    add_event,
    add_finding,
    add_letter,
    add_plan,
    approve_plan,
    assert_estimate_figures,
    assert_fields,
    assert_number,
    assert_placement_figures,
    certify_control,
    close_comment,
    cost_line,
    decommission_payload,
    enrollment_payload,
    file_result,
    inquiry_completion_payload,
    lender_acceptance_payload,
    operation_certification_payload,
    phase_review_payload,
    request_completion,
    review_phase,
    sampling_result_payload,
    set_clock,
    stage_all_goals_attained,
    stage_approved,
    stage_assessed,
    stage_enrolled,
    stage_enrollment,
    stage_implementation,
    stage_plan,
    stage_protection,
    stage_quote,
    stage_registry,
    stage_site,
    submit_phase,
    submit_plan,
    technical_review,
    technical_review_payload,
)

# ─── every_declared_not_found_code_is_triggerable_by_an_unknown_id ────────────────


def test_each_retrieval_route_names_the_resource_kind_it_could_not_find(api):
    """
    Eleven reads against an empty database return eleven distinct codes, not one.

    "Each resource kind has its own not-found code so the caller can tell which segment failed:
    `ERR_SITE_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_PROTECTION_NOT_FOUND`,
    `ERR_OBLIGATION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_CONTROL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_LETTER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_GOAL_NOT_FOUND`,
    `ERR_FINDING_NOT_FOUND`, `ERR_PARTY_NOT_FOUND` and `ERR_LAB_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_declared_not_found_code_is_triggerable_by_an_unknown_id
    """
    set_clock(api, CLOCK_EPOCH)
    unknown = NON_EXISTENT_UUID

    validate_error(api.get_party(unknown, PROGRAM_ADMIN), ERR_PARTY_NOT_FOUND, 404)
    validate_error(
        api.get_contaminant_finding(unknown, REVIEWER_ALPHA), ERR_FINDING_NOT_FOUND, 404
    )
    validate_error(
        api.get_cleanup_goal(unknown, REVIEWER_ALPHA), ERR_GOAL_NOT_FOUND, 404
    )
    validate_error(
        api.get_continuing_obligation(unknown, REVIEWER_ALPHA),
        ERR_OBLIGATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_enrollment(unknown, REVIEWER_ALPHA), ERR_ENROLLMENT_NOT_FOUND, 404
    )
    validate_error(api.get_plan(unknown, REVIEWER_ALPHA), ERR_PLAN_NOT_FOUND, 404)
    validate_error(api.get_policy(unknown, REVIEWER_ALPHA), ERR_POLICY_NOT_FOUND, 404)
    validate_error(
        api.get_site_control(unknown, REVIEWER_ALPHA), ERR_CONTROL_NOT_FOUND, 404
    )
    validate_error(
        api.get_funding_award(unknown, REVIEWER_ALPHA), ERR_AWARD_NOT_FOUND, 404
    )
    validate_error(
        api.get_nfa_letter(unknown, REVIEWER_ALPHA), ERR_LETTER_NOT_FOUND, 404
    )
    validate_error(
        api.get_monitoring_event(unknown, REVIEWER_ALPHA), ERR_EVENT_NOT_FOUND, 404
    )


# ─── each_aggregate_reports_its_own_priority_twelve_state_code ────────────────────

FIRST_RESULT_UGL = 100.0
REJECTED_RESULT_UGL = 90.0
RESULT_CLOCK = "2027-06-01T00:00:00Z"
EARLY_LOAN_REFERENCE = "LOAN-2743-EARLY"
UNSUBMITTED_REVIEW_COMMENT = "Reviewing a plan that was never submitted."
PREMATURE_RETIREMENT_NOTE = "Retiring a control that is still only proposed."


def test_reviewing_a_plan_that_was_never_submitted_names_the_plan(api):
    """
    The technical branch cannot be decided on a draft.

    "`APPROVED` and `WITHDRAWN` are the plan's terminal states, and reviewing a `DRAFT` plan,
    approving from any state other than `PUBLIC_COMMENT`, or submitting an `APPROVED` or
    `WITHDRAWN` plan are all refused with `ERR_INVALID_PLAN_STATE`."

    Design: Corner/errors/each_aggregate_reports_its_own_priority_twelve_state_code
    """
    world = stage_enrolled(api)
    stage_plan(world)

    refused = api.technical_review_plan(
        world.plan["id"],
        technical_review_payload(
            decision="PASS", review_comment=UNSUBMITTED_REVIEW_COMMENT
        ),
        REVIEWER_ALPHA,
    )
    validate_error(refused, ERR_INVALID_PLAN_STATE, 409)

    assert_fields(
        world.read_plan(), status="DRAFT", technical_review_state="NOT_STARTED"
    )


def test_retiring_a_control_that_is_only_proposed_names_the_control(api):
    """
    Retirement is reserved for a control that has actually been in service.

    "Only an `OPERATING` control may be retired; any other status is
    `ERR_INVALID_CONTROL_STATE`."

    Design: Corner/errors/each_aggregate_reports_its_own_priority_twelve_state_code
    """
    world = stage_enrolled(api)
    stage_plan(world)

    refused = api.decommission_control(
        world.control["id"],
        REVIEWER_ALPHA,
        decommission_payload(decommission_note=PREMATURE_RETIREMENT_NOTE),
    )
    validate_error(refused, ERR_INVALID_CONTROL_STATE, 409)

    assert_fields(world.read_control(), status="PROPOSED")


def test_relying_on_a_letter_that_was_never_issued_names_the_letter(api):
    """
    A lender cannot rely on a draft.

    "Attempting acceptance on a letter that is still `DRAFT`, or one that has been `REVOKED`, is
    refused with `ERR_INVALID_LETTER_STATE`, as is issuing a letter that is already `ISSUED`."

    Design: Corner/errors/each_aggregate_reports_its_own_priority_twelve_state_code
    """
    world = stage_enrolled(api)
    stage_plan(world)
    world.letter = add_letter(world)

    refused = api.accept_nfa_letter(
        world.letter["id"],
        lender_acceptance_payload(lender_reference=EARLY_LOAN_REFERENCE),
        LENDER,
    )
    validate_error(refused, ERR_INVALID_LETTER_STATE, 409)

    assert_fields(
        world.read_letter(),
        status="DRAFT",
        accepted_by_lender_user_id=None,
        lender_reference=None,
    )


def test_filing_a_second_result_against_one_event_names_the_event(api):
    """
    The rejected re-filing does not replay the goal either.

    "Filing results against an event that is already `REPORTED` is refused with
    `ERR_EVENT_ALREADY_REPORTED`."

    Design: Corner/errors/each_aggregate_reports_its_own_priority_twelve_state_code
    """
    world = stage_enrolled(api)
    stage_plan(world)
    event = add_event(world, cleanup_goal_id=world.goal_restricted["id"])
    set_clock(api, RESULT_CLOCK)
    file_result(world, event, FIRST_RESULT_UGL)

    refused = api.file_monitoring_result(
        event["id"],
        sampling_result_payload(REJECTED_RESULT_UGL),
        world.consult_headers,
    )
    validate_error(refused, ERR_EVENT_ALREADY_REPORTED, 409)

    reported = get_success_data(api.get_monitoring_event(event["id"], REVIEWER_ALPHA))
    assert_fields(reported, status="REPORTED", result_status="COMPLIANT")
    assert_number(reported["result_value_ugl"], "100.0", "result_value_ugl")
    assert_fields(world.read_goal(world.goal_restricted), compliant_streak=1)


# ─── deficient_inquiry_outranks_the_phase_i_approval_gate ─────────────────────────

REVISION_COMMENT = "Historical use records incomplete; re-do the records review."


def _a_draft_records_review(api):
    """A protection whose nominated inquiry phase is still an unsubmitted draft."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    phase = add_assessment_phase(world, phase_type="PHASE_I")
    add_finding(world, phase)
    return world, phase


def test_an_unapproved_records_review_cannot_close_the_inquiry(api):
    """
    The referential gate speaks first, while the protection's own dimension is still pending.

    "The nominated phase must be an assessment phase on **this protection's site** with
    `phase_type` `PHASE_I` and `status` `APPROVED`, else `ERR_PHASE_I_NOT_APPROVED`."

    Design: Corner/errors/deficient_inquiry_outranks_the_phase_i_approval_gate
    """
    world, phase = _a_draft_records_review(api)

    refused = api.complete_inquiry(
        world.protection["id"],
        inquiry_completion_payload(phase["id"]),
        world.consult_headers,
    )
    validate_error(refused, ERR_PHASE_I_NOT_APPROVED, 422)

    assert_fields(
        world.read_protection(),
        inquiry_state="AAI_PENDING",
        aai_phase_id=None,
        aai_expires_on=None,
    )


def test_once_the_inquiry_is_deficient_the_state_code_outranks_the_referential_one(api):
    """
    The same body, the same unapproved phase — but now a wrong-state conflict instead.

    "Deficiency is not curable on the same record: filing an inquiry completion against a
    protection whose `inquiry_state` is already `AAI_DEFICIENT` is refused with
    `ERR_INQUIRY_DEFICIENT` (HTTP 409)."

    Design: Corner/errors/deficient_inquiry_outranks_the_phase_i_approval_gate
    """
    world, phase = _a_draft_records_review(api)
    before = world.read_protection()

    submit_phase(world, phase)
    returned = review_phase(
        world, phase, "REQUEST_REVISION", review_comment=REVISION_COMMENT
    )
    assert_fields(returned, status="REVISION_REQUESTED", review_round=1)
    assert_fields(
        world.read_protection(),
        inquiry_state="AAI_DEFICIENT",
        bfpp_status="NOT_ESTABLISHED",
        version=before["version"] + 1,
    )

    refused = api.complete_inquiry(
        world.protection["id"],
        inquiry_completion_payload(phase["id"]),
        world.consult_headers,
    )
    validate_error(refused, ERR_INQUIRY_DEFICIENT, 409)

    assert_fields(world.read_protection(), aai_phase_id=None, aai_expires_on=None)


# ─── enrollment_and_plan_prerequisite_gates_are_triggerable ───────────────────────

UNASSESSED_APPLICANT_STATEMENT = "Tannery parcel enrollment filed before any assessment."
GOALLESS_REMEDY_NARRATIVE = (
    "Excavation and off-site disposal with vapor mitigation, filed before any cleanup goal "
    "was derived."
)


def test_a_parcel_with_no_screening_at_all_cannot_be_enrolled(api):
    """
    The programme will not take an application on an unscreened parcel.

    "An application may only be filed once the parcel has at least been screened —
    `delineation_status` must not be `NONE`, meaning an approved `PHASE_I` phase exists —
    otherwise the application is refused with `ERR_DELINEATION_REQUIRED`."

    Design: Corner/errors/enrollment_and_plan_prerequisite_gates_are_triggerable
    """
    world = stage_registry(api)
    stage_site(world)
    assert_fields(world.read_site(), delineation_status="NONE")

    refused = api.create_enrollment(
        enrollment_payload(
            world.site["id"], applicant_statement=UNASSESSED_APPLICANT_STATEMENT
        ),
        world.redev_headers,
    )
    validate_error(refused, ERR_DELINEATION_REQUIRED, 422)

    _rows, meta = validate_paginated(
        api.list_site_enrollments(world.site["id"], world.redev_headers)
    )
    assert meta["total_count"] == 0, f"no enrollment may have been created: {meta}"


def test_a_remedy_on_a_delineated_parcel_still_needs_a_goal_to_aim_at(api):
    """
    Delineation is not enough: the submit needs something to pin.

    "and at least one cleanup goal must exist on the site, else `ERR_NO_CLEANUP_GOALS`."

    Design: Corner/errors/enrollment_and_plan_prerequisite_gates_are_triggerable
    """
    world = stage_assessed(api)
    stage_enrollment(world)
    world.plan = add_plan(world, remedy_narrative=GOALLESS_REMEDY_NARRATIVE)
    assert_fields(world.read_site(), delineation_status="DELINEATED")
    assert world.read_goals() == [], "this parcel deliberately has no cleanup goals"

    refused = api.submit_plan(world.plan["id"], world.consult_headers)
    validate_error(refused, ERR_NO_CLEANUP_GOALS, 422)

    assert_fields(
        world.read_plan(),
        status="DRAFT",
        pinned_cleanup_goal_versions=[],
        technical_review_state="NOT_STARTED",
    )


# ─── basis_phase_ineligibility_is_triggerable_at_plan_submit ──────────────────────

PHASE_I_BASIS_NARRATIVE = (
    "Remedy narrative citing the Phase I records review as its delineation basis."
)

# The records review screened at 96.00 times its screening level, which earns the adder.
PRICED_OFF_THE_RECORDS_REVIEW = {
    "direct_cost_cents": 89787402,
    "escalation_cents": 11313213,
    "contingency_pct": "0.40",
    "contingency_cents": 40440246,
    "oversight_cents": 4000000,
    "total_cents": 145540861,
}


def _a_remedy_filed_on_the_records_review(api):
    """A draft remedy whose basis phase is the approved PHASE_I rather than the PHASE_II."""
    world = stage_enrolled(api)
    world.plan = add_plan(
        world,
        basis_assessment_phase_id=world.phase_i["id"],
        remedy_narrative=PHASE_I_BASIS_NARRATIVE,
    )
    return world


def test_the_records_review_basis_is_accepted_at_create_and_prices_the_estimate(api):
    """
    The filing is stored unchecked, and it prices itself off the screening tier plus the adder.

    "A five-percentage-point adder is applied on top when that same basis phase's
    `max_exceedance_factor` is greater than or equal to 10.0, and no adder is applied when it is
    below 10.0 — a plume an order of magnitude above screening levels earns extra reserve."

    Design: Corner/errors/basis_phase_ineligibility_is_triggerable_at_plan_submit
    """
    world = _a_remedy_filed_on_the_records_review(api)

    assert_fields(world.read_plan(), status="DRAFT")
    assert_estimate_figures(world.plan, PRICED_OFF_THE_RECORDS_REVIEW)


def test_the_submit_refuses_the_records_review_as_a_delineation_basis(api):
    """
    A `PHASE_I` is neither a `PHASE_II` nor a `SUPPLEMENTAL`, so the fork never opens.

    "the `basis_assessment_phase_id` must reference an assessment phase on the plan's own site
    whose `phase_type` is `PHASE_II` or `SUPPLEMENTAL`, whose `status` is `APPROVED` and whose
    `delineation_complete` is true, else `ERR_BASIS_PHASE_INELIGIBLE`;"

    Design: Corner/errors/basis_phase_ineligibility_is_triggerable_at_plan_submit
    """
    world = _a_remedy_filed_on_the_records_review(api)

    refused = api.submit_plan(world.plan["id"], world.consult_headers)
    validate_error(refused, ERR_BASIS_PHASE_INELIGIBLE, 422)

    assert_fields(
        world.read_plan(),
        status="DRAFT",
        technical_review_state="NOT_STARTED",
        public_comment_state="NOT_STARTED",
    )


# ─── undelineated_exceedance_blocks_a_delineation_complete_approval ───────────────

OPEN_BOUNDARY_PHASE = {
    "phase_type": "PHASE_II",
    "field_start_date": "2026-06-15",
    "field_end_date": "2026-07-05",
    "delineation_confidence": "FULL",
    "delineation_complete": True,
}
OPEN_BOUNDARY_FINDING = {
    "contaminant_code": "TCE",
    "media": "SOIL_VAPOR",
    "sample_location_code": "SV-21",
    "max_concentration_ugl": 24.0,
    "screening_level_ugl": 5.0,
    "delineated": False,
}
CLOSED_BOUNDARY_PHASE = {
    "phase_type": "SUPPLEMENTAL",
    "field_start_date": "2026-08-01",
    "field_end_date": "2026-08-20",
    "delineation_confidence": "FULL",
    "delineation_complete": True,
}
OPTIMISTIC_APPROVAL_COMMENT = "Attempting to approve an open plume boundary."
BOUNDARY_CLOSED_COMMENT = "Boundary closed by the supplemental borings."


def _a_phase_claiming_closed_boundaries_it_does_not_have(api):
    """A submitted PHASE_II asserting complete delineation over an open plume."""
    world = stage_registry(api)
    stage_site(world)
    phase = add_assessment_phase(world, **OPEN_BOUNDARY_PHASE)
    finding = add_finding(world, phase, **OPEN_BOUNDARY_FINDING)
    submit_phase(world, phase)
    return world, phase, finding


def test_an_open_plume_boundary_blocks_the_approval_of_the_phase_that_claims_it(api):
    """
    The exceeding analyte is four-fold over its screening level and still undelineated.

    "Approval requires that the parcel not be `FROZEN`, and it enforces the
    delineation-integrity rule: when the phase's `phase_type` is `PHASE_II` or `SUPPLEMENTAL`
    **and** its `delineation_complete` is true, every finding on that phase whose
    `exceedance_factor` is strictly greater than 1.0 must have `delineated` true."

    Design: Corner/errors/undelineated_exceedance_blocks_a_delineation_complete_approval
    """
    world, phase, finding = _a_phase_claiming_closed_boundaries_it_does_not_have(api)
    recorded = get_success_data(
        api.get_contaminant_finding(finding["id"], world.consult_headers)
    )
    assert_number(recorded["exceedance_factor"], "4.80", "exceedance_factor")
    assert_fields(recorded, delineated=False)

    refused = api.review_assessment_phase(
        phase["id"],
        phase_review_payload(
            decision="APPROVE", review_comment=OPTIMISTIC_APPROVAL_COMMENT
        ),
        REVIEWER_ALPHA,
    )
    validate_error(refused, ERR_MEDIA_NOT_DELINEATED, 422)

    still_open = get_success_data(
        api.get_assessment_phase(phase["id"], world.consult_headers)
    )
    assert_fields(still_open, status="UNDER_REVIEW", reviewed_by_user_id=None)
    assert_fields(world.read_site(), delineation_status="NONE")


def test_a_supplemental_phase_that_closes_the_boundary_delineates_the_parcel(api):
    """
    The same analyte, re-bored and now delineated, carries the approval through.

    "approving a `PHASE_II` or `SUPPLEMENTAL` phase whose `delineation_complete` is true moves
    it to `DELINEATED`."

    Design: Corner/errors/undelineated_exceedance_blocks_a_delineation_complete_approval
    """
    world, rejected_phase, _finding = (
        _a_phase_claiming_closed_boundaries_it_does_not_have(api)
    )
    api.review_assessment_phase(
        rejected_phase["id"],
        phase_review_payload(
            decision="APPROVE", review_comment=OPTIMISTIC_APPROVAL_COMMENT
        ),
        REVIEWER_ALPHA,
    )

    supplemental = add_assessment_phase(
        world, supersedes_phase_id=rejected_phase["id"], **CLOSED_BOUNDARY_PHASE
    )
    add_finding(
        world,
        supplemental,
        **{**OPEN_BOUNDARY_FINDING, "sample_location_code": "SV-21R", "delineated": True},
    )
    submit_phase(world, supplemental)
    approved = review_phase(
        world, supplemental, "APPROVE", review_comment=BOUNDARY_CLOSED_COMMENT
    )

    assert_fields(
        approved, status="APPROVED", supersedes_phase_id=rejected_phase["id"]
    )
    assert_fields(world.read_site(), delineation_status="DELINEATED")


# ─── third_revision_request_is_refused_by_the_plan_revision_ceiling ───────────────

REVISION_ROUNDS = (
    "Round one: revise the vapour mitigation design.",
    "Round two: monitoring well network still inadequate.",
)
THIRD_REVISION_COMMENT = "Round three: refused by the revision ceiling."


def _a_remedy_returned_twice(api):
    """A remedy back under technical review after two accepted revision requests."""
    world = stage_enrolled(api)
    stage_plan(world)
    for comment in REVISION_ROUNDS:
        submit_plan(world)
        technical_review(world, decision="REQUEST_REVISION", review_comment=comment)
    return world


def test_the_first_two_revision_requests_are_accepted_and_void_the_comment_period(api):
    """
    Each accepted revision winds the counter on and clears the pins the submit had made.

    "When issued, the plan moves `UNDER_TECHNICAL_REVIEW → REVISION_REQUESTED`,
    `revision_round` increments by 1, `public_comment_state` resets to `NOT_STARTED` and
    `public_comment_count` resets to zero because the comment period is void,
    `pinned_cleanup_goal_versions` is cleared to an empty array, and every cost-cap policy on
    this plan whose `status` is `QUOTED` becomes `CANCELLED` with its `version` incremented by
    1."

    Design: Corner/errors/third_revision_request_is_refused_by_the_plan_revision_ceiling
    """
    world = stage_enrolled(api)
    stage_plan(world)

    for expected_round, comment in enumerate(REVISION_ROUNDS, start=1):
        submit_plan(world)
        returned = technical_review(
            world, decision="REQUEST_REVISION", review_comment=comment
        )
        assert_fields(
            returned,
            status="REVISION_REQUESTED",
            revision_round=expected_round,
            public_comment_state="NOT_STARTED",
            public_comment_count=0,
            pinned_cleanup_goal_versions=[],
        )


def test_the_third_revision_request_is_refused_and_leaves_the_plan_under_review(api):
    """
    The re-submit that precedes it succeeds and re-pins both goals; only the decision fails.

    "A `REQUEST_REVISION` decision on the technical branch is bounded: it may be issued only
    while `revision_round` is 1 or less, and a third revision request is refused with
    `ERR_PLAN_REVISION_LIMIT` (HTTP 409)."

    Design: Corner/errors/third_revision_request_is_refused_by_the_plan_revision_ceiling
    """
    world = _a_remedy_returned_twice(api)

    resubmitted = submit_plan(world)
    assert_fields(resubmitted, status="UNDER_TECHNICAL_REVIEW", revision_round=2)
    assert len(resubmitted["pinned_cleanup_goal_versions"]) == 2, (
        f"the re-submit must re-pin both goals: {resubmitted}"
    )

    refused = api.technical_review_plan(
        world.plan["id"],
        technical_review_payload(
            decision="REQUEST_REVISION", review_comment=THIRD_REVISION_COMMENT
        ),
        REVIEWER_ALPHA,
    )
    validate_error(refused, ERR_PLAN_REVISION_LIMIT, 409)

    assert_fields(
        world.read_plan(),
        status="UNDER_TECHNICAL_REVIEW",
        revision_round=2,
        public_comment_state="OPEN",
    )


# ─── completion_request_without_attained_goals_is_refused ─────────────────────────


def test_operating_controls_alone_do_not_earn_a_completion_review(api):
    """
    The remedy is in service and the parcel is unfrozen, but nothing has been demonstrated yet.

    "every cleanup goal on the site must have `attainment_status` `ATTAINED`, else
    `ERR_GOALS_NOT_ATTAINED`;"

    Design: Corner/errors/completion_request_without_attained_goals_is_refused
    """
    world = stage_implementation(api)
    assert_fields(world.read_control(), status="OPERATING")
    before = world.read_enrollment()
    assert_fields(before, status="IMPLEMENTATION")
    for goal in world.read_goals():
        assert_fields(goal, compliant_streak=0, attainment_status="NOT_ATTAINED")

    refused = api.request_completion(world.enrollment["id"], world.redev_headers)
    validate_error(refused, ERR_GOALS_NOT_ATTAINED, 422)

    assert_fields(
        world.read_enrollment(),
        status="IMPLEMENTATION",
        completion_requested_at=None,
        version=before["version"],
    )


# ─── certification_and_result_window_codes_are_triggerable ────────────────────────

ONE_DAY_BEFORE_COVERAGE = "2026-12-31"
INSIDE_COVERAGE = "2027-01-15"
INSIDE_COVERAGE_CLOCK = "2027-01-15T00:00:00Z"
FEBRUARY_RESULT_UGL = 100.0


def _an_approved_control_and_a_february_window(api):
    """A control whose coverage opens in 2027 and an event whose window opens in February."""
    world = stage_approved(api)
    event = add_event(world)
    set_clock(api, INSIDE_COVERAGE_CLOCK)
    return world, event


def test_a_certification_dated_one_day_before_coverage_is_refused(api):
    """
    The payload date is read against the coverage interval, and the same route then succeeds.

    "For any passing certification the parcel must not be `FROZEN`, and the
    `certification_date` must fall inside the control's `coverage_from` to `coverage_to`
    interval, inclusive at both ends — a date outside it is refused with
    `ERR_CERTIFICATION_OUTSIDE_COVERAGE`."

    Design: Corner/errors/certification_and_result_window_codes_are_triggerable
    """
    world, _event = _an_approved_control_and_a_february_window(api)

    refused = api.certify_control_operation(
        world.control["id"],
        operation_certification_payload(
            condition="PASS", certification_date=ONE_DAY_BEFORE_COVERAGE
        ),
        world.redev_headers,
    )
    validate_error(refused, ERR_CERTIFICATION_OUTSIDE_COVERAGE, 422)
    assert_fields(world.read_control(), status="APPROVED", last_certified_on=None)

    in_coverage = certify_control(
        world, condition="PASS", certification_date=INSIDE_COVERAGE
    )
    assert_fields(
        in_coverage, status="OPERATING", last_certified_on=INSIDE_COVERAGE
    )


def test_a_result_filed_before_its_window_opens_is_refused(api):
    """
    This one is read against the logical clock, not against anything in the payload.

    "The logical clock must have reached `window_start` — filing before the reserved window has
    opened is refused with `ERR_RESULTS_BEFORE_WINDOW`."

    Design: Corner/errors/certification_and_result_window_codes_are_triggerable
    """
    world, event = _an_approved_control_and_a_february_window(api)

    refused = api.file_monitoring_result(
        event["id"],
        sampling_result_payload(FEBRUARY_RESULT_UGL),
        world.consult_headers,
    )
    validate_error(refused, ERR_RESULTS_BEFORE_WINDOW, 422)

    unreported = get_success_data(
        api.get_monitoring_event(event["id"], REVIEWER_ALPHA)
    )
    assert_fields(
        unreported,
        status="SCHEDULED",
        result_status="PENDING",
        result_value_ugl=None,
    )
    assert_fields(world.read_goal(world.goal_restricted), compliant_streak=0)


# ─── unrestricted_closure_scope_requires_every_goal_unrestricted ───────────────────


def test_a_parcel_relying_on_a_credited_control_cannot_close_unrestricted(api):
    """
    Every other gate above this one is satisfied; only the goal basis stands in the way.

    "And a `requested_scope` of `UNRESTRICTED` requires that every cleanup goal on the parcel
    have `basis` `UNRESTRICTED` — a parcel closing on the strength of a credited control cannot
    be granted unrestricted closure, and the attempt is refused with
    `ERR_UNRESTRICTED_SCOPE_NOT_SUPPORTED`."

    Design: Corner/errors/unrestricted_closure_scope_requires_every_goal_unrestricted
    """
    world = stage_implementation(api)
    stage_all_goals_attained(world)
    world.enrollment = request_completion(world)
    world.letter = add_letter(world, requested_scope="UNRESTRICTED")

    assert_fields(world.read_site(), cleanup_posture="OPEN")
    assert_fields(world.read_enrollment(), status="COMPLETION_REVIEW")
    assert_fields(world.read_control(), status="OPERATING")
    assert_fields(world.read_goal(world.goal_restricted), basis="RESTRICTED")
    assert_fields(world.read_goal(world.goal_unrestricted), basis="UNRESTRICTED")

    refused = api.issue_nfa_letter(world.letter["id"], REVIEWER_BETA)
    validate_error(refused, ERR_UNRESTRICTED_SCOPE_NOT_SUPPORTED, 422)

    assert_fields(
        world.read_letter(),
        status="DRAFT",
        issued_on=None,
        issued_by_user_id=None,
        controls_certified_count=0,
    )
    assert_fields(world.read_enrollment(), status="COMPLETION_REVIEW")


# ─── post_quote_plan_edit_invalidates_the_attachment_point_at_bind ─────────────────

FIRST_PHASE_NARRATIVE = (
    "Phased excavation with sub-slab vapour mitigation; first phase only."
)
QUOTE_REFERENCE = "CCP-2743-B1"

AS_QUOTED_ESTIMATE = {
    "direct_cost_cents": 50000000,
    "escalation_cents": 6300000,
    "contingency_pct": "0.10",
    "contingency_cents": 5630000,
    "oversight_cents": 4000000,
    "total_cents": 65930000,
}
AS_QUOTED_PLACEMENT = {
    "underwriting_estimate_cents": 79625000,
    "attachment_point_cents": 87587500,
    "buffer_layer_cents": 7962500,
    "limit_cents": 30000000,
    "premium_cents": 2500000,
    "rate_applied": "0.055",
}
AFTER_THE_EDIT_ESTIMATE = {
    "direct_cost_cents": 100000000,
    "escalation_cents": 12600000,
    "contingency_pct": "0.10",
    "contingency_cents": 11260000,
    "oversight_cents": 4000000,
    "total_cents": 127860000,
}
DOUBLED_FOOTPRINT_COMMENT = "Expanded excavation footprint accepted."


def _a_quote_struck_before_the_footprint_doubled(api):
    """A quote priced on a 500-unit excavation line, then the line doubled and approved."""
    world = stage_enrolled(api)
    world.plan = add_plan(
        world,
        cost_lines=[cost_line("EXCAVATION_DISPOSAL", "SOIL", 500, 100000)],
        remedy_narrative=FIRST_PHASE_NARRATIVE,
    )
    world.control = add_control(world)
    stage_quote(world, policy_reference=QUOTE_REFERENCE)
    return world


def _the_edited_plan_carried_to_approval(world):
    """Double the excavation line, then take the plan through both branches to approval."""
    world.plan = get_success_data(
        world.api.patch_plan(
            world.plan["id"],
            {"cost_lines": [cost_line("EXCAVATION_DISPOSAL", "SOIL", 1000, 100000)]},
            world.consult_headers,
        )
    )
    submit_plan(world)
    technical_review(world, decision="PASS", review_comment=DOUBLED_FOOTPRINT_COMMENT)
    close_comment(world, public_comment_count=2)
    world.plan = approve_plan(world)
    return world


def test_the_quote_prices_itself_off_the_plan_as_it_stood(api):
    """
    A ten percent self-funded layer above the underwriting estimate, and the premium floor.

    "The attachment point is the underwriting estimate multiplied by 1.10, rounded half up to
    whole cents, and stored as `attachment_point_cents`;"

    Design: Corner/errors/post_quote_plan_edit_invalidates_the_attachment_point_at_bind
    """
    world = _a_quote_struck_before_the_footprint_doubled(api)

    assert_estimate_figures(world.read_plan(), AS_QUOTED_ESTIMATE)
    assert_placement_figures(world.policy, AS_QUOTED_PLACEMENT)
    assert_fields(world.read_policy(), status="QUOTED", bound_at=None)


def test_the_bind_retests_the_attachment_point_against_the_plan_as_it_now_stands(api):
    """
    The quote-time estimate would have bound; the current one does not.

    "the policy's `attachment_point_cents` must be greater than or equal to the plan's current
    `total_estimate_cents` multiplied by 1.05 and rounded half up — the self-funded buffer must
    still sit at least five percent above the design estimate, and a plan edited upward after the
    quote was struck will fail this test with `ERR_ATTACHMENT_POINT_TOO_LOW`;"

    Design: Corner/errors/post_quote_plan_edit_invalidates_the_attachment_point_at_bind
    """
    world = _a_quote_struck_before_the_footprint_doubled(api)
    _the_edited_plan_carried_to_approval(world)
    assert_estimate_figures(world.read_plan(), AFTER_THE_EDIT_ESTIMATE)

    refused = api.bind_policy(world.policy["id"], world.insurer_headers)
    validate_error(refused, ERR_ATTACHMENT_POINT_TOO_LOW, 422)

    assert_fields(
        world.read_policy(),
        status="QUOTED",
        bound_at=None,
        attachment_point_cents=AS_QUOTED_PLACEMENT["attachment_point_cents"],
    )
    assert_fields(
        world.read_plan(),
        total_funding_need_cents=AFTER_THE_EDIT_ESTIMATE["total_cents"],
    )
