"""Cascades whose every link is caused strictly by the link above it."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    assert_compliance_run,
    assert_exam_dimensions,
    assert_instant_equals,
    create_draft_survey,
    exam_version,
    generate_letter,
    read_exam,
    read_facility,
    read_letter,
    read_order,
    read_unit,
    recommend_order,
    run_compliance,
    send_letter,
    set_clock,
    validate_success,
)


@pytest.fixture
def cascade_world(core):
    """A recalled exam with an open order, plus a draft annual survey to fail."""
    exam = acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-9001",
        performed_at="2026-07-15T00:00:00Z",
    )
    core["exam_id"] = exam["id"]
    order = recommend_order(
        core,
        exam["id"],
        "ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Recall workup",
    )
    core["order_id"] = order["id"]
    survey = create_draft_survey(
        core,
        survey_type="ANNUAL",
        effective_start="2026-07-01T00:00:00Z",
        effective_end="2027-07-01T00:00:00Z",
    )
    core["survey_id"] = survey["id"]
    return core


FAILING_DECISION = {
    "phantom_score": 5.5,
    "mean_glandular_dose_mgy": 3.20,
    "critical_deficiency_codes": ["DET-01"],
    "outcome_note": "Dead detector pixel cluster in the central quadrant",
}


def test_failing_survey_drives_the_unit_out_of_service_and_the_facility_to_suspended(
    api, cascade_world
):
    """Levels one to three: survey_compliance FAILED, then PROBATION plus OUT_OF_SERVICE.

    PRD: "Level two, caused by that, moves the unit's `accreditation_status` to
    `PROBATION` — this fires from `ACCREDITED`, from `PROVISIONAL` and from
    `REACCREDITATION_DUE` alike — and, only when the deciding survey's
    `critical_deficiency_codes` is non-empty, additionally moves the unit's
    `operational_state` from `IN_SERVICE` to `OUT_OF_SERVICE`."

    Design: Difficulty/transitive_cascade/failing_survey_cascades_five_levels_to_external_followup
    """
    core = cascade_world
    survey = validate_success(
        api.submit_physicist_survey(core["survey_id"], FAILING_DECISION, core["phys_headers"])
    )
    assert survey["status"] == "FAILED_ACTION_REQUIRED"
    assert_instant_equals(survey["decided_at"], "2026-08-01T00:00:00Z", "decided_at")
    assert survey["remediation_attempts"] == 0
    unit = read_unit(core["unit_id"])
    assert unit["survey_compliance"] == "FAILED"
    assert unit["accreditation_status"] == "PROBATION"
    assert unit["operational_state"] == "OUT_OF_SERVICE"
    assert unit["last_passed_survey_end"] is None
    assert read_facility(core["facility_id"])["compliance_posture"] == "SUSPENDED"


def test_suspension_refers_the_open_order_out_and_flips_the_exam_external(
    api, cascade_world
):
    """Levels four and five reach an order and an exam the request never named.

    PRD: "Every `SupplementalScreeningOrder` reachable from the facility — through
    a unit of the facility, to an exam acquired on that unit, to that exam's orders
    — whose `status` is `RECOMMENDED` or `COVERAGE_DETERMINED` moves to
    `REFERRED_OUT` with `external_referral_note` stamped, and each such order in
    turn moves its exam's `follow_up_status` from `PENDING` to `PENDING_EXTERNAL`."

    Design: Difficulty/transitive_cascade/failing_survey_cascades_five_levels_to_external_followup
    """
    core = cascade_world
    validate_success(
        api.submit_physicist_survey(core["survey_id"], FAILING_DECISION, core["phys_headers"])
    )
    order = read_order(core["order_id"])
    assert order["status"] == "REFERRED_OUT"
    assert order["external_referral_note"] is not None
    assert_exam_dimensions(read_exam(core["exam_id"]), follow_up_status="PENDING_EXTERNAL")


@pytest.fixture
def delivered_letter_world(core):
    """A routine read whose letter is already assumed delivered nineteen days later."""
    exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-9101",
        performed_at="2026-07-01T00:00:00Z",
    )
    core["exam_id"] = exam["id"]
    letter = generate_letter(
        core,
        exam["id"],
        expected_exam_version=exam_version(exam["id"]),
        dispatch_channel="MAIL",
    )
    core["letter_id"] = letter["id"]
    send_letter(core, letter["id"])
    set_clock("2026-08-20T00:00:00Z")
    core["run"] = run_compliance(core)
    return core


AMENDMENT = {
    "density_category": "B",
    "amendment_reason": "Density re-scored on comparison with priors",
}


def test_amendment_supersedes_a_delivered_letter_and_reopens_the_obligation(
    api, delivered_letter_world
):
    """A terminal DELIVERED_ASSUMED letter is superseded and the count climbs to one.

    PRD: "The effect on the facility's `open_notice_obligations` depends on where
    the notification dimension was: a letter that was `QUEUED` or `SENT` was
    already counted as an open obligation, so the count is unchanged, whereas a
    `COMPLETE` obligation reopening from a `DELIVERED_ASSUMED` letter increases the
    count by 1."

    Design: Difficulty/transitive_cascade/amendment_cascades_three_levels_and_reopens_a_completed_obligation
    """
    core = delivered_letter_world
    assert_compliance_run(core["run"], letters_marked_delivered=1)
    exam = validate_success(api.amend_exam(core["exam_id"], AMENDMENT, core["rad_headers"]))
    assert exam["report_status"] == "AMENDED"
    assert exam["amendment_count"] == 1
    assert exam["density_category"] == "B"
    assert read_letter(core["letter_id"])["status"] == "SUPERSEDED"
    assert read_facility(core["facility_id"])["open_notice_obligations"] == 1


def test_reopened_notification_clears_the_deadline_and_spares_the_followup_dimension(
    api, delivered_letter_world
):
    """The notification dimension returns to PENDING while follow-up stays untouched.

    PRD: "Level three, caused by that supersession, moves the exam's
    `notification_status` back to `PENDING` and clears `notification_deadline_at`,
    because the letter the patient received described a finding that no longer
    stands."

    Design: Difficulty/transitive_cascade/amendment_cascades_three_levels_and_reopens_a_completed_obligation
    """
    core = delivered_letter_world
    exam = validate_success(api.amend_exam(core["exam_id"], AMENDMENT, core["rad_headers"]))
    assert_exam_dimensions(
        exam, notification_status="PENDING", follow_up_status="NOT_REQUIRED"
    )
    assert exam["notification_deadline_at"] is None
    assert exam["interpreted_late"] is True
