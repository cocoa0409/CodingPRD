"""Quote pricing (circular permit-on-net, per-line tax rounding) and incentive math
(federal vs utility, federal cap, stacking cap).

Translates difficulty rules combinatorial_formula and dual_variant_calc (incentive branch),
plus the calculation/cyclic corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_assessed_job,
    setup_activated_job,
    submit_federal_claim,
    create_quote_payload,
    create_incentive_claim_payload,
    make_homeowner_headers,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


# ─── Quote pricing — circular permit-on-net (mode c) ─────────────────────

def test_quote_total_circular_permit_on_net():
    """PRD §3.4: "The `permit_fee_cents` is keyed on that post-discount net: when the
    net is at least 150,000 the permit fee is 20,000; otherwise, when it is at least 90,000
    the permit fee is 15,000; otherwise the permit fee is 12,000."
    PRD §3.4: "The `quote_total_cents` is the net after discount plus `tax_cents` plus
    `permit_fee_cents`."

    Design: Difficulty/combinatorial_formula/quote_total_circular_permit_on_net
    """
    ctx = setup_assessed_job()
    quote = validate_success(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"], labor_cents=120000, parts_line_cents=[60000, 5000]),
        COORDINATOR), 201)
    # base 185000; discount 5% -> 9250; net 175750; permit 20000 (>=150000);
    # tax: round(.0825*60000)=4950 + round(.0825*5000)=413 = 5363; total 201113
    assert quote["base_subtotal_cents"] == 185000
    assert quote["discount_cents"] == 9250
    assert quote["permit_fee_cents"] == 20000
    assert quote["tax_cents"] == 5363
    assert quote["quote_total_cents"] == 201113


def test_quote_discount_tier_keyed_on_subtotal():
    """PRD §3.4: "A volume discount is keyed on that subtotal. When `base_subtotal_cents`
    is at least 200,000 the discount rate is 10%; otherwise, when it is at least 100,000 the
    discount rate is 5%; otherwise the discount rate is 0%."

    Design: Difficulty/combinatorial_formula/quote_total_circular_permit_on_net
    """
    ctx = setup_assessed_job()
    # base 185000 is in [100000, 200000) -> 5% -> discount 9250
    quote = validate_success(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"], labor_cents=120000, parts_line_cents=[60000, 5000]),
        COORDINATOR), 201)
    assert quote["base_subtotal_cents"] == 185000
    assert quote["discount_cents"] == 9250


# ─── Quote tax — per-line rounding order (mode b) ────────────────────────

def test_quote_tax_per_line_rounding_order():
    """PRD §3.4: "the tax rate of 8.25% (0.0825) is applied to each individual entry in
    `parts_line_cents`, each per-line result is rounded half up to whole cents, and only
    then are the rounded per-line amounts summed."

    Design: Difficulty/combinatorial_formula/quote_tax_per_line_rounding_order
    """
    ctx = setup_assessed_job()
    # parts [5050,5050,5050]: round(.0825*5050)=round(416.625)=417 per line; 417*3=1251
    quote = validate_success(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"], labor_cents=10000, parts_line_cents=[5050, 5050, 5050]),
        COORDINATOR), 201)
    assert quote["tax_cents"] == 1251


def test_quote_tax_labor_not_taxed():
    """PRD §3.4: "The sales tax, stored as `tax_cents`, is computed over the parts lines
    only — labor is never taxed."

    Design: Difficulty/combinatorial_formula/quote_tax_per_line_rounding_order
    """
    ctx = setup_assessed_job()
    # Same parts as above but very different labor; tax depends only on parts -> still 1251
    quote = validate_success(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"], labor_cents=99000, parts_line_cents=[5050, 5050, 5050]),
        COORDINATOR), 201)
    assert quote["tax_cents"] == 1251


# ─── Quote revision loop (corner cyclic) ─────────────────────────────────

def test_quote_revision_recomputes_totals_at_discount_boundary():
    """PRD §3.4: "a coordinator may revise it, supplying a fresh `labor_cents` and/or
    `parts_line_cents`, which moves it from `REJECTED` back to `DRAFT` and recomputes all
    totals from the new inputs."
    PRD §3.4: "(The boundary is inclusive: a subtotal of exactly 200,000 selects the 10%
    tier, not the 5% tier.)"

    Design: Corner/state_machines/quote_revision_loop_back_to_draft
    """
    ctx = setup_assessed_job()
    quote = get_success_data(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"], labor_cents=50000, parts_line_cents=[10000]),
        COORDINATOR))
    get_success_data(api_client.send_quote(quote["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.reject_quote(quote["id"], ho_headers))

    revised = validate_success(api_client.revise_quote(
        quote["id"], {"labor_cents": 100000, "parts_line_cents": [100000]}, COORDINATOR), 200)
    # base 200000 -> 10% discount 20000; net 180000 -> permit 20000 (>=150000);
    # tax round(.0825*100000)=8250; total 180000+8250+20000 = 208250
    assert revised["status"] == "DRAFT"
    assert revised["base_subtotal_cents"] == 200000
    assert revised["discount_cents"] == 20000
    assert revised["permit_fee_cents"] == 20000
    assert revised["tax_cents"] == 8250
    assert revised["quote_total_cents"] == 208250


# ─── Incentive — federal vs utility divergence ───────────────────────────

def test_incentive_federal_vs_utility_diverge():
    """PRD §3.8: "For a `FEDERAL_45W` claim, the award is 30% of the `eligible_cost_cents`,
    rounded half up, but never more than 100,000 cents (a one-thousand-dollar cap)."
    PRD §3.8: "For a `UTILITY_REBATE` claim, the system starts from a base: 50,000 cents
    when the `utility_program_tier` is `PREMIUM`, otherwise 25,000 cents for `BASIC`. It
    then adds a panel-upgrade adder of 30,000 cents when `includes_panel_upgrade` is true,
    and 0 otherwise."

    Design: Difficulty/dual_variant_calc/incentive_federal_vs_utility_diverge
    """
    ctx = setup_activated_job()
    fed = validate_success(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "FEDERAL_45W", 195750), COORDINATOR), 201)
    # min(round(0.30*195750)=58725, 100000) = 58725
    assert fed["award_cents"] == 58725

    util = validate_success(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "UTILITY_REBATE", 195750,
                                       utility_program_tier="PREMIUM", includes_panel_upgrade=True),
        COORDINATOR), 201)
    # PREMIUM 50000 + adder 30000 = 80000; no qualifying federal sibling (fed still DRAFT)
    assert util["award_cents"] == 80000


def test_incentive_federal_branch_ignores_tier_and_adder():
    """PRD §3.8: "The federal branch ignores the tier, the panel-upgrade adder, and the
    stacking cap entirely — it is simply the smaller of the rounded 30% figure and the
    100,000-cent cap."

    Design: Difficulty/dual_variant_calc/incentive_federal_vs_utility_diverge
    """
    ctx = setup_activated_job()
    fed = validate_success(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "FEDERAL_45W", 195750), COORDINATOR), 201)
    assert fed["award_cents"] == 58725


def test_federal_cap_binds_at_high_eligible_cost():
    """PRD §3.8: "the award is 30% of the `eligible_cost_cents`, rounded half up, but never
    more than 100,000 cents (a one-thousand-dollar cap)."

    Design: Corner/calculations/federal_45w_cap_applied_at_high_eligible_cost
    """
    ctx = setup_activated_job()
    fed = validate_success(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "FEDERAL_45W", 400000), COORDINATOR), 201)
    # min(round(0.30*400000)=120000, 100000) = 100000
    assert fed["award_cents"] == 100000


def test_utility_rebate_capped_by_federal_sibling_stacking():
    """PRD §3.8: "the system computes a cap of 80% of the `eligible_cost_cents`, rounded
    half up, and looks up the federal award already in play on this same job — that is, the
    `award_cents` of this job's `FEDERAL_45W` claim whose status is `SUBMITTED` or `PAID`"
    PRD §3.8: "the utility `award_cents` becomes the cap minus the existing federal award,
    but never below 0."

    Design: Corner/calculations/utility_rebate_capped_by_federal_sibling_stacking
    """
    ctx = setup_activated_job()
    # Federal claim eligible 100000 -> award 30000, advanced to SUBMITTED
    submit_federal_claim(ctx, 100000)
    util = validate_success(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "UTILITY_REBATE", 100000,
                                       utility_program_tier="PREMIUM", includes_panel_upgrade=True),
        COORDINATOR), 201)
    # util_raw 80000; stack_cap round(0.80*100000)=80000; fed 30000 + 80000 > 80000
    # -> award = 80000 - 30000 = 50000
    assert util["award_cents"] == 50000
