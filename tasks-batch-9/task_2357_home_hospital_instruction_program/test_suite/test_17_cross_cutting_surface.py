"""Three cross-cutting layers walked end to end on a single case.

The first layer is concurrency: all three writes that hang off a case demand the
version their client last saw, and each of them refuses a version that an
intervening write has already invalidated — including a version that looked
fresh two calls ago. The second layer is the all-or-nothing cascade: one
completion request either moves five rows or none of them, and the refusal leaves
every one of those rows exactly where it stood. The third layer is a rate
threshold that arms on its own boundary, releases the moment a single visit is
recorded, and arms again on the next completed week rather than latching once.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    DEFAULT_TEACHER,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    accept_assignment,
    activate_case,
    api_client,
    create_certification_payload,
    create_extension_request_payload,
    create_transition_plan_payload,
    decide_extension_payload,
    finalize_safety_review,
    get_success_data,
    log_session_delivered,
    open_case,
    propose_assignment,
    publish_entitlement_rule,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    record_safety_review,
    register_student,
    register_teacher,
    review_certification,
    schedule_session,
    set_clock,
    setup_active_case_with_session,
    setup_case_with_transition_plan,
    validate_error,
    validate_success,
)

CLOCK = "2026-09-01T00:00:00Z"
ACTIVATION_CLOCK = "2026-09-07T08:00:00Z"

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

CLEARED_SAFETY_REVIEW = {
    "hazard_findings": ["UNLIT_ACCESS"],
    "escort_available": False,
}


def _read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_transition_plan(plan_id, CM_HEADERS))


def _read_pacing_sync(sync_id: str) -> dict:
    return get_success_data(api_client.get_pacing_sync(sync_id, CM_HEADERS))


class TestEveryConcurrencyGuardOnTheSameCase:
    """The three writes that declare a parent version, exercised on one chain."""

    def test_all_three_creations_refuse_a_stale_version_and_take_the_re_read_one(self):
        """A certification, an extension request and a transition plan each carry the
        client's last observed case version, and each of the three is refused when an
        intervening write has moved the case on: a rejected certification advances the
        case twice, an acceptance plus an activation invalidate the version a submitter
        held before them, and an approved extension invalidates the version the activation
        handed out. Each refusal writes nothing at all, and the version read back
        afterwards is accepted immediately.

        The PRD states: "Each of the three therefore requires the client to declare
        which revision of the case it observed, through a non-optional body field named
        `expected_case_version` carrying the client's last observed `version` of the
        parent `HomeboundCase`."

        The PRD states: "If `expected_case_version` does not equal the case's current
        `version`, the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412,
        and nothing is written."

        The PRD states: "Certification submission (`POST /hhi/certifications`) requires
        `expected_case_version`."

        The PRD states: "Extension request creation (`POST /hhi/extension-requests`)
        requires `expected_case_version`."

        The PRD states: "Transition plan creation (`POST /hhi/transition-plans`)
        requires `expected_case_version`."

        The PRD states: "A `CaseManager` submits one against a `DRAFT` case, which
        advances `service_status` from `DRAFT` to `PENDING_CERT_REVIEW` and increments
        the case's `version` by one."

        The PRD states: "The case's `version` increments by one either way."

        The PRD states: "The certification moves from `SUBMITTED` to `REJECTED`, its
        `is_current` stays false, and the case's `service_status` returns from
        `PENDING_CERT_REVIEW` back to `DRAFT` so that a corrected certification can be
        submitted."

        The PRD states: "A `CaseManager` requests one against an `ACTIVE` case, which
        advances `service_status` `ACTIVE → EXTENSION_PENDING` and increments the case's
        `version` by one."

        The PRD states: "Starting review moves the request `SUBMITTED → UNDER_REVIEW`,
        refreshing `updated_at` and changing nothing on the case."

        The PRD states: "Either decision stamps `decided_by_user_id` with the acting
        `X-User-ID`, moves the case `EXTENSION_PENDING → ACTIVE`, and increments the
        case's `version` by one — the loop `ACTIVE → EXTENSION_PENDING → ACTIVE` is
        deliberately cyclic, and `extension_count` reaching 2 is what terminates it."

        The PRD states: "A `CaseManager` opens a plan against an `ACTIVE` case, which
        advances the case `ACTIVE → TRANSITION_PLANNED` and increments its `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/all_three_concurrency_rules_reject_a_stale_case_version_and_accept_the_fresh_one
        """
        set_clock(CLOCK)
        publish_entitlement_rule(**MIDDLE_IN_HOME_RULE)
        student = register_student()
        teacher = register_teacher(**DEFAULT_TEACHER)
        case = open_case(student["id"])
        case_id = case["id"]
        case_v0 = case["version"]

        first_cert = validate_success(
            api_client.create_certification(
                create_certification_payload(case_id, case_v0, **CERT_WINDOW),
                CM_HEADERS,
            ),
            201,
        )
        rejected = review_certification(
            first_cert["id"],
            "REJECT",
            review_note="Diagnosis category unsupported by the attached note",
        )
        assert rejected["status"] == "REJECTED"
        assert read_case(case_id)["service_status"] == "DRAFT", (
            "rejection is a revision cycle, so the case is open to a corrected document"
        )

        validate_error(
            api_client.create_certification(
                create_certification_payload(case_id, case_v0, **CERT_WINDOW),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_STALE_CASE_VERSION.value,
            412,
        )
        case_v_after_reject = read_case(case_id)["version"]
        assert case_v_after_reject == case_v0 + 2, (
            "the submission and the review each moved the case once, which is exactly "
            "why the version captured before them is no longer usable"
        )

        second_cert = validate_success(
            api_client.create_certification(
                create_certification_payload(
                    case_id, case_v_after_reject, **CERT_WINDOW
                ),
                CM_HEADERS,
            ),
            201,
        )
        review_certification(second_cert["id"], "ACCEPT")

        review = record_safety_review(case_id, **CLEARED_SAFETY_REVIEW)
        finalize_safety_review(review["id"])
        assignment = propose_assignment(case_id, "PRIMARY", teacher["id"])
        accept_assignment(assignment["id"], teacher["id"])

        set_clock(ACTIVATION_CLOCK)
        activated = activate_case(case_id)
        case_v_active = activated["version"]
        assert activated["service_status"] == "ACTIVE"

        validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    second_cert["id"],
                    case_v_after_reject,
                    requested_additional_days=15,
                    justification="Recovery slower than certified",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_STALE_CASE_VERSION.value,
            412,
        )
        after_refusal = read_case(case_id)
        assert after_refusal["version"] == case_v_active, (
            "a version that predates the acceptance and the activation writes nothing"
        )
        assert after_refusal["service_status"] == "ACTIVE", (
            "the refused request never moved the case into EXTENSION_PENDING"
        )

        extension = validate_success(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    second_cert["id"],
                    case_v_active,
                    requested_additional_days=15,
                    justification="Recovery slower than certified",
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert read_case(case_id)["service_status"] == "EXTENSION_PENDING"
        get_success_data(
            api_client.start_extension_review(extension["id"], PA_HEADERS)
        )
        validate_success(
            api_client.decide_extension_request(
                extension["id"],
                decide_extension_payload(
                    "APPROVED", decision_note="Updated documentation on file"
                ),
                PA_HEADERS,
            )
        )

        plan_payload = create_transition_plan_payload(
            case_id,
            case_v_active,
            target_return_date="2026-10-26",
            reintegration_mode="FULL_DAY",
            ramp_weeks=0,
        )
        validate_error(
            api_client.create_transition_plan(plan_payload, CM_HEADERS),
            ApiErrorId.ERR_STALE_CASE_VERSION.value,
            412,
        )
        case_v_after_decide = read_case(case_id)["version"]
        assert case_v_after_decide == case_v_active + 2, (
            "requesting the extension moved the case once and deciding it moved the "
            "case once, while starting the review changed nothing on the case"
        )
        assert read_case(case_id)["service_status"] == "ACTIVE", (
            "the refused plan left the case in service rather than in planning"
        )

        plan = validate_success(
            api_client.create_transition_plan(
                {**plan_payload, "expected_case_version": case_v_after_decide},
                CM_HEADERS,
            ),
            201,
        )
        assert plan["status"] == "DRAFT"
        assert read_case(case_id)["service_status"] == "TRANSITION_PLANNED", (
            "the same payload succeeds once it declares the version it actually observed"
        )


class TestCompletionCascadesCompletelyOrNotAtAll:
    """One request, five rows, and a refusal that moves none of them."""

    def test_the_refused_completion_moves_nothing_and_the_accepted_one_moves_everything(
        self,
    ):
        """A READY plan whose target return date has not arrived is refused, and the
        refusal leaves the plan, the case, the assignment, the session and the teacher
        aggregate untouched. A week later the identical request walks all four levels in
        one response cycle: plan to case, case to assignment and session, assignment to the
        teacher's re-summed commitment — while the coordination row, which the completion
        cascade never names, stays acknowledged.

        The PRD states: "Completion is a `ProgramAdministrator` act against a `READY`
        plan on or after the target date."

        The PRD states: "Completing a plan whose `status` is not `READY` is
        `ERR_PLAN_NOT_READY`, and completing before the clock date has reached
        `target_return_date` is `ERR_RETURN_DATE_NOT_REACHED`."

        The PRD states: "Completion moves the plan `READY → COMPLETED`, stamps
        `completed_at` with the clock instant, and closes the case: the case advances
        `TRANSITION_PLANNED → CLOSED` with `close_reason` `RETURNED_TO_CAMPUS`, every
        assignment of the case whose `status` is `ACTIVE` is moved to `RELEASED` with
        `release_reason` `CASE_CLOSED` and `weekly_committed_minutes` 0,
        `committed_weekly_minutes` is recomputed for each released teacher, every
        session of the case whose `status` is `SCHEDULED` is moved to `CANCELLED_ADMIN`,
        and the case's `version` increments by one."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        The PRD states: "The derived flag `over_cap` is true when
        `committed_weekly_minutes` is strictly greater than that teacher's
        `max_weekly_caseload_minutes`, and false when the two are equal."

        The PRD states: "Recomputations are always full recomputations from the current
        input set, never incremental deltas applied to a stored running figure."

        Design: Corner/cross_cutting_complexity_layers/a_failed_completion_cascades_nothing_and_a_successful_one_cascades_four_levels
        """
        bundle = setup_case_with_transition_plan(
            clock=CLOCK,
            activation_clock=ACTIVATION_CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
            plan={
                "target_return_date": "2026-09-14",
                "reintegration_mode": "FULL_DAY",
                "ramp_weeks": 0,
            },
            pacing_syncs=1,
            coordinate=True,
            acknowledge=True,
        )
        case_id = bundle["case"]["id"]
        plan_id = bundle["plan"]["id"]
        assignment_id = bundle["primary_assignment"]["id"]
        teacher_id = bundle["teacher"]["id"]
        sync_id = bundle["pacing_syncs"][0]["id"]

        assert bundle["plan"]["status"] == "READY", (
            "one coordination row exists and it has been acknowledged, so the plan "
            "settled at READY inside the acknowledgement request"
        )
        session = schedule_session(
            case_id,
            assignment_id,
            scheduled_start="2026-09-10T09:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
        )
        session_id = session["id"]
        assert session["status"] == "SCHEDULED"
        version_before = read_case(case_id)["version"]

        validate_error(
            api_client.complete_transition_plan(plan_id, PA_HEADERS),
            ApiErrorId.ERR_RETURN_DATE_NOT_REACHED.value,
            409,
        )

        held_plan = _read_plan(plan_id)
        assert held_plan["status"] == "READY"
        assert held_plan["completed_at"] is None
        stalled_case = read_case(case_id)
        assert stalled_case["service_status"] == "TRANSITION_PLANNED"
        assert stalled_case["version"] == version_before, (
            "the refusal is not a mutation, so the case carries the same version"
        )
        assert read_assignment(assignment_id)["status"] == "ACTIVE"
        assert read_assignment(assignment_id)["weekly_committed_minutes"] == 390
        assert read_session(session_id)["status"] == "SCHEDULED"
        assert read_teacher(teacher_id)["committed_weekly_minutes"] == 390, (
            "no level of the cascade ran, right down to the teacher aggregate"
        )

        set_clock("2026-09-14T09:00:00Z")
        completed = validate_success(
            api_client.complete_transition_plan(plan_id, PA_HEADERS)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"].startswith("2026-09-14T09:00:00"), (
            "the stamp is the clock instant, not wall-clock time"
        )

        closed_case = read_case(case_id)
        assert closed_case["service_status"] == "CLOSED"
        assert closed_case["close_reason"] == "RETURNED_TO_CAMPUS"
        assert closed_case["version"] == version_before + 1, (
            "the whole cascade is one mutation of the case, counted once"
        )

        released = read_assignment(assignment_id)
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "CASE_CLOSED"
        assert released["weekly_committed_minutes"] == 0
        cancelled = read_session(session_id)
        assert cancelled["status"] == "CANCELLED_ADMIN"
        assert cancelled["credited_minutes"] == 0, (
            "an administratively cancelled visit never earned a minute"
        )

        freed_teacher = read_teacher(teacher_id)
        assert freed_teacher["committed_weekly_minutes"] == 0, (
            "the re-sum finds no active assignment left to count"
        )
        assert freed_teacher["over_cap"] is False

        assert _read_pacing_sync(sync_id)["ack_status"] == "ACKED", (
            "the cascade reaches assignments and sessions, not coordination rows"
        )


class TestTheServiceGapThresholdArmsOnItsOwnBoundary:
    """A shortfall of exactly one weekly entitlement, released and re-armed."""

    def test_the_hold_fires_at_one_entitlement_releases_on_one_visit_and_re_arms(self):
        """After one completed service week with nothing delivered the shortfall is exactly
        one weekly entitlement, which is the inclusive edge of the hold condition, so the
        funding posture moves to HELD. A single thirty-minute visit drops the shortfall
        below that edge and the posture returns to accruing inside the same request. A
        second completed week rebuilds the shortfall past the same edge and the hold fires
        again, so the threshold re-arms every week rather than latching once. The read-only
        summary in between changes nothing.

        The PRD states: "Count the completed service weeks as the number of whole
        seven-day spans between the case's `service_start_date` and the clock date,
        taking the floor so a partial week contributes nothing."

        The PRD states: "Multiply that count by the case's `weekly_entitled_minutes` to
        get the minutes expected to date."

        The PRD states: "Subtract the case's `reported_apportionment_minutes` from that
        expectation and floor the difference at 0; the result is `service_gap_minutes`."

        The PRD states: "When the recomputed gap reaches or exceeds exactly one weekly
        entitlement — that is, when `service_gap_minutes` is greater than or equal to
        `weekly_entitled_minutes` — and the case's `funding_status` is `ACCRUING` or
        `RECONCILED`, the funding posture moves to `HELD`."

        The PRD states: "When the recomputed gap falls back below one weekly entitlement
        and the case's `funding_status` is `HELD`, the posture returns to `ACCRUING`."

        The PRD states: "This recomputation runs after every attendance ledger write —
        delivery, student unavailability, teacher cancellation, safety abort, and void —
        and after every provisional funding report."

        The PRD states: "Each `DELIVERED` session contributes its `credited_minutes`."

        The PRD states: "Reporting also recomputes `service_gap_minutes`, which may fire
        a hold or release one, and increments the case's `version` by one."

        The PRD states: "After any of the four outcomes the case's
        `reported_apportionment_minutes` is recomputed as the sum of
        `apportionment_minutes` across that case's entire attendance ledger, its
        `service_gap_minutes` is recomputed per §3.7 — which may itself move the case's
        funding posture — and its `makeup_obligation_minutes` is recomputed."

        Design: Corner/cross_cutting_complexity_layers/the_service_gap_hold_arms_at_exactly_one_weekly_entitlement_and_re_arms_each_week
        """
        bundle = setup_active_case_with_session(
            clock=CLOCK,
            activation_clock=ACTIVATION_CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
            session={
                "scheduled_start": "2026-09-08T09:00:00Z",
                "scheduled_end": "2026-09-08T09:30:00Z",
            },
        )
        case_id = bundle["case"]["id"]
        session_id = bundle["session"]["id"]
        teacher_id = bundle["teacher"]["id"]
        assert bundle["case"]["weekly_entitled_minutes"] == 390
        assert bundle["case"]["service_start_date"] == "2026-09-07"

        first = validate_success(api_client.report_case_funding(case_id, PA_HEADERS))
        assert first["service_gap_minutes"] == 0, (
            "no whole seven-day span has closed yet, so nothing is owed yet"
        )
        assert first["funding_status"] == "ACCRUING"
        assert first["provisional_apportionment_minutes"] == 30, (
            "the one scheduled half-hour visit is projected forward at 30 minutes"
        )

        set_clock("2026-09-14T09:00:00Z")
        second = validate_success(api_client.report_case_funding(case_id, PA_HEADERS))
        assert second["reported_apportionment_minutes"] == 0, (
            "the visit is still only scheduled, so the ledger is empty"
        )
        assert second["service_gap_minutes"] == 390, (
            "one completed week at 390 entitled minutes against nothing delivered"
        )
        assert second["funding_status"] == "HELD", (
            "the shortfall equals one weekly entitlement, which the inclusive "
            "greater-than-or-equal condition already catches"
        )

        logged = log_session_delivered(session_id, teacher_id, 30)
        assert logged["credited_minutes"] == 30
        released = read_case(case_id)
        assert released["reported_apportionment_minutes"] == 30
        assert released["service_gap_minutes"] == 360, (
            "the 390 owed less the 30 now on the ledger"
        )
        assert released["funding_status"] == "ACCRUING", (
            "the gap fell below one weekly entitlement in the very request that "
            "wrote the ledger row"
        )

        set_clock("2026-09-21T09:00:00Z")
        summary = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert summary["weekly_entitled_minutes"] == 390
        assert summary["funding_status"] == "ACCRUING", (
            "the summary is a read model: the posture only moves on a ledger write "
            "or a provisional report"
        )
        assert read_case(case_id)["funding_status"] == "ACCRUING"

        third = validate_success(api_client.report_case_funding(case_id, PA_HEADERS))
        assert third["service_gap_minutes"] == 750, (
            "two completed weeks owe 780 minutes and 30 have been delivered"
        )
        assert third["funding_status"] == "HELD", (
            "the threshold re-arms on the next completed week instead of latching "
            "once on the first hold"
        )
        assert third["provisional_apportionment_minutes"] == 30, (
            "the single delivered visit contributes its 30 credited minutes, well "
            "under the window cap"
        )
