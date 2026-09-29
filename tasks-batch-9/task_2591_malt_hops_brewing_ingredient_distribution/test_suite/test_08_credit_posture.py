"""Credit posture at the limit, and the dock gate that reads the credit dimension."""
import pytest

from test_helpers import (
    WH_HEADERS,
    add_malt_line,
    add_spot_hop_line,
    approve_credit,
    confirm_order,
    create_brewer,
    create_malt_product,
    create_order,
    create_released_lot,
    create_variety,
    create_zone,
    get_brewer,
    get_zone,
    hold_credit,
    pick_order,
    pin_clock,
    set_credit_limit,
    stage_shipment,
    validate_error,
    validate_success,
)


@pytest.fixture
def exact_exposure_brewer():
    """A brewer whose only exposure is one CONFIRMED order of exactly 171,000 cents."""
    pin_clock()
    brewer = create_brewer(name="Exactly Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=20000,
                              lot_code="LOT-2606")
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-EXACT")
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    order = confirm_order(order["id"], brewer["id"])
    return {"brewer": brewer, "product": product, "lot": lot, "order": order}


def test_exposure_exactly_equal_to_the_limit_lands_in_watch_not_hold(
        api, exact_exposure_brewer):
    """171,000 against a 171,000 limit is 100.00 percent utilisation and only WATCH.

    PRD §3.1: "Exposure exactly equal to the limit is *not* a hold — a brewery
    sitting at exactly 100.00% utilisation lands in `WATCH` — and the hold test
    compares raw cents rather than the rounded percentage."

    Design: Difficulty/boundary_precision_check/credit_exposure_exactly_at_limit_is_watch_not_hold
    """
    world = exact_exposure_brewer
    assert world["order"]["total_cents"] == 171000, (
        f"137000 + 25000 freight + 9000 pallet breaks = 171000, got "
        f"{world['order']['total_cents']}")

    before = get_brewer(world["brewer"]["id"])
    assert before["credit_exposure_cents"] == 171000, (
        f"the single open order is the whole exposure, got "
        f"{before['credit_exposure_cents']}")
    assert before["ar_balance_cents"] == 0, (
        f"nothing is invoiced, got {before['ar_balance_cents']}")

    at_limit = set_credit_limit(world["brewer"]["id"], 171000)
    assert at_limit["credit_utilization_pct"] == pytest.approx(100.00, abs=0.005), (
        f"171000 of 171000 is 100.00 percent, got "
        f"{at_limit['credit_utilization_pct']}")
    assert at_limit["credit_status"] == "WATCH", (
        f"the hold test is strictly greater-than, got {at_limit['credit_status']}")
    assert at_limit["credit_status"] != "HOLD", (
        "sitting exactly on the limit must not be a hold")
    assert at_limit["open_order_exposure_cents"] == 171000, (
        f"repricing the brewer does not touch the order, got "
        f"{at_limit['open_order_exposure_cents']}")


def test_one_cent_less_limit_is_a_hold_at_the_same_rounded_percentage(
        api, exact_exposure_brewer):
    """170,999 still rounds to 100.00 percent yet must read HOLD.

    PRD §3.1: "`credit_status` is `HOLD` when `credit_exposure_cents` is
    **strictly greater** than `credit_limit_cents`; otherwise `WATCH` when
    `credit_utilization_pct` is at least 85.00; otherwise `GOOD_STANDING`."

    Design: Difficulty/boundary_precision_check/credit_exposure_exactly_at_limit_is_watch_not_hold
    """
    world = exact_exposure_brewer
    at_limit = set_credit_limit(world["brewer"]["id"], 171000)
    over_limit = set_credit_limit(world["brewer"]["id"], 170999)

    assert over_limit["credit_utilization_pct"] == pytest.approx(100.00, abs=0.005), (
        "171000 of 170999 rounds to the same 100.00 percent, got "
        f"{over_limit['credit_utilization_pct']}")
    assert over_limit["credit_utilization_pct"] == \
        pytest.approx(at_limit["credit_utilization_pct"], abs=0.005), (
        "the two limits produce the same rounded percentage, got "
        f"{at_limit['credit_utilization_pct']} and "
        f"{over_limit['credit_utilization_pct']}")
    assert over_limit["credit_status"] == "HOLD", (
        f"one cent of excess is a hold, got {over_limit['credit_status']}")
    assert at_limit["credit_status"] != over_limit["credit_status"], (
        "a one-cent difference in the limit must change the status, both read "
        f"{over_limit['credit_status']}")
    assert over_limit["open_order_exposure_cents"] == 171000, (
        f"the open order is unchanged throughout, got "
        f"{over_limit['open_order_exposure_cents']}")


@pytest.fixture
def picked_order_on_credit_hold():
    """A STAGED 4-pallet load over a PICKED order whose credit was pulled after picking.

    The hold is recorded before the load exists, so nothing is dragged to HELD and
    the load sits squarely in STAGED with its pallets occupied.
    """
    pin_clock()
    brewer = create_brewer(name="Dock Hold Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-DOCK")
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    order = confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"])
    order = pick_order(order["id"])
    order = hold_credit(order["id"], note="aged receivable flagged after picking")
    shipment = stage_shipment(order["id"], zone["id"], pallet_count=4,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z",
                              reefer_setpoint_c=2.0, reefer_tolerance_c=2.0)
    return {"brewer": brewer, "variety": variety, "zone": zone, "order": order,
            "shipment": shipment}


def test_departure_is_refused_by_the_parent_orders_credit_dimension(
        api, picked_order_on_credit_hold):
    """The fulfillment precondition is met, so only the credit dimension can refuse.

    PRD §3.9: "The owning order must be in `PICKED`, and its `credit_status` must
    be `APPROVED`, otherwise `ERR_ORDER_CREDIT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/shipment_depart_gated_on_order_credit_dimension
    """
    world = picked_order_on_credit_hold
    assert world["order"]["fulfillment_status"] == "PICKED", (
        f"the order is picked, got {world['order']['fulfillment_status']}")
    assert world["order"]["credit_status"] == "ON_HOLD", (
        f"its credit dimension is on hold, got {world['order']['credit_status']}")
    assert world["order"]["total_cents"] == 95380, (
        f"44880 + 43000 freight + 7500 surcharge = 95380, got "
        f"{world['order']['total_cents']}")
    assert world["shipment"]["status"] == "STAGED", (
        f"the load is staged after the hold, got {world['shipment']['status']}")
    assert get_zone(world["zone"]["id"])["occupied_pallets"] == 4, (
        "four pallets are occupied, got "
        f"{get_zone(world['zone']['id'])['occupied_pallets']}")

    blocked = api.depart_shipment(world["shipment"]["id"], WH_HEADERS)
    validate_error(blocked, "ERR_ORDER_CREDIT_NOT_APPROVED", expected_status=402)

    shipment = validate_success(api.get_shipment(world["shipment"]["id"],
                                                 WH_HEADERS))
    assert shipment["status"] == "STAGED", (
        f"the load is neither HELD nor IN_TRANSIT, got {shipment['status']}")
    assert get_zone(world["zone"]["id"])["occupied_pallets"] == 4, (
        "a refused departure must not release pallets, got "
        f"{get_zone(world['zone']['id'])['occupied_pallets']}")


def test_re_approving_the_order_lets_the_same_load_depart_and_frees_the_zone(
        api, picked_order_on_credit_hold):
    """Clearing the receivable on the parent order unblocks the dock.

    PRD §3.9: "The warehouse sends a `STAGED` load onto the road, moving it
    `STAGED → IN_TRANSIT` and releasing its `pallet_count` from the zone."

    Design: Difficulty/cross_entity_state_dependency/shipment_depart_gated_on_order_credit_dimension
    """
    world = picked_order_on_credit_hold
    validate_error(api.depart_shipment(world["shipment"]["id"], WH_HEADERS),
                   "ERR_ORDER_CREDIT_NOT_APPROVED", expected_status=402)

    order = approve_credit(world["order"]["id"], note="receivable cleared")
    assert order["credit_status"] == "APPROVED", (
        f"the credit dimension is cleared, got {order['credit_status']}")
    assert order["fulfillment_status"] == "PICKED", (
        f"the fulfillment dimension never moved, got {order['fulfillment_status']}")

    departed = validate_success(api.depart_shipment(world["shipment"]["id"],
                                                    WH_HEADERS))
    assert departed["status"] == "IN_TRANSIT", (
        f"the same load now departs, got {departed['status']}")
    assert get_zone(world["zone"]["id"])["occupied_pallets"] == 0, (
        "departure releases the pallets, got "
        f"{get_zone(world['zone']['id'])['occupied_pallets']}")
