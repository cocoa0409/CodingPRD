"""Composite setup helpers for the wholesale vehicle auction workflows.

These encapsulate the multi-step preambles that most interesting tests share:
standing up a sale with a lane, registering dealers, consigning + cataloging a
vehicle, run-listing it as a lot, running the block (open/bid/close), hammering
to create a settlement, and clearing/settling through to a gate pass.

All setup calls go through get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" error, not a confusing
assertion deep inside a test.

Identity threading: Buyer is entity_backed, so every bid / arbitration-claim /
transport call is made with make_buyer_headers(buyer_id) carrying the real
Buyer.id. Seller-owned writes use make_seller_headers(seller_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import make_admin_headers, make_buyer_headers, make_seller_headers
from . import factories as f


# ─── Tier 0: primitive creators (each returns the created entity dict) ──────
def create_sale(api, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.create_sale(f.create_sale_payload(**overrides), admin_headers))


def create_lane(api, sale_id, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.create_lane(f.create_lane_payload(sale_id, **overrides), admin_headers))


def create_seller(api, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.create_seller(f.create_seller_payload(**overrides), admin_headers))


def create_buyer(api, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.create_buyer(f.create_buyer_payload(**overrides), admin_headers))


def create_carrier(api, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.create_carrier(f.create_carrier_payload(**overrides), admin_headers))


def create_consignment(api, sale_id, seller_id, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(
        api.create_consignment(f.create_consignment_payload(sale_id, seller_id, **overrides), admin_headers)
    )


def create_condition_report(api, consignment_id, admin_headers=None, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(
        api.create_condition_report(f.create_condition_report_payload(consignment_id, **overrides), admin_headers)
    )


def catalog_consignment(api, consignment_id, admin_headers=None, reserve_price_cents=0,
                        floor_price_cents=0, **overrides):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(
        api.catalog_consignment(
            consignment_id, f.catalog_payload(reserve_price_cents, floor_price_cents, **overrides), admin_headers
        )
    )


# ─── Tier 1: cataloged consignment ──────────────────────────────────────────
def make_cataloged_consignment(api, sale_id, seller_id, admin_headers=None,
                               reserve_price_cents=0, floor_price_cents=0,
                               grade=4.0, announcements=None, title_status=None, **cons_overrides):
    """Submitted consignment + condition report + catalog -> CATALOGED. Returns consignment dict
    (post-catalog) plus the condition report id via key '_condition_report_id'."""
    admin_headers = admin_headers or make_admin_headers()
    cons_kwargs = dict(cons_overrides)
    if title_status is not None:
        cons_kwargs["title_status"] = title_status
    cons = create_consignment(api, sale_id, seller_id, admin_headers, **cons_kwargs)
    cr_kwargs = {"grade": grade}
    if announcements is not None:
        cr_kwargs["announcements"] = announcements
    cr = create_condition_report(api, cons["id"], admin_headers, **cr_kwargs)
    cataloged = catalog_consignment(api, cons["id"], admin_headers, reserve_price_cents, floor_price_cents)
    cataloged["_condition_report_id"] = cr["id"]
    return cataloged


# ─── Tier 1: run-listed lot in a (not-yet-started) sale ─────────────────────
def make_scheduled_lot(api, sale_id, consignment_id, lane_id, admin_headers=None,
                       run_number=1, slot_start_minute=0, slot_end_minute=10,
                       starting_bid_cents=400000, **overrides):
    """Create a lot (SCHEDULED) for a cataloged consignment. Cascades consignment -> RUN_LISTED."""
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(
        api.create_lot(
            f.create_lot_payload(sale_id, consignment_id, lane_id, run_number,
                                 slot_start_minute, slot_end_minute, starting_bid_cents, **overrides),
            admin_headers,
        )
    )


def open_and_start_sale(api, sale_id, admin_headers=None):
    """DRAFT -> OPEN -> RUNNING (activates lanes)."""
    admin_headers = admin_headers or make_admin_headers()
    get_success_data(api.open_sale(sale_id, admin_headers))
    return get_success_data(api.start_sale(sale_id, admin_headers))


# ─── Tier 2: a running sale with one ACTIVE lane and one SCHEDULED lot ───────
def setup_running_sale_with_lot(api, admin_headers=None, reserve_price_cents=0,
                                floor_price_cents=0, starting_bid_cents=400000,
                                grade=4.0, announcements=None, title_status=None,
                                buyer_fee_schedule_code=None, seller_fee_pct=None):
    """Full preamble to a RUNNING sale with one ACTIVE lane and one SCHEDULED lot.

    Returns a dict with keys: sale, lane, seller, consignment, lot, condition_report_id.
    The sale is started AFTER the lot is created so the consignment can be cataloged
    and run-listed while the sale is still OPEN, then activated by start.
    """
    admin_headers = admin_headers or make_admin_headers()
    sale_kwargs = {}
    if buyer_fee_schedule_code is not None:
        sale_kwargs["buyer_fee_schedule_code"] = buyer_fee_schedule_code
    sale = create_sale(api, admin_headers, **sale_kwargs)
    lane = create_lane(api, sale["id"], admin_headers)
    seller_kwargs = {}
    if seller_fee_pct is not None:
        seller_kwargs["seller_fee_pct"] = seller_fee_pct
    seller = create_seller(api, admin_headers, **seller_kwargs)
    cons = make_cataloged_consignment(
        api, sale["id"], seller["id"], admin_headers,
        reserve_price_cents=reserve_price_cents, floor_price_cents=floor_price_cents,
        grade=grade, announcements=announcements, title_status=title_status,
    )
    lot = make_scheduled_lot(api, sale["id"], cons["id"], lane["id"], admin_headers,
                             starting_bid_cents=starting_bid_cents)
    open_and_start_sale(api, sale["id"], admin_headers)
    return {
        "sale": sale,
        "lane": lane,
        "seller": seller,
        "consignment": cons,
        "lot": lot,
        "condition_report_id": cons["_condition_report_id"],
    }


# ─── Tier 3: a lot with bidding OPEN, plus helpers to place bids ────────────
def open_bidding(api, lot_id, admin_headers=None):
    """SCHEDULED -> BIDDING_OPEN. Returns the lot dict (carrying the current version)."""
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.open_bidding(lot_id, admin_headers))


def current_lot_version(api, lot_id, admin_headers=None):
    admin_headers = admin_headers or make_admin_headers()
    return get_success_data(api.get_lot(lot_id, admin_headers))["version"]


def place_bid(api, lot_id, buyer_id, expected_lot_version, bid_type="LIVE",
              amount_cents=400000, channel="LANE"):
    """Place a bid as the owning buyer (entity_backed identity threaded in)."""
    return api.place_bid(
        lot_id,
        f.place_bid_payload(buyer_id, expected_lot_version, bid_type, amount_cents, channel),
        make_buyer_headers(buyer_id),
    )


def place_bid_ok(api, lot_id, buyer_id, expected_lot_version, bid_type="LIVE",
                 amount_cents=400000, channel="LANE"):
    """Place a bid and require 2xx; returns the appended Bid dict."""
    return get_success_data(place_bid(api, lot_id, buyer_id, expected_lot_version, bid_type, amount_cents, channel))


def setup_lot_bidding_open(api, admin_headers=None, **sale_overrides):
    """Running sale with one ACTIVE lane, one lot moved to BIDDING_OPEN.

    Returns the dict from setup_running_sale_with_lot plus 'lot_open' (the
    open-bidding response, carrying the initialized version) under key 'lot'.
    """
    admin_headers = admin_headers or make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin_headers, **sale_overrides)
    ctx["lot"] = open_bidding(api, ctx["lot"]["id"], admin_headers)
    return ctx


# ─── Tier 3: hammer a lot SOLD and surface its settlement ───────────────────
def get_settlement_for_lot(api, lot_id, admin_headers=None):
    admin_headers = admin_headers or make_admin_headers()
    data, _ = _list(api.list_settlements(admin_headers, params={"lot_id": lot_id}))
    assert data, f"No settlement found for lot {lot_id}"
    return data[0]


def get_gate_pass_for_settlement(api, settlement_id, admin_headers=None):
    admin_headers = admin_headers or make_admin_headers()
    data, _ = _list(api.list_gate_passes(admin_headers, params={"settlement_id": settlement_id}))
    assert data, f"No gate pass found for settlement {settlement_id}"
    return data[0]


def _list(response):
    body = get_success_data(response)
    # list endpoints return the array directly in data
    assert isinstance(body, list), f"Expected list data, got {type(body)}"
    return body, None


def setup_hammered_lot(api, admin_headers=None, buyer=None, reserve_price_cents=0,
                       floor_price_cents=0, starting_bid_cents=400000,
                       winning_amount_cents=800000, channel="LANE",
                       buyer_fee_schedule_code=None, seller_fee_pct=None,
                       grade=4.0, announcements=None, credit_limit_cents=5_000_000):
    """Drive one lot all the way to HAMMERED (outcome SOLD), creating its settlement.

    A single buyer places a winning PROXY bid that clears at the standing price.
    Returns a dict with keys: sale, lane, seller, buyer, consignment, lot
    (post-hammer), settlement, condition_report_id.
    """
    admin_headers = admin_headers or make_admin_headers()
    ctx = setup_running_sale_with_lot(
        api, admin_headers,
        reserve_price_cents=reserve_price_cents, floor_price_cents=floor_price_cents,
        starting_bid_cents=starting_bid_cents, grade=grade, announcements=announcements,
        buyer_fee_schedule_code=buyer_fee_schedule_code, seller_fee_pct=seller_fee_pct,
    )
    if buyer is None:
        buyer = create_buyer(api, admin_headers, credit_limit_cents=credit_limit_cents)
    lot_open = open_bidding(api, ctx["lot"]["id"], admin_headers)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=winning_amount_cents, channel=channel)
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin_headers))
    lot_hammered = get_success_data(api.hammer_lot(ctx["lot"]["id"], admin_headers))
    settlement = get_settlement_for_lot(api, ctx["lot"]["id"], admin_headers)
    ctx.update({"buyer": buyer, "lot": lot_hammered, "settlement": settlement})
    return ctx


# ─── Tier 3: a two-proxy hammered lot (B1 wins over B2) ─────────────────────
def setup_two_proxy_hammered_lot(api, admin_headers=None, starting_bid_cents=600000,
                                 b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE",
                                 buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02,
                                 b1_credit=5_000_000, b2_credit=5_000_000,
                                 reserve_price_cents=0, floor_price_cents=0):
    """Two buyers (B1 top, B2 second) PROXY bid; clearing settles between them; hammer SOLD.

    Returns dict with keys: sale, lane, seller, b1, b2, consignment, lot, settlement,
    condition_report_id.
    """
    admin_headers = admin_headers or make_admin_headers()
    ctx = setup_running_sale_with_lot(
        api, admin_headers,
        reserve_price_cents=reserve_price_cents, floor_price_cents=floor_price_cents,
        starting_bid_cents=starting_bid_cents,
        buyer_fee_schedule_code=buyer_fee_schedule_code, seller_fee_pct=seller_fee_pct,
    )
    b1 = create_buyer(api, admin_headers, dealer_name="Buyer B1", credit_limit_cents=b1_credit)
    b2 = create_buyer(api, admin_headers, dealer_name="Buyer B2", credit_limit_cents=b2_credit)
    lot_open = open_bidding(api, ctx["lot"]["id"], admin_headers)
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=b1_ceiling, channel=channel)
    v1 = current_lot_version(api, ctx["lot"]["id"], admin_headers)
    place_bid_ok(api, ctx["lot"]["id"], b2["id"], v1,
                 bid_type="PROXY", amount_cents=b2_ceiling, channel=channel)
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin_headers))
    lot_hammered = get_success_data(api.hammer_lot(ctx["lot"]["id"], admin_headers))
    settlement = get_settlement_for_lot(api, ctx["lot"]["id"], admin_headers)
    ctx.update({"b1": b1, "b2": b2, "lot": lot_hammered, "settlement": settlement})
    return ctx


# ─── Tier 4: paid settlement + open arbitration claim by winning buyer ──────
def setup_paid_settlement_with_open_claim(api, admin_headers=None, claimed_cents=100000,
                                          reason_code="MECHANICAL", **two_proxy_overrides):
    """Two-proxy hammer -> record payment -> winning buyer (B1) opens an arbitration claim.

    Returns the two-proxy ctx plus 'claim' (the OPEN claim dict).
    """
    admin_headers = admin_headers or make_admin_headers()
    ctx = setup_two_proxy_hammered_lot(api, admin_headers, **two_proxy_overrides)
    get_success_data(api.record_payment(ctx["settlement"]["id"], admin_headers))
    claim = get_success_data(
        api.create_arbitration_claim(
            f.create_arbitration_claim_payload(ctx["lot"]["id"], ctx["b1"]["id"], reason_code, claimed_cents),
            make_buyer_headers(ctx["b1"]["id"]),
        )
    )
    ctx["claim"] = claim
    return ctx


# ─── Tier 5: cleared settlement (payment + title) with auto-issued gate pass ─
def setup_cleared_settlement(api, admin_headers=None, title_first=False, **hammer_overrides):
    """Hammered lot -> record payment + record title -> settlement CLEARED, gate pass ISSUED.

    Returns the setup_hammered_lot ctx plus 'gate_pass' (the auto-issued gate pass dict)
    and refreshes 'settlement' to the cleared state.
    """
    admin_headers = admin_headers or make_admin_headers()
    ctx = setup_hammered_lot(api, admin_headers, **hammer_overrides)
    sid = ctx["settlement"]["id"]
    if title_first:
        get_success_data(api.record_title(sid, admin_headers))
        cleared = get_success_data(api.record_payment(sid, admin_headers))
    else:
        get_success_data(api.record_payment(sid, admin_headers))
        cleared = get_success_data(api.record_title(sid, admin_headers))
    ctx["settlement"] = cleared
    ctx["gate_pass"] = get_gate_pass_for_settlement(api, sid, admin_headers)
    return ctx
