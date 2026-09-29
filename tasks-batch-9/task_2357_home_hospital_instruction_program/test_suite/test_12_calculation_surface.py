"""The derived numbers, and the decisions that hang off which band they land in.

A risk score is banded, and the band both flips a case flag and gates what may
then be scheduled. A weekly entitlement is re-resolved when the delivery mode
changes under it. An allocation share is rounded to a step, so the residual has
to land somewhere. Two apportionment figures read different input sets over the
same sessions, and the settlement ratio is taken before recapture, never after.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    accept_assignment,
    activate_case,
    api_client,
    create_session_payload,
    finalize_safety_review,
    ledger_entries_for_case,
    log_session,
    log_session_delivered,
    log_student_unavailable_payload,
    make_homebound_teacher_headers,
    open_case,
    open_sped_service_log,
    propose_assignment,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    record_safety_review,
    record_sped_delivery_payload,
    register_student,
    register_teacher,
    review_certification,
    schedule_session,
    sessions_for_case,
    set_clock,
    setup_active_case,
    setup_case_with_primary_assignment,
    setup_catalogue,
    setup_eligible_case,
    sped_continuation_payload,
    submit_certification,
    validate_error,
    validate_success,
    verify_session,
    void_session_payload,
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

# A published MIDDLE / VIRTUAL_SYNC rule whose base is 300 weekly minutes.
VIRTUAL_RULE = {
    "grade_band": "MIDDLE",
    "delivery_mode": "VIRTUAL_SYNC",
    "base_weekly_minutes": 300,
    "cap_weekly_minutes": 480,
    "min_session_minutes": 30,
    "max_session_minutes": 120,
    "max_daily_minutes": 240,
    "min_gap_minutes": 15,
    "travel_buffer_minutes": 0,
}

IEP_STUDENT = {
    "student_number": "S-0003",
    "full_name": "Cara Voss",
    "grade_level": 7,
    "special_ed_status": "IEP",
    "iep_service_minutes_weekly": 300,
}


def _book(case_id: str, assignment_id: str, **overrides):
    return api_client.create_session(
        create_session_payload(case_id, assignment_id, **overrides), CM_HEADERS
    )


def _case_needing_an_escort() -> dict:
    """An ACTIVE in-home case whose governing finalized review scores exactly 20 and so
    bands CLEARED_WITH_ESCORT rather than CLEARED."""
    bundle = setup_case_with_primary_assignment(
        clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
    )
    case_id = bundle["case"]["id"]
    bundle["draft_review"] = record_safety_review(
        case_id,
        hazard_findings=["NO_SECONDARY_EXIT", "UNLIT_ACCESS"],
        escort_available=False,
    )
    bundle["safety_review"] = finalize_safety_review(bundle["draft_review"]["id"])
    set_clock(ACTIVATION_CLOCK)
    bundle["case"] = activate_case(case_id)
    return bundle


def _two_cases_facing_the_same_hazards() -> dict:
    """Two ELIGIBLE in-home cases, each with an accepted primary assignment, one
    catalogue holding both a MIDDLE / IN_HOME and a MIDDLE / VIRTUAL_SYNC rule."""
    rules = setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE, VIRTUAL_RULE])
    bundle = {"in_home_rule": rules[0], "virtual_rule": rules[1]}

    plan = (
        ("attested", "E-1001", {}, "1234567890"),
        (
            "onsite",
            "E-1002",
            {"student_number": "S-0002", "full_name": "Ben Oyo", "grade_level": 8},
            "1234567891",
        ),
    )
    for key, employee_number, student_overrides, npi in plan:
        student = register_student(**student_overrides)
        teacher = register_teacher(
            full_name=f"Teacher {key}", employee_number=employee_number
        )
        case = open_case(student["id"], delivery_mode="IN_HOME")
        certification = submit_certification(
            case["id"], physician_npi=npi, **CERT_WINDOW
        )
        review_certification(certification["id"], "ACCEPT")
        assignment = propose_assignment(case["id"], "PRIMARY", teacher["id"])
        bundle[f"{key}_teacher"] = teacher
        bundle[f"{key}_assignment"] = accept_assignment(
            assignment["id"], teacher["id"]
        )
        bundle[f"{key}_case"] = read_case(case["id"])
    return bundle


def _case_with_a_speech_service_log() -> dict:
    """An ACTIVE case for an IEP student carrying one SPEECH continuation log that owes
    60 minutes a week, with service_start_date 2026-09-07."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        student=dict(IEP_STUDENT),
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    bundle["log"] = open_sped_service_log(
        bundle["case"]["id"], service_type="SPEECH", required_weekly_minutes=60
    )
    return bundle


def _case_with_five_sessions_in_five_postures() -> dict:
    """An ACTIVE case whose five in-home sessions end up DELIVERED, STUDENT_UNAVAILABLE,
    CANCELLED_ADMIN, still SCHEDULED, and VOIDED, with the clock at 2026-09-10T16:00."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    assignment_id = bundle["primary_assignment"]["id"]
    teacher_id = bundle["teacher"]["id"]

    plan = (
        ("delivered", "2026-09-07T09:00:00Z", "2026-09-07T11:00:00Z", "MATH"),
        ("absent", "2026-09-07T13:00:00Z", "2026-09-07T15:00:00Z", "ELA"),
        ("cancelled", "2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z", "MATH"),
        ("scheduled", "2026-09-09T09:00:00Z", "2026-09-09T10:00:00Z", "SCIENCE"),
        ("voided", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z", "ELA"),
    )
    for key, start, end, subject in plan:
        bundle[key] = schedule_session(
            case_id,
            assignment_id,
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject=subject,
        )

    validate_success(api_client.cancel_session(bundle["cancelled"]["id"], PA_HEADERS))
    set_clock("2026-09-10T16:00:00Z")
    log_session_delivered(bundle["delivered"]["id"], teacher_id, 120)
    log_session(
        bundle["absent"]["id"],
        teacher_id,
        log_student_unavailable_payload("MEDICAL", outcome_reason="Fever"),
    )
    log_session_delivered(bundle["voided"]["id"], teacher_id, 120)
    validate_success(
        api_client.void_session(
            bundle["voided"]["id"],
            void_session_payload(void_reason="DOCUMENTATION_DEFECT"),
            PA_HEADERS,
        )
    )
    return bundle


def _case_with_two_verified_visits() -> dict:
    """An ACTIVE / ACCRUING case at 390 weekly minutes holding two verified 120-minute
    in-home visits inside one ISO week, with the clock at 2026-09-09T09:00:00Z."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    for key, start, end, subject in (
        ("monday", "2026-09-07T09:00:00Z", "2026-09-07T11:00:00Z", "MATH"),
        ("tuesday", "2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z", "ELA"),
    ):
        bundle[key] = schedule_session(
            case_id,
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject=subject,
        )
    set_clock("2026-09-08T16:00:00Z")
    for key in ("monday", "tuesday"):
        log_session_delivered(bundle[key]["id"], bundle["teacher"]["id"], 120)
        bundle[key] = verify_session(bundle[key]["id"])
    set_clock("2026-09-09T09:00:00Z")
    return bundle


class TestTheEscortBandFlipsACaseFlagAndGatesScheduling:
    """Twenty points is not merely a number; it is a precondition on every visit."""

    def test_a_score_of_twenty_requires_an_escort_on_every_in_home_visit(self):
        """Fifteen plus five undiscounted lands in the escort band, which sets the case's
        escort_required, after which the same in-home visit is refused without a
        confirmed escort and accepted with one.

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

        The PRD states: "The server also derives `expires_on` as the `review_date`
        advanced by sixty days, and computes an initial `risk_score`."

        The PRD states: "Finalization refreshes the case's `escort_required`, setting it
        true when the resulting `clearance` is `CLEARED_WITH_ESCORT` and false
        otherwise, and increments the case's `version` by one."

        The PRD states: "Activation advances `service_status` `ELIGIBLE → ACTIVE`, sets
        `service_start_date` to the clock date, refreshes `escort_required` from the
        governing finalized review, moves `funding_status` `NOT_REPORTED → ACCRUING` in
        the same request with `service_gap_minutes` initialized to 0, and increments the
        case's `version` by one."

        The PRD states: "Finally, when the case's `escort_required` is true and the
        session's `delivery_mode` is `IN_HOME`, the payload must supply
        `escort_confirmed` as true, or the request is rejected with
        `ERR_ESCORT_REQUIRED_NOT_CONFIRMED`."

        The PRD states: "From those two instants the server derives `scheduled_minutes`
        as the whole-minute span between them and `service_date` as the UTC calendar
        date of `scheduled_start`."

        Design: Corner/calculations/onsite_escort_band_sets_case_escort_required_and_gates_in_home_scheduling
        """
        bundle = _case_needing_an_escort()
        case_id = bundle["case"]["id"]
        assignment_id = bundle["primary_assignment"]["id"]

        draft = bundle["draft_review"]
        assert draft["scoring_variant"] == "ONSITE_VERIFIED"
        assert draft["risk_score"] == 20, "15 plus 5, with no escort mitigation to apply"
        assert draft["status"] == "DRAFT"
        assert draft["clearance"] == "PENDING"
        assert draft["expires_on"] == "2026-11-01", "sixty days past 2026-09-02"

        finalized = bundle["safety_review"]
        assert finalized["status"] == "FINALIZED"
        assert finalized["risk_score"] == 20, "the re-score reaches the same figure"
        assert finalized["clearance"] == "CLEARED_WITH_ESCORT", (
            "20 clears the 15-point lower bound but not the 35-point one"
        )

        case = bundle["case"]
        assert case["service_status"] == "ACTIVE"
        assert case["escort_required"] is True
        assert case["service_start_date"] == "2026-09-07"

        window = {
            "scheduled_start": "2026-09-08T09:00:00Z",
            "scheduled_end": "2026-09-08T10:00:00Z",
            "delivery_mode": "IN_HOME",
            "subject": "MATH",
        }
        validate_error(
            _book(case_id, assignment_id, **window),
            ApiErrorId.ERR_ESCORT_REQUIRED_NOT_CONFIRMED.value,
            422,
        )
        assert sessions_for_case(case_id) == [], (
            "the refused visit was never put on the calendar"
        )

        booked = validate_success(
            _book(case_id, assignment_id, escort_confirmed=True, **window), 201
        )
        assert booked["status"] == "SCHEDULED"
        assert booked["scheduled_minutes"] == 60
        assert booked["service_date"] == "2026-09-08"
        assert [row["id"] for row in sessions_for_case(case_id)] == [booked["id"]]


class TestTheEvidenceSourceAloneDecidesTheOutcome:
    """One hazard set, two review paths, two entirely different consequences."""

    def test_an_attested_seventy_goes_virtual_while_a_verified_seventy_is_blocked(self):
        """The parent-attested review discounts to 53 and forces the case onto a virtual
        rule at 330 minutes; the walked-through review of the very same hazards scores 60,
        lands exactly on the blocking bound, and refuses activation.

        The PRD states: "Under `SELF_REPORTED`, the raw sum is multiplied by 0.75,
        rounded half up to a whole point, and then capped at 100; `escort_available` is
        ignored entirely, on the reasoning that a parent attestation cannot vouch for an
        escort arrangement."

        The PRD states: "Under `ONSITE_VERIFIED`, the raw sum is used undiscounted, a
        flat 10 points of escort mitigation is subtracted when `escort_available` is
        true and nothing is subtracted when it is false, the result is floored at 0, and
        it is capped at 100."

        The PRD states: "`clearance` is banded from `risk_score` with inclusive lower
        bounds: `BLOCKED` at 60 points or above, otherwise `VIRTUAL_ONLY` at 35 points
        or above, otherwise `CLEARED_WITH_ESCORT` at 15 points or above, otherwise
        `CLEARED`."

        The PRD states: "When the resulting `clearance` is `VIRTUAL_ONLY` and the case's
        `delivery_mode` is `IN_HOME` or `HYBRID`, the case's `delivery_mode` is
        rewritten to `VIRTUAL_SYNC`; its `entitlement_rule_id` is re-resolved against
        the student's `grade_band` paired with `VIRTUAL_SYNC`, failing with
        `ERR_NO_PUBLISHED_ENTITLEMENT_RULE` when no published rule covers that pair; its
        `weekly_entitled_minutes` is recomputed per §3.3; the weekly allocation is
        recomputed across the case's active assignments; `committed_weekly_minutes` and
        `over_cap` are recomputed for every affected teacher; and every session of that
        case whose `status` is `SCHEDULED` and whose own `delivery_mode` is `IN_HOME` is
        moved to `CANCELLED_ADMIN`."

        The PRD states: "An effective duration of at least 60 calendar days earns a
        bonus of 60 minutes; failing that, an effective duration of at least 30 calendar
        days earns a bonus of 30 minutes; a shorter effective duration earns no bonus."

        The PRD states: "And when the case's `delivery_mode` is `IN_HOME` or `HYBRID`, a
        review of that case must exist with `status` `FINALIZED` and `clearance` either
        `CLEARED` or `CLEARED_WITH_ESCORT`: no finalized review at all is
        `ERR_SAFETY_REVIEW_MISSING`, and a finalized review whose `clearance` is
        `BLOCKED` is `ERR_SAFETY_CLEARANCE_BLOCKED`."

        Design: Corner/calculations/blocked_clearance_is_selected_by_evidence_source_and_stops_activation
        """
        bundle = _two_cases_facing_the_same_hazards()
        hazards = {
            "hazard_findings": ["WEAPON_PRESENT_UNSECURED", "ACTIVE_INFECTION_RISK"],
            "escort_available": True,
        }
        assert bundle["attested_case"]["weekly_entitled_minutes"] == 390
        assert bundle["onsite_case"]["weekly_entitled_minutes"] == 390

        attested = record_safety_review(
            bundle["attested_case"]["id"],
            evidence_source="PARENT_ATTESTATION",
            **hazards,
        )
        assert attested["scoring_variant"] == "SELF_REPORTED"
        assert attested["risk_score"] == 53, (
            "seventy raw points discounted by a quarter and rounded half up"
        )
        attested_final = finalize_safety_review(attested["id"])
        assert attested_final["status"] == "FINALIZED"
        assert attested_final["risk_score"] == 53
        assert attested_final["clearance"] == "VIRTUAL_ONLY"

        onsite = record_safety_review(
            bundle["onsite_case"]["id"],
            evidence_source="ONSITE_WALKTHROUGH",
            **hazards,
        )
        assert onsite["scoring_variant"] == "ONSITE_VERIFIED"
        assert onsite["risk_score"] == 60, "seventy raw points less ten for the escort"
        onsite_final = finalize_safety_review(onsite["id"])
        assert onsite_final["status"] == "FINALIZED"
        assert onsite_final["risk_score"] == 60
        assert onsite_final["clearance"] == "BLOCKED", (
            "the lower bound is inclusive, so exactly 60 blocks"
        )

        set_clock(ACTIVATION_CLOCK)
        validate_error(
            api_client.activate_case(bundle["onsite_case"]["id"], PA_HEADERS),
            ApiErrorId.ERR_SAFETY_CLEARANCE_BLOCKED.value,
            422,
        )
        blocked_case = read_case(bundle["onsite_case"]["id"])
        assert blocked_case["service_status"] == "ELIGIBLE"
        assert blocked_case["funding_status"] == "NOT_REPORTED"

        rerouted = read_case(bundle["attested_case"]["id"])
        assert rerouted["delivery_mode"] == "VIRTUAL_SYNC"
        assert rerouted["entitlement_rule_id"] == bundle["virtual_rule"]["id"], (
            "the virtual pair was re-resolved out of the same catalogue"
        )
        assert rerouted["weekly_entitled_minutes"] == 330, (
            "300 base at a factor of one, plus the thirty-day duration bonus"
        )
        assert (
            read_assignment(bundle["attested_assignment"]["id"])[
                "weekly_committed_minutes"
            ]
            == 330
        ), "the allocation followed the re-resolved entitlement"


class TestTheCompensatoryBalanceCountsWholeWeeksOnly:
    """A partial week owes nothing, and a frozen delivery total keeps owing more."""

    def test_the_owed_balance_waits_for_whole_weeks_then_grows_through_a_suspension(self):
        """Six days after the service start the balance is still zero even against a
        single delivery; at twenty-one days it is 90; and a suspension that freezes the
        delivered total lets the twenty-eight-day balance reach 150.

        The PRD states: "Count the weeks elapsed as the number of whole seven-day spans
        between the case's `service_start_date` and the clock date, taking the floor,
        and treating the count as 0 when `service_start_date` is null."

        The PRD states: "Multiply that count by the log's `required_weekly_minutes`,
        subtract `delivered_cumulative_minutes`, and floor the difference at 0."

        The PRD states: "This is recomputed when a log is opened, whenever a delivery is
        recorded, and on every continuation-status change."

        The PRD states: "Recording adds `minutes` to `delivered_cumulative_minutes` and
        sets `last_service_date` to the supplied `service_date`."

        The PRD states: "From either `CONTINUED` or `MODIFIED_VIRTUAL` the log may move
        to `SUSPENDED_PENDING_IEP`, which freezes `delivered_cumulative_minutes` — while
        a log is suspended, any attempt to record delivered minutes against it is
        rejected with `ERR_SPED_SERVICE_SUSPENDED` — while `compensatory_minutes_owed`
        keeps accruing with each elapsed week, so the suspension window accumulates as a
        debt."

        The PRD states: "When the student's `special_ed_status` is `IEP`, the floor is
        the student's `iep_service_minutes_weekly` multiplied by 0.60 and rounded half
        up to a whole minute; for any other special-education status the floor is 0."

        The PRD states: "The entitlement is then the larger of the adjusted entitlement
        and the floor, and that larger value is finally clamped down to the rule's
        `cap_weekly_minutes` if it exceeds it."

        Design: Corner/calculations/sped_compensatory_balance_uses_floor_weeks_and_grows_while_suspended
        """
        bundle = _case_with_a_speech_service_log()
        log_id = bundle["log"]["id"]
        teacher_headers = make_homebound_teacher_headers(bundle["teacher"]["id"])

        assert bundle["log"]["continuation_status"] == "CONTINUED"
        assert bundle["log"]["delivered_cumulative_minutes"] == 0
        assert bundle["log"]["compensatory_minutes_owed"] == 0, (
            "no whole week has elapsed on the service start date itself"
        )

        set_clock("2026-09-13T09:00:00Z")
        first = validate_success(
            api_client.record_sped_delivery(
                log_id,
                record_sped_delivery_payload(minutes=60, service_date="2026-09-08"),
                teacher_headers,
            )
        )
        assert first["delivered_cumulative_minutes"] == 60
        assert first["last_service_date"] == "2026-09-08"
        assert first["compensatory_minutes_owed"] == 0, (
            "six elapsed days floor to zero whole weeks, so nothing is yet owed"
        )

        set_clock("2026-09-28T09:00:00Z")
        second = validate_success(
            api_client.record_sped_delivery(
                log_id,
                record_sped_delivery_payload(minutes=30, service_date="2026-09-25"),
                CM_HEADERS,
            )
        )
        assert second["delivered_cumulative_minutes"] == 90
        assert second["compensatory_minutes_owed"] == 90, "three weeks of 60 less 90"

        set_clock("2026-10-05T09:00:00Z")
        suspended = validate_success(
            api_client.change_sped_continuation(
                log_id,
                sped_continuation_payload(
                    "SUSPENDED_PENDING_IEP",
                    continuation_reason="Awaiting IEP amendment meeting",
                ),
                CM_HEADERS,
            )
        )
        assert suspended["continuation_status"] == "SUSPENDED_PENDING_IEP"
        assert suspended["delivered_cumulative_minutes"] == 90, (
            "the delivered total is frozen where the suspension found it"
        )
        assert suspended["compensatory_minutes_owed"] == 150, (
            "a fourth week accrues against a frozen delivery total"
        )

        case = read_case(bundle["case"]["id"])
        assert case["weekly_entitled_minutes"] == 390, (
            "the special-education floor of 180 never rises above the adjusted 390"
        )


class TestTheProvisionalSetAndTheLedgerReadDifferentSessions:
    """Five sessions, five postures, and two figures that must not agree."""

    def test_only_the_delivered_and_still_scheduled_visits_enter_the_provisional_total(
        self,
    ):
        """The absent, cancelled and voided visits are all excluded, so the provisional
        figure is 180 while the ledger-derived figure is 120 — and the gap between them is
        exactly the sixty projected minutes of the visit not yet served.

        The PRD states: "Its input set is that case's sessions whose `status` is
        `SCHEDULED` or `DELIVERED` and whose `service_date` falls between
        `service_start_date` and `certified_end_date` inclusive on both ends; sessions
        that are `VOIDED`, `CANCELLED_ADMIN`, `STUDENT_UNAVAILABLE`, `TEACHER_CANCELLED`
        or `SAFETY_ABORTED` never participate, and verification is ignored entirely."

        The PRD states: "Each `DELIVERED` session contributes its `credited_minutes`."

        The PRD states: "Each still-`SCHEDULED` session contributes a projected credit
        computed the same way delivered credit is computed but from the plan rather than
        from the report: take the lesser of that session's `scheduled_minutes` and the
        rule's `max_session_minutes`, multiply by 0.90 when the session's
        `delivery_mode` is `VIRTUAL_SYNC` and by 1.00 when it is `IN_HOME`, divide by
        five, round half up, and multiply back by five."

        The PRD states: "Those contributions are summed into a raw provisional total,
        and the total is capped once — over the whole certified window rather than week
        by week — at the case's `weekly_entitled_minutes` multiplied by the number of
        window weeks, where window weeks is the number of days separating
        `service_start_date` from `certified_end_date`, plus one, divided by seven and
        rounded up to a whole week."

        The PRD states: "Count the completed service weeks as the number of whole
        seven-day spans between the case's `service_start_date` and the clock date,
        taking the floor so a partial week contributes nothing."

        The PRD states: "The final input set is that case's sessions whose `status` is
        `DELIVERED` *and* which carry a non-null `verified_at`, whose `service_date`
        falls between `service_start_date` and `certified_end_date` inclusive on both
        ends."

        The PRD states: "It returns the `case_id`, the case's `weekly_entitled_minutes`,
        the `window_weeks` and `service_weeks` counts, the `entitled_total_minutes`
        those counts imply, the `provisional_minutes` and `final_verified_minutes`
        figures, a `projected_unrounded_minutes` diagnostic, the case's current
        `reported_apportionment_minutes`, `service_gap_minutes`, `delivery_ratio_pct`,
        `recapture_minutes`, `net_apportionment_minutes`, and `funding_status`."

        The PRD states: "A `ProgramAdministrator` may cancel a `SCHEDULED` session,
        moving it `SCHEDULED → CANCELLED_ADMIN`; no ledger row is written and the case's
        `makeup_obligation_minutes` is unchanged."

        Design: Corner/calculations/provisional_accrual_input_set_drops_cancelled_absent_and_voided_sessions
        """
        bundle = _case_with_five_sessions_in_five_postures()
        case_id = bundle["case"]["id"]

        assert read_session(bundle["delivered"]["id"])["status"] == "DELIVERED"
        assert read_session(bundle["absent"]["id"])["status"] == "STUDENT_UNAVAILABLE"
        assert read_session(bundle["cancelled"]["id"])["status"] == "CANCELLED_ADMIN"
        assert read_session(bundle["scheduled"]["id"])["status"] == "SCHEDULED"
        assert read_session(bundle["voided"]["id"])["status"] == "VOIDED"

        reported = validate_success(
            api_client.report_case_funding(case_id, PA_HEADERS)
        )
        assert reported["provisional_apportionment_minutes"] == 180, (
            "120 credited plus 60 projected, well under the 1950-minute window cap"
        )
        assert reported["reported_apportionment_minutes"] == 120, (
            "the ledger sums 120 plus 0 plus 120 less 120"
        )
        assert reported["funding_status"] == "ACCRUING"
        assert reported["service_gap_minutes"] == 0, (
            "three elapsed days floor to zero completed service weeks"
        )

        summary = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert summary["case_id"] == case_id
        assert summary["weekly_entitled_minutes"] == 390
        assert summary["window_weeks"] == 5
        assert summary["service_weeks"] == 1
        assert summary["entitled_total_minutes"] == 390
        assert summary["provisional_minutes"] == 180
        assert summary["final_verified_minutes"] == 0, (
            "neither delivered visit was ever verified"
        )
        assert summary["reported_apportionment_minutes"] == 120
        assert summary["delivery_ratio_pct"] == 0.00

        entries = ledger_entries_for_case(case_id)
        assert len(entries) == 4, "the cancelled visit never produced a ledger row"
        assert [entry["attendance_code"] for entry in entries] == [
            "HB_PRESENT",
            "HB_ABSENT_MEDICAL",
            "HB_PRESENT",
            "HB_REVERSAL",
        ]
        assert [entry["apportionment_minutes"] for entry in entries] == [
            120,
            0,
            120,
            -120,
        ]


class TestTheSupportShareRoundsToAStepAndThePrimaryAbsorbsTheRest:
    """Eighty-one minutes is not a legal share, so somebody has to carry the four."""

    def test_a_share_of_eighty_one_rounds_down_to_eighty_and_the_primary_takes_one_ninety(
        self,
    ):
        """On a 270-minute virtual case the thirty-percent share rounds to 80 rather than
        85, and the primary row lands on 190 so the two active rows still sum to exactly
        270.

        The PRD states: "Take that rule's `base_weekly_minutes` and multiply it by a
        diagnosis factor determined by the case's `diagnosis_category`: the factor is
        1.00 for `MEDICAL_ACUTE`, 1.00 for `MEDICAL_CHRONIC`, 0.80 for `PSYCHIATRIC`,
        0.90 for `PREGNANCY_POSTPARTUM`, and 1.00 for `INJURY_REHAB`."

        The PRD states: "An effective duration of at least 60 calendar days earns a
        bonus of 60 minutes; failing that, an effective duration of at least 30 calendar
        days earns a bonus of 30 minutes; a shorter effective duration earns no bonus."

        The PRD states: "Support staff share thirty percent of the entitlement: when the
        case has at least one active support assignment, multiply
        `weekly_entitled_minutes` by 0.30, divide by the number of active support
        assignments, divide by five, round half up to a whole number, and multiply back
        by five; every active support assignment receives that same per-support figure,
        and the support total is that figure multiplied by the number of support
        assignments."

        The PRD states: "When the case has no active support assignment the support
        total is 0."

        The PRD states: "The primary assignment nominally carries the remaining seventy
        percent, and concretely it receives the case's `weekly_entitled_minutes` minus
        the support total — so the primary row absorbs the entire rounding residual and
        the sum of `weekly_committed_minutes` across active assignments equals
        `weekly_entitled_minutes` exactly."

        The PRD states: "A teacher whose `safety_clearance_status` is `EXPIRED` may not
        accept at all, and that rejection carries `ERR_TEACHER_CLEARANCE_EXPIRED`."

        The PRD states: "The derived flag `over_cap` is true when
        `committed_weekly_minutes` is strictly greater than that teacher's
        `max_weekly_caseload_minutes`, and false when the two are equal."

        Design: Corner/calculations/support_share_rounds_to_the_allocation_step_and_the_primary_row_absorbs_the_residual
        """
        bundle = setup_eligible_case(
            clock=CLOCK,
            rules=[VIRTUAL_RULE],
            case={"delivery_mode": "VIRTUAL_SYNC"},
            certification={
                "diagnosis_category": "PREGNANCY_POSTPARTUM",
                "certified_start_date": "2026-09-07",
                "certified_end_date": "2026-09-27",
                "expected_absence_days": 20,
                "signature_date": "2026-09-01",
            },
        )
        case_id = bundle["case"]["id"]
        assert bundle["case"]["weekly_entitled_minutes"] == 270, (
            "300 at a factor of 0.90, and twenty absence days earn no bonus"
        )
        assert bundle["case"]["entitlement_rule_id"] == bundle["rule"]["id"]
        assert bundle["case"]["service_status"] == "ELIGIBLE"

        primary_teacher = register_teacher(
            max_weekly_caseload_minutes=600, home_visit_eligible=False
        )
        support_teacher = register_teacher(
            full_name="Sam Duro",
            employee_number="E-1002",
            credential_areas=["SCIENCE"],
            grade_bands=["MIDDLE"],
            max_weekly_caseload_minutes=600,
            safety_clearance_status="RESTRICTED",
            home_visit_eligible=False,
        )

        primary_proposal = propose_assignment(case_id, "PRIMARY", primary_teacher["id"])
        primary = accept_assignment(primary_proposal["id"], primary_teacher["id"])
        assert primary["status"] == "ACTIVE"
        assert primary["weekly_committed_minutes"] == 270, (
            "with no support row yet the primary carries the whole entitlement"
        )

        support_proposal = propose_assignment(case_id, "SUPPORT", support_teacher["id"])
        support = accept_assignment(support_proposal["id"], support_teacher["id"])
        assert support["status"] == "ACTIVE", (
            "only an expired clearance bars acceptance, and this one is restricted"
        )
        assert support["weekly_committed_minutes"] == 80, (
            "eighty-one rounds to the nearest step of five as 80, not 85"
        )

        primary_after = read_assignment(primary["id"])
        assert primary_after["weekly_committed_minutes"] == 190
        assert (
            primary_after["weekly_committed_minutes"]
            + support["weekly_committed_minutes"]
            == 270
        ), "the residual has to land on the primary row for the sum to be exact"

        primary_read = read_teacher(primary_teacher["id"])
        assert primary_read["committed_weekly_minutes"] == 190
        assert primary_read["over_cap"] is False
        support_read = read_teacher(support_teacher["id"])
        assert support_read["committed_weekly_minutes"] == 80
        assert support_read["over_cap"] is False


class TestTheSettlementRatioIsTakenBeforeRecapture:
    """And the two refusals that follow it are deliberately different codes."""

    def test_a_ratio_of_sixty_two_recaptures_a_quarter_of_the_shortfall_then_locks(self):
        """240 verified minutes against an entitled 390 gives 0.62, which recaptures a
        quarter of the 150-minute shortfall as 38 and nets 202; a second reconcile is
        refused as already reconciled, and once voids push the gap to a full entitlement
        the refusal changes to not-accruing.

        The PRD states: "Count elapsed weeks as the number of days separating
        `service_start_date` from the clock date, plus one, divided by seven and rounded
        up to a whole week; count window weeks the same way, from `service_start_date`
        to `certified_end_date`; and take service weeks as the lesser of the two, so a
        case reconciled early is measured against elapsed time and a case reconciled
        late is measured against its window."

        The PRD states: "The entitled total is the case's `weekly_entitled_minutes`
        multiplied by service weeks."

        The PRD states: "`delivery_ratio_pct` is 0.00 when the entitled total is zero,
        and otherwise the raw final figure divided by the entitled total, rounded half
        up to two decimal places."

        The PRD states: "The ratio is always computed on the raw final figure before any
        recapture, never on the net."

        The PRD states: "A ratio below 0.75 but at least 0.50 recaptures twenty-five
        percent."

        The PRD states: "In the three non-forfeit bands the shortfall is the entitled
        total minus the raw final figure, floored at 0; `final_apportionment_minutes` is
        set to the raw final figure; `recapture_minutes` is the shortfall multiplied by
        the band's recapture rate, rounded half up to whole minutes;
        `net_apportionment_minutes` is the raw final figure minus `recapture_minutes`,
        floored at 0; and the funding posture moves `ACCRUING → RECONCILED`."

        The PRD states: "Reconciliation requires the case's `funding_status` to be
        `ACCRUING`, rejecting `NOT_REPORTED`, `HELD` and `FORFEITED` with
        `ERR_FUNDING_NOT_ACCRUING` and rejecting an already-reconciled case with the
        more specific `ERR_FUNDING_ALREADY_RECONCILED`, and it requires the case's
        `service_status` to be `ACTIVE`, `EXTENSION_PENDING`, `TRANSITION_PLANNED` or
        `CLOSED`, rejecting others with `ERR_INVALID_CASE_STATE`."

        The PRD states: "When the recomputed gap reaches or exceeds exactly one weekly
        entitlement — that is, when `service_gap_minutes` is greater than or equal to
        `weekly_entitled_minutes` — and the case's `funding_status` is `ACCRUING` or
        `RECONCILED`, the funding posture moves to `HELD`."

        The PRD states: "It appends a compensating ledger row with `attendance_code`
        `HB_REVERSAL`, whose `reversal_of_entry_id` points at the entry being reversed
        and whose `apportionment_minutes` is the arithmetic negation of that entry's
        `apportionment_minutes`."

        Design: Corner/calculations/reconciliation_recaptures_on_the_raw_ratio_then_refuses_repeat_and_held_reconciles
        """
        bundle = _case_with_two_verified_visits()
        case_id = bundle["case"]["id"]

        settled = validate_success(
            api_client.reconcile_case_funding(case_id, PA_HEADERS)
        )
        assert settled["final_apportionment_minutes"] == 240
        assert settled["delivery_ratio_pct"] == 0.62, (
            "240 over 390 rounded half up to two places, taken on the raw figure"
        )
        assert settled["recapture_minutes"] == 38, (
            "a quarter of the 150-minute shortfall, rounded half up from 37.5"
        )
        assert settled["net_apportionment_minutes"] == 202
        assert settled["funding_status"] == "RECONCILED"

        repeat = validate_error(
            api_client.reconcile_case_funding(case_id, PA_HEADERS),
            ApiErrorId.ERR_FUNDING_ALREADY_RECONCILED.value,
            409,
        )
        assert repeat["error_id"] != ApiErrorId.ERR_FUNDING_NOT_ACCRUING.value, (
            "an already-reconciled case gets the more specific of the two codes"
        )
        assert read_case(case_id)["net_apportionment_minutes"] == 202

        set_clock("2026-09-14T09:00:00Z")
        validate_success(
            api_client.void_session(
                bundle["monday"]["id"],
                void_session_payload(void_reason="AUDIT_REVERSAL"),
                PA_HEADERS,
            )
        )
        after_first_void = read_case(case_id)
        assert after_first_void["reported_apportionment_minutes"] == 120
        assert after_first_void["service_gap_minutes"] == 270
        assert after_first_void["funding_status"] == "RECONCILED", (
            "270 is short of a full weekly entitlement, so no hold opens yet"
        )

        validate_success(
            api_client.void_session(
                bundle["tuesday"]["id"],
                void_session_payload(void_reason="AUDIT_REVERSAL"),
                PA_HEADERS,
            )
        )
        after_second_void = read_case(case_id)
        assert after_second_void["reported_apportionment_minutes"] == 0
        assert after_second_void["service_gap_minutes"] == 390
        assert after_second_void["funding_status"] == "HELD", (
            "a gap equal to one weekly entitlement reopens the settled case"
        )

        held = validate_error(
            api_client.reconcile_case_funding(case_id, PA_HEADERS),
            ApiErrorId.ERR_FUNDING_NOT_ACCRUING.value,
            409,
        )
        assert held["error_id"] != ApiErrorId.ERR_FUNDING_ALREADY_RECONCILED.value, (
            "the posture is no longer RECONCILED, so the general code answers"
        )

        entries = ledger_entries_for_case(case_id)
        assert [entry["apportionment_minutes"] for entry in entries] == [
            120,
            120,
            -120,
            -120,
        ]
        assert sum(entry["apportionment_minutes"] for entry in entries) == 0
