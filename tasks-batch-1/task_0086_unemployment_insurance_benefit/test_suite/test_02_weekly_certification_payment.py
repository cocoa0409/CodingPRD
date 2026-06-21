"""Weekly certification payment: payable-amount calc, the pay cascade
(balance -> employer reserves), exhaustion boundary, parallel status axes."""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_eligible_claim, make_eligible_week, make_paid_week,
    make_two_employer_eligible_claim, get_charge_for_employer,
    file_week, adjudicate_week, pay_week, set_claim_balance,
    establish_overpayment, apply_recovery, current_overpayment_version,
    assert_weekly_certification, assert_claim, assert_employer_charge,
    assert_overpayment_conserved,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]
BPO = TEST_USERS["benefit_payment_officer_headers"]


# ── Difficulty: combinatorial_formula / weekly_payable_nested_min_max_disregard ──

def test_payable_amount_nested_disregard_and_earnings(api):
    """PRD §3.5.1: "it is the larger of 5,000 cents and twenty-five percent of the
    claim's weekly_benefit_amount_cents ... Next compute the countable earnings:
    the claimant's reported_earnings_cents for the week less the disregard, but
    never below 0. The gross payable is the weekly_benefit_amount_cents less the
    countable earnings, again never below 0."

    Design: Difficulty/combinatorial_formula/weekly_payable_nested_min_max_disregard
    """
    # WBA 30000, earnings 20000: disregard=max(5000,7500)=7500; countable=12500;
    # gross=30000-12500=17500; balance 780000 -> payable 17500.
    scenario, wc = make_paid_week(reported_earnings_cents=20000)
    assert_weekly_certification(wc)
    assert wc["payable_amount_cents"] == 17500
    assert wc["payment_status"] == "PAID"
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert claim["remaining_balance_cents"] == 762500


def test_payable_amount_balance_unchanged_when_zero_payable(api):
    """PRD §3.5.1: "The gross payable is the weekly_benefit_amount_cents less the
    countable earnings, again never below 0."
    PRD §3.5: "debits the claim's remaining_balance_cents by the computed
    payable_amount_cents".

    Design: Difficulty/combinatorial_formula/weekly_payable_nested_min_max_disregard
    """
    # WBA 30000, earnings 40000: disregard 7500; countable 32500; gross
    # max(0,30000-32500)=0 -> payable 0; balance stays 780000.
    scenario, wc = make_paid_week(reported_earnings_cents=40000)
    assert wc["payable_amount_cents"] == 0
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert claim["remaining_balance_cents"] == 780000


# ── Corner: calculations / earnings_above_wba_plus_disregard_pays_zero ──

def test_earnings_above_wba_plus_disregard_pays_zero(api):
    """PRD §3.5.1: "Next compute the countable earnings: the claimant's
    reported_earnings_cents for the week less the disregard, but never below 0. The
    gross payable is the weekly_benefit_amount_cents less the countable earnings,
    again never below 0."

    Design: Corner/calculations/earnings_above_wba_plus_disregard_pays_zero
    """
    scenario, wc = make_paid_week(reported_earnings_cents=40000)
    assert wc["payable_amount_cents"] == 0
    assert wc["payment_status"] == "PAID"
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert claim["remaining_balance_cents"] == 780000


# ── Difficulty: dual_variant_calc / employer_charge_single_vs_multi_allocation_diverge ──

def test_multi_employer_charge_largest_remainder_split(api):
    """PRD §3.5.2: "its raw share is the payable_amount_cents multiplied by that
    employer's wages divided by the total base-period wages; the integer floor of
    each raw share is the employer's provisional charge in whole cents. The cents
    left over ... are distributed one cent at a time using the largest-remainder
    method, in this tie-break order: first to the employers with the largest
    fractional remainders, descending".

    Design: Difficulty/dual_variant_calc/employer_charge_single_vs_multi_allocation_diverge
    """
    # ALTERNATE WBA 11500; pay full week (no earnings). X wages 300000, Y 240000,
    # total 540000. raw_X=6388.9->6388(+1)=6389 ; raw_Y=5111.1->5111. sum 11500.
    scenario = make_two_employer_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    wc = get_success_data(api_client.get_weekly_certification(wc["id"], BPO))
    charge_x = get_charge_for_employer(scenario["employer_x"]["id"])
    charge_y = get_charge_for_employer(scenario["employer_y"]["id"])
    assert_employer_charge(charge_x)
    assert charge_x["charge_amount_cents"] == 6389
    assert charge_y["charge_amount_cents"] == 5111
    assert charge_x["charge_amount_cents"] + charge_y["charge_amount_cents"] == 11500
    assert wc["payable_amount_cents"] == 11500


def test_single_employer_charged_full_payable(api):
    """PRD §3.5.2: "When there is only a single base-period employer, that employer
    is charged the full payable_amount_cents with no remainder step."

    Design: Difficulty/dual_variant_calc/employer_charge_single_vs_multi_allocation_diverge
    """
    # STANDARD single-employer claim, WBA 30000, no earnings: payable 30000 all
    # charged to the one base-period employer.
    scenario, wc = make_paid_week(reported_earnings_cents=0)
    assert wc["payable_amount_cents"] == 30000
    charge = get_charge_for_employer(scenario["employer"]["id"])
    assert charge["charge_amount_cents"] == 30000
    assert charge["status"] == "POSTED"


# ── Difficulty: transitive_cascade / pay_week_cascades_balance_then_employer_reserve ──

def test_pay_cascades_balance_then_reserves(api):
    """PRD §3.5: "On success the system sets payment_status to PAID, debits the
    claim's remaining_balance_cents by the computed payable_amount_cents, allocates
    employer charges (Section 3.5.2), and increments the certification's version."
    PRD §3.5.2: "Posting a charge debits that employer's
    reserve_account_balance_cents by the charge_amount_cents."

    Design: Difficulty/transitive_cascade/pay_week_cascades_balance_then_employer_reserve
    """
    # MBA 270000, payable 11500 -> balance 270000-11500=258500.
    # X charged 6389 -> reserve 100000000-6389=99993611;
    # Y charged 5111 -> reserve 100000000-5111=99994889.
    scenario = make_two_employer_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    emp_x = get_success_data(api_client.get_employer(scenario["employer_x"]["id"], ADJ))
    emp_y = get_success_data(api_client.get_employer(scenario["employer_y"]["id"], ADJ))
    assert claim["remaining_balance_cents"] == 258500
    assert emp_x["reserve_account_balance_cents"] == 99993611
    assert emp_y["reserve_account_balance_cents"] == 99994889


def test_pay_creates_posted_charges_summing_to_payable(api):
    """PRD §3.5.2: "For each allocated employer the system creates an EmployerCharge
    naming the employer_id charged and the weekly_certification_id that generated
    it, with the computed charge_amount_cents, in POSTED status".
    PRD §3.5.2: "Each leftover cent raises one employer's charge by one, so the sum
    of all charge_amount_cents equals the payable_amount_cents exactly."

    Design: Difficulty/transitive_cascade/pay_week_cascades_balance_then_employer_reserve
    """
    # The third link of the chain: the debit drives creation of EmployerCharge rows
    # whose amounts (POSTED) reconcile to the week's payable_amount_cents (11500).
    scenario = make_two_employer_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    wc = get_success_data(api_client.get_weekly_certification(wc["id"], BPO))
    charge_x = get_charge_for_employer(scenario["employer_x"]["id"])
    charge_y = get_charge_for_employer(scenario["employer_y"]["id"])
    assert charge_x["status"] == "POSTED"
    assert charge_y["status"] == "POSTED"
    assert charge_x["charge_amount_cents"] + charge_y["charge_amount_cents"] == \
        wc["payable_amount_cents"] == 11500


# ── Difficulty: boundary_precision_check / claim_exhausts_at_exactly_zero_balance ──

def test_claim_exhausts_at_exactly_zero(api):
    """PRD §3.5: "If that debit drives remaining_balance_cents to exactly 0, the
    claim transitions MONETARILY_ELIGIBLE → EXHAUSTED, recomputing its balance (now
    0) and incrementing the claim's version; a payment that leaves the balance
    above 0 keeps the claim MONETARILY_ELIGIBLE. The exhausted transition fires
    only at exactly 0."

    Design: Difficulty/boundary_precision_check/claim_exhausts_at_exactly_zero_balance
    """
    # Two-quarter claim (Q4+Q3 each 130000): qualifies (total 260000, hq 130000),
    # hq 130000 -> WBA 5000, base MBA 130000. Force balance to 5000, pay one full
    # week (no earnings) -> payable 5000 -> balance 0 -> EXHAUSTED.
    scenario = make_eligible_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)])
    set_claim_balance(scenario["claim"]["id"], 5000)
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    wc = get_success_data(api_client.get_weekly_certification(wc["id"], BPO))
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert wc["payable_amount_cents"] == 5000
    assert claim["remaining_balance_cents"] == 0
    assert claim["status"] == "EXHAUSTED"


def test_claim_stays_eligible_when_balance_above_zero(api):
    """PRD §3.5: "a payment that leaves the balance above 0 keeps the claim
    MONETARILY_ELIGIBLE. The exhausted transition fires only at exactly 0."

    Design: Difficulty/boundary_precision_check/claim_exhausts_at_exactly_zero_balance
    """
    # Two-quarter claim (Q4+Q3 each 130000): qualifies, WBA 5000, base MBA 130000.
    # Force balance to 8000, pay a full week (payable 5000) -> 3000 left.
    scenario = make_eligible_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)])
    set_claim_balance(scenario["claim"]["id"], 8000)
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert claim["remaining_balance_cents"] == 3000
    assert claim["status"] == "MONETARILY_ELIGIBLE"


# ── Difficulty: non_linear_state_machine / weekly_certification_parallel_axes_independent ──

def test_paid_week_moves_to_offset_while_adjudication_stays_eligible(api):
    """PRD §3.8: "When the recovery's recovery_method is OFFSET, the referenced
    WeeklyCertification has its payment_status cascaded PAID → OFFSET (its
    adjudication axis stays ELIGIBLE — the two axes move independently)."
    PRD §3.8: "A recovery that brings recovered_cents to exactly total_assessed_cents
    moves the overpayment to SATISFIED".

    Design: Difficulty/non_linear_state_machine/weekly_certification_parallel_axes_independent
    """
    # WBA 30000, no earnings: paid week pays 30000. NONFRAUD overpayment principal
    # 30000 (total 30000). OFFSET recovery of 30000 against the week -> SATISFIED,
    # week payment_status OFFSET, adjudication_status still ELIGIBLE.
    scenario, wc = make_paid_week(reported_earnings_cents=0)
    op = establish_overpayment(scenario["claim"]["id"], "NONFRAUD", 30000)
    apply_recovery(op["id"], 30000, op["version"], recovery_method="OFFSET",
                   weekly_certification_id=wc["id"])
    wc_after = get_success_data(api_client.get_weekly_certification(wc["id"], BPO))
    op_after = get_success_data(api_client.get_overpayment(op["id"], BPO))
    assert wc_after["payment_status"] == "OFFSET"
    assert wc_after["adjudication_status"] == "ELIGIBLE"
    assert op_after["status"] == "SATISFIED"
    assert_overpayment_conserved(op_after)


def test_offset_recovery_satisfies_and_cascades(api):
    """PRD §3.8: "When the recovery's recovery_method is OFFSET, the referenced
    WeeklyCertification has its payment_status cascaded PAID → OFFSET".

    Design: Difficulty/non_linear_state_machine/weekly_certification_parallel_axes_independent
    """
    scenario, wc = make_paid_week(reported_earnings_cents=0)
    op = establish_overpayment(scenario["claim"]["id"], "NONFRAUD", 30000)
    rec = apply_recovery(op["id"], 30000, op["version"], recovery_method="OFFSET",
                         weekly_certification_id=wc["id"])
    assert rec["status"] == "APPLIED"
    op_after = get_success_data(api_client.get_overpayment(op["id"], BPO))
    assert op_after["recovered_cents"] == 30000
    assert op_after["status"] == "SATISFIED"


# ── Corner: state_machines / weekly_certification_initial_axes ──

def test_weekly_certification_initial_axes(api):
    """PRD §3.5: "A new certification starts with adjudication_status of PENDING and
    payment_status of UNPAID."
    PRD §3.5: "When a certification is filed, the system computes
    work_search_required. It is true unless the week is exempt".

    Design: Corner/state_machines/weekly_certification_initial_axes
    """
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"], "2026-04-11")
    assert wc["adjudication_status"] == "PENDING"
    assert wc["payment_status"] == "UNPAID"
    assert wc["work_search_required"] is True


# ── Corner: endpoints / list_weekly_certifications_by_claim_reverse_reachability ──

def test_list_weekly_certifications_for_claim(api):
    """PRD §2.5: "Endpoint paths that nest one resource under another (for example,
    the recoveries that belong to an overpayment, or the work-search contacts that
    belong to a weekly certification) are validated left to right."
    PRD §2.3: "Each list response carries limit, offset, total_count, and has_more
    in the meta object of the envelope."

    Design: Corner/endpoints/list_weekly_certifications_by_claim_reverse_reachability
    """
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", work_search_waived=True)
    from test_helpers import validate_paginated
    data, meta = validate_paginated(
        api_client.list_claim_weekly_certifications(scenario["claim"]["id"], ADJ))
    assert meta["total_count"] == 1
    assert any(item["id"] == wc["id"] for item in data)
