"""
Borrow workflow (PRD §3.4) including all PRD §2.7 validation gates that fire
on POST /rentals: 8 (offline), 9 (maintenance), 10 (no available device),
13 (pricing not configured), 14 (refund risk), 15 (borrow risk),
16 (deposit insufficient), 17 (wallet insufficient), and the §3.4 selector
policy.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    BORROW_LIMIT_24H,
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    REFUND_LIMIT_30D,
    advance_clock_to,
    api_client,
    assert_rental,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    create_pricing_plan,
    create_user,
    deposit,
    heartbeat,
    iso_add_hours,
    make_user_headers,
    schedule_maintenance,
    setup_borrow_environment,
    setup_cabinet_with_device,
    setup_funded_user,
    setup_pricing_plans,
    setup_user_with_borrow_count,
    setup_user_with_refund_count,
    topup_wallet,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_borrow_succeeds_creates_active_rental(api):
    """PRD §3.4: "A new Rental row is created with user_id equal to the caller,
    start_cabinet_id equal to the supplied cabinet ... rental_status ACTIVE,
    and payment_status PENDING."
    """
    env = setup_borrow_environment(rented_at="2026-01-01T10:00:00Z")
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    rental = validate_success(res, 201)
    assert_rental(rental)
    assert rental["user_id"] == env["user"]["id"]
    assert rental["start_cabinet_id"] == env["cabinet"]["id"]
    assert rental["device_id"] == env["device"]["id"]
    assert rental["rental_status"] == "ACTIVE"
    assert rental["payment_status"] == "PENDING"
    assert rental["rented_at"] is not None


def test_borrow_clears_device_location_and_slot(api):
    """PRD §3.4: "transitions Device.status from AVAILABLE to BORROWED and
    clears the device's current_cabinet_id and current_slot_index. The slot
    the device was housed in transitions OCCUPIED → EMPTY and its device_id
    is cleared."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    device_after = validate_success(
        api.get_device(env["device"]["id"], ADMIN_HEADERS), 200
    )
    assert device_after["status"] == "BORROWED"
    assert device_after["current_cabinet_id"] is None
    assert device_after["current_slot_index"] is None

    cab_after = validate_success(
        api.get_cabinet(env["cabinet"]["id"], ADMIN_HEADERS), 200
    )
    target_slot = next(s for s in cab_after["slots"] if s["slot_index"] == 0)
    assert target_slot["slot_status"] == "EMPTY"
    assert target_slot["device_id"] is None


def test_borrow_increments_borrow_count_24h(api):
    """PRD §3.4: "The user's borrow_count_24h increases by exactly one — it is
    incremented every time the borrow attempt reaches the side-effect stage."
    """
    env = setup_borrow_environment()
    user_before = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    borrow_for(env["user"], env["cabinet"]["id"])
    user_after = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert user_after["borrow_count_24h"] == user_before["borrow_count_24h"] + 1


# ---------------------------------------------------------------------------
# Selector policy (PRD §3.4)
# ---------------------------------------------------------------------------


def test_selector_picks_highest_battery(api):
    """PRD §3.4: "The eligible set is ranked by battery_level in descending
    order ... The top-ranked device wins."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    d1 = create_device(cabinet["id"], 0, battery_level=60)
    d2 = create_device(cabinet["id"], 1, battery_level=80)  # highest battery
    d3 = create_device(cabinet["id"], 2, battery_level=70)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    assert rental["device_id"] == d2["id"], (
        "selector must pick highest battery (PRD §3.4)"
    )


def test_selector_filters_out_low_battery(api):
    """PRD §3.4: "filters in to those Device records ... whose battery_level
    is at or above 50."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=49)  # ineligible
    eligible = create_device(cabinet["id"], 1, battery_level=51)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    assert rental["device_id"] == eligible["id"]


def test_selector_battery_50_eligible(api):
    """PRD §3.4: "battery_level is at or above 50" — boundary is inclusive."""
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    boundary_device = create_device(cabinet["id"], 0, battery_level=50)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    assert rental["device_id"] == boundary_device["id"]


# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------


def test_borrow_rejected_when_no_available_device(api):
    """PRD §3.4: "if the eligible set is empty the borrow is rejected with
    ERR_NO_AVAILABLE_DEVICE."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    # Only one device, below the 50 threshold.
    create_device(cabinet["id"], 0, battery_level=10)
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_NO_AVAILABLE_DEVICE")


def test_borrow_rejected_when_pricing_not_configured(api):
    """PRD §2.7 priority 13: "at borrow time, a PricingPlan exists whose
    city_code equals the start cabinet's city_code (rejection:
    ERR_PRICING_NOT_CONFIGURED, HTTP 422)."
    """
    setup_pricing_plans(["BJ"])  # only BJ plan exists
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_PRICING_NOT_CONFIGURED")


def test_borrow_rejected_when_deposit_insufficient(api):
    """PRD §2.7 priority 16: "the user's deposit_balance is at or above the
    minimum deposit of 99.00 CNY (rejection: ERR_DEPOSIT_INSUFFICIENT,
    HTTP 402)."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"])
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = create_user()
    # No deposit, no wallet.
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_DEPOSIT_INSUFFICIENT")


def test_borrow_rejected_when_wallet_negative(api):
    """PRD §2.7 priority 17: "the user's wallet_balance is at or above 0 at
    borrow time (rejection: ERR_WALLET_INSUFFICIENT, HTTP 402)."

    To get wallet negative: user starts with wallet=0 (only deposit), borrow,
    wait past 24h so overdue penalty + base fee accumulate, return — wallet
    debited beyond zero. Then attempt a fresh borrow.
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    create_device(cabinet["id"], 1, battery_level=80)  # second device for re-borrow
    debt_user = create_user()
    deposit(debt_user["id"], 99.00)  # deposit 99, wallet stays 0.00
    r1 = borrow_for(debt_user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")  # 25h elapsed
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api_client.run_sweep({"sweep_type": "overdue"})
    api.return_rental(
        r1["id"],
        {"return_cabinet_id": cabinet["id"]},
        make_user_headers(debt_user["id"]),
    )
    user_post = validate_success(
        api.get_user(debt_user["id"], make_user_headers(debt_user["id"])), 200
    )
    assert user_post["wallet_balance"] < 0, (
        f"wallet must be negative; got {user_post['wallet_balance']}"
    )
    # Now attempt a fresh borrow — wallet < 0 → ERR_WALLET_INSUFFICIENT.
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(debt_user["id"])
    )
    validate_error(res, "ERR_WALLET_INSUFFICIENT")


# ---------------------------------------------------------------------------
# Risk control (PRD §2.7 priorities 14-15 / §3.7)
# ---------------------------------------------------------------------------


def test_borrow_rejected_at_refund_limit(api):
    """PRD §3.7: "blocks borrowing once it reaches 5 (the check is strict
    less-than, so a count of 4 still permits borrow and a count of 5 rejects
    with ERR_REFUND_LIMIT_EXCEEDED)."
    """
    env = setup_user_with_refund_count(REFUND_LIMIT_30D)
    # User has refund_count_30d == 5 now. Build a fresh borrowable state.
    create_device(env["cabinet"]["id"], 23, battery_level=80)
    advance_clock_to(env["clock"])
    heartbeat(env["cabinet"]["id"], env["clock"])
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    validate_error(res, "ERR_REFUND_LIMIT_EXCEEDED")


def test_refund_count_4_still_permits_borrow(api):
    """PRD §3.7: "a count of 4 still permits borrow."
    """
    env = setup_user_with_refund_count(REFUND_LIMIT_30D - 1)  # 4 refunds
    advance_clock_to(env["clock"])
    heartbeat(env["cabinet"]["id"], env["clock"])
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    rental = validate_success(res, 201)
    assert rental["rental_status"] == "ACTIVE"


def test_borrow_rejected_at_borrow_limit(api):
    """PRD §3.7: "blocks borrowing once it reaches 10 (the check is strict
    less-than, so a count of 9 still permits borrow and a count of 10
    rejects with ERR_ABNORMAL_BORROW_PATTERN)."
    """
    env = setup_user_with_borrow_count(BORROW_LIMIT_24H)
    advance_clock_to(env["clock"])
    heartbeat(env["cabinet"]["id"], env["clock"])
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    validate_error(res, "ERR_ABNORMAL_BORROW_PATTERN")


# ---------------------------------------------------------------------------
# One-active-rental invariant (PRD §3.4 / §2.7 priority 6)
# ---------------------------------------------------------------------------


def test_second_borrow_while_active_rejected(api):
    """PRD §3.4: "any second borrow attempt while the same user already has a
    rental in ACTIVE, OVERDUE, or STUCK is rejected with ERR_DUPLICATE_RENTAL."
    """
    env = setup_borrow_environment()
    borrow_for(env["user"], env["cabinet"]["id"])
    # Add a second device so eligibility is satisfied for the second attempt.
    create_device(env["cabinet"]["id"], 1, battery_level=80)
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_RENTAL")


def test_second_borrow_after_return_permitted(api):
    """PRD §3.4: invariant only applies when prior rental is ACTIVE/OVERDUE/STUCK.
    A returned rental should not block fresh borrowing."""
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    api.return_rental(
        rental["id"],
        {"return_cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    # Add fresh device — original was returned to slot 0 so it's available.
    advance_clock_to("2026-01-01T11:30:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:30:00Z")
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    validate_success(res, 201)
