"""Derived values, rollups, posture gating and the documented calculations."""
from datetime import timedelta
from decimal import Decimal

from core import (
    ApiError, FEE_RATE_TIER_1, FEE_RATE_TIER_2, FEE_RATE_TIER_3,
    FEE_TIER_1_CEILING_CENTS, FEE_TIER_2_CEILING_CENTS, FMV_DE_MINIMIS_CENTS,
    MATERIAL_VARIANCE_THRESHOLD_CENTS, PROCESSING_FEE_FLAT_CENTS,
    clock_dt, db, parse_dt, round_half_up, rows, touch,
)


# ---------------------------------------------------------------- posture
def posture_of(event):
    if event["status"] == "CLOSED":
        return "FROZEN"
    for run in db.runs.values():
        if run["event_id"] == event["id"] and run["status"] == "FINALIZED":
            return "FROZEN"
    if event["status"] == "SETTLING":
        return "RESTRICTED"
    return "OPEN"


def event_view(event):
    out = {k: v for k, v in event.items() if not k.startswith("_")}
    out["posture"] = posture_of(event)
    return out


def gate(event, restricted=False):
    """Posture gate consulted on every mutation of a child of the event."""
    p = posture_of(event)
    if p == "FROZEN":
        raise ApiError("ERR_EVENT_FROZEN", "the owning event is frozen")
    if restricted and p == "RESTRICTED":
        raise ApiError("ERR_EVENT_RESTRICTED", "the owning event is restricted")


# ---------------------------------------------------------------- rollups
def recompute_table(table, bump=True):
    reserved = 0
    for order in db.orders.values():
        if order["table_id"] != table["id"]:
            continue
        if order["payment_status"] == "REFUNDED":
            continue
        if order["seating_status"] == "RELEASED":
            continue
        reserved += order["seat_count"]
    table["seats_reserved"] = reserved
    table["status"] = "AVAILABLE" if reserved < table["seat_count"] else "SOLD_OUT"
    if bump:
        touch(table)


def recompute_bidder(bidder, bump=True):
    total = 0
    for inv in db.invoices.values():
        if inv["bidder_id"] == bidder["id"] and inv["status"] in (
                "OPEN", "PENDING_PAYMENT", "PARTIALLY_PAID"):
            total += inv["balance_due_cents"]
    bidder["outstanding_balance_cents"] = total
    if bump:
        touch(bidder)


def recompute_sponsor_ads(sponsor, bump=True):
    sponsor["placed_ad_count"] = sum(
        1 for ad in db.ads.values()
        if ad["sponsor_id"] == sponsor["id"] and ad["status"] == "PLACED")
    if bump:
        touch(sponsor)


def event_gross_collected(event_id):
    total = 0
    for pay in db.payments.values():
        if pay["status"] != "CAPTURED":
            continue
        inv = db.invoices.get(pay["invoice_id"])
        if inv is not None and inv["event_id"] == event_id:
            total += pay["amount_cents"]
    return total


def event_unpaid_invoices(event_id):
    return sum(1 for inv in db.invoices.values()
               if inv["event_id"] == event_id
               and inv["status"] in ("PENDING_PAYMENT", "PARTIALLY_PAID"))


def event_open_lots(event_id):
    return sum(1 for it in db.items.values()
               if it["event_id"] == event_id and it["listing_status"] == "OPEN")


def event_match_awarded(event_id):
    return sum(g["match_cents"] for g in db.paddles.values()
               if g["event_id"] == event_id)


def recompute_event(event, bump=True):
    eid = event["id"]
    event["match_awarded_cents"] = event_match_awarded(eid)
    event["gross_collected_cents"] = event_gross_collected(eid)
    event["open_lot_count"] = event_open_lots(eid)
    event["unpaid_invoice_count"] = event_unpaid_invoices(eid)
    if bump:
        touch(event)


# ---------------------------------------------------------------- tickets
def price_ticket_order(event, table, order_type, seat_count):
    start = parse_dt(event["event_start_utc"])
    cutoff = start - timedelta(days=30)
    early = clock_dt() <= cutoff

    if order_type == "TABLE":
        base = table["table_price_cents"]
        units = 1
    else:
        base = table["seat_price_cents"]
        units = seat_count

    if not early:
        rate = Decimal("0")
    elif order_type == "TABLE":
        rate = Decimal("0.15")
    else:
        rate = Decimal("0.10")

    unit_price = round_half_up(Decimal(base) * (Decimal(1) - rate))
    subtotal = unit_price * units
    benefit = 7500 * seat_count
    return {
        "unit_price_cents": unit_price,
        "subtotal_cents": subtotal,
        "benefit_value_cents": benefit,
        "early_bird_applied": early,
    }


# ---------------------------------------------------------------- auction
def active_bids(item_id):
    out = [b for b in db.bids.values()
           if b["item_id"] == item_id and b["status"] == "ACTIVE"]
    out.sort(key=lambda b: (-b["effective_max_cents"], b["created_at"], b["_seq"]))
    return out


def valuation(item, variant):
    active = active_bids(item["id"])
    if not active:
        return {"amount_cents": 0, "active_bid_count": 0, "source_bid_id": None}
    top = active[0]
    if variant == "PLACED_AMOUNT":
        amount = top["amount_cents"]
    else:
        if len(active) == 1:
            amount = top["amount_cents"]
        else:
            runner = active[1]["effective_max_cents"]
            amount = min(top["effective_max_cents"],
                         runner + item["min_increment_cents"])
    return {"amount_cents": amount, "active_bid_count": len(active),
            "source_bid_id": top["id"]}


def recompute_leading(item):
    item["current_leading_amount_cents"] = valuation(item, "PROXY_SETTLED")["amount_cents"]


# ---------------------------------------------------------------- invoices
def fee_rate(subtotal):
    if subtotal < FEE_TIER_1_CEILING_CENTS:
        return FEE_RATE_TIER_1
    if subtotal < FEE_TIER_2_CEILING_CENTS:
        return FEE_RATE_TIER_2
    return FEE_RATE_TIER_3


def recompute_invoice(invoice, bump=True):
    lines = [l for l in invoice["line_items"] if l["line_type"] != "PROCESSING_FEE"]
    subtotal = sum(l["amount_cents"] for l in lines)
    fee = round_half_up(Decimal(subtotal) * fee_rate(subtotal)) + PROCESSING_FEE_FLAT_CENTS
    invoice["line_subtotal_cents"] = subtotal
    invoice["processing_fee_cents"] = fee
    if invoice["cover_processing_fee"]:
        total = subtotal + fee
        lines = lines + [{"line_type": "PROCESSING_FEE", "source_id": None,
                          "amount_cents": fee}]
    else:
        total = subtotal
    invoice["line_items"] = lines
    invoice["total_due_cents"] = total
    paid = sum(p["amount_cents"] for p in db.payments.values()
               if p["invoice_id"] == invoice["id"] and p["status"] == "CAPTURED")
    invoice["amount_paid_cents"] = paid
    invoice["balance_due_cents"] = total - paid
    if bump:
        touch(invoice)


def append_line(invoice, line_type, source_id, amount_cents):
    invoice["line_items"].append({"line_type": line_type, "source_id": source_id,
                                  "amount_cents": amount_cents})


# ---------------------------------------------------------------- receipts
def receipt_amounts(invoice):
    benefit = 0
    deductible = 0
    for line in invoice["line_items"]:
        if line["line_type"] == "AUCTION_ITEM":
            item = db.items.get(line["source_id"])
            fmv = item["estimated_fmv_cents"] if item else 0
            benefit += fmv
            deductible += max(0, line["amount_cents"] - fmv)
        elif line["line_type"] == "TICKET":
            order = db.orders.get(line["source_id"])
            bv = order["benefit_value_cents"] if order else 0
            benefit += bv
            deductible += max(0, line["amount_cents"] - bv)
        else:
            deductible += line["amount_cents"]
    if benefit < FMV_DE_MINIMIS_CENTS:
        benefit = 0
        deductible = invoice["total_due_cents"]
    return benefit, deductible


# ---------------------------------------------------------------- pledges
def pledge_channel(event_id, basis):
    total = 0
    for p in db.pledges.values():
        if p["event_id"] != event_id:
            continue
        if basis == "BOOKED":
            if p["status"] in ("PROMISED", "PARTIALLY_FULFILLED", "FULFILLED"):
                total += p["total_amount_cents"]
        else:
            if p["status"] in ("PROMISED", "PARTIALLY_FULFILLED", "FULFILLED", "LAPSED"):
                total += p["received_amount_cents"]
    return total


def channel_tickets(event_id):
    return sum(o["subtotal_cents"] for o in db.orders.values()
               if o["event_id"] == event_id and o["payment_status"] in ("INVOICED", "PAID"))


def channel_auction(event_id):
    return sum(i["hammer_price_cents"] or 0 for i in db.items.values()
               if i["event_id"] == event_id and i["listing_status"] == "AWARDED")


def channel_paddle(event_id):
    return sum(g["level_cents"] for g in db.paddles.values()
               if g["event_id"] == event_id
               and g["settlement_status"] in ("INVOICED", "PAID"))


def channel_sponsorship(event_id):
    return sum(s["paid_amount_cents"] for s in db.sponsors.values()
               if s["event_id"] == event_id and s["status"] == "CONFIRMED")


def compute_run(run, event):
    eid = event["id"]
    tickets = channel_tickets(eid)
    auction = channel_auction(eid)
    paddle = channel_paddle(eid)
    pledge = pledge_channel(eid, run["revenue_basis"])
    sponsorship = channel_sponsorship(eid)
    expected = tickets + auction + paddle + pledge + sponsorship
    collected = event["gross_collected_cents"]
    variance = expected - collected
    run["channel_breakdown"] = [
        {"channel": "TICKETS", "expected_cents": tickets},
        {"channel": "AUCTION", "expected_cents": auction},
        {"channel": "PADDLE", "expected_cents": paddle},
        {"channel": "PLEDGE", "expected_cents": pledge},
        {"channel": "SPONSORSHIP", "expected_cents": sponsorship},
    ]
    run["expected_total_cents"] = expected
    run["collected_total_cents"] = collected
    run["variance_cents"] = variance
    run["is_material_variance"] = abs(variance) >= MATERIAL_VARIANCE_THRESHOLD_CENTS
