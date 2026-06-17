"""Reservation / agreement / unit / ticket state machines, branching closes, and
the return → inspection → close → out-of-service → ticket cascade.

Covers difficulty rules non_linear_state_machine, transitive_cascade,
compensating_invariant, plus the corner state_machines instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_yard, create_reservation, setup_picked_up_agreement,
    setup_returned_pending_inspection, setup_closed_agreement,
    setup_out_of_service_unit, return_agreement, inspect,
    find_agreement_for_reservation, pull_unit_out_of_service, set_clock,
    create_maintenance_ticket_payload, TEST_USERS,
)

YM = TEST_USERS["yard_manager_headers"]
AGENT = TEST_USERS["rental_agent_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ─── non_linear_state_machine: agreement branch ──────────────────

def test_agreement_closes_clean_unit_returns_available(api):
    """PRD §3.6: "When the inspection yields no net damage, the agreement moves
    RETURNED_PENDING_INSPECTION → CLOSED."
    PRD §3.6: "If the inspection found no damage (damage_assessed_cents is 0) and
    the unit's lifetime_rental_days plus this agreement's billed days remains
    strictly below service_due_at_days, the unit returns to the pool:
    availability_state moves ON_RENT → AVAILABLE and its version increments."

    Design: Difficulty/non_linear_state_machine/agreement_branch_closed_vs_closed_with_damage
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=0)
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    assert ag["agreement_state"] == "CLOSED"
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "AVAILABLE"


def test_agreement_closes_with_damage_unit_out_of_service(api):
    """PRD §3.6: "When the inspection yields positive net damage, it moves
    RETURNED_PENDING_INSPECTION → CLOSED_WITH_DAMAGE, and the server creates a
    DamageCharge".
    PRD §3.6: "whenever damage_assessed_cents is greater than 0 ... the unit moves
    ON_RENT → OUT_OF_SERVICE, its version increments".

    Design: Difficulty/non_linear_state_machine/agreement_branch_closed_vs_closed_with_damage
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=9000)
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    assert ag["agreement_state"] == "CLOSED_WITH_DAMAGE"
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "OUT_OF_SERVICE"


# ─── non_linear_state_machine: equipment unit branch ─────────────

def test_unit_forks_to_on_rent_on_pickup(api):
    """PRD §3.5: "On success the server sets the unit availability_state to
    ON_RENT, sets its fuel_level_liters to the catalog item's fuel_capacity_liters,
    increments the unit's version, and opens a RentalAgreement in ON_RENT."

    Design: Difficulty/non_linear_state_machine/equipment_unit_branch_available_forks_to_on_rent_vs_out_of_service
    """
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "ON_RENT"


def test_unit_forks_to_out_of_service_on_manual_pull(api):
    """PRD §3.2: "This manual pull is only valid when the unit is currently
    AVAILABLE; it sets the unit's availability_state from AVAILABLE to
    OUT_OF_SERVICE, increments the unit's version, and creates the ticket in the
    OPEN state."

    Design: Difficulty/non_linear_state_machine/equipment_unit_branch_available_forks_to_on_rent_vs_out_of_service
    """
    ctx = setup_yard()
    ticket = pull_unit_out_of_service(ctx["unit"]["id"], reason="SCHEDULED_SERVICE")
    assert ticket["ticket_state"] == "OPEN"
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "OUT_OF_SERVICE"


# ─── transitive_cascade: depth-3 damage cascade ──────────────────

def test_damage_return_cascade_opens_maintenance_ticket(api):
    """PRD §3.6: "The full cascade therefore reads return → inspection → agreement
    close → unit out of service → maintenance ticket open."
    PRD §3.6: "the server auto-creates a MaintenanceTicket in OPEN whose
    opened_by_agreement_id is this agreement and whose reason is DAMAGE_REPAIR when
    damage was assessed".

    Design: Difficulty/transitive_cascade/inspection_damage_cascade_depth3_to_maintenance_ticket
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=15000)
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    assert ag["agreement_state"] == "CLOSED_WITH_DAMAGE"
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "OUT_OF_SERVICE"
    tickets, _ = _list(api.list_maintenance_tickets(
        YM, params={"opened_by_agreement_id": ctx["agreement"]["id"]}))
    assert len(tickets) == 1
    assert tickets[0]["ticket_state"] == "OPEN"
    assert tickets[0]["reason"] == "DAMAGE_REPAIR"


def test_damage_return_cascade_closes_reservation_fulfilled(api):
    """PRD §3.6: "The account's outstanding_balance_cents is then recomputed, and
    the linked reservation transitions ON_RENT → FULFILLED."

    Design: Difficulty/transitive_cascade/inspection_damage_cascade_depth3_to_maintenance_ticket
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=15000)
    res = validate_success(
        api.get_reservation(ctx["reservation"]["id"], YM), 200)
    assert res["reservation_state"] == "FULFILLED"


# ─── transitive_cascade: depth-2 confirm → ledger → balance ──────

def test_confirm_posts_deposit_hold_and_recomputes_balance(api):
    """PRD §3.4: "Once all checks pass, the server posts a DEPOSIT_HOLD ledger
    entry for the deposit amount and recomputes the account's
    outstanding_balance_cents."

    Design: Difficulty/transitive_cascade/confirm_cascade_depth2_deposit_hold_then_balance
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    assert r["reservation_state"] == "CONFIRMED"
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "AVAILABLE"
    acct = validate_success(
        api.get_contractor_account(ctx["account"]["id"], YM), 200)
    assert acct["outstanding_balance_cents"] == 50000


def test_confirm_deposit_hold_appears_on_ledger(api):
    """PRD §2.9: "Every charge, hold, refund, and payment is an append-only
    AccountLedgerEntry carrying a signed amount_cents."
    PRD §3.4: "the server posts a DEPOSIT_HOLD ledger entry for the deposit amount".

    Design: Difficulty/transitive_cascade/confirm_cascade_depth2_deposit_hold_then_balance
    """
    ctx = setup_yard()
    create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                       rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    entries, _ = _list(api.list_account_ledger(
        ctx["account"]["id"], YM, params={"entry_type": "DEPOSIT_HOLD"}))
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 50000
    assert entries[0]["entry_type"] == "DEPOSIT_HOLD"


# ─── compensating_invariant ──────────────────────────────────────

def test_cancel_reverses_deposit_hold_balance_conserved(api):
    """PRD §3.4: "Cancelling moves the reservation to the terminal CANCELLED state
    and posts a DEPOSIT_REFUND ledger entry reversing the original deposit hold,
    after which the account balance is recomputed."

    Design: Difficulty/compensating_invariant/cancel_reverses_deposit_hold_account_balance_conserved
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    validate_success(api.cancel_reservation(r["id"], AGENT), 200)
    acct = validate_success(
        api.get_contractor_account(ctx["account"]["id"], YM), 200)
    assert acct["outstanding_balance_cents"] == 0


def test_cancel_leaves_unit_available(api):
    """PRD §3.4: "Because confirming never changed the unit's availability_state,
    cancellation simply frees the future booking interval."

    Design: Difficulty/compensating_invariant/cancel_reverses_deposit_hold_account_balance_conserved
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    validate_success(api.cancel_reservation(r["id"], AGENT), 200)
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "AVAILABLE"


def test_resolve_ticket_restores_available_count(api):
    """PRD §3.2: "only when no other OPEN MaintenanceTicket remains on that unit
    does the resolution set the unit's availability_state back to AVAILABLE and
    increment its version."

    Design: Difficulty/compensating_invariant/maintenance_resolve_restores_available_unit_count_conserved
    """
    ctx = setup_out_of_service_unit()
    validate_success(
        api.resolve_maintenance_ticket(ctx["ticket"]["id"], YM), 200)
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "AVAILABLE"
    item = validate_success(api.get_catalog_item(ctx["item"]["id"], YM), 200)
    assert item["available_unit_count"] == 1


def test_resolve_ticket_sets_ticket_resolved(api):
    """PRD §3.2: "Resolving a ticket is a YardManager action that moves it from
    OPEN to RESOLVED; it requires the ticket be OPEN".

    Design: Difficulty/compensating_invariant/maintenance_resolve_restores_available_unit_count_conserved
    """
    ctx = setup_out_of_service_unit()
    ticket = validate_success(
        api.resolve_maintenance_ticket(ctx["ticket"]["id"], YM), 200)
    assert ticket["ticket_state"] == "RESOLVED"


# ─── corner: state_machines ──────────────────────────────────────

def test_cancel_already_cancelled_reservation_invalid_state(api):
    """PRD §3.4: "Cancelling a reservation that is not CONFIRMED is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/cancel_already_cancelled_reservation_returns_invalid_state
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    validate_success(api.cancel_reservation(r["id"], AGENT), 200)
    res = api.cancel_reservation(r["id"], AGENT)
    validate_error(res, "ERR_INVALID_STATE")
    acct = validate_success(
        api.get_contractor_account(ctx["account"]["id"], YM), 200)
    assert acct["outstanding_balance_cents"] == 0


def test_return_closed_agreement_invalid_state(api):
    """PRD §3.6: "Marking a return on an agreement that is not ON_RENT is rejected
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/return_agreement_from_terminal_closed_returns_invalid_state
    """
    ctx = setup_closed_agreement(clean=True, reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    res = api.return_agreement(ctx["agreement"]["id"], AGENT)
    validate_error(res, "ERR_INVALID_STATE")


def test_pickup_delivery_only_item_returns_delivery_required(api):
    """PRD §3.4: "requesting PICKUP for a catalog item whose requires_delivery is
    true is rejected with ERR_DELIVERY_REQUIRED (HTTP 422)."

    Design: Corner/state_machines/pickup_delivery_only_item_returns_delivery_required
    """
    ctx = setup_yard(item_overrides={"requires_delivery": True})
    res = api.create_reservation({
        "contractor_account_id": ctx["account"]["id"],
        "catalog_item_id": ctx["item"]["id"],
        "equipment_unit_id": ctx["unit"]["id"],
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False,
    }, AGENT)
    validate_error(res, "ERR_DELIVERY_REQUIRED")


def test_dispatch_pickup_reservation_returns_wrong_fulfillment(api):
    """PRD §3.5: "The request must target a DELIVERY reservation — dispatching a
    PICKUP reservation is rejected with ERR_WRONG_FULFILLMENT (HTTP 422)".

    Design: Corner/state_machines/dispatch_on_pickup_reservation_returns_wrong_fulfillment
    """
    ctx = setup_yard()
    truck = validate_success(
        api.create_delivery_truck({"name": "Truck-1", "buffer_minutes": 60}, YM), 201)
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           fulfillment_method="PICKUP",
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    res = api.dispatch_reservation(r["id"], {
        "delivery_truck_id": truck["id"],
        "delivery_window_start": "2026-06-01T09:00:00.000Z",
        "delivery_window_end": "2026-06-01T10:00:00.000Z",
    }, AGENT)
    validate_error(res, "ERR_WRONG_FULFILLMENT")


def test_resolve_already_resolved_ticket_invalid_state(api):
    """PRD §3.2: "Resolving a ticket is a YardManager action that moves it from
    OPEN to RESOLVED; it requires the ticket be OPEN".

    Design: Corner/state_machines/resolve_already_resolved_ticket_returns_invalid_state
    """
    ctx = setup_out_of_service_unit()
    validate_success(
        api.resolve_maintenance_ticket(ctx["ticket"]["id"], YM), 200)
    res = api.resolve_maintenance_ticket(ctx["ticket"]["id"], YM)
    validate_error(res, "ERR_INVALID_STATE")


def test_new_reservation_starts_confirmed(api):
    """PRD §3.4: "On confirmation the reservation enters the CONFIRMED state".

    Design: Corner/state_machines/reservation_starts_in_confirmed_initial_state
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    assert r["reservation_state"] == "CONFIRMED"


def test_reservation_start_in_past_rejected(api):
    """PRD §3.4: "Then the past-date check: rental_start_date must be on or after
    the yard clock's current date, or the request is rejected with
    ERR_START_IN_PAST (HTTP 422)."

    Design: Corner/state_machines/return_in_past_before_start_blocked_start_in_past
    """
    ctx = setup_yard(clock="2026-06-10T08:00:00.000Z")
    res = api.create_reservation({
        "contractor_account_id": ctx["account"]["id"],
        "catalog_item_id": ctx["item"]["id"],
        "equipment_unit_id": ctx["unit"]["id"],
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-05",
        "damage_waiver_opted": False,
    }, AGENT)
    validate_error(res, "ERR_START_IN_PAST")


def test_omitted_unit_empty_pool_returns_no_unit_available(api):
    """PRD §3.4: "If that candidate pool is empty — no available unit of the item
    is free for the interval — the create is rejected with ERR_NO_UNIT_AVAILABLE
    (HTTP 409)."

    Design: Corner/state_machines/no_unit_available_empty_pool_on_omitted_unit
    """
    ctx = setup_yard()
    pull_unit_out_of_service(ctx["unit"]["id"], reason="SCHEDULED_SERVICE")
    res = api.create_reservation({
        "contractor_account_id": ctx["account"]["id"],
        "catalog_item_id": ctx["item"]["id"],
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-05",
        "damage_waiver_opted": False,
    }, AGENT)
    validate_error(res, "ERR_NO_UNIT_AVAILABLE")


def _list(response):
    body = response.json()
    return body["data"], body.get("meta", {})
