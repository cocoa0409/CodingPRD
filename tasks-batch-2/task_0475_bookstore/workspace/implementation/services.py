"""Shared business-logic helpers: recompute derived fields, stock selection,
ledger appends, and existence lookups.
"""
from db import db, new_id, now_iso
from common import make_record, touch


# ---- existence lookups -----------------------------------------------------

def get_or_none(coll, _id):
    return coll.get(_id)


# ---- derived-field recompute ----------------------------------------------

def recompute_title_counts(title, mutate=True):
    """Recompute on_hand_qty/reserved_qty from live StockItem rows.

    mutate=True bumps version+updated_at (a write-side recompute, per PRD §2.4).
    mutate=False just refreshes the projected value for a read.
    """
    on_hand = 0
    reserved = 0
    tid = title["id"]
    for si in db.stock_items.values():
        if si["title_id"] != tid:
            continue
        if si["state"] == "AVAILABLE":
            on_hand += 1
        elif si["state"] == "RESERVED":
            reserved += 1
    changed = title.get("on_hand_qty") != on_hand or title.get("reserved_qty") != reserved
    title["on_hand_qty"] = on_hand
    title["reserved_qty"] = reserved
    if mutate:
        touch(title)
    return changed


def recompute_order_line_reserved(line, mutate=True):
    cnt = 0
    lid = line["id"]
    for si in db.stock_items.values():
        if si.get("reserved_order_line_id") == lid and si["state"] == "RESERVED":
            cnt += 1
    line["reserved_qty"] = cnt
    if mutate:
        touch(line)


def recompute_member_balances(member):
    """Set store_credit_cents and loyalty_points from live ledger / awards.

    store_credit_cents = sum of ledger delta_cents (never negative).
    loyalty_points is maintained incrementally (sum of finalized awards); we only
    ensure the field exists here. This is read-side: it does NOT bump version.
    """
    mid = member["id"]
    total = 0
    for e in db.credit_ledger.values():
        if e["member_id"] == mid:
            total += e["delta_cents"]
    if total < 0:
        total = 0
    member["store_credit_cents"] = total
    member.setdefault("loyalty_points", 0)


def recompute_order_subtotal(order):
    subtotal = 0
    oid = order["id"]
    for line in db.order_lines.values():
        if line["order_id"] == oid:
            subtotal += line["line_total_cents"]
    order["subtotal_cents"] = subtotal


def recompute_event_tickets_sold(event, mutate=True):
    eid = event["id"]
    cnt = 0
    for t in db.event_tickets.values():
        if t["event_id"] == eid and t["state"] == "BOOKED":
            cnt += 1
    event["tickets_sold"] = cnt
    if mutate:
        touch(event)


def recompute_agreement_counters(agreement, mutate=True):
    aid = agreement["id"]
    units = 0
    payout = 0
    for c in db.consignment_copies.values():
        if c["agreement_id"] == aid and c["state"] == "SOLD":
            units += 1
            payout += c.get("payout_cents") or 0
    agreement["units_sold_to_date"] = units
    agreement["total_payout_cents"] = payout
    if mutate:
        touch(agreement)


# ---- stock selection -------------------------------------------------------

def available_stock_for_title(title_id):
    """AVAILABLE stock items for a title, oldest created_at first (then _seq)."""
    items = [
        si for si in db.stock_items.values()
        if si["title_id"] == title_id and si["state"] == "AVAILABLE"
    ]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return items


def reserved_stock_for_line(line_id):
    return [
        si for si in db.stock_items.values()
        if si.get("reserved_order_line_id") == line_id and si["state"] == "RESERVED"
    ]


# ---- consignment sale ------------------------------------------------------

def sell_consignment_copy(copy, backing_stock_item=None):
    """Transition an ON_SHELF ConsignmentCopy to SOLD: compute payout from the
    tier (units_sold_to_date BEFORE this copy is counted), flip the backing
    StockItem to SOLD, bump the agreement's counters, recompute Title counts.

    Returns the agreement (for the caller to recompute the title if needed).
    """
    from calculations import consignment_payout
    agreement = db.consignment_agreements[copy["agreement_id"]]

    units_before = agreement["units_sold_to_date"]
    payout = consignment_payout(units_before, copy["sale_price_cents"])
    copy["payout_cents"] = payout
    copy["state"] = "SOLD"
    touch(copy)

    # flip backing stock item to SOLD (find it if not provided)
    si = backing_stock_item
    if si is None:
        for s in db.stock_items.values():
            if s.get("consignment_copy_id") == copy["id"]:
                si = s
                break
    if si is not None and si["state"] != "SOLD":
        si["state"] = "SOLD"
        si["reserved_order_line_id"] = None
        touch(si)

    recompute_agreement_counters(agreement, mutate=True)
    return agreement


# ---- ledger ----------------------------------------------------------------

def append_ledger(member_id, delta_cents, reason, ref_id):
    """Append an immutable CreditLedgerEntry (id + created_at only)."""
    entry = {
        "id": new_id(),
        "created_at": now_iso(),
        "member_id": member_id,
        "delta_cents": delta_cents,
        "reason": reason,
        "ref_id": ref_id,
        "_seq": db.next_seq(),
    }
    db.credit_ledger[entry["id"]] = entry
    return entry
