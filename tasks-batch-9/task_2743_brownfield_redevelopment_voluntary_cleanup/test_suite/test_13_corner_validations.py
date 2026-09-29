"""
Which rule speaks when a request is wrong in more than one way.

Every case here loads a single request with two or more genuine defects and pins the one
the caller is told about: a blank identity ahead of a malformed body, a role refusal ahead
of a missing field, a bad enum ahead of a missing parcel, a path identifier ahead of a body
reference, and — further down the ladder — a frozen or restricted parcel ahead of whatever
state the target child happens to be in, and a documentation gap ahead of the arithmetic
that would have found no money to spend.
"""

from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    CLOCK_EPOCH,
    ERR_CERTIFICATION_WINDOW_CLOSED,
    ERR_FORBIDDEN_ROLE,
    ERR_FUNDING_NEED_UNDETERMINED,
    ERR_INVALID_REQUEST,
    ERR_LAB_NOT_FOUND,
    ERR_MISSING_ELIGIBILITY_DOCUMENT,
    ERR_NO_ELIGIBLE_COST_BASE,
    ERR_PARTY_TYPE_MISMATCH,
    ERR_PROTECTION_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SITE_FROZEN,
    ERR_SITE_NOT_FOUND,
    ERR_SITE_POSTURE_RESTRICTED,
    ERR_UNAUTHENTICATED,
    PROGRAM_ADMIN,
    REVIEWER_ALPHA,
    REVIEWER_ALPHA_USER_ID,
    REVIEWER_BETA,
    ROLE_REDEVELOPER,
    add_award,
    add_event,
    add_letter,
    add_site,
    assert_fields,
    assert_funding_conservation,
    assert_instant,
    assert_number,
    assert_pagination_meta,
    certify_control,
    certify_obligation,
    cleanup_goal_payload,
    file_result,
    funding_decision_payload,
    impose_obligation,
    inquiry_completion_payload,
    make_redeveloper_headers,
    monitoring_event_payload,
    redeveloper_payload,
    request_completion,
    run_sweep,
    set_clock,
    site_payload,
    stage_acquisition,
    stage_all_goals_attained,
    stage_approved,
    stage_assessed,
    stage_control_operating,
    stage_inquiry,
    stage_phase_i,
    stage_protection,
    stage_registry,
    stage_site,
    void_payload,
)

UNKNOWN_SITE_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_PROTECTION_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_PHASE_ID = "00000000-0000-4000-8000-0000000000bb"
UNKNOWN_LAB_ID = "00000000-0000-4000-8000-0000000000cc"
UNKNOWN_GOAL_ID = "00000000-0000-4000-8000-0000000000dd"


def _one_registered_owner(api):
    """The clock at its starting instant and a single redeveloper on the register."""
    set_clock(api, CLOCK_EPOCH)
    return get_success_data(api.create_party(redeveloper_payload(), PROGRAM_ADMIN), 201)


# ─── request_missing_x_user_id_returns_unauthenticated_before_not_found ──────────


def test_a_blank_user_id_is_reported_before_the_body_or_the_path_is_examined(api):
    """
    Three defects in one request, and only the identity one is mentioned.

    "1. **Header presence** — both auth headers present and non-blank, else
    `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/request_missing_x_user_id_returns_unauthenticated_before_not_found
    """
    owner = _one_registered_owner(api)
    assert owner["id"], "the owner must exist so only the header is at fault"

    response = api.derive_cleanup_goal(
        UNKNOWN_SITE_ID,
        cleanup_goal_payload(
            contaminant_code="TCE",
            media="PLASMA",
            screening_level_ugl=-3.0,
            basis="UNRESTRICTED",
        ),
        build_user_headers("", ROLE_REDEVELOPER),
    )
    validate_error(response, ERR_UNAUTHENTICATED, 401)


# ─── wrong_role_returns_forbidden_role_before_invalid_request ────────────────────


def test_the_role_check_is_reported_before_the_shape_of_the_body(api):
    """
    A redeveloper may not register organisations, so its malformed payload is never read.

    "2. **Role authorisation** — the acting `X-User-Role` appears in the endpoint's role
    list, else `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/wrong_role_returns_forbidden_role_before_invalid_request
    """
    owner = _one_registered_owner(api)

    response = api.create_party(
        {"party_type": "MUNICIPALITY", "state_code": "Ohio"},
        make_redeveloper_headers(owner["id"]),
    )
    validate_error(response, ERR_FORBIDDEN_ROLE, 403)

    _rows, meta = validate_paginated(api.list_parties(PROGRAM_ADMIN))
    assert_pagination_meta(meta, expected_total=1)


# ─── malformed_enum_returns_invalid_request_before_site_not_found ────────────────


def test_an_unrecognised_media_is_reported_before_the_unknown_parcel(api):
    """
    Both rules are reachable on the same URL; the shape check simply gets there first.

    "Two requests that are each wrong in three ways therefore report only their earliest
    failure, and a test that expects a business error can be masked by an earlier structural
    one."

    Design: Corner/validations/malformed_enum_returns_invalid_request_before_site_not_found
    """
    world = stage_registry(api)

    malformed = api.derive_cleanup_goal(
        UNKNOWN_SITE_ID,
        cleanup_goal_payload(
            contaminant_code="TCE",
            media="PLASMA",
            screening_level_ugl=5.0,
            basis="UNRESTRICTED",
        ),
        world.redev_headers,
    )
    validate_error(malformed, ERR_INVALID_REQUEST, 422)

    well_formed = api.derive_cleanup_goal(
        UNKNOWN_SITE_ID,
        cleanup_goal_payload(
            contaminant_code="TCE",
            media="SOIL_VAPOR",
            screening_level_ugl=5.0,
            basis="UNRESTRICTED",
        ),
        world.redev_headers,
    )
    validate_error(well_formed, ERR_SITE_NOT_FOUND, 404)


# ─── unknown_path_id_returns_protection_not_found_before_body_fk ─────────────────


def test_the_path_protection_is_resolved_before_the_phase_named_in_the_body(api):
    """
    Two unminted identifiers in one call, and the URL's is the one reported.

    "Foreign keys supplied in a request body are resolved after every path identifier, and
    among themselves in a fixed order: `site_id` first, then `vcp_enrollment_id`, then
    `remedial_action_plan_id`, then the party references (`owner_party_id`,
    `consultant_party_id`, `insurer_party_id`), then `laboratory_id`, then `cleanup_goal_id`,
    then `site_control_id`, and finally the assessment-phase references `aai_phase_id` and
    `basis_assessment_phase_id`."

    Design: Corner/validations/unknown_path_id_returns_protection_not_found_before_body_fk
    """
    world = stage_registry(api)
    stage_site(world)

    response = api.complete_inquiry(
        UNKNOWN_PROTECTION_ID,
        inquiry_completion_payload(UNKNOWN_PHASE_ID),
        world.consult_headers,
    )
    validate_error(response, ERR_PROTECTION_NOT_FOUND, 404)


# ─── multiple_unknown_body_fks_return_site_not_found_first ───────────────────────


def test_the_parcel_reference_is_reported_ahead_of_the_laboratory_reference(api):
    """
    Three unresolvable body references, then two: each time the earliest one answers.

    "The first unresolvable reference determines the 404 code returned."

    Design: Corner/validations/multiple_unknown_body_fks_return_site_not_found_first
    """
    world = stage_registry(api)
    stage_site(world)

    all_three_unknown = api.create_monitoring_event(
        monitoring_event_payload(UNKNOWN_SITE_ID, UNKNOWN_LAB_ID, UNKNOWN_GOAL_ID),
        world.consult_headers,
    )
    validate_error(all_three_unknown, ERR_SITE_NOT_FOUND, 404)

    lab_and_goal_unknown = api.create_monitoring_event(
        monitoring_event_payload(world.site["id"], UNKNOWN_LAB_ID, UNKNOWN_GOAL_ID),
        world.consult_headers,
    )
    validate_error(lab_and_goal_unknown, ERR_LAB_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_monitoring_events(world.consult_headers, site_id=world.site["id"])
    )
    assert_pagination_meta(meta, expected_total=0)


# ─── site_owner_party_must_be_a_redeveloper ─────────────────────────────────────


def test_a_parcel_may_only_be_registered_against_a_redeveloper_party(api):
    """
    The owner slot is typed, and a consultant in it is a typing failure, not a shape one.

    "If the referenced owner party is not a `REDEVELOPER`, registration is refused with
    `ERR_PARTY_TYPE_MISMATCH`."

    Design: Corner/validations/site_owner_party_must_be_a_redeveloper
    """
    world = stage_registry(api)
    payload = site_payload(
        world.consultant["id"],
        site_name="Wrong Owner Parcel",
        county_code="OH-049",
        acreage=2.0,
        intended_reuse="COMMERCIAL",
        planned_acquisition_date="2026-11-15",
    )

    # Ownership (priority 6) is checked before party typing (priority 8), so the
    # acting X-User-ID must be the very party sitting in the owner slot; only then
    # is the typing rule the earliest rule this request violates.
    wrong_type = api.create_site(
        payload, make_redeveloper_headers(world.consultant["id"])
    )
    validate_error(wrong_type, ERR_PARTY_TYPE_MISMATCH, 422)

    payload["owner_party_id"] = world.redeveloper["id"]
    accepted = get_success_data(api.create_site(payload, world.redev_headers), 201)
    assert_fields(
        accepted,
        owner_party_id=world.redeveloper["id"],
        site_name="Wrong Owner Parcel",
        intended_reuse="COMMERCIAL",
    )


# ─── void_certification_by_the_imposing_reviewer_rejected ────────────────────────

CRITICAL_DUTY_DESCRIPTION = "Maintain fencing, signage and stormwater controls."
CRITICAL_DUTY_DUE_DATE = "2027-03-01"
ADVANCED_DUE_DATE = "2027-05-30"
VOID_REASON = "Inspection log did not support the filed certification."


def _a_certified_duty_on_an_established_defence(api):
    """
    A closed acquisition, a complete inquiry, one imposed duty and one certification.

    The duty is imposed by the first opaque reviewer, so that reviewer is precisely the one
    barred from voiding the certification the owner then files.
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(world)
    stage_inquiry(world)
    stage_acquisition(world)
    world.duty = impose_obligation(
        world,
        obligation_category="REASONABLE_STEPS",
        description=CRITICAL_DUTY_DESCRIPTION,
        due_date=CRITICAL_DUTY_DUE_DATE,
        recurrence_days=90,
    )
    world.certified = certify_obligation(world, world.duty)
    return world


def test_the_reviewer_who_imposed_the_duty_may_not_void_its_certification(api):
    """
    The compensating action is refused, and the closed period stays closed.

    "The reviewer who voids a certification must not be the reviewer who imposed the duty in
    the first place: the acting `X-User-ID` must differ from the obligation's
    `imposed_by_user_id`."

    Design: Corner/validations/void_certification_by_the_imposing_reviewer_rejected
    """
    world = _a_certified_duty_on_an_established_defence(api)
    assert_fields(
        world.certified,
        status="SATISFIED",
        certification_count=1,
        prior_due_date=CRITICAL_DUTY_DUE_DATE,
        due_date=ADVANCED_DUE_DATE,
        imposed_by_user_id=REVIEWER_ALPHA_USER_ID,
    )

    refused = api.void_certification(
        world.duty["id"], REVIEWER_ALPHA, void_payload(void_reason=VOID_REASON)
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    assert_fields(
        world.read_obligation(world.duty),
        status="SATISFIED",
        certification_count=1,
        prior_due_date=CRITICAL_DUTY_DUE_DATE,
        due_date=ADVANCED_DUE_DATE,
    )


def test_a_second_reviewer_voids_it_and_the_duty_lands_back_in_current(api):
    """
    The restored deadline is months away, so the duty returns to the unwarned state.

    "Which state the duty lands in depends on how much of the restored period remains against
    the logical clock: if the restored `due_date` is more than 30 days in the future the duty
    returns to `CURRENT`; if it is between 0 and 30 days in the future inclusive — inside the
    grace window — the duty returns to `AT_RISK` instead."

    Design: Corner/validations/void_certification_by_the_imposing_reviewer_rejected
    """
    world = _a_certified_duty_on_an_established_defence(api)

    voided = get_success_data(
        api.void_certification(
            world.duty["id"], REVIEWER_BETA, void_payload(void_reason=VOID_REASON)
        )
    )
    assert_fields(
        voided,
        status="CURRENT",
        due_date=CRITICAL_DUTY_DUE_DATE,
        prior_due_date=None,
        certified_at=None,
        certification_count=0,
        version=world.certified["version"] + 1,
    )

    protection = world.read_protection()
    assert_fields(
        protection,
        obligation_state="CURRENT",
        obligations_total_weight=5,
        current_weight=5,
        satisfied_weight=0,
        at_risk_weight=0,
        lapsed_weight=0,
        bfpp_status="ESTABLISHED",
    )
    assert_number(protection["compliance_pct"], "1.0000", "compliance_pct")


# ─── cleanup_goal_control_credit_type_is_conditionally_required ──────────────────


def test_the_control_credit_pairing_is_enforced_in_both_directions(api):
    """
    A restricted goal without a credited control, and an unrestricted goal with one.

    "Where `basis` is `RESTRICTED`, a `control_credit_type` naming the control whose exposure
    interruption is credited is required; where `basis` is `UNRESTRICTED`,
    `control_credit_type` must be absent and defaults to null."

    Design: Corner/validations/cleanup_goal_control_credit_type_is_conditionally_required
    """
    world = stage_assessed(api)

    restricted_without_credit = cleanup_goal_payload(
        contaminant_code="TCE", media="SOIL_VAPOR", screening_level_ugl=5.0, basis="RESTRICTED"
    )
    restricted_without_credit.pop("control_credit_type")
    missing = api.derive_cleanup_goal(
        world.site["id"], restricted_without_credit, world.redev_headers
    )
    validate_error(missing, ERR_INVALID_REQUEST, 422)

    surplus = api.derive_cleanup_goal(
        world.site["id"],
        cleanup_goal_payload(
            contaminant_code="TCE",
            media="SOIL_VAPOR",
            screening_level_ugl=5.0,
            basis="UNRESTRICTED",
            control_credit_type="VAPOR_MITIGATION",
        ),
        world.redev_headers,
    )
    validate_error(surplus, ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(
        api.list_cleanup_goals(world.site["id"], world.consult_headers)
    )
    assert_pagination_meta(meta, expected_total=0)


def test_the_two_legal_pairings_each_derive_their_own_target(api):
    """
    With the pairing honoured, the credited basis lands on the shared budget and the other does not.

    "An `UNRESTRICTED` goal pins the scenario multiplier at 1.0 and forgoes any control
    credit, so it produces the strictest of the two targets and needs no control to be built."

    Design: Corner/validations/cleanup_goal_control_credit_type_is_conditionally_required
    """
    world = stage_assessed(api)

    restricted = get_success_data(
        api.derive_cleanup_goal(
            world.site["id"],
            cleanup_goal_payload(
                contaminant_code="TCE",
                media="SOIL_VAPOR",
                screening_level_ugl=5.0,
                basis="RESTRICTED",
                control_credit_type="VAPOR_MITIGATION",
            ),
            world.redev_headers,
        ),
        201,
    )
    assert_fields(
        restricted,
        basis="RESTRICTED",
        control_credit_type="VAPOR_MITIGATION",
        cumulative_cap_applied=True,
    )
    assert_number(restricted["goal_ugl"], "250.00", "goal_ugl")

    unrestricted = get_success_data(
        api.derive_cleanup_goal(
            world.site["id"],
            cleanup_goal_payload(
                contaminant_code="PCE",
                media="SOIL_VAPOR",
                screening_level_ugl=5.0,
                basis="UNRESTRICTED",
            ),
            world.redev_headers,
        ),
        201,
    )
    assert_fields(
        unrestricted,
        basis="UNRESTRICTED",
        control_credit_type=None,
        cumulative_cap_applied=False,
    )
    assert_number(unrestricted["goal_ugl"], "166.67", "goal_ugl")

    _rows, meta = validate_paginated(
        api.list_cleanup_goals(world.site["id"], world.consult_headers)
    )
    assert_pagination_meta(meta, expected_total=2)


# ─── restricted_posture_outranks_both_the_control_and_enrollment_state_gates ─────

FAILED_INSPECTION_DATE = "2027-06-01"


def _a_closure_request_undone_by_a_failed_inspection(api):
    """
    A parcel one signature from closure, then knocked back by a failing inspection.

    Both goals are demonstrated and the completion review is open with a draft letter on
    file, so the three guards on issuance — posture, enrollment state and control operation
    — are all violated at once by the single failing certification that follows.
    """
    world = stage_approved(api)
    stage_control_operating(world)
    stage_all_goals_attained(world)
    request_completion(world)
    world.letter = add_letter(world)
    world.failed = certify_control(
        world, condition="FAIL", certification_date=FAILED_INSPECTION_DATE
    )
    return world


def test_the_failed_inspection_restricts_the_parcel_and_reopens_the_implementation(api):
    """
    One verdict moves the control, the parcel and the enrollment in the same request.

    "It then cascades: the parcel's `impaired_control_count` increments and its
    `cleanup_posture` becomes `RESTRICTED` unless the parcel is already `FROZEN`, in which
    case forfeiture continues to dominate; and, at the next level down, an enrollment sitting
    in `COMPLETION_REVIEW` whose approved plan owns this control is pushed back to
    `IMPLEMENTATION` with its `reverted_completion_count` incremented by 1."

    Design: Corner/validations/restricted_posture_outranks_both_the_control_and_enrollment_state_gates
    """
    world = _a_closure_request_undone_by_a_failed_inspection(api)

    assert_fields(
        world.failed,
        status="IMPAIRED",
        impairment_count=1,
        impaired_since=FAILED_INSPECTION_DATE,
    )
    assert_fields(world.read_site(), cleanup_posture="RESTRICTED", impaired_control_count=1)
    assert_fields(
        world.read_enrollment(), status="IMPLEMENTATION", reverted_completion_count=1
    )


def test_the_posture_gate_answers_ahead_of_the_enrollment_and_control_gates(api):
    """
    Three guards fail at once and the earliest one is the only one reported.

    "Validations are evaluated in ascending priority order, and evaluation stops at the first
    violation: the first rule violated determines the response, and no later rule is even
    considered."

    Design: Corner/validations/restricted_posture_outranks_both_the_control_and_enrollment_state_gates
    """
    world = _a_closure_request_undone_by_a_failed_inspection(api)

    refused = api.issue_nfa_letter(world.letter["id"], REVIEWER_BETA)
    validate_error(refused, ERR_SITE_POSTURE_RESTRICTED, 409)

    assert_fields(
        world.read_letter(),
        status="DRAFT",
        requested_scope="RESTRICTED_WITH_CONTROLS",
        issued_on=None,
        issued_by_user_id=None,
        controls_certified_count=0,
        reissue_count=0,
    )


# ─── frozen_site_refuses_child_mutations_but_still_accepts_the_sweep ─────────────

FROZEN_DUTY_DUE_DATE = "2027-03-01"
FIRST_EVENT_CODE = "2027-M02"
FIRST_EVENT_SAMPLE_DATE = "2027-02-05"
FIRST_EVENT_WINDOW = ("2027-02-01T00:00:00Z", "2027-02-10T00:00:00Z")
FAILING_RESULT = 900.0

FORFEITING_SWEEP_DATE = "2027-03-02"
SECOND_SWEEP_DATE = "2027-03-03"

LATER_EVENT_CODE = "2027-M04"
LATER_EVENT_SAMPLE_DATE = "2027-04-05"
LATER_EVENT_WINDOW = ("2027-04-01T00:00:00Z", "2027-04-10T00:00:00Z")


def _a_frozen_parcel(api):
    """
    A parcel whose defence has been forfeited by a lapsed defence-critical duty.

    The exceeding sample impairs the control first, so the parcel is already `RESTRICTED`
    when the sweep lapses the duty — which is what makes the forfeiture, not the impairment,
    the posture that answers afterwards.
    """
    world = stage_approved(api)
    stage_control_operating(world)
    world.duty = impose_obligation(
        world,
        obligation_category="REASONABLE_STEPS",
        description=CRITICAL_DUTY_DESCRIPTION,
        due_date=FROZEN_DUTY_DUE_DATE,
        recurrence_days=90,
    )
    event = add_event(
        world,
        cleanup_goal_id=world.goal_restricted["id"],
        site_control_id=world.control["id"],
        monitoring_period_code=FIRST_EVENT_CODE,
        sample_date=FIRST_EVENT_SAMPLE_DATE,
        window_start=FIRST_EVENT_WINDOW[0],
        window_end=FIRST_EVENT_WINDOW[1],
    )
    set_clock(world.api, "2027-02-06T00:00:00Z")
    file_result(world, event, FAILING_RESULT)
    set_clock(world.api, "2027-03-02T00:00:00Z")
    run_sweep(world, FORFEITING_SWEEP_DATE, site_id=world.site["id"])
    return world


def test_the_frozen_parcel_refuses_a_new_monitoring_event(api):
    """
    An ordinary child create on a frozen parcel is refused outright.

    "A `FROZEN` parcel refuses **every** mutating endpoint scoped to that site, with exactly
    three exemptions: the compliance sweep, the void-certification compensating action, and
    the logical-clock endpoint."

    Design: Corner/validations/frozen_site_refuses_child_mutations_but_still_accepts_the_sweep
    """
    world = _a_frozen_parcel(api)
    assert_fields(world.read_site(), cleanup_posture="FROZEN", impaired_control_count=1)

    refused = api.create_monitoring_event(
        monitoring_event_payload(
            world.site["id"],
            world.laboratory["id"],
            world.goal_unrestricted["id"],
            monitoring_period_code=LATER_EVENT_CODE,
            sample_date=LATER_EVENT_SAMPLE_DATE,
            window_start=LATER_EVENT_WINDOW[0],
            window_end=LATER_EVENT_WINDOW[1],
        ),
        world.consult_headers,
    )
    validate_error(refused, ERR_SITE_FROZEN, 409)

    _rows, meta = validate_paginated(
        api.list_monitoring_events(world.consult_headers, site_id=world.site["id"])
    )
    assert_pagination_meta(meta, expected_total=1)


def test_the_frozen_parcel_still_accepts_the_sweep_and_the_clock(api):
    """
    The two exempt operations keep working, and the second sweep finds nothing left to lapse.

    "The sweep takes an `as_of_date` and an optional `site_id` to narrow it to one parcel, and
    it is one of the three operations that runs even on a `FROZEN` parcel — indeed running it
    on frozen parcels is the point, since forfeiture is exactly what it detects."

    Design: Corner/validations/frozen_site_refuses_child_mutations_but_still_accepts_the_sweep
    """
    world = _a_frozen_parcel(api)

    assert (
        set_clock(api, "2027-03-03T00:00:00Z") == "2027-03-03T00:00:00Z"
    ), "the logical clock is exempt from the frozen gate"

    again = run_sweep(world, SECOND_SWEEP_DATE, site_id=world.site["id"])
    assert_fields(again, lapsed_count=0)

    assert_fields(world.read_obligation(world.duty), status="LAPSED")
    assert_fields(world.read_site(), cleanup_posture="FROZEN")


# ─── certify_after_the_due_date_returns_certification_window_closed ──────────────

ON_TIME_CLOCK = "2027-03-01T00:00:00Z"
ONE_DAY_LATE_CLOCK = "2027-03-02T00:00:00Z"


def _an_imposed_duty_awaiting_certification(api):
    """One defence-critical duty on an acquired parcel, deadline at the start of March."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(world)
    stage_inquiry(world)
    stage_acquisition(world)
    world.duty = impose_obligation(
        world,
        obligation_category="REASONABLE_STEPS",
        description=CRITICAL_DUTY_DESCRIPTION,
        due_date=CRITICAL_DUTY_DUE_DATE,
        recurrence_days=90,
    )
    return world


def test_certifying_on_the_due_date_itself_is_accepted(api):
    """
    The window is inclusive of its last day, and the period rolls forward from there.

    "Certification is available from `CURRENT` and from `AT_RISK`, and both source states
    produce the identical effect set: the current `due_date` is copied into `prior_due_date`,
    then `due_date` is advanced by `recurrence_days`; `certified_at` is set from the logical
    clock; `certification_count` increments by 1; the duty's `status` becomes `SATISFIED`; the
    protection's four weight buckets and `compliance_pct` are recomputed; and both the duty's
    `version` and the protection's `version` increment by 1."

    Design: Corner/validations/certify_after_the_due_date_returns_certification_window_closed
    """
    world = _an_imposed_duty_awaiting_certification(api)
    set_clock(api, ON_TIME_CLOCK)

    certified = certify_obligation(world, world.duty)
    assert_fields(
        certified,
        status="SATISFIED",
        prior_due_date=CRITICAL_DUTY_DUE_DATE,
        due_date=ADVANCED_DUE_DATE,
        certification_count=1,
        version=world.duty["version"] + 1,
    )
    assert_instant(certified["certified_at"], ON_TIME_CLOCK, "certified_at")


def test_certifying_the_day_after_the_deadline_is_refused(api):
    """
    One day past the deadline the period is closed and nothing about the duty moves.

    "Three conditions apply: the acting `X-User-ID` must equal the site's `owner_party_id`,
    the parcel must not be `FROZEN`, and the logical clock's current date must be on or before
    the duty's `due_date` — certifying after the period has closed is
    `ERR_CERTIFICATION_WINDOW_CLOSED`."

    Design: Corner/validations/certify_after_the_due_date_returns_certification_window_closed
    """
    world = _an_imposed_duty_awaiting_certification(api)
    set_clock(api, ONE_DAY_LATE_CLOCK)

    refused = api.certify_obligation(world.duty["id"], world.redev_headers)
    validate_error(refused, ERR_CERTIFICATION_WINDOW_CLOSED, 422)

    assert_fields(
        world.read_obligation(world.duty),
        status="CURRENT",
        due_date=CRITICAL_DUTY_DUE_DATE,
        prior_due_date=None,
        certified_at=None,
        certification_count=0,
        version=world.duty["version"],
    )
    protection = world.read_protection()
    assert_fields(protection, current_weight=5, satisfied_weight=0)
    assert_number(protection["compliance_pct"], "1.0000", "compliance_pct")


# ─── funding_award_checks_documents_before_the_eligible_cost_base ────────────────

GRANT_ALLOCATION_CENTS = 23842210
FUNDING_NEED_CENTS = 115210677
UNFUNDED_GAP_CENTS = 91368467
LOCAL_MATCH_CENTS = 4768442

SECOND_PARCEL = {
    "site_name": "Cuyahoga Tannery Parcel",
    "county_code": "OH-035",
    "acreage": 3.75,
    "intended_reuse": "RESIDENTIAL",
    "planned_acquisition_date": "2026-11-01",
}


def _four_applications_against_one_approved_remedy(api):
    """
    An approved remedy, a second parcel with no remedy at all, and four applications.

    Only the last application is sound: the first names the parcel that has no approved
    remedy, the second is short two eligibility documents, and the third is fully documented
    but claims a category the remedy has no cost line in.
    """
    world = stage_approved(api)
    other_parcel = add_site(world, **SECOND_PARCEL)

    applications = {
        "no_plan": add_award(
            world,
            site_id=other_parcel["id"],
            program_code="OH-VACANT-PARCEL-GRANT",
            program_priority=5,
        ),
        "undocumented": add_award(
            world,
            program_code="OH-SITE-ASSESS",
            program_priority=3,
            max_award_cents=5000000,
            max_share_pct=0.25,
            match_requirement_pct=0.10,
            eligible_cost_categories=["OVERSIGHT"],
            eligibility_documents=["PHASE_II_REPORT", "COST_ESTIMATE"],
        ),
        "no_base": add_award(
            world,
            program_code="OH-OVERSIGHT-OFFSET",
            program_priority=4,
            max_award_cents=5000000,
            max_share_pct=0.25,
            match_requirement_pct=0.10,
            eligible_cost_categories=["OVERSIGHT"],
        ),
        "sound": add_award(world),
    }
    return world, applications


def _award(world, application):
    """Ask the agency to award one application."""
    return world.api.decide_funding_award(
        application["id"],
        funding_decision_payload(decision="AWARD", decision_note="Programme review complete."),
        REVIEWER_ALPHA,
    )


def test_an_application_on_a_parcel_with_no_approved_remedy_has_no_need_to_fund(api):
    """
    Fully documented, but there is no approved remedy to size the funding against.

    "The parcel must also carry a remedial action plan in `APPROVED`, since without one the
    funding need is undefined — refused with `ERR_FUNDING_NEED_UNDETERMINED` — and the
    approved plan must contain at least one cost line whose `cost_category` falls in this
    award's `eligible_cost_categories`, since otherwise the eligible base is zero and the
    programme has nothing to pay for; that is `ERR_NO_ELIGIBLE_COST_BASE`."

    Design: Corner/validations/funding_award_checks_documents_before_the_eligible_cost_base
    """
    world, applications = _four_applications_against_one_approved_remedy(api)

    refused = _award(world, applications["no_plan"])
    validate_error(refused, ERR_FUNDING_NEED_UNDETERMINED, 422)

    assert_fields(
        world.read_award(applications["no_plan"]), status="APPLIED", allocated_cents=0
    )


def test_the_missing_documents_are_reported_and_the_cost_base_is_never_reached(api):
    """
    Two of the grant's four required codes are absent, so the documentation gate answers.

    "The documentation requirement depends on the `funding_kind`, and the two branches are
    enumerated in full: a `GRANT` requires `eligibility_documents` to contain
    `SITE_CONTROL_EVIDENCE`, `PHASE_II_REPORT`, `COST_ESTIMATE` and `MATCH_COMMITMENT`; a
    `TAX_CREDIT` requires `BFPP_CERTIFICATION`, `PHASE_II_REPORT` and `COST_ESTIMATE`."

    Design: Corner/validations/funding_award_checks_documents_before_the_eligible_cost_base
    """
    world, applications = _four_applications_against_one_approved_remedy(api)

    refused = _award(world, applications["undocumented"])
    validate_error(refused, ERR_MISSING_ELIGIBILITY_DOCUMENT, 422)

    assert_fields(
        world.read_award(applications["undocumented"]), status="APPLIED", allocated_cents=0
    )


def test_a_fully_documented_programme_with_no_matching_cost_line_finds_no_base(api):
    """
    With the documents in order the next gate bites: oversight is not a filed cost line.

    "The parcel must also carry a remedial action plan in `APPROVED`, since without one the
    funding need is undefined — refused with `ERR_FUNDING_NEED_UNDETERMINED` — and the
    approved plan must contain at least one cost line whose `cost_category` falls in this
    award's `eligible_cost_categories`, since otherwise the eligible base is zero and the
    programme has nothing to pay for; that is `ERR_NO_ELIGIBLE_COST_BASE`."

    Design: Corner/validations/funding_award_checks_documents_before_the_eligible_cost_base
    """
    world, applications = _four_applications_against_one_approved_remedy(api)

    refused = _award(world, applications["no_base"])
    validate_error(refused, ERR_NO_ELIGIBLE_COST_BASE, 422)

    assert_fields(
        world.read_award(applications["no_base"]), status="APPLIED", allocated_cents=0
    )


def test_the_sound_application_takes_its_share_of_the_eligible_base(api):
    """
    The one application that clears every gate is capped by its share of the base.

    "A share cap is that eligible base multiplied by the application's `max_share_pct`,
    rounded half up to whole cents."

    Design: Corner/validations/funding_award_checks_documents_before_the_eligible_cost_base
    """
    world, applications = _four_applications_against_one_approved_remedy(api)

    awarded = get_success_data(_award(world, applications["sound"]))
    assert_fields(
        awarded,
        status="AWARDED",
        allocated_cents=GRANT_ALLOCATION_CENTS,
        decided_by_user_id=REVIEWER_ALPHA_USER_ID,
    )


def test_the_assembly_reports_the_gap_and_the_match_left_by_the_one_award(api):
    """
    Three refusals allocate nothing, and the remainder of the need is the reported gap.

    "When every awarded application has been visited, whatever remains of the running
    remainder is the parcel's `unfunded_gap_cents`, and `local_match_required_cents` is the
    sum, over each allocation, of that allocation's `allocated_cents` multiplied by that
    application's own `match_requirement_pct`, each product rounded half up to whole cents
    before summing."

    Design: Corner/validations/funding_award_checks_documents_before_the_eligible_cost_base
    """
    world, applications = _four_applications_against_one_approved_remedy(api)
    for key in ("no_plan", "undocumented", "no_base"):
        _award(world, applications[key])
    _award(world, applications["sound"])

    assembly = world.read_funding_assembly()
    assert_fields(
        assembly,
        site_id=world.site["id"],
        remedial_action_plan_id=world.plan["id"],
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=UNFUNDED_GAP_CENTS,
        local_match_required_cents=LOCAL_MATCH_CENTS,
    )
    assert [
        (entry["funding_award_id"], entry["allocated_cents"])
        for entry in assembly["allocations"]
    ] == [(applications["sound"]["id"], GRANT_ALLOCATION_CENTS)], (
        "only the sound application appears in the waterfall"
    )
    assert_funding_conservation(assembly)

    for key in ("undocumented", "no_base"):
        assert_fields(world.read_award(applications[key]), status="APPLIED", allocated_cents=0)
