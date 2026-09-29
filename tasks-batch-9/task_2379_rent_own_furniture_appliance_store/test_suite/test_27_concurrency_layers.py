"""The two writes that make the caller quote a version, and what a stale quote costs.

A payment that lands between reading an agreement and asking for a payoff figure
invalidates the payoff request outright. A reschedule that quotes yesterday's
version is refused before it can supersede anything.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_EPOCH,
    DAY_08,
    MANAGER,
    W52_RENEWAL_RATE_CENTS,
    DeliveryOrderStatus,
    ErrorId,
    LoyaltyTier,
    PayoffFormula,
    QuoteStatus,
    UnitStatus,
    assert_fields,
    assert_ordered_by,
    assert_total_count,
    build_tx_floor,
    created,
    deliver_on,
    factories,
    failure,
    sign_on,
)

PRE_DISCOUNT_PAYOFF_CENTS = 145160

RESCHEDULE_START = "2026-08-03T09:00:00Z"
RESCHEDULE_END = "2026-08-03T11:00:00Z"


def test_a_payoff_quote_that_quotes_a_pre_payment_version_is_refused(world):
    """The payment moves the agreement on, so the quote request built before it is dead.

    PRD: If `expected_agreement_version` does not equal the agreement's current `version`, the write is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and nothing is created.

    Design: Corner/cross_cutting_complexity_layers/quote_issue_with_a_stale_agreement_version_is_rejected
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    version_before_the_payment = scenario.read_agreement()["version"]

    world.pay(scenario.agreement_id, W52_RENEWAL_RATE_CENTS)
    version_now = scenario.read_agreement()["version"]
    assert version_now != version_before_the_payment, (
        "posting a payment must move the agreement's version on"
    )

    failure(
        world.api.issue_early_purchase_quote(
            scenario.agreement_id,
            factories.quote_payload(version_before_the_payment),
            MANAGER,
        ),
        ErrorId.STALE_AGREEMENT_VERSION,
    )
    assert_total_count(
        world.api.list_early_purchase_quotes(scenario.agreement_id, MANAGER), 0
    )
    assert scenario.read_agreement()["version"] == version_now, (
        "a refused quote request must not consume a version of its own"
    )

    quote = created(
        world.api.issue_early_purchase_quote(
            scenario.agreement_id, factories.quote_payload(version_now), MANAGER
        )
    )
    assert_fields(
        quote,
        agreement_id=scenario.agreement_id,
        formula_applied=PayoffFormula.PCT_OF_REMAINING,
        rent_applied_snapshot_cents=W52_RENEWAL_RATE_CENTS,
        pre_discount_cents=PRE_DISCOUNT_PAYOFF_CENTS,
        loyalty_tier_snapshot=LoyaltyTier.STANDARD,
        loyalty_discount_cents=0,
        late_fee_component_cents=0,
        payoff_amount_cents=PRE_DISCOUNT_PAYOFF_CENTS,
        status=QuoteStatus.OPEN,
        issued_at=CLOCK_EPOCH,
        expires_at=DAY_08,
    )
    assert_total_count(
        world.api.list_early_purchase_quotes(scenario.agreement_id, MANAGER), 1
    )
    assert scenario.read_agreement()["version"] == version_now + 1


def test_a_reschedule_that_quotes_the_signing_version_supersedes_nothing(world):
    """The stale reschedule is refused before the prior order can be touched.

    PRD: Before the new window is examined at all, the agreement's own prior order in `SCHEDULED` or `FAILED_ATTEMPT` status is taken to `SUPERSEDED` and its crew window is released, so at most one non-terminal delivery order ever exists per agreement and a failed attempt is superseded rather than resurrected.

    Design: Corner/cross_cutting_complexity_layers/delivery_order_reschedule_with_a_stale_agreement_version_is_rejected
    """
    scenario = sign_on(build_tx_floor(world))
    version_at_signing = scenario.agreement_v1

    first = world.schedule_delivery(
        scenario.agreement_id,
        scenario.crew_id,
        RESCHEDULE_START,
        RESCHEDULE_END,
        expected_agreement_version=version_at_signing,
    )
    assert_fields(
        first, status=DeliveryOrderStatus.SCHEDULED, attempt_count=0
    )
    version_after_the_first_order = scenario.read_agreement()["version"]
    assert version_after_the_first_order == version_at_signing + 1

    stale_body = factories.delivery_order_payload(
        scenario.crew_id, version_at_signing, RESCHEDULE_START, RESCHEDULE_END
    )
    failure(
        world.api.create_delivery_order(scenario.agreement_id, stale_body, MANAGER),
        ErrorId.STALE_AGREEMENT_VERSION,
    )
    assert_fields(
        world.get_delivery_order(first["id"]),
        status=DeliveryOrderStatus.SCHEDULED,
        attempt_count=0,
    )
    assert_total_count(
        world.api.list_delivery_orders(
            MANAGER, {"agreement_id": scenario.agreement_id}
        ),
        1,
    )

    # The identical window is free again the moment the first order is superseded,
    # so the retry is not a crew conflict with the order it replaces.
    second = world.schedule_delivery(
        scenario.agreement_id,
        scenario.crew_id,
        RESCHEDULE_START,
        RESCHEDULE_END,
        expected_agreement_version=version_after_the_first_order,
    )
    assert_fields(
        second, status=DeliveryOrderStatus.SCHEDULED, attempt_count=0
    )
    assert_fields(
        world.get_delivery_order(first["id"]),
        status=DeliveryOrderStatus.SUPERSEDED,
        completed_at=None,
    )

    rows = assert_total_count(
        world.api.list_delivery_orders(
            MANAGER, {"agreement_id": scenario.agreement_id}
        ),
        2,
    )
    assert_ordered_by(rows, "created_at")
    assert [row["status"] for row in rows] == [
        DeliveryOrderStatus.SUPERSEDED,
        DeliveryOrderStatus.SCHEDULED,
    ]
    assert scenario.read_unit()["status"] == UnitStatus.RESERVED, (
        "the goods stay reserved across the reschedule"
    )
