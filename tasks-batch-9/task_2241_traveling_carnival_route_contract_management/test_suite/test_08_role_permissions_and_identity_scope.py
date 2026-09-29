"""Every role's own operations, the deny side of the lists and identity scope."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    CLERK,
    CLOCK_AT_LOAD_IN,
    CLOCK_AT_OPEN,
    CLOCK_START,
    COLLIDING_GENERAL_MANAGER_HEADERS,
    COLLIDING_SENDER_USER_ID,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GENERAL_MANAGER,
    LOT_BOSS,
    NEGOTIATOR,
    NEGOTIATOR_SENDER_USER_ID,
    OFFICER,
    ROUTE_MANAGER,
    SAFETY_OFFICER,
    TRANSPORT_PERMIT_VALID_FROM,
    TRANSPORT_PERMIT_VALID_UNTIL,
    ApiErrorId,
    add_route_stop,
    assert_crew_assignment,
    book_crew,
    create_contract_payload,
    create_crew_assignment_payload,
    create_inspection_order_payload,
    create_jurisdiction_payload,
    create_permit_application_payload,
    create_ride_allocation_payload,
    create_ride_payload,
    create_route_payload,
    create_route_stop_payload,
    create_ticket_sale_payload,
    create_venue_payload,
    create_worker_payload,
    inspection_result_payload,
    make_crew_chief_headers,
    open_route,
    permit_decision_payload,
    read_contract,
    read_route,
    read_route_stop,
    register_jurisdiction,
    register_venue,
    register_worker,
    send_contract,
    set_logical_clock,
    setup_committed_route_with_sent_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

CARNIVAL_DEAL = {
    "counterparty_name": "Franklin County Ag Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 1,
    "settlement_basis": "SPLIT_ONLY",
}
OPERATOR_SPEC = {
    "full_name": "Op One",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
}


def test_every_role_exercises_its_own_exclusive_operation(api):
    """PRD §2.1: "A request whose role is well-formed but is not listed as an
    authorized role for the endpoint being called is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §4: "Operations that mint a brand-new resource — registering reference
    data, opening a route, adding a stop, drafting a deal, reserving a ride, filing
    a permit, scheduling an inspection, booking a shift, recording a sales batch,
    building a settlement, logging a closure or proposing a make-good — answer `201
    Created`. Every operation that modifies an existing resource, drives a state
    transition, or reads data answers `200 OK`."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    validate_success(api.set_clock(CLOCK_START, ADMIN))
    jurisdiction = validate_success(
        api.create_jurisdiction(create_jurisdiction_payload(), ADMIN),
        expected_status=201,
    )
    venue = validate_success(
        api.create_venue(create_venue_payload(jurisdiction["id"]), ADMIN),
        expected_status=201,
    )
    ride = validate_success(
        api.create_ride(create_ride_payload(requires_state_inspection=False), ADMIN),
        expected_status=201,
    )
    worker = validate_success(
        api.create_worker(create_worker_payload(**OPERATOR_SPEC), ADMIN),
        expected_status=201,
    )

    route = validate_success(
        api.create_route(create_route_payload(), ROUTE_MANAGER), expected_status=201
    )
    stop = validate_success(
        api.create_route_stop(
            create_route_stop_payload(route["id"], venue["id"]), ROUTE_MANAGER
        ),
        expected_status=201,
    )
    contract = validate_success(
        api.create_contract(
            create_contract_payload(stop["id"], **CARNIVAL_DEAL), NEGOTIATOR
        ),
        expected_status=201,
    )
    validate_success(api.sequence_route(route["id"], ROUTE_MANAGER))
    validate_success(api.send_contract(contract["id"], NEGOTIATOR))
    validate_success(api.commit_route(route["id"], ROUTE_MANAGER))

    # PRD §2.5: the reservation must carry "the `version` of the route stop as
    # they last observed it" — the lot is re-read here because the sequencing
    # step above touched it.
    stop = read_route_stop(stop["id"], LOT_BOSS)
    allocation = validate_success(
        api.create_ride_allocation(
            create_ride_allocation_payload(ride["id"], stop["id"], stop["version"]),
            LOT_BOSS,
        ),
        expected_status=201,
    )
    executed = validate_success(api.execute_contract(contract["id"], GENERAL_MANAGER))
    validate_success(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"],
                worker["id"],
                "RIDE_OPERATOR",
                "2026-09-04T12:00:00Z",
                "2026-09-04T20:00:00Z",
            ),
            LOT_BOSS,
        ),
        expected_status=201,
    )

    transport = validate_success(
        api.create_permit_application(
            create_permit_application_payload(
                stop["id"],
                "TRANSPORT",
                TRANSPORT_PERMIT_VALID_FROM,
                TRANSPORT_PERMIT_VALID_UNTIL,
                axles_declared=4,
            ),
            CLERK,
        ),
        expected_status=201,
    )
    validate_success(api.submit_permit_application(transport["id"], CLERK))
    validate_success(
        api.decide_permit_application(
            transport["id"], permit_decision_payload("APPROVE"), OFFICER
        )
    )

    order = validate_success(
        api.create_inspection_order(
            create_inspection_order_payload(
                allocation["id"], "THIRD_PARTY", "2026-09-02T14:00:00Z"
            ),
            SAFETY_OFFICER,
        ),
        expected_status=201,
    )
    passed = validate_success(
        api.record_inspection_result(
            order["id"], inspection_result_payload("PASS"), OFFICER
        )
    )

    event = validate_success(
        api.create_permit_application(
            create_permit_application_payload(
                stop["id"],
                "EVENT",
                EVENT_PERMIT_VALID_FROM,
                EVENT_PERMIT_VALID_UNTIL,
            ),
            CLERK,
        ),
        expected_status=201,
    )
    validate_success(api.submit_permit_application(event["id"], CLERK))
    validate_success(
        api.decide_permit_application(
            event["id"], permit_decision_payload("APPROVE"), OFFICER
        )
    )

    validate_success(api.set_clock(CLOCK_AT_LOAD_IN, ADMIN))
    validate_success(api.begin_setup(stop["id"], LOT_BOSS))
    validate_success(api.set_clock(CLOCK_AT_OPEN, ADMIN))
    opened = validate_success(api.open_gates(stop["id"], LOT_BOSS))
    sale = validate_success(
        api.create_ticket_sale(
            stop["id"],
            create_ticket_sale_payload("WRISTBAND", 100, 1000, "2026-09-04T18:00:00Z"),
            AUDITOR,
        ),
        expected_status=201,
    )

    assert executed["status"] == "EXECUTED"
    assert executed["last_sent_by_user_id"] == NEGOTIATOR_SENDER_USER_ID
    assert passed["authority"] == "THIRD_PARTY"
    assert passed["status"] == "PASSED"
    assert passed["attempt_number"] == 1
    assert passed["defect_count"] == 0
    assert opened["status"] == "OPEN"
    assert opened["operating_ride_count"] == 1
    assert sale["gross_cents"] == 100000


def test_a_lot_boss_may_neither_add_a_lot_nor_lock_the_itinerary(api):
    """PRD §2.7: "**Endpoint authorization** — the acting role appears on the
    endpoint's authorized-role list (`ERR_ROLE_NOT_PERMITTED`). Applies to every
    endpoint."

    PRD §3.1: "Only a `RouteManager` may add a **stop** to a route."

    PRD §3.1: "Separately, a route with no non-`DARK` stop at all cannot be
    sequenced and answers `ERR_ROUTE_HAS_NO_STOPS`."

    Design: Corner/rbac/a_lot_boss_cannot_create_a_route_stop_or_sequence_a_route
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    route = open_route()

    validate_error(
        api.create_route_stop(
            create_route_stop_payload(route["id"], venue["id"]), LOT_BOSS
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api.sequence_route(route["id"], LOT_BOSS),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )

    stop = validate_success(
        api.create_route_stop(
            create_route_stop_payload(route["id"], venue["id"]), ROUTE_MANAGER
        ),
        expected_status=201,
    )
    assert stop["status"] == "PLANNED"

    _rows, meta = validate_paginated(
        api.list_route_stops(ROUTE_MANAGER, params={"route_id": route["id"]})
    )
    assert meta["total_count"] == 1, "the two refused calls wrote nothing"
    assert read_route(route["id"])["status"] == "DRAFT"


def test_the_sender_of_a_deal_may_not_countersign_it(api):
    """PRD §3.2: "First, segregation of duties: the executing manager's
    `X-User-ID` must differ from the deal's stored `last_sent_by_user_id`, and an
    attempt by the same user to countersign what they sent is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD §2.1: "The negotiator who sends a set of terms may not be the general
    manager who executes them — a violation answers `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    PRD §3.2: "Execution stamps `executed_at` from the logical clock, adds the
    deal's `guarantee_cents` to the route's `total_guaranteed_cents`, and then
    cascades. The first hop advances the lot `PLANNED → CONFIRMED`."

    Design: Corner/rbac/the_same_user_cannot_send_and_countersign_the_same_contract
    """
    ctx = setup_committed_route_with_sent_contract(
        contract_overrides=CARNIVAL_DEAL, sender_user_id=COLLIDING_SENDER_USER_ID
    )
    contract_id = ctx["contract"]["id"]
    stop_id = ctx["stop"]["id"]
    assert ctx["contract"]["last_sent_by_user_id"] == COLLIDING_SENDER_USER_ID

    validate_error(
        api.execute_contract(contract_id, COLLIDING_GENERAL_MANAGER_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    blocked = read_contract(contract_id)
    assert blocked["status"] == "SENT"
    assert blocked["executed_at"] is None
    assert read_route_stop(stop_id)["status"] == "PLANNED"

    executed = validate_success(api.execute_contract(contract_id, GENERAL_MANAGER))
    assert executed["status"] == "EXECUTED"
    assert executed["last_sent_by_user_id"] == COLLIDING_SENDER_USER_ID

    assert read_route_stop(stop_id)["status"] == "CONFIRMED"
    assert read_route(ctx["route"]["id"])["total_guaranteed_cents"] == 900000


def test_a_crew_chief_reads_only_their_own_roster(api):
    """PRD §2.7: "**Crew-chief self-scope** — a `CrewChief` reading a worker's
    assignment roster must be that worker (`ERR_ROLE_NOT_PERMITTED`). Applies to
    the worker-scoped crew-assignment list only."

    PRD §2.1: "When `X-User-Role` is `CrewChief`, `X-User-ID` is the `id` of the
    acting `Worker` row; ownership checks on a crew-roster read compare the worker
    identifier in the path to `X-User-ID`. A `CrewChief` reading the assignment
    roster of a worker whose `id` differs from their own `X-User-ID` is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §3.6: "A rigging premium of 10 percent of that base amount, rounded
    half-up to whole cents, is added for `SETUP` and `TEARDOWN` shifts only, and is
    zero for `RIDE_OPERATOR` and `TICKETING`."

    Design: Corner/rbac/a_crew_chief_cannot_read_another_workers_roster
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction(max_consecutive_work_days=12)
    venue = register_venue(jurisdiction["id"])
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])

    chief = register_worker(
        full_name="Chief One",
        employment_type="PERMANENT",
        hourly_rate_cents=2000,
        certified_ride_classes=["MAJOR"],
    )
    other = register_worker(
        full_name="Op Two",
        employment_type="SEASONAL_DOMESTIC",
        hourly_rate_cents=1600,
        certified_ride_classes=["MAJOR"],
    )
    own_shift = book_crew(
        stop["id"],
        chief["id"],
        "SETUP",
        "2026-09-01T08:00:00Z",
        "2026-09-01T16:00:00Z",
    )

    chief_headers = make_crew_chief_headers(chief["id"])
    validate_error(
        api.list_worker_crew_assignments(other["id"], chief_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )

    rows, meta = validate_paginated(
        api.list_worker_crew_assignments(chief["id"], chief_headers)
    )
    assert meta["total_count"] == 1
    roster_row = rows[0]
    assert roster_row["id"] == own_shift["id"]
    assert_crew_assignment(roster_row)
    assert roster_row["crew_role"] == "SETUP"
    assert roster_row["shift_hours"] == 8.0
    assert roster_row["cost_cents"] == 17600
