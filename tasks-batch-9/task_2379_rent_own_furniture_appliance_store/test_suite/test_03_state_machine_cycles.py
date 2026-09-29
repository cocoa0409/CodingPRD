"""States that are re-entered rather than merely advanced.

A cure followed by a chargeback drives one agreement back into the state it had
already left, and a swap drives one unit out of a customer's hands, through the
service bay and back into the rentable pool at a lower price.
"""

from __future__ import annotations

from test_helpers import (
    DAY_12,
    LoyaltyTier,
    CollectionsStage,
    ConditionGrade,
    EntryType,
    IssueCode,
    PaymentMethod,
    PaymentRowStatus,
    PaymentStatus,
    PossessionStatus,
    Resolution,
    ReversalReason,
    TermType,
    TicketStatus,
    UnitStatus,
    WindowStatus,
    assert_fields,
    assert_points_conserved,
    assert_pricing,
    build_tx_floor,
    deliver_on,
    sign_on,
)

TICKET_WINDOW_START = "2026-08-03T09:00:00Z"
TICKET_WINDOW_END = "2026-08-03T11:00:00Z"


def _cured_then_reversed_setup(world):
    """A delinquent agreement cured by a card payment that is about to be charged back."""
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.set_clock(DAY_12)
    world.day_close(scenario.store_id)
    payment = world.pay(scenario.agreement_id, 9000, PaymentMethod.CARD)
    return scenario, payment


def test_a_chargeback_returns_a_cured_agreement_to_delinquent(world):
    """The cure is undone: the status flips back and the consumed window reopens.

    PRD: The agreement moves `CURRENT` → `DELINQUENT` again, `lifetime_delinquency_count` is incremented once more, and the reinstatement window the payment consumed is reopened `USED` → `OPEN` when the logical clock is still at or before its `expires_at`.

    Design: Difficulty/non_linear_state_machine/payment_status_cycles_current_delinquent_current_delinquent_via_reversal
    """
    scenario, payment = _cured_then_reversed_setup(world)

    cured = scenario.read_agreement()
    assert_fields(cured, payment_status=PaymentStatus.CURRENT, periods_paid=1)
    assert [w["status"] for w in world.windows(scenario.agreement_id)] == [
        WindowStatus.USED
    ], "the curing payment must have consumed the open window"

    reversed_row = world.reverse(payment["id"], ReversalReason.CHARGEBACK)
    assert_fields(
        reversed_row,
        status=PaymentRowStatus.REVERSED,
        reversed_at="2026-08-12T00:00:00Z",
        reversal_reason=ReversalReason.CHARGEBACK,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        payment_status=PaymentStatus.DELINQUENT,
        periods_paid=0,
        rent_applied_cents=0,
        partial_credit_cents=0,
        late_fee_paid_cents=0,
        late_fee_balance_cents=508,
        reinstatement_fee_paid_cents=0,
        reinstatement_fee_balance_cents=500,
        current_period_due_at="2026-08-08T00:00:00Z",
    )

    windows = world.windows(scenario.agreement_id)
    assert len(windows) == 1, f"expected exactly one window, got {len(windows)}"
    assert_fields(
        windows[0], status=WindowStatus.OPEN, expires_at="2026-08-17T00:00:00Z"
    )
    assert scenario.read_customer()["lifetime_delinquency_count"] == 2, (
        "the second entry into delinquency must be counted again"
    )


def test_a_chargeback_claws_back_points_without_touching_the_lifetime_total(world):
    """The reversal is compensating: a negative entry is appended, nothing is erased.

    PRD: A compensating ledger entry with `entry_type` `PAYMENT_REVERSAL` is appended whose `delta_points` is exactly the negation of the payment's `loyalty_points_awarded`, so `loyalty_points_balance` falls while `loyalty_points_lifetime` does not.

    Design: Difficulty/non_linear_state_machine/payment_status_cycles_current_delinquent_current_delinquent_via_reversal
    """
    scenario, payment = _cured_then_reversed_setup(world)
    assert payment["loyalty_points_awarded"] == 50, (
        "5,077 cents of rent at the standard multiplier, with no on-time bonus four "
        "days late, earns 50 points"
    )

    world.reverse(payment["id"], ReversalReason.CHARGEBACK)

    entries = world.ledger(customer_id=scenario.customer_id)
    assert len(entries) == 2, f"expected an accrual and its compensation, got {len(entries)}"
    assert_fields(
        entries[0],
        entry_type=EntryType.PAYMENT_ACCRUAL,
        delta_points=50,
        source_payment_id=payment["id"],
    )
    assert_fields(
        entries[1],
        entry_type=EntryType.PAYMENT_REVERSAL,
        delta_points=-50,
        source_payment_id=payment["id"],
    )

    customer = scenario.read_customer()
    assert_fields(
        customer,
        loyalty_points_balance=0,
        loyalty_points_lifetime=50,
        loyalty_tier=LoyaltyTier.STANDARD,
    )
    assert_points_conserved(customer, entries)


def _swapped_out_to_the_spare(world):
    """Two sofas on the floor; the rented one goes to the bay and the spare takes over."""
    scenario = build_tx_floor(
        world, service_bay_capacity=2, serials=("SN-TX-0001", "SN-TX-0002")
    )
    deliver_on(sign_on(scenario, unit_index=0))
    ticket = world.open_ticket(
        scenario.agreement_id, IssueCode.MECHANICAL, TICKET_WINDOW_START, TICKET_WINDOW_END
    )
    world.issue_swap(ticket["id"], scenario.units[1]["id"])
    return scenario, ticket


def test_a_swapped_out_unit_returns_to_the_pool_one_notch_down_and_one_cycle_up(world):
    """The unit leaves the customer, sits in the bay and re-enters cheaper than it left.

    PRD: A `resolution` of `SWAPPED` is legal only on a ticket in `SWAP_ISSUED`: the ticket moves `SWAP_ISSUED` → `RESOLVED`, the agreement returns `SERVICE_SWAP_PENDING` → `DELIVERED` with its `unit_id` left pointing at the replacement it already moved to, and the swapped-out unit moves `IN_SERVICE` → `AVAILABLE` with its `rent_cycle_count` incremented and its `condition_grade` stepped down one notch, re-entering the rentable pool cheaper than it left it.

    Design: Difficulty/non_linear_state_machine/inventory_unit_cycles_through_service_and_is_repriced_on_re_rent
    """
    scenario, ticket = _swapped_out_to_the_spare(world)

    assert_fields(scenario.read_unit(0), status=UnitStatus.IN_SERVICE)
    assert_fields(
        scenario.read_unit(1),
        status=UnitStatus.ON_RENT,
        replaced_unit_id=scenario.units[0]["id"],
    )

    resolved = world.resolve_ticket(ticket["id"], Resolution.SWAPPED, rent_credit_days=2)
    assert_fields(
        resolved,
        status=TicketStatus.RESOLVED,
        resolution=Resolution.SWAPPED,
        rent_credit_days=2,
    )

    original = scenario.read_unit(0)
    assert_fields(
        original,
        status=UnitStatus.AVAILABLE,
        condition_grade=ConditionGrade.GRADE_A,
        rent_cycle_count=1,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        possession_status=PossessionStatus.DELIVERED,
        unit_id=scenario.units[1]["id"],
        swap_count=1,
        service_credit_days=2,
    )


def test_re_renting_the_serviced_unit_reprices_it_off_its_new_grade_and_cycle(world):
    """A second signing on the same unit reads the wear the service cycle recorded.

    PRD: Third, `adjusted_cash_price_cents` is the unit's `cash_price_cents` multiplied by the grade factor and then by the cycle factor, with a single round-half-up applied to the complete product; rounding after each individual factor is forbidden.

    Design: Difficulty/non_linear_state_machine/inventory_unit_cycles_through_service_and_is_repriced_on_re_rent
    """
    scenario, ticket = _swapped_out_to_the_spare(world)
    world.resolve_ticket(ticket["id"], Resolution.SWAPPED, rent_credit_days=2)

    re_rented = world.sign(
        scenario.customer_id, scenario.units[0]["id"], TermType.WEEKLY, 52
    )
    assert_pricing(
        re_rented,
        adjusted_cash_price_cents=96900,
        renewal_rate_cents=4100,
        rent_subtotal_cents=213200,
        processing_fee_cents=5000,
        total_of_payments_cents=218200,
        monthly_equivalent_rate_cents=17767,
    )
    assert_fields(
        re_rented,
        unit_id=scenario.units[0]["id"],
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.PENDING_DELIVERY,
        collections_stage=CollectionsStage.NONE,
    )
    assert scenario.read_unit(0)["status"] == UnitStatus.RESERVED
