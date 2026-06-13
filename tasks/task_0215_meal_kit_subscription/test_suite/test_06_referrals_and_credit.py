"""Referral program and credit-wallet reconciliation: forward estimate vs settled cap, the
depth-3 ship->settle->credit cascade, refund restoring consumed credit, and the
referral-summary read.

Translates queue A (Difficulty) dual_variant_calc(referral), transitive_cascade(ship),
compensating_invariant(refund), and queue B (Corner) endpoints/referral_summary instance.
"""
import pytest
from test_helpers import (
    validate_success,
    set_clock, create_plan, create_zone, create_recipes,
    register_member, create_subscription, create_box, add_recipes_to_box,
    lock_box, charge_box, ship_box, refund_box,
    create_referral_payload,
    setup_referrer_referee_with_pending_referral,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


def _build_referrer_with_n_referees(zone, plan, n):
    """Register a referrer and n referees (with explicit PENDING referrals). Returns
    (referrer, [referee, ...])."""
    referrer = register_member(zone["id"], full_name="Referrer")
    referees = []
    for i in range(n):
        e = register_member(zone["id"], full_name=f"E{i}")
        validate_success(api_create_referral(referrer, e), 201)
        referees.append(e)
    return referrer, referees


def api_create_referral(referrer, referee):
    from test_helpers import api_client
    return api_client.create_referral(
        create_referral_payload(referrer["id"], referee["id"]), ADMIN)


# ─── Difficulty: dual_variant_calc / referral_reward_forward_estimate_vs_settled_diverge ──

def test_referral_forward_estimate_is_uncapped_pending_times_reward(api):
    """PRD §3.7: "The `forward_estimate_cents` is the fixed reward of 1500 cents multiplied by the count of that member's `PENDING` referrals — an uncapped, not-yet-credited optimistic upper bound."

    Design: Difficulty/dual_variant_calc/referral_reward_forward_estimate_vs_settled_diverge
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    referrer, _ = _build_referrer_with_n_referees(zone, plan, 4)
    summary = validate_success(api.get_referral_summary(
        referrer["id"], make_member_headers(referrer["id"])), 200)
    assert summary["forward_estimate_cents"] == 6000
    assert summary["pending_count"] == 4


def test_referral_forward_estimate_ignores_cap(api):
    """PRD §3.7: "This forward estimate deliberately ignores the per-cycle cap; the actual
    settled rewards honor it."

    Design: Difficulty/dual_variant_calc/referral_reward_forward_estimate_vs_settled_diverge
    """
    # 4 pending referrals -> forward estimate 4*1500 = 6000, even though the settle cap is 3.
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    referrer, _ = _build_referrer_with_n_referees(zone, plan, 4)
    summary = validate_success(api.get_referral_summary(
        referrer["id"], make_member_headers(referrer["id"])), 200)
    assert summary["forward_estimate_cents"] == 6000


# ─── Difficulty: transitive_cascade / ship_settles_referral_credits_referrer_depth3 ──

def test_ship_first_box_settles_referral_and_credits_referrer(api):
    """PRD §3.5: "if this is the referee member's very first box to reach `SHIPPED`, the system settles that referee's `PENDING` referral as a cascade — moving the referral toward `SETTLED`, which in turn credits the referrer's `credit_balance_cents` as described in §3.7."
    PRD §3.7: "the referral settles: its `reward_cents` is set to the fixed reward of 1500 cents, its `status` becomes `SETTLED`, and that 1500 cents is credited to the referrer's `credit_balance_cents`."

    Design: Difficulty/transitive_cascade/ship_settles_referral_credits_referrer_depth3
    """
    ctx = setup_referrer_referee_with_pending_referral(clock="2026-07-01T00:00:00.000Z")
    referrer, referee, referral = ctx["referrer"], ctx["referee"], ctx["referral"]
    plan, recipes = ctx["plan"], ctx["recipes"]
    sub = create_subscription(referee, plan)
    box = create_box(referee, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(referee, box, recipes[:2])
    lock_box(referee, box)
    set_clock("2026-07-11T00:00:00.000Z")
    charge_box(box)
    shipped = validate_success(api.ship_box(box["id"], OPS), 200)
    assert shipped["fulfillment_status"] == "SHIPPED"

    settled = validate_success(api.get_referral(referral["id"], ADMIN), 200)
    assert settled["status"] == "SETTLED"
    assert settled["reward_cents"] == 1500
    referrer_after = validate_success(api.get_member(referrer["id"], ADMIN), 200)
    assert referrer_after["credit_balance_cents"] == 1500


def test_ship_first_box_increments_referee_lifetime_count(api):
    """PRD §3.5: "On a successful ship, the owning member's `lifetime_box_count` increments by one."

    Design: Difficulty/transitive_cascade/ship_settles_referral_credits_referrer_depth3
    """
    ctx = setup_referrer_referee_with_pending_referral(clock="2026-07-01T00:00:00.000Z")
    referee, plan, recipes = ctx["referee"], ctx["plan"], ctx["recipes"]
    sub = create_subscription(referee, plan)
    box = create_box(referee, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(referee, box, recipes[:2])
    lock_box(referee, box)
    set_clock("2026-07-11T00:00:00.000Z")
    charge_box(box)
    validate_success(api.ship_box(box["id"], OPS), 200)
    referee_after = validate_success(api.get_member(referee["id"], ADMIN), 200)
    assert referee_after["lifetime_box_count"] == 1


# ─── Difficulty: compensating_invariant / refund_restores_consumed_credit_balance ──

def test_refund_restores_consumed_credit(api):
    """PRD §3.5: "On a successful refund, the credit that was consumed when this box was charged is restored to the member's `credit_balance_cents` as a compensating ledger entry."

    Design: Difficulty/compensating_invariant/refund_restores_consumed_credit_balance
    """
    # Referrer earns 1500 credit (referee's first box ships). Then referrer's own box is charged
    # (credit_applied 1500 -> credit 0) and refunded (credit restored to 1500, no drift).
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=4, code="P_CMP")
    zone = create_zone(zone_code="ZONE_B", cold_pack_surcharge_cents=499, cutoff_weekday=5)
    recipes = create_recipes(4, prefix="K")
    referrer = register_member(zone["id"], full_name="CMPR")
    referee = register_member(zone["id"], full_name="CMPE")
    validate_success(api.create_referral(
        create_referral_payload(referrer["id"], referee["id"]), ADMIN), 201)

    # ship referee's first box -> credit referrer 1500
    e_sub = create_subscription(referee, plan)
    e_box = create_box(referee, e_sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(referee, e_box, recipes)
    lock_box(referee, e_box)
    set_clock("2026-07-11T00:00:00.000Z")
    charge_box(e_box)
    ship_box(e_box)
    pre = validate_success(api.get_member(referrer["id"], ADMIN), 200)
    assert pre["credit_balance_cents"] == 1500

    # referrer's own box: charge consumes 1500, refund restores it
    set_clock("2026-07-12T00:00:00.000Z")
    r_sub = create_subscription(referrer, plan)
    r_box = create_box(referrer, r_sub, "2026-07-29T00:00:00.000Z")
    add_recipes_to_box(referrer, r_box, recipes)
    lock_box(referrer, r_box)
    set_clock("2026-07-25T00:00:00.000Z")
    charge_box(r_box)
    refunded = validate_success(api.refund_box(r_box["id"], OPS), 200)
    assert refunded["fulfillment_status"] == "REFUNDED"
    post = validate_success(api.get_member(referrer["id"], ADMIN), 200)
    assert post["credit_balance_cents"] == 1500


def test_refund_reaches_refunded_status(api):
    """PRD §3.5: "The operations role refunds a `CHARGED` box, advancing its fulfillment dimension from `CHARGED` to the terminal `REFUNDED`."

    Design: Difficulty/compensating_invariant/refund_restores_consumed_credit_balance
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2, code="P_RFD")
    zone = create_zone()
    recipes = create_recipes(2, prefix="RFD")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    lock_box(member, box)
    set_clock("2026-07-11T00:00:00.000Z")
    charge_box(box)
    refunded = validate_success(api.refund_box(box["id"], OPS), 200)
    assert refunded["fulfillment_status"] == "REFUNDED"


# ─── Corner: endpoints / referral_summary_computed_read ─────────────────────

def test_referral_summary_computed_read(api):
    """PRD §3.2: "A dedicated referral-summary read computes, for a member acting as a referrer, three figures: a forward-looking `forward_estimate_cents`, a `settled_total_cents`, and a `pending_count`."
    PRD §3.7: "The `forward_estimate_cents` is the fixed reward of 1500 cents multiplied by the count of that member's `PENDING` referrals"

    Design: Corner/endpoints/referral_summary_computed_read
    """
    set_clock("2026-07-01T00:00:00.000Z")
    create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    referrer = register_member(zone["id"], full_name="RS")
    referee = register_member(zone["id"], full_name="ES")
    validate_success(api.create_referral(
        create_referral_payload(referrer["id"], referee["id"]), ADMIN), 201)
    summary = validate_success(api.get_referral_summary(
        referrer["id"], make_member_headers(referrer["id"])), 200)
    assert summary["forward_estimate_cents"] == 1500
    assert summary["pending_count"] == 1
    assert summary["settled_total_cents"] == 0
