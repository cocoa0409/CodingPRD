"""Boundary-precision tests for the late fee (overdue-day threshold) and fuel
refill (zero-quantity edge).

Covers difficulty rule boundary_precision_check. Each instance is exercised at
both sides of its boundary (X and X+1 / full vs partial).
"""
from test_helpers import (
    validate_success,
    setup_picked_up_agreement, return_agreement, inspect,
    setup_returned_pending_inspection, TEST_USERS,
)

YM = TEST_USERS["yard_manager_headers"]


def test_late_fee_zero_when_returned_on_scheduled_end(api):
    """PRD §3.8: "Returning on the scheduled end date yields zero overdue days and
    therefore no late fee; returning one day later yields one overdue day."

    Design: Difficulty/boundary_precision_check/late_fee_zero_on_return_exactly_scheduled_end_vs_one_day_over
    """
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    ag = return_agreement(ctx["agreement"]["id"], "2026-06-10T09:00:00.000Z")
    assert ag["late_fee_cents"] == 0


def test_late_fee_one_overdue_day_when_returned_day_after(api):
    """PRD §3.8: "Returning on the scheduled end date yields zero overdue days and
    therefore no late fee; returning one day later yields one overdue day."
    PRD §3.8: "The late_fee_cents is the overdue-day count multiplied by
    daily_rate_cents multiplied by late_fee_multiplier, rounded half up to whole
    cents."

    Design: Difficulty/boundary_precision_check/late_fee_zero_on_return_exactly_scheduled_end_vs_one_day_over
    """
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    ag = return_agreement(ctx["agreement"]["id"], "2026-06-11T09:00:00.000Z")
    # 1 overdue day * 4000 * 1.5 = 6000.
    assert ag["late_fee_cents"] == 6000


def test_fuel_refill_zero_when_returned_full(api):
    """PRD §3.8: "If the unit comes back with at least a full tank, the missing
    liters are zero and there is no fuel charge."

    Design: Difficulty/boundary_precision_check/fuel_refill_zero_when_returned_full_vs_partial
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    ins = inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
                  cleanliness="CLEAN", damage_assessed_cents=0)
    assert ins["fuel_refill_cents"] == 0


def test_fuel_refill_charged_when_returned_partial(api):
    """PRD §3.8: "The missing liters are the dispatch level minus the
    return_fuel_level_liters reported at inspection, never below zero, and then
    capped at the tank's fuel_capacity_liters. The fuel_refill_cents is those
    capped missing liters multiplied by the rate card's fuel_refill_cents_per_liter."

    Design: Difficulty/boundary_precision_check/fuel_refill_zero_when_returned_full_vs_partial
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    ins = inspect(ctx["agreement"]["id"], return_fuel_level_liters=30,
                  cleanliness="CLEAN", damage_assessed_cents=0)
    # missing 10 liters * 200 = 2000.
    assert ins["fuel_refill_cents"] == 2000
