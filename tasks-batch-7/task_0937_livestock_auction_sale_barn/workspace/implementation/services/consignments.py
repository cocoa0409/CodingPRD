"""Consignment head derivations and INV_CONSIGNMENT_HEAD (PRD 2.10, 3.3).

head_unassigned is a STORED counter, never a residual - which is exactly what
makes head_balance_ok falsifiable and worth surfacing.
"""
from store import db


def consignment_lots(consignment_id):
    return sorted([l for l in db["lots"].values()
                   if l["consignment_id"] == consignment_id],
                  key=lambda l: (l["created_at"], l["_seq"]))


def head_in_lots(consignment_id):
    return sum(l["head_count"] for l in consignment_lots(consignment_id)
               if l["sale_status"] != "WITHDRAWN")


def head_sold(consignment_id):
    return sum(l["head_count"] for l in consignment_lots(consignment_id)
               if l["sale_status"] == "SOLD")


def head_no_saled(consignment_id):
    return sum(l["head_count"] for l in consignment_lots(consignment_id)
               if l["sale_status"] == "NO_SALE")


def head_balance_ok(consignment):
    lots_head = head_in_lots(consignment["id"])
    return consignment["head_received"] == (
        lots_head
        + consignment["head_unassigned"]
        + consignment["head_dead"]
        + consignment["head_condemned"]
        + consignment["head_withdrawn"]
    )


def maybe_sorted(consignment, touch):
    """CHECKED_IN -> SORTED when head_unassigned reaches 0, and the re-entry
    edge SORTED -> CHECKED_IN when it rises above 0 again."""
    if consignment["status"] == "CHECKED_IN" and consignment["head_unassigned"] == 0:
        consignment["status"] = "SORTED"
        touch(consignment)
    elif consignment["status"] == "SORTED" and consignment["head_unassigned"] > 0:
        consignment["status"] = "CHECKED_IN"
        touch(consignment)
    return consignment
