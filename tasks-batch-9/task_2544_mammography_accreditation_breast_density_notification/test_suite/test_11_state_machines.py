"""State machines: declared initial states, invalid transitions, self-loops and
terminal lockdown."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    assert_facility_ledger,
    assert_instant_equals,
    assert_personnel_state,
    assert_unit_image_ledger,
    close_inspection,
    create_draft_survey,
    decide_survey,
    exam_payload,
    file_packet,
    generate_letter,
    list_total_count,
    mark_letter_undeliverable,
    outcome_payload,
    packet_payload,
    passing_survey_decision_payload,
    read_exam,
    read_facility,
    read_failure,
    read_letter,
    read_personnel,
    read_survey,
    read_unit,
    record_inspection,
    record_outcome,
    remediate_survey,
    report_failure,
    restore_payload,
    review_packet,
    run_qualification_review,
    resubmit_packet,
    send_letter,
    set_clock,
    setup_two_interpreted_exams,
    validate_error,
    validate_success,
)


def test_new_unit_and_new_personnel_start_in_their_declared_initial_states(api, core):
    """A fresh unit and a fresh technologist land on every declared default at once.

    PRD: "A new unit lands with `accreditation_status` `PROVISIONAL` and
    `operational_state` `IN_SERVICE` — two dimensions that evolve entirely
    independently of one another — with `survey_compliance` `OVERDUE` because no
    physicist survey has passed yet, a null `last_passed_survey_end`, and
    `reaccreditation_attempts_remaining` of 3."

    Design: Corner/state_machines/new_unit_and_new_personnel_start_in_their_declared_initial_states
    """
    unit = read_unit(core["unit_id"])
    assert unit["accreditation_status"] == "PROVISIONAL"
    assert unit["operational_state"] == "IN_SERVICE"
    assert unit["survey_compliance"] == "OVERDUE"
    assert unit["last_passed_survey_end"] is None
    assert unit["reaccreditation_attempts_remaining"] == 3
    assert_unit_image_ledger(
        unit,
        total_images_acquired=0,
        repeat_images_acquired=0,
        image_based_repeat_rate_pct=None,
        patient_based_repeat_rate_pct=None,
        repeat_rate_flag=False,
    )

    technologist = read_personnel(core["tech_id"])
    assert_personnel_state(
        technologist,
        qualification_status="QUALIFIED",
        ce_status="COMPLIANT",
        ce_hours_36mo=0,
        volume_credit_24mo=0,
        ce_deadline_at=None,
    )
    assert technologist["last_qualification_review_at"] is None

    facility = read_facility(core["facility_id"])
    assert facility["compliance_posture"] == "CONDITIONAL"


def test_remediating_a_draft_survey_is_rejected_as_an_invalid_transition(
    api, core, coordinator_headers
):
    """Remediation is reachable only from `FAILED_ACTION_REQUIRED`, never from `DRAFT`.

    PRD: "Remediation is the coordinator's side of the split, and it is only
    available on a survey in `FAILED_ACTION_REQUIRED`."

    Design: Corner/state_machines/remediating_a_draft_survey_is_rejected_as_an_invalid_transition
    """
    survey = create_draft_survey(core)
    assert survey["status"] == "DRAFT"

    validate_error(
        api.remediate_physicist_survey(
            survey["id"], passing_survey_decision_payload(), coordinator_headers
        ),
        "ERR_SURVEY_NOT_DECIDABLE",
        expected_status=409,
    )

    unchanged = read_survey(survey["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["remediation_attempts"] == 0
    assert unchanged["decided_at"] is None
    assert unchanged["phantom_score"] is None
    assert unchanged["mean_glandular_dose_mgy"] is None
    assert read_unit(core["unit_id"])["survey_compliance"] == "OVERDUE"


def test_sending_the_same_letter_twice_is_rejected(api, core, coordinator_headers):
    """Dispatch is available only from `QUEUED`, so the second send finds `SENT`.

    PRD: "It is available only from `QUEUED` — any other state is
    `ERR_LETTER_NOT_SENDABLE` — and it additionally requires the letter's exam
    still to be in `report_status` `INTERPRETED_FINAL` or `AMENDED`."

    Design: Corner/state_machines/sending_the_same_letter_twice_is_rejected
    """
    exam = acquire_and_interpret(
        core, birads=1, density="B", patient_ref="PT-1201", performed_at="2026-07-20T00:00:00Z"
    )
    letter = generate_letter(core, exam["id"])
    assert letter["status"] == "QUEUED"

    sent = send_letter(core, letter["id"])
    assert sent["status"] == "SENT"
    assert_instant_equals(sent["sent_at"], "2026-08-01T00:00:00Z", "sent_at")
    assert read_exam(exam["id"])["notification_status"] == "SENT"

    validate_error(
        api.send_notification_letter(letter["id"], coordinator_headers),
        "ERR_LETTER_NOT_SENDABLE",
        expected_status=409,
    )

    after = read_letter(letter["id"])
    assert after["status"] == "SENT"
    assert after["version"] == sent["version"]
    assert_instant_equals(after["sent_at"], "2026-08-01T00:00:00Z", "sent_at")
    assert read_exam(exam["id"])["notification_status"] == "SENT"
    assert list_total_count(api.list_exam_notification_letters(exam["id"], coordinator_headers)) == 1


def test_closing_an_already_closed_inspection_is_rejected(api, core, inspector_headers):
    """`CLOSED` is terminal, so the second closure of the same inspection is refused.

    PRD: "`CLOSED` is terminal: a second closure attempt is refused with
    `ERR_INSPECTION_ALREADY_CLOSED`."

    Design: Corner/state_machines/closing_an_already_closed_inspection_is_rejected
    """
    inspection = record_inspection(
        core, "LEVEL_2", finding_codes=["900.12(d)(1)"], inspection_date="2026-07-28T00:00:00Z"
    )
    assert inspection["status"] == "CORRECTIVE_ACTION_REQUIRED"
    assert inspection["inspector_findings_level"] == "LEVEL_2"

    closed = close_inspection(core, inspection["id"])
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

    validate_error(
        api.close_inspection(inspection["id"], inspector_headers),
        "ERR_INSPECTION_ALREADY_CLOSED",
        expected_status=409,
    )

    after = validate_success(api.get_inspection(inspection["id"], inspector_headers))
    assert after["status"] == "CLOSED"
    assert after["version"] == closed["version"]
    assert read_facility(core["facility_id"])["compliance_posture"] == "CONDITIONAL"


def test_denied_final_packet_suspends_the_unit_and_locks_every_further_action(
    api, funded_core, coordinator_headers, reviewer_headers
):
    """The third denial suspends the unit, and each later action hits a different guard.

    PRD: "When instead the unit's `reaccreditation_attempts_remaining` has
    reached 0, the same `REVISION_REQUIRED` verdict is terminal: the submission
    moves `SUBMITTED` to `DENIED_FINAL`, and a three-level cascade follows."

    Design: Corner/state_machines/denied_final_packet_suspends_the_unit_and_locks_every_further_action
    """
    core = funded_core
    failure = report_failure(
        core,
        headers=coordinator_headers,
        failure_code="DISPLAY",
        severity="MINOR",
        detected_at="2026-07-30T00:00:00Z",
    )
    assert failure["status"] == "OPEN"
    assert failure["requires_post_repair_survey"] is False
    assert read_unit(core["unit_id"])["operational_state"] == "IN_SERVICE"

    exams = setup_two_interpreted_exams(core)
    exam_ids = [exams[0]["id"], exams[1]["id"]]

    submission = file_packet(core, exam_ids)
    submission = review_packet(core, submission["id"], "REVISION_REQUIRED", deficiency_categories=["POSITIONING"])
    submission = resubmit_packet(core, submission["id"], exam_ids)
    submission = review_packet(core, submission["id"], "REVISION_REQUIRED", deficiency_categories=["POSITIONING"])
    submission = resubmit_packet(core, submission["id"], exam_ids)

    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 0
    assert submission["attempt_number"] == 3
    assert submission["status"] == "SUBMITTED"

    denied = review_packet(
        core,
        submission["id"],
        "REVISION_REQUIRED",
        deficiency_categories=["POSITIONING", "COMPRESSION"],
    )
    assert denied["status"] == "DENIED_FINAL"
    assert denied["review_decision"] == "REVISION_REQUIRED"
    assert_instant_equals(denied["reviewed_at"], "2026-08-01T00:00:00Z", "reviewed_at")
    assert denied["fee_held_cents"] == 0

    unit = read_unit(core["unit_id"])
    assert unit["accreditation_status"] == "SUSPENDED"
    assert unit["operational_state"] == "OUT_OF_SERVICE"

    facility = read_facility(core["facility_id"])
    assert facility["compliance_posture"] == "SUSPENDED"
    assert_facility_ledger(
        facility,
        total_funded_cents=1000000,
        prepaid_credit_cents=250000,
        fee_held_cents=0,
        fee_consumed_cents=750000,
    )

    validate_error(
        api.create_clinical_image_review(
            core["unit_id"], packet_payload(exam_ids, unit["version"]), coordinator_headers
        ),
        "ERR_REACCREDITATION_ATTEMPTS_EXHAUSTED",
        expected_status=409,
    )
    validate_error(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-1299",
                performed_at="2026-07-31T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        "ERR_UNIT_NOT_IN_SERVICE",
        expected_status=409,
    )
    validate_error(
        api.restore_equipment_failure(
            failure["id"],
            restore_payload(repair_note="Monitor replaced after the denial"),
            coordinator_headers,
        ),
        "ERR_UNIT_ACCREDITATION_SUSPENDED",
        expected_status=409,
    )

    still_open = read_failure(failure["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["resolved_at"] is None
    assert read_unit(core["unit_id"])["operational_state"] == "OUT_OF_SERVICE"
    assert (
        list_total_count(
            api.list_unit_clinical_image_reviews(core["unit_id"], coordinator_headers)
        )
        == 1
    )


def test_undeliverable_letter_is_superseded_by_the_reissued_letter(
    api, core, coordinator_headers
):
    """The returned letter reopens the obligation, and the replacement points back at it.

    PRD: "Reopening the obligation is what lets the coordinator generate a
    replacement letter; when that replacement is generated, the `UNDELIVERABLE`
    letter moves to `SUPERSEDED` and the replacement's `supersedes_letter_id`
    points at it."

    Design: Corner/state_machines/undeliverable_letter_is_superseded_by_the_reissued_letter
    """
    exam = acquire_and_interpret(
        core, birads=1, density="B", patient_ref="PT-1201", performed_at="2026-07-20T00:00:00Z"
    )
    first = generate_letter(core, exam["id"], dispatch_channel="MAIL")
    send_letter(core, first["id"])

    returned = mark_letter_undeliverable(
        core, first["id"], reason="Returned by the postal service — addressee moved"
    )
    assert returned["status"] == "UNDELIVERABLE"
    assert returned["undeliverable_reason"] == "Returned by the postal service — addressee moved"
    assert read_exam(exam["id"])["notification_status"] == "PENDING"

    second = generate_letter(core, exam["id"], dispatch_channel="PORTAL")

    assert read_letter(first["id"])["status"] == "SUPERSEDED"
    assert second["status"] == "QUEUED"
    assert second["supersedes_letter_id"] == first["id"]
    assert second["dispatch_channel"] == "PORTAL"
    assert second["density_statement_code"] == "FDA_NOT_DENSE"
    assert second["letter_type"] == "COMBINED"
    assert second["required_notice_codes"] == [
        "FDA-LAY-SUMMARY",
        "FDA-NOT-DENSE",
        "CT-DENS-1",
        "CT-SUPP-2",
    ]
    assert read_exam(exam["id"])["notification_status"] == "GENERATED"
    assert (
        list_total_count(
            api.list_notification_letters(coordinator_headers, params={"exam_id": exam["id"]})
        )
        == 2
    )


def test_a_third_failing_survey_remediation_reaches_failed_final(api, core):
    """The remediation budget of 2 terminates the loop and pulls the unit out of service.

    PRD: "A second remediation that still fails — meaning `remediation_attempts`
    was already 1 — is terminal: the survey moves `FAILED_ACTION_REQUIRED` to
    `FAILED_FINAL` with `remediation_attempts` at 2, and the unit's
    `operational_state` becomes `OUT_OF_SERVICE` unconditionally, whether or not
    any critical deficiency code was recorded."

    Design: Corner/state_machines/a_third_failing_survey_remediation_reaches_failed_final
    """
    survey = create_draft_survey(core)
    decided = decide_survey(
        core,
        survey["id"],
        {
            "phantom_score": 5.5,
            "mean_glandular_dose_mgy": 2.80,
            "critical_deficiency_codes": [],
            "outcome_note": "Phantom score below the minimum",
        },
    )
    assert decided["status"] == "FAILED_ACTION_REQUIRED"
    assert decided["remediation_attempts"] == 0
    assert read_unit(core["unit_id"])["operational_state"] == "IN_SERVICE"

    first = remediate_survey(
        core,
        survey["id"],
        {
            "phantom_score": 5.7,
            "mean_glandular_dose_mgy": 2.80,
            "critical_deficiency_codes": [],
            "outcome_note": "First remediation still short",
        },
    )
    assert first["status"] == "FAILED_ACTION_REQUIRED"
    assert first["remediation_attempts"] == 1
    assert read_unit(core["unit_id"])["operational_state"] == "IN_SERVICE"

    second = remediate_survey(
        core,
        survey["id"],
        {
            "phantom_score": 5.9,
            "mean_glandular_dose_mgy": 2.80,
            "critical_deficiency_codes": [],
            "outcome_note": "Second remediation still short",
        },
    )
    assert second["status"] == "FAILED_FINAL"
    assert second["remediation_attempts"] == 2
    assert_instant_equals(second["decided_at"], "2026-08-01T00:00:00Z", "decided_at")
    assert second["phantom_score"] == pytest.approx(5.9, abs=0.01)

    unit = read_unit(core["unit_id"])
    assert unit["operational_state"] == "OUT_OF_SERVICE"
    assert unit["survey_compliance"] == "FAILED"
    assert unit["accreditation_status"] == "PROBATION"
    assert read_facility(core["facility_id"])["compliance_posture"] == "SUSPENDED"


def test_recording_a_second_pathology_outcome_is_rejected(api, core, qa_headers):
    """A settled pathology result cannot be rewritten by a second outcome post.

    PRD: "An outcome may be recorded once and refined while it is still open, but
    an exam whose `pathology_result` is already `BENIGN` or `MALIGNANT` is
    settled: a further attempt is refused with `ERR_OUTCOME_ALREADY_RECORDED`."

    Design: Corner/state_machines/recording_a_second_pathology_outcome_is_rejected
    """
    exam = acquire_and_interpret(
        core, birads=0, density="C", patient_ref="PT-1301", performed_at="2026-07-15T00:00:00Z"
    )
    recorded = record_outcome(core, exam["id"], biopsy_performed=True, pathology_result="MALIGNANT")
    assert recorded["pathology_result"] == "MALIGNANT"

    validate_error(
        api.record_exam_outcome(exam["id"], outcome_payload(True, "BENIGN"), qa_headers),
        "ERR_OUTCOME_ALREADY_RECORDED",
        expected_status=409,
    )

    after = read_exam(exam["id"])
    assert after["pathology_result"] == "MALIGNANT"
    assert after["biopsy_performed"] is True
    assert after["recall_flag"] is True


def test_expired_grace_moves_personnel_to_deficient_and_lapses_the_qualification(api, core):
    """Crossing `ce_deadline_at` couples the two otherwise parallel personnel dimensions.

    PRD: "Otherwise, when `ce_status` is `GRACE` and the logical clock has passed
    `ce_deadline_at` while a shortfall still exists, the grace period has expired:
    `ce_status` moves `GRACE` to `DEFICIENT`, and a person who was `QUALIFIED`
    moves to `LAPSED`."

    Design: Corner/state_machines/expired_grace_moves_personnel_to_deficient_and_lapses_the_qualification
    """
    first = run_qualification_review(
        core, core["tech_id"], review_note="First continuing-education review"
    )
    assert_personnel_state(first, qualification_status="QUALIFIED", ce_status="GRACE")
    assert_instant_equals(first["ce_deadline_at"], "2026-10-30T00:00:00Z", "ce_deadline_at")

    set_clock("2026-10-31T00:00:00Z")
    expired = run_qualification_review(
        core, core["tech_id"], review_note="Grace period has expired"
    )
    assert_personnel_state(
        expired,
        qualification_status="LAPSED",
        ce_status="DEFICIENT",
        ce_hours_36mo=0.00,
        volume_credit_24mo=0,
    )
    assert_instant_equals(
        expired["last_qualification_review_at"],
        "2026-10-31T00:00:00Z",
        "last_qualification_review_at",
    )
    assert read_facility(core["facility_id"])["compliance_posture"] == "CONDITIONAL"
