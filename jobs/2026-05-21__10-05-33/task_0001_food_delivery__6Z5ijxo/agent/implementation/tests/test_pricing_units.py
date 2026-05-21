"""Direct unit tests on pricing functions imported from server.domain.pricing."""
import sys
import os
# allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.domain.pricing import (
    solo_delivery_fee_cents,
    route_merge_discount_cents,
    tiered_commission_cents,
    commission_cents,
    late_fine_cents,
)
from server.domain.bonus import compute_bonus_tier


def test_solo_fee_zero_distance_no_peak():
    assert solo_delivery_fee_cents(0.0, False) == 300


def test_solo_fee_zero_distance_peak():
    assert solo_delivery_fee_cents(0.0, True) == 500


def test_solo_fee_band_boundary():
    # 2.0 km → 2 bands
    assert solo_delivery_fee_cents(2.0, False) == 300 + 240
    # 2.01 km → 3 bands
    assert solo_delivery_fee_cents(2.01, False) == 300 + 360


def test_merge_discount_floor():
    # solo=540: floor(540*0.25)=135
    assert route_merge_discount_cents(540) == 135
    # solo=300: floor(300*0.25)=75
    assert route_merge_discount_cents(300) == 75
    # solo=303: floor(303*0.25)=75 (not 76)
    assert route_merge_discount_cents(303) == 75


def test_tiered_commission_boundary_20000():
    assert tiered_commission_cents(20000) == 3000


def test_tiered_commission_two_tiers_30000():
    assert tiered_commission_cents(30000) == 4800


def test_tiered_commission_three_tiers_60000():
    assert tiered_commission_cents(60000) == 10600


def test_tiered_commission_below_threshold():
    # 100 * 0.15 = 15
    assert tiered_commission_cents(100) == 15


def test_commission_override_used():
    # 10000 * 0.20 = 2000
    assert commission_cents(10000, 0.20) == 2000


def test_late_fine_tiers():
    assert late_fine_cents(0, 1000) == 0
    assert late_fine_cents(1, 1000) == 200
    assert late_fine_cents(10, 1000) == 200
    assert late_fine_cents(11, 1000) == 550
    assert late_fine_cents(20, 1000) == 1000
    assert late_fine_cents(30, 1000) == 1500
    # >30: cap min(fee, 1500) + 500
    assert late_fine_cents(31, 1000) == 1000 + 500
    assert late_fine_cents(60, 2000) == 1500 + 500
    assert late_fine_cents(60, 1500) == 1500 + 500


def test_bonus_tier_boundaries():
    # All max => 0.6*1 + 0.3*1 + 0.1*1 = 1.0 → PLATINUM
    assert compute_bonus_tier(1.0, 1.0, 5.0) == "PLATINUM"
    # 0.6*0.9 + 0.3*0.9 + 0.1*0.9 = 0.9 → PLATINUM (lower-bound inclusive)
    assert compute_bonus_tier(0.9, 0.9, 4.5) == "PLATINUM"
    # 0.8 weighted: e.g. on_time=0.8, accept=0.8, rating=4.0 (=0.8) -> 0.8 -> GOLD
    assert compute_bonus_tier(0.8, 0.8, 4.0) == "GOLD"
    # 0.7 boundary -> SILVER
    assert compute_bonus_tier(0.7, 0.7, 3.5) == "SILVER"
    # below 0.7 -> BRONZE
    assert compute_bonus_tier(0.5, 0.5, 2.5) == "BRONZE"
