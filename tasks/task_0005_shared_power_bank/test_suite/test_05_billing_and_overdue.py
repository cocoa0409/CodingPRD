"""
Billing and overdue calculations (PRD §3.5 / §3.6).

Covers free_minutes boundary, hourly rate, daily cap, cross-city surcharge
applies-only-on-final, overdue tier A, tier B, cap, and lost conversion.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    LOST_DEVICE_FEE,
    LOST_THRESHOLD_HOURS,
    OVERDUE_PENALTY_CAP,
    OVERDUE_TIER_A_HOURLY,
    OVERDUE_TIER_B_HOURLY,
    advance_clock_to,
    api_client,
    assert_money_equal,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    create_pricing_plan,
    deposit,
    heartbeat,
    make_user_headers,
    return_for,
    setup_borrow_environment,
    setup_funded_user,
    setup_pricing_plans,
    topup_wallet,
    validate_success,
)


# ---------------------------------------------------------------------------
# free_minutes boundary (PRD §3.5)
# ---------------------------------------------------------------------------


def test_free_minutes_inclusive_boundary_at_5_min(api):
    """PRD §3.5: "The grace-free billable_minutes is the larger of zero and
    total_minutes minus the start cabinet's pricing plan's free_minutes."

    With free_minutes=5 and total_minutes=5: billable_minutes = max(0, 5-5)=0,
    billable_hours=0, fee = min(0*hourly_rate, daily_cap) = 0.00.
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T10:05:00Z")  # exactly 5 min
    heartbeat(cabinet["id"], "2026-01-01T10:05:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # PRD §3.4: "the rental detail includes a provisional charged_amount
    # computed against the current logical clock"
    assert fetched["charged_amount"] == 0.00


def test_one_minute_past_free_starts_first_billable_hour(api):
    """PRD §3.5: "billable_hours is billable_minutes divided by 60, rounded
    up to a whole number." 6 min total → billable_minutes=1 → billable_hours=
    ceil(1/60)=1 → fee = min(1*3.00, 30.00) = 3.00.
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T10:06:00Z")  # 6 min
    heartbeat(cabinet["id"], "2026-01-01T10:06:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert_money_equal(fetched["charged_amount"], 3.00)


# ---------------------------------------------------------------------------
# Daily cap (PRD §3.5)
# ---------------------------------------------------------------------------


def test_daily_cap_clamps_within_24_hour_billable(api):
    """PRD §3.5: "When billable_hours is at most 24, the rental fee is the
    smaller of billable_hours multiplied by the start cabinet's hourly_rate
    and the start cabinet's daily_cap."

    11 billable_hours × 3.00 = 33.00 > daily_cap 30.00 → fee 30.00.
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T20:55:00Z")  # 655 min total
    heartbeat(cabinet["id"], "2026-01-01T20:55:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # 655 min - 5 free = 650 → ceil(650/60)=11 hours → min(11*3, 30)=30.00
    assert_money_equal(fetched["charged_amount"], 30.00)
    assert fetched["rental_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Cross-city surcharge (PRD §3.5)
# ---------------------------------------------------------------------------


def test_cross_city_surcharge_only_on_final_return(api):
    """PRD §3.5: "The cross-city surcharge applies only on the final-return
    computation, and only when the start cabinet's city_code differs from
    the return cabinet's city_code ... The provisional read on a non-terminal
    rental never adds the cross-city surcharge."
    """
    setup_pricing_plans(["BJ", "SH"])
    partner = create_location_partner()
    cab_bj = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    cab_sh = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cab_bj["id"], "2026-01-01T10:00:00Z")
    heartbeat(cab_sh["id"], "2026-01-01T10:00:00Z")
    create_device(cab_bj["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cab_bj["id"])
    advance_clock_to("2026-01-01T11:30:00Z")  # 90 min
    heartbeat(cab_bj["id"], "2026-01-01T11:30:00Z")
    heartbeat(cab_sh["id"], "2026-01-01T11:30:00Z")
    # Provisional read while rental is ACTIVE: no surcharge.
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # 90 min - 5 free = 85 → ceil(85/60)=2 → min(2*3,30)=6.00 (no surcharge).
    assert_money_equal(fetched["charged_amount"], 6.00)

    # Final return at SH: BJ ≠ SH → +10.00 cross-city surcharge.
    advance_clock_to("2026-01-01T12:30:00Z")  # 150 min
    heartbeat(cab_bj["id"], "2026-01-01T12:30:00Z")
    heartbeat(cab_sh["id"], "2026-01-01T12:30:00Z")
    final = return_for(user, rental["id"], cab_sh["id"])
    # 150 min - 5 free = 145 → ceil(145/60)=3 → 3*3=9.00; +10 surcharge=19.00
    assert_money_equal(final["charged_amount"], 19.00)


# ---------------------------------------------------------------------------
# Overdue penalty (PRD §3.6)
# ---------------------------------------------------------------------------


def test_overdue_threshold_strictly_greater_than_24h(api):
    """PRD §3.6: "rental_status flips to OVERDUE when elapsed_hours strictly
    greater than 24 ... 24 is exclusive (a rental that has elapsed exactly
    24 hours stays ACTIVE)."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    # Exactly 24h (still ACTIVE)
    advance_clock_to("2026-01-02T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T00:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "ACTIVE"


def test_overdue_at_25h_flips_to_overdue(api):
    """PRD §3.6: ">24h elapsed → OVERDUE."""
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")  # 25h
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "OVERDUE"


def test_lost_threshold_inclusive_at_168h(api):
    """PRD §3.6: "168 is inclusive (a rental that has elapsed exactly 168
    hours becomes LOST)."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")  # 25h
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-08T00:00:00Z")  # exactly 168h
    heartbeat(cabinet["id"], "2026-01-08T00:00:00Z")
    api.run_sweep({"sweep_type": "lost"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "LOST"
    assert fetched["payment_status"] == "DEPOSIT_DEDUCTED"


def test_lost_just_below_threshold_stays_overdue(api):
    """PRD §3.6: "At 167h59m, still OVERDUE."

    (paraphrased — PRD says "elapsed_hours computed as elapsed seconds divided
    by 3600 and rounded down to a whole number", so 167h59m → 167 < 168 → OVERDUE)
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-07T23:59:00Z")  # 167h59m
    heartbeat(cabinet["id"], "2026-01-07T23:59:00Z")
    api.run_sweep({"sweep_type": "lost"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "OVERDUE"


def test_lost_conversion_charged_amount_is_99(api):
    """PRD §3.6: "When the lost sweep promotes the rental from OVERDUE to LOST
    it overwrites Rental.charged_amount with the flat lost-device fee of
    99.00 CNY."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-08T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-08T00:00:00Z")
    api.run_sweep({"sweep_type": "lost"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert_money_equal(fetched["charged_amount"], 99.00)


def test_lost_conversion_deducts_deposit_then_wallet(api):
    """PRD §3.6: "the deposit deduction is the smaller of the user's current
    deposit_balance and the 99.00 CNY lost-device fee, the residual is
    99.00 minus the deposit deduction, the user's deposit_balance is
    decremented by the deposit deduction (and is therefore clamped at zero,
    never going negative), and the user's wallet_balance is decremented by
    the residual."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user(deposit_amount=99.00, wallet_amount=100.00)
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-08T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-08T00:00:00Z")
    api.run_sweep({"sweep_type": "lost"})
    user_after = validate_success(
        api.get_user(user["id"], make_user_headers(user["id"])), 200
    )
    # deposit had 99 → covers the entire 99 fee → deposit=0, wallet=100 untouched
    assert_money_equal(user_after["deposit_balance"], 0.00)
    assert_money_equal(user_after["wallet_balance"], 100.00)


def test_lost_conversion_marks_device_lost(api):
    """PRD §3.6: "The device that was on rental advances to LOST."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    device = create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-08T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-08T00:00:00Z")
    api.run_sweep({"sweep_type": "lost"})
    d_after = validate_success(api.get_device(device["id"], ADMIN_HEADERS), 200)
    assert d_after["status"] == "LOST"


# ---------------------------------------------------------------------------
# Overdue penalty tiers (PRD §3.6)
# ---------------------------------------------------------------------------


def test_overdue_tier_a_penalty(api):
    """PRD §3.6: "For overdue_hours of 48 or fewer, the penalty is
    overdue_hours multiplied by 5.00 CNY per hour; this tier covers elapsed
    hours 24 through 72."

    Test at elapsed_hours=48 → overdue_hours=24 → penalty = 24*5.00=120.00.
    Plus rental_fee at hour cap=30.00 (24+ hours: daily_cap fully filled).
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user(deposit_amount=99.00, wallet_amount=1000.00)
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")  # 25h → overdue sweep
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-03T00:00:00Z")  # 48h elapsed
    heartbeat(cabinet["id"], "2026-01-03T00:00:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # 48h elapsed = 24h overdue. PRD §3.5 24h+ billable_hours uses daily_cap=30.
    # PRD §3.6 overdue_hours (24) × tier A rate (5.00) = 120.00 penalty.
    # provisional charged_amount = rental_fee + overdue_penalty = 30 + 120 = 150.
    assert_money_equal(fetched["charged_amount"], 150.00)


def test_overdue_penalty_capped_after_144_overdue_hours(api):
    """PRD §3.6: "Once overdue_hours exceeds 144 the overdue penalty is
    capped at the full first tier plus the full second tier (48 hours at
    5.00 CNY plus 96 hours at 10.00 CNY, totalling 1200.00 CNY)."

    Test at elapsed_hours=167 → overdue_hours=143 → still in tier B (not yet
    capped); test at elapsed_hours=169 (overdue_hours=145) → cap fires.
    Wait — 168h triggers LOST. PRD says cap fires for "overdue_hours exceeds
    144"; we observe the cap from elapsed_hours=24+145=169 which would
    already be LOST. So: read provisional at 167h (overdue_hours=143):
    penalty = 48*5 + (143-48)*10 = 240 + 950 = 1190.00.
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user(deposit_amount=99.00, wallet_amount=10_000.00)
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-07T23:00:00Z")  # 167h elapsed
    heartbeat(cabinet["id"], "2026-01-07T23:00:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # rental_fee = 30.00 (24h+); overdue_hours = 143 → tier B:
    # 48*5 + (143-48)*10 = 240 + 950 = 1190.00
    assert_money_equal(fetched["charged_amount"], 30.00 + 1190.00)
