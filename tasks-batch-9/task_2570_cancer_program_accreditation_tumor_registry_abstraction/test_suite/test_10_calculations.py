"""Derived numbers: penalties, clamps, rounding order, and empty cohorts."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    assert_casefinding_source,
    assert_created,
    assert_deficiency,
    assert_ok,
    assert_quality_measure,
    assert_reportable_case_parity,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_coc_surveyor_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
    validate_paginated,
)

SURVEYOR = make_coc_surveyor_headers("user-surveyor-1")
COORDINATOR = make_accreditation_coordinator_headers("user-coord-1")


def _program(api, **overrides):
    base = dict(
        name="Northside Cancer Center",
        coc_program_id="COC-1456N",
        annual_analytic_caseload=300,
        reference_year=2018,
        timeliness_standard_days=180,
    )
    base.update(overrides)
    return get_success_data(api.create_program(f.program_payload(**base), PLATFORM_ADMIN))


def _registrar(api, program_id, name):
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


def _source(api, program_id, source_type="PATHOLOGY", expected_monthly_volume=40):
    return get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id,
                source_type=source_type,
                expected_monthly_volume=expected_monthly_volume,
            ),
            REGISTRY_MANAGER,
        )
    )


def _entry(api, source_id, mrn, accession_date="2026-08-03", **overrides):
    base = dict(
        patient_mrn=mrn,
        accession_date=accession_date,
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-07-01",
        first_contact_date="2026-07-05",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    base.update(overrides)
    payload = f.casefinding_entry_payload(**base)
    return get_success_data(api.create_casefinding_entry(source_id, payload, REGISTRY_MANAGER))


def _mint(api, entry_id):
    return get_success_data(
        api.reportability_decision(
            entry_id, f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )


def _measure(api, program_id, measure_code, threshold_pct):
    return get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program_id,
                measure_code=measure_code,
                measurement_year=2026,
                threshold_pct=threshold_pct,
            ),
            REGISTRY_MANAGER,
        )
    )


def test_one_missing_required_field_costs_twelve_points_and_still_blocks_qa(api):
    """88 clears the 85 floor, but the non-empty missing list refuses submission.

    PRD 3.3: "The score starts at 100, loses 12 points for each missing required
    field, loses a further 8 points when `stage_group` is `UNKNOWN`, and loses a
    further 6 points when a `CLINICAL` `stage_source` is recorded on a case whose
    `class_of_case_code` is `CLASS_10` — a clinical stage on a case the program
    itself diagnosed and treated."

    PRD 3.3: "Submission also demands quality: the `completeness_score` must be at
    least 85 **and** `missing_required_fields` must be empty, otherwise the
    submission is refused with `ERR_ABSTRACTION_INCOMPLETE`."

    Design: Corner/calculations/abstraction_completeness_score_penalizes_one_missing_required_field
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    source = _source(api, program["id"])
    case = get_success_data(
        api.assign_case(
            _mint(api, _entry(api, source["id"], "MRN-0001")["id"])["created_case_id"],
            f.assign_payload(author["id"]),
            REGISTRY_MANAGER,
        )
    )

    abstraction = assert_created(
        api.create_abstraction(
            f.abstraction_payload(
                case["id"],
                author["id"],
                case["version"],
                stage_source="PATHOLOGIC",
                t_category="T2",
                n_category="N0",
                m_category="M0",
                stage_group="STAGE_II",
                first_treatment_date="2026-07-10",
                treatment_modalities=["SURGERY"],
                diagnostic_confirmation_code=f.OMIT,
                outcome_status="ALIVE_NO_EVIDENCE",
                last_contact_date="2026-07-20",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )

    assert abstraction["completeness_score"] == 88
    assert abstraction["missing_required_fields"] == ["diagnostic_confirmation_code"]
    assert abstraction["abstraction_state"] == "DRAFT"
    assert abstraction["rework_round"] == 0

    validate_error(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(author["id"]),
        ),
        ApiErrorId.ERR_ABSTRACTION_INCOMPLETE.value,
        422,
    )

    reread = assert_ok(api.get_case(case["id"], REGISTRY_MANAGER))
    assert reread["case_state"] == "IN_ABSTRACTION"


def test_a_program_whose_only_case_is_still_open_reports_full_follow_up(api):
    """A backlog case is not yet in anybody's follow-up denominator.

    PRD 3.5: "Both start from the same base: analytic tumor cases of the program
    that have reached `COMPLETED`, because a case still sitting in the abstraction
    backlog is not yet in anybody's follow-up denominator — which is why a
    brand-new program truthfully reports 100.0."

    Design: Corner/calculations/follow_up_rate_with_empty_completed_cohort_reports_one_hundred
    """
    program = _program(api)
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"], "MRN-0001")["id"])["created_case_id"]

    summary = assert_ok(api.get_compliance_summary(program["id"], REGISTRY_MANAGER))

    assert summary["follow_up_rate_coc_pct"] == 100.0
    assert summary["follow_up_rate_state_pct"] == 100.0
    assert summary["lost_to_follow_up_pct"] == 0.0
    assert summary["open_backlog_count"] == 1
    assert summary["overdue_backlog_count"] == 0
    assert summary["registry_posture"] == "OPEN"

    case = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert case["follow_up_status"] == "CURRENT"
    assert case["follow_up_due_date"] == "2027-07-05"


def test_casefinding_completeness_is_clamped_before_the_multiplication(api):
    """Two expected and three received still reads 100.0, never 150.0.

    PRD 2.6: "A source tracks `entries_this_month`, the number of its entries
    whose `accession_date` falls inside the logical clock's current calendar month,
    and reports `casefinding_completeness_pct`: when `expected_monthly_volume` is
    zero the completeness is reported as 100.0, and otherwise it is the ratio of
    `entries_this_month` to `expected_monthly_volume`, clamped so it can never
    exceed one, multiplied by 100 and rounded to one decimal place — so the figure
    never exceeds 100.0 no matter how many entries arrive."

    Design: Corner/calculations/casefinding_completeness_pct_clamped_at_one_hundred
    """
    program = _program(api)
    source = _source(api, program["id"], "DISEASE_INDEX", 2)

    _entry(api, source["id"], "MRN-1001", accession_date="2026-08-03")
    after_one = assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))
    assert after_one["entries_this_month"] == 1
    assert after_one["casefinding_completeness_pct"] == 50.0

    _entry(api, source["id"], "MRN-1002", accession_date="2026-08-04")
    after_two = assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))
    assert after_two["entries_this_month"] == 2
    assert after_two["casefinding_completeness_pct"] == 100.0

    _entry(api, source["id"], "MRN-1003", accession_date="2026-08-05")
    after_three = assert_casefinding_source(
        assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))
    )
    assert after_three["entries_this_month"] == 3
    assert after_three["casefinding_completeness_pct"] == 100.0
    assert after_three["last_reconciled_through"] is None


def test_two_points_pass_and_three_points_are_a_minor_fail(api):
    """The pass ceiling is inclusive, and the two audits pool into one ledger.

    PRD 3.4: "The `weighted_error_score` is five points per critical discrepancy
    plus three points per major discrepancy plus one point per minor discrepancy.
    The `verdict` then follows three ordered rules: any critical discrepancy at all
    forces `CRITICAL_FAIL` regardless of the total; otherwise a total of two points
    or fewer is `PASS`; otherwise it is `MINOR_FAIL`. A score of exactly 2 passes
    and a score of 3 is a `MINOR_FAIL`."

    Design: Corner/calculations/audit_verdict_pass_at_two_points_and_minor_fail_at_three_points
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    case = get_success_data(
        api.assign_case(
            _mint(api, _entry(api, source_id := _source(api, program["id"])["id"], "MRN-0001")["id"])[
                "created_case_id"
            ],
            f.assign_payload(author["id"]),
            REGISTRY_MANAGER,
        )
    )
    assert source_id
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case["id"],
                author["id"],
                case["version"],
                first_treatment_date="2026-07-10",
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                last_contact_date="2026-07-20",
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
    audit_one = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction["id"],
                reviewer["id"],
                audit_type="ROUTINE_10PCT",
                window_start="2026-08-01",
                window_end="2026-08-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    audit_two = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction["id"],
                reviewer["id"],
                audit_type="TARGETED",
                window_start="2026-08-01",
                window_end="2026-08-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    reviewer_headers = make_qa_reviewer_headers(reviewer["id"])

    passed = assert_ok(
        api.score_qa_audit(
            audit_one["id"],
            f.audit_score_payload(audited_field_count=40, minor_discrepancy_count=2),
            reviewer_headers,
        )
    )
    failed = assert_ok(
        api.score_qa_audit(
            audit_two["id"],
            f.audit_score_payload(audited_field_count=40, minor_discrepancy_count=3),
            reviewer_headers,
        )
    )

    assert passed["weighted_error_score"] == 2
    assert passed["verdict"] == "PASS"
    assert passed["audit_state"] == "CLOSED_PASS"
    assert failed["weighted_error_score"] == 3
    assert failed["verdict"] == "MINOR_FAIL"
    assert failed["audit_state"] == "CLOSED_FAIL"

    registrar = assert_ok(api.get_abstractor(author["id"], REGISTRY_MANAGER))
    assert registrar["lifetime_discrepancy_points"] == 5
    assert registrar["audit_fail_streak"] == 1
    assert registrar["quality_score_rolling_90d"] == 93.8
    assert registrar["quality_score_cumulative"] == 93.8

    assert assert_ok(api.get_abstraction(abstraction["id"], REGISTRY_MANAGER))[
        "abstraction_state"
    ] == "APPROVED"
    assert assert_ok(api.get_case(case["id"], REGISTRY_MANAGER))["case_state"] == "COMPLETED"


def test_the_fourth_open_case_restricts_the_registry_and_the_third_does_not(api):
    """The restricted floor is inclusive and is only reached after the freeze clauses.

    PRD 2.7: "The posture is then decided by four clauses evaluated in exactly this
    order, the first matching clause winning: if the program's
    `accreditation_state` is `PROBATION` or `WITHDRAWN`, the posture is `FROZEN`;
    otherwise, if `open_critical_deficiency_count` is at least 1, the posture is
    `FROZEN`; otherwise, if `overdue_backlog_count` is at least 2, the posture is
    `FROZEN`; otherwise, if `open_backlog_count` is at least 4, the posture is
    `RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Corner/calculations/registry_posture_restricts_at_fourth_open_case_and_not_at_third
    """
    program = _program(api)
    source = _source(api, program["id"])
    entries = [
        _entry(api, source["id"], "MRN-0001"),
        _entry(api, source["id"], "MRN-0002"),
        _entry(api, source["id"], "MRN-0003"),
        _entry(api, source["id"], "MRN-0004"),
    ]

    case_ids = [_mint(api, entries[i]["id"])["created_case_id"] for i in range(3)]
    at_three = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert at_three["open_backlog_count"] == 3
    assert at_three["overdue_backlog_count"] == 0
    assert at_three["registry_posture"] == "OPEN"

    case_ids.append(_mint(api, entries[3]["id"])["created_case_id"])
    at_four = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert at_four["open_backlog_count"] == 4
    assert at_four["registry_posture"] == "RESTRICTED"
    assert at_four["identified_case_count"] == 4

    for case_id in case_ids:
        case = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
        assert case["timeliness_status"] == "ON_TIME"
        assert case["days_to_due"] == 153

    assert_reportable_case_parity(api, REGISTRY_MANAGER, program["id"])


def test_severity_windows_differ_and_a_rejection_extends_the_original_date(api):
    """30, 45 and 60 days from citation; the rejection adds 15 to the first date.

    PRD 3.9: "The response window is derived from severity: a `CRITICAL`
    deficiency must be answered within 30 days of `cited_on`, a `MAJOR` within 45
    days, and a `MINOR` within 60 days, and `response_due_date` is `cited_on` plus
    that many days."

    PRD 3.9: "Below the cap the deficiency moves `RESPONSE_SUBMITTED →
    RESPONSE_REJECTED`, `escalation_count` is incremented by one, and
    `response_due_date` is extended by a further 15 days, giving the program
    another attempt inside the newly extended window."

    Design: Corner/calculations/deficiency_due_dates_use_severity_windows_and_extend_on_rejection
    """
    program = _program(api)

    critical = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="CRITICAL", standard_code="STD-4.4", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )
    major = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MAJOR", standard_code="STD-6.1", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )
    minor = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MINOR", standard_code="STD-7.2", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )

    assert critical["response_due_date"] == "2026-08-31"
    assert critical["deficiency_state"] == "CITED"
    assert minor["response_due_date"] == "2026-09-30"
    assert major["response_due_date"] == "2026-09-15"

    get_success_data(
        api.respond_to_deficiency(
            major["id"],
            f.deficiency_response_payload(
                response_narrative="Corrective action plan filed with monthly monitoring."
            ),
            COORDINATOR,
        )
    )
    rejected = assert_deficiency(
        assert_ok(
            api.review_deficiency_response(
                major["id"],
                f.deficiency_review_payload(
                    "REJECTED", reviewer_notes="Plan lacks measurable monitoring."
                ),
                SURVEYOR,
            )
        )
    )

    assert rejected["deficiency_state"] == "RESPONSE_REJECTED"
    assert rejected["escalation_count"] == 1
    assert rejected["response_due_date"] == "2026-09-30"

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["open_critical_deficiency_count"] == 1
    assert reread["registry_posture"] == "FROZEN"
    assert reread["accreditation_state"] == "ACCREDITED"


def test_an_adjacent_reporting_period_is_fine_but_one_shared_day_is_not(api):
    """The intervals are closed, so a single overlapping calendar day conflicts.

    PRD 3.6: "Reporting periods are exclusive within a program: a new batch
    conflicts with any existing batch of the same program whose `period_start` is
    on or before the new `period_end` and whose `period_end` is on or after the new
    `period_start` — that is, periods that share even a single calendar day
    conflict, and the refusal is `ERR_SUBMISSION_PERIOD_OVERLAP` (HTTP 409).
    Adjacency is fine: a period beginning the day after an existing period ends is
    accepted."

    Design: Corner/calculations/submission_periods_adjacent_accepted_and_single_shared_day_rejected
    """
    program = _program(api)
    get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-01-01",
                period_end="2026-06-30",
                deadline_date="2026-09-30",
            ),
            REGISTRY_MANAGER,
        )
    )

    adjacent = assert_created(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-07-01",
                period_end="2026-12-31",
                deadline_date="2027-03-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    assert adjacent["submission_state"] == "DRAFT"

    validate_error(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-06-30",
                period_end="2026-09-30",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_SUBMISSION_PERIOD_OVERLAP.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_submissions(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_the_follow_up_variant_only_swaps_the_reported_lost_rate(api):
    """A 426-day-old contact is current for the Commission and stale for the state.

    PRD 2.9: "It accepts a `follow_up_variant` parameter that selects only which
    variant `lost_to_follow_up_pct` is reported from: `coc_five_year`, the default
    when the parameter is absent, reports the Commission complement described
    above, while `state_central_all_years` reports 100.0 minus
    `follow_up_rate_state_pct`."

    Design: Corner/calculations/compliance_summary_follow_up_variant_selects_reported_lost_rate
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    entry = _entry(
        api,
        source["id"],
        "MRN-0001",
        diagnosis_date="2025-01-15",
        first_contact_date="2025-01-20",
    )
    case = get_success_data(
        api.assign_case(
            _mint(api, entry["id"])["created_case_id"],
            f.assign_payload(author["id"]),
            REGISTRY_MANAGER,
        )
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case["id"],
                author["id"],
                case["version"],
                first_treatment_date="2025-01-30",
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                last_contact_date="2025-06-01",
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
    get_success_data(
        api.create_follow_up_contact(
            case["id"],
            f.follow_up_contact_payload(
                contact_date="2025-06-01",
                contact_method="CLINIC_VISIT",
                outcome="CONTACT_MADE",
                vital_status_at_contact="ALIVE",
            ),
            REGISTRY_MANAGER,
        )
    )

    default_view = assert_ok(api.get_compliance_summary(program["id"], COORDINATOR))
    state_view = assert_ok(
        api.get_compliance_summary(
            program["id"],
            STATE_REGISTRY_LIAISON,
            {"follow_up_variant": "state_central_all_years"},
        )
    )

    for view in (default_view, state_view):
        assert view["follow_up_rate_coc_pct"] == 100.0
        assert view["follow_up_rate_state_pct"] == 0.0
    assert default_view["lost_to_follow_up_pct"] == 0.0
    assert state_view["lost_to_follow_up_pct"] == 100.0

    reread = assert_ok(api.get_case(case["id"], REGISTRY_MANAGER))
    assert reread["follow_up_status"] == "DELINQUENT"
    assert reread["follow_up_due_date"] == "2026-06-01"

    program_after = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert program_after["registry_posture"] == "OPEN"
    assert program_after["overdue_backlog_count"] == 0


def test_each_stratum_is_rounded_before_the_mean_is_taken(api):
    """66.7 and 71.4 average to 69.05, which rounds up to 69.1 — not 69.0 or 70.0.

    PRD 3.8: "Each surviving stratum's rate is `compliant_case_count` divided by
    `eligible_case_count`, times 100, rounded half up to one decimal place.
    `performance_rate_pct` is then the unweighted mean of those already-rounded
    stratum rates, itself rounded half up to one decimal place — so every stratum
    contributes equally no matter how many eligible cases it holds."

    Design: Corner/calculations/measure_rate_rounds_each_stratum_before_averaging
    """
    program = _program(api)
    measure = _measure(api, program["id"], "BCSRT", 80.0)

    evaluated = assert_quality_measure(
        assert_ok(
            api.evaluate_quality_measure(
                measure["id"],
                f.evaluate_measure_payload(
                    [f.stratum("STAGE_II", 3, 2), f.stratum("STAGE_III", 7, 5)]
                ),
                COORDINATOR,
            )
        )
    )

    assert evaluated["performance_rate_pct"] == 69.1
    assert evaluated["pooled_rate_pct"] == 70.0
    assert evaluated["included_strata_count"] == 2
    assert evaluated["performance_state"] == "UNDER_THRESHOLD"
    assert evaluated["measure_state"] == "PROJECT_REQUIRED"


def test_a_zero_eligible_stratum_is_stored_but_kept_out_of_the_arithmetic(api):
    """Dropping the empty stratum first gives 75.0, not a 37.5 average with zero.

    PRD 3.8: "Strata whose `eligible_case_count` is zero are dropped before any
    arithmetic happens, and `included_strata_count` is the number that survive; if
    none survive, the evaluation is refused with `ERR_MEASURE_STRATA_EMPTY` and no
    rate field is written."

    Design: Corner/calculations/measure_zero_eligible_stratum_excluded_from_mean_and_count
    """
    program = _program(api)
    measure = _measure(api, program["id"], "CSTC", 70.0)

    evaluated = assert_ok(
        api.evaluate_quality_measure(
            measure["id"],
            f.evaluate_measure_payload(
                [f.stratum("STAGE_0", 0, 0), f.stratum("STAGE_I", 4, 3)]
            ),
            REGISTRY_MANAGER,
        )
    )

    assert evaluated["included_strata_count"] == 1
    assert evaluated["performance_rate_pct"] == 75.0
    assert evaluated["pooled_rate_pct"] == 75.0
    assert evaluated["performance_state"] == "MEETS"
    assert evaluated["measure_state"] == "MEASURED"
    assert len(evaluated["strata"]) == 2
