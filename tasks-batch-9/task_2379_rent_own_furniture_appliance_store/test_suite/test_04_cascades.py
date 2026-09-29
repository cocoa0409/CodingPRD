"""Single calls whose consequences travel several rows away.

One curing payment reaches from the reinstatement window through the agreement and
the ledger to the customer's tier. One swap issuance reaches from the unit through
the store's bay counters to the intake gate that refuses the next ticket.
"""

from __future__ import annotations

from test_helpers import (
    DAY_12,
    SEPT_12,
    CollectionsStage,
    ConditionGrade,
    EntryType,
    ErrorId,
    IssueCode,
    LoyaltyTier,
    PaymentMethod,
    PaymentStatus,
    PossessionStatus,
    TicketStatus,
    UnitStatus,
    WindowStatus,
    assert_fields,
    assert_intake_gate,
    assert_paid_pct,
    assert_points_conserved,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    sign_on,
)
from test_helpers.test_users import COLLECTOR, TECHNICIAN

FIRST_TICKET_START = "2026-08-03T09:00:00Z"
FIRST_TICKET_END = "2026-08-03T11:00:00Z"
SECOND_TICKET_START = "2026-08-05T09:00:00Z"
SECOND_TICKET_END = "2026-08-05T11:00:00Z"


def _delinquent_awaiting_a_large_payment(world):
    """The canonical agreement four days past its first due date, after a day-close."""
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.set_clock(DAY_12)
    world.day_close(scenario.store_id)
    return scenario


def test_the_curing_payment_consumes_the_window_and_clears_every_arrear(world):
    """Clearing the arrears in one tender closes the collections campaign.

    PRD: When a payment clears every arrear and the recomputed due date is in the future, the payment's `cured_delinquency` is set to true and `payment_status` moves `DELINQUENT` → `CURRENT`; the `OPEN` window on the agreement moves `OPEN` → `USED`, which closes the collections campaign by moving `collections_stage` `ADVERSE` → `NONE`; the customer's `adverse_agreement_count` falls by one; and when it reaches 0 the customer's `account_flag` moves `ADVERSE` → `NORMAL`.

    Design: Difficulty/transitive_cascade/curing_payment_cascades_five_hops_from_window_to_loyalty_tier
    """
    scenario = _delinquent_awaiting_a_large_payment(world)

    payment = world.pay(
        scenario.agreement_id, 30000, PaymentMethod.MONEY_ORDER, headers=COLLECTOR
    )
    assert_fields(
        payment,
        allocation_late_fee_cents=508,
        allocation_reinstatement_fee_cents=500,
        allocation_rent_cents=25385,
        allocation_partial_credit_cents=3607,
        allocation_customer_credit_cents=0,
        periods_advanced=5,
        days_late=4,
        cured_delinquency=True,
    )

    windows = world.windows(scenario.agreement_id)
    assert len(windows) == 1, f"expected exactly one window, got {len(windows)}"
    assert_fields(windows[0], status=WindowStatus.USED, window_days=5)

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        payment_status=PaymentStatus.CURRENT,
        collections_stage=CollectionsStage.NONE,
        periods_paid=5,
        rent_applied_cents=25385,
        partial_credit_cents=3607,
        late_fee_balance_cents=0,
        reinstatement_fee_balance_cents=0,
        current_period_due_at=SEPT_12,
    )
    assert_paid_pct(agreement, 0.0944)


def test_the_curing_payment_mints_points_that_ratchet_the_customers_tier(world):
    """The last hop lands on the customer: a fresh ledger entry and a new tier.

    PRD: If the resulting `loyalty_points_awarded` is not zero, a ledger entry is appended with `entry_type` `PAYMENT_ACCRUAL`, a positive `delta_points`, the originating `customer_id`, `agreement_id` and `source_payment_id`, an `occurred_at` at the logical clock, and a `balance_after` equal to the customer's balance immediately after the append; the customer's `loyalty_points_balance` and `loyalty_points_lifetime` both rise by that amount and `loyalty_tier` is then recomputed from the new lifetime total — `GOLD` at 500 lifetime points or more, `SILVER` at 200 or more, `STANDARD` below that.

    Design: Difficulty/transitive_cascade/curing_payment_cascades_five_hops_from_window_to_loyalty_tier
    """
    scenario = _delinquent_awaiting_a_large_payment(world)

    payment = world.pay(
        scenario.agreement_id, 30000, PaymentMethod.MONEY_ORDER, headers=COLLECTOR
    )
    assert payment["loyalty_points_awarded"] == 253, (
        "25,385 cents of rent floors to 253 points at the standard multiplier, and "
        "four days late there is no on-time bonus"
    )
    assert payment["loyalty_points_awarded"] < 5 * (50 + 25), (
        "one lump sum must earn strictly less than five separate on-time payments"
    )

    entries = world.ledger(customer_id=scenario.customer_id)
    assert len(entries) == 1, f"expected exactly one ledger entry, got {len(entries)}"
    assert_fields(
        entries[0],
        entry_type=EntryType.PAYMENT_ACCRUAL,
        customer_id=scenario.customer_id,
        agreement_id=scenario.agreement_id,
        source_payment_id=payment["id"],
        delta_points=253,
        balance_after=253,
        occurred_at=DAY_12,
    )

    customer = scenario.read_customer()
    assert_fields(
        customer,
        loyalty_points_balance=253,
        loyalty_points_lifetime=253,
        loyalty_tier=LoyaltyTier.SILVER,
        lifetime_delinquency_count=1,
        adverse_agreement_count=0,
    )
    assert_points_conserved(customer, entries)


def _one_bay_occupied_by_a_swap(world):
    """A store with a single service bay, whose only bay is taken by a swap."""
    scenario = build_tx_floor(
        world, service_bay_capacity=1, serials=("SN-TX-0001", "SN-TX-0002")
    )
    deliver_on(sign_on(scenario, unit_index=0))
    ticket = world.open_ticket(
        scenario.agreement_id, IssueCode.MECHANICAL, FIRST_TICKET_START, FIRST_TICKET_END
    )
    swap = world.issue_swap(ticket["id"], scenario.units[1]["id"])
    return scenario, ticket, swap


def test_issuing_a_swap_fills_the_bay_and_leaves_the_rented_count_alone(world):
    """The replacement takes the vacated slot, so only the service counter moves.

    PRD: The original unit moves `ON_RENT` → `IN_SERVICE`, which raises the store's `units_in_service_count` by one while `units_on_rent_count` stays exactly where it was, because the replacement took the vacated slot; when `units_in_service_count` reaches or passes `service_bay_capacity`, `service_intake_open` flips from true to false and the store stops accepting new tickets.

    Design: Difficulty/transitive_cascade/swap_cascade_closes_store_intake_so_next_ticket_is_rejected
    """
    scenario, _ticket, swap = _one_bay_occupied_by_a_swap(world)

    assert_fields(
        swap,
        status=TicketStatus.SWAP_ISSUED,
        replacement_unit_id=scenario.units[1]["id"],
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        possession_status=PossessionStatus.SERVICE_SWAP_PENDING,
        unit_id=scenario.units[1]["id"],
        swap_count=1,
    )

    assert_fields(
        scenario.read_unit(0),
        status=UnitStatus.IN_SERVICE,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
    )
    assert_fields(
        scenario.read_unit(1),
        status=UnitStatus.ON_RENT,
        replaced_unit_id=scenario.units[0]["id"],
    )

    store = scenario.read_store()
    assert_fields(
        store,
        units_in_service_count=1,
        units_on_rent_count=1,
        service_intake_open=False,
    )
    assert_intake_gate(store)


def test_the_closed_intake_gate_refuses_the_next_ticket_outright(world):
    """With the bay full the store stops accepting tickets, and writes nothing.

    PRD: The store's derived `service_intake_open` must be true, which fails with `ERR_SERVICE_INTAKE_CLOSED` once `units_in_service_count` has reached `service_bay_capacity`.

    Design: Difficulty/transitive_cascade/swap_cascade_closes_store_intake_so_next_ticket_is_rejected
    """
    scenario, _ticket, _swap = _one_bay_occupied_by_a_swap(world)
    assert scenario.read_store()["service_intake_open"] is False

    response = scenario.api.create_service_ticket(
        scenario.agreement_id,
        factories.service_ticket_payload(
            IssueCode.COSMETIC, SECOND_TICKET_START, SECOND_TICKET_END
        ),
        TECHNICIAN,
    )
    failure(response, ErrorId.SERVICE_INTAKE_CLOSED)

    tickets = world.tickets(agreement_id=scenario.agreement_id)
    assert len(tickets) == 1, (
        f"the rejected ticket must not have been written, got {len(tickets)} tickets"
    )
    assert_fields(
        scenario.read_unit(0),
        status=UnitStatus.IN_SERVICE,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
    )
