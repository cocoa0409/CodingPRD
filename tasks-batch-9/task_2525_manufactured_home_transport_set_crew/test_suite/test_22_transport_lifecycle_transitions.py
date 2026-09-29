"""Transport-side lifecycle transitions: remittance, issuance, the road.

Every test in this module builds its own network, order and floor from scratch,
because each test starts against an empty database.
"""

from test_helpers import (
    ApiErrorId,
    assert_route_leg,
    assert_transport_permit,
    assert_version_incremented,
    depart_leg,
    make_plant_dispatcher_headers,
    make_transport_manager_headers,
    open_order,
    pay_and_issue_permit,
    pay_permit_fee_payload,
    measure_section_payload,
    measure_section,
    read_escort_assignment,
    read_escort_crew,
    read_route_leg,
    read_section,
    record_section,
    register_plant,
    release_section,
    reserve_escort,
    set_logical_clock,
    setup_delivered_order,
    setup_leg_awaiting_escorts,
    validate_error,
    validate_success,
    TEST_USERS,
)

PERMIT_DESK = TEST_USERS["permit_desk_headers"]

# A 168-inch-wide, 150-inch-tall floor moving through AZ on a single corridor
# leg needs no escort, so its fee is the 12,000-cent base plus one 4,500-cent
# leg and nothing else.
SINGLE_LEG_AZ_FEE_CENTS = 16500


class TestPermitRemittanceAndIssuance:
    """The REQUESTED -> FEE_PAID -> ISSUED walk of a transport permit."""

    def test_partial_remittance_leaves_the_permit_requested(self, api):
        """PRD §3.4: "A `TransportManager` remits against the permit by supplying
        an `amount_cents` figure, which is simply added to the permit's
        `paid_amount_cents`. The permit moves `REQUESTED → FEE_PAID` only once the
        accumulated `paid_amount_cents` reaches or exceeds
        `provisional_fee_cents`; a remittance that leaves the total short of the
        provisional fee leaves the permit in `REQUESTED` and only raises the
        running total, so a carrier may pay in instalments. Each remittance
        raises the permit's `version`."
        PRD §3.4: "The subtotal begins at a base of one hundred and twenty
        dollars (12,000 cents). To it is added two dollars fifty (250 cents) for
        every inch by which the width in use exceeds the fourteen-foot free
        allowance of 168 inches, where the excess is zero if the width is at or
        under the allowance. Then forty-five dollars (4,500 cents) is added for
        each leg in the leg count in use, and seventy-five dollars (7,500 cents)
        for each escort the requirement matrix demanded in the same evaluation."

        Design: Corner/state_machines/permit_pay_fee_and_issue_valid_transitions
        """
        scenario = setup_leg_awaiting_escorts()
        permit = scenario["permit"]
        carrier = make_transport_manager_headers(scenario["hauler"]["id"])

        assert_transport_permit(permit)
        assert permit["status"] == "REQUESTED", (
            f"a new permit opens in REQUESTED, got {permit['status']}"
        )
        assert permit["provisional_fee_cents"] == SINGLE_LEG_AZ_FEE_CENTS, (
            f"expected a provisional fee of {SINGLE_LEG_AZ_FEE_CENTS} cents, "
            f"got {permit['provisional_fee_cents']}"
        )

        first = validate_success(
            api.pay_permit_fee(permit["id"], pay_permit_fee_payload(8000), carrier)
        )
        assert first["paid_amount_cents"] == 8000, (
            f"the first instalment must accumulate to 8000, "
            f"got {first['paid_amount_cents']}"
        )
        assert first["status"] == "REQUESTED", (
            "a remittance short of the provisional fee leaves the permit in "
            f"REQUESTED, got {first['status']}"
        )
        assert_version_incremented(first["version"], permit["version"])

        second = validate_success(
            api.pay_permit_fee(permit["id"], pay_permit_fee_payload(8500), carrier)
        )
        assert second["paid_amount_cents"] == SINGLE_LEG_AZ_FEE_CENTS, (
            f"the two instalments must accumulate to {SINGLE_LEG_AZ_FEE_CENTS}, "
            f"got {second['paid_amount_cents']}"
        )
        assert second["status"] == "FEE_PAID", (
            "the instalment that reaches the provisional fee flips the permit to "
            f"FEE_PAID, got {second['status']}"
        )
        assert_version_incremented(second["version"], first["version"])

    def test_issuing_the_paid_permit_dates_it_and_frees_the_floor(self, api):
        """PRD §3.4: "A `PermitDesk` operator issues a permit that is in
        `FEE_PAID`, moving it `FEE_PAID → ISSUED`."
        PRD §3.4: "On success the permit's `valid_until_date` is set to the
        logical clock's current UTC date plus five days, the permit's floor moves
        `PERMIT_PENDING → DISPATCH_READY` — or `PERMIT_REVOKED_HOLD →
        DISPATCH_READY` when a held floor is being re-permitted, which is how a
        revocation hold is cleared — both rows' `version` values rise, and the
        order's posture is re-derived."
        PRD §3.4: "The **final** variant runs at issuance; it uses the floor's
        `measured_width_in` and `measured_height_in`, falling back to the
        declared figures only where a measured figure is still null, and it uses
        the permit's *actual* leg count — the number of that permit's route legs
        whose `status` is `SCHEDULED`, `IN_TRANSIT` or `ARRIVED`. Its result is
        stored as `final_fee_cents`."
        PRD §2.6: "On startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must not fall back to real time under any
        circumstance."

        Design: Corner/state_machines/permit_pay_fee_and_issue_valid_transitions
        """
        scenario = setup_leg_awaiting_escorts()
        permit = scenario["permit"]
        section = scenario["section"]
        carrier = make_transport_manager_headers(scenario["hauler"]["id"])

        assert section["transit_status"] == "PERMIT_PENDING", (
            f"the released floor waits in PERMIT_PENDING, got {section['transit_status']}"
        )
        paid = validate_success(
            api.pay_permit_fee(
                permit["id"],
                pay_permit_fee_payload(SINGLE_LEG_AZ_FEE_CENTS),
                carrier,
            )
        )
        assert paid["status"] == "FEE_PAID", (
            f"covering the provisional fee flips the permit to FEE_PAID, got {paid['status']}"
        )

        issued = validate_success(api.issue_permit(permit["id"], {}, PERMIT_DESK))
        assert issued["status"] == "ISSUED", (
            f"issuance moves FEE_PAID -> ISSUED, got {issued['status']}"
        )
        assert issued["final_fee_cents"] == SINGLE_LEG_AZ_FEE_CENTS, (
            f"expected a final fee of {SINGLE_LEG_AZ_FEE_CENTS} cents on one "
            f"scheduled leg at the measured 168 inches, got {issued['final_fee_cents']}"
        )
        assert issued["valid_until_date"] == "2026-08-06", (
            "valid_until_date is the logical date 2026-08-01 plus five days, "
            f"got {issued['valid_until_date']}"
        )
        assert_version_incremented(issued["version"], paid["version"])

        freed = read_section(section["id"])
        assert freed["transit_status"] == "DISPATCH_READY", (
            "issuance pulls the floor PERMIT_PENDING -> DISPATCH_READY, got "
            f"{freed['transit_status']}"
        )
        assert_version_incremented(freed["version"], section["version"])


def _leg_in_transit_with_one_escort_reservation():
    """A rolling corridor leg covered by a single 480-minute escort reservation.

    The reservation opens with the leg's own window at 06:00Z and closes at
    14:00Z, so its frozen `reserved_minutes` is 480, and the crew's default
    600-minute ceiling leaves it `AVAILABLE`.
    """
    scenario = setup_leg_awaiting_escorts(escort_crews=[{}])
    crew = scenario["escort_crews"][0]
    scenario["escort_crew"] = crew
    scenario["assignment"] = reserve_escort(
        scenario["leg"]["id"],
        crew["id"],
        scenario["hauler"]["id"],
        role="ESCORT",
        window_start="2026-08-03T06:00:00.000Z",
        window_end="2026-08-03T14:00:00.000Z",
    )
    pay_and_issue_permit(scenario["permit"]["id"], scenario["hauler"]["id"])
    depart_leg(scenario["leg"]["id"], scenario["hauler"]["id"])
    return scenario


class TestArrivalConsumesEscortCoverage:
    """Arrival is the consuming terminal edge of a corridor leg."""

    def test_arrival_completes_reservations_and_recomputes_crew_minutes(self, api):
        """PRD §3.5: "Arrival, reported by the same carrier on a leg that is
        `IN_TRANSIT`, moves it `IN_TRANSIT → ARRIVED` and consumes its coverage:
        every reserved escort assignment on that leg moves `RESERVED →
        COMPLETED`, and each affected crew's `reserved_minutes` and `status` are
        recomputed."
        PRD §3.5: "A reservation's own `reserved_minutes` is computed once, at
        creation, as the number of minutes between `window_start` and
        `window_end` — the elapsed seconds divided by sixty, rounded half up to a
        whole minute — and is frozen from then on."
        PRD §3.5: "A crew's `reserved_minutes` is never incremented; it is
        recomputed in full as the sum of the frozen `reserved_minutes` of every
        one of that crew's reservations currently in `RESERVED` status. Released
        and completed reservations contribute nothing."
        PRD §3.5: "After every recomputation the crew's `status` is refreshed:
        `OVERBOOKED` when the total exceeds `max_reserved_minutes`, `AVAILABLE`
        otherwise."

        Design: Corner/state_machines/arrive_completes_escort_assignments_and_releases_minutes
        """
        scenario = _leg_in_transit_with_one_escort_reservation()
        leg = read_route_leg(scenario["leg"]["id"])
        crew_before = read_escort_crew(scenario["escort_crew"]["id"])
        carrier = make_transport_manager_headers(scenario["hauler"]["id"])

        assert leg["status"] == "IN_TRANSIT", (
            f"the departed leg is IN_TRANSIT before arrival, got {leg['status']}"
        )
        assert crew_before["reserved_minutes"] == 480, (
            "an 06:00Z-14:00Z reservation freezes 480 minutes onto the crew, got "
            f"{crew_before['reserved_minutes']}"
        )
        assert crew_before["status"] == "AVAILABLE", (
            f"480 minutes is under the 600-minute ceiling, got {crew_before['status']}"
        )

        arrived = validate_success(api.arrive_route_leg(leg["id"], {}, carrier))
        assert_route_leg(arrived)
        assert arrived["status"] == "ARRIVED", (
            f"arrival moves IN_TRANSIT -> ARRIVED, got {arrived['status']}"
        )

        assignment = read_escort_assignment(scenario["assignment"]["id"])
        assert assignment["status"] == "COMPLETED", (
            "arrival consumes the reservation as COMPLETED rather than RELEASED, "
            f"got {assignment['status']}"
        )
        assert assignment["reserved_minutes"] == 480, (
            "the reservation's own minutes are frozen at creation, got "
            f"{assignment['reserved_minutes']}"
        )

        crew_after = read_escort_crew(scenario["escort_crew"]["id"])
        assert crew_after["reserved_minutes"] == 0, (
            "a completed reservation contributes nothing to the crew's total, got "
            f"{crew_after['reserved_minutes']}"
        )
        assert crew_after["status"] == "AVAILABLE", (
            f"a crew with no reserved minutes is AVAILABLE, got {crew_after['status']}"
        )

    def test_arrival_on_the_highest_sequence_leg_delivers_the_floor(self, api):
        """PRD §3.5: "Whether the floor is now home depends on the leg's
        position: when the arriving leg carries the highest `sequence_no` among
        that permit's legs whose `status` is `SCHEDULED`, `IN_TRANSIT` or
        `ARRIVED`, the floor moves `IN_TRANSIT → DELIVERED`; arriving on any
        earlier leg leaves the floor in `IN_TRANSIT`."
        PRD §3.5: "Either way the versions of every mutated row rise and the
        order's posture is re-derived."

        Design: Corner/state_machines/arrive_completes_escort_assignments_and_releases_minutes
        """
        scenario = _leg_in_transit_with_one_escort_reservation()
        leg_before = read_route_leg(scenario["leg"]["id"])
        section_before = read_section(scenario["section"]["id"])
        carrier = make_transport_manager_headers(scenario["hauler"]["id"])

        assert section_before["transit_status"] == "IN_TRANSIT", (
            "departure put the floor on the road, got "
            f"{section_before['transit_status']}"
        )

        arrived = validate_success(api.arrive_route_leg(leg_before["id"], {}, carrier))
        assert arrived["status"] == "ARRIVED", (
            f"the sole leg arrives, got {arrived['status']}"
        )
        assert_version_incremented(arrived["version"], leg_before["version"])

        section_after = read_section(scenario["section"]["id"])
        assert section_after["transit_status"] == "DELIVERED", (
            "the only leg carries the highest sequence_no, so its arrival delivers "
            f"the floor, got {section_after['transit_status']}"
        )
        assert_version_incremented(
            section_after["version"], section_before["version"]
        )


class TestArrivedLegIsTerminal:
    """`ARRIVED` accepts neither of the two triggers the leg machine knows."""

    def test_replaying_depart_on_an_arrived_leg_is_refused(self, api):
        """PRD §3.5: "Five conditions guard it: the leg is `SCHEDULED`, the
        acting `X-User-ID` equals the leg's `hauler_id`, the leg's permit is in
        `ISSUED` status, the carrier's `status` is `ACTIVE`, and every reserved
        escort assignment on the leg belongs to a crew whose `status` is
        `AVAILABLE`."
        PRD §3.5: "A new leg opens at `status` `SCHEDULED`; `ARRIVED` and
        `CANCELLED` are terminal."
        PRD §2.10: "**Priority 7** — the addressed row's current state permits
        the requested transition. Applies to every action endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/depart_and_arrive_on_arrived_leg_return_invalid_state
        """
        scenario = setup_delivered_order()
        leg = read_route_leg(scenario["legs"][0]["id"])
        carrier = make_transport_manager_headers(scenario["hauler"]["id"])

        assert leg["status"] == "ARRIVED", (
            f"the delivered floor's leg has arrived, got {leg['status']}"
        )

        validate_error(
            api.depart_route_leg(leg["id"], {}, carrier),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        after = read_route_leg(leg["id"])
        assert after["status"] == "ARRIVED", (
            f"the refused replay leaves the leg ARRIVED, got {after['status']}"
        )
        assert after["version"] == leg["version"], (
            "a rejected call mutates nothing, so the version must stay at "
            f"{leg['version']}, got {after['version']}"
        )

    def test_replaying_arrive_on_an_arrived_leg_is_refused(self, api):
        """PRD §3.5: "Arrival, reported by the same carrier on a leg that is
        `IN_TRANSIT`, moves it `IN_TRANSIT → ARRIVED` and consumes its coverage:
        every reserved escort assignment on that leg moves `RESERVED →
        COMPLETED`, and each affected crew's `reserved_minutes` and `status` are
        recomputed."
        PRD §3.5: "A new leg opens at `status` `SCHEDULED`; `ARRIVED` and
        `CANCELLED` are terminal."
        PRD §2.10: "All the specialised readiness rules below are evaluated only
        once the base transition is legal, so a row sitting in a terminal state
        always yields `ERR_INVALID_STATE` rather than a domain-specific
        complaint."

        Design: Corner/state_machines/depart_and_arrive_on_arrived_leg_return_invalid_state
        """
        scenario = setup_delivered_order()
        leg = read_route_leg(scenario["legs"][0]["id"])
        section = read_section(scenario["sections"][0]["id"])
        carrier = make_transport_manager_headers(scenario["hauler"]["id"])

        validate_error(
            api.arrive_route_leg(leg["id"], {}, carrier),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        after_leg = read_route_leg(leg["id"])
        after_section = read_section(section["id"])
        assert after_leg["status"] == "ARRIVED", (
            f"the leg stays ARRIVED, got {after_leg['status']}"
        )
        assert after_leg["version"] == leg["version"], (
            f"no version bump on a rejected call, got {after_leg['version']}"
        )
        assert after_section["transit_status"] == "DELIVERED", (
            "the refused replay does not re-fire the floor transition, got "
            f"{after_section['transit_status']}"
        )
        assert after_section["version"] == section["version"], (
            "the floor is delivered exactly once, so its version must stay at "
            f"{section['version']}, got {after_section['version']}"
        )


def _released_floor():
    """A single floor measured once at 170 inches and released once."""
    set_logical_clock()
    plant = register_plant()
    order = open_order(plant["id"])
    section = record_section(order["id"], plant["id"])
    measure_section(section["id"], plant["id"], 170, 150)
    released = release_section(section["id"], plant["id"])
    return plant, released


class TestSectionMeasureAndReleaseAreOnceOnly:
    """Plant QC's two edges each exist exactly once per floor."""

    def test_releasing_an_already_released_floor_is_refused(self, api):
        """PRD §3.2: "Releasing the floor to the permit desk then moves it
        `MEASURED → PERMIT_PENDING`, again only for the owning plant's
        dispatcher."
        PRD §3.2: "Both steps raise the floor's `version` and trigger a
        recomputation of the order's posture; a floor whose owning plant does not
        match the caller is refused with `ERR_NOT_RESOURCE_OWNER`, and a floor in
        the wrong transport status is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/section_measure_and_release_are_once_only
        """
        plant, released = _released_floor()
        dispatcher = make_plant_dispatcher_headers(plant["id"])

        assert released["transit_status"] == "PERMIT_PENDING", (
            "the released floor sits in PERMIT_PENDING, got "
            f"{released['transit_status']}"
        )

        validate_error(
            api.release_section(released["id"], {}, dispatcher),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        after = read_section(released["id"])
        assert after["transit_status"] == "PERMIT_PENDING", (
            "the replayed release is rejected outright rather than replaying the "
            f"first response, got {after['transit_status']}"
        )
        assert after["version"] == released["version"], (
            "a rejected release mutates nothing, so the version must stay at "
            f"{released['version']}, got {after['version']}"
        )

    def test_remeasuring_a_released_floor_is_refused(self, api):
        """PRD §3.2: "Plant QC advances the first step: recording
        `measured_width_in` and `measured_height_in` on a floor that is
        `AT_PLANT` moves it `AT_PLANT → MEASURED`, provided the acting
        dispatcher's plant is the plant on the floor's order."
        PRD §3.2: "Both steps raise the floor's `version` and trigger a
        recomputation of the order's posture; a floor whose owning plant does not
        match the caller is refused with `ERR_NOT_RESOURCE_OWNER`, and a floor in
        the wrong transport status is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/section_measure_and_release_are_once_only
        """
        plant, released = _released_floor()
        dispatcher = make_plant_dispatcher_headers(plant["id"])

        assert released["measured_width_in"] == 170, (
            f"the single measurement recorded 170 inches, got "
            f"{released['measured_width_in']}"
        )

        validate_error(
            api.measure_section(
                released["id"],
                measure_section_payload(measured_width_in=168, measured_height_in=150),
                dispatcher,
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        after = read_section(released["id"])
        assert after["transit_status"] == "PERMIT_PENDING", (
            "measure only exists on the AT_PLANT edge, so the floor is unmoved, got "
            f"{after['transit_status']}"
        )
        assert after["measured_width_in"] == 170, (
            "the rejected re-measure leaves the recorded width untouched, got "
            f"{after['measured_width_in']}"
        )
        assert after["version"] == released["version"], (
            f"no version bump on a rejected call, got {after['version']}"
        )
