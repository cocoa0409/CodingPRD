"""
Operations whose own state permits them but whose sibling entity does not.

In each pair below the target entity is sitting in a state that allows the trigger, and
the refusal comes entirely from another aggregate: an enrollment blocked by its parcel's
inquiry record, a closure letter blocked by an impaired control, and a control blocked by
the cleanup goal that credits it. Moving only the sibling makes the identical call pass.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ERR_CONTROL_STILL_REQUIRED,
    ERR_ENROLLMENT_NOT_ELIGIBLE,
    ERR_SITE_POSTURE_RESTRICTED,
    REVIEWER_ALPHA,
    REVIEWER_GAMMA,
    accept_letter,
    add_enrollment,
    add_event,
    add_letter,
    assert_fields,
    certify_control,
    decommission_payload,
    eligibility_decision_payload,
    file_result,
    issue_letter,
    request_completion,
    schedule_attainment_events,
    set_clock,
    stage_all_goals_attained,
    stage_approved,
    stage_bind,
    stage_control_operating,
    stage_implementation,
    stage_inquiry,
    stage_phase_i,
    stage_protection,
    stage_quote,
    stage_registry,
    stage_site,
    stage_two_awards_granted,
)

# ─── enrollment_decision_depends_on_protection_inquiry_state ────────────────────

DECISION_NOTE = "Track confirmed."


def _application_without_an_accepted_inquiry(api):
    """
    A screened parcel with an application pending and its inquiry never nominated.

    The protection record exists — so the guard is about the inquiry's state and not
    about a missing sibling — but no inquiry-completion call has been made.
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(world)
    world.enrollment = add_enrollment(world)
    return world


def _decide(world):
    """Ask the agency to accept the application onto the restricted-closure track."""
    return world.api.decide_eligibility(
        world.enrollment["id"],
        eligibility_decision_payload(decision="ENROLL", decision_note=DECISION_NOTE),
        REVIEWER_ALPHA,
    )


def test_the_application_is_refused_for_its_parcels_pending_inquiry(api):
    """
    Nothing about the enrollment is wrong; the sibling protection is not ready.

    "Accepting the application requires three things: the parcel's liability protection
    must exist and its `inquiry_state` must be `AAI_COMPLETE` — a cross-entity guard
    refused with `ERR_ENROLLMENT_NOT_ELIGIBLE` when the protection is missing or the
    inquiry is anything other than complete; the parcel must not be `FROZEN`; and a
    `RESTRICTED_CLOSURE` track additionally requires the parcel's
    `institutional_control_committed` to be true, refused with
    `ERR_CONTROL_COMMITMENT_MISSING` when it is false."

    Design: Difficulty/cross_entity_state_dependency/enrollment_decision_depends_on_protection_inquiry_state
    """
    world = _application_without_an_accepted_inquiry(api)
    assert_fields(world.read_protection(), inquiry_state="AAI_PENDING")

    response = _decide(world)
    validate_error(response, ERR_ENROLLMENT_NOT_ELIGIBLE, 422)

    assert_fields(
        world.read_enrollment(),
        status="ELIGIBILITY_REVIEW",
        enrolled_on=None,
        eligibility_decided_by_user_id=None,
    )


def test_only_the_sibling_protection_moves_between_the_two_attempts(api):
    """
    The inquiry acceptance changes the protection and leaves the application alone.

    "On acceptance the server stores `aai_phase_id` and `aai_report_date`, derives
    `aai_expires_on` as the `aai_report_date` advanced by 365 days, recomputes
    `bfpp_status`, and increments the protection's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/enrollment_decision_depends_on_protection_inquiry_state
    """
    world = _application_without_an_accepted_inquiry(api)
    _decide(world)

    stage_inquiry(world)
    assert_fields(
        world.read_protection(),
        inquiry_state="AAI_COMPLETE",
        aai_report_date="2026-07-20",
        aai_expires_on="2027-07-20",
        bfpp_status="NOT_ESTABLISHED",
    )
    assert_fields(
        world.read_enrollment(),
        status="ELIGIBILITY_REVIEW",
        enrolled_on=None,
        eligibility_decided_by_user_id=None,
    )


def test_the_identical_decision_then_accepts_the_application(api):
    """
    Replayed unchanged, the decision now lands on the day the clock is standing on.

    "Acceptance moves the enrollment `ELIGIBILITY_REVIEW → ENROLLED`, sets `enrolled_on`
    from the logical clock's date, records `eligibility_decided_by_user_id`, and increments
    the enrollment's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/enrollment_decision_depends_on_protection_inquiry_state
    """
    world = _application_without_an_accepted_inquiry(api)
    _decide(world)
    stage_inquiry(world)

    accepted = get_success_data(_decide(world))
    assert_fields(
        accepted,
        status="ENROLLED",
        enrolled_on="2026-08-01",
        eligibility_decided_by_user_id="reviewer-alpha",
    )
    assert_fields(
        world.read_site(),
        cleanup_posture="OPEN",
        institutional_control_committed=True,
    )


# ─── letter_reissue_depends_on_impaired_control_returning_to_operating ───────────

LENDER_REFERENCE = "LN-2743-77"


def _revoked_letter_beside_an_impaired_control(api):
    """
    A closed file undone by one exceeding result: letter revoked, control impaired.

    The revocation reason is the curable one, so the letter's own state permits
    re-issuance from the moment the cascade lands.
    """
    world = stage_approved(api)
    stage_quote(world)
    stage_bind(world)
    stage_control_operating(world)
    stage_all_goals_attained(world)
    world.enrollment = request_completion(world)
    world.letter = add_letter(world)
    world.letter = issue_letter(world, headers=REVIEWER_GAMMA)
    world.letter = accept_letter(world, lender_reference=LENDER_REFERENCE)
    stage_two_awards_granted(world)

    set_clock(world.api, "2027-08-06T00:00:00Z")
    event = add_event(
        world,
        cleanup_goal_id=world.goal_restricted["id"],
        site_control_id=world.control["id"],
        monitoring_period_code="2027-M08",
        sample_date="2027-08-05",
        window_start="2027-08-01T00:00:00Z",
        window_end="2027-08-15T00:00:00Z",
    )
    file_result(world, event, 900.0)
    return world


def _reissue(world):
    """Ask a reviewer other than the approving one to re-issue the letter."""
    return world.api.issue_nfa_letter(world.letter["id"], REVIEWER_GAMMA)


def _cure_the_control(world):
    """One passing re-certification inside the coverage interval."""
    set_clock(world.api, "2027-08-07T00:00:00Z")
    return certify_control(world, condition="PASS", certification_date="2027-08-07")


def test_the_reissue_is_refused_while_the_control_is_impaired(api):
    """
    The letter is curable but the parcel is not open, and issuance is closure-critical.

    "A `RESTRICTED` parcel still permits ordinary work but refuses the four
    closure-critical operations that require the parcel to be fully `OPEN` — a completion
    request on an enrollment, issuance of a closure letter, lender acceptance of a closure
    letter, and a funding decision of `AWARD`."

    Design: Difficulty/cross_entity_state_dependency/letter_reissue_depends_on_impaired_control_returning_to_operating
    """
    world = _revoked_letter_beside_an_impaired_control(api)
    assert_fields(world.read_control(), status="IMPAIRED")
    assert_fields(world.read_site(), cleanup_posture="RESTRICTED", impaired_control_count=1)

    response = _reissue(world)
    validate_error(response, ERR_SITE_POSTURE_RESTRICTED, 409)

    assert_fields(
        world.read_letter(),
        status="REVOKED",
        revocation_reason="CONTROL_FAILURE",
        reissue_count=0,
    )


def test_curing_the_control_returns_the_parcel_to_open(api):
    """
    A single passing inspection empties the impaired count and reopens the parcel.

    "A pass arriving from `IMPAIRED` additionally clears `impaired_since`, decrements the
    parcel's `impaired_control_count`, and — when that count reaches zero and the parcel's
    `bfpp_status` is not `FORFEITED` — returns `cleanup_posture` to `OPEN`; the site's
    `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/letter_reissue_depends_on_impaired_control_returning_to_operating
    """
    world = _revoked_letter_beside_an_impaired_control(api)
    _reissue(world)

    cured = _cure_the_control(world)
    assert_fields(
        cured,
        status="OPERATING",
        impaired_since=None,
        impairment_count=1,
        last_certified_on="2027-08-07",
        next_certification_due_on="2027-11-05",
    )
    assert_fields(world.read_site(), cleanup_posture="OPEN", impaired_control_count=0)


def test_the_identical_reissue_then_succeeds_without_restoring_reliance(api):
    """
    Replayed unchanged the letter re-issues, and the lender has to come back.

    "Re-issuance increments `reissue_count` by 1, refreshes `issued_on` and
    `issued_by_user_id`, clears `revocation_reason`, and increments the letter's `version`
    by 1."

    Design: Difficulty/cross_entity_state_dependency/letter_reissue_depends_on_impaired_control_returning_to_operating
    """
    world = _revoked_letter_beside_an_impaired_control(api)
    _reissue(world)
    _cure_the_control(world)

    reissued = get_success_data(_reissue(world))
    assert_fields(
        reissued,
        status="ISSUED",
        reissue_count=1,
        revocation_reason=None,
        issued_on="2027-08-07",
        issued_by_user_id="reviewer-gamma",
        accepted_by_lender_user_id="lender-1",
        lender_reference=LENDER_REFERENCE,
    )
    for award in world.awards:
        assert_fields(world.read_award(award), status="RESCINDED", allocated_cents=0)


# ─── control_decommission_depends_on_credited_goal_attainment ────────────────────

DECOMMISSION_NOTE = "Slab depressurisation no longer required."
CREDITED_RESULTS = (240.0, 250.0, 245.0)
FINAL_RESULT = 200.0


def _operating_control_with_three_of_four_quarters(api):
    """
    A control in service whose credited goal is one quarter short of attainment.

    No closure letter exists, so the other half of the retirement guard cannot be what
    refuses the call.
    """
    world = stage_implementation(api)
    events = schedule_attainment_events(world, world.goal_restricted)
    set_clock(world.api, "2027-06-01T00:00:00Z")
    for event, value in zip(events, CREDITED_RESULTS):
        file_result(world, event, value)
    return world, events


def _decommission(world):
    """Ask the agency to retire the control."""
    return world.api.decommission_control(
        world.control["id"],
        REVIEWER_ALPHA,
        decommission_payload(decommission_note=DECOMMISSION_NOTE),
    )


def test_the_control_may_not_retire_while_its_credited_goal_is_unattained(api):
    """
    The control is retirable on its own status; the goal that credits it is not ready.

    "Two substantive conditions guard the action: every cleanup goal on the parcel whose
    `control_credit_type` equals this control's `control_type` must have
    `attainment_status` `ATTAINED`, and no closure letter on the parcel may be in
    `ACCEPTED_BY_LENDER` with a `requested_scope` of `RESTRICTED_WITH_CONTROLS`."

    Design: Difficulty/cross_entity_state_dependency/control_decommission_depends_on_credited_goal_attainment
    """
    world, _events = _operating_control_with_three_of_four_quarters(api)
    assert_fields(world.read_control(), status="OPERATING", control_type="VAPOR_MITIGATION")
    assert_fields(
        world.read_goal(world.goal_restricted),
        compliant_streak=3,
        attainment_status="NOT_ATTAINED",
        control_credit_type="VAPOR_MITIGATION",
    )

    response = _decommission(world)
    validate_error(response, ERR_CONTROL_STILL_REQUIRED, 422)
    assert_fields(world.read_control(), status="OPERATING")


def test_the_fourth_result_attains_the_credited_goal(api):
    """
    Only the sibling goal moves, and it moves on the strength of its fourth quarter.

    "The final value of that running count is stored as `compliant_streak`, and
    `attainment_status` becomes `ATTAINED` when `compliant_streak` is at least 4 — four
    consecutive compliant sampling results — and `NOT_ATTAINED` otherwise."

    Design: Difficulty/cross_entity_state_dependency/control_decommission_depends_on_credited_goal_attainment
    """
    world, events = _operating_control_with_three_of_four_quarters(api)
    _decommission(world)

    file_result(world, events[3], FINAL_RESULT)
    assert_fields(
        world.read_goal(world.goal_restricted),
        compliant_streak=4,
        attainment_status="ATTAINED",
    )
    assert_fields(world.read_control(), status="OPERATING")


def test_the_identical_retirement_then_succeeds(api):
    """
    Replayed unchanged the control retires, and the uncredited goal never mattered.

    "Retirement sets the `status` to the terminal `DECOMMISSIONED` and increments the
    control's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/control_decommission_depends_on_credited_goal_attainment
    """
    world, events = _operating_control_with_three_of_four_quarters(api)
    _decommission(world)
    file_result(world, events[3], FINAL_RESULT)

    retired = get_success_data(_decommission(world))
    assert_fields(retired, status="DECOMMISSIONED")

    assert_fields(
        world.read_goal(world.goal_unrestricted),
        attainment_status="NOT_ATTAINED",
        basis="UNRESTRICTED",
        control_credit_type=None,
    )
    assert_fields(world.read_site(), impaired_control_count=0, cleanup_posture="OPEN")
