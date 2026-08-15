"""Trip completion cascade: charter credit arithmetic, program accrual,
void compensation, and immediate visibility (PRD §3.4, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_dispatch_ready, setup_active_agreement,
    create_trip, approve_charter_trip, assign_duty, schedule_trip,
    complete_trip, post_expense, setup_enrolled_program,
    generate_statement, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]
FO = TEST_USERS["flight_ops_headers"]
MP = TEST_USERS["maintenance_planner_headers"]
FC = TEST_USERS["finance_controller_headers"]




def _duty_window_for(departure_at):
    """Duty window covering the departure day, 06:00 to 14:00 local schedule.

    For the 2026-08-06 charter departures this matches the 06:00-14:00 window;
    for other departures the window is derived from the departure timestamp.
    """
    day = departure_at[:10]
    return (f"{day}T06:00:00Z", f"{day}T14:00:00Z")


def _setup_charter_trip_scheduled(api, tail_number, quote, direct_costs=(),
                                  departure_at="2026-08-06T08:00:00Z",
                                  block_hours_est=6.0):
    """Dispatch-ready scenario + CHARTER trip approved, direct costs posted,
    crew assigned, SCHEDULED. Returns (scenario, trip)."""
    scenario = setup_dispatch_ready(tail_number=tail_number)
    aircraft_id = scenario["aircraft"]["id"]
    trip = create_trip(
        aircraft_id, trip_use="CHARTER", departure_at=departure_at,
        block_hours_est=block_hours_est, charter_quote_cents=quote,
        arrive_icao="KMIA",
    )
    approve_charter_trip(trip["id"], scenario["owner"]["id"])
    for i, cost in enumerate(direct_costs):
        post_expense(
            aircraft_id, category="CHARTER_DIRECT", amount_cents=cost,
            service_date=departure_at[:10], vendor_name=f"Charter Vendor {i}",
            tax_use="CHARTER_USE", trip_id=trip["id"], paid_date=None,
        )
    window = _duty_window_for(departure_at)
    assign_duty(trip["id"], scenario["captain"]["id"], "PIC", *window)
    assign_duty(trip["id"], scenario["first_officer"]["id"], "SIC", *window)
    trip = schedule_trip(trip["id"])
    return scenario, trip


def test_charter_credit_net_share_on_completion_response(api):
    """PRD §3.8: "When the net is strictly positive, `owner_credit_cents` is
    the net multiplied by the agreement's `charter_owner_share_pct`, rounded
    half up to integer cents, and `charter_shortfall_cents` is zero."
    PRD §3.8: "let the direct charter cost be the sum of `amount_cents` over
    the trip's non-`VOID` expenses in category `CHARTER_DIRECT`, and let the
    net be `charter_quote_cents` minus that direct cost."

    Design: Difficulty/combinatorial_formula/charter_credit_net_share_with_floor
    """
    _scenario, trip = _setup_charter_trip_scheduled(
        api, "N300JX", quote=900000, direct_costs=(200000, 50000)
    )

    completed = complete_trip(trip["id"], 6.0)
    assert completed["status"] == "COMPLETED"
    # net = 900000 - 250000 = 650000; credit = round_half_up(650000 x 0.85).
    assert completed["owner_credit_cents"] == 552500
    assert completed["charter_shortfall_cents"] == 0


def test_charter_credit_net_share_visible_on_fetch(api):
    """PRD §3.8: "When the net is strictly positive, `owner_credit_cents` is
    the net multiplied by the agreement's `charter_owner_share_pct`, rounded
    half up to integer cents, and `charter_shortfall_cents` is zero."

    Design: Difficulty/combinatorial_formula/charter_credit_net_share_with_floor
    """
    _scenario, trip = _setup_charter_trip_scheduled(
        api, "N300JX", quote=900000, direct_costs=(200000, 50000)
    )
    complete_trip(trip["id"], 6.0)

    fetched = validate_success(api.get_trip(trip["id"], FO), 200)
    assert fetched["status"] == "COMPLETED"
    assert fetched["owner_credit_cents"] == 552500
    assert fetched["charter_shortfall_cents"] == 0


def _setup_breakeven_pair(api):
    """Two SCHEDULED charter trips: T1 quote 250000 with costs 200000+50000
    (net exactly 0); T2 quote 249999 with cost 250000 (net -1)."""
    scenario = setup_dispatch_ready(tail_number="N140JX")
    aircraft_id = scenario["aircraft"]["id"]
    owner_id = scenario["owner"]["id"]
    captain = scenario["captain"]
    first_officer = scenario["first_officer"]

    t1 = create_trip(aircraft_id, trip_use="CHARTER",
                     departure_at="2026-08-06T08:00:00Z", block_hours_est=5.0,
                     charter_quote_cents=250000, arrive_icao="KMIA")
    approve_charter_trip(t1["id"], owner_id)
    post_expense(aircraft_id, category="CHARTER_DIRECT", amount_cents=200000,
                 service_date="2026-08-06", vendor_name="JetFuel Co",
                 tax_use="CHARTER_USE", trip_id=t1["id"], paid_date=None)
    post_expense(aircraft_id, category="CHARTER_DIRECT", amount_cents=50000,
                 service_date="2026-08-06", vendor_name="Signature Landing",
                 tax_use="CHARTER_USE", trip_id=t1["id"], paid_date=None)
    assign_duty(t1["id"], captain["id"], "PIC",
                "2026-08-06T06:00:00Z", "2026-08-06T13:00:00Z")
    assign_duty(t1["id"], first_officer["id"], "SIC",
                "2026-08-06T06:00:00Z", "2026-08-06T13:00:00Z")
    t1 = schedule_trip(t1["id"])

    t2 = create_trip(aircraft_id, trip_use="CHARTER",
                     departure_at="2026-08-08T08:00:00Z", block_hours_est=5.0,
                     charter_quote_cents=249999, arrive_icao="KMIA")
    approve_charter_trip(t2["id"], owner_id)
    post_expense(aircraft_id, category="CHARTER_DIRECT", amount_cents=250000,
                 service_date="2026-08-08", vendor_name="JetFuel Co",
                 tax_use="CHARTER_USE", trip_id=t2["id"], paid_date=None)
    assign_duty(t2["id"], captain["id"], "PIC",
                "2026-08-08T06:00:00Z", "2026-08-08T13:00:00Z")
    assign_duty(t2["id"], first_officer["id"], "SIC",
                "2026-08-08T06:00:00Z", "2026-08-08T13:00:00Z")
    t2 = schedule_trip(t2["id"])
    return scenario, t1, t2


def test_charter_breakeven_is_zero_not_shortfall(api):
    """PRD §3.8: "When the net is exactly zero — a break-even trip — both
    values are zero; break-even is not a shortfall."

    Design: Difficulty/boundary_precision_check/charter_credit_breakeven_zero_not_shortfall
    """
    _scenario, t1, _t2 = _setup_breakeven_pair(api)

    completed = complete_trip(t1["id"], 5.0)
    assert completed["owner_credit_cents"] == 0
    assert completed["charter_shortfall_cents"] == 0, (
        "net exactly zero is break-even, not a shortfall"
    )


def test_charter_one_cent_below_costs_yields_shortfall(api):
    """PRD §3.8: "When the net is negative, the credit floors at zero and
    `charter_shortfall_cents` is the absolute amount by which direct costs
    exceeded the quote."

    Design: Difficulty/boundary_precision_check/charter_credit_breakeven_zero_not_shortfall
    """
    _scenario, _t1, t2 = _setup_breakeven_pair(api)

    completed = complete_trip(t2["id"], 5.0)
    assert completed["owner_credit_cents"] == 0
    assert completed["charter_shortfall_cents"] == 1, (
        f"net of -1 cent yields shortfall 1, got {completed['charter_shortfall_cents']}"
    )


def test_trip_completion_immediately_visible(api):
    """PRD §3.4: "Completion, performed by the `FlightOpsManager` against a `SCHEDULED` trip, carries the actual block time in `block_hours_actual`, which must be strictly greater than zero (`ERR_VALIDATION` otherwise)."
    PRD §3.4: "the aircraft's `total_time_hours` increases by `block_hours_actual`"
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/trip_completion_immediately_visible
    """
    _scenario, trip = _setup_charter_trip_scheduled(
        api, "N540JX", quote=900000, direct_costs=()
    )

    completed = complete_trip(trip["id"], 6.0)
    assert completed["status"] == "COMPLETED"
    assert completed["owner_credit_cents"] == 765000, (
        f"no direct costs: credit = 900000 x 0.85 = 765000, got "
        f"{completed['owner_credit_cents']}"
    )

    aircraft_id = _scenario["aircraft"]["id"]
    aircraft = validate_success(api.get_aircraft(aircraft_id, FO), 200)
    assert aircraft["total_time_hours"] == pytest.approx(6.0), (
        "immediate consistency: the read right after completion already shows "
        "the incremented airframe hours"
    )


def _setup_enrolled_program_scenario(api, tail_number):
    """Dispatch-ready scenario + ENROLLED program at 15000 cents/hour."""
    scenario = setup_dispatch_ready(tail_number=tail_number)
    program = setup_enrolled_program(scenario["aircraft"]["id"],
                                     rate_per_hour_cents=15000)
    scenario["program"] = program
    return scenario


def _schedule_owner_trip(api, scenario, departure_at="2026-08-06T08:00:00Z",
                         block_hours_est=5.0,
                         window=("2026-08-06T06:00:00Z", "2026-08-06T13:00:00Z")):
    trip = create_trip(scenario["aircraft"]["id"], trip_use="OWNER_USE",
                       departure_at=departure_at, block_hours_est=block_hours_est)
    assign_duty(trip["id"], scenario["captain"]["id"], "PIC", *window)
    assign_duty(trip["id"], scenario["first_officer"]["id"], "SIC", *window)
    return schedule_trip(trip["id"])


def test_trip_void_restores_airframe_hours_and_voids_accrual(api):
    """PRD §3.4: "A successful void subtracts `block_hours_actual` from the
    aircraft's `total_time_hours`, moves the completion-created accrual expense
    to `VOID`, resets `owner_credit_cents` and `charter_shortfall_cents` to
    null, and recomputes any `DRAFT` statement covering the period."
    PRD §3.4: "if a `MaintenanceProgram` of the aircraft is `ENROLLED` at the
    completion instant, the platform posts a new `Expense` with `category`
    `PROGRAM_ACCRUAL`, `tax_use` `MIXED`, `trip_id` set to this trip,
    `service_date` set to the completion date, and `amount_cents` equal to
    `block_hours_actual` multiplied by the program's `rate_per_hour_cents`,
    rounded half up to integer cents."

    Design: Difficulty/compensating_invariant/program_accrual_conserved_across_complete_and_void
    """
    scenario = _setup_enrolled_program_scenario(api, "N190JX")
    aircraft_id = scenario["aircraft"]["id"]
    trip = _schedule_owner_trip(api, scenario)
    complete_trip(trip["id"], 5.0)

    voided = validate_success(api.void_trip(trip["id"], FO), 200)
    assert voided["status"] == "VOID"
    assert voided.get("owner_credit_cents") is None, (
        "void must reset owner_credit_cents to null"
    )

    aircraft = validate_success(api.get_aircraft(aircraft_id, FO), 200)
    assert aircraft["total_time_hours"] == pytest.approx(0.0), (
        f"void must reverse the accrual of airframe hours, got "
        f"{aircraft['total_time_hours']}"
    )

    data, meta = validate_paginated(
        api.list_expenses(FO, params={"aircraft_id": aircraft_id,
                                      "category": "PROGRAM_ACCRUAL"})
    )
    assert meta["total_count"] == 1
    accrual = data[0]
    assert accrual["amount_cents"] == 75000  # 5.0h x 15000
    assert accrual["status"] == "VOID"


def test_trip_void_does_not_reverse_performed_duty(api):
    """PRD §3.4: "Duty that was actually performed is not un-performed: the
    trip's duty assignments remain `COMPLETED`, and the crew members'
    `flight_hours_total` is not reversed."

    Design: Difficulty/compensating_invariant/program_accrual_conserved_across_complete_and_void
    """
    scenario = _setup_enrolled_program_scenario(api, "N190JX")
    trip = _schedule_owner_trip(api, scenario)
    complete_trip(trip["id"], 5.0)
    validate_success(api.void_trip(trip["id"], FO), 200)

    data, meta = validate_paginated(
        api.list_assignments(FO, params={"trip_id": trip["id"]})
    )
    assert meta["total_count"] == 2
    assert all(a["status"] == "COMPLETED" for a in data), (
        "voided trip's duty assignments remain COMPLETED"
    )

    captain = validate_success(
        api.get_crew_member(scenario["captain"]["id"], FO), 200
    )
    assert captain["flight_hours_total"] == pytest.approx(5.0), (
        "flight_hours_total is not reversed by the void"
    )


def test_program_suspend_pauses_accrual(api):
    """PRD §3.5: "Suspension by the `MaintenancePlanner` moves an `ENROLLED`
    program to `SUSPENDED`, and while suspended no accrual is posted at trip
    completion."
    PRD §3.4: "if a `MaintenanceProgram` of the aircraft is `ENROLLED` at the completion instant, the platform posts a new `Expense` with `category` `PROGRAM_ACCRUAL`, `tax_use` `MIXED`, `trip_id` set to this trip, `service_date` set to the completion date, and `amount_cents` equal to `block_hours_actual` multiplied by the program's `rate_per_hour_cents`, rounded half up to integer cents."

    Design: Corner/state_machines/program_suspend_pauses_accrual
    """
    scenario = setup_dispatch_ready(tail_number="N300JB")
    aircraft_id = scenario["aircraft"]["id"]
    program = setup_enrolled_program(aircraft_id, rate_per_hour_cents=15000)
    suspended = validate_success(api.suspend_program(program["id"], MP), 200)
    assert suspended["status"] == "SUSPENDED"

    trip = _schedule_owner_trip(api, scenario)
    completed = complete_trip(trip["id"], 5.0)
    assert completed["status"] == "COMPLETED"

    aircraft = validate_success(api.get_aircraft(aircraft_id, FO), 200)
    assert aircraft["total_time_hours"] == pytest.approx(5.0)

    data, meta = validate_paginated(
        api.list_expenses(FO, params={"aircraft_id": aircraft_id,
                                      "category": "PROGRAM_ACCRUAL"})
    )
    assert meta["total_count"] == 0, (
        f"no accrual may be posted while the program is SUSPENDED, got "
        f"{meta['total_count']}"
    )


def _setup_completion_cascade_scenario(api):
    """ACTIVE agreement + ENROLLED program (15000/h) + QUALIFIED crew pair +
    ACCEPTED COI + FUEL expense 250000 + DRAFT statement 2026-08 + SCHEDULED
    OWNER_USE trip (est 5.0h, PIC/SIC assigned)."""
    scenario = _setup_enrolled_program_scenario(api, "N800JX")
    aircraft_id = scenario["aircraft"]["id"]
    post_expense(aircraft_id, category="FUEL", amount_cents=250000,
                 service_date="2026-08-05", paid_date="2026-08-07")
    statement = generate_statement(aircraft_id, period="2026-08")
    assert statement["accrual_total_cents"] == 250000
    assert statement["management_fee_cents"] == 525000
    trip = _schedule_owner_trip(api, scenario)
    scenario["statement"] = statement
    scenario["trip"] = trip
    return scenario


def test_trip_completion_accrues_hours_and_mints_program_expense(api):
    """PRD §3.4: "the trip's `block_hours_actual` is set; the aircraft's
    `total_time_hours` increases by `block_hours_actual`; every `ASSIGNED` duty
    assignment of the trip transitions to `COMPLETED`; each assigned crew
    member's `flight_hours_total` increases by `block_hours_actual`"
    PRD §3.4: "if a `MaintenanceProgram` of the aircraft is `ENROLLED` at the
    completion instant, the platform posts a new `Expense` with `category`
    `PROGRAM_ACCRUAL`, `tax_use` `MIXED`, `trip_id` set to this trip,
    `service_date` set to the completion date, and `amount_cents` equal to
    `block_hours_actual` multiplied by the program's `rate_per_hour_cents`,
    rounded half up to integer cents."

    Design: Difficulty/transitive_cascade/trip_completion_hours_accrual_statement_chain
    """
    scenario = _setup_completion_cascade_scenario(api)
    aircraft_id = scenario["aircraft"]["id"]
    trip = scenario["trip"]

    completed = complete_trip(trip["id"], 5.0)
    assert completed["status"] == "COMPLETED"

    aircraft = validate_success(api.get_aircraft(aircraft_id, FO), 200)
    assert aircraft["total_time_hours"] == pytest.approx(5.0)

    data, meta = validate_paginated(
        api.list_expenses(FO, params={"aircraft_id": aircraft_id,
                                      "category": "PROGRAM_ACCRUAL"})
    )
    assert meta["total_count"] == 1, (
        f"exactly one PROGRAM_ACCRUAL expense must be minted, got {meta['total_count']}"
    )
    accrual = data[0]
    assert accrual["status"] == "POSTED"
    assert accrual["amount_cents"] == 75000  # 5.0h x 15000 cents/hour
    assert accrual["trip_id"] == trip["id"]


def test_trip_completion_recomputes_draft_statement_and_crew_hours(api):
    """PRD §3.4: "That new expense itself triggers recomputation of any `DRAFT`
    monthly statement covering the completion period, as does the completion
    itself — the statement's charter offset and accrual totals pick up the new
    values."
    PRD §3.3: "When a trip completes, each of its `ASSIGNED` assignments moves
    to `COMPLETED`, and each assigned crew member's `flight_hours_total` — the
    running sum of `block_hours_actual` over completed trips where the crew
    member held an assignment — increases by the trip's `block_hours_actual`."

    Design: Difficulty/transitive_cascade/trip_completion_hours_accrual_statement_chain
    """
    scenario = _setup_completion_cascade_scenario(api)
    trip = scenario["trip"]
    statement = scenario["statement"]

    complete_trip(trip["id"], 5.0)

    recomputed = validate_success(api.get_statement(statement["id"], AE), 200)
    assert recomputed["status"] == "DRAFT"
    assert recomputed["accrual_total_cents"] == 325000, (
        f"250000 FUEL + 75000 PROGRAM_ACCRUAL, got "
        f"{recomputed['accrual_total_cents']}"
    )
    # fee = 500000 + round_half_up(0.10 x 325000) = 532500
    assert recomputed["management_fee_cents"] == 532500

    captain = validate_success(
        api.get_crew_member(scenario["captain"]["id"], FO), 200
    )
    assert captain["flight_hours_total"] == pytest.approx(5.0)
