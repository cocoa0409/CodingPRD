"""Declared initial states and the refusals that guard each lifecycle step."""

from test_helpers import (
    CLERK,
    CLOCK_AT_LOAD_IN,
    CLOCK_START,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GENERAL_MANAGER,
    GIANT_WHEEL,
    LOT_BOSS,
    OFFICER,
    ROUTE_MANAGER,
    TRANSPORT_PERMIT_VALID_FROM,
    TRANSPORT_PERMIT_VALID_UNTIL,
    ApiErrorId,
    adjudicate_closure,
    assert_contract,
    assert_instant_equals,
    assert_permit_application,
    assert_weather_closure,
    decide_permit,
    draft_contract,
    file_permit,
    log_closure,
    make_general_manager_headers,
    permit_decision_payload,
    read_allocation,
    read_contract,
    read_route,
    read_route_stop,
    read_weather_closure,
    register_ride,
    reserve_allocation,
    set_logical_clock,
    setup_confirmed_lot,
    setup_open_lot,
    setup_planned_lot,
    submit_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

OPEN_LOT_CONTRACT = {
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 1,
    "settlement_basis": "SPLIT_ONLY",
}
OPEN_LOT_RIDE = dict(GIANT_WHEEL, requires_state_inspection=False)
OPEN_LOT_OPERATOR = {
    "full_name": "Op One",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
}


def test_a_fresh_route_lot_deal_allocation_and_permit_hold_their_initial_states(api):
    """PRD §3.1: "The new stop enters `PLANNED` with `sequence_index` and
    `travel_hours_from_previous` at 0, every capacity, labor and closure
    aggregate at 0, and a `compliance_posture` of `PERMIT_HOLD` — no lot is clear
    before its event permit exists."

    PRD §3.2: "A fresh deal sits in `DRAFT` with `negotiation_round` at 0,
    `last_sent_by_user_id` null and `executed_at` null."

    PRD §3.4: "A new permit sits in `DRAFT` with `submitted_at`, `decided_at`
    and `denial_reason` all null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = setup_planned_lot()
    stop_id = ctx["stop"]["id"]
    contract = draft_contract(stop_id)
    allocation = reserve_allocation(register_ride(OPEN_LOT_RIDE)["id"], stop_id)
    permit = file_permit(
        stop_id,
        "TRANSPORT",
        TRANSPORT_PERMIT_VALID_FROM,
        TRANSPORT_PERMIT_VALID_UNTIL,
        axles_declared=4,
    )

    route = read_route(ctx["route"]["id"])
    assert route["status"] == "DRAFT"
    assert route["stop_count"] == 1
    assert route["total_guaranteed_cents"] == 0

    stop = read_route_stop(stop_id)
    assert stop["status"] == "PLANNED"
    assert stop["sequence_index"] == 0
    assert stop["travel_hours_from_previous"] == 0
    assert stop["operating_days"] == 3
    assert stop["scheduled_operating_hours"] == 24
    assert stop["compliance_posture"] == "PERMIT_HOLD"

    assert_contract(contract)
    assert contract["status"] == "DRAFT"
    assert contract["negotiation_round"] == 0
    assert contract["last_sent_by_user_id"] is None
    assert contract["executed_at"] is None
    assert contract["guarantee_cents"] == 0
    assert contract["ride_minimum_count"] == 0
    assert contract["exclusivity"] == "NONE"
    assert contract["settlement_basis"] == "GREATER_OF"

    assert allocation["status"] == "RESERVED"
    assert allocation["released_at"] is None

    assert_permit_application(permit)
    assert permit["status"] == "DRAFT"
    assert permit["submitted_at"] is None
    assert permit["decided_at"] is None
    assert permit["denial_reason"] is None
    assert permit["fee_cents"] == 56000


def test_beginning_setup_on_a_planned_lot_reports_the_stop_state(api):
    """PRD §3.7: "**Beginning setup** — `CONFIRMED → SETUP` — is available to a
    `RouteManager` or a `LotBoss`."

    PRD §2.7: "**Route-stop state** — `ERR_STOP_STATE_INVALID`. The stop must be
    `PLANNED`, `CONFIRMED` or `SETUP` to reserve a ride; `CONFIRMED` to begin setup;
    `SETUP` to open gates; `OPEN` to tear down; `PLANNED`, `CONFIRMED`, `SETUP` or
    `OPEN` to be cancelled; `OPEN` or `TEARDOWN` to record a ticket sale, to log a
    closure, to adjudicate a closure or to create a settlement; `TEARDOWN` to
    finalize a settlement; `PLANNED`, `CONFIRMED` or `SETUP` to submit a permit;
    `PLANNED` to execute a contract; and anything other than `CLOSED` to release an
    allocation or cancel a crew shift."

    Design: Corner/state_machines/begin_setup_on_a_planned_stop_is_rejected
    """
    ctx = setup_planned_lot()
    stop_id = ctx["stop"]["id"]
    set_logical_clock(CLOCK_AT_LOAD_IN)

    validate_error(
        api.begin_setup(stop_id, LOT_BOSS), ApiErrorId.ERR_STOP_STATE_INVALID.value
    )

    stop = read_route_stop(stop_id)
    assert stop["status"] == "PLANNED"
    assert stop["version"] == 1, "the refused transition must not touch the lot"


def test_countersigning_an_already_executed_deal_reports_the_contract_state(api):
    """PRD §3.2: "Third, the stop must still be `PLANNED`, else
    `ERR_STOP_STATE_INVALID`."

    PRD §2.7: "**Route-stop state** — `ERR_STOP_STATE_INVALID`. The stop must be
    `PLANNED`, `CONFIRMED` or `SETUP` to reserve a ride; `CONFIRMED` to begin
    setup; `SETUP` to open gates; `OPEN` to tear down; `PLANNED`, `CONFIRMED`,
    `SETUP` or `OPEN` to be cancelled; `OPEN` or `TEARDOWN` to record a ticket
    sale, to log a closure, to adjudicate a closure or to create a settlement;
    `TEARDOWN` to finalize a settlement; `PLANNED`, `CONFIRMED` or `SETUP` to
    submit a permit; `PLANNED` to execute a contract; and anything other than
    `CLOSED` to release an allocation or cancel a crew shift."

    The first execution confirmed the lot, so the second attempt trips the
    route-stop gate at priority 13 — ahead of the contract-state gate at
    priority 14.

    PRD §2.10: "The **guarantee ledger** of a route, `total_guaranteed_cents`,
    is the sum of `guarantee_cents` over the contracts covering that route's
    stops whose status is `EXECUTED`."

    Design: Corner/state_machines/executing_an_already_executed_contract_is_rejected
    """
    ctx = setup_confirmed_lot(contract_overrides={"guarantee_cents": 500000})
    contract_id = ctx["contract"]["id"]

    validate_error(
        api.execute_contract(contract_id, make_general_manager_headers("user-gm-2")),
        ApiErrorId.ERR_STOP_STATE_INVALID.value,
    )

    contract = read_contract(contract_id)
    assert contract["status"] == "EXECUTED"
    assert contract["version"] == 3

    route = read_route(ctx["route"]["id"])
    assert route["total_guaranteed_cents"] == 500000, (
        "the refused second execution must not add the guarantee twice"
    )

    stop = read_route_stop(ctx["stop"]["id"])
    assert stop["status"] == "CONFIRMED"


def test_a_permit_walks_from_draft_through_submitted_to_approved(api):
    """PRD §3.4: "**Submitting** a permit (`DRAFT → SUBMITTED`) is also a
    `ComplianceClerk` action, admitted while the lot is `PLANNED`, `CONFIRMED` or
    `SETUP`, and it is where the lead-time rule bites."

    PRD §3.4: "Submission stamps `submitted_at` from the logical clock."

    PRD §3.4: "Approval moves the permit `SUBMITTED → APPROVED` and stamps
    `decided_at`; denial moves it `SUBMITTED → DENIED`, stamps `decided_at` and
    stores the supplied `denial_reason` on the row."

    PRD §3.4: "it is the jurisdiction's `permit_fee_cents` base fee plus, for a
    `TRANSPORT` permit only, a surcharge of 1,500 cents (fifteen dollars) for
    each declared axle."

    Design: Corner/state_machines/permit_submit_then_approve_walks_draft_to_approved
    """
    ctx = setup_planned_lot()
    stop_id = ctx["stop"]["id"]
    permit = file_permit(
        stop_id,
        "TRANSPORT",
        TRANSPORT_PERMIT_VALID_FROM,
        TRANSPORT_PERMIT_VALID_UNTIL,
        axles_declared=4,
    )

    set_logical_clock(CLOCK_START)
    submitted = validate_success(api.submit_permit_application(permit["id"], CLERK))
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], CLOCK_START, "submitted_at")
    assert submitted["decided_at"] is None
    assert submitted["version"] == 2

    set_logical_clock("2026-08-02T00:00:00Z")
    approved = validate_success(
        api.decide_permit_application(
            permit["id"],
            permit_decision_payload("APPROVE"),
            OFFICER,
        )
    )
    assert approved["status"] == "APPROVED"
    assert_instant_equals(approved["decided_at"], "2026-08-02T00:00:00Z", "decided_at")
    assert approved["version"] == 3
    assert approved["denial_reason"] is None
    assert approved["fee_cents"] == 56000

    assert read_route_stop(stop_id)["compliance_posture"] == "PERMIT_HOLD"


def test_resubmitting_a_denied_permit_reports_the_permit_state(api):
    """PRD §2.7: "**Other child-resource state** — a permit must be `DRAFT` to submit
    and `SUBMITTED` to decide (`ERR_PERMIT_STATE_INVALID`); an inspection order must
    be `SCHEDULED` to record a result (`ERR_INSPECTION_STATE_INVALID`); a crew
    assignment must be `SCHEDULED` to cancel (`ERR_ASSIGNMENT_STATE_INVALID`); a
    weather closure must be `LOGGED` to adjudicate (`ERR_CLOSURE_STATE_INVALID`); a
    make-good arrangement must be `PROPOSED` to respond to
    (`ERR_MAKEGOOD_STATE_INVALID`)."

    PRD §3.4: "denial moves it `SUBMITTED → DENIED`, stamps `decided_at` and
    stores the supplied `denial_reason` on the row."

    Design: Corner/state_machines/submitting_an_already_denied_permit_is_rejected
    """
    ctx = setup_planned_lot()
    stop_id = ctx["stop"]["id"]
    permit = file_permit(
        stop_id, "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
    )
    submit_permit(permit["id"])
    denied = decide_permit(
        permit["id"], "DENY", denial_reason="Lot abuts a school zone"
    )
    assert denied["status"] == "DENIED"

    validate_error(
        api.submit_permit_application(permit["id"], CLERK),
        ApiErrorId.ERR_PERMIT_STATE_INVALID.value,
    )

    rows, meta = validate_paginated(
        api.list_route_stop_permit_applications(
            stop_id, CLERK, params={"status": "DENIED"}
        )
    )
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["status"] == "DENIED"
    assert row["version"] == 3
    assert row["denial_reason"] == "Lot abuts a school zone"
    assert row["fee_cents"] == 50000

    assert read_route_stop(stop_id)["compliance_posture"] == "PERMIT_HOLD"


def test_adjudicating_a_closure_twice_reports_the_closure_state(api):
    """PRD §2.7: "**Other child-resource state** — a permit must be `DRAFT` to submit
    and `SUBMITTED` to decide (`ERR_PERMIT_STATE_INVALID`); an inspection order must
    be `SCHEDULED` to record a result (`ERR_INSPECTION_STATE_INVALID`); a crew
    assignment must be `SCHEDULED` to cancel (`ERR_ASSIGNMENT_STATE_INVALID`); a
    weather closure must be `LOGGED` to adjudicate (`ERR_CLOSURE_STATE_INVALID`); a
    make-good arrangement must be `PROPOSED` to respond to
    (`ERR_MAKEGOOD_STATE_INVALID`)."

    PRD §3.8: "Logging computes `closure_hours_raw`, the elapsed hours from
    `closed_from` to `closed_to` rounded half-up to two decimals, before any
    clipping or merging, and the row enters `LOGGED` with `abated_hours` at 0."

    Design: Corner/state_machines/adjudicating_an_already_adjudicated_closure_is_rejected
    """
    ctx = setup_open_lot(
        contract_overrides=OPEN_LOT_CONTRACT,
        ride_specs=[OPEN_LOT_RIDE],
        worker_specs=[OPEN_LOT_OPERATOR],
    )
    stop_id = ctx["stop"]["id"]
    set_logical_clock("2026-09-05T00:00:00Z")
    closure = log_closure(
        stop_id, "WIND", "2026-09-04T14:00:00Z", "2026-09-04T17:00:00Z"
    )
    adjudicated = adjudicate_closure(closure["id"])
    assert adjudicated["status"] == "ADJUDICATED"

    validate_error(
        api.adjudicate_weather_closure(closure["id"], GENERAL_MANAGER),
        ApiErrorId.ERR_CLOSURE_STATE_INVALID.value,
    )

    row = read_weather_closure(closure["id"])
    assert_weather_closure(row)
    assert row["status"] == "ADJUDICATED"
    assert row["closure_hours_raw"] == 3.0
    assert row["abated_hours"] == 3.0, "the second call must not double-count"

    stop = read_route_stop(stop_id)
    assert stop["closure_hours_adjudicated"] == 3.0
    assert stop["status"] == "OPEN"


def test_striking_the_lot_before_the_close_date_reports_the_clock_gate(api):
    """PRD §3.7: "**Tearing down** — `OPEN → TEARDOWN` — requires only that the
    logical clock has reached the lot's `close_date`, a premature attempt
    answering `ERR_TEARDOWN_BEFORE_CLOSE_DATE`."

    PRD §3.7: "Opening the gates moves every one of the lot's `COMMITTED`
    allocations to `OPERATING` and re-derives the lot's `operating_ride_count`."

    Design: Corner/state_machines/teardown_before_the_close_date_is_rejected
    """
    ctx = setup_open_lot(
        contract_overrides=OPEN_LOT_CONTRACT,
        ride_specs=[OPEN_LOT_RIDE],
        worker_specs=[OPEN_LOT_OPERATOR],
    )
    stop_id = ctx["stop"]["id"]

    validate_error(
        api.teardown_route_stop(stop_id, ROUTE_MANAGER),
        ApiErrorId.ERR_TEARDOWN_BEFORE_CLOSE_DATE.value,
    )

    stop = read_route_stop(stop_id)
    assert stop["status"] == "OPEN"
    assert stop["operating_ride_count"] == 1

    allocation = read_allocation(ctx["allocations"][0]["id"])
    assert allocation["status"] == "OPERATING"

    assert read_route(ctx["route"]["id"])["status"] == "IN_PROGRESS"
