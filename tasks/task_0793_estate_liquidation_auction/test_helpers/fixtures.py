"""Composite setup helpers for the Estate-Liquidation Auction API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty database before every
test). Setup calls use the lenient get_success_data() so setup failures surface
as clear "Setup failed" errors. Ownership-gated Buyer calls always thread the
real Buyer.id via make_buyer_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import operator_headers, anonymous_headers, make_buyer_headers
from .factories import (
    create_estate_payload, create_lot_payload, create_photo_payload,
    create_buyer_payload, create_bid_payload, create_pickup_window_payload,
    create_dispute_payload,
)

OP = operator_headers()
ANON = anonymous_headers()


# --------------------------------------------------------------------------
# Low-level building blocks
# --------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, OP))


def new_estate(api, **overrides):
    return get_success_data(api.create_estate(create_estate_payload(**overrides), OP))


def new_registered_buyer(api, display_name="Buyer", email="buyer@x.com"):
    return get_success_data(
        api.create_buyer(create_buyer_payload(display_name=display_name, email=email), ANON))


def new_verified_buyer(api, display_name="Buyer", email="buyer@x.com"):
    buyer = new_registered_buyer(api, display_name, email)
    return get_success_data(api.verify_buyer(buyer["id"], OP))


def new_lot(api, estate_id, **overrides):
    """POST /lots only — returns a DRAFT lot with no photo."""
    return get_success_data(api.create_lot(create_lot_payload(estate_id, **overrides), OP))


def attach_photo(api, lot_id, **overrides):
    return get_success_data(api.create_photo(create_photo_payload(lot_id, **overrides), OP))


def new_draft_lot_with_photo(api, estate_id, **overrides):
    """DRAFT lot that already carries one photo (ready to be cataloged)."""
    lot = new_lot(api, estate_id, **overrides)
    attach_photo(api, lot["id"])
    return lot


def new_listed_lot(api, estate_id, **overrides):
    """Create lot -> photo -> CATALOGED -> LISTED. Returns the LISTED lot."""
    lot = new_draft_lot_with_photo(api, estate_id, **overrides)
    get_success_data(api.update_lot(lot["id"], {"status": "CATALOGED"}, OP))
    return get_success_data(api.update_lot(lot["id"], {"status": "LISTED"}, OP))


def lot_version(api, lot_id):
    return get_success_data(api.get_lot(lot_id, OP))["version"]


def bid_on(api, lot_id, buyer_id, amount, version=None):
    """Place a (expected-to-succeed) bid, auto-capturing the current lot version."""
    if version is None:
        version = lot_version(api, lot_id)
    resp = api.create_bid(
        create_bid_payload(lot_id, buyer_id, amount, version),
        make_buyer_headers(buyer_id))
    return get_success_data(resp)


def first_order(api, **params):
    """Return the first Order matching the filter params (Operator read)."""
    data = get_success_data(api.list_orders(OP, params=params or None))
    assert data, f"Setup failed: no order found for {params}"
    return data[0]


def get_order(api, order_id):
    return get_success_data(api.get_order(order_id, OP))


def pay_order_full(api, order, buyer_id):
    """Pay an order in full (amount_cents == total_cents)."""
    resp = api.pay_order(order["id"], {"amount_cents": order["total_cents"]},
                         make_buyer_headers(buyer_id))
    return get_success_data(resp)


def new_pickup_window(api, estate_id, starts_at, ends_at, capacity, **overrides):
    return get_success_data(
        api.create_pickup_window(
            create_pickup_window_payload(estate_id, starts_at, ends_at, capacity,
                                         **overrides), OP))


# --------------------------------------------------------------------------
# Tier 2/3: single-buyer sale lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_live_lot(api, starting_bid=10000, reserve=None, condition_grade="B",
                   estate_overrides=None):
    """Active estate + one SELLING lot + one verified buyer (no bid yet).
    Returns dict(estate, buyer, lot)."""
    estate = new_estate(api, **(estate_overrides or {}))
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    lot_kwargs = {"starting_bid_cents": starting_bid, "condition_grade": condition_grade}
    if reserve is not None:
        lot_kwargs["reserve_cents"] = reserve
    lot = new_listed_lot(api, estate["id"], **lot_kwargs)
    get_success_data(api.open_estate(estate["id"], OP))
    return {"estate": estate, "buyer": buyer, "lot": lot}


def setup_won_lot(api, amount=10000, starting_bid=None, reserve=None,
                  condition_grade="B"):
    """Active estate, one verified buyer who has placed the winning bid `amount`
    on a SELLING lot (estate still LIVE, not yet closed).
    Returns dict(estate, buyer, lot)."""
    s = setup_live_lot(api, starting_bid=starting_bid or amount, reserve=reserve,
                       condition_grade=condition_grade)
    bid_on(api, s["lot"]["id"], s["buyer"]["id"], amount)
    return s


def setup_closed_with_order(api, amount=10000):
    """Buyer wins one lot, estate closed -> order created UNPAID/PENDING.
    Returns dict(estate, buyer, lot, order)."""
    s = setup_won_lot(api, amount=amount)
    get_success_data(api.close_estate(s["estate"]["id"], OP))
    order = first_order(api, buyer_id=s["buyer"]["id"])
    s["order"] = order
    return s


def setup_paid_order(api, amount=10000):
    """Buyer wins one lot, estate closed, order PAID in full.
    Returns dict(estate, buyer, lot, order) with the order refreshed to PAID."""
    s = setup_closed_with_order(api, amount=amount)
    pay_order_full(api, s["order"], s["buyer"]["id"])
    s["order"] = get_order(api, s["order"]["id"])
    return s


def setup_settled_order(api, amount=10000):
    """Buyer wins one lot, estate closed, order PAID, estate SETTLED.
    Returns dict(estate, buyer, lot, order)."""
    s = setup_paid_order(api, amount=amount)
    s["estate"] = get_success_data(api.settle_estate(s["estate"]["id"], OP))
    return s


# --------------------------------------------------------------------------
# Tier 4/5: multi-entity composite scenarios
# --------------------------------------------------------------------------
def setup_provisional_vs_final(api):
    """Two verified buyers, two lots (10000, 5000), both won at close; O1 PAID,
    O2 left UNPAID. Estate CLOSED (not yet settled).
    Returns dict(estate, b1, b2, l1, l2, o1, o2)."""
    estate = new_estate(api)
    b1 = new_verified_buyer(api, "B1", "b1@x.com")
    b2 = new_verified_buyer(api, "B2", "b2@x.com")
    l1 = new_listed_lot(api, estate["id"], starting_bid_cents=10000)
    l2 = new_listed_lot(api, estate["id"], starting_bid_cents=5000, condition_grade="C")
    get_success_data(api.open_estate(estate["id"], OP))
    bid_on(api, l1["id"], b1["id"], 10000)
    bid_on(api, l2["id"], b2["id"], 5000)
    get_success_data(api.close_estate(estate["id"], OP))
    o1 = first_order(api, buyer_id=b1["id"])
    o2 = first_order(api, buyer_id=b2["id"])
    pay_order_full(api, o1, b1["id"])
    return {"estate": estate, "b1": b1, "b2": b2, "l1": l1, "l2": l2,
            "o1": get_order(api, o1["id"]), "o2": get_order(api, o2["id"])}


def setup_gross_vs_net(api):
    """One verified buyer wins in two estates. Ea order PAID (12690), Eb order
    UNPAID (25380). Both estates CLOSED.
    Returns dict(ea, eb, buyer, oa, ob)."""
    ea = new_estate(api, seller_name="Ea", seller_email="ea@e.com")
    eb = new_estate(api, seller_name="Eb", seller_email="eb@e.com")
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    la = new_listed_lot(api, ea["id"], starting_bid_cents=10000, condition_grade="A")
    get_success_data(api.open_estate(ea["id"], OP))
    bid_on(api, la["id"], buyer["id"], 10000)
    get_success_data(api.close_estate(ea["id"], OP))
    oa = first_order(api, estate_id=ea["id"])
    pay_order_full(api, oa, buyer["id"])
    lb = new_listed_lot(api, eb["id"], starting_bid_cents=20000, condition_grade="A")
    get_success_data(api.open_estate(eb["id"], OP))
    bid_on(api, lb["id"], buyer["id"], 20000)
    get_success_data(api.close_estate(eb["id"], OP))
    ob = first_order(api, estate_id=eb["id"])
    return {"ea": ea, "eb": eb, "buyer": buyer,
            "oa": get_order(api, oa["id"]), "ob": get_order(api, ob["id"])}


def setup_lot_with_high_bid(api, starting_bid=10000, first_bid=10000):
    """Live estate, lot SELLING with a standing high bid from B1, plus a second
    verified buyer B2 available for the trigger bid.
    Returns dict(estate, lot, b1, b2)."""
    estate = new_estate(api)
    b1 = new_verified_buyer(api, "B1", "b1@x.com")
    b2 = new_verified_buyer(api, "B2", "b2@x.com")
    lot = new_listed_lot(api, estate["id"], starting_bid_cents=starting_bid)
    get_success_data(api.open_estate(estate["id"], OP))
    bid_on(api, lot["id"], b1["id"], first_bid)
    return {"estate": estate, "lot": lot, "b1": b1, "b2": b2}


def setup_sold_lot_extra_buyer(api, first_bid=2000):
    """Estate CLOSED with L1 SOLD (B1's winning bid == first_bid); a second
    verified buyer B2 is available for a trigger bid on the no-longer-SELLING lot.
    Returns dict(estate, lot, b1, b2)."""
    estate = new_estate(api)
    b1 = new_verified_buyer(api, "B1", "b1@x.com")
    b2 = new_verified_buyer(api, "B2", "b2@x.com")
    lot = new_listed_lot(api, estate["id"], starting_bid_cents=first_bid)
    get_success_data(api.open_estate(estate["id"], OP))
    bid_on(api, lot["id"], b1["id"], first_bid)
    get_success_data(api.close_estate(estate["id"], OP))
    lot = get_success_data(api.get_lot(lot["id"], OP))
    return {"estate": estate, "lot": lot, "b1": b1, "b2": b2}


def setup_three_lot_order(api):
    """One verified buyer wins three lots each at hammer 550 -> one order,
    subtotal 1650. Estate CLOSED.
    Returns dict(estate, buyer, order)."""
    estate = new_estate(api)
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    lots = [new_listed_lot(api, estate["id"], starting_bid_cents=550)
            for _ in range(3)]
    get_success_data(api.open_estate(estate["id"], OP))
    for lot in lots:
        bid_on(api, lot["id"], buyer["id"], 550)
    get_success_data(api.close_estate(estate["id"], OP))
    order = first_order(api, buyer_id=buyer["id"])
    return {"estate": estate, "buyer": buyer, "order": get_order(api, order["id"])}


def setup_paid_order_with_extra_passed_lot(api):
    """B1 wins L1 (order O1 PAID). A separate lot Lx (listed, no bid) PASSES at
    close and is NOT part of O1.lot_ids.
    Returns dict(estate, buyer, l1, lx, order)."""
    estate = new_estate(api)
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    l1 = new_listed_lot(api, estate["id"], starting_bid_cents=10000)
    lx = new_listed_lot(api, estate["id"], starting_bid_cents=5000, condition_grade="C")
    get_success_data(api.open_estate(estate["id"], OP))
    bid_on(api, l1["id"], buyer["id"], 10000)
    get_success_data(api.close_estate(estate["id"], OP))
    order = first_order(api, buyer_id=buyer["id"])
    pay_order_full(api, order, buyer["id"])
    return {"estate": estate, "buyer": buyer, "l1": l1, "lx": lx,
            "order": get_order(api, order["id"])}


def setup_scheduled_pickup(api, capacity=5):
    """Paid order booked into a pickup window (SCHEDULED). Returns
    dict(estate, buyer, lot, order, window)."""
    s = setup_paid_order(api)
    window = new_pickup_window(api, s["estate"]["id"],
                              "2026-03-25T09:00:00Z", "2026-03-25T12:00:00Z",
                              capacity)
    get_success_data(api.schedule_pickup(s["order"]["id"],
                                        {"pickup_window_id": window["id"]},
                                        make_buyer_headers(s["buyer"]["id"])))
    s["window"] = get_success_data(
        api.list_estate_pickup_windows(s["estate"]["id"], OP))[0]
    s["order"] = get_order(api, s["order"]["id"])
    return s


def setup_capacity_one_window(api):
    """Two buyers, two paid orders; a capacity-1 window with O1 already booked
    (booked_count 1 == capacity). Returns dict(estate, b1, b2, o1, o2, window)."""
    estate = new_estate(api)
    b1 = new_verified_buyer(api, "B1", "b1@x.com")
    b2 = new_verified_buyer(api, "B2", "b2@x.com")
    l1 = new_listed_lot(api, estate["id"], starting_bid_cents=10000)
    l2 = new_listed_lot(api, estate["id"], starting_bid_cents=10000)
    get_success_data(api.open_estate(estate["id"], OP))
    bid_on(api, l1["id"], b1["id"], 10000)
    bid_on(api, l2["id"], b2["id"], 10000)
    get_success_data(api.close_estate(estate["id"], OP))
    o1 = first_order(api, buyer_id=b1["id"])
    o2 = first_order(api, buyer_id=b2["id"])
    pay_order_full(api, o1, b1["id"])
    pay_order_full(api, o2, b2["id"])
    window = new_pickup_window(api, estate["id"],
                              "2026-03-25T09:00:00Z", "2026-03-25T10:00:00Z", 1)
    get_success_data(api.schedule_pickup(o1["id"], {"pickup_window_id": window["id"]},
                                        make_buyer_headers(b1["id"])))
    return {"estate": estate, "b1": b1, "b2": b2,
            "o1": get_order(api, o1["id"]), "o2": get_order(api, o2["id"]),
            "window": window}


def setup_dispute(api, status=None, settled=False):
    """Paid order + filed dispute. Optionally advance it to a target status and
    optionally settle the estate first.
    Returns dict(estate, buyer, lot, order, dispute)."""
    if settled:
        s = setup_settled_order(api)
    else:
        s = setup_paid_order(api)
    dispute = get_success_data(
        api.create_dispute(create_dispute_payload(s["order"]["id"], s["lot"]["id"]),
                           make_buyer_headers(s["buyer"]["id"])))
    if status in ("UNDER_REVIEW", "NEEDS_INFO"):
        dispute = get_success_data(
            api.update_dispute(dispute["id"], {"status": "UNDER_REVIEW"}, OP))
    if status == "NEEDS_INFO":
        dispute = get_success_data(
            api.update_dispute(dispute["id"], {"status": "NEEDS_INFO"}, OP))
    s["dispute"] = dispute
    return s


def setup_live_estate_with_draft_lot(api):
    """Estate opened LIVE (via a listed L1); a second lot L2 remains DRAFT
    (photographed). Returns dict(estate, l1, l2)."""
    estate = new_estate(api)
    l1 = new_listed_lot(api, estate["id"], starting_bid_cents=10000)
    l2 = new_draft_lot_with_photo(api, estate["id"], starting_bid_cents=5000)
    get_success_data(api.open_estate(estate["id"], OP))
    return {"estate": estate, "l1": l1, "l2": l2}


def setup_estate_with_abutting_windows(api):
    """Estate with W1 [09:00,12:00) and W2 [12:00,15:00) created (abutting,
    allowed under half-open). Returns dict(estate, w1, w2)."""
    estate = new_estate(api)
    w1 = new_pickup_window(api, estate["id"], "2026-03-25T09:00:00Z",
                          "2026-03-25T12:00:00Z", 3)
    w2 = new_pickup_window(api, estate["id"], "2026-03-25T12:00:00Z",
                          "2026-03-25T15:00:00Z", 3)
    return {"estate": estate, "w1": w1, "w2": w2}


def setup_buyer_holds_abutting_window(api):
    """One buyer wins+pays a lot in each of two estates. Wa [09:00,12:00] in Ea,
    Wb [12:00,15:00] in Eb. Oa is booked into Wa (SCHEDULED); Ob is PAID/PENDING.
    Returns dict(ea, eb, buyer, oa, ob, wa, wb)."""
    ea = new_estate(api, seller_name="Ea", seller_email="ea@e.com")
    eb = new_estate(api, seller_name="Eb", seller_email="eb@e.com")
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    la = new_listed_lot(api, ea["id"], starting_bid_cents=10000)
    get_success_data(api.open_estate(ea["id"], OP))
    bid_on(api, la["id"], buyer["id"], 10000)
    get_success_data(api.close_estate(ea["id"], OP))
    oa = first_order(api, estate_id=ea["id"])
    pay_order_full(api, oa, buyer["id"])
    lb = new_listed_lot(api, eb["id"], starting_bid_cents=10000)
    get_success_data(api.open_estate(eb["id"], OP))
    bid_on(api, lb["id"], buyer["id"], 10000)
    get_success_data(api.close_estate(eb["id"], OP))
    ob = first_order(api, estate_id=eb["id"])
    pay_order_full(api, ob, buyer["id"])
    wa = new_pickup_window(api, ea["id"], "2026-03-25T09:00:00Z",
                          "2026-03-25T12:00:00Z", 5)
    wb = new_pickup_window(api, eb["id"], "2026-03-25T12:00:00Z",
                          "2026-03-25T15:00:00Z", 5)
    get_success_data(api.schedule_pickup(oa["id"], {"pickup_window_id": wa["id"]},
                                        make_buyer_headers(buyer["id"])))
    return {"ea": ea, "eb": eb, "buyer": buyer,
            "oa": get_order(api, oa["id"]), "ob": get_order(api, ob["id"]),
            "wa": wa, "wb": wb}
