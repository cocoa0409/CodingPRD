"""Rental charge calculations: tiered multi-day + member discount + waiver fee,
and the estimated-vs-final (late-fee) divergence.

Queue-A depth: dual_variant_calc (rental), combinatorial_formula (mode a),
boundary_precision_check (return exactly at due). Queue-B: below-threshold calc.
"""
import pytest
from test_helpers import (
    new_member, new_rentable_unit, quote_rental, setup_picked_up_rental,
    return_rental, set_clock,
)

START = "2026-07-05T09:00:00Z"
DUE_7D = "2026-07-12T09:00:00Z"
DUE_6D = "2026-07-11T09:00:00Z"


# ─── dual_variant_calc / rental_estimated_vs_final_charge_diverge ──────────

def test_rental_estimated_charge_at_quote(api):
    """PRD §3.2: "The member-tier discount is then the discounted amount — the daily
    subtotal after the multi-day discount — multiplied by the member's tier rate
    (zero percent for BASIC, ten percent for PREMIER), rounded to whole cents."
    PRD §3.2: "The estimated_charge_cents is the discounted amount minus the
    member-tier discount, plus the waiver fee."

    PREMIER, 2000/day, 7 days, no waiver: 14000 - round(14000*.15)=2100 -> 11900;
    member discount round(11900*.10)=1190 -> estimated 10710.

    Design: Difficulty/dual_variant_calc/rental_estimated_vs_final_charge_diverge
    """
    member = new_member(tier="PREMIER")
    _sku, unit = new_rentable_unit(daily_rental_rate_cents=2000)
    rental = quote_rental(member, unit["id"], START, DUE_7D)
    assert rental["rental_days"] == 7
    assert rental["estimated_charge_cents"] == 10710
    assert rental["final_charge_cents"] is None


def test_rental_final_charge_diverges_from_estimate(api):
    """PRD §3.2: "A rental is late only when returned_at falls strictly after due_at;
    in that case the number of late days is the span from due_at to returned_at in
    days rounded up to the next whole day, and the late fee is that late-day count
    multiplied by the snapshotted daily_rate_cents multiplied by one and one-half,
    rounded to whole cents."
    PRD §3.2: "The resulting final_charge_cents is the estimated charge plus the
    late fee, and on return the member's loyalty_points_balance increases by the
    final charge divided by one hundred, rounded down to a whole number of points."

    Returned 2 days late: late fee round(2*2000*1.5)=6000 -> final 10710+6000=16710.

    Design: Difficulty/dual_variant_calc/rental_estimated_vs_final_charge_diverge
    """
    member, _sku, _unit, rental = setup_picked_up_rental(
        tier="PREMIER", daily_rental_rate_cents=2000, start_at=START, due_at=DUE_7D)
    set_clock("2026-07-14T09:00:00Z")
    returned = return_rental(rental["id"])
    assert returned["estimated_charge_cents"] == 10710
    assert returned["final_charge_cents"] == 16710
    assert returned["final_charge_cents"] != returned["estimated_charge_cents"]


# ─── combinatorial_formula / rental_charge_tiered_nonlinear_mode_a ─────────

def test_rental_days_rounded_up_to_seven(api):
    """PRD §3.2: "rental_days is the span from start_at to due_at expressed in days
    and rounded up to the next whole day, with a floor of one day so that any rental
    spans at least one billable day."

    Design: Difficulty/combinatorial_formula/rental_charge_tiered_nonlinear_mode_a
    """
    member = new_member(tier="PREMIER")
    _sku, unit = new_rentable_unit(daily_rental_rate_cents=3000, category="BACKPACK",
                                   price_cents=40000)
    rental = quote_rental(member, unit["id"], START, DUE_7D, damage_waiver=True)
    assert rental["rental_days"] == 7


def test_rental_tiered_nonlinear_estimated_charge(api):
    """PRD §3.2: "When rental_days is at least seven, a multi-day discount equal to
    the daily subtotal multiplied by fifteen percent (rounded to whole cents) is
    subtracted; below seven days there is no such discount."
    PRD §3.2: "If damage_waiver is set, a waiver fee equal to the original daily
    subtotal multiplied by ten percent (rounded to whole cents) is added; note the
    waiver fee is computed from the daily subtotal before any discount."

    PREMIER, 3000/day, 7 days, waiver: 21000 -3150 =17850; member -round(17850*.10)=1785;
    waiver round(21000*.10)=2100 -> 17850-1785+2100 = 18165.

    Design: Difficulty/combinatorial_formula/rental_charge_tiered_nonlinear_mode_a
    """
    member = new_member(tier="PREMIER")
    _sku, unit = new_rentable_unit(daily_rental_rate_cents=3000, category="BACKPACK",
                                   price_cents=40000)
    rental = quote_rental(member, unit["id"], START, DUE_7D, damage_waiver=True)
    assert rental["estimated_charge_cents"] == 18165


# ─── boundary_precision_check / rental_return_exactly_at_due_no_late_fee ───

def test_return_exactly_at_due_no_late_fee(api):
    """PRD §3.2: "If the return is on or before due_at there is no late fee."
    PRD §3.2: "A rental is late only when returned_at falls strictly after due_at".

    Returning exactly at due_at (2026-07-12T09:00Z) yields no late fee, so
    final_charge_cents == estimated 10710.

    Design: Difficulty/boundary_precision_check/rental_return_exactly_at_due_no_late_fee
    """
    member, _sku, _unit, rental = setup_picked_up_rental(
        tier="PREMIER", daily_rental_rate_cents=2000, start_at=START, due_at=DUE_7D)
    set_clock(DUE_7D)
    returned = return_rental(rental["id"])
    assert returned["final_charge_cents"] == 10710


def test_return_at_due_final_equals_estimate(api):
    """PRD §3.2: "If the return is on or before due_at there is no late fee. The
    resulting final_charge_cents is the estimated charge plus the late fee".

    With a zero late fee at the strict-boundary return, final == estimated.

    Design: Difficulty/boundary_precision_check/rental_return_exactly_at_due_no_late_fee
    """
    member, _sku, _unit, rental = setup_picked_up_rental(
        tier="PREMIER", daily_rental_rate_cents=2000, start_at=START, due_at=DUE_7D)
    set_clock(DUE_7D)
    returned = return_rental(rental["id"])
    assert returned["final_charge_cents"] == returned["estimated_charge_cents"]


# ─── Queue-B calculations / rental_charge_below_multiday_threshold_no_discount

def test_rental_charge_below_multiday_threshold_no_discount(api):
    """PRD §3.2: "When rental_days is at least seven, a multi-day discount equal to
    the daily subtotal multiplied by fifteen percent (rounded to whole cents) is
    subtracted; below seven days there is no such discount."

    PREMIER, 2000/day, 6 days: no multi-day discount; 12000 - round(12000*.10)=1200
    -> estimated 10800.

    Design: Corner/calculations/rental_charge_below_multiday_threshold_no_discount
    """
    member = new_member(tier="PREMIER")
    _sku, unit = new_rentable_unit(daily_rental_rate_cents=2000, price_cents=80000)
    rental = quote_rental(member, unit["id"], START, DUE_6D)
    assert rental["rental_days"] == 6
    assert rental["estimated_charge_cents"] == 10800
