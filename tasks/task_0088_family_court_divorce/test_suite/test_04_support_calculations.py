"""Child- and spousal-support computation (PRD §3.6).

Translates queue A (Difficulty) rules dual_variant_calc, combinatorial_formula,
boundary_precision_check, plus queue B (Corner) `calculations` instances. Every
expected literal is copied verbatim from the design index (pre-computed against the
canonical CA schedule); none is recomputed here.
"""
from test_helpers import validate_success, TEST_USERS
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import make_petitioner_headers
from test_helpers.constants import CA_FULL_TIERS, CA_WIDE_TIER

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Shared composite: canonical CA contested case in DISCOVERY, two children, both
# disclosures VERIFIED (petitioner net 600000, respondent net 300000), declared
# gross 800000/400000, plan PROPOSED 110/255. Reused by the dual-variant CHILD
# and SPOUSAL divergence instances.
# ---------------------------------------------------------------------------
def _setup_divergence_case(children=2, full_tiers=True, with_plan=True):
    tiers = [dict(t) for t in CA_FULL_TIERS] if full_tiers else [dict(t) for t in CA_WIDE_TIER]
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000,
                                       children=children, tiers=tiers)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    FX.verified_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                          gross_monthly_income_cents=720000, tax_withholding_cents=90000,
                          mandatory_retirement_cents=20000, health_insurance_cents=10000)
    FX.verified_disclosure(res["id"], case["id"], "u-res", "RESPONDENT",
                          gross_monthly_income_cents=360000, tax_withholding_cents=45000,
                          mandatory_retirement_cents=10000, health_insurance_cents=5000)
    plan = None
    if with_plan:
        plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    return ctx, plan


# =========================================================================
# Rule: dual_variant_calc — instance child_support_temporary_vs_final_divergence
# =========================================================================
def test_child_support_temporary_uses_declared_gross(api):
    """PRD §3.6: "Under the `TEMPORARY` variant, the combined income is the sum of both
    parties' declared `gross_monthly_income_cents` (taken from the `Party` records), and
    the parenting-time offset uses the plan's current overnight split".

    Declared 800000+400000=1200000 -> tier2 base 150000; payor share 800000/1200000
    -> 100000... actually 2 children scale 150000*1.5=225000, proration *0.6667=150000.

    Design: Difficulty/dual_variant_calc/child_support_temporary_vs_final_divergence
    """
    ctx, _ = _setup_divergence_case(children=2)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 150000


def test_child_support_final_uses_verified_net_and_diverges(api):
    """PRD §3.6: "Under the `FINAL` variant, the combined income is the sum of both
    parties' verified `net_monthly_income_cents` (taken from their verified disclosures —
    net figures, not gross) ... the formula is identical but the result differs
    materially."

    Net 600000+300000=900000 -> tier1 base 100000.

    Design: Difficulty/dual_variant_calc/child_support_temporary_vs_final_divergence
    """
    ctx, _ = _setup_divergence_case(children=2)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    temp = validate_success(api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK), 201)
    final = validate_success(api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "FINAL"), CLERK), 201)
    assert final["monthly_amount_cents"] == 100000
    assert temp["monthly_amount_cents"] != final["monthly_amount_cents"]


# =========================================================================
# Rule: dual_variant_calc — instance spousal_support_temporary_vs_final_divergence
# =========================================================================
def test_spousal_support_temporary_uses_declared_gross(api):
    """PRD §3.6: "The gross obligation is the schedule's `spousal_payor_pct` multiplied
    by the payor's income, minus the schedule's `spousal_payee_offset_pct` multiplied by
    the payee's income, rounded half up to whole cents ... under `TEMPORARY`, the payor
    and payee incomes are the declared gross `gross_monthly_income_cents` from the
    `Party` records".

    0.40*800000 - 0.50*400000 = 120000.

    Design: Difficulty/dual_variant_calc/spousal_support_temporary_vs_final_divergence
    """
    ctx, _ = _setup_divergence_case(children=0, full_tiers=False, with_plan=False)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "SPOUSAL", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 120000


def test_spousal_support_final_uses_verified_net_and_diverges(api):
    """PRD §3.6: "under `FINAL`, they are the verified `net_monthly_income_cents` from
    the parties' disclosures, which are net figures and therefore shrink the obligation
    relative to the temporary gross-based figure."

    0.40*600000 - 0.50*300000 = 90000.

    Design: Difficulty/dual_variant_calc/spousal_support_temporary_vs_final_divergence
    """
    ctx, _ = _setup_divergence_case(children=0, full_tiers=False, with_plan=False)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    temp = validate_success(api.create_support_order(
        F.support_order_payload(case["id"], "SPOUSAL", pet["id"], res["id"], "TEMPORARY"), CLERK), 201)
    final = validate_success(api.create_support_order(
        F.support_order_payload(case["id"], "SPOUSAL", pet["id"], res["id"], "FINAL"), CLERK), 201)
    assert final["monthly_amount_cents"] == 90000
    assert temp["monthly_amount_cents"] != final["monthly_amount_cents"]


# =========================================================================
# Rule: combinatorial_formula — instance child_support_tiered_proration_mode_a
# =========================================================================
def _setup_mode_a_default_case():
    """CA default case in DEFAULT_PENDING; declared gross 800000/400000; 2 children;
    plan 110/255 (payor=petitioner, time_pct 0.3014 < 0.40, no offset)."""
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000, children=2,
                                   tiers=[dict(t) for t in CA_FULL_TIERS])
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    return ctx


def test_child_support_mode_a_tier_proration_amount(api):
    """PRD §3.6: "If there is more than one child, the base is scaled up to the tier's
    `base_cents_one_child` multiplied by the quantity one plus `marginal_pct_per_extra_child`
    times the number of extra children ... rounded half up to whole cents. The obligation
    is then prorated by the payor's income share: the payor's income divided by the
    combined income, multiplied by the scaled base, rounded half up to whole cents."

    Tier2 base 150000, 2 children -> 150000*1.5=225000, payor share 800000/1200000
    -> round(225000*0.6667)=150000.

    Design: Difficulty/combinatorial_formula/child_support_tiered_proration_mode_a
    """
    ctx = _setup_mode_a_default_case()
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 150000


def test_child_support_mode_a_persists_calculated_status(api):
    """PRD §3.6: "A newly created order enters `CALCULATED` status and counts toward the
    case ledger only once it becomes `ACTIVE`."

    Re-fetch confirms the computed 150000 obligation is persisted in CALCULATED state.

    Design: Difficulty/combinatorial_formula/child_support_tiered_proration_mode_a
    """
    ctx = _setup_mode_a_default_case()
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    created = validate_success(api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK), 201)
    fetched = validate_success(api.get_support_order(created["id"], CLERK), 200)
    assert fetched["monthly_amount_cents"] == 150000
    assert fetched["status"] == "CALCULATED"


# =========================================================================
# Rule: combinatorial_formula — instance net_disposable_income_pinned_order_mode_b
# =========================================================================
def _setup_mode_b_disclosure():
    """CA default case DEFAULT_PENDING with a petitioner DRAFT disclosure
    gross=720000, tax=90000, retire=20000, health=10000."""
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000, with_respondent=False)
    case, pet = ctx["case"], ctx["pet"]
    fd = FX.create_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                              gross_monthly_income_cents=720000, tax_withholding_cents=90000,
                              mandatory_retirement_cents=20000, health_insurance_cents=10000)
    return case, pet, fd


def test_net_disposable_income_pinned_order_value(api):
    """PRD §3.3: "it first sums the three deduction lines `tax_withholding_cents`,
    `mandatory_retirement_cents`, and `health_insurance_cents` in that field order, then
    subtracts that total from `gross_monthly_income_cents`, then floors the result at 0
    cents, storing the outcome in `net_monthly_income_cents`."

    720000 - (90000+20000+10000) = 600000.

    Design: Difficulty/combinatorial_formula/net_disposable_income_pinned_order_mode_b
    """
    case, pet, fd = _setup_mode_b_disclosure()
    resp = api.submit_financial_disclosure(fd["id"], make_petitioner_headers("u-pet"))
    data = validate_success(resp, 200)
    assert data["net_monthly_income_cents"] == 600000


def test_net_disposable_income_submit_transitions_to_submitted(api):
    """PRD §3.3: "Submitting a disclosure advances it from `DRAFT` to `SUBMITTED`. ...
    At submission, the system computes net disposable income".

    Design: Difficulty/combinatorial_formula/net_disposable_income_pinned_order_mode_b
    """
    case, pet, fd = _setup_mode_b_disclosure()
    data = validate_success(
        api.submit_financial_disclosure(fd["id"], make_petitioner_headers("u-pet")), 200)
    assert data["status"] == "SUBMITTED"


# =========================================================================
# Rule: boundary_precision_check — instance shared_custody_offset_at_exact_40pct_boundary
# =========================================================================
def _setup_boundary_case():
    """CA default case; 1 child; declared gross 400000/400000 (combined 800000 ->
    tier1 base 100000); plan 146/219 -> payor=petitioner time_pct 146/365 = 0.40."""
    ctx = FX.setup_default_pending(pet_gross=400000, res_gross=400000, children=1)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 146, 219)
    return ctx, plan


def test_parenting_time_pct_at_exact_40pct_boundary(api):
    """PRD §3.4: "the system computes `petitioner_time_pct` as the petitioner's overnights
    divided by 365, rounded half up to four decimal places".

    146 / 365 = 0.4000.

    Design: Difficulty/boundary_precision_check/shared_custody_offset_at_exact_40pct_boundary
    """
    ctx, plan = _setup_boundary_case()
    fetched = validate_success(api.get_parenting_plan(plan["id"], CLERK), 200)
    assert fetched["petitioner_time_pct"] == 0.4


def test_shared_custody_offset_applies_at_exact_threshold(api):
    """PRD §3.6: "if that payor time fraction is at or above the schedule's
    `shared_custody_threshold_pct` (at or above, not strictly above), the obligation is
    reduced by multiplying it by the quantity one minus the payor's time fraction, again
    rounded half up to whole cents."

    Base 100000, payor share 400000/800000 -> 50000; payor_time_pct 0.40 >= 0.40 so
    offset applies: 50000*(1-0.40)=30000.

    Design: Difficulty/boundary_precision_check/shared_custody_offset_at_exact_40pct_boundary
    """
    ctx, plan = _setup_boundary_case()
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 30000


# =========================================================================
# Rule: boundary_precision_check — instance zero_children_child_support_is_zero
# =========================================================================
def _setup_zero_children_case():
    """CA default case; declared gross 800000/400000; ZERO children; plan 110/255."""
    ctx = FX.setup_default_pending(
        pet_gross=800000, res_gross=400000, children=0,
        tiers=[{"min_combined_monthly_cents": 0, "max_combined_monthly_cents": 1999999,
                "base_cents_one_child": 150000, "marginal_pct_per_extra_child": 0.50}])
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    return ctx


def test_zero_children_child_support_is_zero_on_create(api):
    """PRD §3.6: "The child count is the number of `Child` rows on the case. If there are
    no children, the `monthly_amount_cents` is 0 and computation stops."

    Design: Difficulty/boundary_precision_check/zero_children_child_support_is_zero
    """
    ctx = _setup_zero_children_case()
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 0


def test_zero_children_child_support_is_zero_when_fetched(api):
    """PRD §3.6: "If there are no children, the `monthly_amount_cents` is 0 and
    computation stops."

    Re-fetch confirms the zero obligation is persisted.

    Design: Difficulty/boundary_precision_check/zero_children_child_support_is_zero
    """
    ctx = _setup_zero_children_case()
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    created = validate_success(api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY"), CLERK), 201)
    fetched = validate_success(api.get_support_order(created["id"], CLERK), 200)
    assert fetched["monthly_amount_cents"] == 0


# =========================================================================
# Queue B (Corner) — calculations
# =========================================================================
def test_spousal_support_indefinite_term_at_long_marriage_boundary(api):
    """PRD §3.6: "if the case's `marriage_months` is at or above the schedule's
    `long_marriage_months` (at or above, not strictly above), the `support_term_months`
    is set to the sentinel 0, meaning an indefinite term".

    marriage_months 120 >= 120 -> term 0; obligation 0.40*800000 - 0.50*400000 = 120000.

    Design: Corner/calculations/spousal_support_indefinite_term_at_long_marriage_boundary
    """
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000,
                                   marriage_months=120)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "SPOUSAL", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["support_term_months"] == 0
    assert data["monthly_amount_cents"] == 120000


def test_spousal_support_floored_at_zero_when_payee_richer(api):
    """PRD §3.6: "the stored `monthly_amount_cents` is the greater of 0 and that gross
    obligation, so it is never negative ... otherwise it is the floor of `marriage_months`
    divided by 2".

    0.40*300000 - 0.50*500000 = -130000 -> floored to 0; term floor(60/2)=30.

    Design: Corner/calculations/spousal_support_floored_at_zero_when_payee_richer
    """
    ctx = FX.setup_default_pending(pet_gross=300000, res_gross=500000, marriage_months=60)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "SPOUSAL", pet["id"], res["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 0
    assert data["support_term_months"] == 30


def test_child_support_tier_boundary_inclusive_lower_tier(api):
    """PRD §3.6: "Both band endpoints are inclusive, and a value equal to a tier's
    maximum belongs to that tier rather than the next (ties resolve to the lower tier)."

    Combined 499999+500000=999999 == tier1 max -> tier1 base 100000; 1 child;
    payor=respondent share 500000/999999 -> 50000 (payor_time_pct 0.2329 < 0.40, no offset).

    Design: Corner/calculations/child_support_tier_boundary_inclusive_lower_tier
    """
    ctx = FX.setup_default_pending(
        pet_gross=499999, res_gross=500000, children=1,
        tiers=[{"min_combined_monthly_cents": 0, "max_combined_monthly_cents": 999999,
                "base_cents_one_child": 100000, "marginal_pct_per_extra_child": 0.50},
               {"min_combined_monthly_cents": 1000000, "max_combined_monthly_cents": 99999999,
                "base_cents_one_child": 200000, "marginal_pct_per_extra_child": 0.50}])
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 280, 85)
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", res["id"], pet["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 50000
