"""Derived counters and conserved quantities (PRD §2.10): recomputed from source
facts so forward + compensating actions can never drift."""
from db import store, touch

BACKORDER_RISK_THRESHOLD = 2


# ------------------------------------------------------------- resolvers

def award_of_po(po):
    return store.awards.get(po["award_id"])


def po_of_line(line):
    return store.purchase_orders.get(line["purchase_order_id"])


def award_of_line(line):
    po = po_of_line(line)
    return award_of_po(po) if po else None


def district_id_of_po(po):
    award = award_of_po(po)
    return award["district_id"] if award else None


def district_id_of_line(line):
    po = po_of_line(line)
    return district_id_of_po(po) if po else None


def spec_of_line(line):
    sl = store.spec_lines.get(line["spec_line_id"])
    return store.bid_specs.get(sl["bid_spec_id"]) if sl else None


def lines_of_po(po_id):
    return [l for l in store.po_lines.values() if l["purchase_order_id"] == po_id]


def open_notice_of_line(line_id):
    for n in store.backorder_notices.values():
        if n["po_line_id"] == line_id and n["status"] in ("OPEN", "ETA_UPDATED"):
            return n
    return None


# ------------------------------------------------------------- recomputes

def recompute_spec_line(sl):
    """remaining_qty = qty - sum(ordered_qty over non-CANCELLED POLines)."""
    rem = sl["qty"] - sum(
        l["ordered_qty"]
        for l in store.po_lines.values()
        if l["spec_line_id"] == sl["id"] and l["status"] != "CANCELLED"
    )
    if sl["remaining_qty"] != rem:
        sl["remaining_qty"] = rem
        touch(sl)


def recompute_po(po):
    """total_cents, open_backorder_count, posture — all derived from lines."""
    lines = lines_of_po(po["id"])
    total = sum(l["line_total_cents"] for l in lines if l["status"] != "CANCELLED")
    count = sum(1 for l in lines if l["status"] == "BACKORDERED")
    posture = "AT_RISK" if count >= BACKORDER_RISK_THRESHOLD else "ON_TRACK"
    if (
        po["total_cents"] != total
        or po["open_backorder_count"] != count
        or po["posture"] != posture
    ):
        po["total_cents"] = total
        po["open_backorder_count"] = count
        po["posture"] = posture
        touch(po)


def recompute_crew(crew):
    """booked_days = sum(crew_days over this crew's SCHEDULED/IN_PROGRESS tasks)."""
    bd = sum(
        t["crew_days"]
        for t in store.install_tasks.values()
        if t["crew_id"] == crew["id"] and t["status"] in ("SCHEDULED", "IN_PROGRESS")
    )
    if crew["booked_days"] != bd:
        crew["booked_days"] = bd
        touch(crew)


def resolve_open_notice(line):
    """Open notice (OPEN|ETA_UPDATED) -> RESOLVED when the line fully delivers
    or is cancelled; PO counters are recomputed from line statuses."""
    notice = open_notice_of_line(line["id"])
    if notice is not None:
        notice["status"] = "RESOLVED"
        touch(notice)
    po = po_of_line(line)
    if po is not None:
        recompute_po(po)
