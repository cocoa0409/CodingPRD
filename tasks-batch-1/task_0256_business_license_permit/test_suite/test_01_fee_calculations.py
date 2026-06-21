"""Fee calculations: the dual-variant fee story and combinatorial formulas.

Covers difficulty rules dual_variant_calc and combinatorial_formula plus the
corner calculation-result instances that are not owned by a difficulty stub.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_applicant_headers, make_licensing_officer_headers,
    create_activity_category_payload, create_business_payload,
    create_application_payload, create_inspection_payload,
    record_inspection_payload, complete_transfer_payload,
    TEST_USERS,
    setup_issued_license, setup_approved_transfer, get_license_fee_assessments,
    assessments_of_kind,
)

OFFICER = TEST_USERS["licensing_officer_headers"]
INSPECTOR = TEST_USERS["inspection_officer_headers"]
ISSUER = make_licensing_officer_headers("officer-issuer")


def test_estimate_and_final_fee_diverge_same_application(api):
    """PRD §3.2: "the estimate is the base fee for the risk tier — 100.00 for
    `LOW`, 250.00 for `MEDIUM`, 600.00 for `HIGH` — plus 5.00 multiplied by the
    declared employee count, plus a 150.00 variance surcharge when the
    application's `zoning_status` is `VARIANCE_REQUIRED` and nothing otherwise,
    with the three components added together and the total rounded once to two
    decimal places using round-half-up."
    PRD §3.5: "it is the base fee for the activity's risk tier (100.00 for
    `LOW`, 250.00 for `MEDIUM`, 600.00 for `HIGH`), plus 5.00 multiplied by the
    verified employee count, plus the 150.00 zoning variance surcharge when the
    application's `zoning_status` is `VARIANCE_REQUIRED` and nothing otherwise,
    plus 75.00 multiplied by the number of this application's inspections whose
    `result` is `PASSED`; the four components are summed and the total is
    rounded once to two decimal places using round-half-up."

    Design: Difficulty/dual_variant_calc/license_fee_estimate_vs_final_diverge
    """
    # HIGH category, requires_zoning_check, 2 inspections, zone C1 allowed.
    ctx = setup_issued_license(
        category_overrides={
            "code": "FOOD_SERVICE", "risk_tier": "HIGH", "activity_base_risk": 40,
            "required_inspection_count": 2, "requires_zoning_check": True,
            "term_months": 12, "allowed_zones": ["C1", "C2"],
        },
        application_overrides={"declared_employee_count": 12, "requested_zone_code": "C1"},
        passed_inspections=[
            {"inspector_user_id": "insp-1", "verified_employee_count": 15},
            {"inspector_user_id": "insp-1", "verified_employee_count": 15},
        ],
    )
    application = get_success_data(
        api.get_application(ctx["application"]["id"], OFFICER))
    license_ = ctx["license"]

    assert application["estimated_fee"] == 660.00, application["estimated_fee"]
    assert license_["final_fee"] == 825.00, license_["final_fee"]
    assert license_["final_fee"] != application["estimated_fee"]


def test_issuance_fee_nonlinear_multi_input_with_variance(api):
    """PRD §3.5: "it is the base fee for the activity's risk tier (100.00 for
    `LOW`, 250.00 for `MEDIUM`, 600.00 for `HIGH`), plus 5.00 multiplied by the
    verified employee count, plus the 150.00 zoning variance surcharge when the
    application's `zoning_status` is `VARIANCE_REQUIRED` and nothing otherwise,
    plus 75.00 multiplied by the number of this application's inspections whose
    `result` is `PASSED`; the four components are summed and the total is
    rounded once to two decimal places using round-half-up."

    Design: Difficulty/combinatorial_formula/issuance_fee_nonlinear_multi_input
    """
    # MEDIUM, allowed_zones=[C1], request I2 -> VARIANCE_REQUIRED; 1 inspection verified 6.
    api.set_clock("2026-06-01T00:00:00Z", OFFICER)
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="RETAIL_MED", risk_tier="MEDIUM", activity_base_risk=20,
            required_inspection_count=1, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Var Shop", owner_name="V Owner",
                                zone_code="I2"), TEST_USERS["applicant_headers"]))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=4, requested_zone_code="I2"), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    zc = get_success_data(api.zoning_check_application(app["id"], OFFICER))
    assert zc["zoning_status"] == "VARIANCE_REQUIRED"
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "insp-3"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 6, 0), INSPECTOR))
    get_success_data(api.approve_application(app["id"], OFFICER))

    license_ = validate_success(api.issue_application(app["id"], ISSUER), 201)
    assert license_["final_fee"] == 505.00, license_["final_fee"]


def test_variance_surcharge_recompute_order(api):
    """PRD §3.2: "Concretely, the estimate is the base fee for the risk tier —
    100.00 for `LOW`, 250.00 for `MEDIUM`, 600.00 for `HIGH` — plus 5.00
    multiplied by the declared employee count, plus a 150.00 variance surcharge
    when the application's `zoning_status` is `VARIANCE_REQUIRED` and nothing
    otherwise, with the three components added together and the total rounded
    once to two decimal places using round-half-up."
    PRD §3.3: "on this branch the system recomputes `estimated_fee` to include
    the 150.00 zoning variance surcharge and correspondingly raises the open
    `APPLICATION_FEE` assessment's `amount` to match the new estimate."

    Design: Difficulty/combinatorial_formula/variance_surcharge_recompute_order_pinned
    """
    api.set_clock("2026-06-01T00:00:00Z", OFFICER)
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="BAR_HIGH", risk_tier="HIGH", activity_base_risk=35,
            required_inspection_count=0, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Late Bar", owner_name="L Owner",
                                zone_code="I9"), TEST_USERS["applicant_headers"]))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=12, requested_zone_code="I9"), biz_h))
    submitted = get_success_data(api.submit_application(app["id"], biz_h))
    assert submitted["estimated_fee"] == 660.00, submitted["estimated_fee"]

    after = validate_success(api.zoning_check_application(app["id"], OFFICER), 200)
    assert after["estimated_fee"] == 810.00, after["estimated_fee"]
    assert after["zoning_status"] == "VARIANCE_REQUIRED"


def test_penalty_tier_b_day61(api):
    """PRD §3.6: "If it is greater than 60 but at most 90 days, the rate is 25
    percent. ... The penalty is that rate multiplied by the base renewal fee for
    the license's risk tier — 200.00 for `LOW`, 480.00 for `MEDIUM`, 900.00 for
    `HIGH` — rounded to two decimal places using round-half-up."
    PRD §3.6: "The delinquency assessment always opens a `RENEWAL_FEE`
    assessment for the renewal fee, and additionally opens a
    `DELINQUENCY_PENALTY` assessment for the penalty whenever the penalty is
    greater than zero."

    Design: Corner/calculations/penalty_tier_b_day61_correct
    """
    api.set_clock("2026-06-01T00:00:00Z", OFFICER)
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="PEN_MED", risk_tier="MEDIUM", activity_base_risk=20,
            required_inspection_count=0, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Pen Biz", owner_name="PB",
                                zone_code="C1"), TEST_USERS["applicant_headers"]))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    get_success_data(api.approve_application(app["id"], OFFICER))
    lic = get_success_data(api.issue_application(app["id"], ISSUER))
    api.set_clock("2027-08-01T00:00:00Z", OFFICER)  # 61 days overdue
    delinq = validate_success(api.assess_delinquency(lic["id"], OFFICER), 200)
    assert delinq["status"] == "DELINQUENT"

    ledger = get_license_fee_assessments(lic["id"])
    penalties = assessments_of_kind(ledger, "DELINQUENCY_PENALTY")
    assert len(penalties) == 1 and penalties[0]["amount"] == 120.00, penalties
    renewals = assessments_of_kind(ledger, "RENEWAL_FEE")
    assert any(r["amount"] == 480.00 for r in renewals), renewals


def test_transfer_fee_high_risk_surcharge(api):
    """PRD §3.9: "The transfer fee is a flat 300.00, plus a 200.00 risk
    surcharge only when the license's activity `risk_tier` is `HIGH` and nothing
    otherwise, with the two components summed and rounded to two decimal places
    using round-half-up."
    PRD §3.9: "the system computes the `transfer_fee` and opens a `TRANSFER_FEE`
    assessment against the license for it, and both the license's `version` and
    the transfer's `version` advance."

    Design: Corner/calculations/transfer_fee_high_risk_surcharge_correct
    """
    ctx = setup_approved_transfer(risk_tier="HIGH")
    completed = validate_success(api.complete_transfer(
        ctx["transfer"]["id"],
        complete_transfer_payload(ctx["license_version"]), OFFICER), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["transfer_fee"] == 500.00, completed["transfer_fee"]
