"""Consistency model: every write and every cascade it fires is visible in the
same response and in an immediate re-read, with no sweep in between."""

from test_helpers import (
    acquire_exam,
    assert_instant_equals,
    exam_payload,
    list_total_count,
    read_exam,
    read_facility,
    read_unit,
    unit_version,
    validate_error,
    validate_success,
)


def test_a_write_and_its_derived_fields_are_visible_in_the_same_response(
    api, core, coordinator_headers, qa_headers
):
    """The interpretation answer already carries every field it derived.

    PRD: "It recomputes `recall_flag`, which is true exactly when the `exam_type`
    is `SCREENING` **and** the `birads_assessment` is 0; a diagnostic BI-RADS 0 is
    not a recall, and a screening BI-RADS 4 is not a recall either."

    Design: Corner/consistency_model/a_write_and_its_derived_fields_are_visible_in_the_same_response
    """
    exam = acquire_exam(core, patient_ref="PT-SC-1", performed_at="2026-07-20T00:00:00Z")
    before = read_exam(exam["id"])
    assert before["report_status"] == "AWAITING_INTERPRETATION"
    assert_instant_equals(before["report_due_at"], "2026-08-19T00:00:00Z", "report_due_at")
    assert before["interpreted_at"] is None
    assert before["interpreted_late"] is False
    assert before["notification_status"] == "NOT_REQUIRED"

    written = validate_success(
        api.interpret_exam(
            exam["id"],
            {"birads_assessment": 4, "density_category": "C"},
            core["rad_headers"],
        )
    )
    assert written["report_status"] == "INTERPRETED_FINAL"
    assert_instant_equals(written["interpreted_at"], "2026-08-01T00:00:00Z", "interpreted_at")
    assert_instant_equals(written["report_due_at"], "2026-07-27T00:00:00Z", "report_due_at")
    assert written["interpreted_late"] is True
    assert written["recall_flag"] is False
    assert written["density_category"] == "C"
    assert written["birads_assessment"] == 4
    assert written["notification_status"] == "PENDING"
    assert written["follow_up_status"] == "NOT_REQUIRED"
    assert written["interpreting_physician_id"] == core["rad_id"]

    reread = read_exam(exam["id"], qa_headers)
    for field in (
        "report_status",
        "interpreted_at",
        "report_due_at",
        "interpreted_late",
        "recall_flag",
        "density_category",
        "birads_assessment",
        "notification_status",
        "follow_up_status",
        "interpreting_physician_id",
        "version",
    ):
        assert reread[field] == written[field], (
            f"{field}: immediate re-read returned {reread[field]}, "
            f"the write returned {written[field]}"
        )

    assert read_facility(core["facility_id"])["open_notice_obligations"] == 1


def test_cross_entity_cascades_are_visible_immediately_after_the_triggering_request(
    api, core, coordinator_headers
):
    """The unit is unusable in the very next request, with no run in between.

    PRD: "When `requires_post_repair_survey` is true the unit's `operational_state`
    moves `IN_SERVICE` to `OUT_OF_SERVICE`, the facility posture is recomputed off
    that change, and the unit's `version` advances."

    Design: Corner/consistency_model/cross_entity_cascades_are_visible_immediately_after_the_triggering_request
    """
    before_version = unit_version(core)
    assert read_unit(core["unit_id"])["operational_state"] == "IN_SERVICE"

    failure = validate_success(
        api.create_equipment_failure(
            core["unit_id"],
            {
                "failure_code": "DETECTOR",
                "severity": "MAJOR",
                "detected_at": "2026-07-31T00:00:00Z",
            },
            core["phys_headers"],
        ),
        expected_status=201,
    )
    assert failure["status"] == "OPEN"
    assert failure["severity"] == "MAJOR"
    assert failure["failure_code"] == "DETECTOR"
    assert failure["requires_post_repair_survey"] is True
    assert failure["resolved_at"] is None

    unit = read_unit(core["unit_id"])
    assert unit["operational_state"] == "OUT_OF_SERVICE"
    assert unit["accreditation_status"] == "PROVISIONAL"
    assert unit["version"] == before_version + 1

    # The facility's only unit is now out of service, which is the fourth
    # level-one trigger: "or the facility has at least one unit and every one of
    # its units has `operational_state` `OUT_OF_SERVICE`."
    assert read_facility(core["facility_id"])["compliance_posture"] == "SUSPENDED"

    validate_error(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-8001",
                performed_at="2026-08-01T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        "ERR_UNIT_NOT_IN_SERVICE",
        expected_status=409,
    )
    assert list_total_count(api.list_exams(coordinator_headers)) == 0
