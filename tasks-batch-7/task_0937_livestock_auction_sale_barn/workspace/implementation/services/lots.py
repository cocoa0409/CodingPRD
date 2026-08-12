"""Lot weights, weight class and the extension arithmetic (PRD 3.4, 3.8)."""
import config
from money import D, q0, q1, q2
from store import db, get, touch


def lot_tickets(lot_id):
    return sorted([t for t in db["weigh_tickets"].values() if t["lot_id"] == lot_id],
                  key=lambda t: (t["ticket_seq"], t["_seq"]))


def governing_ticket(lot_id):
    """THE governing ticket: status CAPTURED with the highest ticket_seq.
    OPEN, VOIDED and SUPERSEDED tickets are excluded from the choice entirely.

    Adjudication of friction 11: this uniform reading governs on BOTH weigh
    bases. The PRD defines the governing ticket once, without qualifying it by
    weigh_basis, and applies the pencil-shrink percentage to "the governing
    ticket's net weight"; making the pencil variant govern off the FIRST
    captured ticket instead would contradict that sentence and would make the
    re-weigh path unobservable on a pencil-shrink consignment.
    """
    captured = [t for t in lot_tickets(lot_id) if t["status"] == "CAPTURED"]
    if not captured:
        return None
    return max(captured, key=lambda t: (t["ticket_seq"], -t["_seq"]))


def recompute_lot_weights(lot):
    """Copy the governing ticket's weights onto the lot and derive settle
    weight, average weight and weight class (PRD 3.4)."""
    consignment = get("consignments", lot["consignment_id"])
    ticket = governing_ticket(lot["id"])
    if ticket is None:
        lot["gross_weight_lb"] = None
        lot["tare_weight_lb"] = None
        lot["net_weight_lb"] = None
        lot["settle_weight_lb"] = None
        lot["avg_weight_lb"] = None
        lot["weight_class"] = "NONE"
        touch(lot)
        return lot

    lot["gross_weight_lb"] = ticket["gross_weight_lb"]
    lot["tare_weight_lb"] = ticket["tare_weight_lb"]
    lot["net_weight_lb"] = ticket["net_weight_lb"]

    net = D(ticket["net_weight_lb"])
    if consignment and consignment["weigh_basis"] == "PENCIL_SHRINK":
        shrink = D(consignment["pencil_shrink_pct"])
        settle = q0(net * (D(1) - shrink))
    else:
        settle = q0(net)
    lot["settle_weight_lb"] = settle
    lot["avg_weight_lb"] = q1(settle / D(lot["head_count"]))
    lot["weight_class"] = weight_class(settle, lot["avg_weight_lb"])
    touch(lot)
    return lot


def weight_class(settle_weight, avg_weight):
    if settle_weight is None:
        return "NONE"
    if D(avg_weight) < config.WEIGHT_CLASS_MEDIUM_MIN_LB:
        return "LIGHT"
    if D(avg_weight) < config.WEIGHT_CLASS_HEAVY_MIN_LB:
        return "MEDIUM"
    return "HEAVY"


def extension(bid_basis, unit_price, settle_weight_lb, head_count):
    """The dual-variant extension (PRD 3.8)."""
    price = D(unit_price)
    if bid_basis == "PER_CWT":
        weight = D(settle_weight_lb) if settle_weight_lb is not None else D(0)
        return q2(price * weight / D(100))
    return q2(price * D(head_count))


def lot_extension(lot, unit_price):
    return extension(lot["bid_basis"], unit_price, lot.get("settle_weight_lb"),
                     lot["head_count"])
