"""Money calculations: F&B shortfall (carryover variants), resignation refund
(net vs gross), capital-assessment allocation, and the statement total formula.

All tests build their own state from scratch via test_helpers fixtures and pin
the literal expected cents values from the design index.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_member_headers,
    create_club, create_category, create_and_activate_membership,
    create_membership, activate_membership, post_chit, open_statements,
    close_period, get_period_statement, get_club_version, create_assessment,
    get_member_assessment_charge,
)
from test_helpers import api_client as _client_mod  # noqa: F401

_MANAGER = TEST_USERS["club_manager_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================

def test_fb_shortfall_forward_carryover_reduces_effective_minimum(api):
    """PRD §3.7: "When carryover is allowed, the effective minimum for the current
    period is reduced by whatever fb_credit_carried_cents the member brought in,
    and at finalization any surplus — the qualifying spend over the effective
    minimum, floored at zero — is written, capped at one period's fb_minimum_cents,
    into the member's fb_credit_carried_cents for the next period."
    PRD §3.7: "the effective minimum is the category minimum minus the member's
    fb_credit_carried_cents, floored at zero so it is never negative."

    Design: Difficulty/dual_variant_calc/fb_shortfall_no_vs_forward_carryover
    """
    club = create_club(name="Carry Club", fb_minimum_carryover_allowed=True)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")

    # Period 0: spend 26000 DINING -> surplus 6000 carried into period 1.
    post_chit(club["id"], m["id"], 26000, "DINING")
    close_period(club["id"])  # advances to period 1, rolls carryover

    # Period 1: spend 10000 DINING.
    post_chit(club["id"], m["id"], 10000, "DINING")
    close_period(club["id"])  # finalizes the period-1 statement

    stmt = get_period_statement(club["id"], m["id"], 1)
    assert stmt["fb_minimum_cents"] == 14000, (
        f"effective minimum should be 20000-6000=14000, got {stmt['fb_minimum_cents']}"
    )
    assert stmt["fb_spend_cents"] == 10000, f"got {stmt['fb_spend_cents']}"
    assert stmt["fb_shortfall_cents"] == 4000, (
        f"FORWARD_CARRYOVER shortfall should be 14000-10000=4000 "
        f"(NO_CARRYOVER would be 10000), got {stmt['fb_shortfall_cents']}"
    )


def test_fb_shortfall_no_carryover_uses_full_category_minimum(api):
    """PRD §3.7: "When carryover is not allowed, fb_credit_carried_cents is always
    zero, so the effective minimum equals the category minimum outright, any
    surplus over the minimum is simply discarded, and the shortfall is the
    category minimum minus the period's qualifying spend, floored at zero."

    Design: Difficulty/dual_variant_calc/fb_shortfall_no_vs_forward_carryover
    """
    club = create_club(name="NoCarry Club", fb_minimum_carryover_allowed=False)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")

    # Period 0: spend 26000 (surplus 6000 is DISCARDED, nothing carries).
    post_chit(club["id"], m["id"], 26000, "DINING")
    close_period(club["id"])

    # Period 1: spend 10000 DINING. No carried credit -> effective minimum 20000.
    post_chit(club["id"], m["id"], 10000, "DINING")
    close_period(club["id"])

    stmt = get_period_statement(club["id"], m["id"], 1)
    assert stmt["fb_minimum_cents"] == 20000, (
        f"no-carryover effective minimum should equal category minimum 20000, "
        f"got {stmt['fb_minimum_cents']}"
    )
    assert stmt["fb_spend_cents"] == 10000, f"got {stmt['fb_spend_cents']}"
    assert stmt["fb_shortfall_cents"] == 10000, (
        f"NO_CARRYOVER shortfall should be 20000-10000=10000, "
        f"got {stmt['fb_shortfall_cents']}"
    )


def test_resignation_refund_net_of_outstanding_balance(api):
    """PRD §3.3: "The gross refund is the category's refundable_equity_cents
    multiplied by the club's resignation_refund_pct, divided by 100, with the
    result floored to a whole cent (rounding toward zero)."
    PRD §3.3: "the refund owed is the gross refund minus the member's outstanding
    charge_balance_cents at resign time, floored at zero so it can never go
    negative."

    Design: Difficulty/dual_variant_calc/resignation_refund_net_vs_gross
    """
    club = create_club(name="Refund Club")  # resignation_refund_pct default 80
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    # initiation chit debits balance to 50000; pay 40000 -> balance 10000.
    mh = make_member_headers(m["id"])
    validate_success(api.create_payment(m["id"], {"amount_cents": 40000}, mh))

    data = validate_success(api.resign_membership(m["id"], mh))
    assert data["account_status"] == "RESIGNED_PENDING"
    # gross = floor(40000*80/100)=32000; net = 32000 - 10000 = 22000.
    assert data["refund_owed_cents"] == 22000, (
        f"NET_OF_BALANCE refund should be 32000-10000=22000, got {data['refund_owed_cents']}"
    )


def test_resignation_refund_gross_when_zero_balance(api):
    """PRD §3.3: "When the member's charge_balance_cents is zero at resign time,
    no netting occurs and refund_owed_cents equals the gross refund exactly."
    PRD §3.3: "The gross refund is the category's refundable_equity_cents
    multiplied by the club's resignation_refund_pct, divided by 100, with the
    result floored to a whole cent (rounding toward zero)."

    Design: Difficulty/dual_variant_calc/resignation_refund_net_vs_gross
    """
    club = create_club(name="Refund Club 2")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    mh = make_member_headers(m["id"])
    # Fully clear the initiation balance -> 0 at resign time.
    validate_success(api.create_payment(m["id"], {"amount_cents": 50000}, mh))

    data = validate_success(api.resign_membership(m["id"], mh))
    assert data["account_status"] == "RESIGNED_PENDING"
    # gross = floor(40000*80/100) = 32000; no netting.
    assert data["refund_owed_cents"] == 32000, (
        f"GROSS refund should equal 32000 with zero balance, got {data['refund_owed_cents']}"
    )


# ===========================================================================
# Difficulty: combinatorial_formula
# ===========================================================================

def test_equal_assessment_floor_then_distribute_remainder(api):
    """PRD §3.5: "the base share is the target divided by the number of eligible
    memberships, floored to a whole cent; this base is assigned to every member;
    then the leftover — the target minus the base times the member count — is
    distributed one extra cent each to the first members in created_at ascending
    order, until the leftover is exhausted."
    PRD §3.5: "In both bases the shares are floored individually first and the
    remainder is distributed afterward; computing a total and rounding once is
    forbidden."

    Design: Difficulty/combinatorial_formula/assessment_equal_remainder_round_order
    """
    club = create_club(name="Equal Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=20000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    m3 = create_and_activate_membership(club["id"], cat["id"], holder_name="M3")

    asmt = create_assessment(club["id"], 100001, "EQUAL", description="Roof")
    data = validate_success(api.levy_assessment(asmt["id"], _MANAGER))
    assert data["status"] == "LEVIED"
    assert data["levied_amount_cents"] == 100001, f"got {data['levied_amount_cents']}"

    # floor(100001/3)=33333, remainder 2 -> first two by created_at get +1.
    assert get_member_assessment_charge(m1["id"])["amount_cents"] == 33334
    assert get_member_assessment_charge(m2["id"])["amount_cents"] == 33334
    assert get_member_assessment_charge(m3["id"])["amount_cents"] == 33333


def test_equal_assessment_shares_sum_to_target(api):
    """PRD §3.5: "The allocation arithmetic is pinned so that the per-member shares
    always sum exactly to total_target_cents."
    PRD §3.5: "After fan-out the assessment records levied_amount_cents as the sum
    of all the per-member shares it created."

    Design: Difficulty/combinatorial_formula/assessment_equal_remainder_round_order
    """
    club = create_club(name="Equal Club 2")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=20000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    m3 = create_and_activate_membership(club["id"], cat["id"], holder_name="M3")

    asmt = create_assessment(club["id"], 100001, "EQUAL", description="Roof")
    data = validate_success(api.levy_assessment(asmt["id"], _MANAGER))
    shares = [
        get_member_assessment_charge(m1["id"])["amount_cents"],
        get_member_assessment_charge(m2["id"])["amount_cents"],
        get_member_assessment_charge(m3["id"])["amount_cents"],
    ]
    assert sum(shares) == 100001, f"shares {shares} must sum exactly to target 100001"
    assert data["levied_amount_cents"] == 100001, f"got {data['levied_amount_cents']}"


def test_statement_total_sums_dues_shortfall_chits_assessment(api):
    """PRD §3.7: "total_due_cents is the sum of the dues, the food-and-beverage
    shortfall, the chit charges, and the assessment, evaluated in that order with
    the shortfall computed first."
    PRD §3.7: "The food-and-beverage shortfall billed this period,
    fb_shortfall_cents, is the effective minimum minus the qualifying spend,
    floored at zero so a member who meets or beats the minimum is billed no
    shortfall."
    PRD §3.7: "The chit-charges line, chit_charges_cents, is the sum of all POSTED
    chit amounts of any kind in the closing period rolled into the statement."

    Design: Difficulty/combinatorial_formula/statement_total_conditional_branch_sum
    """
    club = create_club(name="Stmt Club", fb_minimum_carryover_allowed=False)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    post_chit(club["id"], m["id"], 12000, "DINING")     # counts toward F&B
    post_chit(club["id"], m["id"], 5000, "PRO_SHOP")    # does not count
    close_period(club["id"])

    stmt = get_period_statement(club["id"], m["id"], 0)
    # fb_shortfall = max(0, 20000-12000)=8000; chit_charges=12000+5000=17000.
    assert stmt["fb_shortfall_cents"] == 8000, f"got {stmt['fb_shortfall_cents']}"
    assert stmt["chit_charges_cents"] == 17000, f"got {stmt['chit_charges_cents']}"
    # total = dues 15000 + shortfall 8000 + chits 17000 + assessment 0 = 40000.
    assert stmt["total_due_cents"] == 40000, f"got {stmt['total_due_cents']}"


def test_statement_total_zero_shortfall_branch_when_spend_meets_minimum(api):
    """PRD §3.7: "The food-and-beverage shortfall billed this period,
    fb_shortfall_cents, is the effective minimum minus the qualifying spend,
    floored at zero so a member who meets or beats the minimum is billed no
    shortfall."
    PRD §3.7: "total_due_cents is the sum of the dues, the food-and-beverage
    shortfall, the chit charges, and the assessment, evaluated in that order with
    the shortfall computed first."

    Design: Difficulty/combinatorial_formula/statement_total_conditional_branch_sum
    """
    club = create_club(name="Stmt Club 2", fb_minimum_carryover_allowed=False)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    # DINING 25000 beats the 20000 minimum -> shortfall branch floors to 0.
    post_chit(club["id"], m["id"], 25000, "DINING")
    close_period(club["id"])

    stmt = get_period_statement(club["id"], m["id"], 0)
    assert stmt["fb_shortfall_cents"] == 0, (
        f"spend 25000 >= minimum 20000 -> no shortfall, got {stmt['fb_shortfall_cents']}"
    )
    # total = dues 15000 + shortfall 0 + chits 25000 + assessment 0 = 40000.
    assert stmt["total_due_cents"] == 40000, f"got {stmt['total_due_cents']}"


# ===========================================================================
# Corner: calculations
# ===========================================================================

def test_fb_no_carryover_shortfall_correct(api):
    """PRD §3.7: "the shortfall is the category minimum minus the period's
    qualifying spend, floored at zero."
    PRD §3.7: "The qualifying spend, fb_spend_cents, is the sum of the member's
    DINING chit amounts in the closing period whose status is POSTED or SETTLED
    (voided chits are excluded)."

    Design: Corner/calculations/fb_no_carryover_shortfall_correct
    """
    club = create_club(name="C1 Club", fb_minimum_carryover_allowed=False)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=0,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    post_chit(club["id"], m["id"], 12000, "DINING")
    close_period(club["id"])

    stmt = get_period_statement(club["id"], m["id"], 0)
    assert stmt["fb_shortfall_cents"] == 8000, f"got {stmt['fb_shortfall_cents']}"


def test_fb_spend_excludes_non_dining_chits(api):
    """PRD §3.5: "At post time the system pins counts_toward_fb to true exactly
    when the kind is DINING and false otherwise."
    PRD §3.7: "The qualifying spend, fb_spend_cents, is the sum of the member's
    DINING chit amounts in the closing period whose status is POSTED or SETTLED
    (voided chits are excluded)."

    Design: Corner/calculations/fb_spend_excludes_non_dining_chits
    """
    club = create_club(name="C2 Club", fb_minimum_carryover_allowed=False)
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=0,
                          fb_minimum_cents=20000, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    post_chit(club["id"], m["id"], 30000, "PRO_SHOP")  # not DINING -> excluded
    close_period(club["id"])

    stmt = get_period_statement(club["id"], m["id"], 0)
    assert stmt["fb_spend_cents"] == 0, f"non-DINING spend must not count, got {stmt['fb_spend_cents']}"
    assert stmt["fb_shortfall_cents"] == 20000, f"got {stmt['fb_shortfall_cents']}"


def test_dues_weighted_assessment_largest_fraction_remainder(api):
    """PRD §3.5: "each member's raw share is the target multiplied by that
    member's weight and divided by the sum of weights over all eligible members;
    each member's base share is the floor of their raw share; the leftover — the
    target minus the sum of the floored bases — is distributed one extra cent
    each to the members with the largest fractional remainder in their raw share,
    ties broken by created_at ascending."

    Design: Corner/calculations/dues_weighted_assessment_largest_fraction_remainder
    """
    club = create_club(name="C3 Club")
    golf = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                           refundable_equity_cents=0, monthly_dues_cents=30000,
                           fb_minimum_cents=0, capacity=5, guest_fee_cents=5000,
                           allows_golf=True)
    social = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                             refundable_equity_cents=0, monthly_dues_cents=20000,
                             fb_minimum_cents=0, capacity=5, guest_fee_cents=5000)
    m1 = create_and_activate_membership(club["id"], golf["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], social["id"], holder_name="M2")
    m3 = create_and_activate_membership(club["id"], social["id"], holder_name="M3")

    asmt = create_assessment(club["id"], 100000, "DUES_WEIGHTED", description="Pool")
    data = validate_success(api.levy_assessment(asmt["id"], _MANAGER))
    assert data["levied_amount_cents"] == 100000, f"got {data['levied_amount_cents']}"

    # weights 30000/20000/20000 (sum 70000): raw 42857.1/28571.4/28571.4,
    # bases 42857/28571/28571 (sum 99999); the 1 remainder goes to the largest
    # fraction (tie at .428 -> created_at ASC -> M2).
    assert get_member_assessment_charge(m1["id"])["amount_cents"] == 42857
    assert get_member_assessment_charge(m2["id"])["amount_cents"] == 28572
    assert get_member_assessment_charge(m3["id"])["amount_cents"] == 28571
