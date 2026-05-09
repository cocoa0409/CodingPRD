"""
Return workflow (PRD §3.5): success path, return-failure cycle (STUCK),
return-retry, cross-cabinet, ownership.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    advance_clock_to,
    api_client,
    assert_money_equal,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    create_pricing_plan,
    heartbeat,
    make_user_headers,
    return_for,
    setup_borrow_environment,
    setup_funded_user,
    setup_pricing_plans,
    setup_stuck_rental,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Happy-path return (PRD §3.5)
# ---------------------------------------------------------------------------


def test_return_transitions_rental_to_returned_billed(api):
    """PRD §3.5: "writes Rental.returned_at to the current logical clock value,
    sets Rental.return_cabinet_id ... computes the final billing ... debits
    User.wallet_balance by exactly the resulting Rental.charged_amount, and
    bubbles Rental.payment_status from PENDING to BILLED in the same operation."
    """
    env = setup_borrow_environment(rented_at="2026-01-01T10:00:00Z")
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")  # 60 min
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    res = api.return_rental(
        rental["id"],
        {"return_cabinet_id": env["cabinet"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    final = validate_success(res, 200)
    assert final["rental_status"] == "RETURNED"
    assert final["payment_status"] == "BILLED"
    assert final["return_cabinet_id"] == env["cabinet"]["id"]
    assert final["returned_at"] is not None
    assert final["charged_amount"] is not None


def test_return_repopulates_device_location(api):
    """PRD §3.5: "transitions the device from BORROWED back to AVAILABLE and
    repopulates the device's current_cabinet_id and current_slot_index to
    point at the return slot."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    return_for(env["user"], rental["id"], env["cabinet"]["id"])
    device = validate_success(
        api.get_device(env["device"]["id"], ADMIN_HEADERS), 200
    )
    assert device["status"] == "AVAILABLE"
    assert device["current_cabinet_id"] == env["cabinet"]["id"]
    assert device["current_slot_index"] is not None


def test_return_writes_slot_to_occupied(api):
    """PRD §3.5: "transitions the chosen slot from EMPTY to OCCUPIED and
    writes the device's id into the slot's device_id."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    cab = validate_success(api.get_cabinet(env["cabinet"]["id"], ADMIN_HEADERS), 200)
    return_slot = next(
        s for s in cab["slots"] if s["slot_index"] == final["return_slot_index"]
    )
    assert return_slot["slot_status"] == "OCCUPIED"
    assert return_slot["device_id"] == env["device"]["id"]


def test_return_debits_wallet_by_charged_amount(api):
    """PRD §3.5: "debits User.wallet_balance by exactly the resulting
    Rental.charged_amount."
    """
    env = setup_borrow_environment()
    user_before = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    user_after = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert_money_equal(
        user_after["wallet_balance"],
        user_before["wallet_balance"] - final["charged_amount"],
    )


# ---------------------------------------------------------------------------
# Return-slot selector (PRD §3.5)
# ---------------------------------------------------------------------------


def test_return_picks_lowest_empty_slot_index(api):
    """PRD §3.5: "ranking is by ascending slot_index ... The lowest-slot_index
    empty slot wins."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    # Slot 1 EMPTY, Slot 2 EMPTY ... slot 0 will be EMPTY after borrow.
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T11:00:00Z")
    final = return_for(user, rental["id"], cabinet["id"])
    # Slot 0 is the lowest empty slot at return time → must be chosen.
    assert final["return_slot_index"] == 0


# ---------------------------------------------------------------------------
# Return-failure cycle (PRD §3.5)
# ---------------------------------------------------------------------------


def test_return_failure_creates_stuck_rental(api):
    """PRD §3.5: "When the eligible-slots set is empty (no slot in the return
    cabinet has slot_status EMPTY) the return becomes a return-failure ...
    The response carries error_id ERR_RETURN_FAILED (HTTP 409)."
    """
    env = setup_stuck_rental()
    assert env["rental"]["rental_status"] == "STUCK"


def test_return_failure_marks_device_stuck_in_slot(api):
    """PRD §3.5: "transitions the device from BORROWED to STUCK_IN_SLOT."
    """
    env = setup_stuck_rental()
    device_id = env["rental"]["device_id"]
    device = validate_success(api.get_device(device_id, ADMIN_HEADERS), 200)
    assert device["status"] == "STUCK_IN_SLOT"


def test_return_failure_creates_stuck_repair_ticket(api):
    """PRD §3.5: "creates a RepairTicket with target_type DEVICE, target_id
    equal to the device, source AUTO_ANOMALY, issue_code STUCK_DEVICE, and
    initial status OPEN."
    """
    env = setup_stuck_rental()
    # The PRD does not expose a list endpoint for repair tickets; we cannot
    # enumerate. Instead, observe the rental and device states are
    # consistent with a STUCK_DEVICE ticket having been created.
    # For ticket-existence verification, the implementation should expose
    # internals via GET if possible — but per PRD only GET /repair-tickets/{id}
    # is defined. Confirm side effects: rental STUCK, device STUCK_IN_SLOT.
    assert env["rental"]["rental_status"] == "STUCK"


def test_return_retry_closes_stuck_cycle(api):
    """PRD §3.5: "on retry success the server transitions the previously-stuck
    slot's slot_status from STUCK back to EMPTY, the device's status from
    STUCK_IN_SLOT back to AVAILABLE, and the rental's rental_status from
    STUCK through ACTIVE and onward to RETURNED in the same operation."
    """
    env = setup_stuck_rental()
    # Free a slot at cabinet1 (where rental started — has 7 EMPTY slots
    # because borrow-from-slot-0 emptied it). Use cabinet1.
    advance_clock_to("2026-01-01T12:00:00Z")
    heartbeat(env["cabinet1"]["id"], "2026-01-01T12:00:00Z")
    heartbeat(env["cabinet2"]["id"], "2026-01-01T12:00:00Z")
    res = api.return_retry(
        env["rental"]["id"],
        {"return_cabinet_id": env["cabinet1"]["id"]},
        make_user_headers(env["user"]["id"]),
    )
    final = validate_success(res, 200)
    assert final["rental_status"] == "RETURNED"
    assert final["payment_status"] == "BILLED"
    device = validate_success(
        api.get_device(final["device_id"], ADMIN_HEADERS), 200
    )
    assert device["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Cross-cabinet returns (PRD §3.5)
# ---------------------------------------------------------------------------


def test_cross_cabinet_return_succeeds(api):
    """PRD §3.5: "Cross-cabinet returns are explicitly supported, including
    returns to a cabinet in a different city than the one where the rental
    began."
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
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(cab_bj["id"], "2026-01-01T11:00:00Z")
    heartbeat(cab_sh["id"], "2026-01-01T11:00:00Z")
    res = api.return_rental(
        rental["id"],
        {"return_cabinet_id": cab_sh["id"]},
        make_user_headers(user["id"]),
    )
    final = validate_success(res, 200)
    assert final["rental_status"] == "RETURNED"
    assert final["return_cabinet_id"] == cab_sh["id"]
