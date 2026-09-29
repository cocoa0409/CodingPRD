"""Compensating actions that must leave the books exactly as they found them.

A reversal has to give back the carried credit that bucket three swallowed, not the
bucket it produced, or money vanishes. A swap has to move possession from one unit to
another without changing how many units sit in customers' homes.
"""

from __future__ import annotations

from test_helpers import (
    DAY_05,
    W52_RENEWAL_RATE_CENTS,
    W52_TOTAL_OF_PAYMENTS_CENTS,
    ConditionGrade,
    EntryType,
    IssueCode,
    LoyaltyTier,
    PaymentMethod,
    PaymentRowStatus,
    PaymentStatus,
    PossessionStatus,
    Resolution,
    ReversalReason,
    TicketStatus,
    UnitStatus,
    assert_cash_conserved,
    assert_fields,
    assert_intake_gate,
    assert_paid_pct,
    assert_points_conserved,
    assert_possession_conserved,
    build_tx_floor,
    deliver_on,
    sign_on,
)

PARTIAL_TENDER_CENTS = 4000
SECOND_TENDER_CENTS = 7000
TWO_PERIODS_OF_RENT_CENTS = 2 * W52_RENEWAL_RATE_CENTS  # 10,154
LEFTOVER_AFTER_TWO_PERIODS_CENTS = 846
POINTS_FOR_TWO_ON_TIME_PERIODS = 126

TICKET_START = "2026-08-03T09:00:00Z"
TICKET_END = "2026-08-03T11:00:00Z"
CREDITED_DAYS = 3


def _a_carried_credit_then_a_payment_that_spends_it(world):
    """Four thousand cents that buy nothing, then seven thousand that buy two periods."""
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    first = world.pay(scenario.agreement_id, PARTIAL_TENDER_CENTS, PaymentMethod.CASH)

    world.set_clock(DAY_05)
    second = world.pay(scenario.agreement_id, SECOND_TENDER_CENTS, PaymentMethod.ACH)
    return scenario, first, second


def test_the_rent_pool_is_the_new_money_plus_the_credit_already_carried(world):
    """Seven thousand alone buys one period; with the carried four thousand it buys two.

    PRD: Before it runs, the agreement's carried `partial_credit_cents` is copied onto the payment as `partial_credit_before_cents`, then the rent pool is formed as the money still remaining plus that carried credit.

    Design: Difficulty/compensating_invariant/cash_conserved_when_a_payment_that_consumed_carried_credit_is_reversed
    """
    scenario, first, second = _a_carried_credit_then_a_payment_that_spends_it(world)

    assert_fields(
        first,
        status=PaymentRowStatus.POSTED,
        partial_credit_before_cents=0,
        allocation_rent_cents=0,
        allocation_partial_credit_cents=PARTIAL_TENDER_CENTS,
        periods_advanced=0,
        loyalty_points_awarded=0,
    )
    assert_fields(
        second,
        status=PaymentRowStatus.POSTED,
        partial_credit_before_cents=PARTIAL_TENDER_CENTS,
        allocation_late_fee_cents=0,
        allocation_reinstatement_fee_cents=0,
        allocation_rent_cents=TWO_PERIODS_OF_RENT_CENTS,
        allocation_partial_credit_cents=LEFTOVER_AFTER_TWO_PERIODS_CENTS,
        allocation_customer_credit_cents=0,
        periods_advanced=2,
        days_late=0,
        loyalty_points_awarded=POINTS_FOR_TWO_ON_TIME_PERIODS,
    )
    assert (
        second["allocation_rent_cents"] + second["allocation_partial_credit_cents"]
        == SECOND_TENDER_CENTS + PARTIAL_TENDER_CENTS
    ), "the pool is the new tender plus the credit it inherited, spent to the cent"

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        periods_paid=2,
        rent_applied_cents=TWO_PERIODS_OF_RENT_CENTS,
        partial_credit_cents=LEFTOVER_AFTER_TWO_PERIODS_CENTS,
        current_period_due_at="2026-08-22T00:00:00Z",
    )
    assert_cash_conserved(agreement, world.payments(scenario.agreement_id))


def test_reversing_it_restores_the_carried_credit_rather_than_the_bucket(world):
    """Unwinding gives back the four thousand it consumed, not the 846 it produced.

    PRD: The carried credit is handled with particular care: `partial_credit_cents` is restored to the payment's `partial_credit_before_cents` and **not** reduced by `allocation_partial_credit_cents`, because bucket three consumed the carried credit on the way in and subtracting the bucket instead would destroy that money out of the ledger.

    Design: Difficulty/compensating_invariant/cash_conserved_when_a_payment_that_consumed_carried_credit_is_reversed
    """
    scenario, first, second = _a_carried_credit_then_a_payment_that_spends_it(world)

    reversed_row = world.reverse(second["id"], ReversalReason.NSF)
    assert_fields(
        reversed_row,
        status=PaymentRowStatus.REVERSED,
        reversal_reason=ReversalReason.NSF,
        reversed_at=DAY_05,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        periods_paid=0,
        rent_applied_cents=0,
        late_fee_paid_cents=0,
        reinstatement_fee_paid_cents=0,
        partial_credit_cents=PARTIAL_TENDER_CENTS,
        customer_credit_contributed_cents=0,
        current_period_due_at="2026-08-08T00:00:00Z",
        payment_status=PaymentStatus.CURRENT,
    )
    assert_paid_pct(agreement, 0.0000)

    payments = world.payments(scenario.agreement_id)
    assert_cash_conserved(agreement, payments)
    surviving = [p for p in payments if p["status"] == PaymentRowStatus.POSTED]
    assert [p["id"] for p in surviving] == [first["id"]], (
        "only the older payment may survive the reversal as POSTED"
    )


def test_the_compensating_ledger_entry_negates_the_accrual_exactly(world):
    """Points fall back to zero while the lifetime total keeps the history.

    PRD: A compensating ledger entry with `entry_type` `PAYMENT_REVERSAL` is appended whose `delta_points` is exactly the negation of the payment's `loyalty_points_awarded`, so `loyalty_points_balance` falls while `loyalty_points_lifetime` does not.

    Design: Difficulty/compensating_invariant/cash_conserved_when_a_payment_that_consumed_carried_credit_is_reversed
    """
    scenario, _first, second = _a_carried_credit_then_a_payment_that_spends_it(world)
    world.reverse(second["id"], ReversalReason.NSF)

    entries = world.ledger(customer_id=scenario.customer_id)
    assert [e["entry_type"] for e in entries] == [
        EntryType.PAYMENT_ACCRUAL,
        EntryType.PAYMENT_REVERSAL,
    ], "the append-only ledger keeps the accrual and its compensation, in that order"
    assert [e["delta_points"] for e in entries] == [
        POINTS_FOR_TWO_ON_TIME_PERIODS,
        -POINTS_FOR_TWO_ON_TIME_PERIODS,
    ]
    assert entries[1]["source_payment_id"] == second["id"]
    assert entries[1]["balance_after"] == 0

    customer = scenario.read_customer()
    assert_fields(
        customer,
        loyalty_points_balance=0,
        loyalty_points_lifetime=POINTS_FOR_TWO_ON_TIME_PERIODS,
        loyalty_tier=LoyaltyTier.STANDARD,
    )
    assert_points_conserved(customer, entries)


def _the_loaner_is_out_and_the_original_is_in_the_bay(world):
    """One rented sofa in the single bay, its twin standing in for it at the house."""
    scenario = deliver_on(
        sign_on(
            build_tx_floor(
                world, service_bay_capacity=1, serials=("SN-TX-0001", "SN-TX-0002")
            )
        )
    )
    ticket = world.open_ticket(
        scenario.agreement_id, IssueCode.MECHANICAL, TICKET_START, TICKET_END
    )
    return scenario, ticket


def _conservation_holds(scenario):
    """Read the store, its units and its agreements and check the possession identity."""
    store = scenario.read_store()
    assert_possession_conserved(
        store,
        scenario.world.units(store_id=scenario.store_id),
        scenario.world.agreements(store_id=scenario.store_id),
    )
    assert_intake_gate(store)
    return store


def test_a_swap_moves_possession_between_units_without_changing_the_headcount(world):
    """One unit leaves the house and another arrives, so the rented count never moves.

    PRD: For any store, the number of its inventory units in status `ON_RENT` equals the number of its agreements whose `possession_status` is `DELIVERED` or `SERVICE_SWAP_PENDING`; the store's `units_on_rent_count` equals that same number; and the store's `units_in_service_count` equals the number of its units in status `IN_SERVICE`.

    Design: Difficulty/compensating_invariant/units_in_customers_hands_conserved_across_swap_and_resolution
    """
    scenario, ticket = _the_loaner_is_out_and_the_original_is_in_the_bay(world)

    before = _conservation_holds(scenario)
    assert_fields(
        before,
        units_on_rent_count=1,
        units_in_service_count=0,
        service_intake_open=True,
    )

    world.issue_swap(ticket["id"], scenario.units[1]["id"])

    after = _conservation_holds(scenario)
    assert_fields(
        after,
        units_on_rent_count=1,
        units_in_service_count=1,
        service_intake_open=False,
    )
    assert scenario.read_unit(0)["status"] == UnitStatus.IN_SERVICE
    assert_fields(
        scenario.read_unit(1),
        status=UnitStatus.ON_RENT,
        replaced_unit_id=scenario.units[0]["id"],
    )
    assert_fields(
        scenario.read_agreement(),
        possession_status=PossessionStatus.SERVICE_SWAP_PENDING,
        unit_id=scenario.units[1]["id"],
        swap_count=1,
    )


def test_resolving_the_swap_frees_the_bay_and_still_balances(world):
    """The serviced unit rejoins the pool one notch down and the identity holds again.

    PRD: A `resolution` of `SWAPPED` is legal only on a ticket in `SWAP_ISSUED`: the ticket moves `SWAP_ISSUED` → `RESOLVED`, the agreement returns `SERVICE_SWAP_PENDING` → `DELIVERED` with its `unit_id` left pointing at the replacement it already moved to, and the swapped-out unit moves `IN_SERVICE` → `AVAILABLE` with its `rent_cycle_count` incremented and its `condition_grade` stepped down one notch, re-entering the rentable pool cheaper than it left it.

    Design: Difficulty/compensating_invariant/units_in_customers_hands_conserved_across_swap_and_resolution
    """
    scenario, ticket = _the_loaner_is_out_and_the_original_is_in_the_bay(world)
    world.issue_swap(ticket["id"], scenario.units[1]["id"])

    resolved = world.resolve_ticket(
        ticket["id"], Resolution.SWAPPED, rent_credit_days=CREDITED_DAYS
    )
    assert_fields(
        resolved,
        status=TicketStatus.RESOLVED,
        resolution=Resolution.SWAPPED,
        rent_credit_days=CREDITED_DAYS,
        replacement_unit_id=scenario.units[1]["id"],
    )

    store = _conservation_holds(scenario)
    assert_fields(
        store,
        units_on_rent_count=1,
        units_in_service_count=0,
        service_intake_open=True,
    )

    assert_fields(
        scenario.read_unit(0),
        status=UnitStatus.AVAILABLE,
        condition_grade=ConditionGrade.GRADE_A,
        rent_cycle_count=1,
    )
    assert_fields(
        scenario.read_unit(1),
        status=UnitStatus.ON_RENT,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
        replaced_unit_id=scenario.units[0]["id"],
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        possession_status=PossessionStatus.DELIVERED,
        unit_id=scenario.units[1]["id"],
        swap_count=1,
        service_credit_days=CREDITED_DAYS,
        rent_applied_cents=0,
        total_of_payments_cents=W52_TOTAL_OF_PAYMENTS_CENTS,
    )
    assert_paid_pct(agreement, 0.0000)
