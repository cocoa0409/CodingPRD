"""Scenario builders: everything that must talk to the API to set a stage.

The builders are layered. Tier 1 creates single rows. Tier 2 composes a
programme with a dated departure. Tier 3 walks a traveler along the booking
dimension. Tier 4 assembles whole departures that are open for sale, and Tier 5
drives the logical clock.

Three PRD rules shape every chain here:

* §3.1 -- a departure may only open for sale when it "already carries at least
  one service booking whose `status` is anything other than `CANCELLED`", so
  every open-for-sale builder first holds a service slot at a sacred site in
  the programme's own destination country.
* §3.5 -- rooming "recomputes the invoice", and enrolment leaves
  `invoice_total_cents` at 0, while §3.7's receipt ceiling is
  `invoice_total_cents` plus `protection_premium_cents`. Cash therefore never
  arrives before the room is assigned.
* §3.5 -- confirmation requires that "The traveler must already have a
  `room_type_assigned`", so rooming also precedes every confirmation.
"""

from __future__ import annotations

from typing import Any

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, HOLY_LAND_DEPOSIT_CENTS
from .factories import (
    advisory_payload,
    agreement_payload,
    air_block_payload,
    departure_payload,
    land_assignment_payload,
    land_resource_payload,
    medical_review_payload,
    negotiation_round_payload,
    open_access_site_payload,
    payment_payload,
    payment_plan_payload,
    pilgrim_payload,
    program_payload,
    protection_payload,
    rooming_payload,
    sacred_site_payload,
    service_booking_payload,
)
from .test_users import TEST_USERS, make_group_leader_headers

# --- Role aliases, so a builder reads as the officer who performs the act ---

PLANNER = TEST_USERS["program_manager"]
PLANNER_SECOND = TEST_USERS["program_manager_second"]
RISK = TEST_USERS["risk_officer"]
RISK_SECOND = TEST_USERS["risk_officer_second"]
AIR_DESK = TEST_USERS["air_desk_agent"]
LAND = TEST_USERS["land_contractor"]
FINANCE = TEST_USERS["finance_controller"]
PROTECTION = TEST_USERS["protection_administrator"]
PROTECTION_REVIEWER = TEST_USERS["protection_reviewer"]
PROTECTION_APPROVER = TEST_USERS["protection_approver"]


# ===========================================================================
# Tier 5 -- the logical clock (PRD §2.4)
# ===========================================================================


def set_clock(current_utc: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Move the server's logical clock to an explicit RFC3339 UTC instant."""
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, headers or PLANNER)
    )


def reset_clock() -> dict[str, Any]:
    return set_clock(DEFAULT_CLOCK)


# ===========================================================================
# Tier 1 -- single rows
# ===========================================================================


def create_program(payload: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    body = payload if payload is not None else program_payload(**overrides)
    return get_success_data(api_client.create_program(body, PLANNER))


def create_departure(program_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_departure(departure_payload(program_id, **overrides), PLANNER)
    )


def create_sacred_site(**overrides: Any) -> dict[str, Any]:
    return get_success_data(api_client.create_sacred_site(sacred_site_payload(**overrides), PLANNER))


def create_open_access_site(**overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_sacred_site(open_access_site_payload(**overrides), PLANNER)
    )


def create_service_booking(
    departure_id: str, sacred_site_id: str, **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api_client.create_service_booking(
            service_booking_payload(departure_id, sacred_site_id, **overrides), PLANNER
        )
    )


def create_land_resource(**overrides: Any) -> dict[str, Any]:
    return get_success_data(api_client.create_land_resource(land_resource_payload(**overrides), LAND))


def create_land_assignment(
    land_resource_id: str, departure_id: str, **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api_client.create_land_assignment(
            land_assignment_payload(land_resource_id, departure_id, **overrides), LAND
        )
    )


def countersign_land_assignment(land_assignment_id: str) -> dict[str, Any]:
    return get_success_data(api_client.countersign_land_assignment(land_assignment_id, LAND))


def create_air_block(departure_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_air_block(air_block_payload(departure_id, **overrides), AIR_DESK)
    )


def create_advisory(**overrides: Any) -> dict[str, Any]:
    return get_success_data(api_client.create_advisory(advisory_payload(**overrides), RISK))


def publish_advisory(advisory_id: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return get_success_data(api_client.publish_advisory(advisory_id, headers or RISK))


def read_advisory(advisory_id: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return get_success_data(api_client.get_advisory(advisory_id, headers or RISK))


# ===========================================================================
# Tier 2 -- a programme with a dated departure
# ===========================================================================


def program_with_departure(
    program_overrides: dict[str, Any] | None = None,
    departure_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a programme and one departure of it, both in their opening state."""
    program = create_program(**(program_overrides or {}))
    departure = create_departure(program["id"], **(departure_overrides or {}))
    return program, departure


def hold_filler_service(program: dict[str, Any], departure: dict[str, Any]) -> dict[str, Any]:
    """Give a departure the non-cancelled itinerary that opening sales requires.

    Uses an open-access site with no turnaround buffer and no clergy
    requirement, in the programme's own `destination_country`, at an instant
    chosen not to collide with any booking a test makes for itself.
    """
    site = create_open_access_site(country=program["destination_country"])
    return create_service_booking(
        departure["id"],
        site["id"],
        service_type="PRAYER_SERVICE",
        scheduled_start_utc="2026-10-01T01:00:00Z",
        duration_minutes=30,
        pax_count=1,
    )


def open_sales(departure_id: str) -> dict[str, Any]:
    return get_success_data(api_client.open_departure_sales(departure_id, PLANNER))


def close_sales(departure_id: str) -> dict[str, Any]:
    return get_success_data(api_client.close_departure_sales(departure_id, PLANNER))


def read_departure(departure_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_departure(departure_id, PLANNER))


def open_departure(
    program_overrides: dict[str, Any] | None = None,
    departure_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A programme plus a departure already `OPEN_FOR_SALE`, itinerary included.

    Returns `{"program", "departure", "service_booking"}` where `departure` is
    the row as it stands after opening.
    """
    program, departure = program_with_departure(program_overrides, departure_overrides)
    service_booking = hold_filler_service(program, departure)
    opened = open_sales(departure["id"])
    return {"program": program, "departure": opened, "service_booking": service_booking}


# ===========================================================================
# Tier 3 -- one traveler along the booking dimension
# ===========================================================================


def enrol_traveler(departure_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_pilgrim(pilgrim_payload(departure_id, **overrides), PLANNER)
    )


def enrol_traveler_as_leader(
    departure_id: str, agreement_id: str, **overrides: Any
) -> dict[str, Any]:
    """A leader books one of their own recruits, threading the agreement id."""
    payload = pilgrim_payload(
        departure_id, recruited_by_agreement_id=agreement_id, **overrides
    )
    return get_success_data(
        api_client.create_pilgrim(payload, make_group_leader_headers(agreement_id))
    )


def assign_room(pilgrim_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.assign_rooming(pilgrim_id, rooming_payload(**overrides), PLANNER)
    )


def pay(pilgrim_id: str, amount_cents: int, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.record_payment(pilgrim_id, payment_payload(amount_cents, **overrides), FINANCE)
    )


def confirm_traveler(pilgrim_id: str) -> dict[str, Any]:
    return get_success_data(api_client.confirm_pilgrim(pilgrim_id, PLANNER))


def read_traveler(pilgrim_id: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return get_success_data(api_client.get_pilgrim(pilgrim_id, headers or PLANNER))


def roomed_traveler(departure_id: str, room_overrides: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """Enrol a traveler and assign the room, so the invoice is live."""
    traveler = enrol_traveler(departure_id, **overrides)
    return assign_room(traveler["id"], **(room_overrides or {}))


def deposited_traveler(
    departure_id: str,
    deposit_cents: int = HOLY_LAND_DEPOSIT_CENTS,
    room_overrides: dict[str, Any] | None = None,
    method: str = "ACH",
    **overrides: Any,
) -> dict[str, Any]:
    """Enrol, room, then take the deposit that crosses the threshold."""
    traveler = roomed_traveler(departure_id, room_overrides, **overrides)
    pay(traveler["id"], deposit_cents, method=method)
    return read_traveler(traveler["id"])


def confirmed_traveler(
    departure_id: str,
    deposit_cents: int = HOLY_LAND_DEPOSIT_CENTS,
    room_overrides: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Enrol, room, deposit, then confirm for travel."""
    traveler = deposited_traveler(
        departure_id, deposit_cents, room_overrides=room_overrides, **overrides
    )
    return confirm_traveler(traveler["id"])


def fully_paid_traveler(
    departure_id: str,
    deposit_cents: int = HOLY_LAND_DEPOSIT_CENTS,
    room_overrides: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Carry a traveler all the way to `PAID_IN_FULL` after confirmation."""
    traveler = confirmed_traveler(
        departure_id, deposit_cents, room_overrides=room_overrides, **overrides
    )
    balance = traveler["invoice_total_cents"] - traveler["cash_applied_cents"]
    if balance > 0:
        pay(traveler["id"], balance)
    return read_traveler(traveler["id"])


# ===========================================================================
# Tier 3 -- the money dimension
# ===========================================================================


def create_plan(
    pilgrim_id: str, plan_type: str, first_due_date: str, **overrides: Any
) -> dict[str, Any]:
    """Read the traveler for its current `version`, then create the plan."""
    traveler = read_traveler(pilgrim_id, FINANCE)
    return get_success_data(
        api_client.create_payment_plan(
            pilgrim_id,
            payment_plan_payload(plan_type, first_due_date, traveler["version"], **overrides),
            FINANCE,
        )
    )


def read_plan(payment_plan_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_payment_plan(payment_plan_id, FINANCE))


def read_receipt(payment_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_payment(payment_id, FINANCE))


def run_sweep(departure_id: str) -> dict[str, Any]:
    return get_success_data(api_client.run_payment_sweep(departure_id, FINANCE))


# ===========================================================================
# Tier 3 -- the protection dimension
# ===========================================================================


def quote_protection(pilgrim_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_protection(protection_payload(pilgrim_id, **overrides), PROTECTION)
    )


def review_protection(
    protection_id: str, headers: dict[str, str] | None = None, **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api_client.medical_review_protection(
            protection_id, medical_review_payload(**overrides), headers or PROTECTION_REVIEWER
        )
    )


def decide_waiver(
    protection_id: str, decision: str, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    return get_success_data(
        api_client.decide_waiver(
            protection_id, {"decision": decision}, headers or PROTECTION_APPROVER
        )
    )


def purchase_protection(protection_id: str) -> dict[str, Any]:
    return get_success_data(api_client.purchase_protection(protection_id, PROTECTION))


def read_protection(protection_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_protection(protection_id, PROTECTION))


def purchased_protection(pilgrim_id: str, **overrides: Any) -> dict[str, Any]:
    """Quote then bind a policy with no waiver in play."""
    protection = quote_protection(pilgrim_id, **overrides)
    return purchase_protection(protection["id"])


# ===========================================================================
# Tier 3 -- the air dimension
# ===========================================================================


def offer_fare(air_block_id: str, fare_cents: int, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.add_negotiation_round(
            air_block_id,
            negotiation_round_payload("CARRIER_OFFER", fare_cents, **overrides),
            AIR_DESK,
        )
    )


def counter_fare(air_block_id: str, fare_cents: int, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.add_negotiation_round(
            air_block_id,
            negotiation_round_payload("OPERATOR_COUNTER", fare_cents, **overrides),
            AIR_DESK,
        )
    )


def confirmed_air_block(
    departure_id: str, offered_fare_cents: int = 810_000, **overrides: Any
) -> dict[str, Any]:
    """Open a block, take one carrier offer, then contract it."""
    block = create_air_block(departure_id, **overrides)
    offer_fare(block["id"], offered_fare_cents)
    return get_success_data(api_client.confirm_air_block(block["id"], AIR_DESK))


def read_air_block(air_block_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_air_block(air_block_id, AIR_DESK))


def file_ticket_name(pilgrim_id: str, ticketed_name: str) -> dict[str, Any]:
    return get_success_data(
        api_client.submit_ticket_name(pilgrim_id, {"ticketed_name": ticketed_name}, AIR_DESK)
    )


# ===========================================================================
# Tier 4 -- leader agreements
# ===========================================================================


def offer_agreement(departure_id: str, **overrides: Any) -> dict[str, Any]:
    """Read the departure for its current `version`, then offer the agreement."""
    departure = read_departure(departure_id)
    return get_success_data(
        api_client.create_agreement(
            agreement_payload(departure_id, departure["version"], **overrides), PLANNER
        )
    )


def active_agreement(departure_id: str, **overrides: Any) -> dict[str, Any]:
    """Offer an agreement and have the leader countersign it."""
    agreement = offer_agreement(departure_id, **overrides)
    return get_success_data(
        api_client.countersign_agreement(
            agreement["id"], make_group_leader_headers(agreement["id"])
        )
    )


def read_agreement(agreement_id: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return get_success_data(api_client.get_agreement(agreement_id, headers or PLANNER))


def settle_agreement(agreement_id: str) -> dict[str, Any]:
    return get_success_data(api_client.settle_agreement(agreement_id, FINANCE))


# ===========================================================================
# Tier 4 -- sacred sites and services
# ===========================================================================


def read_service_booking(service_booking_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_service_booking(service_booking_id, PLANNER))


def clergy_confirm(
    service_booking_id: str, contact_name: str, tradition: str
) -> dict[str, Any]:
    return get_success_data(
        api_client.clergy_confirm_service_booking(
            service_booking_id,
            {"clergy_contact_name": contact_name, "clergy_tradition": tradition},
            PLANNER,
        )
    )


def cancel_service_booking(service_booking_id: str, reason: str) -> dict[str, Any]:
    return get_success_data(
        api_client.cancel_service_booking(
            service_booking_id, {"cancellation_reason": reason}, PLANNER
        )
    )


def read_land_assignment(land_assignment_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_land_assignment(land_assignment_id, LAND))


__all__ = [name for name in dir() if not name.startswith("_")]
