"""Onboarding, creation, defaults, computed fields, sub-resource listings.

Covers corner-design sections: entities, endpoints, consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_lender_payload, create_borrower_payload, create_application_payload,
    create_proceeds_payload, create_collateral_payload,
    assert_lender, assert_application,
    create_lender, create_borrower, create_application,
    add_collateral, reach_approved,
    TEST_USERS,
)

OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_lender_returns_201_with_system_fields(api, sba_officer_headers):
    """PRD §3.1: "A newly created lender starts with both pool balances,
    `ongoing_fee_pool_cents` and `sold_guaranty_balance_cents`, at zero."
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    when the resource is created and increments by one on every mutation of that
    resource."

    Design: Corner/entities/create_lender_returns_201_with_system_fields
    """
    res = api.create_lender(create_lender_payload(name="Echo CDC", program="504"), sba_officer_headers)
    lender = validate_success(res, 201)
    assert_lender(lender)
    assert lender["program"] == "504"
    assert lender["ongoing_fee_pool_cents"] == 0
    assert lender["sold_guaranty_balance_cents"] == 0
    assert lender["version"] == 1, f"version must begin at 1, got {lender['version']}"


def test_get_application_not_found_returns_404(api, sba_officer_headers):
    """PRD §2.5: "the server validates each identifier left to right and rejects
    the request with `ERR_NOT_FOUND` at the first identifier in the path that does
    not resolve to an existing resource."

    Design: Corner/entities/get_application_not_found_returns_404
    """
    res = api.get_application(NONEXISTENT, sba_officer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_borrower_missing_required_field_returns_invalid_request(api, sba_officer_headers, loan_officer_headers):
    """PRD §2.10: "the request body is checked for well-formedness — required fields
    present, no negative or zero value where a positive one is required, enum members
    valid, and any foreign-key target actually existing (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/create_borrower_missing_required_field_returns_invalid_request
    """
    lender = create_lender(name="Req CDC")
    payload = create_borrower_payload(lender["id"], legal_name="NoNaics LLC")
    del payload["naics_code"]
    res = api.create_borrower(payload, loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_borrower_default_eligible_true_when_omitted(api, loan_officer_headers):
    """PRD §3.1: "The borrower also carries `is_eligible_business_type`, a boolean that
    defaults to true and is set false for ineligible types such as passive holding
    companies, lending businesses, and speculative ventures; this flag is the hard
    eligibility gate examined at submit time."

    Design: Corner/entities/borrower_default_eligible_true_when_omitted
    """
    lender = create_lender(name="Def CDC")
    payload = create_borrower_payload(lender["id"], legal_name="Def LLC")
    # is_eligible_business_type intentionally omitted.
    res = api.create_borrower(payload, loan_officer_headers)
    borrower = validate_success(res, 201)
    assert borrower["is_eligible_business_type"] is True


def test_proceeds_is_fixed_asset_computed_from_use_category(api, loan_officer_headers):
    """PRD §3.2: "The system sets the line's `is_fixed_asset` flag to true exactly when
    the category is `EQUIPMENT` or `REAL_ESTATE`, marking the fixed-asset portion of the
    proceeds, and false for every other category."

    Design: Corner/entities/proceeds_is_fixed_asset_computed_from_use_category
    """
    lender = create_lender(name="Fx CDC")
    borrower = create_borrower(lender["id"], legal_name="Fx LLC", naics_code="333120")
    app = create_application(borrower["id"])
    res = api.create_proceeds(
        create_proceeds_payload(app["id"], use_category="EQUIPMENT", amount_cents=50_000_000),
        loan_officer_headers)
    line = validate_success(res, 201)
    assert line["is_fixed_asset"] is True


def test_application_guaranty_pct_over_cap_returns_invalid_request(api, loan_officer_headers):
    """PRD §3.1: "the SBA `guaranty_pct` on that gross loan (a fraction strictly greater
    than 0 and at most 0.90, for example 0.75 or 0.85)".

    Design: Corner/entities/create_application_invalid_enum_program_irrelevant_guaranty_pct_over_cap
    """
    lender = create_lender(name="Tc CDC")
    borrower = create_borrower(lender["id"], legal_name="Tc LLC")
    res = api.create_application(
        create_application_payload(borrower["id"], guaranty_pct=0.95), loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_application_unknown_borrower_fk_returns_invalid_request(api, loan_officer_headers):
    """PRD §2.10: "the request body is checked for well-formedness — required fields
    present, no negative or zero value where a positive one is required, enum members
    valid, and any foreign-key target actually existing (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/application_fk_borrower_unknown_returns_invalid_request
    """
    create_lender(name="Fk CDC")  # lender exists, but borrower id below does not
    res = api.create_application(
        create_application_payload("11111111-1111-4111-8111-111111111111"), loan_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_collateral_subresource_returns_array(api, sba_officer_headers):
    """PRD §3.2: "Collateral items are listable as a sub-resource per application."

    Design: Corner/endpoints/list_collateral_subresource_returns_array
    """
    lender = create_lender(name="Lst CDC")
    borrower = create_borrower(lender["id"], legal_name="Lst LLC")
    app = create_application(borrower["id"])
    add_collateral(app["id"], asset_type="REAL_ESTATE", appraised_value_cents=70_000_000)
    add_collateral(app["id"], asset_type="EQUIPMENT", appraised_value_cents=10_000_000)
    res = api.list_collateral(app["id"], sba_officer_headers)
    data, meta = validate_paginated(res)
    assert len(data) == 2, f"expected exactly 2 collateral rows, got {len(data)}"
    assert all(item["application_id"] == app["id"] for item in data)


def test_list_borrowers_by_lender_subresource(api, loan_officer_headers):
    """PRD §3.1: "The borrowers under a given lender are discoverable by listing that
    lender's borrowers."

    Design: Corner/endpoints/list_borrowers_by_lender_subresource
    """
    lender = create_lender(name="Lb CDC", program="504")
    borrower = create_borrower(lender["id"], legal_name="Lb LLC")
    res = api.list_lender_borrowers(lender["id"], loan_officer_headers)
    data, meta = validate_paginated(res)
    assert any(b["id"] == borrower["id"] for b in data), "created borrower must appear in lender's list"


def test_authorize_freezes_amounts_in_same_response(api):
    """PRD §3.6: "The first frozen figure is `guaranteed_amount_cents`, the SBA-guaranteed
    portion of the loan. It is the application's `requested_amount_cents` multiplied by its
    `guaranty_pct`, rounded half up to whole cents."
    PRD §3.6: "The three floored band fees are then summed to give `guaranty_fee_cents`."

    Design: Corner/consistency_model/authorize_freezes_amounts_in_same_response
    """
    # requested 50000000, gp 0.75 -> guaranteed 37500000; fee:
    #   band1 floor(15000000*0.75*0.02)=225000
    #   band2 floor((70000000-15000000)*0.75*0.03)=floor(55000000*0.0225)=1237500 -> but g=50000000
    #   band2 only spans min(g-TIER1,TIER2-TIER1)=35000000: floor(35000000*0.75*0.03)=787500
    #   fee = 225000 + 787500 = 1012500
    ctx = reach_approved()
    res = api.authorize_application(ctx["application"]["id"], SBA)
    app = validate_success(res, 200)
    assert app["status"] == "AUTHORIZED"
    assert app["guaranteed_amount_cents"] == 37_500_000
    assert app["guaranty_fee_cents"] == 1_012_500
