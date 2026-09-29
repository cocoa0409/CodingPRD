"""Composite setup helpers.

The harness restarts the API before every test, so each helper here builds all of
its preconditions from scratch through the PRD-declared endpoints. Setup calls go
through ``get_success_data`` so that a broken precondition reports itself as a
setup failure rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_AT_LOAD_IN,
    CLOCK_AT_OPEN,
    CLOCK_AT_CLOSE,
    CLOCK_START,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    TRANSPORT_PERMIT_VALID_FROM,
    TRANSPORT_PERMIT_VALID_UNTIL,
)
from .factories import (
    counter_contract_payload,
    create_contract_payload,
    create_crew_assignment_payload,
    create_inspection_order_payload,
    create_jurisdiction_payload,
    create_make_good_payload,
    create_permit_application_payload,
    create_ride_allocation_payload,
    create_ride_payload,
    create_route_payload,
    create_route_stop_payload,
    create_settlement_payload,
    create_ticket_sale_payload,
    create_venue_payload,
    create_weather_closure_payload,
    create_worker_payload,
    dispute_settlement_payload,
    inspection_result_payload,
    make_good_response_payload,
    permit_decision_payload,
)
from .test_users import (
    GENERAL_MANAGER_USER_ID,
    NEGOTIATOR_SENDER_USER_ID,
    TEST_USERS,
    make_contract_negotiator_headers,
    make_general_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ROUTE_MANAGER = TEST_USERS["route_manager_headers"]
NEGOTIATOR = TEST_USERS["contract_negotiator_headers"]
GENERAL_MANAGER = TEST_USERS["general_manager_headers"]
LOT_BOSS = TEST_USERS["lot_boss_headers"]
SAFETY_OFFICER = TEST_USERS["safety_officer_headers"]
CLERK = TEST_USERS["compliance_clerk_headers"]
OFFICER = TEST_USERS["jurisdiction_officer_headers"]
AUDITOR = TEST_USERS["ticketing_auditor_headers"]


# ─── The ride units the fixtures draw on ──────────────────────────────────────
# Each entry is a complete `POST /rides` payload. The charged figures the PRD's
# spacing and surge formulas produce for each are noted for readability.

GIANT_WHEEL = {  # charged 5414 sqft / 375.0 A
    "name": "Giant Wheel",
    "ride_class": "MAJOR",
    "footprint_sqft": 4010,
    "power_amps": 300,
    "crew_size_setup": 6,
    "setup_hours": 8,
    "axle_count": 4,
}
TILT_A_WHIRL = {  # charged 2404 sqft / 138.0 A
    "name": "Tilt-A-Whirl",
    "ride_class": "FLAT",
    "footprint_sqft": 2003,
    "power_amps": 120,
    "crew_size_setup": 4,
    "setup_hours": 5,
    "axle_count": 2,
}
KIDDIE_COASTER = {  # charged 996 sqft / 60.0 A
    "name": "Kiddie Coaster",
    "ride_class": "KIDDIE",
    "footprint_sqft": 905,
    "power_amps": 60,
    "crew_size_setup": 2,
    "setup_hours": 3,
    "axle_count": 1,
}
CHAIR_SWINGS = {  # charged 1924 sqft / 103.5 A
    "name": "Chair Swings",
    "ride_class": "FLAT",
    "footprint_sqft": 1603,
    "power_amps": 90,
    "crew_size_setup": 3,
    "setup_hours": 4,
    "axle_count": 2,
}
KIDDIE_CARS = {  # charged 112 sqft / 1.0 A
    "name": "Kiddie Cars",
    "ride_class": "KIDDIE",
    "footprint_sqft": 101,
    "power_amps": 1,
    "crew_size_setup": 1,
    "setup_hours": 1,
    "axle_count": 1,
}
FUN_SLIDE = {  # charged 552 sqft / 387.0 A
    "name": "Fun Slide",
    "ride_class": "KIDDIE",
    "footprint_sqft": 501,
    "power_amps": 387,
    "crew_size_setup": 2,
    "setup_hours": 2,
    "axle_count": 1,
}
KIDDIE_WHIP = {  # charged 1925 sqft / 100.0 A
    "name": "Kiddie Whip",
    "ride_class": "KIDDIE",
    "footprint_sqft": 1750,
    "power_amps": 100,
    "crew_size_setup": 2,
    "setup_hours": 2,
    "axle_count": 2,
}
TEA_CUPS = {  # charged 11 sqft / 5.0 A
    "name": "Tea Cups",
    "ride_class": "KIDDIE",
    "footprint_sqft": 10,
    "power_amps": 5,
    "crew_size_setup": 1,
    "setup_hours": 1,
    "axle_count": 1,
}


# ─── Primitive setup steps ────────────────────────────────────────────────────

def set_logical_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def register_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN)
    )


def register_venue(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_venue(
            create_venue_payload(jurisdiction_id, **overrides), ADMIN
        )
    )


def register_ride(spec: dict = None, **overrides) -> dict:
    payload = dict(spec or GIANT_WHEEL)
    payload.update(overrides)
    return get_success_data(api_client.create_ride(create_ride_payload(**payload), ADMIN))


def register_worker(**overrides) -> dict:
    return get_success_data(
        api_client.create_worker(create_worker_payload(**overrides), ADMIN)
    )


def open_route(**overrides) -> dict:
    return get_success_data(
        api_client.create_route(create_route_payload(**overrides), ROUTE_MANAGER)
    )


def add_route_stop(route_id: str, venue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_route_stop(
            create_route_stop_payload(route_id, venue_id, **overrides), ROUTE_MANAGER
        )
    )


def sequence_route(route_id: str) -> dict:
    return get_success_data(api_client.sequence_route(route_id, ROUTE_MANAGER))


def commit_route(route_id: str) -> dict:
    return get_success_data(api_client.commit_route(route_id, ROUTE_MANAGER))


def read_route_stop(route_stop_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_route_stop(route_stop_id, headers or ROUTE_MANAGER)
    )


def read_route(route_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_route(route_id, headers or ROUTE_MANAGER))


def read_contract(contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers or NEGOTIATOR))


def read_ride(ride_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_ride(ride_id, headers or ADMIN))


def read_allocation(allocation_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_ride_allocation(allocation_id, headers or LOT_BOSS)
    )


def read_worker(worker_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_worker(worker_id, headers or ADMIN))


def read_settlement(settlement_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, headers or AUDITOR))


def read_readiness(route_stop_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_readiness(route_stop_id, headers or ROUTE_MANAGER)
    )


def read_weather_closure(closure_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_weather_closure(closure_id, headers or ROUTE_MANAGER)
    )


def current_stop_version(route_stop_id: str) -> int:
    """Re-read the lot immediately before a reservation.

    Every accepted reservation, and every cascade that touches the lot, bumps the
    stop's `version`, so the value a reservation must carry has to be read fresh.
    """
    return read_route_stop(route_stop_id, LOT_BOSS)["version"]


def reserve_allocation(ride_id: str, route_stop_id: str, **overrides) -> dict:
    """Reserve a ride onto a lot, refreshing the stop version first."""
    payload = create_ride_allocation_payload(
        ride_id, route_stop_id, current_stop_version(route_stop_id), **overrides
    )
    return get_success_data(api_client.create_ride_allocation(payload, LOT_BOSS))


def commit_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.commit_ride_allocation(allocation_id, LOT_BOSS))


def release_allocation(allocation_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.release_ride_allocation(allocation_id, headers or LOT_BOSS)
    )


def draft_contract(route_stop_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(route_stop_id, **overrides), NEGOTIATOR
        )
    )


def send_contract(contract_id: str, as_user_id: str = NEGOTIATOR_SENDER_USER_ID) -> dict:
    return get_success_data(
        api_client.send_contract(
            contract_id, make_contract_negotiator_headers(as_user_id)
        )
    )


def counter_contract(contract_id: str, **terms) -> dict:
    return get_success_data(
        api_client.counter_contract(
            contract_id, counter_contract_payload(**terms), NEGOTIATOR
        )
    )


def execute_contract(contract_id: str, as_user_id: str = GENERAL_MANAGER_USER_ID) -> dict:
    return get_success_data(
        api_client.execute_contract(contract_id, make_general_manager_headers(as_user_id))
    )


def file_permit(
    route_stop_id: str, permit_type: str, valid_from: str, valid_until: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_permit_application(
            create_permit_application_payload(
                route_stop_id, permit_type, valid_from, valid_until, **overrides
            ),
            CLERK,
        )
    )


def submit_permit(permit_id: str) -> dict:
    return get_success_data(api_client.submit_permit_application(permit_id, CLERK))


def decide_permit(permit_id: str, decision: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_permit_application(
            permit_id, permit_decision_payload(decision, **overrides), OFFICER
        )
    )


def approved_permit(
    route_stop_id: str, permit_type: str, valid_from: str, valid_until: str, **overrides
) -> dict:
    """File, submit and approve one permit in a single step."""
    permit = file_permit(
        route_stop_id, permit_type, valid_from, valid_until, **overrides
    )
    submit_permit(permit["id"])
    return decide_permit(permit["id"], "APPROVE")


def schedule_inspection(
    allocation_id: str, authority: str, scheduled_date: str
) -> dict:
    return get_success_data(
        api_client.create_inspection_order(
            create_inspection_order_payload(allocation_id, authority, scheduled_date),
            SAFETY_OFFICER,
        )
    )


def record_inspection_result(inspection_id: str, result: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_inspection_result(
            inspection_id, inspection_result_payload(result, **overrides), OFFICER
        )
    )


def list_allocation_inspections(allocation_id: str, **params) -> list:
    rows, _meta = validate_paginated(
        api_client.list_allocation_inspections(
            allocation_id, SAFETY_OFFICER, params=params or None
        )
    )
    return rows


def book_crew(
    route_stop_id: str,
    worker_id: str,
    crew_role: str,
    shift_start: str,
    shift_end: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(
                route_stop_id, worker_id, crew_role, shift_start, shift_end, **overrides
            ),
            LOT_BOSS,
        )
    )


def cancel_crew(assignment_id: str) -> dict:
    return get_success_data(api_client.cancel_crew_assignment(assignment_id, LOT_BOSS))


def begin_setup(route_stop_id: str) -> dict:
    return get_success_data(api_client.begin_setup(route_stop_id, LOT_BOSS))


def open_gates(route_stop_id: str) -> dict:
    return get_success_data(api_client.open_gates(route_stop_id, LOT_BOSS))


def teardown_lot(route_stop_id: str) -> dict:
    return get_success_data(api_client.teardown_route_stop(route_stop_id, LOT_BOSS))


def cancel_lot(route_stop_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_route_stop(route_stop_id, headers or ROUTE_MANAGER)
    )


def record_sale(
    route_stop_id: str, channel: str, units: int, unit_price_cents: int, business_date: str
) -> dict:
    return get_success_data(
        api_client.create_ticket_sale(
            route_stop_id,
            create_ticket_sale_payload(channel, units, unit_price_cents, business_date),
            AUDITOR,
        )
    )


def log_closure(route_stop_id: str, cause: str, closed_from: str, closed_to: str) -> dict:
    return get_success_data(
        api_client.create_weather_closure(
            route_stop_id,
            create_weather_closure_payload(cause, closed_from, closed_to),
            ROUTE_MANAGER,
        )
    )


def adjudicate_closure(closure_id: str) -> dict:
    return get_success_data(
        api_client.adjudicate_weather_closure(closure_id, GENERAL_MANAGER)
    )


def current_contract_version(contract_id: str) -> int:
    """Re-read the deal immediately before building a settlement.

    Creating a settlement increments the contract's `version`, so the expected
    value has to be read fresh for every settlement built against the same deal.
    """
    return read_contract(contract_id, AUDITOR)["version"]


def build_settlement(contract_id: str, **overrides) -> dict:
    payload = create_settlement_payload(
        contract_id, current_contract_version(contract_id), **overrides
    )
    return get_success_data(api_client.create_settlement(payload, AUDITOR))


def dispute_settlement(settlement_id: str, dispute_reason: str) -> dict:
    return get_success_data(
        api_client.dispute_settlement(
            settlement_id, dispute_settlement_payload(dispute_reason), NEGOTIATOR
        )
    )


def reconcile_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.reconcile_settlement(settlement_id, AUDITOR))


def finalize_settlement(settlement_id: str) -> dict:
    return get_success_data(
        api_client.finalize_settlement(settlement_id, GENERAL_MANAGER)
    )


def propose_make_good(weather_closure_id: str, contract_id: str, kind: str) -> dict:
    return get_success_data(
        api_client.create_make_good(
            create_make_good_payload(weather_closure_id, contract_id, kind),
            GENERAL_MANAGER,
        )
    )


def respond_make_good(make_good_id: str, response: str) -> dict:
    return get_success_data(
        api_client.respond_make_good(
            make_good_id, make_good_response_payload(response), NEGOTIATOR
        )
    )


# ─── Rediscovery by filtered list read ────────────────────────────────────────

def find_route_stop_by_status(status: str, headers=None) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_route_stops(headers or ROUTE_MANAGER, params={"status": status})
    )
    assert rows, f"Setup expected at least one route stop in {status}"
    return rows[0]


def find_contract_for_stop(route_stop_id: str, status: str, headers=None) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_contracts(
            headers or NEGOTIATOR,
            params={"route_stop_id": route_stop_id, "status": status},
        )
    )
    assert rows, f"Setup expected a {status} contract on stop {route_stop_id}"
    return rows[0]


def find_settlement_for_contract(contract_id: str, status: str, headers=None) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_contract_settlements(
            contract_id, headers or AUDITOR, params={"status": status}
        )
    )
    assert rows, f"Setup expected a {status} settlement on contract {contract_id}"
    return rows[0]


def list_stop_allocations(route_stop_id: str, **params) -> list:
    query = {"route_stop_id": route_stop_id}
    query.update(params)
    rows, _meta = validate_paginated(
        api_client.list_ride_allocations(LOT_BOSS, params=query)
    )
    return rows


# ─── Tier 1: reference data and a planned lot ─────────────────────────────────

def setup_reference_data(jurisdiction_overrides=None, venue_overrides=None) -> dict:
    """Logical clock at its start value, one jurisdiction and one lot."""
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction(**(jurisdiction_overrides or {}))
    venue = register_venue(jurisdiction["id"], **(venue_overrides or {}))
    return {"jurisdiction": jurisdiction, "venue": venue}


def setup_planned_lot(
    jurisdiction_overrides=None,
    venue_overrides=None,
    route_overrides=None,
    stop_overrides=None,
) -> dict:
    """A DRAFT route carrying one PLANNED lot on a freshly registered venue."""
    ctx = setup_reference_data(jurisdiction_overrides, venue_overrides)
    ctx["route"] = open_route(**(route_overrides or {}))
    ctx["stop"] = add_route_stop(
        ctx["route"]["id"], ctx["venue"]["id"], **(stop_overrides or {})
    )
    return ctx


def setup_planned_lot_with_allocations(
    ride_specs=None,
    jurisdiction_overrides=None,
    venue_overrides=None,
    stop_overrides=None,
) -> dict:
    """A PLANNED lot with one RESERVED allocation per supplied ride spec.

    The stop version is re-read before each reservation, so the allocations land
    in the order the specs are given and the lot ledgers accumulate.
    """
    ctx = setup_planned_lot(
        jurisdiction_overrides=jurisdiction_overrides,
        venue_overrides=venue_overrides,
        stop_overrides=stop_overrides,
    )
    ctx["rides"] = []
    ctx["allocations"] = []
    for spec in ride_specs or [GIANT_WHEEL]:
        ride = register_ride(spec)
        ctx["rides"].append(ride)
        ctx["allocations"].append(reserve_allocation(ride["id"], ctx["stop"]["id"]))
    return ctx


# ─── Tier 2: the deal and the itinerary lock ──────────────────────────────────

def setup_sequenced_route_with_draft_contract(
    contract_overrides=None, **planned_kwargs
) -> dict:
    """A SEQUENCED route whose single lot carries a DRAFT deal."""
    ctx = setup_planned_lot(**planned_kwargs)
    ctx["contract"] = draft_contract(
        ctx["stop"]["id"], **(contract_overrides or {})
    )
    ctx["route"] = sequence_route(ctx["route"]["id"])
    return ctx


def setup_committed_route_with_sent_contract(
    contract_overrides=None,
    sender_user_id: str = NEGOTIATOR_SENDER_USER_ID,
    ride_specs=None,
    **planned_kwargs,
) -> dict:
    """A COMMITTED route whose single lot carries a SENT deal.

    Any supplied ride specs are reserved onto the lot while it is still PLANNED,
    so that the later execution cascade has RESERVED allocations to commit.
    """
    ctx = setup_sequenced_route_with_draft_contract(
        contract_overrides=contract_overrides, **planned_kwargs
    )
    ctx["rides"] = []
    ctx["allocations"] = []
    for spec in ride_specs or []:
        ride = register_ride(spec)
        ctx["rides"].append(ride)
        ctx["allocations"].append(reserve_allocation(ride["id"], ctx["stop"]["id"]))
    ctx["contract"] = send_contract(ctx["contract"]["id"], as_user_id=sender_user_id)
    ctx["route"] = commit_route(ctx["route"]["id"])
    return ctx


def setup_confirmed_lot(
    contract_overrides=None,
    ride_specs=None,
    sender_user_id: str = NEGOTIATOR_SENDER_USER_ID,
    executor_user_id: str = GENERAL_MANAGER_USER_ID,
    **planned_kwargs,
) -> dict:
    """An EXECUTED deal on a CONFIRMED lot of a COMMITTED route."""
    ctx = setup_committed_route_with_sent_contract(
        contract_overrides=contract_overrides,
        ride_specs=ride_specs,
        sender_user_id=sender_user_id,
        **planned_kwargs,
    )
    ctx["contract"] = execute_contract(
        ctx["contract"]["id"], as_user_id=executor_user_id
    )
    ctx["stop"] = read_route_stop(ctx["stop"]["id"])
    ctx["route"] = read_route(ctx["route"]["id"])
    ctx["allocations"] = [
        read_allocation(allocation["id"]) for allocation in ctx["allocations"]
    ]
    return ctx


# ─── Tier 3: the full run up to open gates ────────────────────────────────────

DEFAULT_OPERATOR_SHIFT = {
    "crew_role": "RIDE_OPERATOR",
    "shift_start": "2026-09-04T12:00:00Z",
    "shift_end": "2026-09-04T20:00:00Z",
}


def setup_lot_in_setup(
    contract_overrides=None,
    ride_specs=None,
    worker_specs=None,
    crew_specs=None,
    transport_axles: int = 4,
    file_event_permit: bool = True,
    approve_event_permit: bool = True,
    pass_inspections: bool = False,
    **planned_kwargs,
) -> dict:
    """Walk a lot all the way to SETUP.

    Executes the deal, files and approves the TRANSPORT permit that gates setup,
    optionally files the EVENT permit that gates the gates, books the crew, then
    advances the logical clock past `load_in_start` and begins setup.
    """
    ctx = setup_confirmed_lot(
        contract_overrides=contract_overrides,
        ride_specs=ride_specs or [GIANT_WHEEL],
        **planned_kwargs,
    )
    stop_id = ctx["stop"]["id"]

    if pass_inspections:
        pass_all_scheduled_inspections(ctx)

    ctx["transport_permit"] = approved_permit(
        stop_id,
        "TRANSPORT",
        TRANSPORT_PERMIT_VALID_FROM,
        TRANSPORT_PERMIT_VALID_UNTIL,
        axles_declared=transport_axles,
    )
    if file_event_permit:
        event_permit = file_permit(
            stop_id, "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
        )
        # PRD §3.4: submitting moves the permit `DRAFT → SUBMITTED`, so the row
        # kept on the context has to be the post-submission one.
        event_permit = submit_permit(event_permit["id"])
        if approve_event_permit:
            event_permit = decide_permit(event_permit["id"], "APPROVE")
        ctx["event_permit"] = event_permit

    ctx["workers"] = [
        register_worker(**spec) for spec in (worker_specs or [default_operator_spec()])
    ]
    ctx["assignments"] = []
    for index, spec in enumerate(crew_specs or [dict(DEFAULT_OPERATOR_SHIFT)]):
        spec = dict(spec)
        worker_index = spec.pop("worker_index", index if index < len(ctx["workers"]) else 0)
        ctx["assignments"].append(
            book_crew(stop_id, ctx["workers"][worker_index]["id"], **spec)
        )

    set_logical_clock(CLOCK_AT_LOAD_IN)
    ctx["stop"] = begin_setup(stop_id)
    return ctx


def setup_open_lot(**kwargs) -> dict:
    """Walk a lot all the way to OPEN, advancing the clock to the open date."""
    ctx = setup_lot_in_setup(**kwargs)
    set_logical_clock(CLOCK_AT_OPEN)
    ctx["stop"] = open_gates(ctx["stop"]["id"])
    ctx["route"] = read_route(ctx["route"]["id"])
    ctx["allocations"] = [
        read_allocation(allocation["id"]) for allocation in ctx["allocations"]
    ]
    return ctx


def default_operator_spec() -> dict:
    """A permanent hand certified to run every class of unit on the midway."""
    return {
        "full_name": "Op One",
        "employment_type": "PERMANENT",
        "hourly_rate_cents": 1600,
        "certified_ride_classes": ["MAJOR", "FLAT", "KIDDIE"],
    }


def pass_all_scheduled_inspections(ctx: dict) -> None:
    """Record a PASS on every SCHEDULED inspection of the lot's allocations."""
    for allocation in ctx.get("allocations", []):
        for order in list_allocation_inspections(
            allocation["id"], status="SCHEDULED"
        ):
            record_inspection_result(order["id"], "PASS")


# ─── Tier 4: revenue, weather and the struck lot ──────────────────────────────

DEFAULT_SALE_SPECS = [
    {
        "channel": "WRISTBAND",
        "units": 100,
        "unit_price_cents": 1000,
        "business_date": "2026-09-04T18:00:00Z",
    }
]


def record_sales(route_stop_id: str, sale_specs=None) -> list:
    return [
        record_sale(route_stop_id, **spec)
        for spec in (sale_specs if sale_specs is not None else DEFAULT_SALE_SPECS)
    ]


def setup_open_lot_with_sales(sale_specs=None, sales_clock=None, **kwargs) -> dict:
    """An OPEN lot carrying booked sales batches."""
    ctx = setup_open_lot(**kwargs)
    if sales_clock:
        set_logical_clock(sales_clock)
    ctx["sales"] = record_sales(ctx["stop"]["id"], sale_specs)
    ctx["stop"] = read_route_stop(ctx["stop"]["id"])
    return ctx


def setup_teardown_lot(sale_specs=None, sales_clock=None, **kwargs) -> dict:
    """A struck lot: sales booked, clock advanced to the close date, TEARDOWN."""
    ctx = setup_open_lot_with_sales(
        sale_specs=sale_specs, sales_clock=sales_clock, **kwargs
    )
    set_logical_clock(CLOCK_AT_CLOSE)
    ctx["stop"] = teardown_lot(ctx["stop"]["id"])
    return ctx


# ─── Tier 5: settlement and finalization ──────────────────────────────────────

def setup_provisional_settlement_on_open_lot(**kwargs) -> dict:
    """An OPEN lot with a PROVISIONAL settlement built over its sales."""
    ctx = setup_open_lot_with_sales(**kwargs)
    ctx["settlement"] = build_settlement(ctx["contract"]["id"])
    ctx["contract"] = read_contract(ctx["contract"]["id"])
    return ctx


def setup_provisional_settlement_on_struck_lot(**kwargs) -> dict:
    """A TEARDOWN lot with a PROVISIONAL settlement ready to be finalized."""
    ctx = setup_teardown_lot(**kwargs)
    ctx["settlement"] = build_settlement(ctx["contract"]["id"])
    ctx["contract"] = read_contract(ctx["contract"]["id"])
    return ctx


def setup_finalized_settlement(**kwargs) -> dict:
    """A closed lot: the settlement finalized and the closure cascade run."""
    ctx = setup_provisional_settlement_on_struck_lot(**kwargs)
    ctx["settlement"] = finalize_settlement(ctx["settlement"]["id"])
    ctx["stop"] = read_route_stop(ctx["stop"]["id"])
    ctx["route"] = read_route(ctx["route"]["id"])
    return ctx
