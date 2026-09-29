"""Formulas whose inputs recombine, where a fixed rule gets a different answer."""

from test_helpers import (
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    assert_abstraction,
    assert_created,
    assert_ok,
    assert_quality_measure,
    assert_submission,
    factories as f,
    get_success_data,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
)


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


def _abstractor(api, program_id, name):
    return get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program_id,
                name=name,
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )


def _assigned_case(api, source_id, author_id, **entry_overrides):
    entry = get_success_data(
        api.create_casefinding_entry(
            source_id,
            f.casefinding_entry_payload(**entry_overrides),
            make_registry_abstractor_headers(author_id),
        )
    )
    decided = get_success_data(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )
    case = get_success_data(
        api.assign_case(
            decided["created_case_id"], f.assign_payload(author_id), REGISTRY_MANAGER
        )
    )
    return case


# --------------------------------------------------------------------------
# abstraction_required_field_set_recombines_on_three_independent_inputs
# --------------------------------------------------------------------------
def _recombination_world(api):
    program = _program(api, "COC-14552", "Cedar Valley Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="DISEASE_INDEX", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )
    case = _assigned_case(
        api,
        source["id"],
        author["id"],
        patient_mrn="MRN-3201",
        accession_date="2026-08-04",
        primary_site_code="C61.9",
        histology_code="8140/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-03-02",
        first_contact_date="2026-03-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=False,
    )
    payload = f.abstraction_payload(
        case["id"],
        author["id"],
        case["version"],
        stage_source="PATHOLOGIC",
        t_category="T1",
        n_category="N0",
        m_category="M0",
        stage_group="STAGE_I",
        first_treatment_date=f.OMIT,
        treatment_modalities=["NO_TREATMENT"],
        diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
        outcome_status="ALIVE_NO_EVIDENCE",
        last_contact_date="2026-07-01",
    )
    return {"program": program, "author": author, "case": case, "payload": payload}


def test_three_independent_inputs_recombine_the_required_field_set(api):
    """NO_TREATMENT drops first_treatment_date while PATHOLOGIC adds t/n/m.

    PRD 3.3: "Then two subtractions apply: a case whose `analytic_flag` is false
    drops `outcome_status` and `last_contact_date` from the set, and a
    `treatment_modalities` array containing `NO_TREATMENT` drops
    `first_treatment_date`."

    Design: Difficulty/combinatorial_formula/abstraction_required_field_set_recombines_on_three_independent_inputs
    """
    world = _recombination_world(api)

    abstraction = assert_abstraction(
        assert_created(
            api.create_abstraction(
                world["payload"],
                make_registry_abstractor_headers(world["author"]["id"]),
            )
        )
    )

    assert abstraction["missing_required_fields"] == []
    assert abstraction["completeness_score"] == 100
    assert "first_treatment_date" not in abstraction["missing_required_fields"]
    assert "radiation_start_date" not in abstraction["missing_required_fields"]


def test_recombined_complete_abstract_passes_the_submission_quality_gate(api):
    """A 100-point abstract with an empty missing list reaches QA.

    PRD 3.3: "Submission also demands quality: the `completeness_score` must be
    at least 85 **and** `missing_required_fields` must be empty, otherwise the
    submission is refused with `ERR_ABSTRACTION_INCOMPLETE`."

    Design: Difficulty/combinatorial_formula/abstraction_required_field_set_recombines_on_three_independent_inputs
    """
    world = _recombination_world(api)
    abstraction = get_success_data(
        api.create_abstraction(
            world["payload"], make_registry_abstractor_headers(world["author"]["id"])
        )
    )

    submitted = assert_ok(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(world["author"]["id"]),
        )
    )

    assert submitted["abstraction_state"] == "SUBMITTED_FOR_QA"
    case = assert_ok(api.get_case(world["case"]["id"], REGISTRY_MANAGER))
    assert case["case_state"] == "QA_PENDING"
    assert case["class_of_case_code"] == "CLASS_00"
    assert case["analytic_flag"] is True


# --------------------------------------------------------------------------
# quality_measure_stratified_mean_of_rounded_rates_vs_pooled_ratio
# --------------------------------------------------------------------------
STRATA = [
    f.stratum("STAGE_I", 7, 5),
    f.stratum("STAGE_II", 3, 3),
    f.stratum("STAGE_III", 9, 6),
    f.stratum("STAGE_IV", 0, 0),
]


def _measure(api):
    program = _program(api, "COC-14553", "Northshore Cancer Institute")
    return get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"],
                measure_code="BCSRT",
                measurement_year=2025,
                threshold_pct=75.0,
            ),
            REGISTRY_MANAGER,
        )
    )


def test_stratified_mean_of_rounded_rates_diverges_from_the_pooled_ratio(api):
    """The zero-eligible stratum drops out and the two aggregations disagree.

    PRD 3.8: "`performance_rate_pct` is then the unweighted mean of those
    already-rounded stratum rates, itself rounded half up to one decimal place —
    so every stratum contributes equally no matter how many eligible cases it
    holds."

    Design: Difficulty/combinatorial_formula/quality_measure_stratified_mean_of_rounded_rates_vs_pooled_ratio
    """
    measure = _measure(api)

    evaluated = assert_quality_measure(
        assert_ok(
            api.evaluate_quality_measure(
                measure["id"], f.evaluate_measure_payload(STRATA), REGISTRY_MANAGER
            )
        )
    )

    assert evaluated["included_strata_count"] == 3
    assert evaluated["performance_rate_pct"] == 79.4
    assert evaluated["pooled_rate_pct"] == 73.7
    assert evaluated["performance_rate_pct"] != evaluated["pooled_rate_pct"]


def test_only_the_stratified_rate_is_tested_against_the_threshold(api):
    """79.4 clears the 75.0 threshold even though the pooled rate does not.

    PRD 3.8: "The verdict has three bands, tested against `threshold_pct` with
    inclusive comparisons: a basis rate at or above `threshold_pct` plus 10.0 is
    `EXCEEDS`, a basis rate at or above `threshold_pct` is `MEETS`, and anything
    below is `UNDER_THRESHOLD`."

    Design: Difficulty/combinatorial_formula/quality_measure_stratified_mean_of_rounded_rates_vs_pooled_ratio
    """
    measure = _measure(api)

    evaluated = assert_ok(
        api.evaluate_quality_measure(
            measure["id"], f.evaluate_measure_payload(STRATA), REGISTRY_MANAGER
        )
    )

    assert evaluated["performance_state"] == "MEETS"
    assert evaluated["measure_state"] == "MEASURED"

    reread = assert_ok(api.get_quality_measure(measure["id"], REGISTRY_MANAGER))
    assert reread["performance_state"] == "MEETS"
    assert reread["measure_state"] == "MEASURED"


# --------------------------------------------------------------------------
# submission_assessment_relief_tier_keyed_on_pre_relief_subtotal
# --------------------------------------------------------------------------
def _late_batch_world(api):
    """Two late records plus a late batch make a pre-relief subtotal of 20000."""
    program = _program(api, "COC-14554", "Riverbend Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    reviewer = _abstractor(api, program["id"], "Priya Raman")
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )

    def _complete(entry_overrides, abstraction_overrides):
        case = _assigned_case(api, source["id"], author["id"], **entry_overrides)
        abstraction = get_success_data(
            api.create_abstraction(
                f.abstraction_payload(
                    case["id"],
                    author["id"],
                    case["version"],
                    stage_source="PATHOLOGIC",
                    diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                    treatment_modalities=["SURGERY"],
                    outcome_status="ALIVE_NO_EVIDENCE",
                    **abstraction_overrides,
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
        return case["id"]

    case_l1_id = _complete(
        {
            "patient_mrn": "MRN-3301",
            "accession_date": "2026-08-03",
            "primary_site_code": "C50.9",
            "histology_code": "8500/3",
            "behavior_code": "MALIGNANT_3",
            "diagnosis_date": "2025-01-10",
            "first_contact_date": "2025-01-15",
            "diagnosed_at_facility": True,
            "first_treatment_at_facility": True,
        },
        {
            "t_category": "T2",
            "n_category": "N0",
            "m_category": "M0",
            "stage_group": "STAGE_II",
            "first_treatment_date": "2025-02-01",
            "last_contact_date": "2026-06-01",
        },
    )
    case_l2_id = _complete(
        {
            "patient_mrn": "MRN-3302",
            "accession_date": "2026-08-03",
            "primary_site_code": "C34.9",
            "histology_code": "8140/3",
            "behavior_code": "MALIGNANT_3",
            "diagnosis_date": "2025-02-10",
            "first_contact_date": "2025-02-15",
            "diagnosed_at_facility": True,
            "first_treatment_at_facility": True,
        },
        {
            "t_category": "T1",
            "n_category": "N0",
            "m_category": "M0",
            "stage_group": "STAGE_I",
            "first_treatment_date": "2025-03-01",
            "last_contact_date": "2026-06-05",
        },
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
    get_success_data(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(case_l1_id, batch["version"]),
            REGISTRY_MANAGER,
        )
    )
    reread = get_success_data(api.get_submission(batch["id"], REGISTRY_MANAGER))
    get_success_data(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(case_l2_id, reread["version"]),
            REGISTRY_MANAGER,
        )
    )
    get_success_data(
        api.transmit_submission(
            batch["id"],
            f.transmit_payload(transmit_note="state central registry batch 2025H1"),
            REGISTRY_MANAGER,
        )
    )
    return {"batch": batch, "case_l1_id": case_l1_id, "case_l2_id": case_l2_id}


def test_relief_tier_is_selected_from_the_pre_relief_subtotal(api):
    """5000 in records plus a 15000 batch fee hits the inclusive 20000 boundary.

    PRD 3.6: "Fourth, `relief_pct` is selected from that pre-relief subtotal by
    descending threshold with the first match winning: a subtotal of 100000
    cents or more earns 0.30, otherwise 50000 cents or more earns 0.20,
    otherwise 20000 cents or more earns 0.10, otherwise 0.00."

    Design: Difficulty/combinatorial_formula/submission_assessment_relief_tier_keyed_on_pre_relief_subtotal
    """
    world = _late_batch_world(api)

    batch = assert_submission(
        assert_ok(
            api.post_edit_results(
                world["batch"]["id"],
                f.edit_results_payload(
                    [
                        f.item_result(world["case_l1_id"], "ACCEPTED", []),
                        f.item_result(world["case_l2_id"], "ACCEPTED", []),
                    ]
                ),
                STATE_REGISTRY_LIAISON,
            )
        )
    )

    assert batch["late_case_count"] == 2
    assert batch["relief_pct"] == 0.1
    assert batch["assessment_due_cents"] == 18000
    assert batch["assessment_paid_cents"] == 0


def test_all_accepted_edit_results_close_the_batch_and_its_cases(api):
    """Both records come back clean, so the batch and each case dimension settle.

    PRD 3.6: "The batch itself then forks: if every entry was accepted it
    reaches the terminal `TRANSMITTED → ACCEPTED`; if even one entry failed it
    goes `TRANSMITTED → EDITS_RETURNED`."

    Design: Difficulty/combinatorial_formula/submission_assessment_relief_tier_keyed_on_pre_relief_subtotal
    """
    world = _late_batch_world(api)

    batch = assert_ok(
        api.post_edit_results(
            world["batch"]["id"],
            f.edit_results_payload(
                [
                    f.item_result(world["case_l1_id"], "ACCEPTED", []),
                    f.item_result(world["case_l2_id"], "ACCEPTED", []),
                ]
            ),
            STATE_REGISTRY_LIAISON,
        )
    )

    assert batch["submission_state"] == "ACCEPTED"
    assert batch["accepted_item_count"] == 2
    assert batch["failed_item_count"] == 0

    case_l1 = assert_ok(api.get_case(world["case_l1_id"], REGISTRY_MANAGER))
    case_l2 = assert_ok(api.get_case(world["case_l2_id"], REGISTRY_MANAGER))
    assert case_l1["timeliness_status"] == "LATE"
    assert case_l1["submission_state"] == "ACCEPTED"
    assert case_l2["timeliness_status"] == "LATE"
