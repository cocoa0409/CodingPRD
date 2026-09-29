"""Entity surface: creation echoes, declared defaults, retrieval, listing and shape."""

import pytest

from test_helpers import (
    acquire_exam,
    assert_common_fields,
    assert_credit_shape,
    assert_facility_ledger,
    assert_instant_equals,
    ct_policy_payload,
    facility_payload,
    ids_of,
    interpret,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_total_count,
    personnel_payload,
    read_facility,
    read_submission,
    read_unit,
    unit_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_FACILITY_ID = "00000000-0000-4000-8000-0000000000ff"


def test_state_policy_creation_echoes_every_declared_field(api, reviewer_headers):
    """All eleven supplied inputs come back unchanged beside the system fields.

    PRD: "`required_notice_codes` is an ordered list of state-specific notice
    codes, empty when omitted, and its declared order is preserved verbatim
    wherever it is used."

    Design: Corner/entities/state_policy_creation_echoes_every_declared_field
    """
    payload = ct_policy_payload()
    policy = validate_success(
        api.create_state_policy(payload, reviewer_headers), expected_status=201
    )
    for field, expected in payload.items():
        assert policy[field] == expected, f"{field}: expected {expected}, got {policy[field]}"
    assert policy["required_notice_codes"] == ["CT-DENS-1", "CT-SUPP-2"]
    assert_common_fields(policy, expected_version=1)
    assert is_valid_uuid(policy["id"])
    assert is_iso8601_timestamp(policy["created_at"])
    assert is_iso8601_timestamp(policy["updated_at"])


def test_facility_and_audit_cycle_defaults_apply_when_inputs_are_omitted(
    api, coordinator_headers, reviewer_headers, qa_headers
):
    """Capacity defaults to 2, the cycle follow-up window to 365, and metrics stay null.

    PRD: "The payload carries a required `period_start`, a required `period_end`
    that must be strictly after `period_start` (`ERR_INVALID_REQUEST`), and an
    optional `followup_window_days` defaulting to 365 and constrained to the
    inclusive range 30 through 730."

    Design: Corner/entities/facility_and_audit_cycle_defaults_applied_when_optional_inputs_are_omitted
    """
    policy = validate_success(
        api.create_state_policy(ct_policy_payload(), reviewer_headers), expected_status=201
    )
    facility = validate_success(
        api.create_facility(
            facility_payload(
                policy["id"],
                name="Default Harbor Imaging",
                supplemental_concurrent_capacity=None,
            ),
            coordinator_headers,
        ),
        expected_status=201,
    )
    assert facility["supplemental_concurrent_capacity"] == 2
    assert facility["compliance_posture"] == "COMPLIANT"
    assert_facility_ledger(
        facility,
        total_funded_cents=0,
        prepaid_credit_cents=0,
        fee_held_cents=0,
        fee_consumed_cents=0,
    )
    assert facility["open_notice_obligations"] == 0
    assert facility["last_compliance_run_at"] is None
    radiologist = validate_success(
        api.create_personnel(
            facility["id"],
            personnel_payload(
                "INTERPRETING_PHYSICIAN",
                full_name="Rosa Radiologist",
                initial_qualification_on="2024-03-01T00:00:00Z",
                initial_training_hours=65,
                initial_read_volume=260,
            ),
            coordinator_headers,
        ),
        expected_status=201,
    )
    cycle = validate_success(
        api.create_audit_cycle(
            radiologist["id"],
            {"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-07-01T00:00:00Z"},
            qa_headers,
        ),
        expected_status=201,
    )
    assert cycle["followup_window_days"] == 365
    assert cycle["status"] == "OPEN"
    assert cycle["variant_at_close"] is None
    assert cycle["screening_exam_count"] is None
    assert cycle["recall_rate_pct"] is None
    assert cycle["ppv_pct"] is None


def test_unit_retrieval_returns_the_stored_row_and_its_system_fields(api, core, inspector_headers):
    """The read echoes the create, and the client never chose the accreditation fields.

    PRD: "A new unit lands with `accreditation_status` `PROVISIONAL` and
    `operational_state` `IN_SERVICE` — two dimensions that evolve entirely
    independently of one another — with `survey_compliance` `OVERDUE` because no
    physicist survey has passed yet, a null `last_passed_survey_end`, and
    `reaccreditation_attempts_remaining` of 3."

    Design: Corner/entities/unit_retrieval_returns_the_stored_row_and_its_system_fields
    """
    unit = validate_success(api.get_unit(core["unit_id"], inspector_headers))
    assert unit["facility_id"] == core["facility_id"]
    assert unit["manufacturer"] == "Hologic"
    assert unit["model_serial"] == "SEL-9001"
    assert unit["modality"] == "DBT_3D"
    assert_instant_equals(
        unit["accreditation_expires_on"], "2027-06-30T00:00:00Z", "accreditation_expires_on"
    )
    assert unit["accreditation_status"] == "PROVISIONAL"
    assert unit["operational_state"] == "IN_SERVICE"
    assert unit["survey_compliance"] == "OVERDUE"
    assert unit["reaccreditation_attempts_remaining"] == 3
    assert_common_fields(unit, expected_version=1)
    assert_instant_equals(unit["created_at"], "2026-08-01T00:00:00Z", "created_at")


def test_exam_listing_paginates_with_total_count_and_has_more(api, core, coordinator_headers):
    """Two pages of a three-row list, then a filter that narrows it to the unread exam.

    PRD: "The `meta` block of a list response carries `limit` (the effective page
    size actually applied), `offset` (the effective starting position),
    `total_count` (the number of rows matching the filters before pagination), and
    `has_more` (true when rows remain beyond this page)."

    Design: Corner/entities/exam_listing_paginates_with_total_count_and_has_more
    """
    first = acquire_exam(core, patient_ref="PT-1001", performed_at="2026-07-20T00:00:00Z")
    interpret(core, first["id"], birads=1, density="B")
    second = acquire_exam(core, patient_ref="PT-1002", performed_at="2026-07-21T00:00:00Z")
    interpret(core, second["id"], birads=2, density="C")
    third = acquire_exam(core, patient_ref="PT-1003", performed_at="2026-07-22T00:00:00Z")

    page_one, meta_one = validate_paginated(
        api.list_exams(coordinator_headers, {"unit_id": core["unit_id"], "limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_exams(coordinator_headers, {"unit_id": core["unit_id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2
    assert ids_of(page_one + page_two) == [first["id"], second["id"], third["id"]]

    filtered, meta_three = validate_paginated(
        api.list_exams(
            coordinator_headers,
            {"unit_id": core["unit_id"], "report_status": "AWAITING_INTERPRETATION"},
        )
    )
    assert ids_of(filtered) == [third["id"]]
    assert meta_three["total_count"] == 1
    assert meta_three["has_more"] is False


def test_get_unit_with_an_unknown_id_returns_not_found(api, core, coordinator_headers):
    """A well-formed but unpersisted unit id yields the unit's own 404 code.

    PRD: "**Path existence (priority 10)** — every id embedded in the request path
    exists, validated left to right: 404 with the code for the entity that was not
    found — `ERR_STATE_POLICY_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_EXAM_NOT_FOUND`,
    `ERR_LETTER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FAILURE_EVENT_NOT_FOUND`,
    `ERR_REPEAT_RECORD_NOT_FOUND`, `ERR_AUDIT_CYCLE_NOT_FOUND`."

    Design: Corner/entities/get_unit_with_an_unknown_id_returns_not_found
    """
    validate_error(api.get_unit(UNKNOWN_ID, coordinator_headers), "ERR_UNIT_NOT_FOUND", 404)
    assert (
        list_total_count(api.list_facility_units(core["facility_id"], coordinator_headers)) == 1
    )


def test_exam_creation_without_a_patient_state_code_is_rejected(api, core):
    """The residence state drives policy resolution and cannot be backfilled.

    PRD: "The payload names the `unit_id` of the unit that acquired the images; the
    `technologist_id` of the acquiring technologist, which must equal the caller's own
    `X-User-ID`; a pseudonymous `patient_ref` that repeats across that patient's
    exams; the `patient_state_code`, exactly two uppercase letters, naming the
    patient's state of residence and thereby driving policy resolution; the
    `exam_type`, either `SCREENING` or `DIAGNOSTIC`; the `performed_at` acquisition
    instant, which may not be after the logical clock; and `original_image_count`,
    the number of images acquired on the first pass, at least 1."

    Design: Corner/entities/exam_creation_missing_required_patient_state_code_is_rejected
    """
    payload = {
        "unit_id": core["unit_id"],
        "technologist_id": core["tech_id"],
        "patient_ref": "PT-1101",
        "exam_type": "SCREENING",
        "performed_at": "2026-07-20T00:00:00Z",
        "original_image_count": 4,
    }
    validate_error(
        api.create_exam(payload, core["tech_headers"]), "ERR_INVALID_REQUEST", 400
    )
    assert (
        list_total_count(
            api.list_exams(core["coord_headers"], {"unit_id": core["unit_id"]})
        )
        == 0
    )
    assert read_unit(core["unit_id"])["total_images_acquired"] == 0


def test_near_miss_modality_and_lowercase_state_code_are_both_rejected(
    api, core, coordinator_headers, reviewer_headers
):
    """"DBT" is not a modality and "Ct" is not a state code, and neither persists a row.

    PRD: "8. **Request schema (priority 20)** — required body fields present, enum
    values in range, numeric ranges honored, state codes exactly two uppercase
    letters, and conditional field pairings satisfied: `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/unit_modality_rejects_an_unknown_enum_value_and_a_bad_state_code_is_rejected
    """
    validate_error(
        api.create_unit(
            core["facility_id"],
            unit_payload(model_serial="SEL-BAD", modality="DBT"),
            coordinator_headers,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_state_policy(
            {
                "state_code": "Ct",
                "density_notice_rule": "FEDERAL_ONLY",
                "lay_summary_max_reading_grade": 8,
                "lay_summary_deadline_days": 30,
                "supplemental_coverage_mandate": "NONE",
            },
            reviewer_headers,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    assert (
        list_total_count(api.list_facility_units(core["facility_id"], coordinator_headers)) == 1
    )
    assert (
        validate_success(api.get_state_policy(core["policy_id"], coordinator_headers))["id"]
        == core["policy_id"]
    )


def test_qualification_credit_is_immutable_and_carries_no_version_field(
    api, core, coordinator_headers
):
    """A credit exposes only its own fields, with no version and no updated_at.

    PRD: "Credit rows are immutable and, on their own, change nothing about the
    person: posting a credit never moves `qualification_status` or `ce_status`."

    Design: Corner/entities/qualification_credit_is_immutable_and_carries_no_version_field
    """
    credit = validate_success(
        api.create_credit(
            core["tech_id"],
            {
                "credit_type": "CATEGORY_1_CE",
                "awarded_on": "2026-01-01T00:00:00Z",
                "ce_hours": 15,
                "source_note": "DBT refresher",
            },
            coordinator_headers,
        ),
        expected_status=201,
    )
    assert credit["personnel_id"] == core["tech_id"]
    assert credit["credit_type"] == "CATEGORY_1_CE"
    assert credit["ce_hours"] == pytest.approx(15, abs=0.01)
    assert_instant_equals(credit["awarded_on"], "2026-01-01T00:00:00Z", "awarded_on")
    assert credit.get("exam_count") is None
    assert credit.get("modality") is None
    assert_credit_shape(credit)
    assert (
        list_total_count(
            api.list_personnel_credits(
                core["tech_id"], coordinator_headers, {"credit_type": "CATEGORY_1_CE"}
            )
        )
        == 1
    )
    assert (
        list_total_count(
            api.list_personnel_credits(
                core["tech_id"], coordinator_headers, {"credit_type": "READ_VOLUME"}
            )
        )
        == 0
    )


def test_personnel_creation_under_an_unknown_facility_returns_not_found(
    api, core, coordinator_headers
):
    """The leftmost missing path segment decides the code, so the facility 404 wins.

    PRD: "Left-to-right means the leftmost missing segment decides the code:
    addressing a unit under a non-existent facility yields `ERR_FACILITY_NOT_FOUND`,
    never `ERR_UNIT_NOT_FOUND`."

    Design: Corner/entities/personnel_creation_under_an_unknown_facility_returns_not_found
    """
    validate_error(
        api.create_personnel(
            UNKNOWN_FACILITY_ID,
            personnel_payload(
                "TECHNOLOGIST",
                full_name="Nadia Nobody",
                initial_qualification_on="2024-02-01T00:00:00Z",
                modality_certifications=None,
            ),
            coordinator_headers,
        ),
        "ERR_FACILITY_NOT_FOUND",
        404,
    )
    listed = api.list_facility_personnel(core["facility_id"], coordinator_headers)
    assert list_total_count(listed) == 3


def test_one_exam_pair_can_be_cited_by_two_successive_packets(
    api, funded_core, coordinator_headers
):
    """The exam_ids junction is many-to-many, so a withdrawn packet and a fresh one share it.

    PRD: "`exam_ids` is a many-to-many packet membership rather than a scalar
    reference: it must contain at least 2 distinct ids with no duplicates
    (`ERR_PACKET_TOO_SMALL`), every id must resolve to an existing exam
    (`ERR_EXAM_NOT_FOUND`), every one of those exams must have been acquired on this
    same unit (`ERR_EXAM_UNIT_MISMATCH`), and every one must be in `report_status`
    `INTERPRETED_FINAL` or `AMENDED` (`ERR_PACKET_EXAM_NOT_FINAL`) — a packet of
    un-read images certifies nothing."

    Design: Corner/entities/one_exam_can_be_cited_by_two_successive_packets_many_to_many
    """
    from test_helpers import file_packet, unit_version

    core = funded_core
    pair = []
    for ref, day in (("PT-1201", "2026-07-20T00:00:00Z"), ("PT-1202", "2026-07-21T00:00:00Z")):
        exam = acquire_exam(core, patient_ref=ref, performed_at=day)
        interpret(core, exam["id"], birads=1, density="B")
        pair.append(exam["id"])
    first = file_packet(core, pair, reviewer_note="First packet")
    validate_success(
        api.withdraw_clinical_image_review(
            first["id"],
            withdraw_payload(
                expected_unit_version=unit_version(core),
                withdrawal_reason="Rebuilding the packet",
            ),
            coordinator_headers,
        )
    )
    second = file_packet(core, pair, reviewer_note="Second packet citing the same two exams")
    assert sorted(second["exam_ids"]) == sorted(pair)
    assert second["attempt_number"] == 1
    assert second["status"] == "SUBMITTED"
    withdrawn = read_submission(first["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert sorted(withdrawn["exam_ids"]) == sorted(pair)
    assert (
        list_total_count(api.list_exams(coordinator_headers, {"unit_id": core["unit_id"]})) == 2
    )
    assert (
        list_total_count(
            api.list_unit_clinical_image_reviews(core["unit_id"], coordinator_headers)
        )
        == 2
    )
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        prepaid_credit_cents=750000,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
