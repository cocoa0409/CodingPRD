"""Payout settlement: per-booking commission rounding, the release hold and open-claim
guard, and the release/reverse money-conservation compensation.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    setup_open_location, create_booking, dropoff, pickup, set_clock,
    setup_completed_booking, get_only_payout, file_claim,
)

THREE_BAGS_ONE_OVERSIZE = [
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 160},
]


def _two_completed_bookings_fee_1250(api):
    """Two on-time 1-bag/9-day bookings at a 12.5% host, both picked up on 2026-06-19."""
    ctx = setup_open_location(api, platform_fee_bps=1250, tier="NONE",
                              per_bag_coverage_cents=0, premium_cents_per_bag_day=0)
    b1 = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-19",
                        bags=[{"declared_value_cents": 10000, "dimension_sum_cm": 100}])
    dropoff(api, ctx, b1["id"], seal_codes=["K1"])
    b2 = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-19",
                        bags=[{"declared_value_cents": 10000, "dimension_sum_cm": 100}])
    dropoff(api, ctx, b2["id"], seal_codes=["K2"])
    set_clock(api, "2026-06-19T00:00:00Z")
    pickup(api, ctx, b1["id"])
    pickup(api, ctx, b2["id"])
    return ctx


def test_commission_rounds_half_up_per_booking(api):
    """PRD §3.7: "Its `platform_fee_cents` is the commission, computed as the gross times
    the host's `platform_fee_bps` divided by 10000, rounded half up to whole cents, and this
    rounding happens per booking before the net is folded into any host total."

    Design: Difficulty/combinatorial_formula/host_payout_fee_round_per_booking_then_sum_mode_b
    """
    ctx = _two_completed_bookings_fee_1250(api)
    payouts = get_success_data(api.list_payouts(ctx["admin_headers"]))
    assert len(payouts) == 2
    for p in payouts:
        assert p["gross_cents"] == 4500              # 500 * 1 * 9
        assert p["platform_fee_cents"] == 563         # round_half_up(562.5)


def test_host_balance_rounds_per_booking_then_sums(api):
    """PRD §2.6: "Host balances are maintained as the sum of already-rounded per-booking net
    amounts — the system rounds per booking and then sums, never sums and then rounds."

    Design: Difficulty/combinatorial_formula/host_payout_fee_round_per_booking_then_sum_mode_b
    """
    ctx = _two_completed_bookings_fee_1250(api)
    payouts = get_success_data(api.list_payouts(ctx["admin_headers"]))
    set_clock(api, "2026-06-21T00:00:00Z")
    for p in payouts:
        get_success_data(api.release_payout(p["id"], ctx["admin_headers"]))
    host = get_success_data(api.get_host(ctx["host"]["id"], ctx["admin_headers"]))
    assert host["payout_balance_cents"] == 7874       # 2 * (4500 - 563)


# --- Release guarded by open claim --------------------------------------------

def _completed_with_open_claim(api):
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 20000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    file_claim(api, ctx, booking["id"], bags[0]["id"], reason="DAMAGE",
               description="d", claimed_amount_cents=5000)
    set_clock(api, "2026-06-15T00:00:00Z")   # past the 2-day hold; only the open claim blocks
    payout = get_only_payout(api, ctx)
    return ctx, payout


def test_release_blocked_by_open_claim(api):
    """PRD §3.7: "No claim on the payout's booking may be in `OPEN`, `UNDER_REVIEW`, or
    `NEEDS_INFO` — an unresolved claim blocks release with `ERR_PAYOUT_HAS_OPEN_CLAIM`."

    Design: Difficulty/cross_entity_state_dependency/payout_release_blocked_by_open_claim
    """
    ctx, payout = _completed_with_open_claim(api)
    resp = api.release_payout(payout["id"], ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYOUT_HAS_OPEN_CLAIM.value)


def test_release_blocked_by_open_claim_stays_pending(api):
    """PRD §3.7: "A platform admin releases a pending payout, transitioning
    `PENDING → RELEASED`, but only under two conditions."
    PRD §3.7: "an unresolved claim blocks release with `ERR_PAYOUT_HAS_OPEN_CLAIM`."

    Design: Difficulty/cross_entity_state_dependency/payout_release_blocked_by_open_claim
    """
    ctx, payout = _completed_with_open_claim(api)
    api.release_payout(payout["id"], ctx["admin_headers"])
    after = get_success_data(api.get_payout(payout["id"], ctx["admin_headers"]))
    assert after["status"] == "PENDING"


# --- Money conservation on release then reverse -------------------------------

def _released_payout_fee_2000(api):
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200, bags=THREE_BAGS_ONE_OVERSIZE,
        seal_codes=["K0", "K1", "K2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-13")
    payout = get_only_payout(api, ctx)
    set_clock(api, "2026-06-15T00:00:00Z")
    get_success_data(api.release_payout(payout["id"], ctx["admin_headers"]))
    return ctx, payout


def test_release_moves_net_into_payout_balance(api):
    """PRD §3.7: "Releasing a payout moves its net amount out of the host's
    `pending_payout_cents` and into its `payout_balance_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_on_payout_reverse
    """
    ctx, payout = _released_payout_fee_2000(api)
    host = get_success_data(api.get_host(ctx["host"]["id"], ctx["admin_headers"]))
    assert host["payout_balance_cents"] == 4320       # 5400 - 1080
    assert host["pending_payout_cents"] == 0


def test_reverse_compensates_balance_no_drift(api):
    """PRD §3.7: "reversal is a compensation that subtracts the net amount back out of the
    host's `payout_balance_cents`, leaving the ledger conserved with no drift."

    Design: Difficulty/compensating_invariant/money_conservation_on_payout_reverse
    """
    ctx, payout = _released_payout_fee_2000(api)
    reversed_payout = get_success_data(api.reverse_payout(payout["id"], ctx["admin_headers"]))
    assert reversed_payout["status"] == "REVERSED"
    host = get_success_data(api.get_host(ctx["host"]["id"], ctx["admin_headers"]))
    assert host["payout_balance_cents"] == 0


# --- Release hold -------------------------------------------------------------

def test_payout_release_before_hold_returns_held(api):
    """PRD §3.7: "the release must not be premature: the current date must be at least the
    booking's pickup date plus a hold of 2 days, otherwise `ERR_PAYOUT_HELD`."

    Design: Corner/validations/payout_release_before_hold_returns_held
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11", pickup_clock="2026-06-11")
    payout = get_only_payout(api, ctx)
    resp = api.release_payout(payout["id"], ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYOUT_HELD.value)
