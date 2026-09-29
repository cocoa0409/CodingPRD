"""Two rules broken by one call: the response must name the winning one."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    assert_ok,
    assert_submission,
    factories as f,
    get_success_data,
    make_coc_surveyor_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
)

SURVEYOR = make_coc_surveyor_headers("surv-nakamura")


def _program(api, coc_program_id, name):
    return get_success_data(
        api.create_program(
            f.program_payload(
                name=name,
                coc_program_id=coc_program_id,
                annual_analytic_caseload=620,
                reference_year=2018,
                timeliness_standard_days=180,
            ),
            PLATFORM_ADMIN,
        )
    )


def _reportable_case(api, source_id, headers, **entry_overrides):
    entry = get_success_data(
        api.create_casefinding_entry(
            source_id, f.casefinding_entry_payload(**entry_overrides), headers
        )
    )
    decided = get_success_data(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )
    return decided["created_case_id"]


# --------------------------------------------------------------------------
# frozen_registry_masks_abstractor_capacity_cap_on_assign
# --------------------------------------------------------------------------
def _trainee_at_cap_in_frozen_registry(api):
    program = _program(api, "COC-14559", "Stonegate Cancer Program")
    trainee = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Tomas Iverson",
                credential="TRAINEE",
                productivity_target_cases_per_day=0.2,
                certification_expires_on="2027-06-30",
            ),
            REGISTRY_MANAGER,
        )
    )
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="DISEASE_INDEX", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )
    case_g1_id = _reportable_case(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-3701",
        accession_date="2026-08-05",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-06-02",
        first_contact_date="2026-06-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    get_success_data(
        api.assign_case(case_g1_id, f.assign_payload(trainee["id"]), REGISTRY_MANAGER)
    )
    case_g2_id = _reportable_case(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-3702",
        accession_date="2026-08-05",
        primary_site_code="C18.9",
        histology_code="8140/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-06-03",
        first_contact_date="2026-06-10",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    get_success_data(
        api.assign_case(case_g2_id, f.assign_payload(trainee["id"]), REGISTRY_MANAGER)
    )
    case_g3_id = _reportable_case(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-3703",
        accession_date="2026-08-05",
        primary_site_code="C34.9",
        histology_code="8140/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-06-04",
        first_contact_date="2026-06-11",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"],
                severity="CRITICAL",
                standard_code="STD-2.1",
                cited_on="2026-08-01",
                evidence_reference="survey-finding-2.1",
            ),
            SURVEYOR,
        )
    )
    return {
        "program": program,
        "trainee": trainee,
        "case_g3_id": case_g3_id,
    }


def test_frozen_registry_is_reported_instead_of_the_capacity_cap(api):
    """The assignment breaks the freeze rule and the cap rule; the freeze wins.

    PRD 2.11: "A frozen registry masks every capacity, referential, and fiscal
    problem on the same request: an assignment into a frozen registry reports
    `ERR_REGISTRY_FROZEN` even when the chosen registrar is also over capacity,
    whose own code `ERR_ABSTRACTOR_CAPACITY_EXCEEDED` sits in the later
    constraint band."

    Design: Difficulty/priority_pair_validation_conflict/frozen_registry_masks_abstractor_capacity_cap_on_assign
    """
    world = _trainee_at_cap_in_frozen_registry(api)

    response = api.assign_case(
        world["case_g3_id"],
        f.assign_payload(world["trainee"]["id"]),
        REGISTRY_MANAGER,
    )

    error = validate_error(response, ApiErrorId.ERR_REGISTRY_FROZEN.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ABSTRACTOR_CAPACITY_EXCEEDED.value


def test_masked_assignment_leaves_the_case_and_the_workload_untouched(api):
    """The refused assign changes neither the case nor the trainee's worklist.

    PRD 3.2: "Because the frozen check is evaluated well before the capacity
    check, an over-capacity registrar in a frozen registry produces the freeze
    error, never the capacity error."

    Design: Difficulty/priority_pair_validation_conflict/frozen_registry_masks_abstractor_capacity_cap_on_assign
    """
    world = _trainee_at_cap_in_frozen_registry(api)

    api.assign_case(
        world["case_g3_id"], f.assign_payload(world["trainee"]["id"]), REGISTRY_MANAGER
    )

    case_g3 = assert_ok(api.get_case(world["case_g3_id"], REGISTRY_MANAGER))
    assert case_g3["case_state"] == "IDENTIFIED"
    assert case_g3["assigned_abstractor_id"] is None

    trainee = assert_ok(api.get_abstractor(world["trainee"]["id"], REGISTRY_MANAGER))
    assert trainee["assigned_open_case_count"] == 2

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["registry_posture"] == "FROZEN"
    assert program["open_critical_deficiency_count"] == 1
    assert program["open_backlog_count"] == 3


# --------------------------------------------------------------------------
# submission_state_check_masks_unpaid_assessment_on_second_transmit
# --------------------------------------------------------------------------
def _batch_in_edit_resolution_with_unpaid_assessment(api):
    program = _program(api, "COC-14560", "Bluffton Cancer Program")
    author = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Dana Whitfield",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    reviewer = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Priya Raman",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )
    case_m_id = _reportable_case(
        api,
        source["id"],
        make_registry_abstractor_headers(author["id"]),
        patient_mrn="MRN-3801",
        accession_date="2026-08-05",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2025-01-10",
        first_contact_date="2025-01-15",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    case = get_success_data(
        api.assign_case(case_m_id, f.assign_payload(author["id"]), REGISTRY_MANAGER)
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case_m_id,
                author["id"],
                case["version"],
                stage_source="PATHOLOGIC",
                t_category="T2",
                n_category="N0",
                m_category="M0",
                stage_group="STAGE_II",
                first_treatment_date="2025-02-01",
                treatment_modalities=["SURGERY"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                outcome_status="ALIVE_NO_EVIDENCE",
                last_contact_date="2026-06-01",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    get_success_data(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2025-01-01",
                period_end="2025-06-30",
                deadline_date="2025-09-30",
            ),
            REGISTRY_MANAGER,
        )
    )
    item = get_success_data(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(case_m_id, batch["version"]),
            REGISTRY_MANAGER,
        )
    )
    get_success_data(
        api.transmit_submission(batch["id"], f.transmit_payload(), REGISTRY_MANAGER)
    )
    get_success_data(
        api.post_edit_results(
            batch["id"],
            f.edit_results_payload([f.item_result(case_m_id, "EDIT_FAILED", ["EDIT-1210"])]),
            STATE_REGISTRY_LIAISON,
        )
    )
    return {"batch": batch, "item": item, "case_m_id": case_m_id}


def test_transmit_reports_the_state_error_and_never_the_payment_error(api):
    """The batch is both out of DRAFT and carrying an unpaid assessment.

    PRD 2.11: "Within a submission transmit, the state check comes first and the
    fiscal check comes last, so a batch that is both out of `DRAFT` and carrying
    an unpaid assessment reports `ERR_SUBMISSION_NOT_DRAFT` and never the payment
    error."

    Design: Difficulty/priority_pair_validation_conflict/submission_state_check_masks_unpaid_assessment_on_second_transmit
    """
    world = _batch_in_edit_resolution_with_unpaid_assessment(api)

    response = api.transmit_submission(
        world["batch"]["id"], f.transmit_payload(), REGISTRY_MANAGER
    )

    error = validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_DRAFT.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ASSESSMENT_UNPAID.value
    assert response.status_code != 402


def test_refused_transmit_leaves_the_edit_resolution_figures_in_place(api):
    """The failed record, the assessment and the resubmission round all stand.

    PRD 3.6: "Fifth and last, `assessment_due_cents` is the pre-relief subtotal
    multiplied by one minus `relief_pct`, rounded half up to whole cents — a
    single rounding step at the end."

    Design: Difficulty/priority_pair_validation_conflict/submission_state_check_masks_unpaid_assessment_on_second_transmit
    """
    world = _batch_in_edit_resolution_with_unpaid_assessment(api)

    api.transmit_submission(world["batch"]["id"], f.transmit_payload(), REGISTRY_MANAGER)

    batch = assert_submission(
        assert_ok(api.get_submission(world["batch"]["id"], REGISTRY_MANAGER))
    )
    assert batch["submission_state"] == "EDITS_RETURNED"
    assert batch["late_case_count"] == 1
    assert batch["relief_pct"] == 0.0
    assert batch["assessment_due_cents"] == 17500
    assert batch["assessment_paid_cents"] == 0
    assert batch["failed_item_count"] == 1
    assert batch["resubmission_round"] == 0

    item = assert_ok(api.get_submission_item(world["item"]["id"], REGISTRY_MANAGER))
    assert item["edit_status"] == "EDIT_FAILED"

    case_m = assert_ok(api.get_case(world["case_m_id"], REGISTRY_MANAGER))
    assert case_m["submission_state"] == "EDIT_REJECTED"
