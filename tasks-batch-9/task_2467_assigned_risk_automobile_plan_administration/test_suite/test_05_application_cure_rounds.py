"""Cure round-trips: the application returns to SUBMITTED and stops after two."""
from test_helpers import (
    SIX_POINT_VIOLATIONS,
    YOUTHFUL_APPLICANT,
    ApiErrorId,
    api_client,
    bootstrap_plan,
    create_cure_return_payload,
    file_two_market_rejections,
    make_compliance_examiner_headers,
    read_application,
    record_deposit,
    resubmit,
    return_for_cure,
    submit_application,
    create_applicant_with_vehicle,
    validate_error,
    verify_mvr,
)


def _submitted_application_with_verified_record_and_deposit():
    """Submit a six-point risk, document two declinations, verify the record, pay."""
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle(YOUTHFUL_APPLICANT)
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"],
                                    declared_violations=SIX_POINT_VIOLATIONS)
    file_two_market_rejections(application["id"], env["producer"]["id"],
                              document_prefix="DEC-12")
    verify_mvr(application["id"], SIX_POINT_VIOLATIONS)
    record_deposit(application["id"], env["producer"]["id"], 61709)
    return env, application


def test_a_resubmission_returns_the_application_to_submitted_and_clears_the_verified_record():
    """The round-trip counts on the way back and voids the motor-vehicle pull.

    Returning the application for cure moves it out of SUBMITTED without touching
    the counter; the producer's resubmission moves it back, raises cure_count to 1,
    and discards both the verified violation array and its verification timestamp
    so the examiner must pull the record again.

    PRD: "Critically, resubmission resets `verified_violations` to null and
    `mvr_verified_at` to null: the motor-vehicle record must be pulled again,
    because the cure may have changed the very record the examiner verified."
    Design: Difficulty/non_linear_state_machine/application_cure_cycle_returns_to_submitted_and_stops_at_two_rounds
    """
    env, application = _submitted_application_with_verified_record_and_deposit()
    assert read_application(application["id"])["mvr_verified_at"] is not None

    return_for_cure(application["id"], "Garaging address unsupported.")
    returned = read_application(application["id"])
    assert returned["status"] == "RETURNED_FOR_CURE"
    assert returned["cure_count"] == 0

    resubmit(application["id"], env["producer"]["id"])
    resubmitted = read_application(application["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["cure_count"] == 1
    assert resubmitted["mvr_verified_at"] is None
    assert resubmitted["verified_violations"] is None
    assert resubmitted["distinct_rejection_count"] == 2
    assert resubmitted["deposit_paid_total_cents"] == 61709


def test_a_third_cure_return_is_refused_once_two_round_trips_are_spent():
    """Two round-trips are the limit, and the third return leaves everything as it was.

    After two completed cure cycles the counter stands at 2, so a further return is
    inadmissible. The refusal is a plan-limit failure, and the application remains
    in SUBMITTED with its counter, its declination count and its deposit intact.

    PRD: "The plan tolerates at most two cure round-trips, so a return is only
    admissible while `cure_count` is less than 2; a third attempt is refused with
    `ERR_CURE_LIMIT_EXCEEDED` and HTTP 409."
    Design: Difficulty/non_linear_state_machine/application_cure_cycle_returns_to_submitted_and_stops_at_two_rounds
    """
    env, application = _submitted_application_with_verified_record_and_deposit()
    return_for_cure(application["id"], "Garaging address unsupported.")
    resubmit(application["id"], env["producer"]["id"])
    return_for_cure(application["id"], "Declination document illegible.")
    resubmit(application["id"], env["producer"]["id"])
    assert read_application(application["id"])["cure_count"] == 2

    response = api_client.return_application_for_cure(
        application["id"], create_cure_return_payload("Third defect."),
        make_compliance_examiner_headers())

    validate_error(response, ApiErrorId.ERR_CURE_LIMIT_EXCEEDED)
    unchanged = read_application(application["id"])
    assert unchanged["cure_count"] == 2
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["mvr_verified_at"] is None
    assert unchanged["verified_violations"] is None
    assert unchanged["distinct_rejection_count"] == 2
    assert unchanged["deposit_paid_total_cents"] == 61709
