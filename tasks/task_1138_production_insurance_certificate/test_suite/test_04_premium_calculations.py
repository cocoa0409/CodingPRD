"""Premium calculations: cast loadings, provisional-vs-final audit variants,
and tiered bond pricing (PRD §2.6, §3.1, §3.7, §3.10)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    create_completion_bond_payload,
    set_logical_clock, create_production, setup_cast_policy_bound,
    setup_cast_policy_active_for_audit, add_cast_member,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
SU = TEST_USERS["surety_underwriter_headers"]
AUD = TEST_USERS["external_auditor_headers"]


# ─── Cast premium combinatorial loadings (difficulty) ─

def test_cast_premium_combinatorial_loadings(api):
    """PRD §3.1: "The **provisional premium** starts from the declared
    `payroll_basis_cents` and multiplies it by a base rate that depends on the
    coverage line: 1.20 percent for `GENERAL_LIABILITY`, 1.85 percent for
    `EQUIPMENT`, 2.75 percent for `CAST`, 3.50 percent for `ERRORS_OMISSIONS`,
    and 4.20 percent for `FOREIGN_TRAVEL`."
    PRD §3.1: "Cast coverage adds two further loadings: a stunt loading of one
    plus ten hundredths for every cast member whose `role_tier` is `STUNT`,
    capped at 1.50, and an essential-element loading of 1.20 whenever any cast
    member on the production carries `essential_element` set to true (1.00 when
    none does)."

    FEATURE roster: 2 STUNT + 1 essential PRINCIPAL, payroll 100000000.
    100000000 * 0.0275 = 2750000; * 1.00 (FEATURE) = 2750000;
    * 1.20 (two STUNT) = 3300000; * 1.20 (essential element) = 3960000.

    Design: Difficulty/combinatorial_formula/cast_premium_combinatorial_loadings
    """
    prod, cast_policy, _ = setup_cast_policy_bound(
        cast_members=[
            {"role_tier": "STUNT", "essential_element": False,
             "exam_outcome": "CLEARED"},
            {"role_tier": "STUNT", "essential_element": False,
             "exam_outcome": "CLEARED"},
            {"role_tier": "PRINCIPAL", "essential_element": True,
             "exam_outcome": "CLEARED", "weekly_salary_cents": 1000000},
        ])
    assert cast_policy["provisional_premium_cents"] == 3960000
    persisted = validate_success(
        api.get_policy(prod["id"], cast_policy["id"], BROKER), 200)
    assert persisted["provisional_premium_cents"] == 3960000


def test_cast_premium_stunt_loading_capped(api):
    """PRD §3.1: "Cast coverage adds two further loadings: a stunt loading of
    one plus ten hundredths for every cast member whose `role_tier` is `STUNT`,
    capped at 1.50"

    Six STUNT members would produce 1 + 0.10*6 = 1.60 uncapped; the cap pins
    the loading to 1.50: 100000000 * 0.0275 = 2750000; * 1.00 = 2750000;
    * 1.50 = 4125000; * 1.00 (no essential element) = 4125000.

    Design: Difficulty/combinatorial_formula/cast_premium_combinatorial_loadings
    """
    prod, cast_policy, _ = setup_cast_policy_bound(
        cast_members=[{"role_tier": "STUNT", "essential_element": False}
                      for _ in range(6)])
    assert cast_policy["provisional_premium_cents"] == 4125000


# ─── Provisional vs final premium after audit (difficulty) ───

def test_premium_provisional_vs_final_after_audit(api):
    """PRD §3.10: "Posting copies the audit's `reported_payroll_cents` into the
    policy's `audited_payroll_cents`, recomputes the premium with exactly the
    same formula as the provisional premium (§3.1) but reading the audited
    payroll instead of the declared basis — including the same minimum-premium
    floor — and stores the result as the policy's `final_premium_cents`."

    Declared basis 100000000 -> provisional 3630000 (CAST base 0.0275, FEATURE
    1.00, stunt loading 1.10 for one STUNT, essential loading 1.20). Audited
    payroll 120000000 -> 120000000*0.0275 = 3300000; *1.00 = 3300000;
    *1.10 = 3630000; *1.20 = 4356000.

    Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_after_audit
    """
    prod, policy, audit = setup_cast_policy_active_for_audit(
        reported_payroll_cents=120000000, payroll_basis_cents=100000000)
    assert policy["status"] == "ACTIVE"
    assert policy["provisional_premium_cents"] == 3630000

    posted = validate_success(
        api.post_payroll_audit(prod["id"], policy["id"], audit["id"], BROKER), 200)
    policy_after = validate_success(
        api.get_policy(prod["id"], policy["id"], BROKER), 200)
    assert policy_after["provisional_premium_cents"] == 3630000
    assert policy_after["audited_payroll_cents"] == 120000000
    assert policy_after["final_premium_cents"] == 4356000
    assert policy_after["final_premium_cents"] != policy_after["provisional_premium_cents"]
    assert posted["premium_delta_cents"] == (
        policy_after["final_premium_cents"] - policy_after["provisional_premium_cents"])


def test_premium_delta_negative_when_audited_payroll_lower(api):
    """PRD §3.10: "The audit then records `premium_delta_cents`, the final
    premium minus the provisional premium: a positive delta means the
    production owes the carrier the difference, a negative delta means a refund
    is due to the production."

    Audited payroll 80000000 -> 80000000*0.0275 = 2200000; *1.00 = 2200000;
    *1.10 = 2420000; *1.20 = 2904000; delta = 2904000 - 3630000 = -726000.

    Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_after_audit
    """
    prod, policy, audit = setup_cast_policy_active_for_audit(
        reported_payroll_cents=80000000, payroll_basis_cents=100000000)
    posted = validate_success(
        api.post_payroll_audit(prod["id"], policy["id"], audit["id"], BROKER), 200)
    policy_after = validate_success(
        api.get_policy(prod["id"], policy["id"], BROKER), 200)
    assert policy_after["final_premium_cents"] == 2904000
    assert posted["premium_delta_cents"] == -726000
    assert posted["premium_delta_cents"] == (
        policy_after["final_premium_cents"] - policy_after["provisional_premium_cents"])


# ─── Bond premium per-tier rounding (difficulty) ──────

def _underwritten_bond(budget_cents, bond_amount_cents):
    set_logical_clock()
    prod = create_production(budget_cents=budget_cents,
                             requires_completion_bond=True)
    bond = validate_success(
        api_client.apply_completion_bond(
            prod["id"],
            create_completion_bond_payload(bond_amount_cents=bond_amount_cents), PM),
        201)
    return prod, validate_success(api_client.underwrite_bond(prod["id"], SU), 200)


def test_bond_premium_per_tier_rounding(api):
    """PRD §3.7: "The **bond premium** is tiered on `bond_amount_cents`: 2.00
    percent on the first 1,000,000 dollars, 1.50 percent on the portion above
    1,000,000 dollars up to 5,000,000 dollars, 1.10 percent on the portion
    above 5,000,000 dollars up to 25,000,000 dollars, and 0.85 percent on any
    portion above 25,000,000 dollars."
    PRD §3.7: "`strike_price_cents` — the takeover threshold the surety will
    fund up to — is set equal to `bond_amount_cents`."

    bond 1500000000 -> 100000000*0.02 + 400000000*0.015 + 1000000000*0.011
    = 2000000 + 6000000 + 11000000 = 19000000.

    Design: Difficulty/combinatorial_formula/bond_premium_per_tier_rounding
    """
    prod, bond = _underwritten_bond(budget_cents=2000000000,
                                    bond_amount_cents=1500000000)
    assert bond["bond_premium_cents"] == 19000000
    assert bond["strike_price_cents"] == 1500000000


def test_bond_premium_tier_one_boundary(api):
    """PRD §3.7: "a bond amount of exactly 1,000,000 dollars falls entirely
    within the first tier — tier boundaries are inclusive at the lower bound of
    the next tier."
    PRD §2.6: "each pricing tier's contribution is rounded half up to whole
    cents first, and only then are the tier contributions summed"

    bond 100000000 -> 100000000 * 0.02 = 2000000, no higher tier entered.

    Design: Difficulty/combinatorial_formula/bond_premium_per_tier_rounding
    """
    prod, bond = _underwritten_bond(budget_cents=100000000,
                                    bond_amount_cents=100000000)
    assert bond["bond_premium_cents"] == 2000000
    assert bond["strike_price_cents"] == 100000000
