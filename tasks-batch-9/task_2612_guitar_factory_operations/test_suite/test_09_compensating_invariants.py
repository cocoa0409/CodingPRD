"""
Three conserved quantities and the compensating movements that must keep them
balanced: board feet recovered to the rack, deposit cents run through a capped
waterfall, and machine minutes moved sideways rather than erased.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_cancelling_the_order_returns_the_reserved_wood_to_the_rack(api, chain_b):
    """
    The thirty board feet reserved to the cancelled instrument come back as
    unassigned stock rather than being written off, because the billet is
    physically still on the rack and can be cut for another order.

    PRD: "Cancellation drives `commercial_status` to `CANCELLED` and `build_stage`
    to `SCRAPPED`; scraps every part of the order that is not already `INSTALLED`
    or `SCRAPPED` while returning each of their billets `RESERVED → AVAILABLE` and
    moving the board feet from the reserved bucket back to the unassigned bucket;
    releases every station reservation on the order still in status `HELD`, moving
    each one's `duration_minutes` from the station's `held_minutes` to its
    `released_minutes`; and settles the deposit."

    Design: Difficulty/compensating_invariant/i1_board_feet_conserved_when_cancel_recovers_reserved_wood
    """
    before = validate_success(
        api.get_tonewood_lot(chain_b["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(before, available=69.10, unassigned=0.00, reserved=30.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=0.90)

    F.cancel_order(api, chain_b["bo1"], "CUSTOMER_WITHDREW", U.COORDINATOR_HEADERS)

    after = validate_success(
        api.get_tonewood_lot(chain_b["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(after, available=69.10, unassigned=30.00, reserved=0.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=0.90)

    billet = validate_success(api.get_billet(chain_b["blt1"], U.MACHINIST_HEADERS))
    assert billet["status"] == "AVAILABLE"


def test_scrapping_a_part_destroys_the_wood_instead_of_recovering_it(api, comp_routed):
    """
    The forward movement starts from the identical thirty reserved board feet and
    lands them in the scrapped bucket with nothing returned to stock, which is
    what distinguishes destruction from recovery even though both keep the six
    buckets adding up.

    PRD: "Scrapping destroys the wood: the part's billet moves `RESERVED →
    SCRAPPED` and its board feet move out of the lot's `board_feet_reserved` and
    into `board_feet_scrapped`."

    Design: Difficulty/compensating_invariant/i1_board_feet_conserved_when_cancel_recovers_reserved_wood
    """
    res2 = F.create_reservation(api, comp_routed["hs1"], "2026-08-02T10:00:00Z",
                               "2026-08-02T11:00:00Z",
                               component_id=comp_routed["cmp1"],
                               headers=U.LUTHIER_HEADERS)["id"]
    F.hand_shape_component(api, comp_routed["cmp1"], res2, 2.90)
    F.qc_component(api, comp_routed["cmp1"], "HOLD", hold_reason="DIMENSION")
    F.disposition_component(api, comp_routed["cmp1"], "SCRAP", U.INSPECTOR_HEADERS)

    lot = validate_success(
        api.get_tonewood_lot(comp_routed["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(lot, available=69.10, unassigned=0.00, reserved=0.00,
                        consumed=0.00, scrapped=30.00, kerf_loss=0.90)

    billet = validate_success(api.get_billet(comp_routed["blt1"], U.MACHINIST_HEADERS))
    assert billet["status"] == "SCRAPPED"


def test_a_thin_deposit_on_an_expensive_order_forfeits_everything_and_refunds_nothing(api, chain_c):
    """
    A quarter of the binding total is more than the customer ever paid, so the cap
    binds and the refund comes out at exactly zero rather than going negative.

    PRD: "The forfeit is twenty-five percent of that basis — multiply by 2500
    basis points, divide by 10000, round half up — but capped at whatever is
    actually still in `deposit_held_cents`, so the mill can never forfeit more
    than the customer left on deposit."

    Design: Difficulty/compensating_invariant/i2_deposit_conserved_when_the_forfeit_cap_binds
    """
    before = validate_success(
        api.get_build_order(chain_c["bo1"], U.COORDINATOR_HEADERS))
    assert before["binding_quote_total_cents"] == 716610
    assert before["deposit_held_cents"] == 88619

    cancelled = validate_success(api.cancel_build_order(
        chain_c["bo1"], U.COORDINATOR_HEADERS, {"reason": "ARTIST_WITHDREW"}))
    A.assert_deposit_ledger(cancelled, paid=88619, applied=0, refunded=0,
                            forfeited=88619, held=0)


def test_the_cancelled_order_is_closed_on_both_dimensions_by_the_settlement(api, chain_c):
    """
    The same request that runs the money waterfall also drives both dimensions of
    the order to their terminal states, and the four cash buckets still add up to
    everything the customer ever paid.

    PRD: "A thin deposit on an expensive order refunds nothing and forfeits
    precisely what was held."

    Design: Difficulty/compensating_invariant/i2_deposit_conserved_when_the_forfeit_cap_binds
    """
    cancelled = validate_success(api.cancel_build_order(
        chain_c["bo1"], U.COORDINATOR_HEADERS, {"reason": "ARTIST_WITHDREW"}))
    A.assert_order_state(cancelled, build_stage="SCRAPPED",
                         commercial_status="CANCELLED")
    A.assert_money_conserved(cancelled)
    assert cancelled["deposit_forfeited_cents"] == 88619
    assert cancelled["deposit_refunded_cents"] == 0


def two_held_hours_on_one_router(api):
    """One CNC router carrying two booked hours and nothing machined yet."""
    env = X.build_one_cnc_station(api)
    env["res1"] = F.create_reservation(api, env["cnc1"], "2026-08-02T08:00:00Z",
                                      "2026-08-02T09:00:00Z")["id"]
    env["res2"] = F.create_reservation(api, env["cnc1"], "2026-08-02T10:00:00Z",
                                      "2026-08-02T11:00:00Z")["id"]
    return env


def test_giving_a_window_back_moves_the_minutes_sideways_and_never_erases_them(api):
    """
    The booking really happened and was really handed back, so the hour leaves the
    held bucket for the released one while the permanent record of everything ever
    scheduled stays exactly where it was.

    PRD: "Giving the window back — available to a `Machinist`, a `Luthier` or a
    `PlantAdmin` — moves it `HELD → RELEASED`, subtracting `duration_minutes` from
    `held_minutes` and adding it to `released_minutes`."

    Design: Difficulty/compensating_invariant/i3_station_minutes_conserved_when_a_hold_is_released
    """
    env = two_held_hours_on_one_router(api)

    before = validate_success(api.get_station(env["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(before, total=120, held=120, consumed=0, released=0)

    released = F.release_reservation(api, env["res1"])
    assert released["status"] == "RELEASED"

    after = validate_success(api.get_station(env["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(after, total=120, held=60, consumed=0, released=60)


def test_the_same_window_cannot_be_given_back_twice(api):
    """
    A released window is terminal, so a second attempt is refused instead of
    counting the same hour into the released bucket again.

    PRD: "Citing a reservation that is no longer `HELD` — for routing, for
    hand-shaping or for release — is `ERR_RESERVATION_STATE_INVALID`."

    Design: Difficulty/compensating_invariant/i3_station_minutes_conserved_when_a_hold_is_released
    """
    env = two_held_hours_on_one_router(api)
    F.release_reservation(api, env["res1"])

    validate_error(api.release_station_reservation(env["res1"], U.MACHINIST_HEADERS),
                   E.ERR_RESERVATION_STATE_INVALID, 409)

    station = validate_success(api.get_station(env["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(station, total=120, held=60, consumed=0, released=60)
