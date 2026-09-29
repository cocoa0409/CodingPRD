"""No second read required: the confirmation response already carries the frozen
price and the recomputed invoice, and the roster counter it moved is live."""

from __future__ import annotations

from test_helpers import (
    api_client,
    assign_room,
    enrol_traveler,
    open_departure,
    pay,
    read_departure,
    validate_success,
    HOLY_LAND_T1_INVOICE_CENTS,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]


def test_the_confirm_response_itself_carries_the_frozen_price_and_invoice(api):
    """PRD §2.11: "Cascades are **immediate and synchronous**: by the time a
    response is returned, every downstream row is already in its final state, and
    a read of any affected row reflects the completed cascade. There is no
    deferred reconciliation and no eventual consistency." PRD §3.5: "A
    `ProgramManager` confirms a traveler, moving `booking_status` from
    `DEPOSITED` to `CONFIRMED`; a free-seat traveler, who never pays a deposit, is
    confirmed directly from `INQUIRY` and is the only exception." And:
    "Confirmation freezes `price_locked_cents` at the departure's current
    `provisional_per_pax_price_cents`, recomputes `invoice_total_cents`,
    recomputes the departure's `paying_pax_count` and provisional tier fields, and
    recomputes the recruiting agreement's snapshot accrual."

    Design: Corner/consistency_model/confirm_response_already_carries_the_repriced_invoice
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    traveler = enrol_traveler(
        departure_id,
        full_name="Traveler A",
        date_of_birth="1975-01-10",
        room_type_requested="DOUBLE",
    )
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="IL-234")
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")

    confirmed = validate_success(api_client.confirm_pilgrim(traveler["id"], PLANNER))

    # Everything asserted here comes out of the confirmation response itself.
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["price_locked_cents"] == 587_000
    assert confirmed["invoice_total_cents"] == HOLY_LAND_T1_INVOICE_CENTS
    assert confirmed["cash_applied_cents"] == 50_000

    live = read_departure(departure_id)
    assert live["paying_pax_count"] == 1
    assert live["provisional_tier_code"] == "T1"
