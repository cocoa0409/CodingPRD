"""Transition preconditions, business-constraint violations, and uniqueness/coherence
errors across the auction workflows.
"""
import pytest

from test_helpers import (
    make_admin_headers, make_buyer_headers,
    get_success_data, validate_error,
    setup_running_sale_with_lot, setup_cleared_settlement, setup_hammered_lot,
    open_bidding, current_lot_version, place_bid, place_bid_ok,
)
import test_helpers as th


# ─── state_machines: precondition enforcement ───────────────────────────────
def test_open_bidding_twice_rejects_second_call(api):
    """PRD §3.5: "Opening a lot for bidding is an admin action that moves it from
    `SCHEDULED` to `BIDDING_OPEN`. It requires the lot to be `SCHEDULED` (otherwise
    `ERR_LOT_NOT_SCHEDULED`)".

    Design: Corner/state_machines/open_bidding_on_already_open_lot_returns_invalid_state
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, starting_bid_cents=400000)
    get_success_data(api.open_bidding(ctx["lot"]["id"], admin))
    resp = api.open_bidding(ctx["lot"]["id"], admin)
    validate_error(resp, "ERR_LOT_NOT_SCHEDULED")


def test_hammer_when_outcome_not_sold_returns_error(api):
    """PRD §3.6: "Hammering moves the lot to `HAMMERED` and requires the lot to be
    `BIDDING_CLOSED` (otherwise `ERR_LOT_NOT_BIDDING_CLOSED`) and the outcome to compute to
    `SOLD`, meaning `high_bidder_id` is not null and `high_bid_cents` is at least the reserve
    (otherwise `ERR_OUTCOME_NOT_SOLD`)."

    Design: Corner/state_machines/hammer_when_outcome_not_sold_returns_error
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, starting_bid_cents=400000)
    # Open then close with zero buyer bids -> high_bidder null -> outcome PASSED.
    get_success_data(api.open_bidding(ctx["lot"]["id"], admin))
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    resp = api.hammer_lot(ctx["lot"]["id"], admin)
    validate_error(resp, "ERR_OUTCOME_NOT_SOLD")


def test_catalog_without_condition_report_returns_error(api):
    """PRD §3.3: "Cataloging ... requires three things in order: the consignment must be in
    `SUBMITTED` (otherwise `ERR_CONSIGNMENT_NOT_SUBMITTED`); a condition report must already
    exist for the consignment (otherwise `ERR_CONDITION_REPORT_MISSING`)".

    Design: Corner/state_machines/catalog_without_condition_report_returns_error
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons = get_success_data(api.create_consignment(
        th.factories.create_consignment_payload(sale["id"], seller["id"]), admin))
    resp = api.catalog_consignment(cons["id"], th.factories.catalog_payload(0, 0), admin)
    validate_error(resp, "ERR_CONDITION_REPORT_MISSING")


def test_redeem_gatepass_without_dispatched_transport_returns_error(api):
    """PRD §3.11: "Redeeming a gate pass is an admin action requiring the gate pass to be
    `ISSUED` (otherwise `ERR_GATE_PASS_NOT_ISSUED`) and requiring that a transport order
    exists for the same settlement in `DISPATCHED` status (otherwise
    `ERR_NO_DISPATCHED_TRANSPORT`)."

    Design: Corner/state_machines/redeem_gatepass_without_dispatched_transport_returns_error
    """
    admin = make_admin_headers()
    ctx = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                   channel="LANE")
    # Gate pass ISSUED but no transport order created at all -> ERR_NO_DISPATCHED_TRANSPORT.
    resp = api.redeem_gate_pass(ctx["gate_pass"]["id"], admin)
    validate_error(resp, "ERR_NO_DISPATCHED_TRANSPORT")


# ─── validations: violation -> error ────────────────────────────────────────
def test_bid_below_minimum_increment_returns_error(api):
    """PRD §3.5: "when a buyer high bid already stands on the lot, the new `amount_cents`
    must be at least the current `high_bid_cents` plus the applicable bid increment".

    Design: Corner/validations/bid_below_minimum_increment_returns_error
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, starting_bid_cents=500000)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    # B1 LIVE 500000 stands (high_bid 500000, increment 25000 -> min next = 525000).
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], lot_open["version"],
                 bid_type="LIVE", amount_cents=500000, channel="LANE")
    v1 = current_lot_version(api, ctx["lot"]["id"], admin)
    # B2 bids 510000 (< 525000) -> ERR_BID_BELOW_MINIMUM.
    resp = place_bid(api, ctx["lot"]["id"], b2["id"], v1, bid_type="LIVE", amount_cents=510000, channel="LANE")
    validate_error(resp, "ERR_BID_BELOW_MINIMUM")


def test_suspended_buyer_cannot_bid_returns_error(api):
    """PRD §3.2: "A buyer may be moved `ACTIVE → SUSPENDED` and `SUSPENDED → ACTIVE` by an
    admin; a suspended buyer may not place bids."
    PRD §3.5: "the buyer must be `ACTIVE` (otherwise `ERR_BUYER_SUSPENDED`)".

    Design: Corner/validations/suspended_buyer_cannot_bid_returns_error
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    get_success_data(api.suspend_buyer(buyer["id"], admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    resp = place_bid(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                     bid_type="LIVE", amount_cents=400000, channel="LANE")
    validate_error(resp, "ERR_BUYER_SUSPENDED")


def test_catalog_floor_above_reserve_returns_error(api):
    """PRD §3.3: "the supplied floor must not exceed the supplied reserve (otherwise
    `ERR_FLOOR_ABOVE_RESERVE`)."

    Design: Corner/validations/catalog_floor_above_reserve_returns_error
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons = get_success_data(api.create_consignment(
        th.factories.create_consignment_payload(sale["id"], seller["id"]), admin))
    get_success_data(api.create_condition_report(
        th.factories.create_condition_report_payload(cons["id"]), admin))
    resp = api.catalog_consignment(cons["id"],
                                   th.factories.catalog_payload(reserve_price_cents=400000,
                                                                floor_price_cents=500000), admin)
    validate_error(resp, "ERR_FLOOR_ABOVE_RESERVE")


def test_duplicate_vin_in_sale_returns_error(api):
    """PRD §3.3: "The `vin` must be unique within its sale; a repeat is rejected with
    `ERR_DUPLICATE_VIN`."

    Design: Corner/validations/duplicate_vin_in_sale_returns_error
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    vin = th.factories.next_vin()
    get_success_data(api.create_consignment(
        th.factories.create_consignment_payload(sale["id"], seller["id"], vin=vin), admin))
    resp = api.create_consignment(
        th.factories.create_consignment_payload(sale["id"], seller["id"], vin=vin), admin)
    validate_error(resp, "ERR_DUPLICATE_VIN")


def test_insufficient_credit_blocks_winning_bid(api):
    """PRD §3.5: "the buyer must have enough available credit to cover the projected total
    due were this bid to win (otherwise `ERR_INSUFFICIENT_CREDIT`, HTTP 402)."

    Design: Corner/validations/insufficient_credit_blocks_winning_bid
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(
        th.factories.create_buyer_payload(dealer_name="B1", credit_limit_cents=100), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    resp = place_bid(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                     bid_type="LIVE", amount_cents=400000, channel="LANE")
    validate_error(resp, "ERR_INSUFFICIENT_CREDIT")


# ─── errors: violation -> error ─────────────────────────────────────────────
def test_duplicate_run_number_in_lane_returns_error(api):
    """PRD §3.4: "the `run_number` must be a positive integer unique within its lane; a
    duplicate is rejected with `ERR_DUPLICATE_RUN_NUMBER`."

    Design: Corner/errors/duplicate_run_number_in_lane_returns_error
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons1 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    cons2 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    th.fixtures.make_scheduled_lot(api, sale["id"], cons1["id"], lane["id"], admin,
                                   run_number=1, slot_start_minute=0, slot_end_minute=10)
    # Same run_number 1, non-overlapping slot [20,30) -> only the run_number uniqueness fails.
    resp = api.create_lot(
        th.factories.create_lot_payload(sale["id"], cons2["id"], lane["id"], run_number=1,
                                        slot_start_minute=20, slot_end_minute=30),
        admin,
    )
    validate_error(resp, "ERR_DUPLICATE_RUN_NUMBER")


def test_dispatch_with_suspended_carrier_returns_error(api):
    """PRD §3.11: "Dispatching is an admin action moving the order from `REQUESTED` to
    `DISPATCHED`; it requires the order to be `REQUESTED` ..., the referenced settlement to
    be `CLEARED` ..., and the carrier to be `ACTIVE` (otherwise `ERR_CARRIER_SUSPENDED`)."

    Design: Corner/errors/dispatch_with_suspended_carrier_returns_error
    """
    admin = make_admin_headers()
    carrier = get_success_data(api.create_carrier(th.factories.create_carrier_payload(), admin))
    ctx = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                   channel="LANE")
    to = get_success_data(api.create_transport_order(
        th.factories.create_transport_order_payload(ctx["settlement"]["id"], carrier["id"],
                                                    pickup_start_minute=100, pickup_end_minute=160),
        admin,
    ))
    get_success_data(api.suspend_carrier(carrier["id"], admin))
    resp = api.dispatch_transport_order(to["id"], admin)
    validate_error(resp, "ERR_CARRIER_SUSPENDED")


def test_dispatch_before_settlement_cleared_returns_error(api):
    """PRD §3.11: "it requires the order to be `REQUESTED` ..., the referenced settlement to
    be `CLEARED` (otherwise `ERR_SETTLEMENT_NOT_CLEARED`)".

    Design: Corner/errors/transport_dispatch_before_settlement_cleared_returns_error
    """
    admin = make_admin_headers()
    carrier = get_success_data(api.create_carrier(th.factories.create_carrier_payload(), admin))
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE")
    # Record payment only (title not recorded) -> settlement stays OPEN (not CLEARED).
    get_success_data(api.record_payment(ctx["settlement"]["id"], admin))
    to = get_success_data(api.create_transport_order(
        th.factories.create_transport_order_payload(ctx["settlement"]["id"], carrier["id"],
                                                    pickup_start_minute=100, pickup_end_minute=160),
        admin,
    ))
    resp = api.dispatch_transport_order(to["id"], admin)
    validate_error(resp, "ERR_SETTLEMENT_NOT_CLEARED")


def test_lane_archive_with_lots_returns_error(api):
    """PRD §3.1: "Archiving a lane ... requires the lane to be `PLANNED` (otherwise
    `ERR_LANE_NOT_PLANNED`) and requires the lane's `scheduled_slot_count` to be 0
    (otherwise `ERR_LANE_HAS_LOTS`)."

    Design: Corner/errors/lane_archive_with_lots_returns_error
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    th.fixtures.make_scheduled_lot(api, sale["id"], cons["id"], lane["id"], admin)
    # Lane still PLANNED (sale never started) but holds one lot -> scheduled_slot_count > 0.
    resp = api.archive_lane(lane["id"], admin)
    validate_error(resp, "ERR_LANE_HAS_LOTS")
