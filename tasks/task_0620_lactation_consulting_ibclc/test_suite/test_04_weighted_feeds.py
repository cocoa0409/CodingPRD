"""Follow-up plan weighted-feed rollups: the pinned sum-then-round order, the
empty-set boundary, and the per-feed transfer computation.

Depth instances (queue A): combinatorial_formula, boundary_precision_check;
plus corner-design breadth for the transfer_grams computed field.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_open_follow_up_plan, add_weighted_feed,
    create_weighted_feed_payload,
    make_consultant_headers,
)


# ─── combinatorial_formula / weighted_feed_sum_then_round_order ─────────────

def test_weighted_feed_avg_is_sum_then_round_once(api):
    """PRD §3.8: "The `avg_transfer_grams` is the mean per-feed transfer: when the
    plan has no feeds it is 0, and otherwise it is the total transfer divided by the
    number of feeds, rounded half-up exactly once after summing. The rounding order
    is fixed — sum the integer per-feed transfers first, then round the single mean
    — rather than rounding each feed and then averaging."

    Three feeds transferring 50, 50, 51: total 151, avg = round_half_up(151/3) =
    round_half_up(50.333) = 50.

    Design: Difficulty/combinatorial_formula/weighted_feed_sum_then_round_order
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=100)
    plan, cons = ctx["plan"], ctx["consultant"]
    add_weighted_feed(plan["id"], cons["id"], 4000, 4050)   # 50
    add_weighted_feed(plan["id"], cons["id"], 4050, 4100)   # 50
    last = get_success_data(api.create_weighted_feed(
        create_weighted_feed_payload(plan["id"], 4100, 4151),  # 51
        make_consultant_headers(cons["id"])))
    assert last["transfer_grams"] == 51

    plan_after = get_success_data(api.get_follow_up_plan(plan["id"], make_consultant_headers(cons["id"])))
    assert plan_after["total_transfer_grams"] == 151, (
        f"expected total 151, got {plan_after['total_transfer_grams']}")
    assert plan_after["avg_transfer_grams"] == 50, (
        f"expected avg 50, got {plan_after['avg_transfer_grams']}")


def test_weighted_feed_meets_target_when_total_reaches_goal(api):
    """PRD §3.8: "The boolean `meets_target` is true when `total_transfer_grams` is
    greater than or equal to the plan's `target_daily_transfer_grams`."

    Total 151 >= target 100 -> meets_target true.

    Design: Difficulty/combinatorial_formula/weighted_feed_sum_then_round_order
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=100)
    plan, cons = ctx["plan"], ctx["consultant"]
    add_weighted_feed(plan["id"], cons["id"], 4000, 4050)
    add_weighted_feed(plan["id"], cons["id"], 4050, 4100)
    add_weighted_feed(plan["id"], cons["id"], 4100, 4151)

    plan_after = get_success_data(api.get_follow_up_plan(plan["id"], make_consultant_headers(cons["id"])))
    assert plan_after["meets_target"] is True


# ─── boundary_precision_check / weighted_feed_empty_set_avg_zero ────────────

def test_empty_plan_has_zero_rollups_and_unmet_target(api):
    """PRD §3.8: "The `avg_transfer_grams` is the mean per-feed transfer: when the
    plan has no feeds it is 0".
    PRD §3.8: "The boolean `meets_target` is true when `total_transfer_grams` is
    greater than or equal to the plan's `target_daily_transfer_grams`."

    A freshly OPEN plan with target 50 and zero feeds has total 0, avg 0, and
    meets_target false (target 50 > 0).

    Design: Difficulty/boundary_precision_check/weighted_feed_empty_set_avg_zero
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=50)
    plan, cons = ctx["plan"], ctx["consultant"]
    fresh = get_success_data(api.get_follow_up_plan(plan["id"], make_consultant_headers(cons["id"])))
    assert fresh["total_transfer_grams"] == 0, (
        f"expected total 0, got {fresh['total_transfer_grams']}")
    assert fresh["avg_transfer_grams"] == 0, (
        f"expected avg 0, got {fresh['avg_transfer_grams']}")
    assert fresh["meets_target"] is False, "meets_target must be false for an empty plan"


def test_open_plan_starts_with_zero_total_transfer(api):
    """PRD §3.8: "when the plan has no feeds it is 0".

    The plan-creation response itself reports total_transfer_grams 0 before any feed.

    Design: Difficulty/boundary_precision_check/weighted_feed_empty_set_avg_zero
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=50)
    plan = ctx["plan"]
    assert plan["total_transfer_grams"] == 0
    assert plan["avg_transfer_grams"] == 0


# ─── Corner: entities / weighted_feed_transfer_grams_computed ───────────────

def test_weighted_feed_transfer_grams_computed(api):
    """PRD §3.8: "Each feed's `transfer_grams` is computed as its post-feed weight
    minus its pre-feed weight — the milk transferred that feed."

    pre 4000 / post 4045 -> transfer_grams 45.

    Design: Corner/entities/weighted_feed_transfer_grams_computed
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=100)
    plan, cons = ctx["plan"], ctx["consultant"]
    feed = validate_success(api.create_weighted_feed(
        create_weighted_feed_payload(plan["id"], 4000, 4045),
        make_consultant_headers(cons["id"])), 201)
    assert feed["transfer_grams"] == 45, f"expected 45, got {feed['transfer_grams']}"
