"""Revoking an issued permit fans out through five levels (PRD §3.4).

One revoke call touches the permit, its scheduled legs, the escort reservations
on those legs, each affected escort crew's minute ledger, the floor's transport
status and finally the order's posture — and the second level is conditional,
because a leg already on the road is left alone.
"""

from test_helpers import (
    TEST_USERS,
    add_route_leg,
    api_client,
    depart_leg,
    issue_permit,
    measure_and_release_section,
    open_order,
    pay_permit_fee,
    read_escort_assignment,
    read_escort_crew,
    read_order,
    read_permit,
    read_route_leg,
    read_section,
    record_section,
    register_escort_crew,
    register_hauler,
    register_plant,
    request_permit,
    reserve_escort,
    revoke_permit_payload,
    set_logical_clock,
    validate_success,
)

LEG_ONE_WINDOW = ("2026-08-03T06:00:00.000Z", "2026-08-03T14:00:00.000Z")
LEG_TWO_WINDOW = ("2026-08-04T06:00:00.000Z", "2026-08-04T14:00:00.000Z")


def _issued_permit_with_a_rolling_leg(max_reserved_minutes=1200):
    """An issued AZ permit with leg 1 `IN_TRANSIT` and leg 2 still `SCHEDULED`.

    The floor is 168 inches wide and 150 inches tall in AZ, so the matrix demands
    no escorts and no pilot car and the two-leg fee assembles to 21,000 cents;
    the eight-hour reservation placed on leg 2 is therefore voluntary coverage
    whose release is observable on its own.
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    escort_crew = register_escort_crew(
        endorsement_class="STANDARD",
        buffer_minutes=45,
        max_reserved_minutes=max_reserved_minutes,
    )
    order = open_order(
        plant["id"], section_count=1, destination_state="AZ", wind_zone="I"
    )
    section = record_section(
        order["id"],
        plant["id"],
        section_index=1,
        declared_width_in=168,
        declared_height_in=150,
    )
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(section["id"], state_code="AZ", planned_leg_count=2)
    leg_one = add_route_leg(
        permit["id"],
        hauler["id"],
        sequence_no=1,
        corridor_id="AZ-I10",
        state_code="AZ",
        window_start=LEG_ONE_WINDOW[0],
        window_end=LEG_ONE_WINDOW[1],
    )
    leg_two = add_route_leg(
        permit["id"],
        hauler["id"],
        sequence_no=2,
        corridor_id="AZ-SR87",
        state_code="AZ",
        window_start=LEG_TWO_WINDOW[0],
        window_end=LEG_TWO_WINDOW[1],
    )
    assignment = reserve_escort(
        leg_two["id"],
        escort_crew["id"],
        hauler["id"],
        role="ESCORT",
        window_start=LEG_TWO_WINDOW[0],
        window_end=LEG_TWO_WINDOW[1],
    )
    pay_permit_fee(permit["id"], hauler["id"], 21000)
    issue_permit(permit["id"])
    depart_leg(leg_one["id"], hauler["id"])
    return {
        "plant": plant,
        "hauler": hauler,
        "escort_crew": read_escort_crew(escort_crew["id"]),
        "order": order,
        "section": read_section(section["id"]),
        "permit": read_permit(permit["id"]),
        "leg_one": read_route_leg(leg_one["id"]),
        "leg_two": read_route_leg(leg_two["id"]),
        "assignment": read_escort_assignment(assignment["id"]),
    }


def _revoke(permit_id, reason_code="BRIDGE_POSTING"):
    return validate_success(
        api_client.revoke_permit(
            permit_id,
            revoke_permit_payload(reason_code=reason_code),
            TEST_USERS["permit_desk_headers"],
        )
    )


def test_revocation_cascades_through_leg_escort_ledger_floor_and_posture():
    """PRD §3.4: "The permit moves `ISSUED → REVOKED`. Every route leg of that
    permit whose `status` is `SCHEDULED` moves `SCHEDULED → CANCELLED`; legs
    already `IN_TRANSIT` or `ARRIVED` are left untouched. Because those legs
    cancelled, every reserved escort assignment on them moves `RESERVED →
    RELEASED`. Because those reservations were released, each affected escort
    crew's `reserved_minutes` is recomputed from its surviving reserved
    assignments and its `status` is refreshed, which may return an `OVERBOOKED`
    crew to `AVAILABLE`. Because the floor now has no permit in `ISSUED` status at
    all, the floor moves `DISPATCH_READY → PERMIT_REVOKED_HOLD` or `IN_TRANSIT →
    PERMIT_REVOKED_HOLD`. And because a floor entered a hold state, the order's
    posture is re-derived and lands on `TRANSPORT_BLOCKED`."

    Design: Difficulty/transitive_cascade/permit_revoke_five_level_transport_cascade
    """
    scenario = _issued_permit_with_a_rolling_leg()
    assert scenario["permit"]["status"] == "ISSUED", (
        f"the permit must be ISSUED before revocation, got {scenario['permit']['status']}"
    )
    assert scenario["section"]["transit_status"] == "IN_TRANSIT", (
        "departing leg 1 puts the floor IN_TRANSIT, got "
        f"{scenario['section']['transit_status']}"
    )
    assert scenario["escort_crew"]["reserved_minutes"] == 480, (
        "an eight-hour reservation freezes 480 minutes onto the crew, got "
        f"{scenario['escort_crew']['reserved_minutes']}"
    )

    revoked = _revoke(scenario["permit"]["id"])

    assert revoked["status"] == "REVOKED", (
        f"ISSUED -> REVOKED expected, got {revoked['status']}"
    )
    leg_two = read_route_leg(scenario["leg_two"]["id"])
    assert leg_two["status"] == "CANCELLED", (
        f"the SCHEDULED leg must be cancelled, got {leg_two['status']}"
    )
    assignment = read_escort_assignment(scenario["assignment"]["id"])
    assert assignment["status"] == "RELEASED", (
        "the reservation on the cancelled leg must move RESERVED -> RELEASED, got "
        f"{assignment['status']}"
    )
    crew = read_escort_crew(scenario["escort_crew"]["id"])
    assert crew["reserved_minutes"] == 0, (
        "with no surviving reserved assignment the crew's ledger recomputes to 0, "
        f"got {crew['reserved_minutes']}"
    )
    assert crew["status"] == "AVAILABLE", (
        f"the refreshed crew status must be AVAILABLE, got {crew['status']}"
    )
    section = read_section(scenario["section"]["id"])
    assert section["transit_status"] == "PERMIT_REVOKED_HOLD", (
        "the floor has no ISSUED permit left, so it moves IN_TRANSIT -> "
        f"PERMIT_REVOKED_HOLD, got {section['transit_status']}"
    )
    order = read_order(scenario["order"]["id"])
    assert order["posture"] == "TRANSPORT_BLOCKED", (
        "a floor in a hold state drives the order's posture to TRANSPORT_BLOCKED, "
        f"got {order['posture']}"
    )


def test_revocation_cancels_the_scheduled_leg_and_leaves_the_rolling_one_alone():
    """PRD §3.4: "Every route leg of that permit whose `status` is `SCHEDULED`
    moves `SCHEDULED → CANCELLED`; legs already `IN_TRANSIT` or `ARRIVED` are left
    untouched."
    PRD §3.4: "Every row mutated anywhere in that chain has its `version` raised by
    one."

    Design: Difficulty/transitive_cascade/permit_revoke_five_level_transport_cascade
    """
    scenario = _issued_permit_with_a_rolling_leg()
    leg_one_before = scenario["leg_one"]
    leg_two_before = scenario["leg_two"]

    assert leg_one_before["status"] == "IN_TRANSIT", (
        f"leg 1 must already be rolling, got {leg_one_before['status']}"
    )
    assert leg_two_before["status"] == "SCHEDULED", (
        f"leg 2 must still be SCHEDULED, got {leg_two_before['status']}"
    )

    _revoke(scenario["permit"]["id"])

    leg_one_after = read_route_leg(leg_one_before["id"])
    leg_two_after = read_route_leg(leg_two_before["id"])

    assert leg_one_after["status"] == "IN_TRANSIT", (
        "a leg already on the road is left untouched by the revocation, expected "
        f"IN_TRANSIT, got {leg_one_after['status']}"
    )
    assert leg_one_after["version"] == leg_one_before["version"], (
        "an untouched leg is not mutated, so its version must not rise: expected "
        f"{leg_one_before['version']}, got {leg_one_after['version']}"
    )
    assert leg_two_after["status"] == "CANCELLED", (
        f"the not-yet-departed leg is cancelled, got {leg_two_after['status']}"
    )
    assert leg_two_after["version"] > leg_two_before["version"], (
        "the cancelled leg was mutated, so its version must rise: was "
        f"{leg_two_before['version']}, got {leg_two_after['version']}"
    )


def test_revocation_returns_an_overbooked_escort_crew_to_available():
    """PRD §3.4: "Because those reservations were released, each affected escort
    crew's `reserved_minutes` is recomputed from its surviving reserved assignments
    and its `status` is refreshed, which may return an `OVERBOOKED` crew to
    `AVAILABLE`."
    PRD §3.5: "A crew's `reserved_minutes` is never incremented; it is recomputed in
    full as the sum of the frozen `reserved_minutes` of every one of that crew's
    reservations currently in `RESERVED` status."

    Design: Difficulty/transitive_cascade/permit_revoke_five_level_transport_cascade
    """
    scenario = _issued_permit_with_a_rolling_leg(max_reserved_minutes=240)
    crew_before = scenario["escort_crew"]

    assert crew_before["reserved_minutes"] == 480, (
        "the eight-hour reservation freezes 480 minutes onto the crew, got "
        f"{crew_before['reserved_minutes']}"
    )
    assert crew_before["status"] == "OVERBOOKED", (
        "480 booked minutes exceed a 240-minute ceiling, so the crew must read "
        f"OVERBOOKED, got {crew_before['status']}"
    )

    _revoke(scenario["permit"]["id"])

    crew_after = read_escort_crew(crew_before["id"])
    assert crew_after["reserved_minutes"] == 0, (
        "the released reservation contributes nothing, so the ledger recomputes to "
        f"0, got {crew_after['reserved_minutes']}"
    )
    assert crew_after["status"] == "AVAILABLE", (
        "with no booked minutes left the refreshed status returns to AVAILABLE, got "
        f"{crew_after['status']}"
    )
    assert read_escort_assignment(scenario["assignment"]["id"])["status"] == "RELEASED", (
        "the reservation on the cancelled leg must have been released"
    )
