"""Closures, weather, and the cascades that ripple from attractions to slots,
reservations, refunds, and the venue posture."""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_paginated,
    setup_venue_attraction_slot, create_paid_reservation,
    create_venue, create_attraction, create_staffed_zone,
    set_clock, open_closure, get_attraction_version,
    create_scare_zone_payload, weather_payload, lift_payload,
    TEST_USERS,
)

BOX = TEST_USERS["box_office_headers"]
OPS = TEST_USERS["ops_headers"]
ACTOR = TEST_USERS["actor_headers"]


def test_attraction_cycles_open_paused_open_via_closure_and_lift(api):
    """PRD 3.9: "Opening a closure drives the attraction from OPEN to PAUSED".
    PRD 3.9: "The closure moves to the terminal LIFTED state and its version
    increments. If no other ACTIVE closure remains on the attraction, the attraction
    returns from PAUSED to OPEN".

    A SAFETY closure pauses an OPEN attraction; lifting that lone closure returns it
    to OPEN, completing the OPEN -> PAUSED -> OPEN cycle.

    Design: Difficulty/non_linear_state_machine/nlsm_attraction_closure_cyclic_open_paused_open
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    att_v0 = attraction["version"]

    closure = get_success_data(
        api.create_closure(attraction["id"], {"reason": "SAFETY",
                                              "expected_attraction_version": att_v0}, OPS)
    )
    paused = validate_success(api.get_attraction(attraction["id"], OPS), 200)
    assert paused["status"] == "PAUSED"

    lifted = validate_success(
        api.lift_closure(closure["id"], lift_payload(paused["version"]), OPS), 200
    )
    assert lifted["status"] == "LIFTED"
    reopened = validate_success(api.get_attraction(attraction["id"], OPS), 200)
    assert reopened["status"] == "OPEN"


def test_closure_lift_returns_closure_to_lifted_terminal(api):
    """PRD 3.9: "The operations manager lifts an ACTIVE closure, carrying
    expected_attraction_version ... The closure moves to the terminal LIFTED state
    and its version increments."

    Lifting an ACTIVE closure transitions the closure itself to LIFTED.

    Design: Difficulty/non_linear_state_machine/nlsm_attraction_closure_cyclic_open_paused_open
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    closure = open_closure(attraction["id"], reason="SAFETY")
    assert closure["status"] == "ACTIVE"
    paused = validate_success(api.get_attraction(attraction["id"], OPS), 200)

    lifted = validate_success(
        api.lift_closure(closure["id"], lift_payload(paused["version"]), OPS), 200
    )
    assert lifted["status"] == "LIFTED"


def test_closure_depth3_cascade_pauses_slot_cancels_reservation_refunds_wallet(api):
    """PRD 3.9: "Opening a closure drives the attraction from OPEN to PAUSED ... every
    SCHEDULED slot of the attraction is set to CLOSED. Second — caused by each slot
    closing — every reservation holding a ticket on a now-closed slot whose entry
    state is HELD or RESERVED is moved to CANCELLED. Third — caused by each such
    cancellation where the reservation's payment state was PAID — the payment state
    moves to REFUNDED and the reservation's full total_cents is added to the owning
    guest's wallet_credit_cents. The closure tallies how many reservations it
    auto-refunded on its opened_reservation_refunds".

    A closure on an attraction holding a RESERVED+PAID reservation (total 2410)
    cascades: attraction PAUSED, slot CLOSED, reservation CANCELLED+REFUNDED, guest
    wallet += 2410, closure.opened_reservation_refunds == 1.

    Design: Difficulty/transitive_cascade/tc_depth3_closure_pauses_slot_cancels_reservation_refunds_wallet
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_paid_reservation(venue["id"], slot["id"])
    assert reservation["total_cents"] == 2410

    closure = open_closure(attraction["id"], reason="SAFETY")

    att = validate_success(api.get_attraction(attraction["id"], OPS), 200)
    assert att["status"] == "PAUSED"
    closed_slot = validate_success(api.get_time_slot(slot["id"], BOX), 200)
    assert closed_slot["status"] == "CLOSED"
    res = validate_success(api.get_reservation(reservation["id"], BOX), 200)
    assert res["entry_status"] == "CANCELLED"
    assert res["payment_status"] == "REFUNDED"
    g = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g["wallet_credit_cents"] == 2410
    clo = validate_success(api.get_closure(closure["id"], OPS), 200)
    assert clo["opened_reservation_refunds"] == 1


def test_closure_cascade_cancels_reserved_reservation_via_closed_slot(api):
    """PRD 3.9: "every SCHEDULED slot of the attraction is set to CLOSED. Second —
    caused by each slot closing — every reservation holding a ticket on a now-closed
    slot whose entry state is HELD or RESERVED is moved to CANCELLED."

    A closure on an attraction holding a RESERVED (still UNPAID) reservation drives the
    slot CLOSED and the reservation CANCELLED via the same depth chain, isolating the
    slot-closes-then-reservation-cancels hops without a refund leg.

    Design: Difficulty/transitive_cascade/tc_depth3_closure_pauses_slot_cancels_reservation_refunds_wallet
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    from test_helpers import create_reserved_reservation
    guest, reservation, ticket = create_reserved_reservation(venue["id"], slot["id"])
    assert reservation["entry_status"] == "RESERVED"
    assert reservation["payment_status"] == "UNPAID"

    open_closure(attraction["id"], reason="SAFETY")

    closed_slot = validate_success(api.get_time_slot(slot["id"], BOX), 200)
    assert closed_slot["status"] == "CLOSED"
    res = validate_success(api.get_reservation(reservation["id"], BOX), 200)
    assert res["entry_status"] == "CANCELLED"
    # Unpaid -> no refund: payment stays UNPAID, wallet stays 0.
    assert res["payment_status"] == "UNPAID"
    g = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g["wallet_credit_cents"] == 0


def test_actor_checkout_understaffs_zone_and_pauses_attraction(api):
    """PRD 3.8: "An actor later checks out of a CHECKED_IN shift, moving it to the
    terminal CHECKED_OUT state, lowering the zone's checked_in_count by one, and — if
    checked_in_count thereby falls below min_actors — bubbling the zone down to
    UNDERSTAFFED. When a check-out drops a zone to UNDERSTAFFED, the system raises an
    ACTIVE Closure on that attraction with reason UNDERSTAFFED and runs the
    attraction's pause cascade".

    The only CHECKED_IN actor checking out of a min_actors-1 zone drops it to
    UNDERSTAFFED and pauses the attraction via an UNDERSTAFFED closure.

    Design: Difficulty/transitive_cascade/tc_depth2_actor_checkout_understaffs_zone_opens_closure
    """
    set_clock("2026-10-31T18:30:00Z")
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    zone, shifts = create_staffed_zone(attraction["id"], actor_user_id="actor-9", min_actors=1)
    staffed = validate_success(api.get_scare_zone(zone["id"], OPS), 200)
    assert staffed["staffing_status"] == "STAFFED"

    validate_success(api.check_out_shift(shifts[0]["id"], ACTOR), 200)

    after_zone = validate_success(api.get_scare_zone(zone["id"], OPS), 200)
    assert after_zone["staffing_status"] == "UNDERSTAFFED"
    after_att = validate_success(api.get_attraction(attraction["id"], OPS), 200)
    assert after_att["status"] == "PAUSED"


def test_actor_checkout_cascade_opens_understaffed_closure(api):
    """PRD 3.8: "When a check-out drops a zone to UNDERSTAFFED, the system raises an
    ACTIVE Closure on that attraction with reason UNDERSTAFFED and runs the
    attraction's pause cascade described in Section 3.9."

    The check-out cascade creates an ACTIVE closure carrying reason UNDERSTAFFED on
    the affected attraction.

    Design: Difficulty/transitive_cascade/tc_depth2_actor_checkout_understaffs_zone_opens_closure
    """
    set_clock("2026-10-31T18:30:00Z")
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    zone, shifts = create_staffed_zone(attraction["id"], actor_user_id="actor-8", min_actors=1)

    validate_success(api.check_out_shift(shifts[0]["id"], ACTOR), 200)

    closures_resp = api.list_closures(OPS, params={"attraction_id": attraction["id"]})
    closures, _meta = validate_paginated(closures_resp)
    reasons = [c["reason"] for c in closures if c["status"] == "ACTIVE"]
    assert "UNDERSTAFFED" in reasons, f"expected an UNDERSTAFFED closure, got {reasons}"


def test_weather_severe_shutdown_pauses_open_attractions(api):
    """PRD 3.9: "Setting weather_status to SEVERE puts the venue into SHUTDOWN: every
    OPEN attraction of the venue receives an ACTIVE Closure with reason WEATHER and
    runs the same pause cascade, all sales are blocked, and the venue's version
    increments."

    Setting venue weather SEVERE drives operational_state SHUTDOWN and pauses the
    venue's OPEN attraction.

    Design: Corner/cross_cutting/weather_severe_shutdown_cascade
    """
    venue = create_venue()
    att = create_attraction(venue["id"])
    ven_v0 = venue["version"]

    validate_success(
        api.set_weather(venue["id"], weather_payload("SEVERE", ven_v0), OPS), 200
    )
    refreshed_venue = validate_success(api.get_venue(venue["id"], OPS), 200)
    assert refreshed_venue["operational_state"] == "SHUTDOWN"
    refreshed_att = validate_success(api.get_attraction(att["id"], OPS), 200)
    assert refreshed_att["status"] == "PAUSED"
