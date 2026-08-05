"""Pickup, final settlement, the estimate-vs-final divergence, the overage boundary,
and the depth-2 payout/host cascade triggered by pickup.
"""
from test_helpers import (
    get_success_data,
    setup_open_location, create_booking,
    setup_completed_booking, get_only_payout,
    assert_payout, assert_payout_partition,
)

THREE_BAGS_ONE_OVERSIZE = [
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 160},
]


# --- Dual variant: forward estimate vs chronological final settlement ---------

def test_booking_estimate_forward_looking(api):
    """PRD §3.3: "This provisional estimate uses the requested pickup date and the declared
    bag sizes; it deliberately ignores any actual pickup date and any late fee, which only
    materialize at settlement."

    Design: Difficulty/dual_variant_calc/booking_estimate_vs_final_late_pickup
    """
    ctx = setup_open_location(api, platform_fee_bps=2000, tier="PREMIUM",
                              per_bag_coverage_cents=50000, premium_cents_per_bag_day=200)
    booking = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13",
                             bags=THREE_BAGS_ONE_OVERSIZE)
    # base 4500 + oversize 900 + insurance 1800 = 7200; no late fee in the estimate.
    assert booking["estimated_total_cents"] == 7200


def test_final_settlement_late_pickup_adds_late_fee(api):
    """PRD §3.6: "The `late_fee_cents` is `overage_days` multiplied by a late-fee multiplier
    of 2, multiplied by `per_bag_day_rate_cents`, multiplied by `bag_count`."
    PRD §3.6: "The booking's `final_total_cents` is the sum of the base, oversize, insurance,
    and late-fee components; it is null until the booking completes."

    Design: Difficulty/dual_variant_calc/booking_estimate_vs_final_late_pickup
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200, bags=THREE_BAGS_ONE_OVERSIZE,
        seal_codes=["SL-0", "SL-1", "SL-2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-14")
    assert booking["overage_days"] == 1
    assert booking["late_fee_cents"] == 3000       # 1 * 2 * 500 * 3
    assert booking["final_total_cents"] == 10200    # 4500 + 900 + 1800 + 3000


# --- Overage-days boundary: on-time vs one day late ----------------------------

def test_pickup_on_time_zero_overage(api):
    """PRD §3.6: "The booking's `overage_days` is the number of days between the scheduled
    check-out date and the actual pickup date, floored at 0 so that an on-time or early
    pickup incurs none."

    Design: Difficulty/boundary_precision_check/pickup_overage_zero_vs_one_late_fee
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}], seal_codes=["P1"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-13")
    assert booking["overage_days"] == 0
    assert booking["late_fee_cents"] == 0


def test_pickup_one_day_late_one_overage(api):
    """PRD §3.6: "The `late_fee_cents` is `overage_days` multiplied by a late-fee multiplier
    of 2, multiplied by `per_bag_day_rate_cents`, multiplied by `bag_count`."

    Design: Difficulty/boundary_precision_check/pickup_overage_zero_vs_one_late_fee
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}], seal_codes=["P2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-14")
    assert booking["overage_days"] == 1
    assert booking["late_fee_cents"] == 1000        # 1 * 2 * 500 * 1


# --- Depth-2 cascade: pickup -> payout -> host balances -----------------------

def test_pickup_creates_payout_with_net(api):
    """PRD §3.6: "First, a `Payout` is created for the host in `PENDING` status via the
    provisional payout calculation of §3.7."
    PRD §3.7: "Its `net_cents` is the gross minus the platform fee minus the claim deduction."

    Design: Difficulty/transitive_cascade/pickup_creates_payout_updates_host_depth2
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200, bags=THREE_BAGS_ONE_OVERSIZE,
        seal_codes=["K0", "K1", "K2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-13")
    payout = get_only_payout(api, ctx)
    assert_payout(payout)
    assert payout["status"] == "PENDING"
    assert payout["gross_cents"] == 5400            # 4500 + 900 (insurance excluded)
    assert payout["platform_fee_cents"] == 1080     # round_half_up(5400 * 0.20)
    assert payout["net_cents"] == 4320
    assert_payout_partition(payout)


def test_pickup_updates_host_pending_and_lifetime(api):
    """PRD §3.6: "Second, that payout's net amount is added to the host's
    `pending_payout_cents` and to its `lifetime_earnings_cents`."

    Design: Difficulty/transitive_cascade/pickup_creates_payout_updates_host_depth2
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200, bags=THREE_BAGS_ONE_OVERSIZE,
        seal_codes=["K0", "K1", "K2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-13")
    host = get_success_data(api.get_host(ctx["host"]["id"], ctx["admin_headers"]))
    assert host["pending_payout_cents"] == 4320
    assert host["lifetime_earnings_cents"] == 4320
