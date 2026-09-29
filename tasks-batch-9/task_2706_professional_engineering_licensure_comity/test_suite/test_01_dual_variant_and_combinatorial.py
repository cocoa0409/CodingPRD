"""Dual-variant valuation and pinned combinatorial arithmetic.

Covers the two experience-credit variants of PRD §3.3, the two continuing
professional competency contexts of PRD §3.6, the civil-penalty assessment
order of operations in PRD §3.9, and the eight-step application fee assessment
of PRD §3.2.
"""

import pytest

from test_helpers import (
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_money_cents,
    assert_pdh_value,
    factories,
    fixtures,
    get_success_data,
    make_applicant_headers,
    validate_success,
)


def _competency_report_under_audit(api, draw=True):
    """A licensee with one accepted competency report, optionally drawn into audit.

    Thirty declared hours arrive as four line items — COURSE 14.0, SELF_STUDY
    8.0, SEMINAR 6.0 and an ethics-flagged TEACHING 2.0 — and only the COURSE
    item ever has its documentation accepted by the board.
    """
    engineer, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"pdh_requirement": 30}
    )
    report = fixtures.create_cpc_report(
        api,
        license_["id"],
        engineer["id"],
        license_["version"],
        period_start=license_["current_period_start"],
        period_end=license_["current_period_end"],
        self_certified_pdh=30,
        carryover_pdh_claimed=0,
    )
    course = fixtures.add_pdh_record(
        api,
        report["id"],
        engineer["id"],
        activity_type="COURSE",
        pdh_hours=14.0,
        completed_on="2026-02-10T00:00:00Z",
        ethics_flag=False,
    )
    self_study = fixtures.add_pdh_record(
        api,
        report["id"],
        engineer["id"],
        activity_type="SELF_STUDY",
        pdh_hours=8.0,
        completed_on="2026-03-15T00:00:00Z",
        ethics_flag=False,
    )
    seminar = fixtures.add_pdh_record(
        api,
        report["id"],
        engineer["id"],
        activity_type="SEMINAR",
        pdh_hours=6.0,
        completed_on="2026-04-20T00:00:00Z",
        ethics_flag=False,
    )
    teaching = fixtures.add_pdh_record(
        api,
        report["id"],
        engineer["id"],
        activity_type="TEACHING",
        pdh_hours=2.0,
        completed_on="2026-05-05T00:00:00Z",
        ethics_flag=True,
    )
    fixtures.review_pdh_documentation(api, course["id"], "ACCEPT")
    state = {
        "engineer": engineer,
        "license": license_,
        "report": report,
        "course": course,
        "self_study": self_study,
        "seminar": seminar,
        "teaching": teaching,
        "audit": None,
    }
    if not draw:
        return state
    state["report"] = fixtures.accept_cpc_report(api, report["id"])
    state["audit"] = fixtures.draw_audit(
        api,
        headers=BOARD_SECRETARY_HEADERS,
        sample_pct=0.10,
        as_of_period_end=license_["current_period_end"],
    )
    return state


def _flagged_plan_set_case(api, sheet_count):
    """A PLAN_STAMPING complaint under investigation over a sealed, flagged set."""
    engineer, license_ = fixtures.create_licensed_engineer(api)
    firm = fixtures.create_firm(api, license_["id"])
    plan = fixtures.create_plan_submission(api, firm["id"], sheet_count=sheet_count)
    fixtures.seal_plan(api, plan["id"], license_["id"], engineer["id"])
    fixtures.flag_plan(api, plan["id"], reason="Seal applied without responsible charge.")
    case = fixtures.create_case(
        api,
        allegation_type="PLAN_STAMPING",
        complainant_name="City of Ashford",
        respondent_license_id=license_["id"],
        subject_plan_submission_id=plan["id"],
    )
    case = fixtures.open_investigation(api, case["id"])
    return {"engineer": engineer, "license": license_, "firm": firm, "plan": plan, "case": case}


# ---------------------------------------------------------------------------
# Experience credit: the self-reported figure against the board-determined one
# ---------------------------------------------------------------------------


def test_progressive_block_reads_36_provisional_months_and_18_verified_months(api):
    """PRD §3.3: "The divergence is real and observable on identical data: a `PROGRESSIVE` post-degree block spanning January 2019 through December 2022 has 48 raw months and a multiplier of 0.75, contributing 36 months provisionally — inside the single-block cap — but only 18 months finally if the accepted verification on it came from a project manager rather than a direct supervisor."

    Design: Difficulty/dual_variant_calc/experience_credit_provisional_36_vs_verified_final_18
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="reference_accepted",
        experience_overrides={
            "employer_name": "Cascade Structures",
            "position_title": "Project Engineer",
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
            "responsibility_level": "PROGRESSIVE",
            "post_degree": True,
        },
        reference_overrides={"relationship": "PROJECT_MANAGER"},
        submission_overrides={
            "evaluation_score": 4,
            "months_confirmed": 48,
            "responsibility_confirmed": True,
        },
    )
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]
    applicant = make_applicant_headers(engineer_id)
    before = get_success_data(api.get_application(application_id, applicant))

    data = validate_success(
        api.determine_credit(application_id, BOARD_REVIEWER_HEADERS), 200
    )

    assert data["provisional_experience_months"] == 36
    assert data["verified_experience_months"] == 18
    assert data["provisional_experience_months"] - data["verified_experience_months"] == 18
    assert data["credit_determined_by_user_id"] == "REV-1"
    assert data["status"] == "UNDER_REVIEW"
    assert data["version"] == before["version"] + 1

    record = get_success_data(
        api.get_experience_record(track["experience_record"]["id"], applicant)
    )
    assert record["raw_months"] == 48
    assert round(record["credit_multiplier"], 2) == pytest.approx(0.75)
    assert record["credited_months"] == 18
    assert record["verification_status"] == "VERIFIED"


def test_direct_supervisor_verification_credits_the_full_36_months(api):
    """PRD §3.3: "The **board-determined** figure, written to `verified_experience_months`, includes only blocks whose `verification_status` is `VERIFIED`, and weights each block at 1.00 when the accepted verification on it came from a `DIRECT_SUPERVISOR` and at 0.50 when it came from a `PROJECT_MANAGER` or a `PEER`."

    Design: Difficulty/dual_variant_calc/experience_credit_provisional_36_vs_verified_final_18
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="reference_accepted",
        experience_overrides={
            "employer_name": "Cascade Structures",
            "position_title": "Project Engineer",
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
            "responsibility_level": "PROGRESSIVE",
            "post_degree": True,
        },
        reference_overrides={"relationship": "DIRECT_SUPERVISOR"},
        submission_overrides={
            "evaluation_score": 4,
            "months_confirmed": 48,
            "responsibility_confirmed": True,
        },
    )
    application_id = track["application"]["id"]
    applicant = make_applicant_headers(track["engineer"]["id"])

    data = validate_success(
        api.determine_credit(application_id, BOARD_REVIEWER_HEADERS), 200
    )

    assert data["provisional_experience_months"] == 36
    assert data["verified_experience_months"] == 36
    assert data["provisional_experience_months"] - data["verified_experience_months"] == 0

    record = get_success_data(
        api.get_experience_record(track["experience_record"]["id"], applicant)
    )
    assert record["raw_months"] == 48
    assert round(record["credit_multiplier"], 2) == pytest.approx(0.75)
    assert record["credited_months"] == 36


def test_single_block_cap_bites_before_the_project_manager_weighting(api):
    """PRD §3.3: "Cap that truncated figure at 48 months, which is the most any single block may contribute. Multiply the capped figure by the block's weighting for the variant in force and truncate downward again."

    Design: Difficulty/dual_variant_calc/experience_credit_provisional_36_vs_verified_final_18
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="reference_accepted",
        experience_overrides={
            "employer_name": "Cascade Structures",
            "position_title": "Principal Engineer",
            "period_start_month": "2016-01",
            "period_end_month": "2020-12",
            "responsibility_level": "RESPONSIBLE_CHARGE",
            "post_degree": True,
        },
        reference_overrides={"relationship": "PROJECT_MANAGER"},
        submission_overrides={
            "evaluation_score": 5,
            "months_confirmed": 60,
            "responsibility_confirmed": True,
        },
    )
    application_id = track["application"]["id"]
    applicant = make_applicant_headers(track["engineer"]["id"])

    data = validate_success(
        api.determine_credit(application_id, BOARD_REVIEWER_HEADERS), 200
    )

    assert data["provisional_experience_months"] == 48
    assert data["verified_experience_months"] == 24

    record = get_success_data(
        api.get_experience_record(track["experience_record"]["id"], applicant)
    )
    assert record["raw_months"] == 60
    assert round(record["credit_multiplier"], 2) == pytest.approx(1.0)
    assert record["credited_months"] == 24


# ---------------------------------------------------------------------------
# Competency hours: the self-certified context against the audit-verified one
# ---------------------------------------------------------------------------


def test_self_certified_context_admits_undocumented_hours_for_a_30_hour_total(api):
    """PRD §3.6: "The **self-certified** context governs while a report stands in `SUBMITTED` or `ACCEPTED`, takes the licensee's attestation at face value, includes every line item whose `documentation_status` is `NONE` or `ACCEPTED` — only `REJECTED` documentation is dropped — allows `SELF_STUDY` a ceiling of 8 hours, and writes its result to `self_certified_total_pdh`."

    Design: Difficulty/dual_variant_calc/cpc_pdh_self_certified_30_vs_audit_verified_14
    """
    state = _competency_report_under_audit(api, draw=False)

    data = validate_success(
        api.accept_cpc_report(state["report"]["id"], BOARD_REVIEWER_HEADERS), 200
    )

    assert data["status"] == "ACCEPTED"
    assert_pdh_value(data["self_certified_total_pdh"], 30.0)
    assert_pdh_value(data["shortfall_pdh"], 0.0)
    assert data["audit_id"] is None

    course = get_success_data(api.get_pdh_record(state["course"]["id"], BOARD_REVIEWER_HEADERS))
    assert course["documentation_status"] == "ACCEPTED"
    for key in ("self_study", "seminar", "teaching"):
        item = get_success_data(
            api.get_pdh_record(state[key]["id"], BOARD_REVIEWER_HEADERS)
        )
        assert item["documentation_status"] == "NONE"


def test_audit_draw_recomputes_the_same_hours_to_an_audit_verified_total_of_14(api):
    """PRD §3.6: "On identical line items the divergence is stark: a report whose 30 declared hours include 8 hours of self study and whose documentation was never submitted reads 30.0 self-certified and 14.0 audit-verified."

    Design: Difficulty/dual_variant_calc/cpc_pdh_self_certified_30_vs_audit_verified_14
    """
    state = _competency_report_under_audit(api, draw=False)
    report = fixtures.accept_cpc_report(api, state["report"]["id"])
    assert_pdh_value(report["self_certified_total_pdh"], 30.0)

    audit = validate_success(
        api.create_cpc_audit(
            factories.cpc_audit_payload(
                audit_cycle_label="CPC-2028-A",
                sample_pct=0.10,
                as_of_period_end=state["license"]["current_period_end"],
            ),
            BOARD_SECRETARY_HEADERS,
        ),
        201,
    )

    assert audit["pool_size"] == 1
    assert audit["sampled_count"] == 1
    assert audit["status"] == "SAMPLED"
    assert audit["created_by_user_id"] == "SEC-1"

    drawn = get_success_data(api.get_cpc_report(report["id"], BOARD_REVIEWER_HEADERS))
    assert drawn["status"] == "UNDER_AUDIT"
    assert drawn["audit_id"] == audit["id"]
    assert_pdh_value(drawn["audit_verified_total_pdh"], 14.0)
    assert_pdh_value(drawn["self_certified_total_pdh"], 30.0)


def test_audit_shortfall_adds_the_hour_gap_of_16_to_the_ethics_floor_of_2(api):
    """PRD §3.6: "The ethics deficiency is 2 hours minus the ethics hours just summed, or 0 if that difference would be negative. `shortfall_pdh` is the sum of those two deficiencies, rounded half up to one decimal place."

    Design: Difficulty/dual_variant_calc/cpc_pdh_self_certified_30_vs_audit_verified_14
    """
    state = _competency_report_under_audit(api)
    report_id = state["report"]["id"]

    data = validate_success(
        api.audit_decision(report_id, {"decision": "DEFICIENT"}, BOARD_REVIEWER_HEADERS), 200
    )

    assert data["status"] == "AUDIT_DEFICIENT"
    assert_pdh_value(data["audit_verified_total_pdh"], 14.0)
    assert_pdh_value(data["shortfall_pdh"], 18.0)
    assert_pdh_value(data["self_certified_total_pdh"], 30.0)
    assert data["audit_decided_by_user_id"] == "REV-1"
    assert data["audit_id"] == state["audit"]["id"]

    audit = get_success_data(
        api.get_cpc_audit(state["audit"]["id"], BOARD_REVIEWER_HEADERS)
    )
    assert audit["status"] == "CLOSED"
    license_ = get_success_data(
        api.get_license(state["license"]["id"], BOARD_REVIEWER_HEADERS)
    )
    assert license_["discipline_flag"] is True


# ---------------------------------------------------------------------------
# Civil penalty: the pinned rounding order of the five assessment steps
# ---------------------------------------------------------------------------


def test_stamping_component_rounds_per_sheet_before_multiplying_by_seven_sheets(api):
    """PRD §3.9: "The order sensitivity is real rather than theoretical: with a `penalty_factor` of 0.85 and a `sheet_count` of 7, rounding per sheet first gives 1,466 cents per sheet and 10,262 cents for the component, whereas multiplying everything before rounding would give 10,264 — a two-cent divergence, and the pinned order is the correct one."

    Design: Difficulty/combinatorial_formula/civil_penalty_round_per_sheet_then_multiply_391062
    """
    state = _flagged_plan_set_case(api, sheet_count=7)

    data = validate_success(
        api.record_finding(
            state["case"]["id"],
            factories.finding_payload(
                finding="PROBABLE_CAUSE",
                aggravating_factor_count=0,
                mitigating_factor_count=1,
                violation_count=2,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        200,
    )

    assert round(data["penalty_factor"], 2) == pytest.approx(0.85)
    assert_money_cents(data["assessed_penalty_cents"], 391062)
    # 340000 conduct + 10262 stamping + 40800 cost recovery.
    assert data["assessed_penalty_cents"] - (340000 + 40800) == 10262
    assert data["investigation_status"] == "PROBABLE_CAUSE"
    assert data["sanction_status"] == "NONE"
    assert data["aggravating_factor_count"] == 0
    assert data["mitigating_factor_count"] == 1
    assert data["violation_count"] == 2

    plan = get_success_data(
        api.get_plan_submission(state["plan"]["id"], BOARD_INVESTIGATOR_HEADERS)
    )
    assert plan["sheet_count"] == 7
    assert plan["status"] == "FLAGGED"


def test_penalty_omits_the_stamping_component_when_no_plan_set_is_named(api):
    """PRD §3.9: "Step three computes the per-sheet stamping component, and only when `subject_plan_submission_id` is set: multiply 1,725 cents by `penalty_factor`, **round that per-sheet amount half up to a whole cent first**, and only then multiply by the plan set's `sheet_count` as it stands at finding time. When no plan set is named the stamping component is 0."

    Design: Difficulty/combinatorial_formula/civil_penalty_round_per_sheet_then_multiply_391062
    """
    engineer, license_ = fixtures.create_licensed_engineer(api)
    case = fixtures.create_case(
        api, allegation_type="NEGLIGENCE", respondent_license_id=license_["id"]
    )
    case = fixtures.open_investigation(api, case["id"])

    data = validate_success(
        api.record_finding(
            case["id"],
            factories.finding_payload(
                finding="PROBABLE_CAUSE",
                aggravating_factor_count=0,
                mitigating_factor_count=1,
                violation_count=2,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        200,
    )

    assert data["subject_plan_submission_id"] is None
    assert round(data["penalty_factor"], 2) == pytest.approx(0.85)
    # 127500 per violation x 2 violations + 0 stamping + 40800 cost recovery.
    assert_money_cents(data["assessed_penalty_cents"], 295800)
    assert data["investigation_status"] == "PROBABLE_CAUSE"


def test_stamping_component_rounds_per_sheet_at_a_factor_above_one(api):
    """PRD §3.9: "Step one computes the aggravation/mitigation factor: start at 1.00, add 0.25 for each aggravating factor found, subtract 0.15 for each mitigating factor found, round that raw figure half up to two decimal places, and then clamp the result to no less than 0.50 and no more than 2.00."

    Design: Difficulty/combinatorial_formula/civil_penalty_round_per_sheet_then_multiply_391062
    """
    state = _flagged_plan_set_case(api, sheet_count=12)

    data = validate_success(
        api.record_finding(
            state["case"]["id"],
            factories.finding_payload(
                finding="PROBABLE_CAUSE",
                aggravating_factor_count=2,
                mitigating_factor_count=1,
                violation_count=1,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        200,
    )

    assert round(data["penalty_factor"], 2) == pytest.approx(1.35)
    # 270000 conduct + 27948 stamping (2329 per sheet x 12) + 64800 cost recovery.
    assert_money_cents(data["assessed_penalty_cents"], 362748)
    assert data["assessed_penalty_cents"] - (270000 + 64800) == 27948


def test_statutory_cap_applies_only_to_the_sum_of_the_rounded_components(api):
    """PRD §3.9: "Step five adds the three already-rounded components and takes the smaller of that sum and the statutory cap of 1,000,000 cents; the sum itself is never rounded again."

    Design: Difficulty/combinatorial_formula/civil_penalty_round_per_sheet_then_multiply_391062
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        unlicensed_respondent_name="Meridian Design Group",
    )
    case = fixtures.open_investigation(api, case["id"])

    data = validate_success(
        api.record_finding(
            case["id"],
            factories.finding_payload(
                finding="PROBABLE_CAUSE",
                aggravating_factor_count=8,
                mitigating_factor_count=0,
                violation_count=2,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        200,
    )

    assert round(data["penalty_factor"], 2) == pytest.approx(2.0)
    # 500000 per violation x 2 + 0 stamping + 96000 cost recovery = 1096000, capped.
    assert_money_cents(data["assessed_penalty_cents"], 1000000)
    assert data["respondent_license_id"] is None


# ---------------------------------------------------------------------------
# Application fee: the comity tier keyed off the pre-discount total
# ---------------------------------------------------------------------------


def test_comity_tier_is_keyed_off_the_pre_discount_total_not_the_subtotal(api):
    """PRD §3.2: "The comity discount tier looks as though it should key off the amount finally owed, but that amount already nets the discount out, which would be circular; the board's rule keys the tier off the pre-discount total instead."

    Design: Difficulty/combinatorial_formula/comity_fee_tier_keyed_on_pre_credit_total_47642
    """
    engineer = fixtures.create_engineer(api, full_name="Nils Bergen", ncees_record_id="NC-77120")
    applicant = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api,
        engineer["id"],
        pathway="COMITY",
        exam_code="PE_MECHANICAL",
        degree_level="MS",
        expedite_requested=True,
    )
    fixtures.evaluate_education(
        api, application["id"], degree_level="MS", accreditation_finding="EABET_ACCREDITED"
    )
    fixtures.transmit_ncees_packet(
        api,
        application["id"],
        ncees_record_id="NC-77120",
        source_jurisdiction="WA",
        verified_exam_pass=True,
        verified_years_licensed=9,
        disciplinary_history_count=0,
        record_expires_on="2027-06-30T00:00:00Z",
    )
    fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        employer_name="Puget Mechanical",
        position_title="Principal Engineer",
        period_start_month="2016-01",
        period_end_month="2021-12",
        responsibility_level="RESPONSIBLE_CHARGE",
        post_degree=True,
    )

    data = validate_success(api.get_fee_assessment(application["id"], applicant), 200)

    assert_money_cents(data["base_fee_cents"], 37500)
    assert_money_cents(data["records_verification_fee_cents"], 2500)
    assert_money_cents(data["ncees_record_fee_cents"], 7500)
    assert_money_cents(data["expedite_surcharge_cents"], 8550)
    assert_money_cents(data["pre_credit_total_cents"], 56050)
    assert data["comity_credit_tier_pct"] == pytest.approx(0.15)
    assert_money_cents(data["comity_credit_cents"], 8408)
    assert_money_cents(data["assessment_total_cents"], 47642)

    stored = get_success_data(api.get_application(application["id"], applicant))
    assert_money_cents(stored["fee_assessment_cents"], 47642)
    assert stored["ncees_record_status"] == "MATCHED"
    assert stored["status"] == "DRAFT"


def test_pre_discount_total_of_exactly_50000_cents_takes_the_15_percent_tier(api):
    """PRD §3.2: "The thresholds are inclusive, so a pre-discount total of exactly 50,000 cents takes the 15 percent rate while 49,999 cents takes 10 percent."

    Design: Difficulty/combinatorial_formula/comity_fee_tier_keyed_on_pre_credit_total_47642
    """
    on_threshold = fixtures.create_engineer(api, ncees_record_id="NC-50000A")
    on_headers = make_applicant_headers(on_threshold["id"])
    app_on = fixtures.create_application(
        api, on_threshold["id"], pathway="COMITY", exam_code="PE_CIVIL", expedite_requested=False
    )
    fixtures.transmit_ncees_packet(
        api, app_on["id"], ncees_record_id="NC-50000A", verified_years_licensed=9
    )
    fixtures.add_experience_record(
        api,
        app_on["id"],
        on_threshold["id"],
        period_start_month="2016-01",
        period_end_month="2018-12",
    )
    fixtures.add_experience_record(
        api,
        app_on["id"],
        on_threshold["id"],
        period_start_month="2019-01",
        period_end_month="2021-12",
    )

    data = validate_success(api.get_fee_assessment(app_on["id"], on_headers), 200)

    assert_money_cents(data["records_verification_fee_cents"], 5000)
    assert_money_cents(data["expedite_surcharge_cents"], 0)
    assert_money_cents(data["pre_credit_total_cents"], 50000)
    assert data["comity_credit_tier_pct"] == pytest.approx(0.15)
    assert_money_cents(data["comity_credit_cents"], 7500)
    assert_money_cents(data["assessment_total_cents"], 42500)

    below = fixtures.create_engineer(api, ncees_record_id="NC-47500B")
    below_headers = make_applicant_headers(below["id"])
    app_below = fixtures.create_application(
        api, below["id"], pathway="COMITY", exam_code="PE_CIVIL", expedite_requested=False
    )
    fixtures.transmit_ncees_packet(
        api, app_below["id"], ncees_record_id="NC-47500B", verified_years_licensed=9
    )
    fixtures.add_experience_record(
        api,
        app_below["id"],
        below["id"],
        period_start_month="2016-01",
        period_end_month="2018-12",
    )

    below_data = validate_success(api.get_fee_assessment(app_below["id"], below_headers), 200)

    assert_money_cents(below_data["pre_credit_total_cents"], 47500)
    assert below_data["comity_credit_tier_pct"] == pytest.approx(0.10)
    assert_money_cents(below_data["comity_credit_cents"], 4750)
    assert_money_cents(below_data["assessment_total_cents"], 42750)


def test_examination_pathway_takes_no_comity_discount_at_any_pre_discount_total(api):
    """PRD §3.2: "Step six picks the comity discount rate from that pre-discount total: 0 percent for any file whose `pathway` is not `COMITY`; otherwise 15 percent when the pre-discount total is at least 50,000 cents, 10 percent when it is at least 30,000 cents, and 5 percent below that."

    Design: Difficulty/combinatorial_formula/comity_fee_tier_keyed_on_pre_credit_total_47642
    """
    engineer = fixtures.create_engineer(api)
    applicant = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api,
        engineer["id"],
        pathway="STANDARD_EXAM",
        exam_code="PE_ELECTRICAL",
        expedite_requested=True,
    )
    fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        period_start_month="2019-01",
        period_end_month="2022-12",
    )

    data = validate_success(api.get_fee_assessment(application["id"], applicant), 200)

    assert_money_cents(data["base_fee_cents"], 25000)
    assert_money_cents(data["records_verification_fee_cents"], 2500)
    assert_money_cents(data["ncees_record_fee_cents"], 0)
    assert_money_cents(data["expedite_surcharge_cents"], 4950)
    assert_money_cents(data["pre_credit_total_cents"], 32450)
    assert data["comity_credit_tier_pct"] == pytest.approx(0.0)
    assert_money_cents(data["comity_credit_cents"], 0)
    assert_money_cents(data["assessment_total_cents"], 32450)

    stored = get_success_data(api.get_application(application["id"], applicant))
    assert_money_cents(stored["fee_assessment_cents"], 32450)
    assert stored["ncees_record_status"] == "NOT_REQUESTED"
