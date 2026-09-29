"""Clock gates, gating permits, operating windows and the money that closes a run."""

from test_helpers import (
    AUDITOR,
    CLERK,
    CLOCK_AT_CLOSE,
    CLOCK_AT_LOAD_IN,
    CLOCK_AT_OPEN,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GENERAL_MANAGER,
    GIANT_WHEEL,
    LOT_BOSS,
    NEGOTIATOR,
    ROUTE_MANAGER,
    TRANSPORT_PERMIT_VALID_FROM,
    TRANSPORT_PERMIT_VALID_UNTIL,
    ApiErrorId,
    adjudicate_closure,
    approved_permit,
    assert_instant_equals,
    assert_lot_ledgers,
    assert_make_good_arrangement,
    assert_settlement,
    assert_settlement_amounts,
    assert_ticket_sale,
    book_crew,
    build_settlement,
    cancel_crew,
    create_make_good_payload,
    create_settlement_payload,
    create_ticket_sale_payload,
    create_weather_closure_payload,
    current_contract_version,
    decide_permit,
    file_permit,
    list_allocation_inspections,
    log_closure,
    make_good_response_payload,
    read_allocation,
    read_readiness,
    read_ride,
    read_route,
    read_route_stop,
    read_settlement,
    read_weather_closure,
    record_inspection_result,
    record_sale,
    register_worker,
    release_allocation,
    respond_make_good,
    set_logical_clock,
    setup_confirmed_lot,
    setup_lot_in_setup,
    setup_open_lot,
    submit_permit,
    teardown_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

INSPECTABLE_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=False)
STATE_INSPECTED_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=True)
OPERATOR_SPEC = {
    "full_name": "Op One",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
}
OPERATOR_SHIFT = {
    "crew_role": "RIDE_OPERATOR",
    "shift_start": "2026-09-04T12:00:00Z",
    "shift_end": "2026-09-04T20:00:00Z",
}
BIG_GUARANTEE_DEAL = {
    "counterparty_name": "Franklin County Ag Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 1,
    "settlement_basis": "SPLIT_ONLY",
}
THIN_GUARANTEE_DEAL = dict(BIG_GUARANTEE_DEAL, guarantee_cents=20000)


def _confirmed_lot_without_permits():
    """An EXECUTED deal on a CONFIRMED lot carrying one COMMITTED unit."""
    return setup_confirmed_lot(
        contract_overrides=BIG_GUARANTEE_DEAL,
        ride_specs=[INSPECTABLE_WHEEL],
        jurisdiction_overrides={"requires_state_ride_inspection": False},
    )


def _permit_row(api, route_stop_id: str, permit_id: str) -> dict:
    """Re-read one permit through the lot's permit listing."""
    rows, _meta = validate_paginated(
        api.list_route_stop_permit_applications(route_stop_id, CLERK)
    )
    matches = [row for row in rows if row["id"] == permit_id]
    assert len(matches) == 1, "the filed permit must appear exactly once on the lot"
    return matches[0]


def test_the_setup_and_gate_clock_errors_fire_on_both_sides_of_the_windows(api):
    """PRD §3.7: "The logical clock must have reached the lot's `load_in_start`,
    else `ERR_LOAD_IN_NOT_OPEN`."

    PRD §3.7: "The checks run in the global order of §2.7, which means an
    unresolved inspection is reported before a missing permit or a thin crew: first
    the lot must be `SETUP`; then the posture must not be `INSPECTION_HOLD`, else
    `ERR_INSPECTION_NOT_PASSED`; then the logical clock must have reached
    `open_date`, else `ERR_GATES_BEFORE_OPEN_DATE`; then the count of the lot's
    allocations in `COMMITTED` must be at least the `ride_minimum_count` of the
    lot's `EXECUTED` deal, else `ERR_RIDE_MINIMUM_NOT_MET`; then the `EVENT` permit
    must be in hand and unexpired, else `ERR_PERMIT_NOT_APPROVED` or
    `ERR_PERMIT_EXPIRED`; and finally the posture must not be `LABOR_HOLD`, else
    `ERR_CREW_COVERAGE_INSUFFICIENT`."

    PRD §3.7: "Opening the gates moves every one of the lot's `COMMITTED`
    allocations to `OPERATING` and re-derives the lot's `operating_ride_count`. It
    also reaches across to the route: a route sitting in `COMMITTED` advances
    `COMMITTED → IN_PROGRESS` the moment its first lot opens."

    Design: Corner/errors/the_setup_and_gate_clock_errors_fire_on_both_sides_of_the_windows
    """
    ctx = _confirmed_lot_without_permits()
    stop_id = ctx["stop"]["id"]
    approved_permit(
        stop_id,
        "TRANSPORT",
        TRANSPORT_PERMIT_VALID_FROM,
        TRANSPORT_PERMIT_VALID_UNTIL,
        axles_declared=4,
    )
    approved_permit(
        stop_id, "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
    )
    operator = register_worker(**OPERATOR_SPEC)
    first_shift = book_crew(stop_id, operator["id"], **OPERATOR_SHIFT)

    set_logical_clock("2026-09-01T05:00:00Z")
    validate_error(
        api.begin_setup(stop_id, LOT_BOSS),
        ApiErrorId.ERR_LOAD_IN_NOT_OPEN.value,
        expected_status=409,
    )
    assert read_route_stop(stop_id)["status"] == "CONFIRMED"

    set_logical_clock(CLOCK_AT_LOAD_IN)
    in_setup = validate_success(api.begin_setup(stop_id, LOT_BOSS))
    assert in_setup["status"] == "SETUP"

    validate_error(
        api.open_gates(stop_id, LOT_BOSS),
        ApiErrorId.ERR_GATES_BEFORE_OPEN_DATE.value,
        expected_status=409,
    )

    set_logical_clock(CLOCK_AT_OPEN)
    cancelled = cancel_crew(first_shift["id"])
    assert cancelled["status"] == "RELEASED"

    validate_error(
        api.open_gates(stop_id, LOT_BOSS),
        ApiErrorId.ERR_CREW_COVERAGE_INSUFFICIENT.value,
        expected_status=409,
    )
    held = read_readiness(stop_id, LOT_BOSS)
    assert held["compliance_posture"] == "LABOR_HOLD"
    assert held["crew_coverage_ok"] is False
    assert read_route_stop(stop_id)["status"] == "SETUP"

    book_crew(stop_id, operator["id"], **OPERATOR_SHIFT)
    opened = validate_success(api.open_gates(stop_id, LOT_BOSS))
    assert opened["status"] == "OPEN"
    assert opened["operating_ride_count"] == 1
    assert read_allocation(ctx["allocations"][0]["id"])["status"] == "OPERATING"
    assert read_route(ctx["route"]["id"])["status"] == "IN_PROGRESS"


def test_the_transport_permit_gate_reports_unapproved_then_expired(api):
    """PRD §3.7: "And the lot must hold a `TRANSPORT` permit in `APPROVED` whose
    `valid_from` is at or before `load_in_start` and whose `valid_until` is at or
    after `teardown_deadline`, else `ERR_PERMIT_NOT_APPROVED`."

    PRD §3.4: "An `APPROVED` permit whose `valid_until` has fallen behind the
    logical clock is moved `APPROVED → EXPIRED`, and this sweep is evaluated at the
    start of setup and at the opening of the gates, before the permit checks those
    operations run — so a permit that lapsed while the lot sat idle is recognized
    as expired rather than silently satisfying the gate."

    PRD §3.4: "it is the jurisdiction's `permit_fee_cents` base fee plus, for a
    `TRANSPORT` permit only, a surcharge of 1,500 cents (fifteen dollars) for each
    declared axle."

    Design: Corner/errors/the_transport_permit_gate_reports_unapproved_then_expired
    """
    ctx = _confirmed_lot_without_permits()
    stop_id = ctx["stop"]["id"]
    permit = file_permit(
        stop_id,
        "TRANSPORT",
        "2026-08-02T00:00:00Z",
        "2026-08-31T00:00:00Z",
        axles_declared=4,
    )
    submitted = submit_permit(permit["id"])
    assert submitted["status"] == "SUBMITTED"

    set_logical_clock(CLOCK_AT_LOAD_IN)
    validate_error(
        api.begin_setup(stop_id, LOT_BOSS),
        ApiErrorId.ERR_PERMIT_NOT_APPROVED.value,
        expected_status=409,
    )
    assert _permit_row(api, stop_id, permit["id"])["status"] == "SUBMITTED", (
        "an undecided permit is not swept into EXPIRED"
    )

    approved = decide_permit(permit["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["fee_cents"] == 56000

    validate_error(
        api.begin_setup(stop_id, LOT_BOSS),
        ApiErrorId.ERR_PERMIT_EXPIRED.value,
        expected_status=409,
    )
    assert _permit_row(api, stop_id, permit["id"])["status"] == "EXPIRED"
    assert read_route_stop(stop_id)["status"] == "CONFIRMED"


def test_setup_without_a_committed_ride_reports_no_committed_rides(api):
    """PRD §3.7: "The lot must hold at least one allocation in `COMMITTED` or
    `INSPECTION_HELD`, else `ERR_NO_COMMITTED_RIDES` — there is no point opening a
    gate to an empty lot."

    PRD §3.3: "Release stamps `released_at` from the logical clock and reduces the
    lot's `allocated_sqft_used` by this allocation's `footprint_charged_sqft` and
    its `power_amps_used` by this allocation's `power_charged_amps`. The ride
    returns to `AVAILABLE` unless it is `OUT_OF_SERVICE` or still holds another
    allocation in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`."

    Design: Corner/errors/setup_without_a_committed_ride_reports_no_committed_rides
    """
    ctx = _confirmed_lot_without_permits()
    stop_id = ctx["stop"]["id"]
    permit = approved_permit(
        stop_id,
        "TRANSPORT",
        TRANSPORT_PERMIT_VALID_FROM,
        TRANSPORT_PERMIT_VALID_UNTIL,
        axles_declared=4,
    )
    assert permit["status"] == "APPROVED"

    released = release_allocation(ctx["allocations"][0]["id"])
    assert released["status"] == "RELEASED"
    assert read_ride(ctx["rides"][0]["id"])["status"] == "AVAILABLE"

    set_logical_clock(CLOCK_AT_LOAD_IN)
    validate_error(
        api.begin_setup(stop_id, LOT_BOSS),
        ApiErrorId.ERR_NO_COMMITTED_RIDES.value,
        expected_status=409,
    )

    stop = read_route_stop(stop_id)
    assert stop["status"] == "CONFIRMED"
    assert_lot_ledgers(stop, 0, 0.0)
    assert _permit_row(api, stop_id, permit["id"])["status"] == "APPROVED", (
        "a permit still inside its validity window is not swept"
    )


def test_the_gates_report_the_unpassed_inspection_first_and_the_ride_minimum_second(api):
    """PRD §3.7: "The checks run in the global order of §2.7, which means an unresolved
    inspection is reported before a missing permit or a thin crew: first the lot must
    be `SETUP`; then the posture must not be `INSPECTION_HOLD`, else
    `ERR_INSPECTION_NOT_PASSED`; then the logical clock must have reached `open_date`,
    else `ERR_GATES_BEFORE_OPEN_DATE`; then the count of the lot's allocations in
    `COMMITTED` must be at least the `ride_minimum_count` of the lot's `EXECUTED`
    deal, else `ERR_RIDE_MINIMUM_NOT_MET`; then the `EVENT` permit must be in hand and
    unexpired, else `ERR_PERMIT_NOT_APPROVED` or `ERR_PERMIT_EXPIRED`; and finally the
    posture must not be `LABOR_HOLD`, else `ERR_CREW_COVERAGE_INSUFFICIENT`."

    PRD §3.5: "The ladder considers the UTC calendar days from the day of the
    lot's `load_in_start` through the day of its `open_date`, inclusive."

    PRD §3.5: "The ladder picks the **earliest** candidate day, and because
    calendar days are distinct the ranking never ties; the chosen day at 14:00:00Z
    becomes the inspection's `scheduled_date`."

    PRD §3.7: "The second test is inspections. If any of the lot's allocations in
    `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING` either is itself
    `INSPECTION_HELD`, or belongs to a ride whose `requires_state_inspection` is
    true at a lot whose jurisdiction sets `requires_state_ride_inspection` and has
    no inspection order of its own with `authority` `STATE`, `status` `PASSED` and
    a `scheduled_date` at or before the lot's `open_date`, then the posture is
    `INSPECTION_HOLD` and its blocking error is `ERR_INSPECTION_NOT_PASSED`."

    Design: Corner/errors/the_gates_report_the_unpassed_inspection_first_and_the_ride_minimum_second
    """
    ctx = setup_lot_in_setup(
        contract_overrides=dict(BIG_GUARANTEE_DEAL, ride_minimum_count=2),
        ride_specs=[STATE_INSPECTED_WHEEL],
        jurisdiction_overrides={
            "requires_state_ride_inspection": True,
            "inspection_slot_capacity_per_day": 2,
        },
        worker_specs=[OPERATOR_SPEC],
    )
    stop_id = ctx["stop"]["id"]
    allocation_id = ctx["allocations"][0]["id"]

    set_logical_clock(CLOCK_AT_OPEN)
    validate_error(
        api.open_gates(stop_id, LOT_BOSS),
        ApiErrorId.ERR_INSPECTION_NOT_PASSED.value,
        expected_status=409,
    )
    held = read_readiness(stop_id, LOT_BOSS)
    assert held["compliance_posture"] == "INSPECTION_HOLD"
    assert held["inspections_ok"] is False

    orders = list_allocation_inspections(allocation_id)
    assert len(orders) == 1, "the commit cascade orders exactly one state inspection"
    order = orders[0]
    assert order["authority"] == "STATE"
    assert order["status"] == "SCHEDULED"
    assert order["attempt_number"] == 1
    assert_instant_equals(
        order["scheduled_date"], "2026-09-01T14:00:00Z", "scheduled_date"
    )

    passed = record_inspection_result(order["id"], "PASS")
    assert passed["status"] == "PASSED"
    cleared = read_readiness(stop_id, LOT_BOSS)
    assert cleared["compliance_posture"] == "CLEAR"
    assert cleared["committed_ride_count"] == 1
    assert cleared["ride_minimum_required"] == 2

    validate_error(
        api.open_gates(stop_id, LOT_BOSS),
        ApiErrorId.ERR_RIDE_MINIMUM_NOT_MET.value,
        expected_status=409,
    )
    assert read_route_stop(stop_id)["status"] == "SETUP"
    assert read_route(ctx["route"]["id"])["status"] == "COMMITTED"
    assert read_allocation(allocation_id)["status"] == "COMMITTED"


def test_the_ticket_closure_and_make_good_gates_all_fire_on_an_open_lot(api):
    """PRD §3.8: "a `business_date`, the UTC operating date the batch is booked to,
    which must fall inside the lot's window from `open_date` to `close_date`, a
    batch outside it being refused with `ERR_SALE_OUTSIDE_OPERATING_WINDOW`."

    PRD §3.8: "The closure must actually intersect at least one of the lot's daily
    operating windows, else it is refused with
    `ERR_CLOSURE_OUTSIDE_OPERATING_WINDOW`."

    PRD §3.8: "Four conditions guard the proposal. The deal must have exactly one
    settlement in `PROVISIONAL`, else `ERR_NO_PROVISIONAL_SETTLEMENT`. The
    referenced closure must be `ADJUDICATED` and must belong to the same lot as the
    deal, else `ERR_MAKEGOOD_STOP_MISMATCH`. Refund eligibility depends on the
    weather: a `CASH_REFUND` is admitted only where the closure's `cause` is `WIND`
    or `LIGHTNING`, since only those are refund-eligible causes; a `RAIN` or `HEAT`
    closure may be compensated with `SPONSOR_CREDIT` or `BONUS_DAY` only, and a
    cash refund against one is refused with `ERR_REFUND_NOT_ELIGIBLE`."

    PRD §3.8: "The cap is 30 percent of the deal's `guarantee_cents`, rounded
    half-up to whole cents. Summing the `amount_cents` already committed by the
    deal's arrangements in `PROPOSED` or `ACCEPTED`, if that running total plus the
    smaller of the raw amount and the cap would exceed the cap, the proposal is
    refused with `ERR_MAKEGOOD_CAP_EXCEEDED`. Otherwise `amount_cents` is the
    smaller of the raw amount and the cap, and the arrangement enters `PROPOSED`
    with `responded_at` null."

    PRD §2.7: "**Settlement state** — `ERR_SETTLEMENT_STATE_INVALID`: a settlement
    must be `PROVISIONAL` to be disputed or finalized and `DISPUTED` to be
    reconciled, and when a newly created settlement supersedes an existing row that
    row must be `PROVISIONAL` or `DISPUTED`."

    Design: Corner/errors/the_ticket_closure_and_make_good_gates_all_fire_on_an_open_lot
    """
    ctx = setup_open_lot(
        contract_overrides=THIN_GUARANTEE_DEAL,
        ride_specs=[INSPECTABLE_WHEEL],
        worker_specs=[OPERATOR_SPEC],
    )
    stop_id = ctx["stop"]["id"]
    contract_id = ctx["contract"]["id"]
    set_logical_clock("2026-09-06T18:00:00Z")

    validate_error(
        api.create_ticket_sale(
            stop_id,
            create_ticket_sale_payload(
                "WRISTBAND", 100, 1000, "2026-09-08T18:00:00Z"
            ),
            AUDITOR,
        ),
        ApiErrorId.ERR_SALE_OUTSIDE_OPERATING_WINDOW.value,
        expected_status=422,
    )

    sale = validate_success(
        api.create_ticket_sale(
            stop_id,
            create_ticket_sale_payload(
                "WRISTBAND", 100, 1000, "2026-09-05T18:00:00Z"
            ),
            AUDITOR,
        ),
        expected_status=201,
    )
    assert_ticket_sale(sale)
    assert sale["gross_cents"] == 100000

    validate_error(
        api.create_weather_closure(
            stop_id,
            create_weather_closure_payload(
                "WIND", "2026-09-05T02:00:00Z", "2026-09-05T03:00:00Z"
            ),
            ROUTE_MANAGER,
        ),
        ApiErrorId.ERR_CLOSURE_OUTSIDE_OPERATING_WINDOW.value,
        expected_status=422,
    )

    rain = log_closure(
        stop_id, "RAIN", "2026-09-05T14:00:00Z", "2026-09-05T17:00:00Z"
    )
    assert rain["closure_hours_raw"] == 3.0
    adjudicated = adjudicate_closure(rain["id"])
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["abated_hours"] == 3.0
    assert read_route_stop(stop_id)["closure_hours_adjudicated"] == 3.0

    validate_error(
        api.create_make_good(
            create_make_good_payload(rain["id"], contract_id, "SPONSOR_CREDIT"),
            GENERAL_MANAGER,
        ),
        ApiErrorId.ERR_NO_PROVISIONAL_SETTLEMENT.value,
        expected_status=409,
    )

    settlement = build_settlement(contract_id)
    assert_settlement(settlement)
    assert settlement["status"] == "PROVISIONAL"
    assert settlement["variant"] == "PROVISIONAL"
    assert_settlement_amounts(
        settlement,
        gross_cents=100000,
        tax_cents=6500,
        taxable_net_cents=93500,
        split_share_cents=60775,
        shortfall_penalty_cents=0,
        makegood_deduction_cents=0,
        settlement_due_cents=60775,
    )

    still_logged = log_closure(
        stop_id, "WIND", "2026-09-06T14:00:00Z", "2026-09-06T15:00:00Z"
    )
    assert still_logged["status"] == "LOGGED"
    validate_error(
        api.create_make_good(
            create_make_good_payload(
                still_logged["id"], contract_id, "SPONSOR_CREDIT"
            ),
            GENERAL_MANAGER,
        ),
        ApiErrorId.ERR_MAKEGOOD_STOP_MISMATCH.value,
        expected_status=422,
    )

    validate_error(
        api.create_make_good(
            create_make_good_payload(rain["id"], contract_id, "CASH_REFUND"),
            GENERAL_MANAGER,
        ),
        ApiErrorId.ERR_REFUND_NOT_ELIGIBLE.value,
        expected_status=422,
    )

    credit = validate_success(
        api.create_make_good(
            create_make_good_payload(rain["id"], contract_id, "SPONSOR_CREDIT"),
            GENERAL_MANAGER,
        ),
        expected_status=201,
    )
    assert_make_good_arrangement(credit)
    assert credit["status"] == "PROPOSED"
    assert credit["responded_at"] is None
    assert credit["amount_cents"] == 6000, (
        "the raw sponsor credit is clamped to 30 percent of the guarantee"
    )

    accepted = respond_make_good(credit["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    validate_error(
        api.respond_make_good(
            credit["id"], make_good_response_payload("ACCEPT"), NEGOTIATOR
        ),
        ApiErrorId.ERR_MAKEGOOD_STATE_INVALID.value,
        expected_status=409,
    )

    validate_error(
        api.create_make_good(
            create_make_good_payload(rain["id"], contract_id, "SPONSOR_CREDIT"),
            GENERAL_MANAGER,
        ),
        ApiErrorId.ERR_MAKEGOOD_CAP_EXCEEDED.value,
        expected_status=422,
    )

    validate_error(
        api.reconcile_settlement(settlement["id"], AUDITOR),
        ApiErrorId.ERR_SETTLEMENT_STATE_INVALID.value,
        expected_status=409,
    )
    assert read_settlement(settlement["id"])["status"] == "PROVISIONAL"

    rows, meta = validate_paginated(
        api.list_contract_make_goods(contract_id, GENERAL_MANAGER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == credit["id"]
    assert rows[0]["status"] == "ACCEPTED"


def test_finalize_reports_the_pending_make_good_then_the_already_final_settlement(api):
    """PRD §3.8: "Four conditions apply: the settlement must be `PROVISIONAL`, else
    `ERR_SETTLEMENT_STATE_INVALID`; the lot must be `TEARDOWN`, else
    `ERR_STOP_STATE_INVALID`; every weather closure of the lot must be
    `ADJUDICATED`, a lingering `LOGGED` closure answering
    `ERR_CLOSURE_NOT_ADJUDICATED`; and every make-good arrangement of the deal must
    be `ACCEPTED` or `DECLINED`, a lingering `PROPOSED` one answering
    `ERR_MAKEGOOD_PENDING`."

    PRD §3.8: "It then cascades. The lot advances `TEARDOWN → CLOSED`. That
    closure moves every `SCHEDULED` crew assignment of the lot to `COMPLETED`, and
    each completion recomputes its worker's `worked_days_count` on the worked
    basis. The route's `closed_stop_count` is re-derived, and a route in
    `IN_PROGRESS` whose closed count has caught up with its `stop_count` advances
    to `CLOSED`."

    PRD §2.7: "**Money already closed** — `ERR_SETTLEMENT_ALREADY_FINAL` when a new
    settlement is created for a contract that already has a `FINAL` settlement, or
    when a make-good response accepts an arrangement on such a contract. This check
    deliberately runs **ahead** of the route-stop state gate below: the stop is
    `CLOSED` precisely *because* the settlement went `FINAL`, so reporting the
    derived stop state would hide the real cause."

    Design: Corner/errors/finalize_reports_the_pending_make_good_then_the_already_final_settlement
    """
    ctx = setup_open_lot(
        contract_overrides=BIG_GUARANTEE_DEAL,
        ride_specs=[INSPECTABLE_WHEEL],
        worker_specs=[OPERATOR_SPEC],
    )
    stop_id = ctx["stop"]["id"]
    contract_id = ctx["contract"]["id"]

    set_logical_clock("2026-09-05T18:00:00Z")
    record_sale(stop_id, "WRISTBAND", 100, 1000, "2026-09-05T18:00:00Z")
    rain = log_closure(
        stop_id, "RAIN", "2026-09-05T14:00:00Z", "2026-09-05T17:00:00Z"
    )
    adjudicate_closure(rain["id"])

    set_logical_clock(CLOCK_AT_CLOSE)
    struck = teardown_lot(stop_id)
    assert struck["status"] == "TEARDOWN"

    settlement = build_settlement(contract_id)
    assert settlement["status"] == "PROVISIONAL"

    credit = validate_success(
        api.create_make_good(
            create_make_good_payload(rain["id"], contract_id, "SPONSOR_CREDIT"),
            GENERAL_MANAGER,
        ),
        expected_status=201,
    )
    assert credit["amount_cents"] == 9496

    validate_error(
        api.finalize_settlement(settlement["id"], GENERAL_MANAGER),
        ApiErrorId.ERR_MAKEGOOD_PENDING.value,
        expected_status=409,
    )
    assert read_settlement(settlement["id"])["status"] == "PROVISIONAL"

    declined = respond_make_good(credit["id"], "DECLINE")
    assert declined["status"] == "DECLINED"

    final = validate_success(
        api.finalize_settlement(settlement["id"], GENERAL_MANAGER)
    )
    assert final["status"] == "FINAL"
    assert final["variant"] == "FINAL"
    assert_instant_equals(final["finalized_at"], CLOCK_AT_CLOSE, "finalized_at")
    assert_settlement_amounts(
        final,
        gross_cents=100000,
        tax_cents=6500,
        taxable_net_cents=93500,
        split_share_cents=60775,
        shortfall_penalty_cents=0,
        makegood_deduction_cents=0,
        settlement_due_cents=60775,
    )

    assert read_route_stop(stop_id)["status"] == "CLOSED"
    closed_route = read_route(ctx["route"]["id"])
    assert closed_route["status"] == "CLOSED"
    assert closed_route["closed_stop_count"] == 1
    assert read_allocation(ctx["allocations"][0]["id"])["status"] == "STRUCK"
    assert read_weather_closure(rain["id"])["status"] == "ADJUDICATED"

    validate_error(
        api.create_settlement(
            create_settlement_payload(
                contract_id, current_contract_version(contract_id)
            ),
            AUDITOR,
        ),
        ApiErrorId.ERR_SETTLEMENT_ALREADY_FINAL.value,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_contract_settlements(contract_id, AUDITOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == settlement["id"]
    assert rows[0]["status"] == "FINAL"
