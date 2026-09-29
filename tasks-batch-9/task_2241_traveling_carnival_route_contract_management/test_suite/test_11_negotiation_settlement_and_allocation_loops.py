"""The negotiation budget, the dispute loop and the fork out of a reserved unit."""

from test_helpers import (
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GIANT_WHEEL,
    LOT_BOSS,
    NEGOTIATOR,
    TILT_A_WHIRL,
    ApiErrorId,
    approved_permit,
    assert_contract,
    assert_inspection_order,
    assert_instant_equals,
    assert_lot_ledgers,
    assert_readiness,
    assert_settlement_amounts,
    build_settlement,
    commit_allocation,
    counter_contract,
    dispute_settlement,
    list_allocation_inspections,
    read_allocation,
    read_contract,
    read_readiness,
    read_ride,
    read_route_stop,
    read_settlement,
    reconcile_settlement,
    record_sale,
    release_allocation,
    reserve_allocation,
    register_ride,
    send_contract,
    set_logical_clock,
    setup_confirmed_lot,
    setup_open_lot_with_sales,
    setup_sequenced_route_with_draft_contract,
    validate_error,
    validate_paginated,
)

OPENING_TERMS = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 4,
    "exclusivity": "RIDES",
    "settlement_basis": "GREATER_OF",
}
FIRST_COUNTER = {"revenue_split_pct_operator": 68, "guarantee_cents": 1000000}
SECOND_COUNTER = {
    "revenue_split_pct_operator": 70,
    "guarantee_cents": 1200000,
    "ride_minimum_count": 5,
}

SPLIT_ONLY_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
SOLO_OPERATOR = {
    "full_name": "Op Solo",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
    "housing_required": False,
}
THREE_CHANNEL_SALES = [
    {
        "channel": "WRISTBAND",
        "units": 300,
        "unit_price_cents": 4167,
        "business_date": "2026-09-04T18:00:00Z",
    },
    {
        "channel": "SINGLE",
        "units": 700,
        "unit_price_cents": 1043,
        "business_date": "2026-09-04T19:00:00Z",
    },
    {
        "channel": "PRESALE",
        "units": 501,
        "unit_price_cents": 2100,
        "business_date": "2026-09-04T19:30:00Z",
    },
]
DISPUTE_REASON = (
    "Presale scan counts from the west gate were omitted from the provisional draw."
)
INSPECTABLE_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=True)
PLAIN_TILT = dict(TILT_A_WHIRL, requires_state_inspection=False)
CLOCK_AT_FORK = "2026-08-20T00:00:00Z"
FIRST_SLOT_DAY = "2026-09-01T14:00:00Z"


def _deal_countered_twice():
    """A deal walked DRAFT → SENT → COUNTERED → SENT → COUNTERED."""
    ctx = setup_sequenced_route_with_draft_contract(contract_overrides=OPENING_TERMS)
    contract_id = ctx["contract"]["id"]
    send_contract(contract_id)
    counter_contract(contract_id, **FIRST_COUNTER)
    send_contract(contract_id)
    ctx["contract"] = counter_contract(contract_id, **SECOND_COUNTER)
    return ctx


def _provisional_settlement_on_a_three_channel_lot():
    """An OPEN lot with three booked channels and one PROVISIONAL settlement."""
    ctx = setup_open_lot_with_sales(
        sale_specs=THREE_CHANNEL_SALES,
        contract_overrides=SPLIT_ONLY_DEAL,
        ride_specs=[dict(GIANT_WHEEL, requires_state_inspection=False)],
        worker_specs=[SOLO_OPERATOR],
        jurisdiction_overrides={"requires_state_ride_inspection": False},
    )
    ctx["settlement"] = build_settlement(ctx["contract"]["id"])
    return ctx


def _confirmed_lot_with_two_reserved_units():
    """A CONFIRMED lot carrying two freshly RESERVED units and an approved permit."""
    ctx = setup_confirmed_lot(
        contract_overrides=SPLIT_ONLY_DEAL,
        jurisdiction_overrides={
            "requires_state_ride_inspection": True,
            "inspection_slot_capacity_per_day": 2,
        },
        venue_overrides={"housing_pads_available": 4},
    )
    ctx["event_permit"] = approved_permit(
        ctx["stop"]["id"], "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
    )
    set_logical_clock(CLOCK_AT_FORK)
    ctx["wheel"] = register_ride(INSPECTABLE_WHEEL)
    ctx["tilt"] = register_ride(PLAIN_TILT)
    ctx["wheel_allocation"] = reserve_allocation(ctx["wheel"]["id"], ctx["stop"]["id"])
    ctx["tilt_allocation"] = reserve_allocation(ctx["tilt"]["id"], ctx["stop"]["id"])
    return ctx


def test_each_counter_bumps_the_round_and_overwrites_only_the_named_terms(api):
    """PRD §3.2: "Negotiation is a genuine loop with a finite budget. Sending a deal
    moves it `DRAFT → SENT`, or `COUNTERED → SENT` when terms have been revised, and
    is available to a `ContractNegotiator` while the route is `SEQUENCED` or
    `COMMITTED` — any other route state answers `ERR_ROUTE_STATE_INVALID`. Sending
    also stamps `last_sent_by_user_id` with the caller's `X-User-ID`, which is what
    makes the later countersignature check possible. Recording the counterparty's
    response moves the deal `SENT → COUNTERED`, increments `negotiation_round` by one,
    and overwrites `revenue_split_pct_operator`, `guarantee_cents` and
    `ride_minimum_count` with whatever values the counter supplies. Each of those
    three is optional on a counter."

    PRD §3.2: "A fresh deal sits in `DRAFT` with `negotiation_round` at 0,
    `last_sent_by_user_id` null and `executed_at` null."

    Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle_dead_ends_at_the_round_budget
    """
    ctx = setup_sequenced_route_with_draft_contract(contract_overrides=OPENING_TERMS)
    contract_id = ctx["contract"]["id"]
    drafted = ctx["contract"]
    assert_contract(drafted)
    assert drafted["status"] == "DRAFT"
    assert drafted["negotiation_round"] == 0

    first_send = send_contract(contract_id)
    assert first_send["status"] == "SENT"
    assert first_send["negotiation_round"] == 0, "sending never spends a round"

    first_counter = counter_contract(contract_id, **FIRST_COUNTER)
    assert first_counter["status"] == "COUNTERED"
    assert first_counter["negotiation_round"] == 1
    assert first_counter["revenue_split_pct_operator"] == 68
    assert first_counter["guarantee_cents"] == 1000000
    assert first_counter["ride_minimum_count"] == 4, "an omitted term is left alone"

    second_send = send_contract(contract_id)
    assert second_send["status"] == "SENT"
    assert second_send["negotiation_round"] == 1

    second_counter = counter_contract(contract_id, **SECOND_COUNTER)
    assert second_counter["status"] == "COUNTERED"
    assert second_counter["negotiation_round"] == 2
    assert second_counter["revenue_split_pct_operator"] == 70
    assert second_counter["guarantee_cents"] == 1200000
    assert second_counter["ride_minimum_count"] == 5


def test_the_third_send_dead_ends_the_deal_without_voiding_it(api):
    """PRD §3.2: "The budget is two rounds, and both halves of the loop respect it: a
    deal may be sent, or re-sent, only while its `negotiation_round` is strictly less
    than 2, and a counter may likewise be recorded only while that same figure is
    strictly less than 2. A deal that has already been countered twice dead-ends at
    `COUNTERED`, and a further send attempt answers
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. This matters because the negotiation loop
    itself never voids a deal — exhausting the budget leaves the row sitting in
    `COUNTERED` indefinitely, and the only paths out of the negotiation states are
    execution or the lot going dark."

    PRD §2.7: "**Negotiation budget** — `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` on
    contract send."

    Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle_dead_ends_at_the_round_budget
    """
    ctx = _deal_countered_twice()
    contract_id = ctx["contract"]["id"]
    assert ctx["contract"]["negotiation_round"] == 2

    validate_error(
        api.send_contract(contract_id, NEGOTIATOR),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
        expected_status=409,
    )

    stuck = read_contract(contract_id)
    assert stuck["status"] == "COUNTERED"
    assert stuck["negotiation_round"] == 2
    assert stuck["executed_at"] is None
    assert stuck["revenue_split_pct_operator"] == 70
    assert stuck["guarantee_cents"] == 1200000
    assert stuck["ride_minimum_count"] == 5


def test_a_dispute_stores_the_reason_and_leaves_the_money_alone(api):
    """PRD §3.8: "Settlements can be contested. A `ContractNegotiator` disputes a
    `PROVISIONAL` settlement (`PROVISIONAL → DISPUTED`), supplying a
    `dispute_reason` that is stored on the row."

    PRD §3.8: "Creating a settlement moves any prior settlement of the same deal in
    `PROVISIONAL` or `DISPUTED` to `SUPERSEDED`, writes a new row whose `variant` and
    `status` are both `PROVISIONAL` with `dispute_reason` and `finalized_at` null, and
    increments the contract's `version` by one."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_reconcile_cycle_recomputes_amounts_and_clears_the_reason
    """
    ctx = _provisional_settlement_on_a_three_channel_lot()
    settlement = ctx["settlement"]
    assert settlement["dispute_reason"] is None
    assert settlement["finalized_at"] is None

    disputed = dispute_settlement(settlement["id"], DISPUTE_REASON)
    assert disputed["id"] == settlement["id"]
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == DISPUTE_REASON
    assert_settlement_amounts(
        disputed,
        gross_cents=3032300,
        tax_cents=197101,
        taxable_net_cents=2835199,
        split_share_cents=1913759,
        settlement_due_cents=1913759,
    )


def test_reconciling_reruns_the_arithmetic_on_the_same_row_and_clears_the_reason(api):
    """PRD §3.8: "A `TicketingAuditor` then reconciles it (`DISPUTED →
    PROVISIONAL`), re-running the provisional variant over the sales rows as they now
    stand, overwriting every computed amount on the same row and clearing
    `dispute_reason` back to null. That loop may run as often as the parties need; the
    row's identity never changes."

    PRD §3.8: "**Tax, rounded per channel then summed.** For each of the same three
    channels, multiply that channel's gross by the jurisdiction's `amusement_tax_pct`
    divided by 100 and round half-up to whole cents. The settlement's `tax_cents` is
    the sum of the three rounded channel taxes. Summing the channels first and
    rounding once is not used and gives a different answer."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_reconcile_cycle_recomputes_amounts_and_clears_the_reason
    """
    ctx = _provisional_settlement_on_a_three_channel_lot()
    settlement_id = ctx["settlement"]["id"]
    dispute_settlement(settlement_id, DISPUTE_REASON)

    record_sale(ctx["stop"]["id"], "PRESALE", 100, 500, "2026-09-05T13:00:00Z")

    reconciled = reconcile_settlement(settlement_id)
    assert reconciled["id"] == settlement_id
    assert reconciled["status"] == "PROVISIONAL"
    assert reconciled["variant"] == "PROVISIONAL"
    assert reconciled["dispute_reason"] is None
    assert reconciled["effective_operator_pct"] == 67.5
    assert_settlement_amounts(
        reconciled,
        gross_cents=3082300,
        tax_cents=200351,
        taxable_net_cents=2881949,
        split_share_cents=1945316,
        settlement_due_cents=1945316,
    )
    assert read_settlement(settlement_id)["status"] == "PROVISIONAL"

    _rows, meta = validate_paginated(
        api.list_contract_settlements(ctx["contract"]["id"], NEGOTIATOR)
    )
    assert meta["total_count"] == 1, "the loop reused the row instead of superseding it"


def test_committing_a_reserved_unit_books_its_slot_and_keeps_the_ledger(api):
    """PRD §3.3: "Committing an allocation explicitly (`RESERVED → COMMITTED`) is a
    `LotBoss` action available while the lot is `CONFIRMED` or `SETUP`; it produces
    exactly the same effects as the cascaded commit described in §3.2, setting the
    ride to `ASSIGNED`, running the slot ladder to create a `STATE` inspection order
    where the ride and jurisdiction both demand one, holding the allocation as
    `INSPECTION_HELD` where the ladder finds no free day, and re-deriving the lot's
    posture."

    PRD §3.5: "The ladder picks the **earliest** candidate day, and because calendar
    days are distinct the ranking never ties; the chosen day at 14:00:00Z becomes the
    inspection's `scheduled_date`."

    PRD §2.10: "The **footprint ledger** of a lot, `allocated_sqft_used`, is the sum
    of `footprint_charged_sqft` over the lot's allocations whose status is `RESERVED`,
    `COMMITTED`, `INSPECTION_HELD` or `OPERATING`."

    Design: Difficulty/non_linear_state_machine/ride_allocation_fork_commit_versus_release_diverges_on_ledger_and_inspection
    """
    ctx = _confirmed_lot_with_two_reserved_units()
    stop_id = ctx["stop"]["id"]
    assert ctx["wheel_allocation"]["status"] == "RESERVED"
    assert ctx["tilt_allocation"]["status"] == "RESERVED"
    assert_lot_ledgers(read_route_stop(stop_id), 7818, 513.0)

    committed = commit_allocation(ctx["wheel_allocation"]["id"])
    assert committed["status"] == "COMMITTED"
    assert committed["released_at"] is None
    assert read_ride(ctx["wheel"]["id"])["status"] == "ASSIGNED"

    orders = list_allocation_inspections(ctx["wheel_allocation"]["id"])
    assert len(orders) == 1
    order = orders[0]
    assert_inspection_order(order)
    assert order["authority"] == "STATE"
    assert order["status"] == "SCHEDULED"
    assert order["attempt_number"] == 1
    assert_instant_equals(order["scheduled_date"], FIRST_SLOT_DAY, "scheduled_date")

    assert_lot_ledgers(read_route_stop(stop_id), 7818, 513.0)


def test_releasing_a_reserved_unit_frees_the_ledger_and_books_no_slot(api):
    """PRD §3.3: "Release stamps `released_at` from the logical clock and reduces the
    lot's `allocated_sqft_used` by this allocation's `footprint_charged_sqft` and its
    `power_amps_used` by this allocation's `power_charged_amps`. The ride returns to
    `AVAILABLE` unless it is `OUT_OF_SERVICE` or still holds another allocation in
    `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. Unlike commit, release
    creates no inspection order, and it leaves any existing `SCHEDULED` inspection
    order on the allocation untouched — the posture calculation simply ignores
    inspections belonging to terminal allocations."

    PRD §2.10: "The **power ledger**, `power_amps_used`, is the sum of
    `power_charged_amps` over that same status set, rounded to one decimal place."

    PRD §3.7: "If any of the lot's allocations in `RESERVED`, `COMMITTED`,
    `INSPECTION_HELD` or `OPERATING` either is itself `INSPECTION_HELD`, or belongs to
    a ride whose `requires_state_inspection` is true at a lot whose jurisdiction sets
    `requires_state_ride_inspection` and has no inspection order of its own with
    `authority` `STATE`, `status` `PASSED` and a `scheduled_date` at or before the
    lot's `open_date`, then the posture is `INSPECTION_HOLD` and its blocking error is
    `ERR_INSPECTION_NOT_PASSED`."

    Design: Difficulty/non_linear_state_machine/ride_allocation_fork_commit_versus_release_diverges_on_ledger_and_inspection
    """
    ctx = _confirmed_lot_with_two_reserved_units()
    stop_id = ctx["stop"]["id"]
    commit_allocation(ctx["wheel_allocation"]["id"])

    released = release_allocation(ctx["tilt_allocation"]["id"])
    assert released["status"] == "RELEASED"
    assert_instant_equals(released["released_at"], CLOCK_AT_FORK, "released_at")
    assert read_ride(ctx["tilt"]["id"])["status"] == "AVAILABLE"
    assert list_allocation_inspections(ctx["tilt_allocation"]["id"]) == []

    assert_lot_ledgers(read_route_stop(stop_id), 5414, 375.0)
    assert read_allocation(ctx["wheel_allocation"]["id"])["status"] == "COMMITTED"

    readiness = read_readiness(stop_id, LOT_BOSS)
    assert_readiness(readiness)
    assert readiness["compliance_posture"] == "INSPECTION_HOLD"
    assert readiness["blocking_error_id"] == ApiErrorId.ERR_INSPECTION_NOT_PASSED.value
