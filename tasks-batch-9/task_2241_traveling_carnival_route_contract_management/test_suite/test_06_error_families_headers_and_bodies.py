"""Identity headers, unknown identifiers, body shape, uniqueness and state gates."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    CLERK,
    CLOCK_START,
    GIANT_WHEEL,
    LOT_BOSS,
    NEGOTIATOR,
    OFFICER,
    ROUTE_MANAGER,
    SAFETY_OFFICER,
    ApiErrorId,
    add_route_stop,
    assert_crew_assignment,
    assert_labor_ledger,
    assert_lot_ledgers,
    book_crew,
    build_user_headers,
    cancel_crew,
    commit_route,
    create_contract_payload,
    create_crew_assignment_payload,
    create_jurisdiction_payload,
    create_ride_allocation_payload,
    create_ride_payload,
    create_route_payload,
    create_route_stop_payload,
    create_worker_payload,
    draft_contract,
    execute_contract,
    inspection_result_payload,
    make_good_response_payload,
    open_route,
    read_allocation,
    read_route,
    read_route_stop,
    read_worker,
    register_jurisdiction,
    register_ride,
    register_venue,
    register_worker,
    release_allocation,
    schedule_inspection,
    send_contract,
    sequence_route,
    set_logical_clock,
    setup_confirmed_lot,
    setup_planned_lot_with_allocations,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)

HOCKING_VALLEY = {
    "name": "Hocking Valley Fair",
    "city": "Logan",
    "lot_area_sqft": 200000,
    "power_amps_available": 1000,
    "expected_attendance": 10001,
    "lot_surface": "GRASS",
}
SECOND_LOT_CALENDAR = {
    "load_in_start": "2026-09-12T06:00:00Z",
    "open_date": "2026-09-14T12:00:00Z",
    "close_date": "2026-09-16T12:00:00Z",
    "teardown_deadline": "2026-09-17T12:00:00Z",
}
VILLAGE_GREEN = {
    "name": "Village Green",
    "city": "Granville",
    "lot_area_sqft": 5000,
    "power_amps_available": 400,
    "expected_attendance": 1001,
    "lot_surface": "GRASS",
}
INSPECTABLE_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=False)

UNKNOWN_IDS = {
    "route": "00000000-0000-0000-0000-000000000001",
    "route_stop": "00000000-0000-0000-0000-000000000002",
    "contract": "00000000-0000-0000-0000-000000000003",
    "allocation": "00000000-0000-0000-0000-000000000004",
    "permit": "00000000-0000-0000-0000-000000000005",
    "inspection": "00000000-0000-0000-0000-000000000006",
    "assignment": "00000000-0000-0000-0000-000000000007",
    "settlement": "00000000-0000-0000-0000-000000000008",
    "closure": "00000000-0000-0000-0000-000000000009",
    "make_good": "00000000-0000-0000-0000-00000000000a",
    "worker": "00000000-0000-0000-0000-00000000000b",
}


def test_a_request_without_an_acting_user_identity_is_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they act.
    A request that omits either header, or that presents an `X-User-Role` value
    which is not one of the ten role names below, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.7: "1. **Authentication** — headers present and the role recognized
    (`ERR_UNAUTHENTICATED`). Applies to every endpoint."

    Design: Corner/errors/a_request_missing_the_x_user_id_header_returns_unauthenticated
    """
    set_logical_clock(CLOCK_START)
    route = validate_success(
        api.create_route(create_route_payload(), ROUTE_MANAGER), expected_status=201
    )

    headerless = validate_error(
        api.get_route(route["id"], {"X-User-Role": "RouteManager"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )
    assert "name" not in headerless, "the refusal must not leak the route payload"
    assert "season_year" not in headerless

    unknown_role = validate_error(
        api.get_route(route["id"], build_user_headers("user-manager-1", "Ringmaster")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )
    assert "name" not in unknown_role, "an unrecognized role is refused before any read"
    assert "season_year" not in unknown_role

    assert read_route(route["id"])["name"] == route["name"]


def test_each_unknown_path_identifier_reports_its_own_not_found(api):
    """PRD §2.7: "**Path existence, left to right** — every resource named by an
    identifier in the URL must exist, validated in the order the identifiers
    appear. The 404 raised names the *first* identifier that fails to resolve,
    using this mapping: a route yields `ERR_ROUTE_NOT_FOUND`, a route stop
    `ERR_ROUTE_STOP_NOT_FOUND`, a contract `ERR_CONTRACT_NOT_FOUND`, a ride
    allocation `ERR_ALLOCATION_NOT_FOUND`, a permit application
    `ERR_PERMIT_NOT_FOUND`, an inspection order `ERR_INSPECTION_NOT_FOUND`, a crew
    assignment `ERR_ASSIGNMENT_NOT_FOUND`, a settlement
    `ERR_SETTLEMENT_NOT_FOUND`, a weather closure `ERR_CLOSURE_NOT_FOUND`, a
    make-good arrangement `ERR_MAKEGOOD_NOT_FOUND`, and a worker
    `ERR_WORKER_NOT_FOUND`."

    Design: Corner/errors/unknown_path_ids_return_the_per_entity_not_found_family
    """
    validate_error(
        api.get_route(UNKNOWN_IDS["route"], ROUTE_MANAGER),
        ApiErrorId.ERR_ROUTE_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.get_route_stop(UNKNOWN_IDS["route_stop"], LOT_BOSS),
        ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.get_contract(UNKNOWN_IDS["contract"], NEGOTIATOR),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.get_ride_allocation(UNKNOWN_IDS["allocation"], LOT_BOSS),
        ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.submit_permit_application(UNKNOWN_IDS["permit"], CLERK),
        ApiErrorId.ERR_PERMIT_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.record_inspection_result(
            UNKNOWN_IDS["inspection"], inspection_result_payload("PASS"), OFFICER
        ),
        ApiErrorId.ERR_INSPECTION_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.cancel_crew_assignment(UNKNOWN_IDS["assignment"], LOT_BOSS),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.get_settlement(UNKNOWN_IDS["settlement"], AUDITOR),
        ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.get_weather_closure(UNKNOWN_IDS["closure"], LOT_BOSS),
        ApiErrorId.ERR_CLOSURE_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.respond_make_good(
            UNKNOWN_IDS["make_good"], make_good_response_payload("ACCEPT"), NEGOTIATOR
        ),
        ApiErrorId.ERR_MAKEGOOD_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api.get_worker(UNKNOWN_IDS["worker"], LOT_BOSS),
        ApiErrorId.ERR_WORKER_NOT_FOUND.value,
        expected_status=404,
    )


def test_body_shape_defects_each_report_the_invalid_request_family(api):
    """PRD §2.7: "**Body shape and range** — required fields present, enum values
    inside their declared sets, numeric ranges honored, and every declared
    intra-body rule satisfied. All failures at this stage answer
    `ERR_INVALID_REQUEST` (HTTP 400). Applies to every creating or acting
    operation."

    PRD §3.1: "`previous_stop_id` names the stop the units haul from and is null
    for the first stop of the route; when supplied it must belong to the same
    `route_id` and must not close a cycle, and a violation of either condition is
    an `ERR_INVALID_REQUEST`."

    PRD §3.6: "`visa_expires_on` records the instant an H-2B authorization lapses;
    it is required exactly when `employment_type` is `H2B_VISA` and must be null
    otherwise, a mismatch either way being refused with `ERR_INVALID_REQUEST`."

    Design: Corner/errors/four_body_shape_defects_each_return_invalid_request
    """
    ctx = setup_reference_data()
    first_route = open_route()
    second_route = open_route(name="2026 Fall Fairs")
    borrowed_stop = add_route_stop(first_route["id"], ctx["venue"]["id"])

    validate_error(
        api.create_ride(create_ride_payload(ride_class="SPIN"), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    validate_error(
        api.create_worker(
            create_worker_payload(
                employment_type="PERMANENT", visa_expires_on="2026-12-01T00:00:00Z"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    validate_error(
        api.create_route_stop(
            create_route_stop_payload(
                second_route["id"],
                ctx["venue"]["id"],
                previous_stop_id=borrowed_stop["id"],
                haul_miles_from_previous=120,
                **SECOND_LOT_CALENDAR,
            ),
            ROUTE_MANAGER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    _rows, meta = validate_paginated(
        api.list_route_stops(ROUTE_MANAGER, params={"route_id": second_route["id"]})
    )
    assert meta["total_count"] == 0, "no refused stop may be written to the route"
    assert read_route(second_route["id"])["stop_count"] == 0
    assert read_route(first_route["id"])["stop_count"] == 1


def test_a_duplicate_state_code_and_a_duplicate_live_deal_both_conflict(api):
    """PRD §2.7: "**Jurisdiction uniqueness** — `ERR_DUPLICATE_JURISDICTION_STATE`
    when a jurisdiction is registered with a `state_code` that already exists."

    PRD §2.7: "**One live deal per lot** — `ERR_DUPLICATE_ACTIVE_CONTRACT` when a
    contract is drafted for a stop that already carries one in `DRAFT`, `SENT`,
    `COUNTERED` or `EXECUTED`."

    Design: Corner/errors/duplicate_state_code_and_duplicate_active_contract_both_conflict
    """
    ctx = setup_reference_data()
    route = open_route()
    stop = add_route_stop(route["id"], ctx["venue"]["id"])
    survivor = draft_contract(
        stop["id"], counterparty_name="Franklin County Ag Society"
    )
    assert survivor["status"] == "DRAFT"

    validate_error(
        api.create_jurisdiction(
            create_jurisdiction_payload(name="Ohio Second Filing"), ADMIN
        ),
        ApiErrorId.ERR_DUPLICATE_JURISDICTION_STATE.value,
        expected_status=409,
    )

    validate_error(
        api.create_contract(
            create_contract_payload(
                stop["id"], counterparty_name="Rival Midway Promotions"
            ),
            NEGOTIATOR,
        ),
        ApiErrorId.ERR_DUPLICATE_ACTIVE_CONTRACT.value,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_contracts(NEGOTIATOR, params={"route_stop_id": stop["id"]})
    )
    assert meta["total_count"] == 1, "a lot carries at most one live deal"
    assert rows[0]["id"] == survivor["id"]
    assert rows[0]["status"] == "DRAFT"


def test_sequencing_reports_no_stops_and_then_a_forked_chain(api):
    """PRD §3.1: "Separately, a route with no non-`DARK` stop at all cannot be
    sequenced and answers `ERR_ROUTE_HAS_NO_STOPS`."

    PRD §3.1: "Three structural conditions must hold, and each failure answers
    `ERR_STOP_CHAIN_INVALID`: exactly one non-`DARK` stop has a null
    `previous_stop_id`; no non-`DARK` stop is named as the predecessor of two or
    more non-`DARK` stops; and the chain so built covers every non-`DARK` stop of
    the route, which rules out both unreachable stops and cycles."

    Design: Corner/errors/sequencing_reports_no_stops_and_then_a_forked_chain
    """
    ctx = setup_reference_data()
    hocking = register_venue(ctx["jurisdiction"]["id"], **HOCKING_VALLEY)
    route = open_route()

    validate_error(
        api.sequence_route(route["id"], ROUTE_MANAGER),
        ApiErrorId.ERR_ROUTE_HAS_NO_STOPS.value,
        expected_status=422,
    )

    first = add_route_stop(route["id"], ctx["venue"]["id"])
    second = add_route_stop(route["id"], hocking["id"], **SECOND_LOT_CALENDAR)

    validate_error(
        api.sequence_route(route["id"], ROUTE_MANAGER),
        ApiErrorId.ERR_STOP_CHAIN_INVALID.value,
        expected_status=422,
    )

    unsequenced = read_route(route["id"])
    assert unsequenced["status"] == "DRAFT"
    assert unsequenced["total_travel_hours"] == 0
    assert unsequenced["stop_count"] == 2

    assert read_route_stop(first["id"])["sequence_index"] == 0
    assert read_route_stop(second["id"])["sequence_index"] == 0, (
        "a refused sequencing assigns no order to either head candidate"
    )


def test_state_gates_refuse_a_commit_a_replayed_cancel_and_a_released_allocation(api):
    """PRD §2.7: "**Route state** — `ERR_ROUTE_STATE_INVALID` when the route is not
    in the state the operation requires: `DRAFT` to sequence, `SEQUENCED` to
    commit, `DRAFT` or `SEQUENCED` to add a stop, `SEQUENCED` or `COMMITTED` to
    send a contract, `COMMITTED` to execute one."

    PRD §2.7: "**Other child-resource state** — a permit must be `DRAFT` to submit
    and `SUBMITTED` to decide (`ERR_PERMIT_STATE_INVALID`); an inspection order
    must be `SCHEDULED` to record a result (`ERR_INSPECTION_STATE_INVALID`); a
    crew assignment must be `SCHEDULED` to cancel
    (`ERR_ASSIGNMENT_STATE_INVALID`); a weather closure must be `LOGGED` to
    adjudicate (`ERR_CLOSURE_STATE_INVALID`); a make-good arrangement must be
    `PROPOSED` to respond to (`ERR_MAKEGOOD_STATE_INVALID`)."

    PRD §2.7: "**Allocation state** — `ERR_ALLOCATION_STATE_INVALID`: `RESERVED`
    to commit; `RESERVED`, `COMMITTED` or `INSPECTION_HELD` to release and to
    schedule an inspection."

    PRD §3.6: "Cancelling a booked shift (`SCHEDULED → RELEASED`) is a `LotBoss`
    action available while the lot is not `CLOSED`. It reverses exactly what the
    booking added: the worker's `scheduled_hours_total` falls by that assignment's
    `shift_hours` and the lot's `labor_cost_provisional_cents` falls by its
    `cost_cents`, restoring both ledgers to their pre-assignment values."

    Design: Corner/errors/state_gate_errors_fire_on_route_allocation_and_assignment_writes
    """
    ctx = setup_planned_lot_with_allocations(ride_specs=[INSPECTABLE_WHEEL])
    stop_id = ctx["stop"]["id"]
    allocation_id = ctx["allocations"][0]["id"]
    rigger = register_worker(
        full_name="Rigger One", employment_type="PERMANENT", hourly_rate_cents=2000
    )
    shift = book_crew(
        stop_id,
        rigger["id"],
        "SETUP",
        "2026-09-01T06:00:00Z",
        "2026-09-01T14:00:00Z",
    )
    assert_crew_assignment(shift)
    assert shift["status"] == "SCHEDULED"

    validate_error(
        api.commit_route(ctx["route"]["id"], ROUTE_MANAGER),
        ApiErrorId.ERR_ROUTE_STATE_INVALID.value,
        expected_status=409,
    )
    assert read_route(ctx["route"]["id"])["status"] == "DRAFT"

    released_shift = cancel_crew(shift["id"])
    assert released_shift["status"] == "RELEASED"

    validate_error(
        api.cancel_crew_assignment(shift["id"], LOT_BOSS),
        ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID.value,
        expected_status=409,
    )
    assert read_worker(rigger["id"])["scheduled_hours_total"] == 0
    assert_labor_ledger(read_route_stop(stop_id), 0)

    contract = draft_contract(
        stop_id,
        counterparty_name="Franklin County Ag Society",
        revenue_split_pct_operator=65,
        guarantee_cents=900000,
        ride_minimum_count=1,
    )
    sequence_route(ctx["route"]["id"])
    send_contract(contract["id"])
    commit_route(ctx["route"]["id"])
    execute_contract(contract["id"])
    assert read_route_stop(stop_id)["status"] == "CONFIRMED"
    assert read_allocation(allocation_id)["status"] == "COMMITTED"

    released_allocation = release_allocation(allocation_id)
    assert released_allocation["status"] == "RELEASED"

    validate_error(
        api.commit_ride_allocation(allocation_id, LOT_BOSS),
        ApiErrorId.ERR_ALLOCATION_STATE_INVALID.value,
        expected_status=409,
    )
    assert read_allocation(allocation_id)["status"] == "RELEASED"

    stop = read_route_stop(stop_id)
    assert_lot_ledgers(stop, 0, 0.0)
    assert_labor_ledger(stop, 0)


def test_an_inspection_result_is_refused_on_replay_and_on_a_released_allocation(api):
    """PRD §2.7: "**Other child-resource state** — a permit must be `DRAFT` to
    submit and `SUBMITTED` to decide (`ERR_PERMIT_STATE_INVALID`); an inspection
    order must be `SCHEDULED` to record a result (`ERR_INSPECTION_STATE_INVALID`);
    a crew assignment must be `SCHEDULED` to cancel
    (`ERR_ASSIGNMENT_STATE_INVALID`); a weather closure must be `LOGGED` to
    adjudicate (`ERR_CLOSURE_STATE_INVALID`); a make-good arrangement must be
    `PROPOSED` to respond to (`ERR_MAKEGOOD_STATE_INVALID`)."

    PRD §2.7: "**Inspectability** — `ERR_ALLOCATION_NOT_INSPECTABLE` when a result
    is recorded against an inspection order whose allocation is neither
    `COMMITTED` nor `INSPECTION_HELD`."

    PRD §3.5: "The new order enters `SCHEDULED` with `defect_count` 0 and
    `result_recorded_at` null, and its `attempt_number` is computed as one more
    than the number of inspection orders already `FAILED` on the same allocation —
    so a re-inspection is a *new* row rather than a reopened one."

    Design: Corner/errors/inspection_result_gates_fire_on_replay_and_on_a_released_allocation
    """
    ctx = setup_confirmed_lot(
        contract_overrides={
            "counterparty_name": "Franklin County Ag Society",
            "revenue_split_pct_operator": 65,
            "guarantee_cents": 900000,
            "ride_minimum_count": 1,
        },
        ride_specs=[INSPECTABLE_WHEEL],
        jurisdiction_overrides={
            "requires_state_ride_inspection": False,
            "inspection_slot_capacity_per_day": 2,
        },
    )
    allocation_id = ctx["allocations"][0]["id"]
    assert ctx["allocations"][0]["status"] == "COMMITTED"

    first_order = schedule_inspection(
        allocation_id, "THIRD_PARTY", "2026-09-02T14:00:00Z"
    )
    second_order = schedule_inspection(
        allocation_id, "THIRD_PARTY", "2026-09-03T14:00:00Z"
    )
    assert first_order["attempt_number"] == 1
    assert second_order["attempt_number"] == 1

    passed = validate_success(
        api.record_inspection_result(
            first_order["id"], inspection_result_payload("PASS"), OFFICER
        )
    )
    assert passed["status"] == "PASSED"
    assert passed["defect_count"] == 0

    validate_error(
        api.record_inspection_result(
            first_order["id"], inspection_result_payload("PASS"), OFFICER
        ),
        ApiErrorId.ERR_INSPECTION_STATE_INVALID.value,
        expected_status=409,
    )

    released = release_allocation(allocation_id)
    assert released["status"] == "RELEASED"

    validate_error(
        api.record_inspection_result(
            second_order["id"], inspection_result_payload("PASS"), OFFICER
        ),
        ApiErrorId.ERR_ALLOCATION_NOT_INSPECTABLE.value,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_allocation_inspections(allocation_id, SAFETY_OFFICER)
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[first_order["id"]]["status"] == "PASSED"
    assert by_id[second_order["id"]]["status"] == "SCHEDULED", (
        "a refused result leaves the order untouched"
    )


def test_an_operator_certified_for_no_allocated_class_is_refused(api):
    """PRD §3.6: "Certification comes first. A `RIDE_OPERATOR` shift requires that
    the worker's `certified_ride_classes` include the `ride_class` of at least one
    ride allocated to that lot in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or
    `OPERATING`; a worker certified for nothing on the lot is refused with
    `ERR_WORKER_NOT_CERTIFIED`."

    PRD §3.6: "A rigging premium of 10 percent of that base amount, rounded
    half-up to whole cents, is added for `SETUP` and `TEARDOWN` shifts only, and is
    zero for `RIDE_OPERATOR` and `TICKETING`. A housing stipend of 3,500 cents
    (thirty-five dollars) per shift is added when the worker's `housing_required`
    is true, and is zero otherwise."

    Design: Corner/errors/an_operator_certified_for_no_allocated_class_is_refused
    """
    ctx = setup_planned_lot_with_allocations(ride_specs=[INSPECTABLE_WHEEL])
    stop_id = ctx["stop"]["id"]
    assert ctx["rides"][0]["ride_class"] == "MAJOR"
    assert ctx["allocations"][0]["status"] == "RESERVED"

    kiddie_hand = register_worker(
        full_name="Kiddie One",
        employment_type="PERMANENT",
        hourly_rate_cents=1600,
        certified_ride_classes=["KIDDIE"],
    )
    major_hand = register_worker(
        full_name="Op One",
        employment_type="PERMANENT",
        hourly_rate_cents=1600,
        certified_ride_classes=["MAJOR"],
    )

    validate_error(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop_id,
                kiddie_hand["id"],
                "RIDE_OPERATOR",
                "2026-09-04T12:00:00Z",
                "2026-09-04T20:00:00Z",
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_WORKER_NOT_CERTIFIED.value,
        expected_status=422,
    )

    admitted = validate_success(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop_id,
                major_hand["id"],
                "RIDE_OPERATOR",
                "2026-09-04T12:00:00Z",
                "2026-09-04T20:00:00Z",
            ),
            LOT_BOSS,
        ),
        expected_status=201,
    )
    assert admitted["status"] == "SCHEDULED"
    assert admitted["shift_hours"] == 8.0
    assert admitted["cost_cents"] == 12800, (
        "an operator shift carries no rigging premium"
    )
    assert admitted["housing_pad_assigned"] is False

    assert_labor_ledger(read_route_stop(stop_id), 12800)
    assert read_worker(kiddie_hand["id"])["scheduled_hours_total"] == 0
    assert read_worker(major_hand["id"])["scheduled_hours_total"] == 8.0

    rows, meta = validate_paginated(
        api.list_route_stop_crew_assignments(stop_id, LOT_BOSS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["worker_id"] == major_hand["id"]


def test_an_oversized_unit_on_a_village_lot_reports_the_capacity_error(api):
    """PRD §3.3: "Not all of a fairground can hold rides: the usable area is 80
    percent of `lot_area_sqft`, rounded **down** to a whole square foot, less a
    circulation reserve of half a square foot per projected attendee — that is,
    `expected_attendance` multiplied by 0.5 and rounded **up** to a whole square
    foot. If the lot's existing `allocated_sqft_used` plus the candidate's charged
    footprint exceeds that usable area, the reservation is refused with
    `ERR_LOT_CAPACITY_EXCEEDED`; a total exactly equal to the usable area is
    admitted."

    PRD §2.7: "41. **Lot footprint budget** — `ERR_LOT_CAPACITY_EXCEEDED` on ride
    reservation. 42. **Lot power budget** — `ERR_LOT_POWER_EXCEEDED` on ride
    reservation."

    Design: Corner/errors/an_oversized_unit_on_a_village_lot_reports_the_capacity_error
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    village = register_venue(jurisdiction["id"], **VILLAGE_GREEN)
    route = open_route(name="2026 Village Circuit")
    stop = add_route_stop(route["id"], village["id"])
    wheel = register_ride(INSPECTABLE_WHEEL)

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(wheel["id"], stop["id"], stop["version"]),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_LOT_CAPACITY_EXCEEDED.value,
        expected_status=422,
    )

    untouched = read_route_stop(stop["id"])
    assert_lot_ledgers(untouched, 0, 0.0)
    assert untouched["version"] == 1, "a refused reservation does not charge the lot"

    _rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"route_stop_id": stop["id"]})
    )
    assert meta["total_count"] == 0
