"""State-machine compliance: the Lot's two parallel dimensions, the
Consignment revert cycle, sale lifecycle preconditions, terminal lockdown,
the terminate cascade, and bid retraction's effect on standing high.
"""
from test_helpers import validate_success, validate_error, get_success_data
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    setup_base_scene, setup_sold_lot, setup_open_lot, setup_settled_lot,
    create_seller, create_active_consignment, create_premium_schedule,
    create_cataloging_sale, create_bidder, register_paddle, place_bid,
    invoice_sold_lot, _publish_and_go_live, ADMIN, AUCTIONEER, FINANCE,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_lot_payload, FLAT_TIERS, STANDARD_TIERS,
)


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
def test_lot_parallel_dimensions_evolve_independently(api):
    """PRD §2.6: "The two dimensions advance independently, with one hard
    ordering rule: `settlement_status` may leave `NONE` only after
    `sale_status` has reached `SOLD`."
    PRD §3.6: "The invoice action finally sets the lot's `settlement_status` to
    `INVOICED` and increments the lot's `version` by 1."

    Before invoice: sale_status SOLD, settlement_status NONE. After invoice:
    sale_status still SOLD, settlement_status INVOICED.

    Design: Difficulty/non_linear_state_machine/nonlinear_lot_parallel_dimensions
    """
    scene = setup_sold_lot(hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    pre = get_success_data(api.get_lot(lot_id, FINANCE))
    assert pre["sale_status"] == "SOLD"
    assert pre["settlement_status"] == "NONE"
    invoice = get_success_data(api.invoice_lot(
        lot_id, {"expected_lot_version": pre["version"]}, FINANCE))
    post = get_success_data(api.get_lot(lot_id, FINANCE))
    assert post["sale_status"] == "SOLD", "sale_status must stay SOLD after invoice"
    assert post["settlement_status"] == "INVOICED"


def test_settlement_status_starts_none_after_knockdown(api):
    """PRD §3.5: "Knock-down does not itself create any invoice or royalty; the
    lot's `settlement_status` stays `NONE` until the buyer is invoiced."

    Right after a SOLD knock-down (before any invoice) the financial dimension
    is still NONE even though the sale dimension is SOLD.

    Design: Difficulty/non_linear_state_machine/nonlinear_lot_parallel_dimensions
    """
    scene = setup_open_lot(tiers=STANDARD_TIERS, reserve_cents=1000000)
    lot_id = scene["lot"]["id"]
    place_bid(lot_id, scene["paddle"]["id"], 1250000)
    lot = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    knocked = get_success_data(api.knock_down_lot(
        lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER))
    assert knocked["sale_status"] == "SOLD"
    assert knocked["settlement_status"] == "NONE"


def test_consignment_revert_cycle_returns_to_active(api):
    """PRD §3.2: "An `ACTIVE` consignment may be reverted to `DRAFT` for
    amendment."
    PRD §3.2: "Activation — countersigning the agreement — advances it from
    `DRAFT` to `ACTIVE`, and is permitted only when the consignment is
    currently `DRAFT` and the `Seller` named by `seller_id` exists"

    DRAFT -> ACTIVE -> DRAFT -> ACTIVE: status returns to a previously visited
    state on the consignment cycle.

    Design: Difficulty/non_linear_state_machine/nonlinear_consignment_revert_cycle
    """
    seller = create_seller()
    cons = get_success_data(api.create_consignment(
        {"seller_id": seller["id"], "seller_commission_bps": 1200}, ADMIN))
    cons = get_success_data(api.activate_consignment(
        cons["id"], {"expected_consignment_version": cons["version"]}, ADMIN))
    assert cons["status"] == "ACTIVE"
    reverted = get_success_data(api.revert_consignment_to_draft(
        cons["id"], {"expected_consignment_version": cons["version"]}, ADMIN))
    assert reverted["status"] == "DRAFT"
    reactivated = get_success_data(api.activate_consignment(
        cons["id"], {"expected_consignment_version": reverted["version"]}, ADMIN))
    assert reactivated["status"] == "ACTIVE"


def test_consignment_revert_increments_version(api):
    """PRD §3.2: "The revert increments the consignment's `version` by 1."
    PRD §3.2: "Activation ... increments the consignment's `version` by 1."

    Each transition around the DRAFT<->ACTIVE cycle bumps the version, so a
    create->activate->revert->activate path produces a strictly rising version.

    Design: Difficulty/non_linear_state_machine/nonlinear_consignment_revert_cycle
    """
    seller = create_seller()
    cons = get_success_data(api.create_consignment(
        {"seller_id": seller["id"], "seller_commission_bps": 1200}, ADMIN))
    v_create = cons["version"]
    cons = get_success_data(api.activate_consignment(
        cons["id"], {"expected_consignment_version": cons["version"]}, ADMIN))
    v_active = cons["version"]
    cons = get_success_data(api.revert_consignment_to_draft(
        cons["id"], {"expected_consignment_version": cons["version"]}, ADMIN))
    v_revert = cons["version"]
    assert v_create == 1
    assert v_active == v_create + 1
    assert v_revert == v_active + 1


# ===========================================================================
# Queue B — state_machines section
# ===========================================================================
def test_publish_already_published_rejected(api):
    """PRD §3.3: "Publishing the catalog moves the sale from `CATALOGING` to
    `PUBLISHED`; it requires the sale to be in `CATALOGING` (otherwise
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/publish_from_published_returns_invalid_state
    """
    scene = setup_base_scene()
    sale_id = scene["sale"]["id"]
    sale = get_success_data(api.get_auction_sale(sale_id, ADMIN))
    published = get_success_data(api.publish_auction_sale(
        sale_id, {"expected_auction_sale_version": sale["version"]}, ADMIN))
    resp = api.publish_auction_sale(
        sale_id, {"expected_auction_sale_version": published["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_publish_with_no_lots_rejected(api):
    """PRD §3.3: "[publish] requires at least one non-withdrawn lot to exist
    (otherwise `ERR_LOTS_REQUIRED`)"

    Design: Corner/state_machines/publish_with_no_lots_returns_lots_required
    """
    schedule = create_premium_schedule(tiers=FLAT_TIERS)
    sale = create_cataloging_sale(schedule["id"])
    sale = get_success_data(api.get_auction_sale(sale["id"], ADMIN))
    resp = api.publish_auction_sale(
        sale["id"], {"expected_auction_sale_version": sale["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_LOTS_REQUIRED.value)


def test_close_sale_with_open_lot_rejected(api):
    """PRD §3.3: "Closing the sale moves it from `LIVE` to `CLOSED`; ... requires
    that no lot in the sale remains `OPEN` ... failing which the close is
    rejected with `ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS`"

    Design: Corner/state_machines/close_sale_with_open_lot_returns_not_empty
    """
    scene = setup_open_lot(tiers=FLAT_TIERS)
    sale_id = scene["sale"]["id"]
    sale = get_success_data(api.get_auction_sale(sale_id, AUCTIONEER))
    resp = api.close_auction_sale(
        sale_id, {"expected_auction_sale_version": sale["version"]}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS.value)


def test_closed_sale_rejects_open_bidding(api):
    """PRD §2.6: "an `AuctionSale` runs `CATALOGING` → `PUBLISHED` → `LIVE` →
    `CLOSED`"
    PRD §3.3: "Going live moves the sale from `PUBLISHED` to `LIVE`; it requires
    the sale to be `PUBLISHED`"

    A CLOSED sale is terminal; re-opening bidding fails the PUBLISHED
    precondition with ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_sale_closed_rejects_further_transition
    """
    # Build a sale that reaches CLOSED via a bought-in lot.
    scene = setup_open_lot(tiers=FLAT_TIERS)
    sale_id = scene["sale"]["id"]
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    get_success_data(api.buy_in_lot(lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER))
    sale = get_success_data(api.get_auction_sale(sale_id, AUCTIONEER))
    closed = get_success_data(api.close_auction_sale(
        sale_id, {"expected_auction_sale_version": sale["version"]}, AUCTIONEER))
    resp = api.open_bidding(
        sale_id, {"expected_auction_sale_version": closed["version"]}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_retract_high_bid_lowers_standing_high(api):
    """PRD §3.5: "An `Auctioneer` may retract an `ACCEPTED` bid, supplying
    `expected_bid_version`; retraction sets the bid's `status` to `RETRACTED`,
    recomputes the lot's standing high, and increments the bid's `version` by 1."
    PRD §3.5: "The standing-high bid on a lot is the bid with the greatest
    `amount_cents` among the lot's bids whose `status` is `ACCEPTED` (a
    `RETRACTED` bid is excluded from this computation"

    After retracting the 200000 bid, standing-high reverts to 100000 so a
    110000 bid (= 100000 + the 10000 increment) is accepted.

    Design: Corner/state_machines/retract_bid_recomputes_standing_high
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=90000,
                           low_estimate_cents=120000, high_estimate_cents=300000)
    lot_id = scene["lot"]["id"]
    paddle_id = scene["paddle"]["id"]
    place_bid(lot_id, paddle_id, 100000)
    high = place_bid(lot_id, paddle_id, 200000)
    retracted = get_success_data(api.retract_bid(
        high["id"], {"expected_bid_version": high["version"]}, AUCTIONEER))
    assert retracted["status"] == "RETRACTED"
    ok = validate_success(
        api.create_bid(lot_id, {"paddle_registration_id": paddle_id,
                                "amount_cents": 110000, "bid_channel": "FLOOR"}, AUCTIONEER),
        expected_status=201)
    assert ok["amount_cents"] == 110000
    assert ok["status"] == "ACCEPTED"


def test_terminate_consignment_cascades_lots_to_withdrawn(api):
    """PRD §3.2: "On termination, every lot under the consignment that is still
    `CATALOGED` is cascaded from `CATALOGED` to `WITHDRAWN`"

    Design: Corner/state_machines/cancelled_terminate_cascade_withdraws_lots
    """
    scene = setup_base_scene()
    cons_id = scene["consignment"]["id"]
    lot_id = scene["lot"]["id"]
    cons = get_success_data(api.get_consignment(cons_id, ADMIN))
    terminated = get_success_data(api.terminate_consignment(
        cons_id, {"expected_consignment_version": cons["version"]}, ADMIN))
    assert terminated["status"] == "TERMINATED"
    lot = get_success_data(api.get_lot(lot_id, ADMIN))
    assert lot["sale_status"] == "WITHDRAWN"


def test_reverse_sale_after_disburse_rejected(api):
    """PRD §3.9: "If the lot's seller statement has already been disbursed —
    that is, the statement is already `PAID` — the entire reverse-sale is
    rejected with `ERR_STATEMENT_ALREADY_PAID` and no side effects fire"

    Design: Corner/state_machines/reverse_sale_after_disburse_returns_statement_paid
    """
    scene, statement, payout = setup_settled_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    resp = api.reverse_sale(lot_id, {"expected_lot_version": lot["version"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_ALREADY_PAID.value)
