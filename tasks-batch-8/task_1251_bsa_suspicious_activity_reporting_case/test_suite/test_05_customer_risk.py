"""Customer risk rating: dual STANDARD/ENHANCED variants and the account-open
gate (PRD §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_customer,
    create_account_payload,
    create_le_inquiry,
    create_staff,
    create_customer,
    validate_error,
    validate_paginated,
    validate_success,
)


def _customer_with_open_inquiries(api, staff, full_name, country_code, country_risk,
                                  inquiry_count=3):
    customer = create_customer(
        staff, full_name=full_name, country_code=country_code,
        country_risk=country_risk)
    for i in range(inquiry_count):
        create_le_inquiry(staff, customer["id"],
                          agency_name=["FBI", "IRS-CI", "DEA"][i % 3],
                          inquiry_reference=f"LE-{country_code}-{i + 1}")
    return validate_success(api.get_customer(customer["id"], staff.analyst), 200)


def test_low_risk_country_customer_uses_standard_score(api):
    """PRD §2.6: "The standard score starts from a base of 100, adds 250 points
    for every SAR filed for the customer within the trailing 365 days, adds 150
    points for every open law-enforcement inquiry, and adds 400 points if any
    of the customer's accounts has ever reached `EXITED`."
    PRD §2.6: "When `country_risk` is `HIGH`, the enhanced score governs; when
    `country_risk` is `LOW`, the standard score governs."
    PRD §2.6: "The `risk_rating` band is then determined by inclusive
    thresholds: 700 or more is `PROHIBITED`, at least 400 but under 700 is
    `HIGH`, at least 200 but under 400 is `MEDIUM`, and anything below 200 is
    `LOW`."

    Three open inquiries give 100 + 3*150 = 550; the applicable STANDARD
    variant lands in the HIGH band.

    Design: Difficulty/dual_variant_calc/customer_risk_standard_vs_enhanced_diverge
    """
    staff = create_staff()
    customer = _customer_with_open_inquiries(
        api, staff, "Pat Lowrisk", "US", "LOW")
    assert_customer(customer)
    assert customer["open_le_inquiry_count"] == 3
    assert customer["risk_score_standard"] == 550
    assert customer["risk_score_enhanced"] == 825, (
        "both variants are always computed and stored"
    )
    assert customer["risk_rating"] == "HIGH", (
        "the LOW country_risk customer is rated by the standard score 550"
    )


def test_high_risk_country_customer_uses_enhanced_score(api):
    """PRD §2.6: "The enhanced score is the standard score multiplied by 1.5,
    rounded half-up to the nearest integer."
    PRD §2.6: "When `country_risk` is `HIGH`, the enhanced score governs; when
    `country_risk` is `LOW`, the standard score governs."
    PRD §2.6: "The `risk_rating` band is then determined by inclusive
    thresholds: 700 or more is `PROHIBITED`, at least 400 but under 700 is
    `HIGH`, at least 200 but under 400 is `MEDIUM`, and anything below 200 is
    `LOW`."

    Identical facts (three open inquiries) yield the same stored scores, but
    the applicable ENHANCED variant 825 >= 700 rates PROHIBITED.

    Design: Difficulty/dual_variant_calc/customer_risk_standard_vs_enhanced_diverge
    """
    staff = create_staff()
    customer = _customer_with_open_inquiries(
        api, staff, "Harriet Highrisk", "IR", "HIGH")
    assert_customer(customer)
    assert customer["open_le_inquiry_count"] == 3
    assert customer["risk_score_standard"] == 550
    assert customer["risk_score_enhanced"] == 825
    assert customer["risk_rating"] == "PROHIBITED", (
        "same facts, different applicable variant, different band"
    )


def test_prohibited_customer_cannot_open_account(api):
    """PRD §2.6: "The rating also gates account opening directly: an attempt to
    open a new account for a customer whose `risk_rating` is `PROHIBITED` or
    whose `status` is `EXITED` is rejected with `ERR_CUSTOMER_PROHIBITED` (HTTP
    409)."

    Design: Corner/errors/prohibited_customer_account_open_rejected
    """
    staff = create_staff()
    customer = _customer_with_open_inquiries(
        api, staff, "Harriet Highrisk", "IR", "HIGH")
    assert customer["risk_rating"] == "PROHIBITED"

    res = api.create_account(
        customer["id"], create_account_payload(account_number="ACC-8503"),
        staff.admin)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_PROHIBITED)
    assert res.status_code == 409
    data, meta = validate_paginated(api.list_accounts(customer["id"], staff.admin))
    assert data == [] and meta["total_count"] == 0
