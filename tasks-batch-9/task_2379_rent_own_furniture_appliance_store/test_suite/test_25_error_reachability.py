"""Every refusal on the dispatch desk, reached in one sitting on one appliance.

A zero-length window, a crew from the wrong shop, a crew that is off the road, a
crew nobody certified for installation, and finally a hand-over that claims no
installation happened — then the one call that works.
"""

from __future__ import annotations

from test_helpers import (
    AUSTIN_MAIN,
    CLOCK_EPOCH,
    MANAGER,
    MN_CREW_A,
    ST_PAUL_MAIN,
    TX_CREW_A,
    TX_CREW_B,
    TX_CREW_C,
    CrewStatus,
    DeliveryOrderStatus,
    ErrorId,
    PossessionStatus,
    ServiceType,
    TermType,
    UnitStatus,
    assert_fields,
    created,
    factories,
    failure,
)

WINDOW_START = "2026-08-01T09:00:00Z"
WINDOW_END = "2026-08-01T11:00:00Z"


def test_every_dispatch_refusal_is_reachable_before_the_hand_over_succeeds(world):
    """Five rejections that write nothing, then a completion that moves everything.

    PRD: The crew must belong to the same store as the agreement (`ERR_CREW_STORE_MISMATCH`) and must be `ACTIVE` (`ERR_CREW_INACTIVE`).

    Design: Corner/errors/delivery_dispatch_error_cluster_is_reachable_end_to_end
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    world.seed_mn_rule()

    tx_store = world.open_store(AUSTIN_MAIN, "TX", 1)
    mn_store = world.open_store(ST_PAUL_MAIN, "MN", 1)
    certified = world.add_crew(tx_store["id"], TX_CREW_A, setup_certified=True)
    uncertified = world.add_crew(tx_store["id"], TX_CREW_B, setup_certified=False)
    off_the_road = world.add_crew(
        tx_store["id"], TX_CREW_C, setup_certified=True, status=CrewStatus.INACTIVE
    )
    wrong_shop = world.add_crew(mn_store["id"], MN_CREW_A, setup_certified=True)

    appliance = world.add_washer(tx_store["id"], "SN-TX-0002")
    customer = world.onboard_dana()
    agreement = world.sign(
        customer["id"], appliance["id"], TermType.MONTHLY, 2
    )
    version_at_signing = agreement["version"]

    def dispatch(crew_id, window_end_at=WINDOW_END):
        """Every attempt quotes the version captured at signing, never a fresh read."""
        return world.api.create_delivery_order(
            agreement["id"],
            factories.delivery_order_payload(
                crew_id,
                version_at_signing,
                WINDOW_START,
                window_end_at,
                ServiceType.DELIVERY_SETUP,
            ),
            MANAGER,
        )

    failure(
        dispatch(certified["id"], window_end_at=WINDOW_START), ErrorId.INVALID_WINDOW
    )
    failure(dispatch(wrong_shop["id"]), ErrorId.CREW_STORE_MISMATCH)
    failure(dispatch(off_the_road["id"]), ErrorId.CREW_INACTIVE)
    failure(dispatch(uncertified["id"]), ErrorId.CREW_NOT_SETUP_CERTIFIED)

    order = created(dispatch(certified["id"]))
    assert_fields(
        order,
        crew_id=certified["id"],
        service_type=ServiceType.DELIVERY_SETUP,
        status=DeliveryOrderStatus.SCHEDULED,
        attempt_count=0,
        setup_completed=False,
    )
    assert world.agreement_version(agreement["id"]) == version_at_signing + 1, (
        "none of the four rejected dispatches may have consumed an agreement version"
    )

    failure(
        world.api.complete_delivery_order(
            order["id"], factories.complete_delivery_payload(False), MANAGER
        ),
        ErrorId.SETUP_NOT_COMPLETED,
    )
    assert (
        world.get_delivery_order(order["id"])["status"] == DeliveryOrderStatus.SCHEDULED
    )

    completed = world.complete_delivery(order["id"], setup_completed=True)
    assert_fields(
        completed,
        status=DeliveryOrderStatus.COMPLETED,
        setup_completed=True,
        completed_at=CLOCK_EPOCH,
    )
    assert (
        world.get_agreement(agreement["id"])["possession_status"]
        == PossessionStatus.DELIVERED
    )
    assert world.get_unit(appliance["id"])["status"] == UnitStatus.ON_RENT
    assert world.get_store(tx_store["id"])["units_on_rent_count"] == 1
