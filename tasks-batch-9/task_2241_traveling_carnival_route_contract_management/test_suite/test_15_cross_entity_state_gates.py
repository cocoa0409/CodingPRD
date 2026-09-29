"""Writes refused by the state of a relative rather than by their own row."""

from test_helpers import (
    CLOCK_AT_CLOSE,
    CLOCK_AT_OPEN,
    CLOCK_START,
    GENERAL_MANAGER,
    GENERAL_MANAGER_USER_ID,
    LOT_BOSS,
    NEGOTIATOR_SENDER_USER_ID,
    TILT_A_WHIRL,
    ApiErrorId,
    adjudicate_closure,
    assert_guarantee_ledger,
    assert_instant_equals,
    assert_readiness,
    assert_settlement_amounts,
    commit_route,
    decide_permit,
    finalize_settlement,
    log_closure,
    read_allocation,
    read_contract,
    read_readiness,
    read_route,
    read_route_stop,
    read_settlement,
    read_weather_closure,
    send_contract,
    set_logical_clock,
    setup_lot_in_setup,
    setup_provisional_settlement_on_struck_lot,
    setup_sequenced_route_with_draft_contract,
    validate_error,
    validate_success,
)

GUARANTEED_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "GREATER_OF",
}
ONE_RIDE_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 1,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
CLOSE_OUT_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
PLAIN_TILT = dict(TILT_A_WHIRL, requires_state_inspection=False)
ADA_OPERATOR = {
    "full_name": "Ada Operator",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["FLAT"],
    "housing_required": False,
}
NO_STATE_INSPECTION = {
    "requires_state_ride_inspection": False,
    "max_consecutive_work_days": 6,
}
CLOSURE_FROM = "2026-09-05T14:00:00Z"
CLOSURE_TO = "2026-09-05T19:00:00Z"


def _sent_deal_on_a_route_that_is_only_sequenced():
    """A SENT deal whose route has been sequenced but never committed."""
    ctx = setup_sequenced_route_with_draft_contract(contract_overrides=GUARANTEED_DEAL)
    ctx["contract"] = send_contract(ctx["contract"]["id"])
    return ctx


def _lot_in_setup_awaiting_its_event_permit_decision():
    """A SETUP lot at its open date whose EVENT permit is submitted but undecided."""
    ctx = setup_lot_in_setup(
        contract_overrides=ONE_RIDE_DEAL,
        ride_specs=[PLAIN_TILT],
        worker_specs=[ADA_OPERATOR],
        approve_event_permit=False,
        jurisdiction_overrides=NO_STATE_INSPECTION,
        venue_overrides={"housing_pads_available": 4},
    )
    set_logical_clock(CLOCK_AT_OPEN)
    return ctx


def _struck_lot_with_an_unadjudicated_closure():
    """A TEARDOWN lot whose PROVISIONAL settlement sits behind a LOGGED closure."""
    ctx = setup_provisional_settlement_on_struck_lot(
        contract_overrides=CLOSE_OUT_DEAL,
        ride_specs=[PLAIN_TILT],
        worker_specs=[ADA_OPERATOR],
        jurisdiction_overrides=NO_STATE_INSPECTION,
    )
    ctx["closure"] = log_closure(
        ctx["stop"]["id"], "WIND", CLOSURE_FROM, CLOSURE_TO
    )
    return ctx


def test_a_deal_cannot_be_executed_while_its_route_is_still_sequenced(api):
    """PRD §3.2: "**Executing** a deal — `SENT → EXECUTED` — is reserved to a
    `GeneralManager` and is the single most consequential operation in the system. Four
    conditions guard it beyond the deal being `SENT`. First, segregation of duties: the
    executing manager's `X-User-ID` must differ from the deal's stored
    `last_sent_by_user_id`, and an attempt by the same user to countersign what they
    sent is refused with `ERR_SEGREGATION_OF_DUTIES`. Second, the route must be
    `COMMITTED`, else `ERR_ROUTE_STATE_INVALID`. Third, the stop must still be
    `PLANNED`, else `ERR_STOP_STATE_INVALID`."

    PRD §2.10: "The **guarantee ledger** of a route, `total_guaranteed_cents`, is the
    sum of `guarantee_cents` over the contracts covering that route's stops whose status
    is `EXECUTED`. Executing a deal adds its guarantee; terminating an executed deal
    subtracts it; voiding an unexecuted one changes nothing."

    Design: Difficulty/cross_entity_state_dependency/contract_execute_requires_the_parent_route_to_be_committed
    """
    ctx = _sent_deal_on_a_route_that_is_only_sequenced()
    assert ctx["route"]["status"] == "SEQUENCED"
    assert ctx["contract"]["status"] == "SENT"
    assert ctx["contract"]["last_sent_by_user_id"] == NEGOTIATOR_SENDER_USER_ID
    assert GENERAL_MANAGER_USER_ID != NEGOTIATOR_SENDER_USER_ID, (
        "the countersigning caller is a different user, so duties are segregated"
    )
    assert read_route_stop(ctx["stop"]["id"])["status"] == "PLANNED"

    validate_error(
        api.execute_contract(ctx["contract"]["id"], GENERAL_MANAGER),
        ApiErrorId.ERR_ROUTE_STATE_INVALID.value,
        expected_status=409,
    )

    untouched = read_contract(ctx["contract"]["id"])
    assert untouched["status"] == "SENT"
    assert untouched["executed_at"] is None
    assert_guarantee_ledger(read_route(ctx["route"]["id"]), 0)


def test_committing_the_route_alone_unblocks_the_countersignature(api):
    """PRD §3.1: "**Committing** a route (`SEQUENCED → COMMITTED`), open to a
    `RouteManager` or a `GeneralManager`, is the point of no return for the itinerary. It
    requires that every non-`DARK` stop of the route already carries a contract in
    `DRAFT`, `SENT`, `COUNTERED` or `EXECUTED`; a stop with no such deal blocks the
    commit with `ERR_STOP_NOT_CONTRACTED`. The commit itself changes nothing but the
    route's status and `version`."

    PRD §3.2: "Execution stamps `executed_at` from the logical clock, adds the deal's
    `guarantee_cents` to the route's `total_guaranteed_cents`, and then cascades. The
    first hop advances the lot `PLANNED → CONFIRMED`."

    PRD §2.10: "The **guarantee ledger** of a route, `total_guaranteed_cents`, is the
    sum of `guarantee_cents` over the contracts covering that route's stops whose status
    is `EXECUTED`."

    Design: Difficulty/cross_entity_state_dependency/contract_execute_requires_the_parent_route_to_be_committed
    """
    ctx = _sent_deal_on_a_route_that_is_only_sequenced()
    contract_id = ctx["contract"]["id"]

    validate_error(
        api.execute_contract(contract_id, GENERAL_MANAGER),
        ApiErrorId.ERR_ROUTE_STATE_INVALID.value,
        expected_status=409,
    )

    committed = commit_route(ctx["route"]["id"])
    assert committed["status"] == "COMMITTED"

    executed = validate_success(api.execute_contract(contract_id, GENERAL_MANAGER))
    assert executed["status"] == "EXECUTED"
    assert_instant_equals(executed["executed_at"], CLOCK_START, "executed_at")

    assert_guarantee_ledger(read_route(ctx["route"]["id"]), 900000)
    assert read_route_stop(ctx["stop"]["id"])["status"] == "CONFIRMED"


def test_the_gates_stay_shut_while_a_sibling_event_permit_is_undecided(api):
    """PRD §3.7: "The first test is the event permit. Unless the lot holds a permit
    whose `permit_type` is `EVENT`, whose `status` is `APPROVED`, whose `valid_from` is
    at or before the lot's `open_date` and whose `valid_until` is at or after its
    `close_date`, the posture is `PERMIT_HOLD`. The blocking error that posture would
    raise is `ERR_PERMIT_NOT_APPROVED`, except where such a permit exists but has gone
    `EXPIRED`, in which case it is `ERR_PERMIT_EXPIRED`."

    PRD §3.7: "The checks run in the global order of §2.7, which means an unresolved
    inspection is reported before a missing permit or a thin crew: first the lot must be
    `SETUP`; then the posture must not be `INSPECTION_HOLD`, else
    `ERR_INSPECTION_NOT_PASSED`; then the logical clock must have reached `open_date`,
    else `ERR_GATES_BEFORE_OPEN_DATE`; then the count of the lot's allocations in
    `COMMITTED` must be at least the `ride_minimum_count` of the lot's `EXECUTED` deal,
    else `ERR_RIDE_MINIMUM_NOT_MET`; then the `EVENT` permit must be in hand and
    unexpired, else `ERR_PERMIT_NOT_APPROVED` or `ERR_PERMIT_EXPIRED`; and finally the
    posture must not be `LABOR_HOLD`, else `ERR_CREW_COVERAGE_INSUFFICIENT`."

    PRD §3.7: "The readiness read exposes this reasoning directly, returning the lot's
    `route_stop_id`, its `compliance_posture`, the `blocking_error_id` that posture
    would raise (null when the posture is `CLEAR`), and four narrower signals:
    `event_permit_ok`, true when the event-permit test above is satisfied;
    `inspections_ok`, true when no allocation trips the inspection test;
    `crew_coverage_ok`, true when none of the three labor conditions holds;
    `committed_ride_count`, the number of the lot's allocations currently in
    `COMMITTED`; and `ride_minimum_required`, the `ride_minimum_count` of the lot's
    executed deal."

    Design: Difficulty/cross_entity_state_dependency/open_gates_blocked_by_a_sibling_event_permit_still_awaiting_decision
    """
    ctx = _lot_in_setup_awaiting_its_event_permit_decision()
    stop_id = ctx["stop"]["id"]
    assert ctx["stop"]["status"] == "SETUP"
    assert ctx["transport_permit"]["status"] == "APPROVED"
    assert ctx["event_permit"]["status"] == "SUBMITTED"

    readiness = read_readiness(stop_id, LOT_BOSS)
    assert_readiness(readiness)
    assert readiness["compliance_posture"] == "PERMIT_HOLD"
    assert readiness["blocking_error_id"] == ApiErrorId.ERR_PERMIT_NOT_APPROVED.value
    assert readiness["event_permit_ok"] is False
    assert readiness["inspections_ok"] is True
    assert readiness["crew_coverage_ok"] is True
    assert readiness["committed_ride_count"] == 1
    assert readiness["ride_minimum_required"] == 1

    validate_error(
        api.open_gates(stop_id, LOT_BOSS),
        ApiErrorId.ERR_PERMIT_NOT_APPROVED.value,
        expected_status=409,
    )
    assert read_route_stop(stop_id)["status"] == "SETUP"


def test_deciding_that_one_sibling_row_clears_the_posture_and_opens_the_lot(api):
    """PRD §3.4: "Approval moves the permit `SUBMITTED → APPROVED` and stamps
    `decided_at`; denial moves it `SUBMITTED → DENIED`, stamps `decided_at` and stores
    the supplied `denial_reason` on the row. Both outcomes re-derive the lot's
    `compliance_posture` — a denied `EVENT` permit is what drives a lot into
    `PERMIT_HOLD`."

    PRD §3.7: "If none of the three matches, the posture is `CLEAR` and there is no
    blocking error."

    PRD §3.7: "Opening the gates moves every one of the lot's `COMMITTED` allocations
    to `OPERATING` and re-derives the lot's `operating_ride_count`. It also reaches
    across to the route: a route sitting in `COMMITTED` advances `COMMITTED →
    IN_PROGRESS` the moment its first lot opens."

    Design: Difficulty/cross_entity_state_dependency/open_gates_blocked_by_a_sibling_event_permit_still_awaiting_decision
    """
    ctx = _lot_in_setup_awaiting_its_event_permit_decision()
    stop_id = ctx["stop"]["id"]

    validate_error(
        api.open_gates(stop_id, LOT_BOSS),
        ApiErrorId.ERR_PERMIT_NOT_APPROVED.value,
        expected_status=409,
    )

    approved = decide_permit(ctx["event_permit"]["id"], "APPROVE")
    assert approved["status"] == "APPROVED"

    cleared = read_readiness(stop_id, LOT_BOSS)
    assert cleared["compliance_posture"] == "CLEAR"
    assert cleared["blocking_error_id"] is None
    assert cleared["event_permit_ok"] is True

    opened = validate_success(api.open_gates(stop_id, LOT_BOSS))
    assert opened["status"] == "OPEN"
    assert opened["operating_ride_count"] == 1
    assert read_allocation(ctx["allocations"][0]["id"])["status"] == "OPERATING"
    assert read_route(ctx["route"]["id"])["status"] == "IN_PROGRESS"


def test_a_settlement_cannot_be_finalized_behind_a_closure_still_logged(api):
    """PRD §3.8: "**Finalizing** is the last act of the run, reserved to a
    `GeneralManager` and moving the settlement `PROVISIONAL → FINAL`. Four conditions
    apply: the settlement must be `PROVISIONAL`, else `ERR_SETTLEMENT_STATE_INVALID`;
    the lot must be `TEARDOWN`, else `ERR_STOP_STATE_INVALID`; every weather closure of
    the lot must be `ADJUDICATED`, a lingering `LOGGED` closure answering
    `ERR_CLOSURE_NOT_ADJUDICATED`; and every make-good arrangement of the deal must be
    `ACCEPTED` or `DECLINED`, a lingering `PROPOSED` one answering
    `ERR_MAKEGOOD_PENDING`."

    PRD §3.8: "Logging computes `closure_hours_raw`, the elapsed hours from
    `closed_from` to `closed_to` rounded half-up to two decimals, before any clipping or
    merging, and the row enters `LOGGED` with `abated_hours` at 0."

    PRD §3.8: "Rows in `LOGGED` contribute nothing to any of this."

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_blocked_by_a_child_weather_closure_still_logged
    """
    ctx = _struck_lot_with_an_unadjudicated_closure()
    closure = ctx["closure"]
    assert closure["status"] == "LOGGED"
    assert closure["abated_hours"] == 0.0
    assert read_route_stop(ctx["stop"]["id"])["closure_hours_adjudicated"] == 0.0

    validate_error(
        api.finalize_settlement(ctx["settlement"]["id"], GENERAL_MANAGER),
        ApiErrorId.ERR_CLOSURE_NOT_ADJUDICATED.value,
        expected_status=409,
    )

    unfinalized = read_settlement(ctx["settlement"]["id"])
    assert unfinalized["status"] == "PROVISIONAL"
    assert unfinalized["variant"] == "PROVISIONAL"
    assert unfinalized["finalized_at"] is None
    assert read_route_stop(ctx["stop"]["id"])["status"] == "TEARDOWN"


def test_adjudicating_the_cousin_row_both_unblocks_and_feeds_the_final_variant(api):
    """PRD §3.8: "That total becomes the lot's `closure_hours_adjudicated` only if it
    is at least two hours; a merged total below two hours abates nothing at all and the
    lot's figure is 0."

    PRD §3.8: "In step 7 it abates the guarantee by adjudicated closure hours instead
    of pro-rating by elapsed days: the abatement ratio is the lot's
    `closure_hours_adjudicated` divided by its `scheduled_operating_hours`, capped at 1;
    `guarantee_effective_cents` is the deal's `guarantee_cents` multiplied by one minus
    that ratio, rounded half-up to whole cents."

    PRD §3.8: "Finalization re-runs the calculation under the `FINAL` variant,
    overwrites every computed amount on the row, sets `variant` to `FINAL` and stamps
    `finalized_at` from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_blocked_by_a_child_weather_closure_still_logged
    """
    ctx = _struck_lot_with_an_unadjudicated_closure()

    validate_error(
        api.finalize_settlement(ctx["settlement"]["id"], GENERAL_MANAGER),
        ApiErrorId.ERR_CLOSURE_NOT_ADJUDICATED.value,
        expected_status=409,
    )

    adjudicated = adjudicate_closure(ctx["closure"]["id"])
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["abated_hours"] == 5.0
    assert read_weather_closure(ctx["closure"]["id"])["abated_hours"] == 5.0
    assert read_route_stop(ctx["stop"]["id"])["closure_hours_adjudicated"] == 5.0

    finalized = finalize_settlement(ctx["settlement"]["id"])
    assert finalized["status"] == "FINAL"
    assert finalized["variant"] == "FINAL"
    assert_instant_equals(finalized["finalized_at"], CLOCK_AT_CLOSE, "finalized_at")
    assert_settlement_amounts(
        finalized,
        gross_cents=100000,
        tax_cents=6500,
        taxable_net_cents=93500,
        split_share_cents=60775,
        guarantee_effective_cents=0,
        settlement_due_cents=60775,
    )
    assert read_route_stop(ctx["stop"]["id"])["status"] == "CLOSED"
