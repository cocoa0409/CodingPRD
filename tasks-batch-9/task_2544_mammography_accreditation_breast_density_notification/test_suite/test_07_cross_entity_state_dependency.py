"""Transitions gated on the state of an entity the request never names."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    acquire_exam,
    assert_facility_ledger,
    assert_instant_equals,
    close_inspection,
    create_draft_survey,
    determine_coverage,
    interpret,
    packet_payload,
    read_facility,
    read_failure,
    read_order,
    read_unit,
    record_level_1_inspection,
    recommend_order,
    report_qualifying_failure,
    restore_payload,
    unit_version,
    validate_error,
    validate_success,
)


@pytest.fixture
def critical_failure(core):
    """A critical detector fault holds the unit out of service with no survey on file."""
    failure = report_qualifying_failure(
        core, severity="CRITICAL", detected_at="2026-07-30T00:00:00Z"
    )
    core["failure_id"] = failure["id"]
    return core


def test_restore_is_refused_while_no_post_repair_survey_has_passed(
    api, critical_failure, coordinator_headers
):
    """The failure event cannot verify itself without a passing survey on the unit.

    PRD: "When the event required a post-repair survey, a survey must exist on the
    same unit with `survey_type` `POST_REPAIR`, `status` `PASSED`, and an
    `effective_start` at or after the event's `detected_at`; otherwise the restore
    is refused with `ERR_POST_REPAIR_SURVEY_MISSING`, which is deliberately precise
    about ordering — a post-repair survey whose window opened before the failure was
    even detected cannot certify the repair."

    Design: Difficulty/cross_entity_state_dependency/unit_restore_blocked_until_a_post_repair_survey_passes
    """
    core = critical_failure
    response = api.restore_equipment_failure(
        core["failure_id"],
        restore_payload(repair_note="Detector module swapped, no physics survey yet"),
        coordinator_headers,
    )
    validate_error(response, "ERR_POST_REPAIR_SURVEY_MISSING", expected_status=409)
    failure = read_failure(core["failure_id"])
    assert failure["status"] == "OPEN"
    assert failure["resolved_at"] is None
    assert read_unit(core["unit_id"])["operational_state"] == "OUT_OF_SERVICE"


def test_the_same_restore_succeeds_once_the_post_repair_survey_passes(
    api, critical_failure, coordinator_headers
):
    """With the certifying survey in place the unit returns to service unchanged otherwise.

    PRD: "On success the event moves `OPEN` to `REPAIR_VERIFIED` with `resolved_at`
    stamped and `repair_note` stored, the unit's `operational_state` returns to
    `IN_SERVICE` when nothing else holds it down, the facility posture is
    recomputed, and the versions of the event and the unit advance."

    Design: Difficulty/cross_entity_state_dependency/unit_restore_blocked_until_a_post_repair_survey_passes
    """
    core = critical_failure
    validate_error(
        api.restore_equipment_failure(
            core["failure_id"],
            restore_payload(repair_note="Detector module swapped, no physics survey yet"),
            coordinator_headers,
        ),
        "ERR_POST_REPAIR_SURVEY_MISSING",
    )
    survey = create_draft_survey(
        core,
        survey_type="POST_REPAIR",
        effective_start="2026-07-31T00:00:00Z",
        effective_end="2026-08-31T00:00:00Z",
    )
    decided = validate_success(
        api.submit_physicist_survey(
            survey["id"],
            {
                "phantom_score": 6.5,
                "mean_glandular_dose_mgy": 2.50,
                "outcome_note": "Replacement detector meets all limits",
            },
            core["phys_headers"],
        )
    )
    assert decided["status"] == "PASSED"
    assert decided["survey_type"] == "POST_REPAIR"
    failure = validate_success(
        api.restore_equipment_failure(
            core["failure_id"],
            restore_payload(repair_note="Detector module swapped, post-repair survey passed"),
            coordinator_headers,
        )
    )
    assert failure["status"] == "REPAIR_VERIFIED"
    assert_instant_equals(failure["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")
    unit = read_unit(core["unit_id"])
    assert unit["operational_state"] == "IN_SERVICE"
    assert unit["survey_compliance"] == "CURRENT"
    assert_instant_equals(
        unit["last_passed_survey_end"], "2026-08-31T00:00:00Z", "last_passed_survey_end"
    )
    assert read_facility(core["facility_id"])["compliance_posture"] == "COMPLIANT"


@pytest.fixture
def suspended_facility_with_order(core):
    """The LEVEL_1 finding is recorded before the order exists, so nothing is referred out."""
    core["inspection"] = record_level_1_inspection(
        core, inspection_date="2026-07-28T00:00:00Z", finding_codes=["900.12(e)(5)"]
    )
    exam = acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-9601",
        performed_at="2026-07-29T00:00:00Z",
    )
    core["exam_id"] = exam["id"]
    order = recommend_order(
        core,
        exam["id"],
        "ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, recall workup",
    )
    core["order_id"] = order["id"]
    determine_coverage(core, order["id"])
    return core


def test_scheduling_is_refused_while_the_grandparent_facility_is_suspended(
    api, suspended_facility_with_order, coordinator_headers
):
    """The order's own state is fine; its facility's derived posture blocks the booking.

    PRD: "The order's `coverage_outcome` must no longer be `UNDETERMINED`
    (`ERR_COVERAGE_NOT_DETERMINED`), and the owning facility's `compliance_posture`
    must not be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`)."

    Design: Difficulty/cross_entity_state_dependency/supplemental_scheduling_blocked_while_the_facility_posture_is_suspended
    """
    core = suspended_facility_with_order
    response = api.schedule_supplemental_order(
        core["order_id"], {"appointment_start": "2026-08-10T09:00:00Z"}, coordinator_headers
    )
    validate_error(response, "ERR_FACILITY_SUSPENDED", expected_status=409)
    order = read_order(core["order_id"])
    assert order["status"] == "COVERAGE_DETERMINED"
    assert order["appointment_start"] is None


def test_closing_the_inspection_recomputes_the_posture_and_lets_the_booking_through(
    api, suspended_facility_with_order, coordinator_headers
):
    """Once the finding closes the posture reads CONDITIONAL and the identical call succeeds.

    PRD: "The `appointment_end` is derived from the modality's duration: 30 minutes
    for `ULTRASOUND`, 45 minutes for `MRI`, and 30 minutes for `CEM`."

    Design: Difficulty/cross_entity_state_dependency/supplemental_scheduling_blocked_while_the_facility_posture_is_suspended
    """
    core = suspended_facility_with_order
    validate_error(
        api.schedule_supplemental_order(
            core["order_id"], {"appointment_start": "2026-08-10T09:00:00Z"}, coordinator_headers
        ),
        "ERR_FACILITY_SUSPENDED",
    )
    closed = close_inspection(
        core, core["inspection"]["id"], closure_note="Corrective action verified on site"
    )
    assert closed["status"] == "CLOSED"
    assert read_facility(core["facility_id"])["compliance_posture"] == "CONDITIONAL"
    order = validate_success(
        api.schedule_supplemental_order(
            core["order_id"], {"appointment_start": "2026-08-10T09:00:00Z"}, coordinator_headers
        )
    )
    assert order["status"] == "SCHEDULED"
    assert_instant_equals(
        order["appointment_start"], "2026-08-10T09:00:00Z", "appointment_start"
    )
    assert_instant_equals(order["appointment_end"], "2026-08-10T09:30:00Z", "appointment_end")
    assert order["coverage_outcome"] == "COVERED_NO_COST_SHARE"


@pytest.fixture
def unread_exams(funded_core):
    """Two acquired exams that nobody has interpreted yet."""
    core = funded_core
    core["pair"] = [
        acquire_exam(core, patient_ref="PT-9701", performed_at="2026-07-25T00:00:00Z")["id"],
        acquire_exam(core, patient_ref="PT-9702", performed_at="2026-07-26T00:00:00Z")["id"],
    ]
    return core


def test_a_packet_of_unread_images_is_refused_and_escrows_nothing(
    api, unread_exams, coordinator_headers
):
    """Every cited exam must already be final, and a rejected filing costs nothing.

    PRD: "24. **Packet exams final (priority 57)** — every exam in a packet has
    `report_status` `INTERPRETED_FINAL` or `AMENDED`: `ERR_PACKET_EXAM_NOT_FINAL`,
    422."

    Design: Difficulty/cross_entity_state_dependency/packet_submission_requires_every_cited_exam_to_be_interpreted_final
    """
    core = unread_exams
    response = api.create_clinical_image_review(
        core["unit_id"],
        packet_payload(
            core["pair"],
            unit_version(core),
            reviewer_note="Packet built before the reads were finalized",
        ),
        coordinator_headers,
    )
    validate_error(response, "ERR_PACKET_EXAM_NOT_FINAL", expected_status=422)
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        prepaid_credit_cents=1000000,
        fee_held_cents=0,
        fee_consumed_cents=0,
    )
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 3


def test_the_same_packet_is_accepted_once_both_reads_are_finalized(
    api, unread_exams, coordinator_headers
):
    """Finalizing the two reads is the only change, and now the escrow is taken.

    PRD: "An accepted filing lands the submission in `status` `SUBMITTED` with
    `attempt_number` 1, `submitted_at` stamped at the logical clock, a null
    `reviewed_at`, a null `review_decision`, an empty `deficiency_categories`, and
    `fee_held_cents` of 250000."

    Design: Difficulty/cross_entity_state_dependency/packet_submission_requires_every_cited_exam_to_be_interpreted_final
    """
    core = unread_exams
    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                core["pair"],
                unit_version(core),
                reviewer_note="Packet built before the reads were finalized",
            ),
            coordinator_headers,
        ),
        "ERR_PACKET_EXAM_NOT_FINAL",
    )
    interpret(core, core["pair"][0], birads=1, density="B")
    interpret(core, core["pair"][1], birads=2, density="C")
    submission = validate_success(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                core["pair"],
                unit_version(core),
                reviewer_note="Packet resubmitted after both reads were finalized",
            ),
            coordinator_headers,
        ),
        expected_status=201,
    )
    assert submission["status"] == "SUBMITTED"
    assert submission["attempt_number"] == 1
    assert submission["fee_held_cents"] == 250000
    assert_instant_equals(submission["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        prepaid_credit_cents=750000,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
