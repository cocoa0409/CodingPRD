"""Non-linear lifecycles: four parallel enrollment dimensions and the bounded remand cycle."""

from test_helpers import (
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_instant,
    assert_instant_null,
    expected_risk_score,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

SWEEP_INSTANT = "2027-06-02T00:00:00Z"
CURE_DEADLINE = "2027-06-17T23:59:59.999Z"
RECERT_DEADLINE = "2027-08-01T23:59:59.999Z"
USAGE_INSTANT = "2027-06-10T00:00:00Z"


def _benefit_with_handset_swept_at_the_notice_window(api):
    """One never-used benefit holding a handset, swept on the day its notice window opens."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    provider = fx.register_provider(api)
    device = fx.stock_device(api, provider)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    enrollment = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date="2026-08-01T00:00:00Z",
    )
    fx.issue_device(api, enrollment["id"], provider, device_id=device["id"])

    fx.set_clock(api, SWEEP_INSTANT)
    sweep = fx.sweep(api, provider["id"])
    return {
        "provider": provider,
        "device": device,
        "enrollment": enrollment,
        "sweep": sweep,
        "agent": fx.provider_headers(provider),
    }


def test_one_sweep_leaves_the_benefit_in_four_different_postures_at_once(api):
    """A single sweep flags non-usage and notices recertification while custody and the benefit hold.

    PRD: "They advance on unrelated triggers; nothing about a benefit's usage posture
    constrains its recertification posture, and a benefit can be simultaneously `ACTIVE`,
    `NON_USAGE_FLAGGED`, `NOTICED` and `DEVICE_ISSUED`."

    Design: Difficulty/non_linear_state_machine/enrollment_four_parallel_dimensions_advance_independently
    """
    context = _benefit_with_handset_swept_at_the_notice_window(api)
    enrollment_id = context["enrollment"]["id"]
    sweep = context["sweep"]

    assert sweep["non_usage_flagged_enrollment_ids"] == [enrollment_id], (
        "the never-used benefit is flagged by step one"
    )
    assert sweep["recert_noticed_enrollment_ids"] == [enrollment_id], (
        "step three notices the same benefit in the same request"
    )
    assert sweep["cure_expired_de_enrolled_enrollment_ids"] == [], (
        "step one wrote a future cure deadline, so step two cannot expire it"
    )
    assert sweep["recert_non_response_de_enrolled_enrollment_ids"] == []

    benefit = fx.refresh_enrollment(api, enrollment_id)
    assert benefit["benefit_status"] == "ACTIVE"
    assert benefit["usage_status"] == "NON_USAGE_FLAGGED"
    assert benefit["recert_status"] == "NOTICED"
    assert benefit["device_status"] == "DEVICE_ISSUED"
    assert_instant(benefit["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
    assert_instant(
        benefit["recert_response_deadline_at"], RECERT_DEADLINE, "recert_response_deadline_at"
    )
    assert_instant(benefit["non_usage_flagged_at"], SWEEP_INSTANT, "non_usage_flagged_at")
    assert_instant(benefit["recert_notice_sent_at"], SWEEP_INSTANT, "recert_notice_sent_at")
    assert benefit["audit_risk_score"] == 40, (
        f"30 for NON_USAGE_FLAGGED plus 10 for one handset, got {benefit['audit_risk_score']}"
    )
    assert expected_risk_score(usage_lapsed=True, device_issuance_count=1) == 40


def test_curing_the_usage_dimension_leaves_the_other_three_untouched(api):
    """One activity write moves only usage_status; the notice and the handset stay put.

    PRD: "Activity on a benefit sitting in `NON_USAGE_FLAGGED` is a **cure**: provided the
    current instant is less than or equal to `cure_deadline_at`, the posture returns
    `NON_USAGE_FLAGGED → USING`, `last_usage_at` is set to the current instant, and both
    `non_usage_flagged_at` and `cure_deadline_at` are cleared to null."

    Design: Difficulty/non_linear_state_machine/enrollment_four_parallel_dimensions_advance_independently
    """
    context = _benefit_with_handset_swept_at_the_notice_window(api)
    enrollment_id = context["enrollment"]["id"]

    fx.set_clock(api, USAGE_INSTANT)
    cured = validate_success(
        api.record_usage(enrollment_id, f.usage_payload(), context["agent"])
    )

    assert cured["usage_status"] == "USING", (
        f"the cure returns the usage dimension to USING, got {cured['usage_status']}"
    )
    assert_instant(cured["last_usage_at"], USAGE_INSTANT, "last_usage_at")
    assert_instant_null(cured["non_usage_flagged_at"], "non_usage_flagged_at")
    assert_instant_null(cured["cure_deadline_at"], "cure_deadline_at")

    assert cured["recert_status"] == "NOTICED", (
        "curing usage does not touch the recertification dimension"
    )
    assert_instant(
        cured["recert_response_deadline_at"], RECERT_DEADLINE, "recert_response_deadline_at"
    )
    assert_instant(cured["recert_notice_sent_at"], SWEEP_INSTANT, "recert_notice_sent_at")
    assert cured["device_status"] == "DEVICE_ISSUED", "handset custody is unchanged"
    assert cured["benefit_status"] == "ACTIVE", "the benefit is still being drawn"
    assert cured["audit_risk_score"] == 10, (
        f"only the single handset weight survives the cure, got {cured['audit_risk_score']}"
    )
    assert fx.refresh_device(api, context["device"]["id"])["status"] == "ISSUED"


def _appeal_remanded_to_the_third_round(api):
    """A de-enrollment appeal carried through two remands and assigned a third reviewer."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    context = fx.active_benefit(api)
    fx.de_enroll(
        api,
        context["enrollment"]["id"],
        reason="SUBSCRIBER_REQUEST",
        headers=context["agent"],
        note="moving out of state",
    )
    case = fx.file_case(
        api,
        context["subscriber"]["id"],
        context["enrollment"]["id"],
        case_type="DE_ENROLLMENT_APPEAL",
        headers=context["holder"],
        narrative="I never asked to be dropped",
    )
    assert case["review_round"] == 0, "a fresh case is born on review round 0"

    for reviewer in ("REV-1", "REV-2"):
        fx.assign_review(api, case["id"], reviewer_ref=reviewer)
        fx.decide_case(api, case["id"], "REMAND", rationale="need the porting log")
    third = fx.assign_review(api, case["id"], reviewer_ref="REV-3")
    assert third["review_round"] == 3, (
        f"the third successful assignment is round 3, got {third['review_round']}"
    )
    context["case"] = third
    return context


def test_the_remand_cycle_is_traversable_and_counts_every_assignment(api):
    """Two full UNDER_REVIEW to REMANDED laps put the case on round three with the third reviewer.

    PRD: "`reviewer_ref` is stored — rewritten, on a re-assignment after a remand —
    `review_round` rises by one as the count of successful assignments, and the case moves
    to `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/subscriber_case_remand_cycle_bounded_at_three_review_rounds
    """
    context = _appeal_remanded_to_the_third_round(api)
    case = context["case"]

    assert case["status"] == "UNDER_REVIEW", (
        f"a re-assignment after a remand returns the case UNDER_REVIEW, got {case['status']}"
    )
    assert case["reviewer_ref"] == "REV-3", (
        "the third assignment rewrites reviewer_ref over the remanded reviewer"
    )

    remanded = fx.decide_case(
        api, case["id"], "REMAND", rationale="third look still inconclusive"
    )
    assert remanded["status"] == "REMANDED", (
        f"REMAND moves the case UNDER_REVIEW to REMANDED, got {remanded['status']}"
    )
    assert remanded["decision"] == "REMAND", "every decision writes the decision field"
    assert remanded["review_round"] == 3, "deciding does not advance the round counter"
    assert remanded["reviewer_ref"] == "REV-3", "the remanded reviewer is still recorded"

    benefit = fx.refresh_enrollment(api, context["enrollment"]["id"])
    assert benefit["benefit_status"] == "DE_ENROLLED", "a remand leaves the benefit untouched"
    assert benefit["reinstatement_count"] == 0, "nothing has been reinstated"


def test_a_fourth_assignment_is_refused_once_the_round_counter_reaches_three(api):
    """The loop is terminated by the counter, not by a state: the case stays REMANDED.

    PRD: "Review is bounded at three rounds: once `review_round` has reached 3 a further
    assignment is refused with `ERR_REVIEW_ROUND_LIMIT`, so a fourth assignment on the same
    case always fails and the `UNDER_REVIEW → REMANDED → UNDER_REVIEW` negotiation cannot
    spin forever."

    Design: Difficulty/non_linear_state_machine/subscriber_case_remand_cycle_bounded_at_three_review_rounds
    """
    context = _appeal_remanded_to_the_third_round(api)
    case_id = context["case"]["id"]
    fx.decide_case(api, case_id, "REMAND", rationale="third look still inconclusive")

    response = api.assign_case_review(
        case_id, f.assign_review_payload(reviewer_ref="REV-4"), PROGRAM_ADMIN
    )
    validate_error(response, ApiErrorId.REVIEW_ROUND_LIMIT.value, 409)

    unchanged = fx.refresh_case(api, case_id)
    assert unchanged["status"] == "REMANDED", (
        f"a refused assignment leaves the case REMANDED, got {unchanged['status']}"
    )
    assert unchanged["review_round"] == 3, "the counter does not move on a refused assignment"
    assert unchanged["reviewer_ref"] == "REV-3", "REV-4 was never recorded"
