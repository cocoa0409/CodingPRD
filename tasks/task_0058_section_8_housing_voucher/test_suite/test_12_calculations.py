"""Queue B (breadth) — eligibility, adjusted-income, annual-review recompute,
and occupancy-standard calculations.
"""
from test_helpers import (
    api_client, validate_success, set_clock,
    create_region, make_eligible_household, issue_voucher, create_household,
    setup_active_hap_contract, draft_annual_review,
    create_voucher_payload, finalize_annual_review_payload,
    CASEWORKER,
)


def test_income_eligibility_equal_to_limit_passes():
    """PRD §3.2: "The family is eligible when its adjusted_annual_income_cents is
    less than or equal to that income limit; the boundary is inclusive, so a
    household whose adjusted income exactly equals the limit qualifies." Family
    of 3 with no deductions at the limit 3,600,000 is ELIGIBLE.

    Design: Corner/calculations/income_eligibility_inclusive_boundary_equal_passes
    """
    region = create_region(code="ELIG_B")
    household = create_household(region["id"], family_size=3, annual_income_cents=3600000)
    hh = validate_success(api_client.determine_eligibility(household["id"], CASEWORKER), 200)
    assert hh["adjusted_annual_income_cents"] == 3600000
    assert hh["status"] == "ELIGIBLE"


def test_income_eligibility_one_over_limit_ineligible():
    """PRD §3.2: "otherwise it sets the status to INELIGIBLE (APPLIED ->
    INELIGIBLE)." Family of 3 with adjusted income 3,600,001, one cent over the
    limit, is INELIGIBLE.

    Design: Corner/calculations/income_eligibility_just_over_limit_ineligible
    """
    region = create_region(code="INELIG_B")
    household = create_household(region["id"], family_size=3, annual_income_cents=3600001)
    hh = validate_success(api_client.determine_eligibility(household["id"], CASEWORKER), 200)
    assert hh["status"] == "INELIGIBLE"


def test_adjusted_income_floored_at_zero():
    """PRD §3.2: "Adjusted income is the gross income minus all three deductions,
    and if that subtraction would fall below zero it is floored at zero." Gross
    50,000 with 2 dependents (96,000 deduction) floors to 0.

    Design: Corner/calculations/adjusted_income_floored_at_zero
    """
    region = create_region(code="FLOOR_R")
    household = create_household(
        region["id"], family_size=3, annual_income_cents=50000, dependents_count=2
    )
    hh = validate_success(api_client.determine_eligibility(household["id"], CASEWORKER), 200)
    assert hh["adjusted_annual_income_cents"] == 0
    assert hh["status"] == "ELIGIBLE"


def test_annual_review_recomputes_ttp_and_subsidy():
    """PRD §3.8: "The review's new_total_tenant_payment_cents is then computed by
    the total-tenant-payment formula of Section 3.5, and its new_hap_subsidy_cents
    by the subsidy formula of Section 3.5. These recomputed amounts cascade onto
    the contract". New income 2,400,000 -> TTP 60,000, subsidy 50,000.

    Design: Corner/calculations/annual_review_recomputes_ttp_and_subsidy
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=110000, family_size=3, annual_income_cents=1500000,
        amount_cents=120000, fmr_cents=120000,
        asking_rent_cents=110000, comparable_rent_cents=110000,
    )
    review = draft_annual_review(
        contract["id"], new_annual_income_cents=2400000,
        effective_date="2026-07-01T00:00:00Z",
    )
    finalized = validate_success(
        api_client.finalize_annual_review(
            review["id"], finalize_annual_review_payload(contract["version"]), CASEWORKER
        ),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["new_total_tenant_payment_cents"] == 60000
    assert finalized["new_hap_subsidy_cents"] == 50000
    updated = validate_success(api_client.get_hap_contract(contract["id"], CASEWORKER), 200)
    assert updated["hap_subsidy_cents"] == 50000


def test_occupancy_studio_for_single_person():
    """PRD §3.3: "a family of one or fewer is assigned 0 bedrooms". A single
    person household's voucher gets bedroom_size 0.

    Design: Corner/calculations/occupancy_studio_for_single_person
    """
    region = create_region(code="OCC_STD")
    household = make_eligible_household(region["id"], family_size=1, annual_income_cents=1000000)
    voucher = validate_success(
        api_client.create_voucher(create_voucher_payload(household["id"]), CASEWORKER), 201
    )
    assert voucher["bedroom_size"] == 0
