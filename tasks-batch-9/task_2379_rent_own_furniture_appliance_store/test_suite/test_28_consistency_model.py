"""What a write hands back must be exactly what the next read finds.

One weekly payment cascades into the agreement's counters, the customer's loyalty
totals and the append-only points ledger. The posting response, the immediate
re-read and the list row must all tell the same story.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_EPOCH,
    DAY_15,
    MANAGER,
    W52_RENEWAL_RATE_CENTS,
    EntryType,
    LoyaltyTier,
    PaymentMethod,
    PaymentRowStatus,
    PaymentStatus,
    ReversalReason,
    assert_fields,
    assert_paid_pct,
    assert_points_conserved,
    assert_total_count,
    build_tx_floor,
    deliver_on,
    sign_on,
)

ON_TIME_WEEKLY_POINTS = 75


def test_the_payment_response_and_the_immediate_reread_agree_on_everything(world):
    """The posting response is the resource, so the read that follows adds nothing new.

    PRD: Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.

    Design: Corner/consistency_model/payment_response_and_immediate_reread_agree_on_every_cascaded_field
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))

    posted = world.pay(
        scenario.agreement_id, W52_RENEWAL_RATE_CENTS, PaymentMethod.CASH
    )
    assert_fields(
        posted,
        agreement_id=scenario.agreement_id,
        amount_cents=W52_RENEWAL_RATE_CENTS,
        payment_method=PaymentMethod.CASH,
        allocation_late_fee_cents=0,
        allocation_reinstatement_fee_cents=0,
        allocation_rent_cents=W52_RENEWAL_RATE_CENTS,
        allocation_partial_credit_cents=0,
        allocation_customer_credit_cents=0,
        partial_credit_before_cents=0,
        periods_advanced=1,
        days_late=0,
        cured_delinquency=False,
        loyalty_points_awarded=ON_TIME_WEEKLY_POINTS,
        status=PaymentRowStatus.POSTED,
        reversal_reason=ReversalReason.NONE,
        reversed_at=None,
        posted_at=CLOCK_EPOCH,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        periods_paid=1,
        rent_applied_cents=W52_RENEWAL_RATE_CENTS,
        partial_credit_cents=0,
        late_fee_balance_cents=0,
        current_period_due_at=DAY_15,
        payment_status=PaymentStatus.CURRENT,
    )
    assert_paid_pct(agreement, 0.0189)

    customer = scenario.read_customer()
    assert_fields(
        customer,
        loyalty_points_balance=ON_TIME_WEEKLY_POINTS,
        loyalty_points_lifetime=ON_TIME_WEEKLY_POINTS,
        loyalty_tier=LoyaltyTier.STANDARD,
        credit_balance_cents=0,
    )

    rows = assert_total_count(
        world.api.list_renewal_payments(scenario.agreement_id, MANAGER), 1
    )
    assert rows[0] == posted, (
        "the listed payment row must match the posting response field for field"
    )

    entries = assert_total_count(
        world.api.list_loyalty_ledger_entries(
            MANAGER, {"agreement_id": scenario.agreement_id}
        ),
        1,
    )
    assert_fields(
        entries[0],
        entry_type=EntryType.PAYMENT_ACCRUAL,
        customer_id=scenario.customer_id,
        agreement_id=scenario.agreement_id,
        source_payment_id=posted["id"],
        delta_points=ON_TIME_WEEKLY_POINTS,
        balance_after=ON_TIME_WEEKLY_POINTS,
    )
    assert_points_conserved(customer, entries)
