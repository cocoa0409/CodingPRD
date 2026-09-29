"""The fail-attempt endpoint is a counter rather than a switch.

Two failures leave the crew free to try again on the same order; the third gives
the goods back to the floor and shuts the order for good.
"""

from __future__ import annotations

from test_helpers import (
    MANAGER,
    DeliveryOrderStatus,
    ErrorId,
    FailureReason,
    PaymentStatus,
    PossessionStatus,
    UnitStatus,
    assert_fields,
    build_tx_floor,
    factories,
    failure,
    sign_on,
)


def test_the_third_failed_attempt_releases_the_goods_and_shuts_the_order(world):
    """Attempts one and two change nothing but the counter; the third releases the unit.

    PRD: The first two failures leave the order `SCHEDULED` so the same crew can try again; the third takes `attempt_count` to 3 and the order `SCHEDULED` → `FAILED_ATTEMPT`, which releases both the crew's window and the goods: the unit returns `RESERVED` → `AVAILABLE` so another agreement may reserve it, while this agreement stays in `PENDING_DELIVERY` with its pricing snapshot fully intact, waiting for a fresh order that will supersede the failed one.

    Design: Corner/endpoints/three_failed_delivery_attempts_release_the_reservation
    """
    scenario = sign_on(build_tx_floor(world))
    order = world.schedule_delivery(scenario.agreement_id, scenario.crew_id)
    assert_fields(
        order, status=DeliveryOrderStatus.SCHEDULED, attempt_count=0
    )

    first = world.fail_attempt(order["id"], FailureReason.CUSTOMER_ABSENT)
    assert_fields(
        first, status=DeliveryOrderStatus.SCHEDULED, attempt_count=1
    )

    second = world.fail_attempt(order["id"], FailureReason.ACCESS_BLOCKED)
    assert_fields(
        second, status=DeliveryOrderStatus.SCHEDULED, attempt_count=2
    )
    assert scenario.read_unit()["status"] == UnitStatus.RESERVED, (
        "the goods stay reserved while the same crew may still try again"
    )

    third = world.fail_attempt(order["id"], FailureReason.VEHICLE_ISSUE)
    assert_fields(
        third,
        status=DeliveryOrderStatus.FAILED_ATTEMPT,
        attempt_count=3,
        completed_at=None,
    )
    assert scenario.read_unit()["status"] == UnitStatus.AVAILABLE, (
        "the third failure must hand the goods back to the floor"
    )

    assert_fields(
        scenario.read_agreement(),
        possession_status=PossessionStatus.PENDING_DELIVERY,
        payment_status=PaymentStatus.CURRENT,
        cycle_anchor_at=None,
        periods_paid=0,
    )
    assert scenario.read_store()["units_on_rent_count"] == 0

    # The third failure released the goods, so the unit-status check (§2.9 check 14,
    # which requires RESERVED to deliver) fails strictly before the delivery-order
    # state check (check 15), and the first failing check owns the response.
    failure(
        world.api.complete_delivery_order(
            order["id"], factories.complete_delivery_payload(True), MANAGER
        ),
        ErrorId.UNIT_NOT_AVAILABLE,
    )
    assert_fields(
        world.get_delivery_order(order["id"]),
        status=DeliveryOrderStatus.FAILED_ATTEMPT,
        completed_at=None,
        setup_completed=False,
    )
