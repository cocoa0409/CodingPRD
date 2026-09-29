"""Pinned arithmetic of the licensure register: the assessed application fee, the
continuing-competency hour valuation and its shortfall, audit-sample ranking, and
the weighting of verified experience credit.
"""

import pytest

from test_helpers import (
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_money_cents,
    assert_pdh_value,
    factories,
    fixtures,
    make_applicant_headers,
    make_licensee_headers,
    validate_success,
)


def test_standard_exam_fee_with_two_records_assesses_30000_cents(api):
    """PRD §3.2: "Step one selects the base charge: 25,000 cents for a `STANDARD_EXAM` file, 37,500 cents for a `COMITY` file. Step two prices verification work: the number of experience blocks attached to the file, multiplied by 2,500 cents apiece, plus a flat 7,500 cents when `ncees_record_status` is `MATCHED` and nothing when it is not."

    Design: Corner/calculations/application_fee_standard_two_records_totals_30000
    """
    engineer = fixtures.create_engineer(api, full_name="Fay Olund")
    application = fixtures.create_application(
        api,
        engineer["id"],
        exam_code="PE_ELECTRICAL",
        pathway="STANDARD_EXAM",
        expedite_requested=False,
    )
    assert application["ncees_record_status"] == "NOT_REQUESTED"

    fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        employer_name="Olund Power",
        position_title="Engineer I",
        period_start_month="2019-01",
        period_end_month="2020-12",
        responsibility_level="SUBORDINATE",
        post_degree=True,
    )
    fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        employer_name="Olund Power",
        position_title="Engineer III",
        period_start_month="2021-01",
        period_end_month="2022-12",
        responsibility_level="RESPONSIBLE_CHARGE",
        post_degree=True,
    )

    applicant = make_applicant_headers(engineer["id"])
    breakdown = validate_success(
        api.get_fee_assessment(application["id"], applicant), 200
    )
    assert_money_cents(breakdown["base_fee_cents"], 25000)
    assert_money_cents(breakdown["records_verification_fee_cents"], 5000)
    assert_money_cents(breakdown["ncees_record_fee_cents"], 0)
    assert_money_cents(breakdown["expedite_surcharge_cents"], 0)
    assert_money_cents(breakdown["pre_credit_total_cents"], 30000)
    assert breakdown["comity_credit_tier_pct"] == pytest.approx(0)
    assert_money_cents(breakdown["comity_credit_cents"], 0)
    assert_money_cents(breakdown["assessment_total_cents"], 30000)

    stored = validate_success(api.get_application(application["id"], applicant), 200)
    assert_money_cents(stored["fee_assessment_cents"], 30000)
    assert_money_cents(stored["fee_paid_cents"], 0)


def test_accepted_documentation_is_the_only_input_to_the_audit_verified_total(api):
    """PRD §3.6: "demands proof, includes only line items whose `documentation_status` is `ACCEPTED`, allows `SELF_STUDY` a ceiling of 0 hours — unproctored self study earns nothing under audit — and writes its result to `audit_verified_total_pdh`"

    Design: Corner/calculations/audit_verified_total_counts_only_accepted_documentation
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 30, "carryover_pdh_claimed": 0}
    )
    engineer_id = setup["engineer"]["id"]
    license_ = setup["license"]
    report_id = setup["report"]["id"]
    completed_on = license_["current_period_start"]

    main_line = fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="COURSE",
        pdh_hours=28.0,
        completed_on=completed_on,
        ethics_flag=False,
    )
    fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="COURSE",
        pdh_hours=2.0,
        completed_on=completed_on,
        ethics_flag=True,
    )
    fixtures.accept_cpc_report(api, report_id)
    fixtures.draw_audit(
        api,
        headers=BOARD_SECRETARY_HEADERS,
        sample_pct=1.0,
        as_of_period_end=license_["current_period_end"],
    )

    licensee = make_licensee_headers(engineer_id)
    under_audit = validate_success(api.get_cpc_report(report_id, licensee), 200)
    assert under_audit["status"] == "UNDER_AUDIT"
    assert_pdh_value(under_audit["audit_verified_total_pdh"], 0.0)

    reviewed = validate_success(
        api.review_pdh_documentation(
            main_line["id"], {"decision": "ACCEPT"}, BOARD_REVIEWER_HEADERS
        ),
        200,
    )
    assert reviewed["documentation_status"] == "ACCEPTED"

    report = validate_success(api.get_cpc_report(report_id, licensee), 200)
    assert_pdh_value(report["audit_verified_total_pdh"], 28.0)
    assert_pdh_value(report["self_certified_total_pdh"], 30.0)
    assert report["status"] == "UNDER_AUDIT"


def test_rejected_documentation_leaves_the_audit_verified_total_untouched(api):
    """PRD §3.6: "A `BoardReviewer` reviews the evidence behind one line item at a time, supplying a `decision` of `ACCEPT` or `REJECT`, which sets that line item's `documentation_status` to `ACCEPTED` or `REJECTED` respectively and re-runs the audit-verified total on the owning report."

    Design: Corner/calculations/audit_verified_total_counts_only_accepted_documentation
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 30, "carryover_pdh_claimed": 0}
    )
    engineer_id = setup["engineer"]["id"]
    license_ = setup["license"]
    report_id = setup["report"]["id"]
    completed_on = license_["current_period_start"]

    main_line = fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="COURSE",
        pdh_hours=28.0,
        completed_on=completed_on,
        ethics_flag=False,
    )
    ethics_line = fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="COURSE",
        pdh_hours=2.0,
        completed_on=completed_on,
        ethics_flag=True,
    )
    fixtures.accept_cpc_report(api, report_id)
    fixtures.draw_audit(
        api,
        headers=BOARD_SECRETARY_HEADERS,
        sample_pct=1.0,
        as_of_period_end=license_["current_period_end"],
    )
    fixtures.review_pdh_documentation(api, main_line["id"], "ACCEPT")

    rejected = validate_success(
        api.review_pdh_documentation(
            ethics_line["id"], {"decision": "REJECT"}, BOARD_REVIEWER_HEADERS
        ),
        200,
    )
    assert rejected["documentation_status"] == "REJECTED"

    licensee = make_licensee_headers(engineer_id)
    report = validate_success(api.get_cpc_report(report_id, licensee), 200)
    assert_pdh_value(report["audit_verified_total_pdh"], 28.0)
    assert_pdh_value(report["self_certified_total_pdh"], 30.0)
    assert report["status"] == "UNDER_AUDIT"


def test_self_study_hours_are_trimmed_to_eight_under_self_certification(api):
    """PRD §3.6: "takes the licensee's attestation at face value, includes every line item whose `documentation_status` is `NONE` or `ACCEPTED` — only `REJECTED` documentation is dropped — allows `SELF_STUDY` a ceiling of 8 hours, and writes its result to `self_certified_total_pdh`"

    Design: Corner/calculations/pdh_self_study_cap_eight_applied_under_self_certification
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 28, "carryover_pdh_claimed": 0}
    )
    engineer_id = setup["engineer"]["id"]
    license_ = setup["license"]
    report_id = setup["report"]["id"]
    assert license_["pdh_requirement"] == pytest.approx(30)

    licensee = make_licensee_headers(engineer_id)
    line = validate_success(
        api.create_pdh_record(
            report_id,
            factories.pdh_record_payload(
                activity_type="SELF_STUDY",
                pdh_hours=12.0,
                completed_on=license_["current_period_start"],
                ethics_flag=False,
            ),
            licensee,
        ),
        201,
    )
    assert_pdh_value(line["pdh_hours"], 12.0)
    assert line["documentation_status"] == "NONE"

    report = validate_success(api.get_cpc_report(report_id, licensee), 200)
    assert_pdh_value(report["self_certified_total_pdh"], 8.0)
    assert_pdh_value(report["shortfall_pdh"], 24.0)


def test_shortfall_adds_the_hour_deficit_to_the_two_hour_ethics_deficit(api):
    """PRD §3.6: "The hour deficiency is the licence's `pdh_requirement` minus the report's total, or 0 if that difference would be negative. The ethics deficiency is 2 hours minus the ethics hours just summed, or 0 if that difference would be negative. `shortfall_pdh` is the sum of those two deficiencies, rounded half up to one decimal place."

    Design: Corner/calculations/pdh_self_study_cap_eight_applied_under_self_certification
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 28, "carryover_pdh_claimed": 0}
    )
    engineer_id = setup["engineer"]["id"]
    license_ = setup["license"]
    report_id = setup["report"]["id"]
    completed_on = license_["current_period_start"]

    fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="SELF_STUDY",
        pdh_hours=12.0,
        completed_on=completed_on,
        ethics_flag=False,
    )

    licensee = make_licensee_headers(engineer_id)
    validate_success(
        api.create_pdh_record(
            report_id,
            factories.pdh_record_payload(
                activity_type="COURSE",
                pdh_hours=20.0,
                completed_on=completed_on,
                ethics_flag=False,
            ),
            licensee,
        ),
        201,
    )

    report = validate_success(api.get_cpc_report(report_id, licensee), 200)
    assert_pdh_value(report["self_certified_total_pdh"], 28.0)
    assert_pdh_value(report["shortfall_pdh"], 4.0)
    assert report["status"] == "SUBMITTED"


def test_hour_total_holds_one_decimal_place_across_three_tenth_hour_activities(api):
    """PRD §3.6: "Step four adds the activity subtotal and the capped carryover and rounds the result half up to one decimal place, giving the report's total."

    Design: Corner/calculations/pdh_total_holds_one_decimal_without_float_drift
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 30.3, "carryover_pdh_claimed": 0}
    )
    engineer_id = setup["engineer"]["id"]
    license_ = setup["license"]
    report_id = setup["report"]["id"]
    completed_on = license_["current_period_start"]

    fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="COURSE",
        pdh_hours=10.1,
        completed_on=completed_on,
        ethics_flag=True,
    )
    fixtures.add_pdh_record(
        api,
        report_id,
        engineer_id,
        activity_type="COURSE",
        pdh_hours=10.1,
        completed_on=completed_on,
        ethics_flag=False,
    )

    licensee = make_licensee_headers(engineer_id)
    validate_success(
        api.create_pdh_record(
            report_id,
            factories.pdh_record_payload(
                activity_type="SEMINAR",
                pdh_hours=10.1,
                completed_on=completed_on,
                ethics_flag=False,
            ),
            licensee,
        ),
        201,
    )

    report = validate_success(api.get_cpc_report(report_id, licensee), 200)
    assert_pdh_value(report["self_certified_total_pdh"], 30.3)
    assert_pdh_value(report["shortfall_pdh"], 0.0)


def test_self_certified_total_recomputes_on_every_line_item_added(api):
    """PRD §3.6: "The hour total is computed in five steps, and each activity category is capped independently before anything is summed."

    Design: Corner/calculations/self_certified_total_recomputes_on_each_pdh_record_added
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 42, "carryover_pdh_claimed": 0}
    )
    engineer_id = setup["engineer"]["id"]
    completed_on = setup["license"]["current_period_start"]
    report_id = setup["report"]["id"]
    licensee = make_licensee_headers(engineer_id)

    walk = (
        ("COURSE", 20.0, False, 20.0, 12.0),
        ("SEMINAR", 10.0, False, 30.0, 2.0),
        ("TEACHING", 15.0, False, 40.0, 2.0),
        ("COURSE", 2.0, True, 42.0, 0.0),
    )
    for activity_type, hours, ethics_flag, expected_total, expected_shortfall in walk:
        validate_success(
            api.create_pdh_record(
                report_id,
                factories.pdh_record_payload(
                    activity_type=activity_type,
                    pdh_hours=hours,
                    completed_on=completed_on,
                    ethics_flag=ethics_flag,
                ),
                licensee,
            ),
            201,
        )
        report = validate_success(api.get_cpc_report(report_id, licensee), 200)
        assert_pdh_value(report["self_certified_total_pdh"], expected_total)
        assert_pdh_value(report["shortfall_pdh"], expected_shortfall)


def test_audit_sample_takes_the_thinnest_margins_not_the_oldest_reports(api):
    """PRD §3.6: "Each pooled report's margin is its `self_certified_total_pdh` minus the `pdh_requirement` of the licence it covers, and the pool is ordered by that margin ascending."

    Design: Corner/calculations/cpc_audit_sample_orders_by_margin_ascending
    """
    reports = {}
    period_end = None
    for label, declared, extra in (
        ("A", 30, None),
        ("B", 40, ("SEMINAR", 10.0)),
        ("C", 35, ("SEMINAR", 5.0)),
    ):
        setup = fixtures.setup_cpc_report(
            api,
            report_overrides={"self_certified_pdh": declared, "carryover_pdh_claimed": 0},
        )
        engineer_id = setup["engineer"]["id"]
        report_id = setup["report"]["id"]
        completed_on = setup["license"]["current_period_start"]
        period_end = setup["license"]["current_period_end"]
        fixtures.add_pdh_record(
            api,
            report_id,
            engineer_id,
            activity_type="COURSE",
            pdh_hours=28.0,
            completed_on=completed_on,
            ethics_flag=False,
        )
        fixtures.add_pdh_record(
            api,
            report_id,
            engineer_id,
            activity_type="COURSE",
            pdh_hours=2.0,
            completed_on=completed_on,
            ethics_flag=True,
        )
        if extra is not None:
            fixtures.add_pdh_record(
                api,
                report_id,
                engineer_id,
                activity_type=extra[0],
                pdh_hours=extra[1],
                completed_on=completed_on,
                ethics_flag=False,
            )
        fixtures.accept_cpc_report(api, report_id)
        reports[label] = report_id

    draw = validate_success(
        api.create_cpc_audit(
            factories.cpc_audit_payload(sample_pct=0.34, as_of_period_end=period_end),
            BOARD_SECRETARY_HEADERS,
        ),
        201,
    )
    assert draw["pool_size"] == 3
    assert draw["sampled_count"] == 2
    assert draw["status"] == "SAMPLED"
    assert draw["created_by_user_id"] == "SEC-1"

    drawn_a = validate_success(
        api.get_cpc_report(reports["A"], BOARD_REVIEWER_HEADERS), 200
    )
    assert drawn_a["status"] == "UNDER_AUDIT"
    assert drawn_a["audit_id"] == draw["id"]
    assert_pdh_value(drawn_a["self_certified_total_pdh"], 30.0)

    drawn_c = validate_success(
        api.get_cpc_report(reports["C"], BOARD_REVIEWER_HEADERS), 200
    )
    assert drawn_c["status"] == "UNDER_AUDIT"
    assert drawn_c["audit_id"] == draw["id"]
    assert_pdh_value(drawn_c["self_certified_total_pdh"], 35.0)

    spared_b = validate_success(
        api.get_cpc_report(reports["B"], BOARD_REVIEWER_HEADERS), 200
    )
    assert spared_b["status"] == "ACCEPTED"
    assert spared_b["audit_id"] is None
    assert_pdh_value(spared_b["self_certified_total_pdh"], 40.0)


def test_peer_verification_halves_the_credited_months_of_a_verified_block(api):
    """PRD §3.3: "includes only blocks whose `verification_status` is `VERIFIED`, and weights each block at 1.00 when the accepted verification on it came from a `DIRECT_SUPERVISOR` and at 0.50 when it came from a `PROJECT_MANAGER` or a `PEER`"

    Design: Corner/calculations/indirect_reference_halves_verified_credit
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="under_review",
        application_overrides={"degree_level": "MS", "exam_code": "PE_CIVIL"},
        education_overrides={"degree_level": "MS"},
        experience_overrides={
            "employer_name": "Renn Water Group",
            "position_title": "Engineer of Record",
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
            "responsibility_level": "RESPONSIBLE_CHARGE",
            "post_degree": True,
        },
        reference_overrides={"relationship": "PEER"},
        submission_overrides={
            "evaluation_score": 5,
            "months_confirmed": 48,
            "responsibility_confirmed": True,
        },
    )
    engineer_id = track["engineer"]["id"]
    application_id = track["application"]["id"]
    record_id = track["experience_record"]["id"]

    accepted = validate_success(
        api.evaluate_reference(
            track["reference"]["id"], {"decision": "ACCEPT"}, BOARD_REVIEWER_HEADERS
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    applicant = make_applicant_headers(engineer_id)
    record = validate_success(api.get_experience_record(record_id, applicant), 200)
    assert record["verification_status"] == "VERIFIED"
    assert record["raw_months"] == 48
    assert record["credit_multiplier"] == pytest.approx(1.0)
    assert record["credited_months"] == 24

    application = validate_success(api.get_application(application_id, applicant), 200)
    assert application["verified_experience_months"] == 24
    assert application["provisional_experience_months"] == 48
