import pytest
from services.computations import (
    haversine_km, compute_delivery_fee, compute_tiered_commission,
    compute_commission, compute_late_fine, compute_rider_score, score_to_tier,
    compute_delivery_fee_with_merge,
)
import math


def test_haversine_same_point():
    assert haversine_km(40.0, -74.0, 40.0, -74.0) == 0.0


def test_haversine_known_distance():
    d = haversine_km(40.7128, -74.0060, 40.7580, -73.9855)
    assert 4.0 <= d <= 6.0


def test_delivery_fee_base():
    fee = compute_delivery_fee(0.1, False)
    assert fee == 300 + 120 + 0


def test_delivery_fee_2km():
    fee = compute_delivery_fee(2.0, False)
    assert fee == 300 + 2 * 120


def test_delivery_fee_2_01km():
    fee = compute_delivery_fee(2.01, False)
    assert fee == 300 + 3 * 120


def test_delivery_fee_peak():
    fee = compute_delivery_fee(2.0, True)
    assert fee == 300 + 2 * 120 + 200


def test_tiered_commission_tier1_only():
    result = compute_tiered_commission(10000)
    assert result == 1500  # 10000 * 0.15


def test_tiered_commission_tier1_full():
    result = compute_tiered_commission(20000)
    assert result == 3000  # 20000 * 0.15


def test_tiered_commission_tier2():
    result = compute_tiered_commission(30000)
    expected = 20000 * 0.15 + 10000 * 0.18
    assert result == int(expected)  # 3000 + 1800 = 4800


def test_tiered_commission_tier3():
    result = compute_tiered_commission(60000)
    expected = 20000 * 0.15 + 30000 * 0.18 + 10000 * 0.22
    assert result == int(expected)  # 3000 + 5400 + 2200 = 10600


def test_tiered_commission_boundary():
    result = compute_tiered_commission(50000)
    expected = 20000 * 0.15 + 30000 * 0.18
    assert result == int(expected)  # 3000 + 5400 = 8400


def test_flat_commission():
    result = compute_commission(10000, 0.10)
    assert result == 1000


def test_flat_commission_rounding():
    result = compute_commission(333, 0.10)
    assert result == 33  # 33.3 rounds to 33


def test_flat_commission_half_up():
    result = compute_commission(5, 0.10)
    assert result == 1  # 0.5 rounds to 1


def test_late_fine_zero():
    assert compute_late_fine(0, 500) == 0


def test_late_fine_1_10():
    assert compute_late_fine(1, 500) == 200
    assert compute_late_fine(10, 500) == 200


def test_late_fine_11_30():
    assert compute_late_fine(11, 500) == 550  # 500 + 50*1
    assert compute_late_fine(20, 500) == 1000  # 500 + 50*10
    assert compute_late_fine(30, 500) == 1500  # 500 + 50*20


def test_late_fine_over_30():
    assert compute_late_fine(31, 500) == min(500, 1500) + 500  # 1000
    assert compute_late_fine(31, 2000) == min(2000, 1500) + 500  # 2000


def test_rider_score_perfect():
    score = compute_rider_score(1.0, 1.0, 5.0)
    assert score == 1.0


def test_rider_score_platinum_boundary():
    score = compute_rider_score(1.0, 1.0, 5.0)
    assert score_to_tier(score) == "PLATINUM"


def test_rider_score_gold_boundary():
    assert score_to_tier(0.899) == "GOLD"
    assert score_to_tier(0.800) == "GOLD"


def test_rider_score_silver_boundary():
    assert score_to_tier(0.799) == "SILVER"
    assert score_to_tier(0.700) == "SILVER"


def test_rider_score_bronze():
    assert score_to_tier(0.699) == "BRONZE"
    assert score_to_tier(0.0) == "BRONZE"


def test_exact_boundaries():
    assert score_to_tier(0.900) == "PLATINUM"
    assert score_to_tier(0.800) == "GOLD"
    assert score_to_tier(0.700) == "SILVER"


def test_delivery_fee_with_merge_solo():
    assert compute_delivery_fee_with_merge(540, None, "a1") == 540
    group = {"assignment_ids": ["a1"]}
    assert compute_delivery_fee_with_merge(540, group, "a1") == 540


def test_delivery_fee_with_merge_merged():
    group = {"assignment_ids": ["a1", "a2"]}
    solo = 540
    discount = int(math.floor(540 * 0.25))
    expected = 540 - discount
    assert compute_delivery_fee_with_merge(solo, group, "a1") == expected
