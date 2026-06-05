"""Valuation regimes, exemption deductions, tax-bill rounding, and numeric boundaries.

Covers difficulty queue instances:
  dual_variant_calc / capped_rollforward_vs_market_rebase_on_assessment
  combinatorial_formula / exemption_deduction_multiinput_branching_mode_a
  combinatorial_formula / tax_bill_round_once_mode_b
  boundary_precision_check / growth_cap_ceiling_exact_boundary
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    make_reviewer_headers,
    setup_successor_open_roll,
    setup_certified_parcel,
    create_assessment,
    claim_exemption,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ===========================================================================
# dual_variant_calc / capped_rollforward_vs_market_rebase_on_assessment
# ===========================================================================
def test_capped_rollforward_clips_to_growth_ceiling(api):
    """PRD §3.3: "When `reassessment_event` is `NONE` **and** the prior base is greater than
    0, the parcel is rolling forward under the cap: the cap ceiling is the prior base
    multiplied by one plus the roll's `growth_cap_pct`, and `capped_base_value` is the smaller
    of the year's `market_value` and that ceiling."
    PRD §3.3: "In either regime `assessed_value` equals `capped_base_value`, and both are
    expressed in whole dollars, rounded half-up to the nearest dollar."

    Design: Difficulty/dual_variant_calc/capped_rollforward_vs_market_rebase_on_assessment
    """
    owner, roll1, parcel, roll2 = setup_successor_open_roll(
        prior_capped_base=100000, growth_cap_pct=0.02, mill_rate=10.0
    )
    asmt = create_assessment(parcel["id"], roll2["id"], 130000, reassessment_event="NONE")
    data = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    # ceiling = 100000 * 1.02 = 102000; min(130000, 102000) = 102000
    assert data["capped_base_value"] == 102000, \
        f"capped roll-forward should clip to 102000, got {data['capped_base_value']}"
    assert data["assessed_value"] == 102000, \
        f"assessed_value must equal capped_base_value, got {data['assessed_value']}"


def test_market_rebase_after_sale_ignores_cap(api):
    """PRD §3.3: "When instead `reassessment_event` is `SALE` or `NEW_CONSTRUCTION`, **or**
    the prior base is 0 (the parcel's first-ever assessment), the cap is ignored entirely and
    `capped_base_value` is set to the full `market_value`, resetting the Proposition-13 base
    for all future years."

    Design: Difficulty/dual_variant_calc/capped_rollforward_vs_market_rebase_on_assessment
    """
    # Certified parcel with prior base 100000, then sold so the next assessment must be SALE.
    owner, roll1, parcel = setup_certified_parcel(prior_capped_base=100000)
    roll2 = api.create_tax_roll(
        f.create_tax_roll_payload(tax_year=2026, prior_roll_id=roll1["id"]), ASSESSOR
    ).json()["data"]
    validate_success(api.open_tax_roll(roll2["id"], ASSESSOR))
    # Record a sale: this resets last_certified_capped_base to 0 and primes a SALE assessment.
    buyer = api.create_owner(f.create_owner_payload(), ASSESSOR).json()["data"]
    validate_success(api.record_sale(parcel["id"], {"new_owner_id": buyer["id"]}, ASSESSOR))
    asmt = create_assessment(parcel["id"], roll2["id"], 130000, reassessment_event="SALE")
    data = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert data["capped_base_value"] == 130000, \
        f"SALE rebase should set capped_base to full market 130000, got {data['capped_base_value']}"
    assert data["assessed_value"] == 130000


# ===========================================================================
# combinatorial_formula / exemption_deduction_multiinput_branching_mode_a
# ===========================================================================
def test_senior_exemption_uses_percentage_when_above_floor(api):
    """PRD §3.4: "A senior deduction is the larger of a 5,000-dollar floor and ten percent of
    the assessment's `assessed_value` rounded half-up to whole dollars — that is, the senior
    amount never falls below 5,000 but rises with valuable homes."

    Design: Difficulty/combinatorial_formula/exemption_deduction_multiinput_branching_mode_a
    """
    # Build a capped assessment (assessed_value 102000) under a senior owner: a parcel
    # certified at prior base 100000, then rolled forward at market 130000 under a 2% cap.
    owner2, roll1b, parcel2 = setup_certified_parcel(
        prior_capped_base=100000, owner_overrides={"birth_date": "1950-01-01T00:00:00.000Z"}
    )
    roll2b = api.create_tax_roll(
        f.create_tax_roll_payload(tax_year=2026, prior_roll_id=roll1b["id"]), ASSESSOR
    ).json()["data"]
    validate_success(api.open_tax_roll(roll2b["id"], ASSESSOR))
    asmt = create_assessment(parcel2["id"], roll2b["id"], 130000, reassessment_event="NONE")
    assert asmt["assessed_value"] == 102000
    exm = claim_exemption(asmt["id"], "SENIOR")
    data = validate_success(api.approve_exemption(exm["id"], REVIEWER))
    # max(5000, round(102000 * 0.10)) = max(5000, 10200) = 10200
    assert data["claimed_amount"] == 10200, \
        f"SENIOR on AV 102000 should be 10200, got {data['claimed_amount']}"
    assert data["status"] == "APPROVED"


def test_disability_exemption_branch_multiplies_percent_and_factor(api):
    """PRD §3.4: "A disability deduction is the assessment's `assessed_value` multiplied by
    the owner's `disability_pct` divided by 100, then multiplied by a factor of one-half, the
    whole rounded half-up to whole dollars."

    Design: Difficulty/combinatorial_formula/exemption_deduction_multiinput_branching_mode_a
    """
    # assessed_value 90000 (first-ever NONE -> market rebase), disability_pct 80:
    # round(90000 * 80/100 * 0.50) = round(36000) = 36000.
    owner = api.create_owner(
        f.create_owner_payload(disability_pct=80), ASSESSOR
    ).json()["data"]
    roll = api.open_tax_roll(
        api.create_tax_roll(f.create_tax_roll_payload(), ASSESSOR).json()["data"]["id"], ASSESSOR
    ).json()["data"]
    parcel = api.create_parcel(f.create_parcel_payload(owner["id"]), ASSESSOR).json()["data"]
    asmt = create_assessment(parcel["id"], roll["id"], 90000, reassessment_event="NONE")
    assert asmt["assessed_value"] == 90000
    exm = claim_exemption(asmt["id"], "DISABILITY")
    data = validate_success(api.approve_exemption(exm["id"], REVIEWER))
    assert data["claimed_amount"] == 36000, \
        f"DISABILITY deduction should be 36000, got {data['claimed_amount']}"


# ===========================================================================
# combinatorial_formula / tax_bill_round_once_mode_b
# ===========================================================================
def test_tax_bill_rounds_once_after_full_precision_product(api):
    """PRD §3.8: "the full-precision product of the billed taxable value and the roll's
    `mill_rate` divided by 1000 is taken first as a dollar figure, then converted to cents,
    and only then rounded half-up to a whole cent — a single rounding applied once, after
    the complete product. (Equivalently, the cents amount is the billed taxable value times
    the mill rate divided by 10, rounded half-up.)"

    Design: Difficulty/combinatorial_formula/tax_bill_round_once_mode_b
    """
    # final_taxable_value 84800 at mill_rate 12.3456: round(84800*12.3456/10) = 104691.
    owner, roll1b, parcel2 = setup_certified_parcel(
        prior_capped_base=100000, owner_overrides={"birth_date": "1950-01-01T00:00:00.000Z"},
        parcel_overrides={"is_primary_residence": True},
    )
    roll2 = api.create_tax_roll(
        f.create_tax_roll_payload(tax_year=2026, mill_rate=12.3456, prior_roll_id=roll1b["id"]),
        ASSESSOR,
    ).json()["data"]
    validate_success(api.open_tax_roll(roll2["id"], ASSESSOR))
    asmt = create_assessment(parcel2["id"], roll2["id"], 130000, reassessment_event="NONE")
    assert asmt["assessed_value"] == 102000
    # HOMESTEAD (7000) + SENIOR (10200) = 17200; taxable = 102000 - 17200 = 84800.
    ex_hs = claim_exemption(asmt["id"], "HOMESTEAD")
    ex_sr = claim_exemption(asmt["id"], "SENIOR")
    validate_success(api.approve_exemption(ex_hs["id"], REVIEWER))
    validate_success(api.approve_exemption(ex_sr["id"], REVIEWER))
    validate_success(api.notice_assessment(asmt["id"], ASSESSOR))
    validate_success(api.finalize_assessment(asmt["id"], ASSESSOR))
    bill = validate_success(api.issue_bill(asmt["id"], ASSESSOR), expected_status=201)
    assert bill["billed_taxable_value"] == 84800, \
        f"billed_taxable_value should be 84800, got {bill['billed_taxable_value']}"
    assert bill["tax_amount_cents"] == 104691, \
        f"round(84800*12.3456/10) should be 104691, got {bill['tax_amount_cents']}"


def test_tax_bill_simple_mill_rate_product(api):
    """PRD §3.8: "the full-precision product of the billed taxable value and the roll's
    `mill_rate` divided by 1000 is taken first as a dollar figure, then converted to cents,
    and only then rounded half-up to a whole cent — a single rounding applied once, after the
    complete product."

    Design: Difficulty/combinatorial_formula/tax_bill_round_once_mode_b
    """
    # final_taxable_value 100000 at mill_rate 10.0: round(100000*10/10) = 100000 cents.
    owner, roll1, parcel = setup_certified_parcel(prior_capped_base=100000)
    roll2 = api.create_tax_roll(
        f.create_tax_roll_payload(tax_year=2026, mill_rate=10.0, prior_roll_id=roll1["id"]),
        ASSESSOR,
    ).json()["data"]
    validate_success(api.open_tax_roll(roll2["id"], ASSESSOR))
    asmt = create_assessment(parcel["id"], roll2["id"], 100000, reassessment_event="NONE")
    # ceiling 102000, market 100000 -> capped 100000, no exemptions -> taxable 100000.
    validate_success(api.notice_assessment(asmt["id"], ASSESSOR))
    validate_success(api.finalize_assessment(asmt["id"], ASSESSOR))
    bill = validate_success(api.issue_bill(asmt["id"], ASSESSOR), expected_status=201)
    assert bill["tax_amount_cents"] == 100000, \
        f"round(100000*10/10) should be 100000, got {bill['tax_amount_cents']}"


# ===========================================================================
# boundary_precision_check / growth_cap_ceiling_exact_boundary
# ===========================================================================
@pytest.mark.parametrize("market_value,expected_capped", [
    (101999, 101999),  # market below ceiling -> market wins
    (102000, 102000),  # market equals ceiling -> equal, 102000
    (102001, 102000),  # market above ceiling -> clipped to ceiling
])
def test_growth_cap_ceiling_boundary(api, market_value, expected_capped):
    """PRD §3.3: "the cap ceiling is the prior base multiplied by one plus the roll's
    `growth_cap_pct`, and `capped_base_value` is the smaller of the year's `market_value`
    and that ceiling."

    Design: Difficulty/boundary_precision_check/growth_cap_ceiling_exact_boundary
    """
    owner, roll1, parcel, roll2 = setup_successor_open_roll(
        prior_capped_base=100000, growth_cap_pct=0.02
    )  # ceiling = 102000
    asmt = create_assessment(parcel["id"], roll2["id"], market_value, reassessment_event="NONE")
    data = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert data["capped_base_value"] == expected_capped, (
        f"market {market_value} against ceiling 102000 should yield {expected_capped}, "
        f"got {data['capped_base_value']}"
    )


def test_growth_cap_ceiling_exactly_at_boundary(api):
    """PRD §3.3: "the cap ceiling is the prior base multiplied by one plus the roll's
    `growth_cap_pct`, and `capped_base_value` is the smaller of the year's `market_value`
    and that ceiling."

    Design: Difficulty/boundary_precision_check/growth_cap_ceiling_exact_boundary
    """
    # market_value exactly at the 102000 ceiling: min(102000, 102000) == 102000.
    owner, roll1, parcel, roll2 = setup_successor_open_roll(
        prior_capped_base=100000, growth_cap_pct=0.02
    )
    asmt = create_assessment(parcel["id"], roll2["id"], 102000, reassessment_event="NONE")
    data = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert data["capped_base_value"] == 102000, \
        f"market exactly at ceiling 102000 should yield 102000, got {data['capped_base_value']}"
