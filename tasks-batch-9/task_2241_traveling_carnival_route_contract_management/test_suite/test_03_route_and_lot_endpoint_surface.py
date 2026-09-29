"""The lot catalogue, the itinerary lock and the computed readiness read."""

from test_helpers import (
    ADMIN,
    CLERK,
    CLOCK_START,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GIANT_WHEEL,
    LOT_BOSS,
    NON_EXISTENT_UUID,
    ROUTE_MANAGER,
    ApiErrorId,
    add_route_stop,
    approved_permit,
    assert_lot_ledgers,
    assert_readiness,
    assert_ride_allocation,
    assert_venue,
    book_crew,
    create_ride_allocation_payload,
    create_venue_payload,
    draft_contract,
    open_route,
    read_readiness,
    read_route,
    read_route_stop,
    register_jurisdiction,
    register_venue,
    register_worker,
    set_logical_clock,
    setup_committed_route_with_sent_contract,
    setup_confirmed_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_lot_is_readable_both_directly_and_through_the_filtered_listing(api):
    """PRD §3.1: "A **lot** — the fairground or midway itself — is registered against a
    `jurisdiction_id` with a `name`, a `city`, a `lot_area_sqft` gross area greater
    than zero, a `power_amps_available` service amperage greater than zero, an
    `expected_attendance` projection of zero or more supplied by the fair authority
    for the full run, and a `lot_surface` of `PAVED`, `GRAVEL` or `GRASS`, the ground
    condition that feeds the setup-hours multiplier a lot boss uses when planning
    erection crews."

    PRD §2.9: "Top-level list reads accept their own filters: `jurisdiction_id` and `state_code` on
    lots, `route_id`, `venue_id`, `previous_stop_id` and `status` on stops,
    `route_stop_id` and `status` on contracts, and `ride_id`, `route_stop_id` and
    `status` on allocations."

    Design: Corner/endpoints/venue_create_read_and_list_cover_the_available_crud_surface
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()

    fairgrounds = validate_success(
        api.create_venue(create_venue_payload(jurisdiction["id"]), ADMIN),
        expected_status=201,
    )
    village_green = validate_success(
        api.create_venue(
            create_venue_payload(
                jurisdiction["id"],
                name="Village Green",
                city="Delaware",
                lot_area_sqft=5000,
                power_amps_available=400,
                expected_attendance=1001,
                lot_surface="GRASS",
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert fairgrounds["id"] != village_green["id"]

    read_back = validate_success(api.get_venue(fairgrounds["id"], LOT_BOSS))
    assert_venue(read_back)
    assert read_back["name"] == "Franklin County Fairgrounds"
    assert read_back["lot_area_sqft"] == 100000

    rows, meta = validate_paginated(
        api.list_venues(
            ROUTE_MANAGER,
            params={"jurisdiction_id": jurisdiction["id"], "limit": 1, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1


def test_committing_a_sequenced_route_locks_it_and_changes_nothing_else(api):
    """PRD §3.1: "**Committing** a route (`SEQUENCED → COMMITTED`), open to a
    `RouteManager` or a `GeneralManager`, is the point of no return for the
    itinerary. It requires that every non-`DARK` stop of the route already carries
    a contract in `DRAFT`, `SENT`, `COUNTERED` or `EXECUTED`; a stop with no such
    deal blocks the commit with `ERR_STOP_NOT_CONTRACTED`. The commit itself
    changes nothing but the route's status and `version`."

    Design: Corner/endpoints/route_commit_action_moves_a_sequenced_route_to_committed
    """
    ctx = setup_committed_route_with_sent_contract(
        contract_overrides={
            "counterparty_name": "Franklin County Ag Society",
            "revenue_split_pct_operator": 65,
            "guarantee_cents": 900000,
            "ride_minimum_count": 1,
        }
    )

    route = read_route(ctx["route"]["id"])
    assert route["status"] == "COMMITTED"
    assert route["stop_count"] == 1
    assert route["total_haul_miles"] == 0
    assert route["total_travel_hours"] == 0
    assert route["total_guaranteed_cents"] == 0, (
        "a sent deal has not been executed, so it contributes no guarantee"
    )

    stop = read_route_stop(ctx["stop"]["id"])
    assert stop["sequence_index"] == 0
    assert stop["travel_hours_from_previous"] == 0
    assert stop["status"] == "PLANNED"

    assert ctx["contract"]["status"] == "SENT"


def test_committing_a_route_is_refused_while_a_lot_carries_no_deal(api):
    """PRD §3.1: "It requires that every non-`DARK` stop of the route already
    carries a contract in `DRAFT`, `SENT`, `COUNTERED` or `EXECUTED`; a stop with
    no such deal blocks the commit with `ERR_STOP_NOT_CONTRACTED`."

    PRD §3.1: "The stop's `travel_hours_from_previous` is then the raw driving
    hours plus ten hours for each rest block, rounded half-up to two decimals."

    Design: Corner/endpoints/commit_is_refused_while_a_non_dark_stop_carries_no_contract
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    franklin = register_venue(jurisdiction["id"])
    hocking = register_venue(
        jurisdiction["id"],
        name="Hocking Valley Fair",
        city="Logan",
        lot_area_sqft=200000,
        power_amps_available=1000,
        expected_attendance=10001,
        lot_surface="GRASS",
    )
    route = open_route()
    head = add_route_stop(route["id"], franklin["id"])
    second = add_route_stop(
        route["id"],
        hocking["id"],
        load_in_start="2026-09-10T06:00:00Z",
        open_date="2026-09-12T12:00:00Z",
        close_date="2026-09-14T12:00:00Z",
        teardown_deadline="2026-09-15T12:00:00Z",
        previous_stop_id=head["id"],
        haul_miles_from_previous=495,
    )
    draft_contract(head["id"], counterparty_name="Franklin County Ag Society")
    validate_success(api.sequence_route(route["id"], ROUTE_MANAGER))

    validate_error(
        api.commit_route(route["id"], ROUTE_MANAGER),
        ApiErrorId.ERR_STOP_NOT_CONTRACTED.value,
    )
    assert read_route(route["id"])["status"] == "SEQUENCED"

    second_row = read_route_stop(second["id"])
    assert second_row["sequence_index"] == 1
    assert second_row["travel_hours_from_previous"] == 21.0
    locked = read_route(route["id"])
    assert locked["total_travel_hours"] == 21.0
    assert locked["total_haul_miles"] == 495

    second_deal = draft_contract(
        second["id"],
        counterparty_name="Hocking Valley Ag Society",
        revenue_split_pct_operator=60,
        guarantee_cents=300000,
        ride_minimum_count=1,
    )
    assert second_deal["status"] == "DRAFT"

    committed = validate_success(api.commit_route(route["id"], ROUTE_MANAGER))
    assert committed["status"] == "COMMITTED"


def test_readiness_reports_a_labor_hold_until_an_operator_is_booked(api):
    """PRD §3.7: "The third test is labor, and it is a three-way disjunction: the
    posture is `LABOR_HOLD` if the count of the lot's `SCHEDULED` `RIDE_OPERATOR`
    assignments is fewer than one per allocation of the lot in `COMMITTED` or
    `OPERATING`; **or** any of the lot's `SCHEDULED` assignments belongs to a
    worker whose `compliance_status` is `VISA_LAPSED`; **or** the count of the
    lot's `SCHEDULED` assignments carrying `housing_pad_assigned` exceeds the
    lot's `housing_pads_available`."

    PRD §3.7: "Its blocking error is `ERR_CREW_COVERAGE_INSUFFICIENT`."

    PRD §3.7: "The readiness read exposes this reasoning directly, returning the
    lot's `route_stop_id`, its `compliance_posture`, the `blocking_error_id` that
    posture would raise (null when the posture is `CLEAR`), and four narrower
    signals: `event_permit_ok`, true when the event-permit test above is
    satisfied; `inspections_ok`, true when no allocation trips the inspection
    test; `crew_coverage_ok`, true when none of the three labor conditions holds;
    `committed_ride_count`, the number of the lot's allocations currently in
    `COMMITTED`; and `ride_minimum_required`, the `ride_minimum_count` of the
    lot's executed deal."

    Design: Corner/endpoints/readiness_read_reports_labor_hold_then_clear_once_an_operator_is_booked
    """
    ctx = setup_confirmed_lot(
        contract_overrides={
            "counterparty_name": "Franklin County Ag Society",
            "revenue_split_pct_operator": 65,
            "guarantee_cents": 900000,
            "ride_minimum_count": 1,
            "settlement_basis": "SPLIT_ONLY",
        },
        ride_specs=[dict(GIANT_WHEEL, requires_state_inspection=False)],
        jurisdiction_overrides={"requires_state_ride_inspection": False},
    )
    stop_id = ctx["stop"]["id"]
    approved_permit(
        stop_id, "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
    )

    held = validate_success(api.get_readiness(stop_id, LOT_BOSS))
    assert_readiness(held)
    assert held["compliance_posture"] == "LABOR_HOLD"
    assert held["blocking_error_id"] == ApiErrorId.ERR_CREW_COVERAGE_INSUFFICIENT.value
    assert held["event_permit_ok"] is True
    assert held["inspections_ok"] is True
    assert held["crew_coverage_ok"] is False
    assert held["committed_ride_count"] == 1
    assert held["ride_minimum_required"] == 1

    operator = register_worker(
        full_name="Op One",
        employment_type="PERMANENT",
        hourly_rate_cents=1600,
        certified_ride_classes=["MAJOR"],
    )
    book_crew(
        stop_id,
        operator["id"],
        "RIDE_OPERATOR",
        "2026-09-04T12:00:00Z",
        "2026-09-04T20:00:00Z",
    )

    cleared = read_readiness(stop_id, LOT_BOSS)
    assert cleared["compliance_posture"] == "CLEAR"
    assert cleared["blocking_error_id"] is None
    assert cleared["crew_coverage_ok"] is True

    assert read_route_stop(stop_id, CLERK)["compliance_posture"] == "CLEAR"
    assert ctx["allocations"][0]["status"] == "COMMITTED"


def test_reserving_a_ride_needs_both_the_ride_and_the_lot_to_exist(api):
    """PRD §2.7: "**Body reference existence** — every foreign reference carried
    in a request body must resolve to an existing row: `jurisdiction_id`,
    `venue_id`, `route_id`, `previous_stop_id`, `route_stop_id`, `ride_id`,
    `worker_id`, `contract_id`, `ride_allocation_id` and `weather_closure_id`. Any
    unresolved reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

    PRD §3.3: "A `LotBoss` puts a ride on a lot by reserving an **allocation**,
    naming a `ride_id`, a `route_stop_id` and the mandatory
    `expected_route_stop_version` described in §2.5."

    Design: Corner/endpoints/ride_allocation_link_binds_a_ride_to_a_stop_and_needs_both_rows
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])
    ride = validate_success(
        api.create_ride(dict(GIANT_WHEEL, requires_state_inspection=False), ADMIN),
        expected_status=201,
    )

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                NON_EXISTENT_UUID, stop["id"], stop["version"]
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value,
    )
    untouched = read_route_stop(stop["id"])
    assert_lot_ledgers(untouched, 0, 0.0)
    assert untouched["version"] == 1

    allocation = validate_success(
        api.create_ride_allocation(
            create_ride_allocation_payload(ride["id"], stop["id"], stop["version"]),
            LOT_BOSS,
        ),
        expected_status=201,
    )
    assert_ride_allocation(allocation)
    assert allocation["ride_id"] == ride["id"]
    assert allocation["route_stop_id"] == stop["id"]
    assert allocation["status"] == "RESERVED"
    assert allocation["footprint_charged_sqft"] == 5414
    assert allocation["power_charged_amps"] == 375.0

    charged = read_route_stop(stop["id"])
    assert_lot_ledgers(charged, 5414, 375.0)
    assert charged["version"] == 2, "the lot is charged exactly once"
