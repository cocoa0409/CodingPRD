"""The declared lifecycles, walked at their edges.

Initial states, the one backward edge that undoes a version pin, the actions that
must be refused rather than quietly re-run, the terminal states that swallow
nothing, and the two big cascades — a locked plan that refuses every roster write
and a closing event that drags lanes, posts, the plan and the on-post roster with
it.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ANALYST_HEADERS,
    ApiClient,
    ApiErrorId,
    AssessmentStatus,
    AssignmentStatus,
    CrowdProfile,
    DutyStatus,
    EventStatus,
    GatePosture,
    IngressStatus,
    LaneStatus,
    PlanStatus,
    PostStatus,
    PostType,
    ProtestLikelihood,
    ReviewStatus,
    RiskTier,
    SubcontractorStatus,
    ThreatLevel,
    VerificationStatus,
    World,
    action,
    assert_assignment_state,
    assert_decimal,
    assert_gate,
    assert_ledger,
    assert_post_fill,
    assert_risk_assessment,
    brief_action,
    build_approved_assessment_world,
    build_briefed_event_world,
    build_clock_world,
    build_draft_assessment_world,
    build_doors_open_world,
    build_plan_with_perimeter_post_world,
    build_review_world,
    create_assignment,
    create_verified_guard,
    confirm,
    guard_payload,
    make_post_supervisor_headers,
    post_payload,
    read_post_version,
    risk_assessment_payload,
    set_clock,
    subcontractor_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PRE_DOORS_INSTANT = "2026-09-12T16:30:00Z"
START_INSTANT = "2026-09-12T18:30:00Z"
CLOSE_INSTANT = "2026-09-12T22:30:00Z"


def test_a_fresh_assessment_opens_in_draft_at_revision_one_with_no_scores():
    """The analyst's first draft is a pure record of inputs, not yet a judgement.

    Every derived figure is left unpopulated and the whole decision trail —
    submitter, approver and rejection reason — is still null, which is what makes
    the later reject-and-revise loop observable as a revision counter rather than
    a status flap. Drafting also does not move the event.

    PRD: "A fresh assessment begins in `DRAFT` with `revision_number` 1, and **no scores are computed at creation** — every derived figure stays unpopulated until the assessment is submitted."
    Design: Corner/state_machines/risk_assessment_starts_in_draft_with_revision_number_one
    """
    api = ApiClient()
    world = build_draft_assessment_world(api)
    assessment = world.assessment

    assert_risk_assessment(assessment)
    assert assessment["status"] == AssessmentStatus.DRAFT
    assert assessment["revision_number"] == 1
    assert assessment["submitted_by_user_id"] is None
    assert assessment["approved_by_user_id"] is None
    assert assessment["rejection_reason"] is None
    assert assessment["threat_level_input"] == ThreatLevel.LOW
    assert assessment["protest_likelihood"] == ProtestLikelihood.NONE
    assert assessment["crowd_profile"] == CrowdProfile.SEATED
    assert assessment["ingress_door_count"] == 1
    assert assessment["layout_complexity_score"] == 1
    assert assessment["history_incident_rate"] == 0
    assert assessment["version"] == 1

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.PLANNING


def test_replaying_an_approval_is_refused_rather_than_re_run():
    """A second APPROVE on an already-approved assessment moves nothing at all.

    No transition here is declared idempotent, and approval is also a cascade
    trigger, so swallowing the retry would fire the event cascade twice. The
    assessment stays at version 3 with its original approver, and the event stays
    at version 2.

    PRD: "**Transition legality** — the target resource's current state has an outgoing transition for the requested action, else `ERR_INVALID_STATE` (409)."
    Design: Corner/state_machines/risk_assessment_approve_twice_rejected_not_silently_idempotent
    """
    api = ApiClient()
    world = build_approved_assessment_world(api)
    assert world.assessment["version"] == 3
    assert world.event_v == 2

    validate_error(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )

    assessment = validate_success(api.get_risk_assessment(world.ra_id, DIRECTOR_HEADERS))
    assert assessment["status"] == AssessmentStatus.APPROVED
    assert assessment["version"] == 3
    assert assessment["approved_by_user_id"] == "director-1"

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED
    assert event["version"] == 2


def test_approving_a_replacement_assessment_retires_the_incumbent():
    """The second approval supersedes the first without re-advancing the event.

    Supersession is the only assessment transition driven by a sibling row. The
    winner records its own approver; the loser reaches the single terminal state
    an assessment has while keeping its historical score, tier and staffing
    figures intact. Both rows remain listed against the event.

    PRD: "Approval also stamps `approved_by_user_id`, supersedes any other assessment on the same event that was already `APPROVED` by transitioning it `APPROVED → SUPERSEDED` and incrementing that assessment's `version`, cascades the event `PLANNING → RISK_ASSESSED` (incrementing the event's `version` and re-deriving its `gate_posture`), and increments the approved assessment's own `version`."
    Design: Corner/state_machines/second_risk_assessment_approval_supersedes_the_prior_approved_one
    """
    api = ApiClient()
    world = build_approved_assessment_world(api)

    replacement = validate_success(
        api.create_risk_assessment(
            world.event_id,
            risk_assessment_payload(
                threat_level_input=ThreatLevel.ELEVATED,
                protest_likelihood=ProtestLikelihood.POSSIBLE,
                crowd_profile=CrowdProfile.GENERAL_ADMISSION,
                layout_complexity_score=3,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(
        api.risk_assessment_decision(replacement["id"], action("SUBMIT"), ANALYST_HEADERS)
    )
    approved = validate_success(
        api.risk_assessment_decision(replacement["id"], action("APPROVE"), DIRECTOR_HEADERS)
    )
    assert approved["status"] == AssessmentStatus.APPROVED
    assert approved["approved_by_user_id"] == "director-1"

    retired = validate_success(api.get_risk_assessment(world.ra_id, DIRECTOR_HEADERS))
    assert retired["status"] == AssessmentStatus.SUPERSEDED
    assert_decimal(retired["composite_threat_score"], 3.75, "composite_threat_score")
    assert retired["risk_tier"] == RiskTier.T1
    assert retired["required_total_staff"] == 5

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED

    _, meta = validate_paginated(
        api.list_event_risk_assessments(world.event_id, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 2


def test_recalling_a_published_plan_clears_the_pin_and_republishing_restores_it():
    """The publish-recall-publish cycle leaves no stale version pin behind.

    Publishing stamps the approved assessment's version onto the plan so the plan
    is permanently sized against that snapshot. Recall is the only backward edge
    that undoes a pin, so it must clear the stamp to null rather than leave it
    dangling — and the second publish stamps the same value again.

    PRD: "Recall, also a coordinator action, returns `PUBLISHED → DRAFT`, but only while no assignment on the plan's posts has `assignment_status` equal to `CONFIRMED`; it clears `pinned_risk_assessment_version` back to null, re-derives `readiness_posture`, and increments `version`."
    Design: Corner/state_machines/staffing_plan_recall_returns_published_plan_to_draft_and_clears_pin
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)

    published = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    assert published["status"] == PlanStatus.PUBLISHED
    assert published["pinned_risk_assessment_version"] == 3
    assert published["required_total_staff"] == 5
    assert published["filled_total_staff"] == 0
    assert_decimal(published["coverage_ratio"], 0.00, "coverage_ratio")

    recalled = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("RECALL"), COORDINATOR_HEADERS)
    )
    assert recalled["status"] == PlanStatus.DRAFT
    assert recalled["pinned_risk_assessment_version"] is None
    assert recalled["is_current"] is True

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert post["status"] == PostStatus.OPEN

    republished = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    assert republished["status"] == PlanStatus.PUBLISHED
    assert republished["pinned_risk_assessment_version"] == 3


def test_activating_a_plan_that_was_never_published_is_refused():
    """ACTIVATE has one inbound state, and DRAFT is not it.

    The refusal has to leave the whole activation side-effect set unrun: no
    version pin appears, the post that is short of its requirement stays OPEN
    rather than flipping to UNDERSTAFFED, and the event is not dragged to STAFFED.

    PRD: "Activation is a director action moving `PUBLISHED → ACTIVATED`."
    Design: Corner/state_machines/staffing_plan_activate_from_draft_returns_invalid_state
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)

    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("ACTIVATE"), DIRECTOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.DRAFT
    assert plan["pinned_risk_assessment_version"] is None

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert post["status"] == PostStatus.OPEN

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED


def _locked_plan_world(api: ApiClient) -> World:
    """Briefed five-slot chain whose plan the director has locked down."""
    world = build_briefed_event_world(api)
    locked = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("LOCK"), DIRECTOR_HEADERS)
    )
    assert locked["status"] == PlanStatus.LOCKED
    return world


def test_every_roster_mutation_is_refused_once_the_plan_is_locked():
    """Four different roster writes, one identical refusal, nothing changed.

    Locking is the point where the roster stops being editable: declaring a post,
    re-profiling one, pencilling a shift in and releasing a committed shift are
    all roster mutations, and all four are refused. The plan's sizing, the post's
    requirement, the committed row and the ledger are untouched afterwards.

    PRD: "Locking, also a director action, moves `ACTIVATED → LOCKED` and requires the event's `status` to be one of `BRIEFED`, `DOORS_OPEN`, `IN_PROGRESS` or `SUSPENDED`; from that point every roster mutation on the plan's posts and assignments is refused with `ERR_PLAN_LOCKED`."
    Design: Corner/state_machines/roster_writes_rejected_on_locked_plan
    """
    api = ApiClient()
    world = _locked_plan_world(api)
    e1_version = read_post_version(api, world.e1_id)

    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P2", PostType.PERIMETER, required_guard_count=1),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_LOCKED,
    )
    validate_error(
        api.update_post(
            world.e1_id,
            {"expected_post_version": e1_version, "required_guard_count": 2},
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_LOCKED,
    )
    validate_error(
        api.create_post_assignment(
            {
                "post_id": world.e1_id,
                "guard_id": world.g4_id,
                "window_start": "2026-09-12T15:00:00Z",
                "window_end": "2026-09-12T22:30:00Z",
            },
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_LOCKED,
    )
    validate_error(
        api.post_assignment_duty_event(
            world.a_e1,
            action("CANCEL", cancellation_reason="guard reassigned"),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_LOCKED,
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.LOCKED
    assert plan["required_total_staff"] == 5
    assert_ledger(plan, 82500, 37.50)

    post = validate_success(api.get_post(world.e1_id, COORDINATOR_HEADERS))
    assert post["required_guard_count"] == 1
    assert_post_fill(post, 1, PostStatus.FILLED)

    row = validate_success(api.get_post_assignment(world.a_e1, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.CONFIRMED


def _started_event_world(api: ApiClient) -> World:
    """Six-slot chain live in progress: four guards on post, both lanes open."""
    world = build_doors_open_world(api)
    set_clock(api, START_INSTANT)
    validate_success(api.event_lifecycle(world.event_id, action("START"), DIRECTOR_HEADERS))
    return world


def test_closing_the_event_relieves_the_on_post_roster_and_shuts_everything_down():
    """The largest cascade in the system, checked hop by hop.

    Only the four guards who actually stood a post are relieved and completed,
    each billed on the six hours they really delivered rather than the seven and
    a half they were rostered for. The two rows that never left the briefing room
    stay confirmed and unbilled, both lanes and all six posts close, and the plan
    is dragged from ACTIVATED through LOCKED to CLOSED in the one request while
    its committed ledger stands still.

    PRD: "Every assignment on the current plan whose `duty_status` is `ON_POST` is relieved — `ON_POST → RELIEVED` with `relieved_at` stamped from the logical clock — and its roster dimension completes, `CONFIRMED → COMPLETED`."
    Design: Corner/state_machines/event_close_cascades_lanes_posts_plan_and_on_post_assignments
    """
    api = ApiClient()
    world = _started_event_world(api)
    set_clock(api, CLOSE_INSTANT)

    closed = validate_success(
        api.event_lifecycle(world.event_id, action("CLOSE"), DIRECTOR_HEADERS)
    )
    assert closed["status"] == EventStatus.CLOSED

    for assignment_id in (world.a_s1, world.a_i1, world.a_i2, world.a_e1):
        row = validate_success(api.get_post_assignment(assignment_id, COORDINATOR_HEADERS))
        assert_assignment_state(row, AssignmentStatus.COMPLETED, DutyStatus.RELIEVED)
        assert row["relieved_at"] == CLOSE_INSTANT
        assert_decimal(row["billed_hours"], 6.00, "billed_hours")
        assert row["billed_cost_cents"] == 13200

    for assignment_id in (world.a_p1, world.a_f1):
        row = validate_success(api.get_post_assignment(assignment_id, COORDINATOR_HEADERS))
        assert_assignment_state(row, AssignmentStatus.CONFIRMED, DutyStatus.BRIEFED)

    for lane_id in (world.lane1_id, world.lane2_id):
        lane = validate_success(api.get_screening_lane(lane_id, COORDINATOR_HEADERS))
        assert lane["status"] == LaneStatus.CLOSED
        assert lane["effective_throughput_pph"] == 0

    posts, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert meta["total_count"] == 6
    assert all(post["status"] == PostStatus.CLOSED for post in posts)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.CLOSED
    assert plan["billed_cost_cents"] == 52800
    assert_ledger(plan, 99000, 45.00)


def test_suspending_a_live_event_holds_its_lanes_and_resumption_reopens_them():
    """Suspend and resume are exact inverses down to the throughput figures.

    A suspension needs no preconditions: it holds the doors, puts every open lane
    on hold with its throughput forced to zero, and freezes the gate through the
    second clause of the posture ladder. Resumption restores the door flow, both
    lane throughputs and — because the plan is still READY and no critical
    reading is in the lookback window — the OPEN gate.

    PRD: "A director may **suspend** a live event, `IN_PROGRESS → SUSPENDED`, with no preconditions: the suspension sets `status` to `SUSPENDED`, sets `ingress_status` to `HOLD`, transitions every lane on the event whose `status` is `OPEN` to `HOLD`, and thereby drives `gate_posture` to `FROZEN` through clause 2 of the ladder."
    Design: Corner/state_machines/event_suspend_holds_open_lanes_and_freezes_gate_then_resume_reopens
    """
    api = ApiClient()
    world = _started_event_world(api)

    suspended = validate_success(
        api.event_lifecycle(world.event_id, action("SUSPEND"), DIRECTOR_HEADERS)
    )
    assert suspended["status"] == EventStatus.SUSPENDED
    assert_gate(suspended, GatePosture.FROZEN, IngressStatus.HOLD)
    for lane_id in (world.lane1_id, world.lane2_id):
        lane = validate_success(api.get_screening_lane(lane_id, COORDINATOR_HEADERS))
        assert lane["status"] == LaneStatus.HOLD
        assert lane["effective_throughput_pph"] == 0

    resumed = validate_success(
        api.event_lifecycle(world.event_id, action("RESUME"), DIRECTOR_HEADERS)
    )
    assert resumed["status"] == EventStatus.IN_PROGRESS
    assert_gate(resumed, GatePosture.OPEN, IngressStatus.NORMAL)

    bag_check = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert bag_check["status"] == LaneStatus.OPEN
    assert bag_check["effective_throughput_pph"] == 175

    express = validate_success(api.get_screening_lane(world.lane2_id, COORDINATOR_HEADERS))
    assert express["status"] == LaneStatus.OPEN
    assert express["effective_throughput_pph"] == 409


def test_a_finalized_review_and_a_debriefed_event_accept_nothing_further():
    """Finalization is the last door in the system, and it locks behind itself.

    The finalize records its director and drags the closed event to DEBRIEFED.
    After that, replaying the finalize, returning the review and closing the event
    again are all refused, because neither the review nor the event has any
    outgoing edge left.

    PRD: "`FINALIZED` is terminal for a review and `DEBRIEFED` is terminal for an event."
    Design: Corner/state_machines/after_action_finalize_cascades_event_to_debriefed_and_locks_terminal_state
    """
    api = ApiClient()
    world = build_review_world(api)
    validate_success(
        api.after_action_review_decision(world.aar_id, action("SUBMIT"), COMMANDER_HEADERS)
    )

    finalized = validate_success(
        api.after_action_review_decision(world.aar_id, action("FINALIZE"), DIRECTOR_HEADERS)
    )
    assert finalized["status"] == ReviewStatus.FINALIZED
    assert finalized["finalized_by_user_id"] == "director-1"

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.DEBRIEFED

    validate_error(
        api.after_action_review_decision(world.aar_id, action("FINALIZE"), DIRECTOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )
    validate_error(
        api.after_action_review_decision(
            world.aar_id, action("RETURN", return_reason="one more look"), DIRECTOR_HEADERS
        ),
        ApiErrorId.INVALID_STATE,
    )
    validate_error(
        api.event_lifecycle(world.event_id, action("CLOSE"), DIRECTOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )

    reviews, _ = validate_paginated(
        api.list_event_after_action_reviews(world.event_id, DIRECTOR_HEADERS)
    )
    assert [review["status"] for review in reviews] == [ReviewStatus.FINALIZED]
    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.DEBRIEFED


def test_a_disqualified_guard_can_never_be_taken_back_through_review():
    """The credential machine's dead end, reached the long way round.

    Each accepted step increments the guard's version exactly once: review, then
    rejection with the clearance stamp cleared, then disqualification. From there
    both the auditor's clearance and the coordinator's resubmission are refused,
    and the version stops moving.

    PRD: "A rejected guard may be disqualified by an auditor, moving `REJECTED → DISQUALIFIED`, which is terminal."
    Design: Corner/state_machines/guard_rejected_then_disqualified_reaches_terminal_state
    """
    api = ApiClient()
    build_clock_world(api)
    guard = validate_success(
        api.create_guard(
            guard_payload("GC-4002", credential_level=2, full_name="Gale Two"),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    guard_id = guard["id"]

    under_review = validate_success(
        api.guard_credential_verification(
            guard_id, action("SUBMIT_FOR_REVIEW"), COORDINATOR_HEADERS
        )
    )
    assert under_review["verification_status"] == VerificationStatus.PENDING_REVIEW
    assert under_review["version"] == 2

    rejected = validate_success(
        api.guard_credential_verification(guard_id, action("REJECT"), AUDITOR_HEADERS)
    )
    assert rejected["verification_status"] == VerificationStatus.REJECTED
    assert rejected["verified_at"] is None
    assert rejected["version"] == 3

    disqualified = validate_success(
        api.guard_credential_verification(guard_id, action("DISQUALIFY"), AUDITOR_HEADERS)
    )
    assert disqualified["verification_status"] == VerificationStatus.DISQUALIFIED
    assert disqualified["version"] == 4

    validate_error(
        api.guard_credential_verification(guard_id, action("VERIFY"), AUDITOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )
    validate_error(
        api.guard_credential_verification(
            guard_id, action("SUBMIT_FOR_REVIEW"), COORDINATOR_HEADERS
        ),
        ApiErrorId.INVALID_STATE,
    )

    stored = validate_success(api.get_guard(guard_id, COORDINATOR_HEADERS))
    assert stored["verification_status"] == VerificationStatus.DISQUALIFIED
    assert stored["version"] == 4


def test_a_terminated_vendor_cannot_be_brought_back():
    """Termination is reachable straight from PENDING and admits no return.

    A vendor that never got approved can still be terminated, and once it is,
    neither approval nor suspension has anywhere to go. The version and the
    verified headcount both stand still through the two refusals.

    PRD: "Termination is reachable from `PENDING`, `APPROVED` or `SUSPENDED` and sets `status` to `TERMINATED`, which is terminal; when terminating from `APPROVED`, the identical four-hop suspension cascade is applied before the status is written."
    Design: Corner/state_machines/subcontractor_terminated_is_terminal_and_approve_is_rejected
    """
    api = ApiClient()
    build_clock_world(api)
    vendor = validate_success(
        api.create_subcontractor(
            subcontractor_payload(
                company_name="Vanguard Protective",
                license_number="SC-3001",
                insurance_expires_on="2027-06-30T00:00:00Z",
                markup_pct=0.18,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    vendor_id = vendor["id"]
    assert vendor["status"] == SubcontractorStatus.PENDING

    terminated = validate_success(
        api.subcontractor_decision(vendor_id, action("TERMINATE"), AUDITOR_HEADERS)
    )
    assert terminated["status"] == SubcontractorStatus.TERMINATED
    assert terminated["version"] == 2

    validate_error(
        api.subcontractor_decision(vendor_id, action("APPROVE"), AUDITOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )
    validate_error(
        api.subcontractor_decision(vendor_id, action("SUSPEND"), AUDITOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )

    stored = validate_success(api.get_subcontractor(vendor_id, COORDINATOR_HEADERS))
    assert stored["status"] == SubcontractorStatus.TERMINATED
    assert stored["version"] == 2
    assert stored["verified_guard_count"] == 0


def test_checking_in_a_guard_who_was_never_briefed_names_the_briefing_specifically():
    """The narrower briefing rule displaces the generic state error.

    A confirmed row still at PENDING_BRIEF is not simply in the wrong state — it
    gets its own error, because the missing step is identifiable. Briefing the row
    then stamps the channel, the module and the briefing instant, and the replayed
    check-in succeeds. Only the duty dimension ever moves.

    PRD: "It requires `assignment_status` to be `CONFIRMED`, requires `duty_status` to already be `BRIEFED` (a row still at `PENDING_BRIEF` yields the specific `ERR_GUARD_NOT_BRIEFED` rather than the generic state error), requires the event's `status` to be one of `BRIEFED`, `DOORS_OPEN`, `IN_PROGRESS` or `SUSPENDED`, and requires the logical clock to have reached at least half an hour before the shift's `window_start`."
    Design: Corner/state_machines/check_in_before_brief_returns_guard_not_briefed
    """
    api = ApiClient()
    world = build_briefed_event_world(api)
    extra_post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P2", PostType.PERIMETER, required_guard_count=1),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    late_guard = create_verified_guard(api, "GC-8006", full_name="Gale Five")
    late_row = create_assignment(api, extra_post["id"], late_guard)
    confirmed = confirm(api, late_row)
    assert_assignment_state(confirmed, AssignmentStatus.CONFIRMED, DutyStatus.PENDING_BRIEF)

    supervisor_headers = make_post_supervisor_headers(world.gs_id)
    validate_error(
        api.post_assignment_duty_event(late_row, action("CHECK_IN"), supervisor_headers),
        ApiErrorId.GUARD_NOT_BRIEFED,
    )
    pending = validate_success(api.get_post_assignment(late_row, COORDINATOR_HEADERS))
    assert pending["duty_status"] == DutyStatus.PENDING_BRIEF
    assert pending["check_in_at"] is None

    briefed = validate_success(
        api.post_assignment_duty_event(
            late_row,
            brief_action(radio_channel="CH5", training_module_code="TM-GALA-01"),
            supervisor_headers,
        )
    )
    assert briefed["duty_status"] == DutyStatus.BRIEFED
    assert briefed["radio_channel"] == "CH5"
    assert briefed["training_module_code"] == "TM-GALA-01"
    assert briefed["briefed_at"] == PRE_DOORS_INSTANT

    on_post = validate_success(
        api.post_assignment_duty_event(late_row, action("CHECK_IN"), supervisor_headers)
    )
    assert_assignment_state(on_post, AssignmentStatus.CONFIRMED, DutyStatus.ON_POST)
    assert on_post["check_in_at"] == PRE_DOORS_INSTANT


def test_a_closed_screening_lane_can_be_neither_reopened_nor_held():
    """Closing a lane is a one-way door, even straight from PLANNED.

    The close forces the throughput to zero and takes the lane to its only
    terminal state. Both remaining actions on the lane's machine are then refused
    and the lane's version stops at two, so nothing was written on the way past.

    PRD: "Lane state moves `PLANNED → OPEN`, cycles `OPEN ↔ HOLD`, and terminates at `CLOSED` from any of `PLANNED`, `OPEN` or `HOLD`."
    Design: Corner/state_machines/screening_lane_closed_is_terminal_and_open_is_rejected
    """
    api = ApiClient()
    world = build_briefed_event_world(api)

    closed = validate_success(
        api.screening_lane_status(world.lane1_id, action("CLOSE"), COORDINATOR_HEADERS)
    )
    assert closed["status"] == LaneStatus.CLOSED
    assert closed["effective_throughput_pph"] == 0
    assert closed["version"] == 2

    validate_error(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )
    validate_error(
        api.screening_lane_status(world.lane1_id, action("HOLD"), COORDINATOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )

    lane = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert lane["status"] == LaneStatus.CLOSED
    assert lane["effective_throughput_pph"] == 0
    assert lane["version"] == 2


def test_a_briefed_event_cannot_be_started_suspended_or_closed():
    """The clock being past every scheduled instant does not create an edge.

    Starting requires the event to be at DOORS_OPEN, suspending requires it to be
    in progress and closing requires the same, so all three are refused even
    though the clock has run past the end of the show. The whole rostered chain
    below the event is left exactly as it was.

    PRD: "Starting the event, `DOORS_OPEN → IN_PROGRESS`, requires only that the logical clock have reached `event_start_at`."
    Design: Corner/state_machines/event_start_from_briefed_returns_invalid_state
    """
    api = ApiClient()
    world = build_briefed_event_world(api)
    set_clock(api, CLOSE_INSTANT)

    for name in ("START", "SUSPEND", "CLOSE"):
        validate_error(
            api.event_lifecycle(world.event_id, action(name), DIRECTOR_HEADERS),
            ApiErrorId.INVALID_STATE,
        )

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.BRIEFED
    assert event["ingress_status"] == IngressStatus.NORMAL

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.ACTIVATED

    for post_id in (world.s1_id, world.i1_id, world.f1_id, world.e1_id):
        post = validate_success(api.get_post(post_id, COORDINATOR_HEADERS))
        assert post["status"] == PostStatus.FILLED

    for assignment_id in world.assignment_ids:
        row = validate_success(api.get_post_assignment(assignment_id, COORDINATOR_HEADERS))
        assert_assignment_state(row, AssignmentStatus.CONFIRMED, DutyStatus.BRIEFED)
