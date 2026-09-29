"""Endpoints: listing mechanics, bulk-set atomicity, cross-reference linking and
recomputation on read."""

from test_helpers import (
    acquire_and_interpret,
    add_second_unit,
    add_unit,
    assert_instant_equals,
    assert_unit_image_ledger,
    create_facility,
    document_repeat,
    exam_payload,
    ids_of,
    list_total_count,
    packet_payload,
    read_exam,
    read_facility,
    read_failure,
    read_unit,
    report_failure,
    setup_two_interpreted_exams,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_list_filters_compose_with_pagination_and_the_default_page_size(
    api, core, coordinator_headers, reviewer_headers
):
    """`total_count` counts the filtered population, and the page is cut after that.

    PRD: "The `meta` block of a list response carries `limit` (the effective page
    size actually applied), `offset` (the effective starting position),
    `total_count` (the number of rows matching the filters before pagination), and
    `has_more` (true when rows remain beyond this page)."

    Design: Corner/endpoints/list_filters_compose_with_pagination_and_the_default_page_size
    """
    second_unit = add_second_unit(core["facility_id"])
    third_unit = add_unit(
        core["facility_id"], manufacturer="Hologic", model_serial="SEL-9003", modality="DBT_3D"
    )
    create_facility(
        core["policy_id"], name="Second Harbor Imaging", accreditation_body="STATE_CERTIFIED"
    )
    failure = report_failure(
        core,
        unit_id=third_unit["id"],
        headers=core["phys_headers"],
        failure_code="DETECTOR",
        severity="MAJOR",
        detected_at="2026-07-30T00:00:00Z",
    )

    rows, meta = validate_paginated(
        api.list_facility_units(
            core["facility_id"],
            coordinator_headers,
            params={"operational_state": "IN_SERVICE", "limit": 1, "offset": 1},
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["has_more"] is False
    assert third_unit["id"] not in ids_of(rows)
    assert rows[0]["id"] == second_unit["id"]

    all_rows, all_meta = validate_paginated(
        api.list_facility_units(core["facility_id"], coordinator_headers)
    )
    assert len(all_rows) == 3
    assert all_meta["total_count"] == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert all_meta["has_more"] is False

    facilities, fac_meta = validate_paginated(
        api.list_policy_facilities(
            core["policy_id"], reviewer_headers, params={"limit": 1, "offset": 0}
        )
    )
    assert len(facilities) == 1
    assert fac_meta["total_count"] == 2
    assert fac_meta["has_more"] is True

    assert read_unit(third_unit["id"])["operational_state"] == "OUT_OF_SERVICE"
    assert read_failure(failure["id"])["requires_post_repair_survey"] is True
    assert read_facility(core["facility_id"])["compliance_posture"] == "CONDITIONAL"


def test_a_packet_is_all_or_nothing_and_never_partially_accepted(
    api, funded_core, coordinator_headers
):
    """A single bad member id rejects the whole set, escrowing nothing and consuming nothing.

    PRD: "every one of those exams must have been acquired on this same unit
    (`ERR_EXAM_UNIT_MISMATCH`)"

    Design: Corner/endpoints/a_packet_is_all_or_nothing_and_never_partially_accepted
    """
    core = funded_core
    second_unit = add_second_unit(core["facility_id"])
    exams = setup_two_interpreted_exams(core)

    third_own = acquire_and_interpret(
        core, birads=1, density="B", patient_ref="PT-BK-C", performed_at="2026-07-22T00:00:00Z"
    )
    sibling = validate_success(
        api.create_exam(
            exam_payload(
                second_unit["id"],
                core["tech_id"],
                patient_ref="PT-BK-X",
                performed_at="2026-07-23T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.interpret_exam(
            sibling["id"],
            {"birads_assessment": 1, "density_category": "B"},
            core["rad_headers"],
        )
    )

    version = unit_version(core)
    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                [exams[0]["id"], exams[1]["id"], sibling["id"]],
                version,
                reviewer_note="Third id is from the sibling unit",
            ),
            coordinator_headers,
        ),
        "ERR_EXAM_UNIT_MISMATCH",
        expected_status=422,
    )

    assert (
        list_total_count(
            api.list_unit_clinical_image_reviews(core["unit_id"], coordinator_headers)
        )
        == 0
    )
    facility = read_facility(core["facility_id"])
    assert facility["prepaid_credit_cents"] == 1000000
    assert facility["fee_held_cents"] == 0
    unit = read_unit(core["unit_id"])
    assert unit["reaccreditation_attempts_remaining"] == 3
    assert unit["version"] == version

    submission = validate_success(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                [exams[0]["id"], exams[1]["id"], third_own["id"]],
                version,
                reviewer_note="All three ids belong to this unit",
            ),
            coordinator_headers,
        ),
        expected_status=201,
    )
    assert len(submission["exam_ids"]) == 3
    assert submission["attempt_number"] == 1
    assert submission["status"] == "SUBMITTED"
    assert submission["fee_held_cents"] == 250000

    after = read_facility(core["facility_id"])
    assert after["prepaid_credit_cents"] == 750000
    assert after["fee_consumed_cents"] == 0
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2


def test_repeat_record_links_only_to_a_failure_on_the_same_unit(
    api, core, coordinator_headers, qa_headers
):
    """The optional link is validated before the unit's image ledger is touched.

    PRD: "**Failure unit match (priority 58)** — the referenced
    `EquipmentFailureEvent` belongs to the same unit as the exam being repeated:
    `ERR_FAILURE_UNIT_MISMATCH`, 422. Applies to `POST /exams/{id}/repeat-records`."

    Design: Corner/endpoints/repeat_record_links_only_to_a_failure_on_the_same_unit
    """
    second_unit = add_second_unit(core["facility_id"])
    exam = validate_success(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-XR-1",
                performed_at="2026-07-20T00:00:00Z",
                original_image_count=4,
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    own_failure = report_failure(
        core,
        failure_code="DISPLAY",
        severity="MINOR",
        detected_at="2026-07-19T00:00:00Z",
    )
    other_failure = report_failure(
        core,
        unit_id=second_unit["id"],
        failure_code="DISPLAY",
        severity="MINOR",
        detected_at="2026-07-19T00:00:00Z",
    )

    validate_error(
        api.create_repeat_record(
            exam["id"],
            {
                "reason_code": "EQUIPMENT_FAILURE",
                "repeat_image_count": 2,
                "equipment_failure_id": other_failure["id"],
            },
            core["tech_headers"],
        ),
        "ERR_FAILURE_UNIT_MISMATCH",
        expected_status=422,
    )
    assert read_exam(exam["id"])["repeat_image_count"] == 0
    assert read_unit(core["unit_id"])["total_images_acquired"] == 4

    record = document_repeat(
        core,
        exam["id"],
        reason_code="EQUIPMENT_FAILURE",
        repeat_image_count=2,
        equipment_failure_id=own_failure["id"],
    )
    assert record["equipment_failure_id"] == own_failure["id"]
    assert record["retracted"] is False
    assert_instant_equals(record["documented_at"], "2026-08-01T00:00:00Z", "documented_at")
    assert read_exam(exam["id"])["repeat_image_count"] == 2

    assert_unit_image_ledger(
        read_unit(core["unit_id"]),
        total_images_acquired=6,
        repeat_images_acquired=2,
        image_based_repeat_rate_pct=33.33,
        patient_based_repeat_rate_pct=100.00,
        repeat_rate_flag=True,
    )
    assert_unit_image_ledger(
        read_unit(second_unit["id"]),
        total_images_acquired=0,
        image_based_repeat_rate_pct=None,
    )
    assert (
        list_total_count(
            api.list_repeat_records(
                qa_headers, params={"equipment_failure_id": own_failure["id"]}
            )
        )
        == 1
    )


def test_interpretation_retroactively_tightens_the_report_due_date_and_flags_it_late(
    api, core, coordinator_headers
):
    """The urgent window is measured from `performed_at`, so the read lands past it.

    PRD: "It re-derives the reporting deadline: when the recorded
    `birads_assessment` is one of 0, 4 or 5, the urgency of the finding
    retroactively tightens `report_due_at` to the `performed_at` instant plus the
    governing policy's `urgent_report_turnaround_days`, replacing the routine
    deadline the exam has been carrying since acquisition; for any other assessment
    the routine `report_due_at` stands."

    Design: Corner/endpoints/interpretation_retroactively_tightens_the_report_due_date_and_flags_it_late
    """
    exam = validate_success(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-UR-1",
                performed_at="2026-07-20T00:00:00Z",
                original_image_count=4,
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    before = read_exam(exam["id"])
    assert_instant_equals(before["report_due_at"], "2026-08-19T00:00:00Z", "report_due_at")
    assert before["interpreted_at"] is None
    assert before["interpreted_late"] is False

    validate_success(
        api.interpret_exam(
            exam["id"],
            {"birads_assessment": 4, "density_category": "D"},
            core["rad_headers"],
        )
    )

    after = read_exam(exam["id"])
    assert_instant_equals(after["report_due_at"], "2026-07-27T00:00:00Z", "report_due_at")
    assert_instant_equals(after["interpreted_at"], "2026-08-01T00:00:00Z", "interpreted_at")
    assert after["interpreted_late"] is True
    assert after["report_status"] == "INTERPRETED_FINAL"
    assert after["notification_status"] == "PENDING"
    assert after["recall_flag"] is False
    assert after["density_category"] == "D"
    assert read_facility(core["facility_id"])["open_notice_obligations"] == 1
