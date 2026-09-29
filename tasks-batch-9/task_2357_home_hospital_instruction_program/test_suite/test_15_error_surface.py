"""Where each refusal code actually lives, and how few of them there really are.

One transition plan, walked from the day it opens to the day it is abandoned,
refuses four different requests for four different reasons — and the same verb
gives two different codes depending on how far along the plan is. One safety
review answers with a single code for two unrelated current states. And one
fiscal ceiling counts approvals rather than attempts, so the request that
breaks it is the third one even though the case and its paperwork are perfectly
in order.
"""

from test_helpers import (
    ApiErrorId,
    CLASSROOM_TEACHER,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    PROGRAM_ADMINISTRATOR_USER_ID,
    CASE_MANAGER_USER_ID,
    abort_transition_plan_payload,
    acknowledge_pacing_sync,
    api_client,
    create_extension_request_payload,
    create_transition_plan_payload,
    decide_extension_payload,
    finalize_safety_review,
    get_success_data,
    list_data,
    open_pacing_sync,
    read_assignment,
    read_case,
    read_teacher,
    record_safety_review,
    register_teacher,
    setup_active_case,
    setup_eligible_case,
    validate_error,
    validate_paginated,
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


def _all(list_call) -> list:
    """Every row of one collection, unfiltered — the only declared query parameters
    are the page window, so any narrowing happens here in the test."""
    return list_data(list_call(PA_HEADERS, params={"limit": 100}))


def _read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_transition_plan(plan_id, CM_HEADERS))


def _read_safety_review(review_id: str) -> dict:
    return get_success_data(api_client.get_safety_review(review_id, CM_HEADERS))


def _case_in_service_with_a_classroom_teacher_of_record() -> dict:
    """An ACTIVE case entitled to 390 minutes a week, carrying no coordination rows
    yet, alongside the campus teacher of record who will answer for one subject."""
    bundle = setup_active_case(
        clock=CLOCK,
        activation_clock=ACTIVATION_CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    bundle["classroom_teacher"] = register_teacher(**CLASSROOM_TEACHER)
    return bundle


def _approve_one_extension(case_id: str, certification_id: str, days: int) -> dict:
    """Submit, start review and approve one extension request of `days` days."""
    request = get_success_data(
        api_client.create_extension_request(
            create_extension_request_payload(
                case_id,
                certification_id,
                read_case(case_id)["version"],
                requested_additional_days=days,
                justification="Surgical recovery extended by two weeks",
            ),
            CM_HEADERS,
        )
    )
    get_success_data(api_client.start_extension_review(request["id"], PA_HEADERS))
    return validate_success(
        api_client.decide_extension_request(
            request["id"],
            decide_extension_payload("APPROVED", decision_note="Documentation on file"),
            PA_HEADERS,
        )
    )


class TestOnePlanTriggersEveryOneOfItsOwnRefusals:
    """Four codes, one plan, and each one only reachable at its own moment."""

    def test_walking_a_plan_to_abandonment_lands_each_code_where_it_belongs(self):
        """Completing a DRAFT plan is refused for not being ready, coordinating a case
        with no coordination rows is refused for having none, coordinating a second time
        is refused on state, and once acknowledgement has carried the plan to READY the
        very same completion request is refused on the target date instead — proving the
        readiness code no longer applies. Aborting works once and is then refused on
        state without disturbing the reason already recorded.

        The PRD states: "A `CaseManager` opens a plan against an `ACTIVE` case, which
        advances the case `ACTIVE → TRANSITION_PLANNED` and increments its `version` by
        one."

        The PRD states: "A new plan starts with `status` `DRAFT`, and its
        `required_ack_count` and `classroom_ack_count` are computed on creation."

        The PRD states: "`required_ack_count` is the number of coordination rows for the
        plan's case whose `ack_status` is `PENDING`, `ACKED` or `DISPUTED`;
        `classroom_ack_count` is the number of those rows whose `ack_status` is
        `ACKED`."

        The PRD states: "Completing a plan whose `status` is not `READY` is
        `ERR_PLAN_NOT_READY`, and completing before the clock date has reached
        `target_return_date` is `ERR_RETURN_DATE_NOT_REACHED`."

        The PRD states: "A `CaseManager` sends a `DRAFT` plan out for classroom
        coordination, moving it `DRAFT → CLASSROOM_COORD_PENDING`."

        The PRD states: "Coordination requires at least one coordination row on the case
        — a `required_ack_count` of at least 1 — and a case with no coordination rows at
        all is rejected with `ERR_NO_PACING_COORDINATION`."

        The PRD states: "Coordinating a plan that is not `DRAFT` is
        `ERR_PLAN_STATE_INVALID`."

        The PRD states: "A new row starts with `ack_status` `PENDING`, and its creation
        recomputes the acknowledgement counters of any open transition plan on the case,
        which may pull a `READY` plan back to `CLASSROOM_COORD_PENDING`."

        The PRD states: "A `ClassroomTeacher` whose `X-User-ID` equals the row's
        `classroom_teacher_id` may acknowledge the pacing target and accommodation,
        moving `ack_status` to `ACKED` from either `PENDING` or `DISPUTED`, and stamping
        `acked_at` with the clock instant; that recomputes the plan counters and may
        advance a plan from `CLASSROOM_COORD_PENDING` to `READY`."

        The PRD states: "A plan in `CLASSROOM_COORD_PENDING` advances to `READY` exactly
        when `required_ack_count` is at least 1, `classroom_ack_count` equals
        `required_ack_count`, and the parent case's `funding_status` is anything other
        than `HELD` — so the plan depends jointly on its coordination children and on
        the case's parallel funding dimension."

        The PRD states: "A `CaseManager` aborts a plan whose `status` is `DRAFT`,
        `CLASSROOM_COORD_PENDING` or `READY`, recording an `abort_reason` of
        `MEDICAL_RELAPSE`, `PARENT_WITHDRAWAL`, `CAMPUS_CAPACITY`, or
        `DOCUMENTATION_DEFECT`."

        The PRD states: "The plan moves to `ABORTED` and the case returns from
        `TRANSITION_PLANNED` to `ACTIVE`, incrementing the case's `version` by one —
        which means a case may enter planning again later, the second cyclic path
        through the service dimension."

        The PRD states: "Aborting a plan that is already `COMPLETED`, `ABORTED` or
        `SUPERSEDED` is `ERR_PLAN_STATE_INVALID`."

        Design: Corner/errors/transition_plan_verbs_expose_their_three_state_and_referential_codes
        """
        bundle = _case_in_service_with_a_classroom_teacher_of_record()
        case_id = bundle["case"]["id"]
        classroom_teacher_id = bundle["classroom_teacher"]["id"]

        plan = validate_success(
            api_client.create_transition_plan(
                create_transition_plan_payload(
                    case_id,
                    bundle["case"]["version"],
                    target_return_date="2026-09-14",
                    reintegration_mode="FULL_DAY",
                    ramp_weeks=0,
                ),
                CM_HEADERS,
            ),
            201,
        )
        plan_id = plan["id"]
        assert plan["status"] == "DRAFT"
        assert plan["required_ack_count"] == 0, "no coordination row exists yet"
        assert plan["classroom_ack_count"] == 0
        assert read_case(case_id)["service_status"] == "TRANSITION_PLANNED"

        validate_error(
            api_client.complete_transition_plan(plan_id, PA_HEADERS),
            ApiErrorId.ERR_PLAN_NOT_READY.value,
            409,
        )
        validate_error(
            api_client.coordinate_transition_plan(plan_id, CM_HEADERS),
            ApiErrorId.ERR_NO_PACING_COORDINATION.value,
            422,
        )
        assert _read_plan(plan_id)["status"] == "DRAFT", (
            "both refusals left the plan exactly where it was"
        )

        sync = open_pacing_sync(
            case_id,
            classroom_teacher_id,
            subject="MATH",
            pacing_target_unit="Unit 3 Linear Equations",
            assessment_accommodation="EXTENDED_TIME",
        )
        assert sync["ack_status"] == "PENDING"

        coordinated = validate_success(
            api_client.coordinate_transition_plan(plan_id, CM_HEADERS)
        )
        assert coordinated["status"] == "CLASSROOM_COORD_PENDING"
        assert coordinated["required_ack_count"] == 1
        assert coordinated["classroom_ack_count"] == 0, (
            "the row exists but nobody has answered it"
        )

        validate_error(
            api_client.coordinate_transition_plan(plan_id, CM_HEADERS),
            ApiErrorId.ERR_PLAN_STATE_INVALID.value,
            409,
        )

        acknowledged = acknowledge_pacing_sync(sync["id"], classroom_teacher_id)
        assert acknowledged["ack_status"] == "ACKED"
        ready = _read_plan(plan_id)
        assert ready["status"] == "READY", (
            "one acknowledgement of one required row satisfies the readiness guard"
        )
        assert ready["classroom_ack_count"] == 1
        assert ready["required_ack_count"] == 1

        refusal = validate_error(
            api_client.complete_transition_plan(plan_id, PA_HEADERS),
            ApiErrorId.ERR_RETURN_DATE_NOT_REACHED.value,
            409,
        )
        assert refusal["error_id"] != ApiErrorId.ERR_PLAN_NOT_READY.value, (
            "the plan is READY now, so only the target-date rule is left to break"
        )
        assert _read_plan(plan_id)["completed_at"] is None

        aborted = validate_success(
            api_client.abort_transition_plan(
                plan_id,
                abort_transition_plan_payload(abort_reason="MEDICAL_RELAPSE"),
                CM_HEADERS,
            )
        )
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "MEDICAL_RELAPSE"
        assert read_case(case_id)["service_status"] == "ACTIVE", (
            "an abandoned return puts the case back into service"
        )

        validate_error(
            api_client.abort_transition_plan(
                plan_id,
                abort_transition_plan_payload(abort_reason="CAMPUS_CAPACITY"),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_PLAN_STATE_INVALID.value,
            409,
        )
        assert _read_plan(plan_id)["abort_reason"] == "MEDICAL_RELAPSE", (
            "the refused second abort did not overwrite the recorded reason"
        )


class TestOneCodeCoversEveryNonDraftReview:
    """A finalized row and a superseded row are different states, one refusal."""

    def test_a_finalized_row_and_a_superseded_row_answer_with_the_same_code(self):
        """The finalize verb wants DRAFT and nothing else. A row that has already been
        finalized refuses with the already-finalized code, and so does the very same row
        after a newer review has pushed it to SUPERSEDED — while the newer review's own
        finalization rescores the home and flips the case's escort requirement.

        The PRD states: "The new review starts with `status` `DRAFT` and `clearance`
        `PENDING`."

        The PRD states: "From `evidence_source` the server derives `scoring_variant`:
        `SELF_REPORTED` when the evidence source is `PARENT_ATTESTATION`, and
        `ONSITE_VERIFIED` when it is `ONSITE_WALKTHROUGH`."

        The PRD states: "The server also derives `expires_on` as the `review_date`
        advanced by sixty days, and computes an initial `risk_score`."

        The PRD states: "The risk score begins as the sum of hazard weights over the
        review's distinct findings: `AGGRESSIVE_ANIMAL` weighs 25 points,
        `NO_SECONDARY_EXIT` 15, `WEAPON_PRESENT_UNSECURED` 40, `SMOKE_OR_AIR_QUALITY`
        10, `ACTIVE_INFECTION_RISK` 30, `UNLIT_ACCESS` 5, and `NO_ADULT_PRESENT` 20."

        The PRD states: "Under `ONSITE_VERIFIED`, the raw sum is used undiscounted, a
        flat 10 points of escort mitigation is subtracted when `escort_available` is
        true and nothing is subtracted when it is false, the result is floored at 0, and
        it is capped at 100."

        The PRD states: "`clearance` is banded from `risk_score` with inclusive lower
        bounds: `BLOCKED` at 60 points or above, otherwise `VIRTUAL_ONLY` at 35 points
        or above, otherwise `CLEARED_WITH_ESCORT` at 15 points or above, otherwise
        `CLEARED`."

        The PRD states: "A `CaseManager` finalizes a `DRAFT` review — finalizing one
        that is not `DRAFT` is `ERR_REVIEW_ALREADY_FINALIZED` — and finalization is the
        authoritative re-score: the `risk_score` is recomputed from the same inputs and
        the `clearance` is re-banded, the review moves `DRAFT → FINALIZED`, its
        `finalized_by_user_id` records the acting `X-User-ID`, and any other review of
        the same case whose `status` was `FINALIZED` is moved to `SUPERSEDED`."

        The PRD states: "A superseded review no longer governs scheduling; the newer
        finalized review does."

        The PRD states: "Finalization refreshes the case's `escort_required`, setting it
        true when the resulting `clearance` is `CLEARED_WITH_ESCORT` and false
        otherwise, and increments the case's `version` by one."

        Design: Corner/errors/finalizing_a_safety_review_that_is_no_longer_draft_is_always_refused
        """
        bundle = setup_eligible_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
        )
        case_id = bundle["case"]["id"]

        first = record_safety_review(
            case_id,
            evidence_source="ONSITE_WALKTHROUGH",
            review_date="2026-09-02",
            hazard_findings=["UNLIT_ACCESS"],
            escort_available=False,
        )
        assert first["status"] == "DRAFT"
        assert first["clearance"] == "PENDING"
        assert first["scoring_variant"] == "ONSITE_VERIFIED"
        assert first["expires_on"] == "2026-11-01", (
            "sixty days past a 2026-09-02 walkthrough"
        )

        first = finalize_safety_review(first["id"])
        assert first["status"] == "FINALIZED"
        assert first["risk_score"] == 5, "one unlit-access finding, no escort discount"
        assert first["clearance"] == "CLEARED"
        assert first["finalized_by_user_id"] == CASE_MANAGER_USER_ID
        assert read_case(case_id)["escort_required"] is False

        validate_error(
            api_client.finalize_safety_review(first["id"], CM_HEADERS),
            ApiErrorId.ERR_REVIEW_ALREADY_FINALIZED.value,
            409,
        )
        untouched = _read_safety_review(first["id"])
        assert untouched["status"] == "FINALIZED"
        assert untouched["risk_score"] == 5
        assert untouched["clearance"] == "CLEARED"
        assert untouched["expires_on"] == "2026-11-01"

        second = record_safety_review(
            case_id,
            evidence_source="ONSITE_WALKTHROUGH",
            review_date="2026-09-03",
            hazard_findings=["NO_SECONDARY_EXIT"],
            escort_available=False,
        )
        second = validate_success(
            api_client.finalize_safety_review(second["id"], CM_HEADERS)
        )
        assert second["risk_score"] == 15, "one missing-secondary-exit finding"
        assert second["clearance"] == "CLEARED_WITH_ESCORT", (
            "fifteen points is the inclusive lower bound of the escort band"
        )
        assert read_case(case_id)["escort_required"] is True

        superseded = _read_safety_review(first["id"])
        assert superseded["status"] == "SUPERSEDED", (
            "the newer finalized review displaced the older one"
        )
        validate_error(
            api_client.finalize_safety_review(first["id"], CM_HEADERS),
            ApiErrorId.ERR_REVIEW_ALREADY_FINALIZED.value,
            409,
        )

        rows, meta = validate_paginated(
            api_client.list_safety_reviews(PA_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 2, "the refused finalizations created nothing"
        statuses = {row["id"]: row["status"] for row in rows}
        assert statuses == {first["id"]: "SUPERSEDED", second["id"]: "FINALIZED"}


class TestTheExtensionCeilingCountsApprovalsRatherThanAttempts:
    """Two approvals lift the entitlement; the third request never opens."""

    def test_the_third_request_is_refused_after_two_approvals_have_raised_the_bonus(
        self,
    ):
        """Each approval advances the certified window by its own requested days and feeds
        the effective absence duration, so the second one crosses the sixty-day threshold
        and the weekly entitlement climbs from 390 to 420 — reallocating the primary
        assignment and the teacher's committed load with it. The third request is then
        refused on the fiscal ceiling even though the case is ACTIVE and its version guard
        is current, so neither the concurrency check nor the state check preempts it.

        The PRD states: "A `CaseManager` requests one against an `ACTIVE` case, which
        advances `service_status` `ACTIVE → EXTENSION_PENDING` and increments the case's
        `version` by one."

        The PRD states: "The case's `extension_count` — the number of that case's
        extension requests whose `status` is `APPROVED` — must be less than 2, and a
        third attempt is rejected with `ERR_EXTENSION_LIMIT_REACHED`."

        The PRD states: "A new request starts with `status` `SUBMITTED`,
        `resubmit_count` 0, and `submitted_by_user_id` set to the acting `X-User-ID`."

        The PRD states: "Starting review moves the request `SUBMITTED → UNDER_REVIEW`,
        refreshing `updated_at` and changing nothing on the case."

        The PRD states: "Either decision stamps `decided_by_user_id` with the acting
        `X-User-ID`, moves the case `EXTENSION_PENDING → ACTIVE`, and increments the
        case's `version` by one — the loop `ACTIVE → EXTENSION_PENDING → ACTIVE` is
        deliberately cyclic, and `extension_count` reaching 2 is what terminates it."

        The PRD states: "An `APPROVED` decision moves the request `UNDER_REVIEW →
        APPROVED` and cascades into the case: `certified_end_date` is advanced by
        `requested_additional_days` calendar days from its current value,
        `extension_count` increments by one, `weekly_entitled_minutes` is recomputed per
        §3.3 — where the newly approved days now feed the effective absence duration and
        may cross a duration-bonus threshold — the weekly allocation is recomputed
        across the case's active assignments, and `committed_weekly_minutes` is
        recomputed for every affected teacher."

        The PRD states: "The effective absence duration is the current accepted
        certification's `expected_absence_days` plus the sum of
        `requested_additional_days` across every extension request of this case whose
        `status` is `APPROVED` — all of them, with no time window."

        The PRD states: "An effective duration of at least 60 calendar days earns a
        bonus of 60 minutes; failing that, an effective duration of at least 30 calendar
        days earns a bonus of 30 minutes; a shorter effective duration earns no bonus."

        The PRD states: "The entitlement is then the larger of the adjusted entitlement
        and the floor, and that larger value is finally clamped down to the rule's
        `cap_weekly_minutes` if it exceeds it."

        The PRD states: "When the case has no active support assignment the support
        total is 0."

        The PRD states: "The primary assignment nominally carries the remaining seventy
        percent, and concretely it receives the case's `weekly_entitled_minutes` minus
        the support total — so the primary row absorbs the entire rounding residual and
        the sum of `weekly_committed_minutes` across active assignments equals
        `weekly_entitled_minutes` exactly."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        Design: Corner/errors/the_third_extension_request_is_refused_after_two_approvals
        """
        bundle = setup_active_case(
            clock=CLOCK,
            activation_clock=ACTIVATION_CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        case_id = bundle["case"]["id"]
        certification_id = bundle["certification"]["id"]
        assert bundle["case"]["weekly_entitled_minutes"] == 390
        assert bundle["case"]["extension_count"] == 0

        first_request = validate_success(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    certification_id,
                    bundle["case"]["version"],
                    requested_additional_days=15,
                    justification="Surgical recovery extended by two weeks",
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert first_request["status"] == "SUBMITTED"
        assert first_request["resubmit_count"] == 0
        assert first_request["submitted_by_user_id"] == CASE_MANAGER_USER_ID
        assert read_case(case_id)["service_status"] == "EXTENSION_PENDING"

        under_review = validate_success(
            api_client.start_extension_review(first_request["id"], PA_HEADERS)
        )
        assert under_review["status"] == "UNDER_REVIEW"
        assert read_case(case_id)["service_status"] == "EXTENSION_PENDING", (
            "starting review changes nothing on the case"
        )

        decided = validate_success(
            api_client.decide_extension_request(
                first_request["id"],
                decide_extension_payload(
                    "APPROVED", decision_note="Updated documentation on file"
                ),
                PA_HEADERS,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == PROGRAM_ADMINISTRATOR_USER_ID

        after_one = read_case(case_id)
        assert after_one["service_status"] == "ACTIVE"
        assert after_one["extension_count"] == 1
        assert after_one["certified_end_date"] == "2026-10-22"
        assert after_one["weekly_entitled_minutes"] == 390, (
            "forty-five effective days still sits in the thirty-minute bonus band"
        )

        _approve_one_extension(case_id, certification_id, 15)

        after_two = read_case(case_id)
        assert after_two["service_status"] == "ACTIVE"
        assert after_two["extension_count"] == 2
        assert after_two["certified_end_date"] == "2026-11-06"
        assert after_two["weekly_entitled_minutes"] == 420, (
            "sixty effective days earns the sixty-minute bonus, still under the 480 cap"
        )

        assignment = read_assignment(bundle["primary_assignment"]["id"])
        assert assignment["weekly_committed_minutes"] == 420, (
            "the sole active primary row absorbs the whole entitlement"
        )
        assert read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 420

        validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    certification_id,
                    after_two["version"],
                    requested_additional_days=10,
                    justification="Third request",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_EXTENSION_LIMIT_REACHED.value,
            422,
        )

        requests = [
            row
            for row in _all(api_client.list_extension_requests)
            if row["case_id"] == case_id
        ]
        assert len(requests) == 2, "the refused third request was never persisted"
        assert {row["status"] for row in requests} == {"APPROVED"}

        final_case = read_case(case_id)
        assert final_case["service_status"] == "ACTIVE"
        assert final_case["version"] == after_two["version"], (
            "a refused request leaves the case version alone"
        )
