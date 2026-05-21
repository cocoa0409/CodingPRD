"""Pure pricing function tests (§3.4 / §3.7)."""
from __future__ import annotations

from app.pricing import (
    commission_flat_cents,
    commission_tiered_cents,
    delivery_fee_solo_cents,
    late_fine_cents,
    merge_discount_cents,
)

from ._harness import test


@test("delivery fee: base 300, 120 per ceil(km) band, 200 peak")
def t():
    # 0 km, non-peak -> 300
    assert delivery_fee_solo_cents(0.0, False) == 300
    # 2.0 km -> bands=2, 300 + 240 = 540
    assert delivery_fee_solo_cents(2.0, False) == 540
    # 2.01 km -> bands=3, 300 + 360 = 660
    assert delivery_fee_solo_cents(2.01, False) == 660
    # 5 km peak -> 300 + 600 + 200 = 1100
    assert delivery_fee_solo_cents(5.0, True) == 1100


@test("merge discount = floor(0.25 * solo_fee)")
def t():
    assert merge_discount_cents(540) == 135
    # 1100 * 0.25 = 275
    assert merge_discount_cents(1100) == 275
    # 999 * 0.25 = 249.75 -> floor 249
    assert merge_discount_cents(999) == 249


@test("commission tiered: 15/18/22% with single half-up rounding")
def t():
    # subtotal 1000 cents -> entirely tier 1 -> 150
    assert commission_tiered_cents(1000) == 150
    # subtotal 20000 -> all tier 1 -> 3000
    assert commission_tiered_cents(20000) == 3000
    # subtotal 30000: 20000*0.15 + 10000*0.18 = 3000 + 1800 = 4800
    assert commission_tiered_cents(30000) == 4800
    # subtotal 50000: 20000*0.15 + 30000*0.18 = 3000 + 5400 = 8400
    assert commission_tiered_cents(50000) == 8400
    # subtotal 60000: 8400 + 10000*0.22 = 8400 + 2200 = 10600
    assert commission_tiered_cents(60000) == 10600


@test("commission flat: subtotal * rate, half-up")
def t():
    # 12345 * 0.10 = 1234.5 -> half-up = 1235
    assert commission_flat_cents(12345, 0.10) == 1235
    # 100 * 0.15 = 15
    assert commission_flat_cents(100, 0.15) == 15


@test("late fine tier 1: 1-10 min -> 200")
def t():
    assert late_fine_cents(1, 500) == 200
    assert late_fine_cents(10, 500) == 200


@test("late fine tier 2: 11-30 min -> 500 + 50/min over 10")
def t():
    # 11 -> 550
    assert late_fine_cents(11, 500) == 550
    # 20 -> 1000
    assert late_fine_cents(20, 500) == 1000
    # 30 -> 1500
    assert late_fine_cents(30, 500) == 1500


@test("late fine tier 3: >30 -> min(fee,1500)+500")
def t():
    # fee=500 -> 500 + 500 = 1000
    assert late_fine_cents(31, 500) == 1000
    # fee=2000 -> 1500 + 500 = 2000 (capped)
    assert late_fine_cents(45, 2000) == 2000
    # fee=1500 -> 1500 + 500 = 2000 (boundary)
    assert late_fine_cents(45, 1500) == 2000


@test("late fine 0 -> 0")
def t():
    assert late_fine_cents(0, 500) == 0
