"""RBAC: authentication, the positive and negative halves of the role matrix,
shared operations, segregation of duties and identity-scoped ownership."""

import pytest

from test_helpers import (
    NO_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    add_personnel,
    add_second_radiologist,
    assert_instant_equals,
    create_facility,
    create_draft_survey,
    exam_payload,
    file_packet,
    interpret_payload,
    list_total_count,
    make_physicist_headers,
    make_qa_headers,
    make_technologist_headers,
    minimal_state_policy_payload,
    open_cycle,
    passing_survey_decision_payload,
    personnel_payload,
    read_cycle,
    read_exam,
    read_facility,
    read_personnel,
    read_survey,
    read_unit,
    retract_payload,
    review_decision_payload,
    setup_two_interpreted_exams,
    survey_payload,
    validate_error,
    validate_success,
)


def test_unauthenticated_and_unknown_role_requests_are_rejected_before_any_business_rule(
    api, core, reviewer_headers
):
    """401 is decided from the headers alone, ahead of the body schema check.

    PRD: "**Authentication (priority 1)** — both headers present and non-empty,
    `X-User-Role` one of the seven declared roles: `ERR_UNAUTHENTICATED`, 401.
    Applies to every endpoint."

    Design: Corner/rbac/unauthenticated_and_unknown_role_requests_are_rejected_before_any_business_rule
    """
    responses = [
        api.get_unit(core["unit_id"], NO_HEADERS),
        api.get_unit(core["unit_id"], UNKNOWN_ROLE_HEADERS),
        api.create_facility({}, NO_HEADERS),
    ]
    for response in responses:
        validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].strip() != ""
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["meta"]["api_request_timestamp"].strip() != ""

    assert list_total_count(api.list_policy_facilities(core["policy_id"], reviewer_headers)) == 1


def test_each_role_performs_its_own_exclusive_operations(
    api, funded_core, coordinator_headers, reviewer_headers, inspector_headers, qa_headers
):
    """All seven roles clear their own exclusive operation inside one workflow.

    PRD: "**Role authorization (priority 2)** — the acting role appears in the
    endpoint's declared role list: `ERR_FORBIDDEN_ROLE`, 403. Applies to every
    endpoint."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    core = funded_core
    exams = setup_two_interpreted_exams(core)
    survey = create_draft_survey(core)
    submission = file_packet(
        core, [exams[0]["id"], exams[1]["id"]], reviewer_note="Initial accreditation packet"
    )

    decided = validate_success(
        api.submit_physicist_survey(
            survey["id"],
            {"phantom_score": 7.0, "mean_glandular_dose_mgy": 2.00, "outcome_note": "Within limits"},
            core["phys_headers"],
        )
    )
    assert decided["status"] == "PASSED"
    assert read_unit(core["unit_id"])["survey_compliance"] == "CURRENT"

    reviewed = validate_success(
        api.review_clinical_image_review(
            submission["id"],
            review_decision_payload("PASS", reviewer_note="Image quality acceptable"),
            reviewer_headers,
        )
    )
    assert reviewed["status"] == "PASSED"
    assert read_unit(core["unit_id"])["accreditation_status"] == "ACCREDITED"

    inspection = validate_success(
        api.create_inspection(
            core["facility_id"],
            {"inspection_date": "2026-07-29T00:00:00Z", "inspector_findings_level": "NONE"},
            inspector_headers,
        ),
        expected_status=201,
    )
    assert inspection["status"] == "RECORDED"

    outcome = validate_success(
        api.record_exam_outcome(
            exams[0]["id"], {"biopsy_performed": True, "pathology_result": "BENIGN"}, qa_headers
        )
    )
    assert outcome["pathology_result"] == "BENIGN"
    assert outcome["biopsy_performed"] is True
    assert_instant_equals(
        outcome["outcome_recorded_at"], "2026-08-01T00:00:00Z", "outcome_recorded_at"
    )

    assert read_facility(core["facility_id"])["compliance_posture"] == "COMPLIANT"


def test_no_role_can_reach_another_roles_exclusive_operation(
    api, core, coordinator_headers, reviewer_headers, inspector_headers, qa_headers
):
    """Eight peer-boundary crossings all return 403 and write nothing.

    PRD: "**Role authorization (priority 2)** — the acting role appears in the
    endpoint's declared role list: `ERR_FORBIDDEN_ROLE`, 403. Applies to every
    endpoint."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    cycle = open_cycle(core)
    exam = validate_success(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-1201",
                performed_at="2026-07-20T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    record = validate_success(
        api.create_repeat_record(
            exam["id"],
            {"reason_code": "POSITIONING", "repeat_image_count": 1},
            core["tech_headers"],
        ),
        expected_status=201,
    )
    inspection = validate_success(
        api.create_inspection(
            core["facility_id"],
            {"inspection_date": "2026-07-29T00:00:00Z", "inspector_findings_level": "NONE"},
            inspector_headers,
        ),
        expected_status=201,
    )

    crossings = [
        api.create_facility(
            {
                "name": "Rogue Center",
                "state_policy_id": core["policy_id"],
                "accreditation_body": "ACR",
            },
            qa_headers,
        ),
        api.create_physicist_survey(core["unit_id"], survey_payload(), coordinator_headers),
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-9001",
                performed_at="2026-07-22T00:00:00Z",
            ),
            core["rad_headers"],
        ),
        api.interpret_exam(exam["id"], interpret_payload(1, "B"), core["tech_headers"]),
        api.retract_repeat_record(
            record["id"],
            retract_payload(retraction_reason="Self-service retraction"),
            core["tech_headers"],
        ),
        api.close_inspection(
            inspection["id"],
            coordinator_headers,
            {"closure_note": "Closing our own inspection"},
        ),
        api.close_audit_cycle(cycle["id"], {"variant": "PPV1_SCREENING"}, reviewer_headers),
        api.create_credit(
            core["rad_id"],
            {
                "credit_type": "CATEGORY_1_CE",
                "awarded_on": "2026-07-01T00:00:00Z",
                "ce_hours": 5.00,
                "source_note": "Physicist-awarded credit",
            },
            core["phys_headers"],
        ),
    ]
    for response in crossings:
        validate_error(response, "ERR_FORBIDDEN_ROLE", expected_status=403)

    assert list_total_count(api.list_policy_facilities(core["policy_id"], reviewer_headers)) == 1
    assert (
        list_total_count(api.list_unit_physicist_surveys(core["unit_id"], coordinator_headers))
        == 0
    )
    assert list_total_count(api.list_exams(coordinator_headers)) == 1
    assert read_exam(exam["id"])["report_status"] == "AWAITING_INTERPRETATION"
    assert validate_success(api.get_repeat_record(record["id"], qa_headers))["retracted"] is False

    after_inspection = validate_success(api.get_inspection(inspection["id"], inspector_headers))
    assert after_inspection["status"] == "RECORDED"
    assert after_inspection["closed_at"] is None

    after_cycle = read_cycle(cycle["id"], qa_headers)
    assert after_cycle["status"] == "OPEN"
    assert after_cycle["locked_at"] is None

    assert list_total_count(api.list_personnel_credits(core["rad_id"], coordinator_headers)) == 0
    assert read_personnel(core["rad_id"])["ce_hours_36mo"] == pytest.approx(0, abs=0.01)


def test_shared_operations_accept_every_listed_role_and_reject_the_rest(
    api, core, coordinator_headers, inspector_headers, qa_headers
):
    """Shared endpoints admit each listed role and still refuse an unlisted one.

    PRD: "**Role authorization (priority 2)** — the acting role appears in the
    endpoint's declared role list: `ERR_FORBIDDEN_ROLE`, 403. Applies to every
    endpoint."

    Design: Corner/rbac/shared_operations_accept_every_listed_role_and_reject_the_rest
    """
    exam = validate_success(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-SC-1",
                performed_at="2026-07-20T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.interpret_exam(exam["id"], interpret_payload(1, "C"), core["rad_headers"])
    )

    by_coordinator = validate_success(
        api.run_compliance_run(core["facility_id"], coordinator_headers)
    )
    assert_instant_equals(by_coordinator["ran_at"], "2026-08-01T00:00:00Z", "ran_at")
    by_qa = validate_success(api.run_compliance_run(core["facility_id"], qa_headers))
    assert_instant_equals(by_qa["ran_at"], "2026-08-01T00:00:00Z", "ran_at")

    before_rejected = read_facility(core["facility_id"])["last_compliance_run_at"]
    validate_error(
        api.run_compliance_run(core["facility_id"], inspector_headers),
        "ERR_FORBIDDEN_ROLE",
        expected_status=403,
    )
    assert_instant_equals(
        read_facility(core["facility_id"])["last_compliance_run_at"],
        before_rejected,
        "last_compliance_run_at",
    )

    by_physicist = validate_success(
        api.create_equipment_failure(
            core["unit_id"],
            {
                "failure_code": "DISPLAY",
                "severity": "MINOR",
                "detected_at": "2026-07-28T00:00:00Z",
            },
            core["phys_headers"],
        ),
        expected_status=201,
    )
    by_technologist = validate_success(
        api.create_equipment_failure(
            core["unit_id"],
            {
                "failure_code": "SOFTWARE",
                "severity": "MINOR",
                "detected_at": "2026-07-29T00:00:00Z",
            },
            core["tech_headers"],
        ),
        expected_status=201,
    )
    for failure in (by_physicist, by_technologist):
        assert failure["status"] == "OPEN"
        assert failure["requires_post_repair_survey"] is False
    assert read_unit(core["unit_id"])["operational_state"] == "IN_SERVICE"

    coordinator_repeat = validate_success(
        api.create_repeat_record(
            exam["id"], {"reason_code": "MOTION", "repeat_image_count": 1}, coordinator_headers
        ),
        expected_status=201,
    )
    assert coordinator_repeat["reason_code"] == "MOTION"
    assert read_unit(core["unit_id"])["repeat_images_acquired"] == 1

    coordinator_order = validate_success(
        api.create_supplemental_order(
            exam["id"],
            {"modality": "MRI", "recommendation_note": "Coordinator-entered recommendation"},
            coordinator_headers,
        ),
        expected_status=201,
    )
    assert coordinator_order["status"] == "RECOMMENDED"

    inspector_policy = validate_success(
        api.create_state_policy(minimal_state_policy_payload("NV"), inspector_headers),
        expected_status=201,
    )
    assert inspector_policy["state_code"] == "NV"

    assert (
        list_total_count(
            api.list_unit_equipment_failures(
                core["unit_id"], core["tech_headers"], params={"status": "OPEN"}
            )
        )
        == 2
    )


def test_segregation_of_duties_separates_the_reader_from_the_auditor_and_the_author_from_the_decider(
    api, core, coordinator_headers, qa_headers
):
    """Identity, not role, decides all three; the correct identity then succeeds.

    PRD: "**Segregation of duties, outcome and audit (priority 4)** — the officer
    recording a pathology outcome is not the exam's `interpreting_physician_id`, and
    the officer closing an audit cycle is not the cycle's `radiologist_id`:
    `ERR_SEGREGATION_OF_DUTIES`, 403. Applies to `POST /exams/{id}/outcome`,
    `POST /audit-cycles/{id}/close`."

    Design: Corner/rbac/segregation_of_duties_separates_the_reader_from_the_auditor_and_the_author_from_the_decider
    """
    second_physicist = add_personnel(
        core["facility_id"],
        personnel_payload(
            "MEDICAL_PHYSICIST",
            full_name="Priya Physicist",
            initial_qualification_on="2024-05-01T00:00:00Z",
            initial_training_hours=30,
            initial_read_volume=4,
        ),
    )
    cycle = open_cycle(core)
    exam = validate_success(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-1201",
                performed_at="2026-07-20T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.interpret_exam(exam["id"], interpret_payload(1, "B"), core["rad_headers"])
    )
    survey = create_draft_survey(core)

    outcome_body = {"biopsy_performed": True, "pathology_result": "BENIGN"}
    close_body = {"variant": "PPV1_SCREENING"}
    decision_body = passing_survey_decision_payload(
        phantom_score=7.0, mean_glandular_dose_mgy=2.00, outcome_note="Submitted by a colleague"
    )

    # Both separations are identity checks on an *officer*: only a
    # `QualityAssuranceOfficer` may reach these endpoints at all (priority 2), so
    # the violation is an officer whose opaque `X-User-ID` happens to equal the
    # stored personnel id — "The server may compare such an identifier against a
    # stored personnel identifier for the segregation-of-duties rules described
    # below — for example against an exam's `interpreting_physician_id` or an
    # audit cycle's `radiologist_id`".
    validate_error(
        api.record_exam_outcome(exam["id"], outcome_body, make_qa_headers(core["rad_id"])),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=403,
    )
    validate_error(
        api.close_audit_cycle(cycle["id"], close_body, make_qa_headers(core["rad_id"])),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=403,
    )
    validate_error(
        api.submit_physicist_survey(
            survey["id"], decision_body, make_physicist_headers(second_physicist["id"])
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=403,
    )

    assert read_exam(exam["id"])["outcome_recorded_at"] is None
    assert read_cycle(cycle["id"], qa_headers)["status"] == "OPEN"
    untouched_survey = read_survey(survey["id"])
    assert untouched_survey["status"] == "DRAFT"
    assert untouched_survey["phantom_score"] is None

    recorded = validate_success(api.record_exam_outcome(exam["id"], outcome_body, qa_headers))
    assert recorded["pathology_result"] == "BENIGN"
    assert_instant_equals(
        recorded["outcome_recorded_at"], "2026-08-01T00:00:00Z", "outcome_recorded_at"
    )

    locked = validate_success(api.close_audit_cycle(cycle["id"], close_body, qa_headers))
    assert locked["status"] == "LOCKED"
    assert locked["variant_at_close"] == "PPV1_SCREENING"
    assert_instant_equals(locked["locked_at"], "2026-08-01T00:00:00Z", "locked_at")

    decided = validate_success(
        api.submit_physicist_survey(
            survey["id"],
            passing_survey_decision_payload(
                phantom_score=7.0,
                mean_glandular_dose_mgy=2.00,
                outcome_note="Submitted by the author",
            ),
            core["phys_headers"],
        )
    )
    assert decided["status"] == "PASSED"
    assert_instant_equals(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")
    assert read_unit(core["unit_id"])["survey_compliance"] == "CURRENT"


def test_ownership_is_checked_against_the_acting_personnel_row(api, core, coordinator_headers):
    """A foreign technologist and a colleague physician are both refused by identity.

    PRD: "**Actor facility membership (priority 3)** — for the three entity-backed
    roles, `X-User-ID` resolves to a `Personnel` row whose `facility_id` matches the
    facility owning the target resource and whose `role_type` matches the acting
    role: `ERR_ACTOR_NOT_AT_FACILITY`, 403."

    Design: Corner/rbac/ownership_is_checked_against_the_acting_personnel_row
    """
    add_second_radiologist(core)
    second_facility = create_facility(
        core["policy_id"], name="Bayside Imaging", accreditation_body="ACR"
    )
    foreign_tech = add_personnel(
        second_facility["id"],
        personnel_payload(
            "TECHNOLOGIST",
            full_name="Tara Tech",
            initial_qualification_on="2024-02-10T00:00:00Z",
            initial_training_hours=50,
            initial_read_volume=40,
        ),
    )
    assert foreign_tech["qualification_status"] == "QUALIFIED"
    assert "DBT_3D" in foreign_tech["modality_certifications"]

    exam = validate_success(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-1201",
                performed_at="2026-07-20T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.interpret_exam(exam["id"], interpret_payload(1, "B"), core["rad_headers"])
    )

    validate_error(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                foreign_tech["id"],
                patient_ref="PT-7001",
                performed_at="2026-07-24T00:00:00Z",
            ),
            make_technologist_headers(foreign_tech["id"]),
        ),
        "ERR_ACTOR_NOT_AT_FACILITY",
        expected_status=403,
    )
    assert list_total_count(api.list_exams(coordinator_headers)) == 1

    validate_error(
        api.amend_exam(
            exam["id"],
            {"birads_assessment": 2, "amendment_reason": "Colleague amendment"},
            core["rad2_headers"],
        ),
        "ERR_NOT_INTERPRETING_PHYSICIAN",
        expected_status=403,
    )
    before = read_exam(exam["id"])
    assert before["birads_assessment"] == 1
    assert before["amendment_count"] == 0

    amended = validate_success(
        api.amend_exam(
            exam["id"],
            {"birads_assessment": 2, "amendment_reason": "Reader-corrected assessment"},
            core["rad_headers"],
        )
    )
    assert amended["report_status"] == "AMENDED"
    assert amended["birads_assessment"] == 2
    assert amended["amendment_count"] == 1
    assert amended["interpreting_physician_id"] == core["rad_id"]
