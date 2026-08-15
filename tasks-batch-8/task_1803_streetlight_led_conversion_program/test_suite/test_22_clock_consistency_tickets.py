"""Corner coverage: the default logical clock, immediate-consistency dispatch
responses, and ticket terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_ticket,
    get_ticket,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    make_program_manager_headers,
    resolve_ticket,
    set_clock,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    triage_and_dispatch_ticket,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


def test_default_clock_pins_period_and_timestamps(api):
    """PRD section 2.4: "The system never reads wall-clock time. All date and
    datetime derivations ... read a server-side logical clock whose value
    before it is ever set is exactly 2026-08-01T00:00:00Z"; PRD section 3.5:
    "its current_period initializes to the logical clock's calendar month in
    YYYY-MM form"; PRD section 3.6: "The server stamps reporter_user_id from
    the caller and reported_at from the logical clock".

    Design: Corner/cross_cutting_complexity_layers/layer_default_clock_pins_period_and_timestamps
    """
    # NOTE: no clock-set call anywhere in this test — fixtures run untouched.
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="CK-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=90)

    acct = create_account(district["id"], "UTILITY_OWNED", account_number="AC-U")
    assert acct["current_period"] == "2026-08"

    ticket = create_ticket(pole["id"], reporter_user_id="citizen-1", description="out",
                           hazard_flag=False)
    assert ticket["reported_at"] == "2026-08-01T00:00:00Z"


def test_immediate_dispatch_response_carries_mutation(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in the
    data field"; PRD section 3.4: "Dispatch from PENDING debits that estimate
    (§2.5), stores the fixture fields, moves the route RELEASED -> IN_PROGRESS
    on the route's first dispatch".

    Design: Corner/consistency_model/consistency_immediate_dispatch_response_carries_mutation
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="IC-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
    wo = wos[0]
    assert wo["version"] == 1 and wo["execution_status"] == "PENDING"

    resp = api.dispatch_work_order(
        wo["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    dispatched = validate_success(resp)
    # the dispatch RESPONSE itself carries the mutation — no re-read needed
    assert dispatched["execution_status"] == "DISPATCHED"
    assert dispatched["estimated_labor_cost_cents"] == 4500  # rhu(6000*45/60)
    assert dispatched["version"] == wo["version"] + 1

    # the route's state is observable in the same immediate read model
    from test_helpers import get_route
    assert get_route(route["id"])["status"] == "IN_PROGRESS"


def test_ticket_terminal_lockdown_family(api):
    """PRD section 3.6: "moves `OPEN` or `REOPENED` → `TRIAGED`
    (`ERR_TICKET_NOT_OPEN` otherwise)"; "requires `DISPATCHED`
    (`ERR_TICKET_NOT_DISPATCHED`)"; "Verification moves `RESOLVED` →
    `VERIFIED`; reopening moves `RESOLVED` → `REOPENED`; both require
    `X-User-ID` equal to `reporter_user_id` (`ERR_FORBIDDEN`) and a `RESOLVED`
    ticket (`ERR_TICKET_NOT_RESOLVED`)".

    Design: Corner/state_machines/sm_ticket_terminal_lockdown_family
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="N-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=90)
    ta = create_ticket(pole["id"], reporter_user_id="citizen-1", description="A",
                       hazard_flag=False)
    triage_and_dispatch_ticket(ta["id"], crew["id"])
    set_clock("2026-08-02T00:00:00Z")
    resolve_ticket(ta["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
    resp = api.verify_ticket(ta["id"], make_citizen_reporter_headers("citizen-1"))
    validate_success(resp)
    assert get_ticket(ta["id"])["status"] == "VERIFIED"

    # VERIFIED is terminal for triage, resolve, and reopen
    resp = api.triage_ticket(ta["id"], PM)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_OPEN, expected_status=409)
    resp = api.resolve_ticket(
        ta["id"], {"resolution_code": "NO_FAULT_FOUND"},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_DISPATCHED, expected_status=409)
    resp = api.reopen_ticket(ta["id"], make_citizen_reporter_headers("citizen-1"))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_RESOLVED, expected_status=409)

    # an OPEN (never resolved) ticket cannot reopen either
    tb = create_ticket(pole["id"], reporter_user_id="citizen-1", description="B",
                       hazard_flag=False)
    assert tb["status"] == "OPEN"
    resp = api.reopen_ticket(tb["id"], make_citizen_reporter_headers("citizen-1"))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_RESOLVED, expected_status=409)
    assert get_ticket(ta["id"])["status"] == "VERIFIED"
    assert get_ticket(tb["id"])["status"] == "OPEN"
