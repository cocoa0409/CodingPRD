"""Settlement payout math: tiered per-dispatch payout, round-per-line-then-sum,
the two settlement-method variants, and the exact-floor boundary.

Queue A: tiered_line_payout_overperform_bonus, settlement_round_per_line_then_sum,
settlement_pay_for_performance_vs_capacity, performance_floor_exact_ratio_no_penalty.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_settlement_payload,
    setup_submitted_settlement, setup_two_device_completed_event,
)
from test_helpers.api_client import api_client

OP = TEST_USERS["program_operator_headers"]


def _event_dispatches(evt_id):
    return get_success_data(api_client.list_event_dispatches(evt_id, OP))


# --------------------------------------------------------------------------- #
# combinatorial_formula / tiered_line_payout_overperform_bonus
# --------------------------------------------------------------------------- #
def test_overperform_dispatch_earns_bonus_tier(api):
    """PRD §3.7: "If the ratio is at or above the overperformance threshold of
    1.10, the dispatch earns a bonus: its incentive is delivered_kwh multiplied by
    the incentive rate and then by a bonus multiplier of 1.15, with no penalty."

    Design: Difficulty/combinatorial_formula/tiered_line_payout_overperform_bonus
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE",
                                     baseline_loads=(10, 9, 8), event_load=3.0, committed_kw=5)
    disp = _event_dispatches(ctx["evt_id"])[0]
    assert disp["performance_ratio"] == pytest.approx(1.2, abs=0.0001)
    # 12.0 kWh * 50 * 1.15 = 690 cents (bonus tier), not the flat 600.
    assert disp["net_payment_cents"] == 690


def test_overperform_settlement_total_matches_bonus_line(api):
    """PRD §3.7: "Under PAY_FOR_PERFORMANCE, the settlement net is the sum of the
    eligible dispatches' already-rounded per-dispatch net_payment_cents — each line
    is rounded to whole cents first and only then summed, so the round-then-sum
    order is authoritative and must not be re-derived from unrounded line values."

    Design: Difficulty/combinatorial_formula/tiered_line_payout_overperform_bonus
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE",
                                     baseline_loads=(10, 9, 8), event_load=3.0, committed_kw=5)
    assert ctx["settlement"]["net_payment_cents"] == 690


# --------------------------------------------------------------------------- #
# combinatorial_formula / settlement_round_per_line_then_sum
# --------------------------------------------------------------------------- #
def test_each_line_rounds_half_up_to_51_cents(api):
    """PRD §3.7: "The dispatch's net is its incentive minus its penalty. That net
    is rounded half-up to whole cents and then floored at 0, so net_payment_cents
    is the greater of 0 and the rounded net; no dispatch ever carries a negative
    payout."

    Design: Difficulty/combinatorial_formula/settlement_round_per_line_then_sum
    """
    ctx = setup_two_device_completed_event(committed_kw=1.0, baseline_load=6.01,
                                           event_load=5.00)
    settle = get_success_data(api.create_settlement(create_settlement_payload(ctx["evt_id"]), OP))
    get_success_data(api.submit_settlement(settle["id"], OP))
    dispatches = _event_dispatches(ctx["evt_id"])
    for disp in dispatches:
        # raw 1.01 kWh * 50 = 50.5 cents -> round_half_up -> 51
        assert disp["net_payment_cents"] == 51


def test_settlement_sums_rounded_lines_to_102_not_101(api):
    """PRD §3.7: "Under PAY_FOR_PERFORMANCE, the settlement net is the sum of the
    eligible dispatches' already-rounded per-dispatch net_payment_cents — each line
    is rounded to whole cents first and only then summed, so the round-then-sum
    order is authoritative and must not be re-derived from unrounded line values."

    Design: Difficulty/combinatorial_formula/settlement_round_per_line_then_sum
    """
    ctx = setup_two_device_completed_event(committed_kw=1.0, baseline_load=6.01,
                                           event_load=5.00)
    settle = get_success_data(api.create_settlement(create_settlement_payload(ctx["evt_id"]), OP))
    submitted = validate_success(api.submit_settlement(settle["id"], OP))
    # 51 + 51 = 102 (round-per-line then sum), NOT sum-then-round 101.
    assert submitted["net_payment_cents"] == 102


# --------------------------------------------------------------------------- #
# dual_variant_calc / settlement_pay_for_performance_vs_capacity
# --------------------------------------------------------------------------- #
def test_pay_for_performance_settles_to_500(api):
    """PRD §3.7: "Otherwise, if the ratio is at or above the program's
    performance_floor_pct, the incentive is delivered_kwh multiplied by the
    incentive rate, with no penalty."

    Design: Difficulty/dual_variant_calc/settlement_pay_for_performance_vs_capacity
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE",
                                     baseline_loads=(10, 9, 8), event_load=4.0, committed_kw=5)
    # 10.0 kWh delivered at ratio 1.0 -> 10.0 * 50 = 500 cents.
    assert ctx["settlement"]["net_payment_cents"] == 500


def test_capacity_payment_settles_to_5000(api):
    """PRD §3.7: "Under CAPACITY_PAYMENT, the per-dispatch tiered payout is not used
    at all; instead the settlement pays for committed capacity net of an energy
    shortfall. The capacity component is the sum of assigned_reduction_kw over the
    eligible dispatches, multiplied by the program's capacity_incentive_cents_per_kw."

    Design: Difficulty/dual_variant_calc/settlement_pay_for_performance_vs_capacity
    """
    ctx = setup_submitted_settlement(settlement_method="CAPACITY_PAYMENT",
                                     baseline_loads=(10, 9, 8), event_load=4.0, committed_kw=5)
    # capacity 5 kW * 1000 = 5000; shortfall max(0, 5*2 - 10)*80 = 0 -> net 5000.
    assert ctx["settlement"]["net_payment_cents"] == 5000


# --------------------------------------------------------------------------- #
# boundary_precision_check / performance_floor_exact_ratio_no_penalty
# --------------------------------------------------------------------------- #
def test_ratio_exactly_at_floor(api):
    """PRD §3.6: "The performance_ratio is actual_reduction_kw divided by the
    dispatch's assigned_reduction_kw, rounded half-up to four decimal places; when
    assigned_reduction_kw is 0 the ratio is defined as 0 rather than divided."

    Design: Difficulty/boundary_precision_check/performance_floor_exact_ratio_no_penalty
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE",
                                     performance_floor_pct=0.75,
                                     baseline_loads=(10, 9, 8), event_load=5.25, committed_kw=5)
    disp = _event_dispatches(ctx["evt_id"])[0]
    # actual 3.75 kW / assigned 5.0 = 0.75, exactly at the floor.
    assert disp["performance_ratio"] == pytest.approx(0.75, abs=0.0001)


def test_exact_floor_ratio_incurs_no_penalty(api):
    """PRD §3.7: "Otherwise, if the ratio is at or above the program's
    performance_floor_pct, the incentive is delivered_kwh multiplied by the
    incentive rate, with no penalty."

    Design: Difficulty/boundary_precision_check/performance_floor_exact_ratio_no_penalty
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE",
                                     performance_floor_pct=0.75,
                                     baseline_loads=(10, 9, 8), event_load=5.25, committed_kw=5)
    disp = _event_dispatches(ctx["evt_id"])[0]
    # 7.5 kWh * 50 = 375 cents, no penalty at the exact floor.
    assert disp["net_payment_cents"] == 375
