"""Who may act, on which verb, and against which row.

The four authority layers are kept apart deliberately: an endpoint-level refusal
never masquerades as an action-level one, an action-level refusal never reaches
the row-scope check, and a caller who clears all three can still be refused for
reviewing their own work. Every refusal is paired with the accepted call that
proves the endpoint itself was reachable.
"""

from test_helpers import (
    ANALYST_2_HEADERS,
    AUDITOR_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_2_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssessmentStatus,
    DensityLevel,
    DutyStatus,
    EmploymentType,
    EventStatus,
    ReviewStatus,
    SubcontractorStatus,
    VerificationStatus,
    action,
    brief_action,
    build_approved_assessment_world,
    build_clock_world,
    build_draft_assessment_world,
    build_five_post_activated_world,
    build_review_world,
    build_submitted_assessment_world,
    event_payload,
    guard_payload,
    make_analyst_headers,
    make_post_supervisor_headers,
    make_subcontractor_liaison_headers,
    set_clock,
    subcontracted_guard_payload,
    subcontractor_payload,
    validate_error,
    validate_paginated,
    validate_success,
    venue_payload,
)

PRE_DOORS_INSTANT = "2026-09-12T16:30:00Z"


def test_authoring_venues_and_events_belongs_to_the_director_alone():
    """Four other-role attempts on the authoring surface, then the director.

    The lifecycle call is the telling one: the coordinator is not on that endpoint
    at all, so the endpoint-level refusal answers and the action is never
    inspected. The event PATCH likewise never reaches the version check, so its
    supplied version is not consumed and the profile is untouched.

    PRD: "**Endpoint role authority** — the acting role appears among the target endpoint's authorised roles in §4, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."
    Design: Corner/rbac/venue_and_event_authoring_are_exclusive_to_the_security_director_returns_forbidden
    """
    api = ApiClient()
    world = build_approved_assessment_world(api)
    new_venue = venue_payload(
        name="Quiet Hall", gross_capacity=2000, door_count=2, egress_capacity_per_minute=300,
        perimeter_length_m=200,
    )

    validate_error(api.create_venue(new_venue, ANALYST_2_HEADERS), ApiErrorId.ROLE_NOT_PERMITTED)
    validate_error(
        api.create_venue(new_venue, COORDINATOR_HEADERS), ApiErrorId.ROLE_NOT_PERMITTED
    )
    validate_error(
        api.create_event(
            event_payload(
                world.venue_id,
                event_name="Winter Gala",
                doors_open_at="2026-11-12T17:00:00Z",
                event_start_at="2026-11-12T18:30:00Z",
                event_end_at="2026-11-12T22:30:00Z",
            ),
            COMMANDER_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.event_lifecycle(world.event_id, action("BRIEF"), COORDINATOR_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.update_event(
            world.event_id,
            {"expected_event_version": world.event_v, "vip_present": True},
            COMMANDER_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    validate_success(api.create_venue(new_venue, DIRECTOR_HEADERS), expected_status=201)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED
    assert event["vip_present"] is False
    assert event["version"] == world.event_v


def test_the_analyst_owns_submission_and_the_director_owns_the_decision():
    """Neither role may borrow the other's verbs on the shared endpoint.

    Both refusals are action-level rather than endpoint-level, which is exactly
    the distinction: the analyst is declared on the decision endpoint, just not
    for APPROVE or REJECT. The exclusion runs both ways, so the director cannot
    SUBMIT either. None of the three refusals touched the row.

    PRD: "- Risk-assessment decisions: `SUBMIT` and `REVISE` belong exclusively to `RiskAnalyst`; `APPROVE` and `REJECT` belong exclusively to `SecurityDirector`."
    Design: Corner/rbac/risk_analyst_can_submit_and_revise_but_never_approve_or_reject
    """
    api = ApiClient()
    world = build_submitted_assessment_world(api)

    validate_error(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), ANALYST_2_HEADERS),
        ApiErrorId.ACTION_NOT_PERMITTED_FOR_ROLE,
    )
    validate_error(
        api.risk_assessment_decision(
            world.ra_id,
            action("REJECT", rejection_reason="layout score understated"),
            ANALYST_2_HEADERS,
        ),
        ApiErrorId.ACTION_NOT_PERMITTED_FOR_ROLE,
    )
    validate_error(
        api.risk_assessment_decision(world.ra_id, action("SUBMIT"), DIRECTOR_HEADERS),
        ApiErrorId.ACTION_NOT_PERMITTED_FOR_ROLE,
    )

    approved = validate_success(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS)
    )
    assert approved["status"] == AssessmentStatus.APPROVED

    assessment = validate_success(api.get_risk_assessment(world.ra_id, DIRECTOR_HEADERS))
    assert assessment["revision_number"] == 1
    assert assessment["submitted_by_user_id"] == "analyst-1"
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.RISK_ASSESSED
    )


def test_only_the_auditor_may_verify_reject_or_disqualify_a_guard():
    """Three auditor-only verbs refused, one shared verb accepted, same caller.

    The coordinator is declared on the credential endpoint, so all three refusals
    are action-level; the shared SUBMIT_FOR_REVIEW from that same caller goes
    through on the same endpoint. The auditor's verification stamps the clock and
    leaves a level-one guard short of the supervisor threshold. Exactly two of the
    six calls mutated the guard.

    PRD: "- Guard credential verification: `SUBMIT_FOR_REVIEW` is shared by `StaffingCoordinator` and `SubcontractorLiaison`; `VERIFY`, `REJECT` and `DISQUALIFY` belong exclusively to `CredentialAuditor`."
    Design: Corner/rbac/only_the_credential_auditor_may_verify_reject_or_disqualify_a_guard
    """
    api = ApiClient()
    build_clock_world(api)
    guard = validate_success(
        api.create_guard(guard_payload("GC-7001"), COORDINATOR_HEADERS), expected_status=201
    )
    guard_id = guard["id"]
    assert guard["verification_status"] == VerificationStatus.UNVERIFIED

    for refused in ("VERIFY", "REJECT", "DISQUALIFY"):
        validate_error(
            api.guard_credential_verification(guard_id, action(refused), COORDINATOR_HEADERS),
            ApiErrorId.ACTION_NOT_PERMITTED_FOR_ROLE,
        )

    submitted = validate_success(
        api.guard_credential_verification(
            guard_id, action("SUBMIT_FOR_REVIEW"), COORDINATOR_HEADERS
        )
    )
    assert submitted["verification_status"] == VerificationStatus.PENDING_REVIEW

    verified = validate_success(
        api.guard_credential_verification(guard_id, action("VERIFY"), AUDITOR_HEADERS)
    )
    assert verified["verification_status"] == VerificationStatus.VERIFIED
    assert verified["verified_at"].startswith("2026-09-01T00:00:00")
    assert verified["is_supervisor_qualified"] is False
    assert verified["version"] == 3


def test_a_supervisor_may_only_move_its_own_row_or_a_row_on_a_plan_it_supervises():
    """Peers on one post hold no authority over each other.

    Being CONFIRMED somewhere on the plan is not standing either, as the floor
    post's untouched row shows. The two accepted calls are the guard's own row and
    the genuine supervisor's, and the peer who was refused both writes can still
    read the whole post — the scope binds duty-event writes, not the shared reads.

    PRD: "Concretely, a `PostSupervisor` acting on a post assignment must either be that assignment's own guard — `X-User-ID` equal to the assignment's `guard_id` — or hold a `CONFIRMED` assignment on a `SUPERVISOR` post belonging to the same staffing plan; otherwise the request is rejected with `ERR_NOT_POST_SUPERVISOR` (403)."
    Design: Corner/rbac/post_supervisor_scope_is_own_assignment_or_a_supervisor_post_on_the_same_plan
    """
    api = ApiClient()
    world = build_five_post_activated_world(api)
    set_clock(api, PRE_DOORS_INSTANT)

    validate_error(
        api.post_assignment_duty_event(
            world.a_i1, brief_action(radio_channel="CH2"), make_post_supervisor_headers(world.g2_id)
        ),
        ApiErrorId.NOT_POST_SUPERVISOR,
    )
    validate_error(
        api.post_assignment_duty_event(
            world.a_f1, brief_action(radio_channel="CH3"), make_post_supervisor_headers(world.g1_id)
        ),
        ApiErrorId.NOT_POST_SUPERVISOR,
    )

    own_row = validate_success(
        api.post_assignment_duty_event(
            world.a_i1, brief_action(radio_channel="CH2"), make_post_supervisor_headers(world.g1_id)
        )
    )
    assert own_row["duty_status"] == DutyStatus.BRIEFED
    assert own_row["radio_channel"] == "CH2"

    by_supervisor = validate_success(
        api.post_assignment_duty_event(
            world.a_i2, brief_action(radio_channel="CH2"), make_post_supervisor_headers(world.gs_id)
        )
    )
    assert by_supervisor["duty_status"] == DutyStatus.BRIEFED

    _, meta = validate_paginated(
        api.list_post_assignments(
            make_post_supervisor_headers(world.g2_id), params={"post_id": world.i1_id}
        )
    )
    assert meta["total_count"] == 2

    untouched = validate_success(api.get_post_assignment(world.a_f1, COORDINATOR_HEADERS))
    assert untouched["duty_status"] == DutyStatus.PENDING_BRIEF


def test_nobody_may_decide_the_assessment_they_submitted():
    """Role and action both permitted, and the request is still refused.

    The submitter holds the director role too, and the rule compares the recorded
    submitter identifier rather than the role, so both decision verbs are closed
    to that user — the refusal is not limited to the favourable one. A second
    director approves, and the recorded submitter is unchanged by any of it.

    PRD: "Those recorded identifiers are what the segregation-of-duties rules compare: the `X-User-ID` performing an assessment `APPROVE` or `REJECT` must differ from that assessment's `submitted_by_user_id`, and the `X-User-ID` performing a review `RETURN` or `FINALIZE` must differ from that review's `authored_by_user_id`."
    Design: Corner/rbac/assessment_approval_by_its_own_submitter_returns_segregation_of_duties
    """
    api = ApiClient()
    world = build_draft_assessment_world(api)
    submitted = validate_success(
        api.risk_assessment_decision(
            world.ra_id, action("SUBMIT"), make_analyst_headers("director-1")
        )
    )
    assert submitted["submitted_by_user_id"] == "director-1"

    validate_error(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api.risk_assessment_decision(
            world.ra_id,
            action("REJECT", rejection_reason="self review not permitted"),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    approved = validate_success(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_2_HEADERS)
    )
    assert approved["status"] == AssessmentStatus.APPROVED
    assert approved["approved_by_user_id"] == "director-2"
    assert approved["submitted_by_user_id"] == "director-1"
    assert approved["revision_number"] == 1
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.RISK_ASSESSED
    )


def test_the_author_of_a_review_may_neither_return_it_nor_finalize_it():
    """The same rule, applied to the other pair of verbs.

    Both director-only decisions are closed to the author, and the review keeps
    its submitted state and its null return reason through the refusals. Another
    director finalizes, which cascades the closed event to DEBRIEFED, and the
    review's computed metrics are exactly what they were before the refusals.

    PRD: "**Segregation of duties** — as described in §2.1, else `ERR_SEGREGATION_OF_DUTIES` (403). Guards `POST /event-security/risk-assessments/{id}/decision` for `APPROVE` and `REJECT`, and `POST /event-security/after-action-reviews/{id}/decision` for `RETURN` and `FINALIZE`."
    Design: Corner/rbac/after_action_return_and_finalize_by_its_author_return_segregation_of_duties
    """
    api = ApiClient()
    world = build_review_world(api, author_headers=DIRECTOR_HEADERS)
    assert world.review["authored_by_user_id"] == "director-1"
    submitted = validate_success(
        api.after_action_review_decision(world.aar_id, action("SUBMIT"), COMMANDER_HEADERS)
    )
    assert submitted["status"] == ReviewStatus.SUBMITTED

    validate_error(
        api.after_action_review_decision(
            world.aar_id,
            action("RETURN", return_reason="narrative omits the queue hold"),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api.after_action_review_decision(world.aar_id, action("FINALIZE"), DIRECTOR_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    finalized = validate_success(
        api.after_action_review_decision(world.aar_id, action("FINALIZE"), DIRECTOR_2_HEADERS)
    )
    assert finalized["status"] == ReviewStatus.FINALIZED
    assert finalized["return_reason"] is None
    assert finalized["total_incident_count"] == 2
    assert finalized["sla_breach_count"] == 1
    assert finalized["peak_density_level"] == DensityLevel.RED
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.DEBRIEFED
    )


def test_sourcing_a_vendor_guard_is_open_to_the_coordinator_and_the_liaison_alike():
    """A shared operation, exercised from both sides.

    The coordinator and the vendor's own liaison each source a guard against the
    approved vendor and get the identical field shape back, and the liaison can
    then push its own guard into review — the verb it shares with the coordinator.
    Only the guard the auditor actually verified is counted on the vendor.

    PRD: "A **Guard** is sourced by a coordinator or a vendor liaison with a `full_name`, an `employment_type` of either `EMPLOYEE` or `SUBCONTRACTED`, a `credential_level` that is a whole number from 1 to 4, the guard-card `license_number`, the card expiry `credential_expires_on`, and a straight-time `base_hourly_rate_cents` of at least 1."
    Design: Corner/rbac/guard_sourcing_and_resubmission_are_shared_by_coordinator_and_liaison
    """
    api = ApiClient()
    build_clock_world(api)
    vendor = validate_success(
        api.create_subcontractor(subcontractor_payload(), AUDITOR_HEADERS), expected_status=201
    )
    vendor_id = vendor["id"]
    validate_success(api.subcontractor_decision(vendor_id, action("APPROVE"), AUDITOR_HEADERS))
    liaison_headers = make_subcontractor_liaison_headers(vendor_id)

    by_coordinator = validate_success(
        api.create_guard(
            subcontracted_guard_payload("GC-5001", vendor_id, full_name="Vendor Hand A"),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    by_liaison = validate_success(
        api.create_guard(
            subcontracted_guard_payload("GC-5002", vendor_id, full_name="Vendor Hand B"),
            liaison_headers,
        ),
        expected_status=201,
    )
    for sourced in (by_coordinator, by_liaison):
        assert sourced["employment_type"] == EmploymentType.SUBCONTRACTED
        assert sourced["subcontractor_id"] == vendor_id
        assert sourced["verification_status"] == VerificationStatus.UNVERIFIED

    in_review = validate_success(
        api.guard_credential_verification(
            by_liaison["id"], action("SUBMIT_FOR_REVIEW"), liaison_headers
        )
    )
    assert in_review["verification_status"] == VerificationStatus.PENDING_REVIEW
    verified = validate_success(
        api.guard_credential_verification(by_liaison["id"], action("VERIFY"), AUDITOR_HEADERS)
    )
    assert verified["verification_status"] == VerificationStatus.VERIFIED

    _, meta = validate_paginated(
        api.list_guards(liaison_headers, params={"subcontractor_id": vendor_id})
    )
    assert meta["total_count"] == 2

    vendor_after = validate_success(api.get_subcontractor(vendor_id, AUDITOR_HEADERS))
    assert vendor_after["verified_guard_count"] == 1
    assert vendor_after["status"] == SubcontractorStatus.APPROVED
