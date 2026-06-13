"""Composite setup helpers for the Art Auction Consignment API.

Most interesting claims require the system to be walked through 8-20 API
calls to reach a precise state (a SOLD lot in a CLOSED sale, an invoice PAID,
a statement disbursed, ...). These helpers encapsulate those chains so tests
can focus on assertions.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints — every test runs against a freshly-restarted, empty server.
Setup uses get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Version threading: OCC-guarded transitions need the resource's *current*
version. Helpers always read the live version (via a GET or the prior
response) immediately before each guarded write, exactly as the design index
chains do.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_premium_schedule_payload,
    create_seller_payload,
    create_bidder_payload,
    create_consignment_payload,
    create_auction_sale_payload,
    create_lot_payload,
    create_paddle_registration_payload,
    create_bid_payload,
    STANDARD_TIERS,
    FLAT_TIERS,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
AUCTIONEER = TEST_USERS["auctioneer_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------
def create_premium_schedule(tiers=None, name="Standard"):
    payload = create_premium_schedule_payload(
        name=name, tiers=[dict(t) for t in (tiers if tiers is not None else STANDARD_TIERS)]
    )
    return get_success_data(api_client.create_premium_schedule(payload, ADMIN))


def create_seller(**overrides):
    return get_success_data(api_client.create_seller(create_seller_payload(**overrides), ADMIN))


def create_bidder(**overrides):
    return get_success_data(api_client.create_bidder(create_bidder_payload(**overrides), ADMIN))


def create_active_consignment(seller_id, seller_commission_bps=1000, **overrides):
    """Create a DRAFT consignment then activate it -> ACTIVE."""
    cons = get_success_data(api_client.create_consignment(
        create_consignment_payload(seller_id, seller_commission_bps=seller_commission_bps, **overrides), ADMIN))
    cons = get_success_data(api_client.activate_consignment(
        cons["id"], {"expected_consignment_version": cons["version"]}, ADMIN))
    return cons


def create_draft_consignment(seller_id, seller_commission_bps=1000, **overrides):
    return get_success_data(api_client.create_consignment(
        create_consignment_payload(seller_id, seller_commission_bps=seller_commission_bps, **overrides), ADMIN))


def create_cataloging_sale(schedule_id, **overrides):
    return get_success_data(api_client.create_auction_sale(
        create_auction_sale_payload(schedule_id, **overrides), ADMIN))


def register_paddle(sale_id, bidder_id, **overrides):
    return get_success_data(api_client.create_paddle_registration(
        create_paddle_registration_payload(sale_id, bidder_id, **overrides), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: a base scene — schedule + seller + bidder + ACTIVE consignment +
# CATALOGING sale + one CATALOGED lot + a FLOOR paddle.
# ---------------------------------------------------------------------------
def setup_base_scene(tiers=None, seller_commission_bps=1000, credit_limit_cents=500000000,
                     artist_alive=False, low_estimate_cents=1300000, high_estimate_cents=1800000,
                     reserve_cents=1000000, lot_number=1):
    """Returns dict with schedule, seller, bidder, consignment, sale, lot, paddle."""
    schedule = create_premium_schedule(tiers=tiers)
    seller = create_seller()
    bidder = create_bidder(credit_limit_cents=credit_limit_cents)
    cons = create_active_consignment(seller["id"], seller_commission_bps=seller_commission_bps)
    sale = create_cataloging_sale(schedule["id"])
    lot = get_success_data(api_client.create_lot(
        sale["id"],
        create_lot_payload(
            cons["id"], lot_number=lot_number, artist_alive=artist_alive,
            low_estimate_cents=low_estimate_cents, high_estimate_cents=high_estimate_cents,
            reserve_cents=reserve_cents),
        ADMIN))
    paddle = register_paddle(sale["id"], bidder["id"])
    return {
        "schedule": schedule, "seller": seller, "bidder": bidder,
        "consignment": cons, "sale": sale, "lot": lot, "paddle": paddle,
    }


def _publish_and_go_live(sale_id):
    sale = get_success_data(api_client.get_auction_sale(sale_id, ADMIN))
    sale = get_success_data(api_client.publish_auction_sale(
        sale_id, {"expected_auction_sale_version": sale["version"]}, ADMIN))
    sale = get_success_data(api_client.open_bidding(
        sale_id, {"expected_auction_sale_version": sale["version"]}, AUCTIONEER))
    return sale


# ---------------------------------------------------------------------------
# Tier 2: an OPEN lot in a LIVE sale, ready for bidding.
# ---------------------------------------------------------------------------
def setup_open_lot(tiers=None, reserve_cents=1000000, low_estimate_cents=1300000,
                   high_estimate_cents=1800000, credit_limit_cents=500000000,
                   artist_alive=False):
    """Schedule + seller + bidder + ACTIVE consignment + LIVE sale + OPEN lot
    + FLOOR paddle. Returns the scene dict (lot now OPEN)."""
    scene = setup_base_scene(
        tiers=tiers, reserve_cents=reserve_cents, low_estimate_cents=low_estimate_cents,
        high_estimate_cents=high_estimate_cents, credit_limit_cents=credit_limit_cents,
        artist_alive=artist_alive)
    _publish_and_go_live(scene["sale"]["id"])
    scene["lot"] = get_success_data(api_client.get_lot(scene["lot"]["id"], AUCTIONEER))
    return scene


def place_bid(lot_id, paddle_id, amount_cents, bid_channel="FLOOR", headers=None):
    return get_success_data(api_client.create_bid(
        lot_id, create_bid_payload(paddle_id, amount_cents, bid_channel=bid_channel),
        headers or AUCTIONEER))


# ---------------------------------------------------------------------------
# Tier 3: a SOLD lot in a CLOSED sale (knock-down at a chosen hammer).
# ---------------------------------------------------------------------------
def setup_sold_lot(hammer_cents=1250000, tiers=None, seller_commission_bps=1000,
                   artist_alive=False, reserve_cents=1000000, low_estimate_cents=1300000,
                   high_estimate_cents=1800000, credit_limit_cents=500000000):
    """Walk all the way to: lot SOLD at `hammer_cents`, sale CLOSED.
    Returns scene dict (lot now SOLD, sale CLOSED)."""
    scene = setup_base_scene(
        tiers=tiers, seller_commission_bps=seller_commission_bps, artist_alive=artist_alive,
        reserve_cents=reserve_cents, low_estimate_cents=low_estimate_cents,
        high_estimate_cents=high_estimate_cents, credit_limit_cents=credit_limit_cents)
    sale_id = scene["sale"]["id"]
    lot_id = scene["lot"]["id"]
    _publish_and_go_live(sale_id)
    place_bid(lot_id, scene["paddle"]["id"], hammer_cents)
    lot = get_success_data(api_client.get_lot(lot_id, AUCTIONEER))
    lot = get_success_data(api_client.knock_down_lot(
        lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER))
    sale = get_success_data(api_client.get_auction_sale(sale_id, AUCTIONEER))
    get_success_data(api_client.close_auction_sale(
        sale_id, {"expected_auction_sale_version": sale["version"]}, AUCTIONEER))
    scene["lot"] = get_success_data(api_client.get_lot(lot_id, FINANCE))
    return scene


# ---------------------------------------------------------------------------
# Tier 4: settlement-stage shortcuts.
# ---------------------------------------------------------------------------
def invoice_sold_lot(scene):
    """Given a scene with a SOLD lot in a CLOSED sale, issue the invoice.
    Returns (scene, invoice). scene['lot'] refreshed to settlement INVOICED."""
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api_client.get_lot(lot_id, FINANCE))
    invoice = get_success_data(api_client.invoice_lot(
        lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    scene["invoice"] = invoice
    scene["lot"] = get_success_data(api_client.get_lot(lot_id, FINANCE))
    return scene, invoice


def setup_invoiced_lot(hammer_cents=1250000, tiers=None, seller_commission_bps=1000,
                       artist_alive=False, credit_limit_cents=500000000):
    """SOLD lot in CLOSED sale, then invoiced (Invoice ISSUED). Returns
    (scene, invoice)."""
    scene = setup_sold_lot(
        hammer_cents=hammer_cents, tiers=tiers, seller_commission_bps=seller_commission_bps,
        artist_alive=artist_alive, credit_limit_cents=credit_limit_cents)
    return invoice_sold_lot(scene)


def pay_invoice_full(invoice):
    """Pay an invoice in full (total_due in one payment) -> PAID."""
    return get_success_data(api_client.create_payment(
        invoice["id"],
        {"amount_cents": invoice["total_due_cents"], "expected_invoice_version": invoice["version"]},
        FINANCE))


def setup_paid_invoice_lot(hammer_cents=1250000, tiers=None, seller_commission_bps=1000,
                           artist_alive=False, credit_limit_cents=500000000):
    """SOLD lot in CLOSED sale, invoiced and fully PAID. Returns
    (scene, invoice_paid)."""
    scene, invoice = setup_invoiced_lot(
        hammer_cents=hammer_cents, tiers=tiers, seller_commission_bps=seller_commission_bps,
        artist_alive=artist_alive, credit_limit_cents=credit_limit_cents)
    paid = pay_invoice_full(invoice)
    scene["invoice"] = paid
    scene["lot"] = get_success_data(api_client.get_lot(scene["lot"]["id"], FINANCE))
    return scene, paid


def setup_statemented_lot(hammer_cents=1250000, tiers=None, seller_commission_bps=1000,
                          artist_alive=False, credit_limit_cents=500000000):
    """Through to a generated SellerStatement (lot STATEMENTED, statement
    PENDING). Returns (scene, statement)."""
    scene, paid = setup_paid_invoice_lot(
        hammer_cents=hammer_cents, tiers=tiers, seller_commission_bps=seller_commission_bps,
        artist_alive=artist_alive, credit_limit_cents=credit_limit_cents)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api_client.get_lot(lot_id, FINANCE))
    statement = get_success_data(api_client.statement_lot(
        lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    scene["statement"] = statement
    scene["lot"] = get_success_data(api_client.get_lot(lot_id, FINANCE))
    return scene, statement


def setup_settled_lot(hammer_cents=1250000, tiers=None, seller_commission_bps=1000,
                      artist_alive=True, credit_limit_cents=500000000):
    """Full lifecycle through disbursement: lot SETTLED, statement PAID,
    payout DISBURSED, royalty (if any) REMITTED. Returns
    (scene, statement, payout)."""
    scene, statement = setup_statemented_lot(
        hammer_cents=hammer_cents, tiers=tiers, seller_commission_bps=seller_commission_bps,
        artist_alive=artist_alive, credit_limit_cents=credit_limit_cents)
    payout = get_success_data(api_client.disburse_statement(
        statement["id"], {"expected_seller_statement_version": statement["version"]}, FINANCE))
    scene["payout"] = payout
    scene["statement"] = get_success_data(api_client.get_seller_statement(statement["id"], FINANCE))
    scene["lot"] = get_success_data(api_client.get_lot(scene["lot"]["id"], FINANCE))
    return scene, statement, payout
