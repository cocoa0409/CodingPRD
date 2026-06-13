"""Cross-cutting domain helpers: roll-up counters, balance recompute,
standing-high bid resolution.
"""
import db


def recompute_sale_lot_count(auction_sale_id):
    """lot_count = count of Lots in this sale with sale_status != WITHDRAWN."""
    sale = db.auction_sales.get(auction_sale_id)
    if sale is None:
        return
    count = sum(
        1 for lot in db.lots.values()
        if lot["auction_sale_id"] == auction_sale_id and lot["sale_status"] != "WITHDRAWN"
    )
    sale["lot_count"] = count


def recompute_consignment_lot_count(consignment_id):
    """lot_count = count of Lots for this consignment with sale_status != WITHDRAWN."""
    cons = db.consignments.get(consignment_id)
    if cons is None:
        return
    count = sum(
        1 for lot in db.lots.values()
        if lot["consignment_id"] == consignment_id and lot["sale_status"] != "WITHDRAWN"
    )
    cons["lot_count"] = count


def recompute_bidder_outstanding(bidder_id):
    """outstanding_balance_cents = sum of total_due_cents over this bidder's
    Invoices in status ISSUED (PRD §3.1)."""
    bidder = db.bidders.get(bidder_id)
    if bidder is None:
        return
    total = sum(
        inv["total_due_cents"] for inv in db.invoices.values()
        if inv["bidder_id"] == bidder_id and inv["status"] == "ISSUED"
    )
    bidder["outstanding_balance_cents"] = total


def lot_bids(lot_id):
    return [b for b in db.bids.values() if b["lot_id"] == lot_id]


def standing_high_bid(lot_id, statuses=("ACCEPTED",)):
    """The standing-high bid among bids with status in `statuses`.

    Greatest amount_cents; ties broken by EARLIEST created_at (ASC), then by
    creation sequence — never by id (SCAFFOLD calc standing_high_bid /
    PRD §3.5). Returns the bid record or None.
    """
    candidates = [b for b in lot_bids(lot_id) if b["status"] in statuses]
    if not candidates:
        return None
    # max amount; tie -> earliest created_at -> earliest _seq.
    candidates.sort(key=lambda b: (-b["amount_cents"], b.get("created_at", ""), b.get("_seq", 0)))
    return candidates[0]


def standing_high_amount(lot_id, statuses=("ACCEPTED",)):
    """The standing-high amount among bids with status in `statuses`; 0 if none."""
    bid = standing_high_bid(lot_id, statuses)
    return bid["amount_cents"] if bid else 0
