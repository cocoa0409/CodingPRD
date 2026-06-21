"""Season pricing and priority-points accrual — dual-variant and combinatorial
calculation depth probes (PRD §3.7, §3.8, §3.9, §3.10, §3.11).

All money is integer cents; rounding discipline is pinned per rule (PRD §2.7).
"""
from test_helpers import (
    validate_success,
    setup_pending_subscription,
    setup_active_subscription,
    setup_active_subscription_with_payment_plan,
    setup_listed_resale,
    list_plan_installments,
    pay_installment,
    create_account,
    TEST_USERS,
)

_BOX = TEST_USERS["box_office_headers"]
_FIN = TEST_USERS["finance_headers"]


# =========================================================================
# Dual-variant: renewal_price FULL vs PARTIAL on Subscription.locked_price_cents
# =========================================================================
def test_full_plan_locks_full_base_price(api):
    """PRD §3.7: "Multiply that full price by the plan's `price_multiplier_bps`,
    divide by 10000, and take the floor of the result to obtain the plan-adjusted
    price; for a `FULL` plan whose multiplier is 10000 this equals the full base
    price, while for a `PARTIAL` plan it is prorated downward."
    PRD §3.7: "the subscription's `locked_price_cents` is the sum of those per-seat
    prices across all `ASSIGNED` assignments."

    Design: Difficulty/dual_variant_calc/renewal_price_full_vs_partial_on_subscription
    """
    ctx = setup_pending_subscription(
        base_price_cents=200000, plan_type="FULL", price_multiplier_bps=10000
    )
    resp = api.activate_subscription(ctx["subscription"]["id"], _BOX)
    sub = validate_success(resp)
    assert sub["locked_price_cents"] == 200000, sub["locked_price_cents"]


def test_partial_plan_prorates_locked_price(api):
    """PRD §3.7: "Multiply that full price by the plan's `price_multiplier_bps`,
    divide by 10000, and take the floor of the result to obtain the plan-adjusted
    price; for a `FULL` plan whose multiplier is 10000 this equals the full base
    price, while for a `PARTIAL` plan it is prorated downward."

    A PARTIAL plan at 5500 bps on a BRONZE holder yields floor(200000*5500/10000)
    = 110000, above the 100000 floor so the floor does not bind.

    Design: Difficulty/dual_variant_calc/renewal_price_full_vs_partial_on_subscription
    """
    ctx = setup_pending_subscription(
        base_price_cents=200000, plan_type="PARTIAL", price_multiplier_bps=5500
    )
    resp = api.activate_subscription(ctx["subscription"]["id"], _BOX)
    sub = validate_success(resp)
    assert sub["locked_price_cents"] == 110000, sub["locked_price_cents"]


def test_full_and_partial_diverge_on_same_base(api):
    """PRD §3.7: "for a `FULL` plan whose multiplier is 10000 this equals the full
    base price, while for a `PARTIAL` plan it is prorated downward."

    Two subscriptions on the same 200000 section, one FULL and one PARTIAL(5500),
    produce divergent locked totals (200000 vs 110000).

    Design: Difficulty/dual_variant_calc/renewal_price_full_vs_partial_on_subscription
    """
    full = setup_pending_subscription(base_price_cents=200000, plan_type="FULL",
                                      price_multiplier_bps=10000, section_name="Full Sec")
    part = setup_pending_subscription(base_price_cents=200000, plan_type="PARTIAL",
                                      price_multiplier_bps=5500, section_name="Part Sec")
    full_sub = validate_success(api.activate_subscription(full["subscription"]["id"], _BOX))
    part_sub = validate_success(api.activate_subscription(part["subscription"]["id"], _BOX))
    assert full_sub["locked_price_cents"] == 200000
    assert part_sub["locked_price_cents"] == 110000
    assert full_sub["locked_price_cents"] != part_sub["locked_price_cents"]


# =========================================================================
# Dual-variant: priority_points standard vs playoff on Account.priority_points
# =========================================================================
def test_standard_accrual_grants_base_points(api):
    """PRD §3.8: "Begin with a base of the seat count multiplied by 100 points per
    seat. Add a tenure bonus of the account's `consecutive_seasons` multiplied by 50
    points per season. The sum of those two is the standard accrual."
    PRD §3.8: "if the plan does not include playoffs, no playoff term is added."

    One seat, consecutive_seasons=0, no playoffs -> 100 points.

    Design: Difficulty/dual_variant_calc/priority_points_standard_vs_playoff_on_account
    """
    ctx = setup_pending_subscription(
        plan_type="FULL", price_multiplier_bps=10000,
        includes_playoffs=False, consecutive_seasons=0,
    )
    validate_success(api.activate_subscription(ctx["subscription"]["id"], _BOX))
    acc = validate_success(api.get_account(ctx["account"]["id"], _BOX))
    assert acc["priority_points"] == 100, acc["priority_points"]


def test_playoff_accrual_adds_playoff_bonus(api):
    """PRD §3.8: "If the subscription's plan has `includes_playoffs` set to true,
    add a further playoff bonus of 200 points for each seat (200 multiplied by the
    seat count) on top of the standard accrual."

    One seat, consecutive_seasons=0, playoffs -> 100 + 200 = 300 points, landing on
    Account.priority_points (a different entity domain than locked_price_cents).

    Design: Difficulty/dual_variant_calc/priority_points_standard_vs_playoff_on_account
    """
    ctx = setup_pending_subscription(
        plan_type="FULL", price_multiplier_bps=10000,
        includes_playoffs=True, consecutive_seasons=0,
    )
    validate_success(api.activate_subscription(ctx["subscription"]["id"], _BOX))
    acc = validate_success(api.get_account(ctx["account"]["id"], _BOX))
    assert acc["priority_points"] == 300, acc["priority_points"]


# =========================================================================
# Combinatorial: renewal_price floor-bind (mode a)
# =========================================================================
def test_partial_floor_binds_and_raises_seat_price(api):
    """PRD §3.7: "The per-seat `assigned_price_cents` is then the larger of this
    discounted figure and a minimum partial-season floor of 100000 cents — the
    floor is applied after the loyalty discount, not before."

    base=150000, PARTIAL 5500 -> plan_adjusted=82500, BRONZE disc=0; the 100000
    floor binds and raises assigned_price_cents to 100000.

    Design: Difficulty/combinatorial_formula/renewal_price_tiered_multiplier_loyalty_floor_mode_a
    """
    ctx = setup_pending_subscription(
        base_price_cents=150000, plan_type="PARTIAL", price_multiplier_bps=5500
    )
    sub = validate_success(api.activate_subscription(ctx["subscription"]["id"], _BOX))
    assert sub["locked_price_cents"] == 100000, sub["locked_price_cents"]
    sa = validate_success(api.get_seat_assignment(ctx["assignment"]["id"], _BOX))
    assert sa["assigned_price_cents"] == 100000, sa["assigned_price_cents"]


def test_partial_floor_binds_on_seat_assignment_price(api):
    """PRD §3.7: "Each seat's `assigned_price_cents` is set to its computed per-seat
    price, and the subscription's `locked_price_cents` is the sum of those per-seat
    prices across all `ASSIGNED` assignments."
    PRD §3.7: "The per-seat `assigned_price_cents` is then the larger of this
    discounted figure and a minimum partial-season floor of 100000 cents — the
    floor is applied after the loyalty discount, not before."

    Design: Difficulty/combinatorial_formula/renewal_price_tiered_multiplier_loyalty_floor_mode_a
    """
    ctx = setup_pending_subscription(
        base_price_cents=150000, plan_type="PARTIAL", price_multiplier_bps=5500,
        section_name="Floor Sec",
    )
    validate_success(api.activate_subscription(ctx["subscription"]["id"], _BOX))
    sa = validate_success(api.get_seat_assignment(ctx["assignment"]["id"], _BOX))
    assert sa["assigned_price_cents"] == 100000, sa["assigned_price_cents"]


# =========================================================================
# Combinatorial: resale_payout round-each-fee-then-sum (mode b)
# =========================================================================
def test_resale_payout_rounds_each_fee_then_subtracts(api):
    """PRD §3.9: "Each fee is computed independently as gross multiplied by that
    fee's basis points divided by 10000 and rounded half up to a whole cent, and
    only then are the two rounded fees subtracted from the gross. The two fees must
    be rounded separately and summed — the system must not add the two basis-point
    rates together and round a single combined fee, because that produces a
    different cent."

    gross=10005: mkt=round_half_up(750.375)=750, proc=round_half_up(290.145)=290,
    payout=10005-750-290=8965 (one cent off from the combine-then-round path).

    Design: Difficulty/combinatorial_formula/resale_payout_round_each_fee_component_mode_b
    """
    ctx = setup_listed_resale(listing_price_cents=10005)
    resp = api.complete_sale(ctx["transfer"]["id"], {"recipient_account_id": ctx["buyer"]["id"]}, _BOX)
    tt = validate_success(resp)
    assert tt["status"] == "SOLD", tt["status"]
    assert tt["payout_cents"] == 8965, tt["payout_cents"]


def test_resale_payout_round_each_on_round_gross(api):
    """PRD §3.9: "a marketplace fee of 750 basis points of the gross, and a
    processing fee of 290 basis points of the gross. Each fee is computed
    independently as gross multiplied by that fee's basis points divided by 10000
    and rounded half up to a whole cent, and only then are the two rounded fees
    subtracted from the gross."

    gross=20000: mkt=1500, proc=580, payout=20000-1500-580=17920.

    Design: Difficulty/combinatorial_formula/resale_payout_round_each_fee_component_mode_b
    """
    ctx = setup_listed_resale(listing_price_cents=20000, section_name="Resale Sec")
    resp = api.complete_sale(ctx["transfer"]["id"], {"recipient_account_id": ctx["buyer"]["id"]}, _BOX)
    tt = validate_success(resp)
    assert tt["payout_cents"] == 17920, tt["payout_cents"]


# =========================================================================
# Corner — calculations: GOLD loyalty discount via grant-points
# =========================================================================
def test_gold_loyalty_discount_applied_at_activation(api):
    """PRD §3.7: "Next compute a loyalty discount: multiply the plan-adjusted price
    by the account's loyalty rate in basis points, divide by 10000, and take the
    floor; the loyalty rate is 0 basis points for `BRONZE`, 500 basis points for
    `SILVER`, and 1000 basis points for `GOLD`."

    GOLD holder on a FULL 200000 plan -> disc=floor(200000*1000/10000)=20000 ->
    assigned_price_cents=180000.

    Design: Corner/calculations/renewal_price_loyalty_discount_gold_via_grant_points
    """
    ctx = setup_pending_subscription(
        base_price_cents=200000, plan_type="FULL", price_multiplier_bps=10000,
        grant_account_points=1000,
    )
    sub = validate_success(api.activate_subscription(ctx["subscription"]["id"], _BOX))
    assert sub["locked_price_cents"] == 180000, sub["locked_price_cents"]
    sa = validate_success(api.get_seat_assignment(ctx["assignment"]["id"], _BOX))
    assert sa["assigned_price_cents"] == 180000, sa["assigned_price_cents"]


# =========================================================================
# Corner — calculations: installment waterfall remainder on last installment
# =========================================================================
def test_installment_waterfall_remainder_on_last(api):
    """PRD §3.10: "The down payment, carried by the installment whose `sequence` is
    1, is 2500 basis points of the total — total multiplied by 2500, divided by
    10000, rounded half up to a whole cent."
    PRD §3.10: "`sequence` 1 receives the down payment; sequences 2 through
    `installment_count` minus 1 each receive the per-installment amount; and the
    highest sequence, `installment_count`, receives the per-installment amount plus
    the remainder, so the rounding remainder always lands on the last installment."

    total=200000, count=3: down=50000, remaining=150000, per=floor(150000/2)=75000,
    remainder=0 -> [50000, 75000, 75000].

    Design: Corner/calculations/payment_plan_waterfall_remainder_on_last_installment
    """
    ctx = setup_active_subscription(base_price_cents=200000, plan_type="FULL",
                                    price_multiplier_bps=10000)
    resp = api.create_payment_plan(
        {"subscription_id": ctx["subscription"]["id"], "installment_count": 3}, _FIN
    )
    plan = validate_success(resp, expected_status=201)
    assert plan["total_cents"] == 200000, plan["total_cents"]
    rows = list_plan_installments(plan["id"])
    amounts = {r["sequence"]: r["amount_cents"] for r in rows}
    assert amounts[1] == 50000, amounts
    assert amounts[2] == 75000, amounts
    assert amounts[3] == 75000, amounts


# =========================================================================
# Corner — calculations: cancellation refund = paid - fee
# =========================================================================
def test_cancellation_refund_paid_minus_fee(api):
    """PRD §3.11: "The cancellation fee is 1000 basis points of the subscription's
    `locked_price_cents` — `locked_price_cents` multiplied by 1000, divided by
    10000, rounded half up to a whole cent. The refund is the paid amount minus the
    fee, floored at 0 so that it is never negative."
    PRD §3.10: "any `ACTIVE` `PaymentPlan` for the subscription transitions to
    `CANCELLED`, which voids each of its `SCHEDULED` `Installment` rows to `VOID`."

    paid=50000, fee=round_half_up(200000*1000/10000)=20000, refund=30000; the plan
    ends CANCELLED with amount_paid_cents=50000 preserved.

    Design: Corner/calculations/cancellation_refund_partial_paid_minus_fee
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4,
                                                      base_price_cents=200000)
    pay_installment(ctx["payment_plan"]["id"], 1)
    sub = validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    assert sub["status"] == "CANCELLED", sub["status"]
    plan = validate_success(api.get_payment_plan(ctx["payment_plan"]["id"], _FIN))
    assert plan["status"] == "CANCELLED", plan["status"]
    assert plan["amount_paid_cents"] == 50000, plan["amount_paid_cents"]
