"""Queue A (depth) — TTP and subsidy calculation tests at lease-up.

Each test builds the full lease-up precondition graph, triggers POST
/hap-contracts, and asserts the computed monetary fields against the
literal expected values pinned in the design index.
"""
from test_helpers import (
    api_client, validate_success, setup_leaseup_ready, CASEWORKER,
    create_hap_contract_payload,
)


def _lease_up(scenario, contract_rent_cents):
    return api_client.create_hap_contract(
        create_hap_contract_payload(
            scenario["voucher"]["id"], scenario["unit"]["id"],
            contract_rent_cents, scenario["voucher_version"],
        ),
        CASEWORKER,
    )


# ── rule: dual_variant_calc ────────────────────────────────


def test_ttp_takes_max_of_thirty_pct_adjusted_floor():
    """PRD §3.5: "It is the largest of three candidates: thirty percent of the
    household's monthly adjusted income; ten percent of the household's monthly
    gross income; and a statutory minimum rent of 50 dollars (5,000 cents)."
    Family gross 1,800,000 with 2 dependents -> adjusted 1,704,000; 30% of
    monthly adjusted (42,600) is the binding floor, subsidy 47,400.

    Design: Difficulty/dual_variant_calc/ttp_max_floor_30pct_vs_10pct_gross
    """
    scenario = setup_leaseup_ready(
        region_code="METRO_NORTH", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    contract = validate_success(_lease_up(scenario, 90000), 201)
    assert contract["total_tenant_payment_cents"] == 42600
    assert contract["hap_subsidy_cents"] == 47400


def test_subsidy_capped_when_contract_exceeds_payment_standard():
    """PRD §3.5: "when the contract rent exceeds the payment standard the
    capped rent equals the payment standard and the tenant absorbs the overage
    above it. The HAP subsidy is the capped rent minus the total tenant payment,
    floored at zero so it is never negative." Family of 4 gross 3,000,000 ->
    TTP 75,000; ps 95,000 caps contract 120,000 -> subsidy 20,000, burden 100,000.

    Design: Difficulty/dual_variant_calc/subsidy_capped_by_payment_standard_vs_gross
    """
    scenario = setup_leaseup_ready(
        region_code="OPP_AREA", family_size=4, annual_income_cents=3000000,
        bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=120000, comparable_rent_cents=120000,
    )
    contract = validate_success(_lease_up(scenario, 120000), 201)
    assert contract["total_tenant_payment_cents"] == 75000
    assert contract["hap_subsidy_cents"] == 20000
    assert contract["tenant_rent_burden_cents"] == 100000


# ── rule: combinatorial_formula ────────────────────────────


def test_ttp_ten_pct_gross_is_binding_floor():
    """PRD §3.5: "the second candidate is 0.10 of monthly gross income. The
    system takes the maximum of these three candidates and rounds that maximum
    half up to the nearest whole cent." A large childcare deduction drops
    adjusted to 600,000 so 10%-of-gross (25,000) beats 30%-adjusted (15,000);
    subsidy 35,000.

    Design: Difficulty/combinatorial_formula/ttp_three_input_nonlinear_max_floor
    """
    scenario = setup_leaseup_ready(
        region_code="WEST_END", family_size=2, annual_income_cents=3000000,
        childcare_expense_cents=2250000, bedroom_size=1,
        amount_cents=60000, fmr_cents=60000,
        asking_rent_cents=60000, comparable_rent_cents=60000,
    )
    contract = validate_success(_lease_up(scenario, 60000), 201)
    assert contract["total_tenant_payment_cents"] == 25000
    assert contract["hap_subsidy_cents"] == 35000


def test_subsidy_eval_order_cap_then_subtract_then_floor():
    """PRD §3.5: "The capped rent is the lesser of the contract_rent_cents and
    that payment-standard amount ... The HAP subsidy is the capped rent minus
    the total tenant payment, floored at zero ... Finally the contract's
    tenant_rent_burden_cents is the contract_rent_cents minus the
    hap_subsidy_cents." Single-person studio gross 600,000 -> TTP 15,000;
    contract 39,000 below ps 40,000 -> subsidy 24,000, burden 15,000.

    Design: Difficulty/combinatorial_formula/subsidy_pinned_eval_order_cap_then_subtract_then_floor
    """
    scenario = setup_leaseup_ready(
        region_code="EAST_SIDE", family_size=1, annual_income_cents=600000,
        bedroom_size=0, amount_cents=40000, fmr_cents=40000,
        asking_rent_cents=39000, comparable_rent_cents=39000,
    )
    contract = validate_success(_lease_up(scenario, 39000), 201)
    assert contract["total_tenant_payment_cents"] == 15000
    assert contract["hap_subsidy_cents"] == 24000
    assert contract["tenant_rent_burden_cents"] == 15000
