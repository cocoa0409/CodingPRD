"""Billing calculations: annual fee proration, resale split, special-assessment
distribution, the delinquency late-charge engine, owner balance.

Difficulty: dual_variant_calc (provisional vs resale split; SIMPLE vs COMPOUNDING),
combinatorial_formula (round-then-distribute). Corner: remainder tie-break,
owner open_balance.
"""
from test_helpers import (
    get_success_data,
    create_resort, create_owner, create_active_contract,
    create_issued_invoice, get_annual_invoice, get_special_assessment_invoice,
    setup_lien_case,
    create_resale_transfer_payload, create_special_assessment_payload, levy_payload,
    set_clock,
    TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]
_RA = TEST_USERS["resale_agent_headers"]
_CO = TEST_USERS["compliance_officer_headers"]


# =========================================================================== #
# Difficulty: dual_variant_calc — provisional full-year vs resale-split
# =========================================================================== #
def test_annual_invoice_provisional_full_year_amount(api):
    """PRD §3.7: "The provisional full-year annual fee is computed as the contract's
    `annual_points_allotment` divided by 1000, multiplied by the resort's
    `annual_fee_cents_per_1000_points`, with the result taken as the ceiling to a
    whole number of cents".

    Design: Difficulty/dual_variant_calc/maintenance_fee_provisional_vs_resale_split
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    invoice = create_issued_invoice(resort, contract, use_year=2026)
    # 10000/1000 * 20000 = 200000.
    assert invoice["amount_cents"] == 200000, \
        f"expected provisional amount 200000, got {invoice['amount_cents']}"


def test_resale_completion_splits_annual_invoice_seller_and_buyer(api):
    """PRD §3.9: "the seller's share is the full-year figure multiplied by `transfer_day_of_year`,
    divided by 365, floored to whole cents; the buyer's share is the full-year
    figure minus the seller's share, so that the remainder absorbs any rounding and
    the two parts sum back exactly to the original full-year figure. The seller's
    existing `ANNUAL` invoice has its `amount_cents` reduced to the seller's share,
    and a new `ISSUED` buyer invoice is created carrying the buyer's share."

    Design: Difficulty/dual_variant_calc/maintenance_fee_provisional_vs_resale_split
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000,
                           rescission_days=7)
    seller = create_owner(resort["id"], full_name="Seller", email="seller@x.com")
    buyer = create_owner(resort["id"], full_name="Buyer", email="buyer@x.com")
    contract = create_active_contract(resort["id"], seller["id"], annual_points_allotment=10000)
    invoice = create_issued_invoice(resort, contract, use_year=2026)
    assert invoice["amount_cents"] == 200000

    transfer = get_success_data(api.create_resale_transfer(
        create_resale_transfer_payload(contract["id"], buyer["id"], 2026, 120), _RA))
    set_clock(resort["id"], "2026-01-20T00:00:00Z")  # elapse the transfer's cooling-off window
    completed = get_success_data(api.complete_resale_transfer(transfer["id"], _RA))

    # seller_share = floor(200000 * 120 / 365) = floor(65753.42..) = 65753.
    seller_inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert seller_inv["amount_cents"] == 65753, \
        f"seller share floor(200000*120/365)==65753, got {seller_inv['amount_cents']}"

    # buyer_share = 200000 - 65753 = 134247 on the new buyer contract's ANNUAL invoice.
    buyer_inv = get_annual_invoice(completed["new_contract_id"], 2026)
    assert buyer_inv["amount_cents"] == 134247, \
        f"buyer share 200000-65753==134247, got {buyer_inv['amount_cents']}"
    assert seller_inv["amount_cents"] + buyer_inv["amount_cents"] == 200000, "split must conserve"


# =========================================================================== #
# Difficulty: dual_variant_calc — SIMPLE vs COMPOUNDING late charge
# =========================================================================== #
def test_compounding_late_charge_three_escalations(api):
    """PRD §3.8: "Under the `COMPOUNDING` basis, each period instead charges the late rate of 0.05
    against the running balance — the invoice's `amount_cents` plus its
    already-accumulated `late_charge_cents` — again floored to whole cents and
    added to `late_charge_cents`."
    PRD §3.8: "It carries an `escalation_periods` counter starting at 0 and a `late_charge_basis`
    that selects the late-charge formula, defaulting to `COMPOUNDING` but settable
    to `SIMPLE`."

    Design: Difficulty/dual_variant_calc/delinquency_late_charge_simple_vs_compounding
    """
    resort, owner, contract, invoice, case = setup_lien_case(escalations=1)
    assert case["late_charge_basis"] == "COMPOUNDING", \
        f"default basis must be COMPOUNDING, got {case['late_charge_basis']}"
    # Already escalated once in setup_lien_case (period 1). Escalate two more -> 3 total.
    get_success_data(api.escalate_delinquency_case(case["id"], _CO))
    get_success_data(api.escalate_delinquency_case(case["id"], _CO))

    # amount_cents=200000. COMPOUNDING:
    #  p1: floor(200000*0.05)=10000 -> 10000
    #  p2: floor((200000+10000)*0.05)=10500 -> 20500
    #  p3: floor((200000+20500)*0.05)=11025 -> 31525
    inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv["late_charge_cents"] == 31525, \
        f"COMPOUNDING three periods == 31525, got {inv['late_charge_cents']}"


def test_late_charge_first_period_equals_flat_rate(api):
    """PRD §3.8: "Under the `COMPOUNDING` basis, each period instead charges the late rate of 0.05
    against the running balance — the invoice's `amount_cents` plus its
    already-accumulated `late_charge_cents` — again floored to whole cents and
    added to `late_charge_cents`."
    PRD §3.8: "Each escalation increments `escalation_periods` by one and applies the late-charge
    engine to each of the contract's `DELINQUENT` invoices."

    Design: Difficulty/dual_variant_calc/delinquency_late_charge_simple_vs_compounding
    """
    # The default-basis (COMPOUNDING) case after exactly one escalation:
    # late_charge_cents = floor((200000 + 0) * 0.05) = 10000, escalation_periods = 1.
    resort, owner, contract, invoice, case = setup_lien_case(escalations=1)
    assert case["escalation_periods"] == 1, \
        f"one escalation -> escalation_periods 1, got {case['escalation_periods']}"
    inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv["late_charge_cents"] == 10000, \
        f"first period floor(200000*0.05)==10000, got {inv['late_charge_cents']}"


# =========================================================================== #
# Difficulty: combinatorial_formula — special assessment round-then-distribute
# =========================================================================== #
def test_special_assessment_round_then_distribute_two_contracts(api):
    """PRD §3.7: "for each contract taking the exact proportional share (the `total_amount_cents`
    multiplied by that contract's basis, divided by the total basis) and flooring it
    to whole cents. The cents left over after flooring — the `total_amount_cents`
    minus the sum of the floored shares — are then handed out one extra cent at a
    time to contracts ordered by the largest fractional remainder of their exact
    share first, with ties broken by the earlier contract `created_at`."

    Design: Difficulty/combinatorial_formula/special_assessment_round_then_distribute
    """
    from test_helpers import create_contract
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner_a = create_owner(resort["id"], full_name="OA", email="oa@x.com")
    owner_b = create_owner(resort["id"], full_name="OB", email="ob@x.com")
    # Create A then B (B wins the leftover cent by the larger fractional remainder).
    ca = create_contract(resort["id"], owner_a["id"], annual_points_allotment=10000)
    cb = create_contract(resort["id"], owner_b["id"], annual_points_allotment=20000)
    set_clock(resort["id"], "2026-01-08T00:00:00Z")
    get_success_data(api.activate_contract(ca["id"], _RM))
    get_success_data(api.activate_contract(cb["id"], _RM))

    sa = get_success_data(api.create_special_assessment(
        create_special_assessment_payload(resort["id"], 100000, 2026), _RM))
    get_success_data(api.levy_special_assessment(sa["id"], levy_payload("2026-04-01T00:00:00Z"), _RM))

    # total_basis=30000. A: 100000*10000/30000=33333.33 -> floor 33333 (rem .33).
    # B: 100000*20000/30000=66666.67 -> floor 66666 (rem .67). leftover 1 -> B (larger rem).
    inv_a = get_special_assessment_invoice(ca["id"], sa["id"])
    inv_b = get_special_assessment_invoice(cb["id"], sa["id"])
    assert inv_a["amount_cents"] == 33333, f"A expected 33333, got {inv_a['amount_cents']}"
    assert inv_b["amount_cents"] == 66667, f"B expected 66667, got {inv_b['amount_cents']}"
    assert inv_a["amount_cents"] + inv_b["amount_cents"] == 100000, "must conserve"


def test_special_assessment_exact_proportional_split_no_remainder(api):
    """PRD §3.7: "The distribution is computed by first summing every active
    contract's points basis, then for each contract taking the exact proportional
    share (the `total_amount_cents` multiplied by that contract's basis, divided by
    the total basis) and flooring it to whole cents."

    Design: Difficulty/combinatorial_formula/special_assessment_round_then_distribute
    """
    from test_helpers import create_contract
    # Two equal-basis contracts splitting an evenly-divisible total: each share is
    # exact (no leftover cent to distribute).
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    oa = create_owner(resort["id"], full_name="OA", email="oa@x.com")
    ob = create_owner(resort["id"], full_name="OB", email="ob@x.com")
    ca = create_contract(resort["id"], oa["id"], annual_points_allotment=10000)
    cb = create_contract(resort["id"], ob["id"], annual_points_allotment=10000)
    set_clock(resort["id"], "2026-01-08T00:00:00Z")
    get_success_data(api.activate_contract(ca["id"], _RM))
    get_success_data(api.activate_contract(cb["id"], _RM))
    sa = get_success_data(api.create_special_assessment(
        create_special_assessment_payload(resort["id"], 100000, 2026), _RM))
    get_success_data(api.levy_special_assessment(sa["id"], levy_payload("2026-04-01T00:00:00Z"), _RM))

    inv_a = get_special_assessment_invoice(ca["id"], sa["id"])
    inv_b = get_special_assessment_invoice(cb["id"], sa["id"])
    assert inv_a["amount_cents"] == 50000, f"A expected 50000, got {inv_a['amount_cents']}"
    assert inv_b["amount_cents"] == 50000, f"B expected 50000, got {inv_b['amount_cents']}"


# =========================================================================== #
# Corner: calculations — remainder tie-break by created_at
# =========================================================================== #
def test_special_assessment_remainder_tiebreak_by_created_at(api):
    """PRD §3.7: "The cents left over after flooring — the `total_amount_cents`
    minus the sum of the floored shares — are then handed out one extra cent at a
    time to contracts ordered by the largest fractional remainder of their exact
    share first, with ties broken by the earlier contract `created_at`."

    Design: Corner/calculations/special_assessment_remainder_tiebreak_by_created_at
    """
    from test_helpers import create_contract
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    oa = create_owner(resort["id"], full_name="OA", email="oa@x.com")
    ob = create_owner(resort["id"], full_name="OB", email="ob@x.com")
    oc = create_owner(resort["id"], full_name="OC", email="oc@x.com")
    ca = create_contract(resort["id"], oa["id"], annual_points_allotment=10000)
    cb = create_contract(resort["id"], ob["id"], annual_points_allotment=10000)
    cc = create_contract(resort["id"], oc["id"], annual_points_allotment=10000)
    set_clock(resort["id"], "2026-01-08T00:00:00Z")
    get_success_data(api.activate_contract(ca["id"], _RM))
    get_success_data(api.activate_contract(cb["id"], _RM))
    get_success_data(api.activate_contract(cc["id"], _RM))

    sa = get_success_data(api.create_special_assessment(
        create_special_assessment_payload(resort["id"], 100000, 2026), _RM))
    get_success_data(api.levy_special_assessment(sa["id"], levy_payload("2026-04-01T00:00:00Z"), _RM))

    # Three equal bases: each floors to 33333 (rem 1 cent total). Equal fractional
    # parts -> tie broken by earliest created_at -> A gets the extra cent.
    inv_a = get_special_assessment_invoice(ca["id"], sa["id"])
    inv_b = get_special_assessment_invoice(cb["id"], sa["id"])
    inv_c = get_special_assessment_invoice(cc["id"], sa["id"])
    assert inv_a["amount_cents"] == 33334, f"A (earliest) expected 33334, got {inv_a['amount_cents']}"
    assert inv_b["amount_cents"] == 33333, f"B expected 33333, got {inv_b['amount_cents']}"
    assert inv_c["amount_cents"] == 33333, f"C expected 33333, got {inv_c['amount_cents']}"
    assert inv_a["amount_cents"] + inv_b["amount_cents"] + inv_c["amount_cents"] == 100000


# =========================================================================== #
# Corner: entities — owner open_balance from issued invoices
# =========================================================================== #
def test_owner_open_balance_from_issued_invoice(api):
    """PRD §3.1: "`open_balance_cents`, is the sum of `amount_due_cents` across all of that owner's
    invoices whose status is either `ISSUED` or `DELINQUENT`."
    PRD §3.1: "otherwise, if any of the owner's invoices is `DELINQUENT`, the owner is
    `DELINQUENT`; otherwise the owner is `GOOD_STANDING`."

    Design: Corner/entities/owner_open_balance_computed_from_issued_invoices
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    create_issued_invoice(resort, contract, use_year=2026)  # 200000, ISSUED, not delinquent

    fetched = get_success_data(api.get_owner(owner["id"], _RM))
    assert fetched["open_balance_cents"] == 200000, \
        f"expected open_balance 200000, got {fetched['open_balance_cents']}"
    assert fetched["status"] == "GOOD_STANDING", \
        f"ISSUED (not delinquent) -> GOOD_STANDING, got {fetched['status']}"
