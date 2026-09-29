"""Two requests that violate two rules at once: the earlier rung of the ladder wins."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    LicenseStatus,
    api_client,
    assign_evaluator_payload,
    fixtures,
    make_school_psychologist_headers,
    start_testing_payload,
)
from test_helpers.test_users import TEST_USERS


def _case_in_testing_and_an_evaluator_from_another_building():
    """An IN_TESTING evaluation, plus a psychologist who covers a different building."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    building_one = fixtures.create_school(
        name="Maple Grove Elementary",
        building_code="MG08",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=410,
    )
    building_two = fixtures.create_school(
        name="Pine Ridge Elementary",
        building_code="PR09",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=430,
    )
    covering = fixtures.create_psychologist(
        [building_one["id"]],
        full_name="Hana Sato",
        employee_number="E-1009",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    outsider = fixtures.create_psychologist(
        [building_two["id"]],
        full_name="Ivan Petrov",
        employee_number="E-1010",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    instrument = fixtures.create_instrument(
        name="WJ-IV",
        instrument_code="WJ4",
        protocol_stock_count=8,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1500,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    fixtures.assign_license_seat(instrument["id"], covering["id"])

    referral, evaluation = fixtures.consented_referral(
        building_one["id"],
        student_local_id="STU-J",
        requested_domains=["ACADEMIC"],
        intervention_team_summary="tier 3 maths",
    )
    fixtures.assign_evaluator(evaluation["id"], covering["id"])
    evaluation = fixtures.start_testing(
        evaluation["id"], instrument["id"], covering["id"]
    )
    return referral, covering, outsider, evaluation, building_one


def _case_with_an_expired_licence_and_an_empty_shelf():
    """An ASSIGNED evaluation whose only instrument fails both consumable gates."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Sunset Middle",
        building_code="SM10",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=580,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Jo Kim",
        employee_number="E-1011",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    instrument = fixtures.create_instrument(
        name="DAS-II",
        instrument_code="DAS2",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1600,
        license_seat_total=2,
        license_expires_on="2026-07-31",
        supported_language_editions=["en"],
    )
    fixtures.assign_license_seat(instrument["id"], psychologist["id"])

    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-K",
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 3 cognition",
    )
    evaluation = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    return school, psychologist, instrument, evaluation


def test_the_assessment_posture_is_reported_ahead_of_the_building_mismatch():
    """Rerouting a case under test to an uncovered evaluator reports the posture.

    "Validations are evaluated in one fixed ascending order and **the first failure wins** — later checks never run, and never mask an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/state_p8_beats_building_mismatch_p14
    """
    (
        referral,
        _,
        outsider,
        evaluation,
        building_one,
    ) = _case_in_testing_and_an_evaluator_from_another_building()

    # Both conditions hold: the posture forbids routing, and the named target
    # does not cover the building that raised the referral.
    assert evaluation["assessment_status"] == AssessmentStatus.IN_TESTING.value
    assert referral["school_id"] == building_one["id"]
    assert building_one["id"] not in outsider["assigned_school_ids"]

    fresh_version = fixtures.evaluation_version(evaluation["id"])
    response = api_client.assign_evaluator(
        evaluation["id"],
        assign_evaluator_payload(fresh_version, outsider["id"]),
        TEST_USERS["psych_services_supervisor_headers"],
    )

    validate_error(response, ApiErrorId.ERR_EVALUATION_STATE_INVALID.value, 409)


def test_the_refused_reroute_writes_nothing_at_all():
    """The case keeps its evaluator, its posture, its counter and its version.

    "Both modes also require that the evaluation's `assessment_status` is currently `PENDING_ASSIGNMENT` or `ASSIGNED` — any other assessment posture is rejected with `ERR_EVALUATION_STATE_INVALID` — and that the parent referral's `status` is `CONSENTED` or `CONSENT_WAIVED`, since routing an evaluation whose consent has been withdrawn is rejected with `ERR_CONSENT_NOT_ON_FILE`."

    Design: Difficulty/priority_pair_validation_conflict/state_p8_beats_building_mismatch_p14
    """
    (
        _,
        covering,
        outsider,
        evaluation,
        _,
    ) = _case_in_testing_and_an_evaluator_from_another_building()
    fresh_version = fixtures.evaluation_version(evaluation["id"])

    api_client.assign_evaluator(
        evaluation["id"],
        assign_evaluator_payload(fresh_version, outsider["id"]),
        TEST_USERS["psych_services_supervisor_headers"],
    )

    unchanged = fixtures.get_evaluation(evaluation["id"])
    assert unchanged["psychologist_id"] == covering["id"]
    assert unchanged["assessment_status"] == AssessmentStatus.IN_TESTING.value
    assert unchanged["reassignment_count"] == 0
    assert unchanged["version"] == fresh_version

    assert fixtures.get_psychologist(outsider["id"])["open_case_points"] == 0


def test_the_licence_gate_is_reported_ahead_of_the_empty_shelf():
    """An expired licence and a bare shelf together report the licence.

    "On testing-start, the licensing check at position 12 runs before the interpreter check at position 17, which in turn runs before the inventory check at position 29 — so a psychologist with no valid scoring seat, no interpreter session and no protocol stock sees `ERR_SCORING_LICENSE_INVALID`, not the other two."

    Design: Difficulty/priority_pair_validation_conflict/licensing_p12_beats_protocol_stock_p29
    """
    _, psychologist, instrument, evaluation = (
        _case_with_an_expired_licence_and_an_empty_shelf()
    )

    # Both conditions hold at trigger time.
    live_instrument = fixtures.get_instrument(instrument["id"])
    assert live_instrument["license_status"] == LicenseStatus.EXPIRED.value
    assert live_instrument["protocol_stock_count"] == 0
    assert len(evaluation["evaluation_domains"]) == 1

    response = api_client.start_testing(
        evaluation["id"],
        start_testing_payload(instrument["id"]),
        make_school_psychologist_headers(psychologist["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SCORING_LICENSE_INVALID.value, 422)


def test_the_refused_testing_start_consumes_no_booklets():
    """Nothing is debited and the shelf is never driven negative.

    "On success the same product is written to the evaluation's `protocol_units_consumed` and debited from the instrument's `protocol_stock_count`."

    Design: Difficulty/priority_pair_validation_conflict/licensing_p12_beats_protocol_stock_p29
    """
    _, psychologist, instrument, evaluation = (
        _case_with_an_expired_licence_and_an_empty_shelf()
    )

    api_client.start_testing(
        evaluation["id"],
        start_testing_payload(instrument["id"]),
        make_school_psychologist_headers(psychologist["id"]),
    )

    unchanged = fixtures.get_evaluation(evaluation["id"])
    assert unchanged["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert unchanged["testing_instrument_id"] is None
    assert unchanged["protocol_units_consumed"] == 0

    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 0
