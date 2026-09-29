"""Role exclusivity, genuinely shared routes and the same-user prohibitions."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    PROGRAM_ADMIN_USER_ID,
    SURVEYOR,
    SURVEYOR_ALPHA_USER_ID,
    SURVEYOR_BETA,
    add_finding,
    api_client,
    assessment_payload,
    assign_director,
    correction_decision_payload,
    correction_submission_payload,
    create_certificate,
    create_operator,
    create_site,
    create_storage_unit,
    create_trained_operator,
    inspection_payload,
    issue_survey,
    make_lab_director_headers,
    make_operator_headers,
    open_survey,
    patient_result_payload,
    pt_investigation_decision_payload,
    read_assessment,
    read_certificate,
    read_deficiency,
    read_inspection,
    read_operator,
    read_site,
    read_storage_unit,
    record_temperature_reading,
    set_clock,
    setup_covered_site,
    site_payload,
    training_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
ABSENT_DEVICE = "6f1d0c2b-0000-4000-8000-0000000000a1"
ABSENT_LOT = "6f1d0c2b-0000-4000-8000-0000000000a2"
ABSENT_PT_EVENT = "6f1d0c2b-0000-4000-8000-0000000000a3"


def test_each_roles_exclusive_route_is_shut_to_every_other_role():
    """Five wrong-role writes, all 403 — one of them against an id that does not exist.

    PRD 2.7: "2. **Rank 2 — authorisation.** The acting role appears in the endpoint's
    authorised-role list in §4, and for the entity-backed roles the `X-User-ID` resolves
    to an operator row. Otherwise `ERR_UNAUTHORIZED` (403)."

    PRD 4: "| POST | `/poct/sites` | Create a point-of-care testing site. |
    ProgramAdmin |" and "| POST | `/poct/inspections` | Open a survey against a site;
    created directly in progress. | Surveyor |" and "| POST | `/poct/test-results` |
    Capture a patient result from an instrument. Manual entry requires a reason and an
    unblocked site and instrument. | Operator |" and "| POST |
    `/poct/pt-events/{id}/investigation-decision` | Accept the investigation (terminal)
    or reject it back into the investigation loop. | LabDirector |" and "| POST |
    `/poct/certificates/{id}/suspend` | Suspend a certificate; drives the certificate
    withdrawal cascade across sites, operators, submitted assessments and instruments. |
    ProgramAdmin |"

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    set_clock(SEPTEMBER)
    certificate = create_certificate(certificate_number="45D2243049")
    site = create_site(name="GI Clinic POCT", department_code="DEPT-4500")
    operator = create_trained_operator(
        site["id"], full_name="Nils Bergqvist",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-01-05",
        training={
            "training_module_code": "POCT-GLUCO-101", "completed_on": "2026-08-20"
        },
    )

    surveyor_making_a_site = api_client.create_site(
        site_payload(name="Surveyor's Own Site", department_code="DEPT-4599"), SURVEYOR
    )
    coordinator_opening_a_survey = api_client.create_inspection(
        inspection_payload(
            site["id"], inspection_type="BIENNIAL_SURVEY",
            scheduled_date="2026-09-01",
        ),
        COORDINATOR,
    )
    coordinator_capturing_a_result = api_client.create_test_result(
        patient_result_payload(
            ABSENT_DEVICE, operator["id"], ABSENT_LOT,
            patient_mrn="MRN-9001", measured_value=100.0,
        ),
        COORDINATOR,
    )
    coordinator_deciding_an_investigation = api_client.decide_pt_investigation(
        ABSENT_PT_EVENT,
        pt_investigation_decision_payload("ACCEPT", note="looks fine to me"),
        COORDINATOR,
    )
    director_suspending_a_certificate = api_client.suspend_certificate(
        certificate["id"], {"reason": "director-initiated suspension"},
        make_lab_director_headers(operator["id"]),
    )

    for response in (
        surveyor_making_a_site,
        coordinator_opening_a_survey,
        coordinator_capturing_a_result,
        coordinator_deciding_an_investigation,
        director_suspending_a_certificate,
    ):
        validate_error(response, "ERR_UNAUTHORIZED", 403)

    _surveys, survey_meta = validate_paginated(
        api_client.list_inspections(SURVEYOR, params={"site_id": site["id"]})
    )
    _results, result_meta = validate_paginated(
        api_client.list_test_results(ADMIN, params={"device_id": ABSENT_DEVICE})
    )
    _sites, site_meta = validate_paginated(api_client.list_sites(ADMIN))
    assert survey_meta["total_count"] == 0
    assert result_meta["total_count"] == 0
    assert site_meta["total_count"] == 1
    assert read_certificate(certificate["id"])["status"] == "ACTIVE"


def test_the_shared_routes_behave_identically_from_every_role_that_holds_them():
    """Two roles train, three record probe readings, and the rows differ only in who.

    PRD 3.3: "A `ProgramAdmin` or `QualityCoordinator` records completion of the site's
    point-of-care training module by supplying the `training_module_code` and the
    `completed_on` date of the session." and "On success the operator's
    `training_module_code` is stored, `training_completed_at` is stamped with the
    current logical instant, competency advances `PENDING → PROVISIONAL`, access
    advances `LOCKED_OUT → ACTIVE`, `lockout_reason` is cleared to null, and the
    operator's `version` increments."

    PRD 4: "| POST | `/poct/storage-units/{id}/temperature-readings` | Record a probe
    reading; an out-of-range reading opens an excursion and drives the excursion
    cascade. Bounds are inclusive. | Operator, QualityCoordinator, ProgramAdmin |"

    PRD 3.5: "The unit's `last_reading_c` is the `reading_c` of the reading with the
    greatest `recorded_at`; where two readings share that instant, the later-created row
    wins."

    Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Ortho Clinic POCT", department_code="DEPT-4600")
    first = create_operator(
        site["id"], full_name="Ola Kirsch",
        role_title="NURSE", hire_date="2026-01-05",
    )
    second = create_operator(
        site["id"], full_name="Pia Halvorsen",
        role_title="NURSE", hire_date="2026-01-06",
    )
    unit = create_storage_unit(
        site["id"], name="Reagent Fridge 1", min_temp_c=2.0, max_temp_c=8.0
    )

    trained_by_admin = validate_success(
        api_client.record_training(
            first["id"],
            training_payload(
                training_module_code="POCT-GLUCO-101", completed_on="2026-08-20"
            ),
            ADMIN,
        ),
        200,
    )
    trained_by_coordinator = validate_success(
        api_client.record_training(
            second["id"],
            training_payload(
                training_module_code="POCT-GLUCO-101", completed_on="2026-08-21"
            ),
            COORDINATOR,
        ),
        200,
    )
    by_operator = record_temperature_reading(
        unit["id"], 4.0, make_operator_headers(first["id"]),
        recorded_at="2026-09-01T09:00:00Z", recorded_by_user_id=first["id"],
    )
    by_coordinator = record_temperature_reading(
        unit["id"], 4.5, COORDINATOR,
        recorded_at="2026-09-01T13:00:00Z", recorded_by_user_id="user-qc",
    )
    by_admin = record_temperature_reading(
        unit["id"], 5.0, ADMIN,
        recorded_at="2026-09-01T17:00:00Z", recorded_by_user_id="user-admin",
    )

    assert trained_by_admin["competency_status"] == "PROVISIONAL"
    assert trained_by_coordinator["competency_status"] == "PROVISIONAL"
    assert trained_by_admin["access_status"] == "ACTIVE"
    assert trained_by_coordinator["access_status"] == "ACTIVE"
    assert trained_by_admin["lockout_reason"] is None
    assert trained_by_coordinator["lockout_reason"] is None
    assert by_operator["disposition"] == "IN_RANGE"
    assert by_coordinator["disposition"] == "IN_RANGE"
    assert by_admin["disposition"] == "IN_RANGE"
    assert by_operator["recorded_by_user_id"] == first["id"]
    assert by_coordinator["recorded_by_user_id"] == "user-qc"
    assert by_admin["recorded_by_user_id"] == "user-admin"

    _readings, meta = validate_paginated(
        api_client.list_temperature_readings(unit["id"], SURVEYOR)
    )
    assert meta["total_count"] == 3
    unit_after = read_storage_unit(unit["id"], SURVEYOR)
    assert unit_after["excursion_state"] == "IN_RANGE"
    assert unit_after["last_reading_c"] == 5.0
    site_after = read_site(site["id"])
    assert site_after["total_operator_count"] == 2
    assert site_after["lapsed_or_locked_operator_count"] == 0


def test_the_surveyor_who_wrote_the_citation_cannot_accept_its_correction():
    """Same role on both sides, so only the user id explains the refusal.

    PRD 2.8: "On a deficiency correction decision, the acting `X-User-ID` must differ
    from the finding's `issued_by_user_id`: the surveyor who wrote a citation may not be
    the surveyor who accepts its correction."

    PRD 2.7: "35. **Rank 65 — segregation of duties**, on competency-assessment
    submission, competency decision, deficiency correction decision and patient-result
    posting. Otherwise `ERR_SEGREGATION_OF_DUTIES` (422). See §2.8 for the four
    clauses."

    Design: Corner/rbac/issuing_surveyor_cannot_accept_the_correction_they_issued
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243050"},
        site_overrides={
            "name": "Vascular Clinic POCT", "department_code": "DEPT-4700",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    survey = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-09-01",
    )
    finding = add_finding(
        survey["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="STANDARD_LEVEL",
        description="weekly control log incomplete",
        correction_due_date="2026-10-15",
    )
    issued = issue_survey(survey["id"], SURVEYOR, issued_on="2026-09-01")
    assert issued["issued_weight_total"] == 3.00
    assert issued["status"] == "DEFICIENCIES_ISSUED"
    open_finding = read_deficiency(finding["id"])
    assert open_finding["status"] == "OPEN"
    assert open_finding["weight"] == 3.00
    assert open_finding["issued_by_user_id"] == SURVEYOR_ALPHA_USER_ID

    submitted = validate_success(
        api_client.submit_correction(
            finding["id"],
            correction_submission_payload(
                correction_narrative="log reprinted, daily sign-off added",
                evidence_ref="POC-2026-09-14",
            ),
            COORDINATOR,
        ),
        200,
    )
    assert submitted["status"] == "CORRECTION_SUBMITTED"
    assert submitted["correction_round"] == 1

    self_accept = api_client.decide_correction(
        finding["id"],
        correction_decision_payload("ACCEPT", note="closing my own finding"),
        SURVEYOR,
    )
    validate_error(self_accept, "ERR_SEGREGATION_OF_DUTIES", 422)
    mid = read_site(site["id"], COORDINATOR)
    assert mid["open_deficiency_weight"] == 3.00
    assert mid["oversight_posture"] == "OPEN"

    second_accept = validate_success(
        api_client.decide_correction(
            finding["id"],
            correction_decision_payload(
                "ACCEPT", note="evidence reviewed by a second surveyor"
            ),
            SURVEYOR_BETA,
        ),
        200,
    )

    assert second_accept["status"] == "CLOSED"
    assert read_inspection(survey["id"])["status"] == "CLOSED"
    after = read_site(site["id"], COORDINATOR)
    assert after["open_deficiency_weight"] == 0.00
    assert after["oversight_posture"] == "OPEN"
    assert after["inspection_readiness_score"] == 100.00


def test_the_director_who_assessed_cannot_decide_and_neither_can_a_stand_in():
    """Two different limbs of the director clause fail; the programme office decides.

    PRD 2.8: "On competency-assessment submission, `assessor_operator_id` must differ
    from `operator_id`: nobody attests to their own competency."

    PRD 2.8: "On a competency decision taken with `X-User-Role` of `LabDirector`, the
    acting `X-User-ID` must equal the site's `lab_director_operator_id`, must differ
    from the assessment's `assessor_operator_id`, and must differ from its
    `operator_id`. A director who performed the assessment, or who is the subject of it,
    or who is not the director of record for that site, may not decide it. A
    `ProgramAdmin` acting on the same operation carries an opaque identifier and
    therefore satisfies all three conditions by construction."

    Design: Corner/rbac/lab_director_who_served_as_assessor_cannot_approve_that_assessment
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243051"},
        site_overrides={
            "name": "Womens Health POCT", "department_code": "DEPT-4800",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    director = create_trained_operator(
        site["id"], full_name="Dr. Quinn Abernathy",
        role_title="PHYSICIAN", hire_date="2026-01-05",
        training={
            "training_module_code": "POCT-DIRECTOR-101", "completed_on": "2026-08-18"
        },
    )
    subject = create_trained_operator(
        site["id"], full_name="Rex Sundaram",
        role_title="NURSE", hire_date="2026-01-06",
        training={
            "training_module_code": "POCT-GLUCO-101", "completed_on": "2026-08-19"
        },
    )
    stand_in = create_trained_operator(
        site["id"], full_name="Sena Okonkwo",
        role_title="MIDLEVEL_PRACTITIONER", hire_date="2026-01-07",
        training={
            "training_module_code": "POCT-GLUCO-101", "completed_on": "2026-08-20"
        },
    )
    appointed = assign_director(site["id"], director["id"])
    assert appointed["lab_director_operator_id"] == director["id"]
    subject_version = subject["version"]

    self_assessment = api_client.create_assessment(
        assessment_payload(
            subject["id"], subject["id"], subject_version,
            effective_date="2026-09-01", expires_at="2027-03-01",
        ),
        COORDINATOR,
    )
    validate_error(self_assessment, "ERR_SEGREGATION_OF_DUTIES", 422)

    assessment = validate_success(
        api_client.create_assessment(
            assessment_payload(
                subject["id"], director["id"], subject_version,
                effective_date="2026-09-01", expires_at="2027-03-01",
            ),
            COORDINATOR,
        ),
        201,
    )
    assert assessment["status"] == "SUBMITTED"
    assert assessment["assessor_operator_id"] == director["id"]

    assessor_deciding = api_client.decide_assessment(
        assessment["id"],
        {"decision": "APPROVE", "note": "I assessed and I approve"},
        make_lab_director_headers(director["id"]),
    )
    stand_in_deciding = api_client.decide_assessment(
        assessment["id"],
        {"decision": "APPROVE", "note": "approving on the director's behalf"},
        make_lab_director_headers(stand_in["id"]),
    )
    validate_error(assessor_deciding, "ERR_SEGREGATION_OF_DUTIES", 422)
    validate_error(stand_in_deciding, "ERR_SEGREGATION_OF_DUTIES", 422)
    assert read_assessment(assessment["id"])["status"] == "SUBMITTED"

    approved = validate_success(
        api_client.decide_assessment(
            assessment["id"],
            {
                "decision": "APPROVE",
                "note": "program office review of the assessment file",
            },
            ADMIN,
        ),
        200,
    )

    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == PROGRAM_ADMIN_USER_ID
    subject_after = read_operator(subject["id"], COORDINATOR)
    assert subject_after["competency_status"] == "COMPETENT"
    assert subject_after["competency_expires_at"] == "2027-03-01"
