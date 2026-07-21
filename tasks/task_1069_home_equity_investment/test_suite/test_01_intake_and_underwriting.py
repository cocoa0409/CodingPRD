"""Intake, application creation, and the underwriting decision.

Covers queue-B entity/validation/state instances plus the queue-A
combined_ltv inclusive-boundary difficulty instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS, make_homeowner_headers,
    create_fund_payload, create_homeowner_payload, create_application_payload,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_new_fund_starts_fully_available(api):
    """PRD §2.6: "At creation a fund has `committed_capital_cents` equal to 0
    and `available_capital_cents` equal to its `total_capital_cents`."

    Design: Corner/entities/fund_create_computed_available_equals_total
    """
    fund = get_success_data(api.create_fund(create_fund_payload(total_capital_cents=30000000), ANALYST))
    got = validate_success(api.get_fund(fund["id"], ANALYST))
    assert got["committed_capital_cents"] == 0
    assert got["available_capital_cents"] == 30000000


def test_get_unknown_application_is_not_found(api):
    """PRD §2.4: "each successive `id` segment must resolve to an existing
    record before the next is considered, and the first unresolved segment
    yields that resource's specific not-found error, each carrying HTTP 404:
    ... an application `ERR_APPLICATION_NOT_FOUND`".

    Design: Corner/entities/application_get_nonexistent_returns_not_found
    """
    validate_error(api.get_application(NON_EXISTENT, ANALYST), "ERR_APPLICATION_NOT_FOUND", 404)


def test_application_missing_requested_investment_is_validation_error(api):
    """PRD §2.8: "Malformed bodies, missing required fields, and bad enum values
    are surfaced as ERR_VALIDATION (HTTP 400) as part of request parsing."

    Design: Corner/entities/application_create_missing_required_returns_validation
    """
    fund = get_success_data(api.create_fund(create_fund_payload(), ANALYST))
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(), ANALYST))
    payload = create_application_payload(ho["id"], fund["id"])
    del payload["requested_investment_cents"]
    validate_error(
        api.create_application(payload, make_homeowner_headers(ho["id"])),
        "ERR_VALIDATION", 400,
    )


def test_application_with_unknown_fund_is_not_found(api):
    """PRD §3.1: "If the referenced fund_id does not resolve to a fund the create
    is rejected with ERR_FUND_NOT_FOUND".

    Design: Corner/entities/application_create_bad_fund_returns_not_found
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(), ANALYST))
    payload = create_application_payload(ho["id"], NON_EXISTENT)
    validate_error(
        api.create_application(payload, make_homeowner_headers(ho["id"])),
        "ERR_FUND_NOT_FOUND", 404,
    )


def test_application_bad_property_type_is_validation_error(api):
    """PRD §2.8: "Malformed bodies, missing required fields, and bad enum values
    are surfaced as ERR_VALIDATION (HTTP 400) as part of request parsing."

    Design: Corner/entities/application_create_bad_property_type_invalid_enum
    """
    fund = get_success_data(api.create_fund(create_fund_payload(), ANALYST))
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(), ANALYST))
    payload = create_application_payload(ho["id"], fund["id"], property_type="HOUSEBOAT")
    validate_error(
        api.create_application(payload, make_homeowner_headers(ho["id"])),
        "ERR_VALIDATION", 400,
    )


def test_decision_by_homeowner_is_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to invoke the requested endpoint per the authorization matrix in
    Section 4, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    (The decision endpoint is authorized for InvestmentAnalyst only.)

    Design: Corner/validations/decision_by_homeowner_unauthorized
    """
    ctx = fixtures.setup_under_review_application(api)
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    validate_error(
        api.decide_application(ctx["application"]["id"], {"decision": "APPROVE"}, ho_headers),
        "ERR_UNAUTHORIZED", 403,
    )


def test_unknown_role_is_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
    these six known roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/validations/create_application_unknown_role_unauthenticated
    """
    fund = get_success_data(api.create_fund(create_fund_payload(), ANALYST))
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(), ANALYST))
    guest_headers = {"X-User-ID": ho["id"], "X-User-Role": "Guest"}
    payload = create_application_payload(ho["id"], fund["id"])
    validate_error(api.create_application(payload, guest_headers), "ERR_UNAUTHENTICATED", 401)


def test_submit_without_completed_valuation_rejected(api):
    """PRD §3.1: "The homeowner may advance the application from DRAFT to
    UNDER_REVIEW, but only once at least one COMPLETED valuation exists for that
    application; submitting with no completed valuation is rejected with
    ERR_NO_COMPLETED_VALUATION."

    Design: Corner/state_machines/submit_without_completed_valuation_returns_error
    """
    fund = get_success_data(api.create_fund(create_fund_payload(), ANALYST))
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(), ANALYST))
    app = get_success_data(api.create_application(
        create_application_payload(ho["id"], fund["id"]), make_homeowner_headers(ho["id"])
    ))
    validate_error(
        api.submit_application(app["id"], make_homeowner_headers(ho["id"])),
        "ERR_NO_COMPLETED_VALUATION", 409,
    )


def test_approve_ltv_exactly_at_ceiling_is_accepted(api):
    """PRD §3.3: "Approval is allowed only when combined_ltv is at most 0.75; if
    it exceeds 0.75 the approval is rejected with ERR_LTV_EXCEEDED and the
    application stays UNDER_REVIEW."

    Design: Difficulty/boundary_precision_check/combined_ltv_inclusive_boundary
    """
    ctx = fixtures.setup_under_review_application(
        api, valued_amount_cents=100000000,
        requested_investment_cents=25000000,
        existing_mortgage_balance_cents=50000000,
    )
    approved = validate_success(
        api.decide_application(ctx["application"]["id"], {"decision": "APPROVE"}, ANALYST)
    )
    assert approved["status"] == "APPROVED"
    assert approved["combined_ltv"] == 0.75


def test_approve_at_ceiling_assigns_elevated_risk_band(api):
    """PRD §3.3: "a risk_band is assigned from it: LOW when combined_ltv is at
    most 0.50, MODERATE when it is greater than 0.50 but at most 0.65, and
    ELEVATED when it is greater than 0.65".

    Design: Difficulty/boundary_precision_check/combined_ltv_inclusive_boundary
    """
    ctx = fixtures.setup_under_review_application(
        api, valued_amount_cents=100000000,
        requested_investment_cents=25000000,
        existing_mortgage_balance_cents=50000000,
    )
    approved = validate_success(
        api.decide_application(ctx["application"]["id"], {"decision": "APPROVE"}, ANALYST)
    )
    assert approved["risk_band"] == "ELEVATED"


def test_approve_ltv_over_ceiling_rejected(api):
    """PRD §3.3: "Approval is allowed only when combined_ltv is at most 0.75; if
    it exceeds 0.75 the approval is rejected with ERR_LTV_EXCEEDED and the
    application stays UNDER_REVIEW."

    Design: Corner/validations/decision_approve_ltv_exceeded_returns_422
    """
    ctx = fixtures.setup_under_review_application(
        api, valued_amount_cents=100000000,
        requested_investment_cents=26000000,
        existing_mortgage_balance_cents=50000000,
    )
    validate_error(
        api.decide_application(ctx["application"]["id"], {"decision": "APPROVE"}, ANALYST),
        "ERR_LTV_EXCEEDED", 422,
    )
