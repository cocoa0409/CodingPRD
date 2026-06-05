"""Breadth tests: valid and invalid state transitions, terminal lockdown, cascades.

Covers queue B section: state_machines.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)


def test_activate_already_active_contract_invalid_state(api):
    """PRD §3.2: "Activation, performed by the `Customer`, takes a contract from `DRAFT`
    to `ACTIVE`; it is permitted only when the contract is currently in `DRAFT`."

    Re-activating an already-ACTIVE contract is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_already_active_contract_invalid_state
    """
    _, _, con = fx.setup_active_contract(zip="30001",
                                         contract_overrides={"contract_price_cents": 10000,
                                                             "term_months": 3})
    cust_headers = fx.make_customer_headers(con["customer_id"])
    resp = api.activate_contract(con["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_complete_scheduled_visit_invalid_state(api):
    """PRD §3.6: "A visit may be completed only from `DISPATCHED`, and only when its
    assigned `equipment_id` is set and that equipment's `status` is still `IN_SERVICE`."

    Completing a never-dispatched SCHEDULED visit is rejected with ERR_INVALID_STATE and
    the visit stays SCHEDULED.

    Design: Corner/state_machines/complete_scheduled_visit_invalid_state
    """
    ctx, visit = fx.setup_scheduled_visit(
        zip="30002",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 10000,
                            "term_months": 3},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
        with_equipment=False,
    )
    crew = fx.make_crew(ctx["route"]["id"])
    resp = api.complete_visit(visit["id"], fx.make_crew_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert fx.get_visit(visit["id"])["status"] == "SCHEDULED"


def test_contract_initial_state_is_draft(api):
    """PRD §3.2: "A freshly created contract is born in `DRAFT` status with its
    provisional `accrued_balance_cents` running balance at zero."

    Design: Corner/state_machines/contract_initial_state_is_draft
    """
    cust = fx.make_customer(service_zip="30003")
    prop = fx.make_property(cust["id"], zip="30003")
    con = validate_success(
        api.create_contract(
            {"customer_id": cust["id"], "property_id": prop["id"], "season": "WINTER",
             "contract_price_cents": 9000, "term_months": 2},
            fx.make_customer_headers(cust["id"]),
        ),
        expected_status=201,
    )
    assert con["status"] == "DRAFT"


def test_closed_contract_terminal_lockdown(api):
    """PRD §3.2: "A contract moves through four states: `DRAFT`, `ACTIVE`, `SUSPENDED`, and `CLOSED`, with `CLOSED` terminal."
    PRD §3.2: "Suspension, performed by a `DispatchManager`, takes an `ACTIVE` contract to `SUSPENDED` and is permitted only from `ACTIVE`."

    Suspending a CLOSED contract is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/closed_contract_terminal_lockdown
    """
    _, _, con = fx.setup_active_contract(zip="30004",
                                         contract_overrides={"contract_price_cents": 10000,
                                                             "term_months": 3})
    fx.api_client.close_season(con["id"], TEST_USERS["dispatcher_headers"])
    resp = api.suspend_contract(con["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert fx.get_contract(con["id"])["status"] == "CLOSED"


def test_reject_skip_keeps_visit_scheduled(api):
    """PRD §3.7: "Rejection is permitted only from `PENDING`, sets the request to `REJECTED`, grants no credit, and leaves the referenced visit in `SCHEDULED`."

    Design: Corner/state_machines/reject_skip_keeps_visit_scheduled
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="30005",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 30000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    rejected = validate_success(
        api.reject_skip_request(skip["id"], TEST_USERS["dispatcher_headers"])
    )
    assert rejected["status"] == "REJECTED"
    assert fx.get_visit(visit["id"])["status"] == "SCHEDULED"
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 0


def test_suspend_cascades_routestop_inactive(api):
    """PRD §3.2: "every `RouteStop` whose `property_id` matches the contract's property
    has its `active` flag flipped to false, removing it from all future dispatch sweeps."

    Design: Corner/state_machines/suspend_cascades_routestop_inactive
    """
    ctx = fx.setup_route_with_stop(zip="30006",
                                   contract_overrides={"contract_price_cents": 10000,
                                                       "term_months": 3})
    suspended = validate_success(
        api.suspend_contract(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    )
    assert suspended["status"] == "SUSPENDED"
    assert fx.get_route_stop(ctx["stop"]["id"])["active"] is False


def test_close_season_blocked_by_open_dispatch(api):
    """PRD §3.2: "Closing is permitted only when the contract is `ACTIVE` and when no service visit on the contract is currently in `DISPATCHED` state; an attempt to close a season with an open dispatch outstanding is rejected with `ERR_OPEN_DISPATCH_EXISTS`."

    Design: Corner/state_machines/close_season_blocked_by_open_dispatch
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="30007",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
        with_crew=False,
    )
    resp = api.close_season(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_DISPATCH_EXISTS.value)
    assert fx.get_contract(ctx["contract"]["id"])["status"] == "ACTIVE"


def test_start_maintenance_on_maintenance_due_valid(api):
    """PRD §3.8: "A `DispatchManager` begins maintenance, moving the equipment from `MAINTENANCE_DUE` to `UNDER_MAINTENANCE`; this transition is permitted only from `MAINTENANCE_DUE`."

    Design: Corner/state_machines/maintenance_due_to_under_maintenance_valid
    """
    ctx, completed, eq = fx.setup_equipment_maintenance_due(zip="30008", age_months=24,
                                                            runtime_hours=44)
    assert eq["status"] == "MAINTENANCE_DUE"
    moved = validate_success(
        api.start_maintenance(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"])
    )
    assert moved["status"] == "UNDER_MAINTENANCE"
