"""Errors: each declared code driven from the API surface and asserted by id,
status and the absence of any side effect."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_facility_ledger,
    assert_instant_equals,
    assert_unit_image_ledger,
    close_cycle,
    document_repeat,
    file_packet,
    generate_letter,
    ids_of,
    interpret_payload,
    list_total_count,
    open_cycle,
    packet_payload,
    read_cycle,
    read_exam,
    read_facility,
    read_failure,
    read_letter,
    read_order,
    read_submission,
    read_unit,
    recommend_order,
    report_failure,
    restore_payload,
    retract_payload,
    review_decision_payload,
    review_packet,
    schedule_payload,
    set_clock,
    setup_two_interpreted_exams,
    supplemental_order_payload,
    undeliverable_payload,
    unit_version,
    validate_error,
    validate_success,
    withdraw_payload,
)


def test_every_unknown_path_id_returns_its_own_not_found_code(api, coordinator_headers):
    """Ten resource families, ten distinct 404 codes off the same absent id.

    PRD: "**Path existence (priority 10)** — every id embedded in the request path
    exists, validated left to right: 404 with the code for the entity that was not
    found — `ERR_STATE_POLICY_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_EXAM_NOT_FOUND`,
    `ERR_LETTER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FAILURE_EVENT_NOT_FOUND`,
    `ERR_REPEAT_RECORD_NOT_FOUND`, `ERR_AUDIT_CYCLE_NOT_FOUND`."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
    """
    set_clock()
    missing = NON_EXISTENT_UUID
    probes = [
        (api.get_state_policy(missing, coordinator_headers), "ERR_STATE_POLICY_NOT_FOUND"),
        (api.get_physicist_survey(missing, coordinator_headers), "ERR_SURVEY_NOT_FOUND"),
        (api.get_inspection(missing, coordinator_headers), "ERR_INSPECTION_NOT_FOUND"),
        (
            api.get_clinical_image_review(missing, coordinator_headers),
            "ERR_SUBMISSION_NOT_FOUND",
        ),
        (api.get_exam(missing, coordinator_headers), "ERR_EXAM_NOT_FOUND"),
        (api.get_notification_letter(missing, coordinator_headers), "ERR_LETTER_NOT_FOUND"),
        (api.get_supplemental_order(missing, coordinator_headers), "ERR_ORDER_NOT_FOUND"),
        (
            api.get_equipment_failure(missing, coordinator_headers),
            "ERR_FAILURE_EVENT_NOT_FOUND",
        ),
        (api.get_repeat_record(missing, coordinator_headers), "ERR_REPEAT_RECORD_NOT_FOUND"),
        (api.get_audit_cycle(missing, coordinator_headers), "ERR_AUDIT_CYCLE_NOT_FOUND"),
    ]

    seen = []
    for response, expected in probes:
        error = validate_error(response, expected, expected_status=404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].strip() != ""
        seen.append(error["error_id"])

    assert len(seen) == 10
    assert len(set(seen)) == 10


def test_submission_and_letter_actions_are_rejected_from_the_wrong_state(
    api, funded_core, coordinator_headers, reviewer_headers
):
    """Three submission actions and one letter action own four distinct 409 codes.

    PRD: "**State precondition (priority 40)** — the target resource sits in a
    state from which the requested transition is declared: 409 with the code for the
    operation — `ERR_SURVEY_NOT_DECIDABLE`, `ERR_SUBMISSION_NOT_REVIEWABLE`,
    `ERR_SUBMISSION_NOT_REVISABLE`, `ERR_SUBMISSION_NOT_WITHDRAWABLE`,
    `ERR_INSPECTION_ALREADY_CLOSED`, `ERR_LETTER_NOT_SENDABLE`,
    `ERR_LETTER_NOT_SENT`, `ERR_ORDER_NOT_DETERMINABLE`,
    `ERR_ORDER_NOT_SCHEDULABLE`, `ERR_ORDER_NOT_COMPLETABLE`,
    `ERR_EXAM_NOT_INTERPRETABLE`, `ERR_EXAM_NOT_AMENDABLE`,
    `ERR_OUTCOME_ALREADY_RECORDED`, `ERR_AUDIT_CYCLE_NOT_CLOSABLE`,
    `ERR_FAILURE_ALREADY_RESOLVED`, `ERR_REPEAT_RECORD_ALREADY_RETRACTED`."

    Design: Corner/errors/submission_and_letter_actions_are_rejected_from_the_wrong_state
    """
    core = funded_core
    exams = setup_two_interpreted_exams(core)
    exam_ids = [exams[0]["id"], exams[1]["id"]]

    submission = file_packet(core, exam_ids, reviewer_note="Initial accreditation packet")
    passed = review_packet(
        core, submission["id"], "PASS", reviewer_note="Image quality acceptable"
    )
    assert passed["status"] == "PASSED"

    letter = generate_letter(core, exams[0]["id"], dispatch_channel="MAIL")
    assert letter["status"] == "QUEUED"
    current_version = unit_version(core)

    validate_error(
        api.review_clinical_image_review(
            submission["id"],
            review_decision_payload("REVISION_REQUIRED", reviewer_note="Second opinion"),
            reviewer_headers,
        ),
        "ERR_SUBMISSION_NOT_REVIEWABLE",
        expected_status=409,
    )
    validate_error(
        api.resubmit_clinical_image_review(
            submission["id"],
            packet_payload(
                exam_ids, current_version, reviewer_note="Trying to revise a passed packet"
            ),
            coordinator_headers,
        ),
        "ERR_SUBMISSION_NOT_REVISABLE",
        expected_status=409,
    )
    validate_error(
        api.withdraw_clinical_image_review(
            submission["id"],
            withdraw_payload(
                expected_unit_version=current_version,
                withdrawal_reason="Trying to withdraw a passed packet",
            ),
            coordinator_headers,
        ),
        "ERR_SUBMISSION_NOT_WITHDRAWABLE",
        expected_status=409,
    )
    validate_error(
        api.mark_letter_undeliverable(
            letter["id"],
            undeliverable_payload(undeliverable_reason="Returned to sender"),
            coordinator_headers,
        ),
        "ERR_LETTER_NOT_SENT",
        expected_status=409,
    )

    after_submission = read_submission(submission["id"])
    assert after_submission["status"] == "PASSED"
    assert after_submission["attempt_number"] == 1

    after_letter = read_letter(letter["id"])
    assert after_letter["status"] == "QUEUED"
    assert after_letter["undeliverable_reason"] is None

    unit = read_unit(core["unit_id"])
    assert unit["accreditation_status"] == "ACCREDITED"
    assert unit["reaccreditation_attempts_remaining"] == 3
    assert unit["version"] == current_version

    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=750000,
        fee_held_cents=0,
        fee_consumed_cents=250000,
    )


def test_order_and_exam_actions_are_rejected_from_the_wrong_state(
    api, core, coordinator_headers
):
    """A completed order and a recommended order fail opposite actions on one exam.

    PRD: "Completion is a coordinator action available only from `SCHEDULED`; from
    any other state it is `ERR_ORDER_NOT_COMPLETABLE`."

    Design: Corner/errors/order_and_exam_actions_are_rejected_from_the_wrong_state
    """
    exam = validate_success(
        api.create_exam(
            {
                "unit_id": core["unit_id"],
                "technologist_id": core["tech_id"],
                "patient_ref": "PT-SC-1",
                "patient_state_code": "CT",
                "exam_type": "SCREENING",
                "performed_at": "2026-07-20T00:00:00Z",
                "original_image_count": 4,
            },
            core["tech_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.interpret_exam(exam["id"], interpret_payload(1, "C"), core["rad_headers"])
    )

    ultrasound = recommend_order(
        core,
        exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, supplemental ultrasound advised",
    )
    validate_success(api.determine_coverage(ultrasound["id"], coordinator_headers))
    validate_success(
        api.schedule_supplemental_order(
            ultrasound["id"], schedule_payload("2026-08-10T14:00:00Z"), coordinator_headers
        )
    )
    completed = validate_success(
        api.complete_supplemental_order(
            ultrasound["id"], coordinator_headers, {"completion_note": "Ultrasound performed"}
        )
    )
    assert completed["status"] == "COMPLETED"

    mri = validate_success(
        api.create_supplemental_order(
            exam["id"],
            supplemental_order_payload("MRI", recommendation_note="Second-line MRI recommended"),
            core["rad_headers"],
        ),
        expected_status=201,
    )
    unread = validate_success(
        api.create_exam(
            {
                "unit_id": core["unit_id"],
                "technologist_id": core["tech_id"],
                "patient_ref": "PT-SC-9",
                "patient_state_code": "CT",
                "exam_type": "SCREENING",
                "performed_at": "2026-07-25T00:00:00Z",
                "original_image_count": 4,
            },
            core["tech_headers"],
        ),
        expected_status=201,
    )

    validate_error(
        api.determine_coverage(ultrasound["id"], coordinator_headers),
        "ERR_ORDER_NOT_DETERMINABLE",
        expected_status=409,
    )
    validate_error(
        api.schedule_supplemental_order(
            ultrasound["id"], schedule_payload("2026-08-20T14:00:00Z"), coordinator_headers
        ),
        "ERR_ORDER_NOT_SCHEDULABLE",
        expected_status=409,
    )
    validate_error(
        api.complete_supplemental_order(
            mri["id"], coordinator_headers, {"completion_note": "Never scheduled"}
        ),
        "ERR_ORDER_NOT_COMPLETABLE",
        expected_status=409,
    )
    validate_error(
        api.interpret_exam(exam["id"], interpret_payload(2, "C"), core["rad_headers"]),
        "ERR_EXAM_NOT_INTERPRETABLE",
        expected_status=409,
    )
    validate_error(
        api.amend_exam(
            unread["id"],
            {"birads_assessment": 2, "amendment_reason": "Amending an unread exam"},
            core["rad_headers"],
        ),
        "ERR_EXAM_NOT_AMENDABLE",
        expected_status=409,
    )

    after_ultrasound = read_order(ultrasound["id"])
    assert after_ultrasound["status"] == "COMPLETED"
    assert_instant_equals(
        after_ultrasound["completed_at"], completed["completed_at"], "completed_at"
    )

    after_mri = read_order(mri["id"])
    assert after_mri["status"] == "RECOMMENDED"
    assert after_mri["coverage_outcome"] == "UNDETERMINED"

    after_exam = read_exam(exam["id"])
    assert after_exam["birads_assessment"] == 1
    assert after_exam["amendment_count"] == 0
    assert after_exam["report_status"] == "INTERPRETED_FINAL"

    after_unread = read_exam(unread["id"])
    assert after_unread["report_status"] == "AWAITING_INTERPRETATION"
    assert after_unread["interpreting_physician_id"] is None


def test_audit_failure_and_repeat_actions_are_rejected_when_already_final(
    api, core, coordinator_headers, qa_headers
):
    """Three idempotency-looking retries are refused and re-run no side effect.

    PRD: "The cycle must be in `OPEN` or `AMENDED`; any other state is
    `ERR_AUDIT_CYCLE_NOT_CLOSABLE`."

    Design: Corner/errors/audit_failure_and_repeat_actions_are_rejected_when_already_final
    """
    cycle = open_cycle(core)
    exam = validate_success(
        api.create_exam(
            {
                "unit_id": core["unit_id"],
                "technologist_id": core["tech_id"],
                "patient_ref": "PT-1201",
                "patient_state_code": "CT",
                "exam_type": "SCREENING",
                "performed_at": "2026-07-20T00:00:00Z",
                "original_image_count": 4,
            },
            core["tech_headers"],
        ),
        expected_status=201,
    )
    record = document_repeat(core, exam["id"], reason_code="POSITIONING", repeat_image_count=1)
    validate_success(
        api.retract_repeat_record(
            record["id"],
            retract_payload(retraction_reason="Logged against the wrong patient"),
            qa_headers,
        )
    )
    failure = report_failure(
        core,
        headers=coordinator_headers,
        failure_code="DISPLAY",
        severity="MINOR",
        detected_at="2026-07-28T00:00:00Z",
    )
    assert failure["requires_post_repair_survey"] is False
    validate_success(
        api.restore_equipment_failure(
            failure["id"],
            restore_payload(repair_note="Review monitor recalibrated"),
            coordinator_headers,
        )
    )
    locked = close_cycle(core, cycle["id"], "PPV1_SCREENING")
    assert locked["status"] == "LOCKED"

    validate_error(
        api.close_audit_cycle(cycle["id"], {"variant": "PPV3_BIOPSY_ALL"}, qa_headers),
        "ERR_AUDIT_CYCLE_NOT_CLOSABLE",
        expected_status=409,
    )
    after_cycle = read_cycle(cycle["id"], qa_headers)
    assert after_cycle["status"] == "LOCKED"
    assert after_cycle["variant_at_close"] == "PPV1_SCREENING"
    assert_instant_equals(after_cycle["locked_at"], "2026-08-01T00:00:00Z", "locked_at")

    validate_error(
        api.restore_equipment_failure(
            failure["id"], restore_payload(repair_note="Restoring twice"), coordinator_headers
        ),
        "ERR_FAILURE_ALREADY_RESOLVED",
        expected_status=409,
    )
    after_failure = read_failure(failure["id"])
    assert after_failure["status"] == "REPAIR_VERIFIED"
    assert_instant_equals(after_failure["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")
    assert after_failure["repair_note"] == "Review monitor recalibrated"
    assert read_unit(core["unit_id"])["operational_state"] == "IN_SERVICE"

    validate_error(
        api.retract_repeat_record(
            record["id"], retract_payload(retraction_reason="Retracting twice"), qa_headers
        ),
        "ERR_REPEAT_RECORD_ALREADY_RETRACTED",
        expected_status=409,
    )
    after_record = validate_success(api.get_repeat_record(record["id"], qa_headers))
    assert after_record["retracted"] is True
    assert after_record["retraction_reason"] == "Logged against the wrong patient"

    assert_unit_image_ledger(
        read_unit(core["unit_id"]), total_images_acquired=4, repeat_images_acquired=0
    )


def test_a_second_open_packet_on_the_same_unit_is_rejected(
    api, funded_core, coordinator_headers
):
    """The one-open-packet rule escrows no second fee and burns no second attempt.

    PRD: "**One open submission per unit (priority 71)** — at most one non-terminal
    `ClinicalImageReviewSubmission`, meaning one in `SUBMITTED` or
    `REVISION_REQUIRED`, may exist on a unit: `ERR_SUBMISSION_ALREADY_OPEN`, 409."

    Design: Corner/errors/a_second_open_packet_on_the_same_unit_is_rejected
    """
    core = funded_core
    exams = setup_two_interpreted_exams(core)
    exam_ids = [exams[0]["id"], exams[1]["id"]]

    first = file_packet(core, exam_ids, reviewer_note="First packet")
    assert first["status"] == "SUBMITTED"
    current_version = unit_version(core)

    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                exam_ids,
                current_version,
                reviewer_note="Second packet while the first is open",
            ),
            coordinator_headers,
        ),
        "ERR_SUBMISSION_ALREADY_OPEN",
        expected_status=409,
    )

    response = api.list_unit_clinical_image_reviews(core["unit_id"], coordinator_headers)
    assert list_total_count(response) == 1
    rows = response.json()["data"]
    assert ids_of(rows) == [first["id"]]
    assert rows[0]["status"] == "SUBMITTED"
    assert rows[0]["attempt_number"] == 1

    unit = read_unit(core["unit_id"])
    assert unit["reaccreditation_attempts_remaining"] == 2
    assert unit["version"] == current_version

    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=750000,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
