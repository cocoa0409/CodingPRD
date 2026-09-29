"""Two stored variants of the same performance figure diverge on one data set."""

from test_helpers import (
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_abstractor,
    assert_ok,
    assert_program,
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


def _source(api, program_id, source_type="PATHOLOGY"):
    return get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id, source_type=source_type, expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )


def _entry(api, source_id, author_id, **overrides):
    return get_success_data(
        api.create_casefinding_entry(
            source_id,
            f.casefinding_entry_payload(**overrides),
            make_registry_abstractor_headers(author_id),
        )
    )


def _mint_case(api, entry_id):
    entry = get_success_data(
        api.reportability_decision(
            entry_id,
            f.reportability_decision_payload(
                "REPORTABLE", decision_reason_code="SEER_REPORTABLE_BEHAVIOR"
            ),
            REGISTRY_MANAGER,
        )
    )
    return entry["created_case_id"]


def _complete_case(api, case_id, author_id, reviewer_id, **abstraction_overrides):
    case = get_success_data(
        api.assign_case(case_id, f.assign_payload(author_id), REGISTRY_MANAGER)
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case_id,
                author_id,
                case["version"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                **abstraction_overrides,
            ),
            make_registry_abstractor_headers(author_id),
        )
    )
    get_success_data(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(author_id),
        )
    )
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer_id),
        )
    )
    return abstraction


def _follow_up_cohort(api):
    """Two COMPLETED analytic cases: one recent, one diagnosed in 2021."""
    program = _program(api, "COC-14550", "Lakeside Regional Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    reviewer = _abstractor(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])

    entry_r = _entry(
        api,
        source["id"],
        author["id"],
        patient_mrn="MRN-3001",
        accession_date="2026-08-05",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-03-02",
        first_contact_date="2026-03-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    case_r_id = _mint_case(api, entry_r["id"])
    _complete_case(
        api,
        case_r_id,
        author["id"],
        reviewer["id"],
        stage_group="STAGE_II",
        first_treatment_date="2026-03-20",
        treatment_modalities=["SURGERY", "RADIATION"],
        radiation_start_date="2026-04-15",
        last_contact_date="2026-07-01",
    )

    entry_o = _entry(
        api,
        source["id"],
        author["id"],
        patient_mrn="MRN-3002",
        accession_date="2026-08-06",
        primary_site_code="C34.9",
        histology_code="8140/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2021-02-10",
        first_contact_date="2021-02-20",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    case_o_id = _mint_case(api, entry_o["id"])
    _complete_case(
        api,
        case_o_id,
        author["id"],
        reviewer["id"],
        t_category="T1",
        stage_group="STAGE_I",
        first_treatment_date="2021-03-01",
        treatment_modalities=["SURGERY"],
        last_contact_date="2021-06-15",
    )

    get_success_data(
        api.create_follow_up_contact(
            case_r_id,
            f.follow_up_contact_payload(
                contact_date="2026-07-20",
                contact_method="CLINIC_VISIT",
                outcome="CONTACT_MADE",
                vital_status_at_contact="ALIVE",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    get_success_data(
        api.create_follow_up_contact(
            case_o_id,
            f.follow_up_contact_payload(
                contact_date="2025-06-01",
                contact_method="LETTER",
                outcome="CONTACT_MADE",
                vital_status_at_contact="ALIVE",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    return {
        "program": program,
        "case_r_id": case_r_id,
        "case_o_id": case_o_id,
    }


def test_compliance_summary_reports_diverging_coc_and_state_follow_up_rates(api):
    """Both variants read the same two completed analytic cases and disagree.

    PRD 3.5: "The Commission-facing variant, stored as `follow_up_rate_coc_pct`,
    restricts the denominator to cases diagnosed within 1826 days of the clock
    date and drops patients whose `vital_status` is `DEAD` entirely; its
    numerator is those denominator cases with a non-null `last_contact_date` no
    more than 456 days old."

    Design: Difficulty/dual_variant_calc/follow_up_rate_coc_five_year_vs_state_central_all_years_divergence
    """
    world = _follow_up_cohort(api)

    summary = assert_ok(
        api.get_compliance_summary(world["program"]["id"], REGISTRY_MANAGER)
    )

    assert summary["follow_up_rate_coc_pct"] == 100.0
    assert summary["follow_up_rate_state_pct"] == 50.0
    assert summary["lost_to_follow_up_pct"] == 0.0
    assert summary["follow_up_rate_coc_pct"] != summary["follow_up_rate_state_pct"]


def test_case_follow_up_standing_bands_underpin_the_two_rate_variants(api):
    """The 2021 case is DELINQUENT while the recent one is CURRENT.

    PRD 3.5: "an age of 365 days or fewer is `CURRENT`, an age from 366 through
    456 days is `DELINQUENT`, and an age of 457 days or more is `LOST`."

    Design: Difficulty/dual_variant_calc/follow_up_rate_coc_five_year_vs_state_central_all_years_divergence
    """
    world = _follow_up_cohort(api)

    case_o = assert_ok(api.get_case(world["case_o_id"], REGISTRY_MANAGER))
    case_r = assert_ok(api.get_case(world["case_r_id"], REGISTRY_MANAGER))
    program = assert_program(
        assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    )

    assert case_o["last_contact_date"] == "2025-06-01"
    assert case_o["follow_up_status"] == "DELINQUENT"
    assert case_o["follow_up_due_date"] == "2026-06-01"
    assert case_r["follow_up_status"] == "CURRENT"
    assert program["open_backlog_count"] == 0
    assert program["registry_posture"] == "OPEN"


def _quality_score_cohort(api):
    """One aged critical audit outside the rolling window, one fresh audit open."""
    program = _program(api, "COC-14551", "Harbor Point Cancer Center")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    reviewer = _abstractor(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])

    entry_1 = _entry(
        api,
        source["id"],
        author["id"],
        patient_mrn="MRN-3101",
        accession_date="2026-08-05",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-03-02",
        first_contact_date="2026-03-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    case_1_id = _mint_case(api, entry_1["id"])
    abstraction_1 = _complete_case(
        api,
        case_1_id,
        author["id"],
        reviewer["id"],
        stage_group="STAGE_II",
        first_treatment_date="2026-03-20",
        treatment_modalities=["SURGERY"],
        last_contact_date="2026-07-01",
    )

    entry_2 = _entry(
        api,
        source["id"],
        author["id"],
        patient_mrn="MRN-3102",
        accession_date="2026-08-06",
        primary_site_code="C18.9",
        histology_code="8140/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-03-15",
        first_contact_date="2026-03-20",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    case_2_id = _mint_case(api, entry_2["id"])
    abstraction_2 = _complete_case(
        api,
        case_2_id,
        author["id"],
        reviewer["id"],
        t_category="T1",
        stage_group="STAGE_I",
        first_treatment_date="2026-04-01",
        treatment_modalities=["SURGERY"],
        last_contact_date="2026-07-05",
    )

    audit_1 = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction_1["id"],
                reviewer["id"],
                audit_type="ROUTINE_10PCT",
                window_start="2026-07-01",
                window_end="2026-07-31",
            ),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    get_success_data(
        api.score_qa_audit(
            audit_1["id"],
            f.audit_score_payload(
                audited_field_count=50, critical_discrepancy_count=1
            ),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    get_success_data(
        api.set_clock(f.clock_payload("2026-11-09T00:00:00Z"), PLATFORM_ADMIN)
    )
    audit_2 = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction_2["id"],
                reviewer["id"],
                audit_type="TARGETED",
                window_start="2026-11-01",
                window_end="2026-11-09",
            ),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    return {
        "author": author,
        "reviewer": reviewer,
        "case_1_id": case_1_id,
        "audit_1": audit_1,
        "audit_2": audit_2,
    }


def test_rolling_and_cumulative_quality_scores_diverge_after_a_second_audit(api):
    """The 90-day score ignores the aged critical audit the all-time score keeps.

    PRD 3.4: "`quality_score_rolling_90d` is the weighted variant: over only
    those audits whose `scored_at` falls on or after the clock instant less 90
    days, it divides the sum of `weighted_error_score` by the sum of
    `audited_field_count`, multiplies by 100, subtracts the result from 100,
    rounds half up to one decimal place, and clamps into 0.0 through 100.0; when
    no audited fields fall in the window the score is 100.0."

    Design: Difficulty/dual_variant_calc/abstractor_quality_rolling_weighted_vs_cumulative_unweighted_divergence
    """
    world = _quality_score_cohort(api)

    scored = assert_ok(
        api.score_qa_audit(
            world["audit_2"]["id"],
            f.audit_score_payload(
                audited_field_count=50, minor_discrepancy_count=3
            ),
            make_qa_reviewer_headers(world["reviewer"]["id"]),
        )
    )

    assert scored["weighted_error_score"] == 3
    assert scored["verdict"] == "MINOR_FAIL"
    assert scored["audit_state"] == "CLOSED_FAIL"

    author = assert_abstractor(
        assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    )
    assert author["quality_score_rolling_90d"] == 94.0
    assert author["quality_score_cumulative"] == 96.0
    assert author["quality_score_rolling_90d"] != author["quality_score_cumulative"]


def test_second_failing_audit_accumulates_points_and_streak_without_suspension(api):
    """Two closed fails put eight points on the ledger and leave the registrar active.

    PRD 3.4: "On `MINOR_FAIL` or `CRITICAL_FAIL` the audit moves `OPEN →
    CLOSED_FAIL` and the fail branch does strictly more:
    `lifetime_discrepancy_points` still rises by the same weighted amount, both
    quality scores are still recomputed, but `audit_fail_streak` is incremented
    by one instead of cleared."

    Design: Difficulty/dual_variant_calc/abstractor_quality_rolling_weighted_vs_cumulative_unweighted_divergence
    """
    world = _quality_score_cohort(api)

    assert_ok(
        api.score_qa_audit(
            world["audit_2"]["id"],
            f.audit_score_payload(
                audited_field_count=50, minor_discrepancy_count=3
            ),
            make_qa_reviewer_headers(world["reviewer"]["id"]),
        )
    )

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["lifetime_discrepancy_points"] == 8
    assert author["audit_fail_streak"] == 2
    assert author["employment_status"] == "ACTIVE"

    audit_1 = assert_ok(api.get_qa_audit(world["audit_1"]["id"], REGISTRY_MANAGER))
    assert audit_1["audit_state"] == "CLOSED_FAIL"
    assert audit_1["weighted_error_score"] == 5

    case_1 = assert_ok(api.get_case(world["case_1_id"], REGISTRY_MANAGER))
    assert case_1["case_state"] == "REWORK_PENDING"
