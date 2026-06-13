"""Distribution event cascades: planned poundage, TEFAP split, finalize."""
import itertools

from db import db
from services import models
from services.calc import round2

# Monotonic counter for finalize ordering (chronological ledger tiebreak).
_finalize_seq = itertools.count(1)


def reserved_lines(order_id, statuses):
    lines = [
        l
        for l in db.order_lines.values()
        if l["agency_order_id"] == order_id and l["line_status"] in statuses
    ]
    lines.sort(key=lambda l: l["_seq"])
    return lines


def planned_event_poundage(order_id):
    """Forward-looking planned poundage (PRD §3.7): the sum of reserved_lbs over
    the order's lines reserved by the FEFO run at pack time — i.e. a SHORT line
    "contributes only its reserved amount" and an already-PACKED line is
    excluded. Both RESERVED and SHORT lines contribute their reserved_lbs."""
    total = 0.0
    for line in reserved_lines(order_id, {"RESERVED", "SHORT"}):
        total += line["reserved_lbs"]
    return round2(total)


def order_has_tefap_reserved_line(order_id):
    """True if any RESERVED line of the order draws from a TEFAP-sourced lot."""
    for line in reserved_lines(order_id, {"RESERVED"}):
        lot_id = line["reserved_lot_id"]
        if lot_id:
            lot = db.inventory_lots.get(lot_id)
            if lot is not None and lot["source_type"] == "TEFAP":
                return True
    return False


def compute_tefap_split(order_id, actual_distributed_lbs):
    """FEFO waterfall over the order's PACKED lines, ascending by reserved lot's
    (expiration_date, created_at). Allocate min(remaining, line.reserved_lbs);
    if the lot is TEFAP, add (rounded per-line) to tefap_lbs. Round each line
    allocation to 2dp THEN sum (calc event_tefap_split / PRD §3.8)."""
    lines = reserved_lines(order_id, {"PACKED"})

    def sort_key(line):
        lot = db.inventory_lots.get(line["reserved_lot_id"])
        if lot is None:
            return (models.parse_iso("9999-12-31T00:00:00Z"), line["_seq"])
        return (models.parse_iso(lot["expiration_date"]), lot["_seq"])

    lines.sort(key=sort_key)

    remaining = round2(actual_distributed_lbs)
    tefap_total = 0.0
    for line in lines:
        if remaining <= 0:
            break
        alloc = round2(min(remaining, line["reserved_lbs"]))
        remaining = round2(remaining - alloc)
        lot = db.inventory_lots.get(line["reserved_lot_id"])
        if lot is not None and lot["source_type"] == "TEFAP":
            tefap_total = round2(tefap_total + alloc)
    return round2(tefap_total)


def finalize_cascade(event, actual_distributed_lbs):
    """Deplete reserved lots backing PACKED lines, fulfill order, bump agency
    ledger. Returns nothing; mutates event/order/lots/agency."""
    order = db.agency_orders[event["agency_order_id"]]

    event["tefap_lbs"] = compute_tefap_split(order["id"], actual_distributed_lbs)
    event["actual_distributed_lbs"] = round2(actual_distributed_lbs)

    # Reserved lots for PACKED lines: RESERVED -> DEPLETED (permanent consume).
    touched_units = set()
    for line in reserved_lines(order["id"], {"PACKED"}):
        lot = db.inventory_lots.get(line["reserved_lot_id"])
        if lot is not None and lot["disposition"] == "RESERVED":
            lot["disposition"] = "DEPLETED"
            models.touch(lot)
            touched_units.add(lot["cold_storage_unit_id"])
    for unit_id in touched_units:
        unit = db.cold_storage_units.get(unit_id)
        if unit is not None:
            models.recompute_unit_occupancy(unit)

    # Order APPROVED -> FULFILLED.
    order["status"] = "FULFILLED"
    models.touch(order)

    # Agency lifetime ledger.
    agency = db.agencies.get(order["agency_id"])
    if agency is not None:
        agency["lifetime_distributed_lbs"] = round2(
            agency["lifetime_distributed_lbs"] + actual_distributed_lbs
        )
        models.touch(agency)

    event["status"] = "FINALIZED"
    event["finalized_at_seq"] = next(_finalize_seq)
    models.touch(event)
