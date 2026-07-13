"""Rent math: anticipated vs actual gross, the greatest-of-three TTP, medical
threshold rounding, and tenant rent vs utility reimbursement."""
from test_helpers import TEST_USERS
from test_helpers.fixtures import (
    setup_finalized_annual_cert, report_interim_change, process_interim_change,
    get_certification_by_source_interim,
)

HS = TEST_USERS["housing_specialist_headers"]

ALVAREZ_MEMBERS = [
    {"full_name": "Head Alvarez", "relationship": "HEAD",
     "annual_income_cents": 3600000, "nonrecurring_income_cents": 240000},
    {"full_name": "Dep One", "relationship": "DEPENDENT", "annual_income_cents": 0, "is_dependent": True},
    {"full_name": "Dep Two", "relationship": "DEPENDENT", "annual_income_cents": 0, "is_dependent": True},
]


# ---------------------------------------------------------------------------
# dual_variant_calc / rent_anticipated_vs_actual_ttp
# ---------------------------------------------------------------------------
def test_annual_cert_uses_anticipated_gross_including_nonrecurring(api):
    """PRD §3.5: "For the anticipated variant, used by INITIAL and ANNUAL
    certifications, each member contributes its annual_income_cents plus its
    nonrecurring_income_cents, projecting the full forward year including one-time
    amounts." PRD §3.5: "The Total Tenant Payment is the integer maximum of these three
    components and is snapshotted as ttp_cents."

    Design: Difficulty/dual_variant_calc/rent_anticipated_vs_actual_ttp
    """
    ctx = setup_finalized_annual_cert(api, members=ALVAREZ_MEMBERS, utility_allowance_cents=10000)
    cert = ctx["cert"]
    assert cert["annual_gross_income_cents"] == 3840000, \
        "anticipated gross adds the 240,000 nonrecurring to 3,600,000 recurring"
    assert cert["ttp_cents"] == 93600


def test_interim_cert_uses_actual_gross_excluding_nonrecurring(api):
    """PRD §3.5: "For the actual variant, used by INTERIM certifications, each member
    contributes only its annual_income_cents, so the non-recurring lines are excluded
    and the same roster yields a lower gross than the anticipated variant." PRD §3.7: a
    processed change "finalizes that interim certification to EFFECTIVE on the actual-income
    variant (recurring income only)".

    Design: Difficulty/dual_variant_calc/rent_anticipated_vs_actual_ttp
    """
    ctx = setup_finalized_annual_cert(api, members=ALVAREZ_MEMBERS, utility_allowance_cents=10000)
    ic = report_interim_change(api, ctx["tenancy"]["id"], ctx["applicant"]["id"],
                               "COMPOSITION", "2026-05-01T00:00:00Z")
    process_interim_change(api, ic["id"], "PROCESS")
    interim_cert = get_certification_by_source_interim(api, ic["id"])
    assert interim_cert["annual_gross_income_cents"] == 3600000, \
        "actual gross excludes the nonrecurring lines"
    assert interim_cert["ttp_cents"] == 87600
    assert 93600 != interim_cert["ttp_cents"], "the two variants diverge on identical member rows"


# ---------------------------------------------------------------------------
# combinatorial_formula / ttp_greatest_of_three_min_rent_floor
# ---------------------------------------------------------------------------
def test_ttp_floors_at_minimum_rent(api):
    """PRD §3.5: "The third component is a minimum rent floor of 5,000 cents ($50). The
    Total Tenant Payment is the integer maximum of these three components and is
    snapshotted as ttp_cents."

    Design: Difficulty/combinatorial_formula/ttp_greatest_of_three_min_rent_floor
    """
    members = [{"full_name": "Head Low", "relationship": "HEAD", "annual_income_cents": 120000}]
    ctx = setup_finalized_annual_cert(api, members=members, bedroom_size=1, utility_allowance_cents=0)
    assert ctx["cert"]["ttp_cents"] == 5000, \
        "both percentage components fall below the 5,000-cent floor, so the floor wins"


def test_ttp_floor_case_adjusted_income_equals_gross(api):
    """PRD §3.5: "The adjusted income is the gross minus the sum of the dependent,
    elderly-or-disabled, childcare, and medical deductions, floored at zero" — with no
    deductions the adjusted equals the gross.

    Design: Difficulty/combinatorial_formula/ttp_greatest_of_three_min_rent_floor
    """
    members = [{"full_name": "Head Low", "relationship": "HEAD", "annual_income_cents": 120000}]
    ctx = setup_finalized_annual_cert(api, members=members, bedroom_size=1, utility_allowance_cents=0)
    assert ctx["cert"]["annual_adjusted_income_cents"] == 120000


# ---------------------------------------------------------------------------
# combinatorial_formula / adjusted_income_medical_threshold_rounding
# ---------------------------------------------------------------------------
OKAFOR_MEMBERS = [
    {"full_name": "Head Okafor", "relationship": "HEAD", "annual_income_cents": 2410000, "is_elderly": True},
    {"full_name": "Dep Okafor", "relationship": "DEPENDENT", "annual_income_cents": 0,
     "is_dependent": True, "is_disabled": True},
]


def test_adjusted_income_rounds_medical_threshold_before_subtracting(api):
    """PRD §3.5: "the threshold is 3% of the gross, and the order of operations is
    pinned — first compute 3% of the gross and round it half-up to whole cents, then
    subtract that rounded threshold from the certification's medical_expenses_annual_cents,
    taking the greater of that difference and zero".

    Design: Difficulty/combinatorial_formula/adjusted_income_medical_threshold_rounding
    """
    ctx = setup_finalized_annual_cert(api, members=OKAFOR_MEMBERS, utility_allowance_cents=0,
                                      childcare_expenses_annual_cents=120000,
                                      medical_expenses_annual_cents=150000)
    cert = ctx["cert"]
    assert cert["annual_gross_income_cents"] == 2410000
    assert cert["annual_adjusted_income_cents"] == 2124300, \
        "medical deduction uses the rounded 72,300 threshold (150000 - 72300 = 77700)"


def test_ttp_component_resolves_half_up_rounding(api):
    """PRD §3.5: "The first component is 30% of the annual adjusted income divided by
    12, with that whole expression rounded half-up to whole cents in a single step (the
    annual figure is divided by 12 inside the rounding step and is never pre-rounded to a
    monthly amount first)."

    Design: Difficulty/combinatorial_formula/adjusted_income_medical_threshold_rounding
    """
    ctx = setup_finalized_annual_cert(api, members=OKAFOR_MEMBERS, utility_allowance_cents=0,
                                      childcare_expenses_annual_cents=120000,
                                      medical_expenses_annual_cents=150000)
    assert ctx["cert"]["ttp_cents"] == 53108, \
        "0.30 * 2124300 / 12 == 53107.5 rounds half-up to 53108"


# ---------------------------------------------------------------------------
# Corner: utility_reimbursement_when_ua_exceeds_ttp
# ---------------------------------------------------------------------------
def test_utility_reimbursement_when_allowance_exceeds_ttp(api):
    """PRD §3.5: "the monthly_tenant_rent_cents is the Total Tenant Payment minus the
    utility allowance, floored at zero, and the utility_reimbursement_cents is the
    utility allowance minus the Total Tenant Payment, floored at zero. At most one of the
    two is positive."

    Design: Corner/calculations/utility_reimbursement_when_ua_exceeds_ttp
    """
    members = [{"full_name": "Head RB", "relationship": "HEAD", "annual_income_cents": 120000}]
    ctx = setup_finalized_annual_cert(api, members=members, utility_allowance_cents=8000)
    assert ctx["cert"]["ttp_cents"] == 5000
    assert ctx["tenancy"]["monthly_tenant_rent_cents"] == 0
    assert ctx["tenancy"]["utility_reimbursement_cents"] == 3000, "8000 allowance minus 5000 TTP"
