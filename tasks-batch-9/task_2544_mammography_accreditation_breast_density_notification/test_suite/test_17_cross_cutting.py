"""Cross-cutting layers: optimistic concurrency on both tokens, per-request
version monotonicity, and the replayed operations checkpoint."""

from test_helpers import (
    acquire_exam,
    assert_compliance_run,
    assert_facility_ledger,
    assert_instant_equals,
    assert_ledger_identity,
    assert_personnel_state,
    exam_version,
    file_packet,
    generate_letter,
    interpret,
    letter_payload,
    list_total_count,
    packet_payload,
    read_exam,
    read_facility,
    read_letter,
    read_personnel,
    read_submission,
    read_unit,
    report_failure,
    resubmit_packet,
    review_packet,
    run_compliance,
    setup_dense_screening_exam,
    setup_two_interpreted_exams,
    unit_version,
    validate_error,
    validate_success,
)


def test_stale_unit_version_is_rejected_on_packet_create_and_on_resubmit(
    api, funded_core, coordinator_headers
):
    """The superseded token is refused ahead of the one-open-packet rule.

    PRD: "Creating a clinical image review submission on a unit requires a
    non-optional `expected_unit_version` field carrying the client's last observed
    `version` of that `MammographyUnit`. If the value does not match the unit's
    current `version`, the request is rejected with `ERR_STALE_UNIT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_rejected_on_packet_create_and_on_resubmit
    """
    core = funded_core
    exams = setup_two_interpreted_exams(core)
    exam_ids = [exams[0]["id"], exams[1]["id"]]

    stale_version = unit_version(core)
    submission = file_packet(
        core, exam_ids, expected_unit_version=stale_version, reviewer_note="First filing"
    )
    assert submission["status"] == "SUBMITTED"
    assert submission["attempt_number"] == 1
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=750000,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
    assert_ledger_identity(read_facility(core["facility_id"]))

    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(exam_ids, stale_version, reviewer_note="Replayed filing"),
            coordinator_headers,
        ),
        "ERR_STALE_UNIT_VERSION",
        expected_status=412,
    )

    unit_after_replay = read_unit(core["unit_id"])
    assert unit_after_replay["reaccreditation_attempts_remaining"] == 2
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=750000,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
    assert (
        list_total_count(
            api.list_unit_clinical_image_reviews(core["unit_id"], coordinator_headers)
        )
        == 1
    )

    sent_back = review_packet(
        core, submission["id"], "REVISION_REQUIRED", reviewer_note="Positioning deficiencies"
    )
    assert sent_back["status"] == "REVISION_REQUIRED"
    assert_ledger_identity(read_facility(core["facility_id"]))

    validate_error(
        api.resubmit_clinical_image_review(
            submission["id"],
            packet_payload(exam_ids, stale_version, reviewer_note="Stale refiling"),
            coordinator_headers,
        ),
        "ERR_STALE_UNIT_VERSION",
        expected_status=412,
    )
    still_open = read_submission(submission["id"])
    assert still_open["status"] == "REVISION_REQUIRED"
    assert still_open["attempt_number"] == 1
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2

    current_version = unit_version(core)
    assert current_version > stale_version

    refiled = resubmit_packet(
        core,
        submission["id"],
        exam_ids,
        expected_unit_version=current_version,
        reviewer_note="Refiled against the current version",
    )
    assert refiled["status"] == "SUBMITTED"
    assert refiled["attempt_number"] == 2
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 1
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=500000,
        fee_held_cents=250000,
        fee_consumed_cents=250000,
    )
    assert_ledger_identity(read_facility(core["facility_id"]))


def test_stale_exam_version_is_rejected_on_letter_generation_even_when_the_state_allows_it(
    api, core, coordinator_headers
):
    """The same superseded token is refused before and after the state reopens.

    PRD: "Generating a notification letter on an exam requires a non-optional
    `expected_exam_version` field carrying the client's last observed `version` of
    that `Exam`. A mismatch with the exam's current `version` is rejected with
    `ERR_STALE_EXAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_exam_version_is_rejected_on_letter_generation_even_when_the_state_allows_it
    """
    exam = setup_dense_screening_exam(core, density="C", birads=1)
    stale_version = exam_version(exam["id"])

    first_letter = generate_letter(
        core, exam["id"], expected_exam_version=stale_version, dispatch_channel="MAIL"
    )
    assert first_letter["status"] == "QUEUED"
    assert read_exam(exam["id"])["notification_status"] == "GENERATED"

    validate_error(
        api.create_notification_letter(
            exam["id"],
            letter_payload(stale_version, dispatch_channel="MAIL"),
            coordinator_headers,
        ),
        "ERR_STALE_EXAM_VERSION",
        expected_status=412,
    )

    amended = validate_success(
        api.amend_exam(
            exam["id"],
            {"birads_assessment": 2, "amendment_reason": "Assessment corrected on review"},
            core["rad_headers"],
        )
    )
    assert amended["report_status"] == "AMENDED"
    assert amended["notification_status"] == "PENDING"
    assert read_letter(first_letter["id"])["status"] == "SUPERSEDED"

    validate_error(
        api.create_notification_letter(
            exam["id"],
            letter_payload(stale_version, dispatch_channel="MAIL"),
            coordinator_headers,
        ),
        "ERR_STALE_EXAM_VERSION",
        expected_status=412,
    )

    current_version = exam_version(exam["id"])
    assert current_version > stale_version

    second_letter = generate_letter(
        core, exam["id"], expected_exam_version=current_version, dispatch_channel="MAIL"
    )
    assert second_letter["status"] == "QUEUED"
    assert second_letter["id"] != first_letter["id"]
    assert read_exam(exam["id"])["notification_status"] == "GENERATED"
    assert (
        list_total_count(api.list_exam_notification_letters(exam["id"], coordinator_headers)) == 2
    )


def test_version_increments_once_per_write_and_never_on_a_read(
    api, funded_core, coordinator_headers, qa_headers
):
    """Reads and a non-mutating child row leave the counter alone; writes add one.

    PRD: "Most resources additionally carry `updated_at` — the same format,
    refreshed on every accepted mutation — and `version`, an integer that starts at
    1 on creation and increases by exactly 1 on every accepted mutation of that
    resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_write_and_never_on_a_read
    """
    core = funded_core

    first_read = read_unit(core["unit_id"], coordinator_headers)
    assert first_read["version"] == 1
    assert first_read["accreditation_status"] == "PROVISIONAL"
    assert first_read["operational_state"] == "IN_SERVICE"
    second_read = read_unit(core["unit_id"], qa_headers)
    assert second_read["version"] == 1

    failure = report_failure(
        core,
        headers=core["tech_headers"],
        failure_code="DISPLAY",
        severity="MINOR",
        detected_at="2026-07-28T00:00:00Z",
    )
    assert failure["status"] == "OPEN"
    assert failure["requires_post_repair_survey"] is False
    assert failure["version"] == 1
    after_failure = read_unit(core["unit_id"])
    assert after_failure["version"] == 1
    assert after_failure["operational_state"] == "IN_SERVICE"

    first_exam = acquire_exam(
        core, patient_ref="PT-1201", performed_at="2026-07-20T00:00:00Z"
    )
    assert first_exam["version"] == 1
    assert first_exam["report_status"] == "AWAITING_INTERPRETATION"
    assert read_unit(core["unit_id"])["version"] == 2

    interpreted = interpret(core, first_exam["id"], birads=1, density="B")
    assert interpreted["report_status"] == "INTERPRETED_FINAL"
    assert interpreted["version"] == 2
    assert read_unit(core["unit_id"])["version"] == 2

    second_exam = acquire_exam(
        core, patient_ref="PT-1202", performed_at="2026-07-21T00:00:00Z"
    )
    interpret(core, second_exam["id"], birads=1, density="B")
    assert read_unit(core["unit_id"])["version"] == 3

    submission = file_packet(
        core,
        [first_exam["id"], second_exam["id"]],
        reviewer_note="Two interpreted studies",
    )
    assert submission["version"] == 1
    assert read_unit(core["unit_id"])["version"] == 4

    passed = review_packet(core, submission["id"], "PASS", reviewer_note="Images acceptable")
    assert passed["status"] == "PASSED"
    assert passed["version"] == 2
    final_unit = read_unit(core["unit_id"])
    assert final_unit["version"] == 5
    assert final_unit["accreditation_status"] == "ACCREDITED"
    assert final_unit["reaccreditation_attempts_remaining"] == 3
    assert read_exam(first_exam["id"])["version"] == 2


def test_the_compliance_run_checkpoint_is_a_no_op_when_replayed_at_the_same_instant(
    api, core, coordinator_headers, qa_headers
):
    """The replayed run moves nothing and advances no entity version.

    PRD: "Running the same checkpoint twice at the same clock reading is safe: the
    second run finds nothing left to move and reports zeros across all seven
    counters while still restamping `ran_at`, `last_compliance_run_at` and the
    recomputed `compliance_posture`."

    Design: Corner/cross_cutting_complexity_layers/the_compliance_run_checkpoint_is_a_no_op_when_replayed_at_the_same_instant
    """
    exam = acquire_exam(core, patient_ref="PT-1201", performed_at="2026-07-20T00:00:00Z")
    interpret(core, exam["id"], birads=1, density="B")

    first = run_compliance(core, headers=coordinator_headers)
    assert_compliance_run(
        first,
        ran_at="2026-08-01T00:00:00Z",
        units_marked_reaccreditation_due=0,
        # `units_survey_overdue` is deliberately not pinned on either run: PRD
        # names the field but never says whether it counts units that *moved*
        # into `OVERDUE` on this sweep or censuses the units sitting in
        # `OVERDUE` afterwards, and those readings diverge for a unit that was
        # already `OVERDUE` at creation.
        exams_marked_delayed=0,
        letters_marked_delivered=0,
        orders_marked_lost=0,
        personnel_moved_to_grace=3,
        personnel_moved_to_deficient=0,
        compliance_posture="CONDITIONAL",
    )

    radiologist = read_personnel(core["rad_id"])
    assert_personnel_state(
        radiologist, qualification_status="QUALIFIED", ce_status="GRACE"
    )
    assert_instant_equals(
        radiologist["ce_deadline_at"], "2026-10-30T00:00:00Z", "ce_deadline_at"
    )
    assert_instant_equals(
        read_facility(core["facility_id"])["last_compliance_run_at"],
        "2026-08-01T00:00:00Z",
        "last_compliance_run_at",
    )
    checkpoint_version = radiologist["version"]

    second = run_compliance(core, headers=qa_headers)
    assert_compliance_run(
        second,
        ran_at="2026-08-01T00:00:00Z",
        units_marked_reaccreditation_due=0,
        exams_marked_delayed=0,
        letters_marked_delivered=0,
        orders_marked_lost=0,
        personnel_moved_to_grace=0,
        personnel_moved_to_deficient=0,
        compliance_posture="CONDITIONAL",
    )

    replayed = read_personnel(core["rad_id"])
    assert replayed["version"] == checkpoint_version
    assert_personnel_state(replayed, qualification_status="QUALIFIED", ce_status="GRACE")
    assert_instant_equals(
        replayed["ce_deadline_at"], "2026-10-30T00:00:00Z", "ce_deadline_at"
    )
    assert_instant_equals(
        read_facility(core["facility_id"])["last_compliance_run_at"],
        "2026-08-01T00:00:00Z",
        "last_compliance_run_at",
    )
    assert read_exam(exam["id"])["report_status"] == "INTERPRETED_FINAL"
