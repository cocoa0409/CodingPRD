"""Cross-entity state transitions and cascades (SCAFFOLD §1.2, PRD §3.7/§3.9/§3.11).

Every entity touched by a cascade gets its version incremented and updated_at
refreshed (db.touch). Cascades are atomic within the triggering request."""
from clock import clock
from db import db, touch
from helpers import parse_iso
from services import calculations as calc


def recompute_administered_days(order):
    """administered_days = count of this order's NursingVisit in COMPLETED."""
    count = sum(
        1 for v in db.nursing_visits.values()
        if v["order_id"] == order["id"] and v["status"] == "COMPLETED"
    )
    order["administered_days"] = count
    return count


def hold_order(order, hold_reason):
    """Drive a RELEASED/ACTIVE order to ON_HOLD. When the held order was ACTIVE,
    also sweep every SCHEDULED visit with a future start_at into MISSED."""
    was_active = order["status"] == "ACTIVE"
    order["status"] = "ON_HOLD"
    order["hold_reason"] = hold_reason
    touch(order)

    if was_active:
        now = clock.now()
        for v in db.nursing_visits.values():
            if v["order_id"] != order["id"]:
                continue
            if v["status"] != "SCHEDULED":
                continue
            if parse_iso(v["start_at"]) > now:
                v["status"] = "MISSED"
                touch(v)


def discontinue_cascade(order):
    """Run the atomic discontinuation cascade (PRD §3.11, §3.8):
      - every SCHEDULED visit -> CANCELLED
      - every ORDERED/COMPOUNDED compound -> WASTED; COMPOUNDED returns vials to inventory
      - every PICKING SupplyKit -> CANCELLED (PRD §3.8: order discontinuation is a
        kit-cancel trigger)
    The order itself is set to DISCONTINUED by the caller via this helper."""
    for v in db.nursing_visits.values():
        if v["order_id"] == order["id"] and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            touch(v)

    for c in db.compounds.values():
        if c["order_id"] != order["id"]:
            continue
        if c["status"] == "ORDERED":
            c["status"] = "WASTED"
            touch(c)
        elif c["status"] == "COMPOUNDED":
            # return reserved vials to inventory before wasting
            drug = _drug_for_order(order)
            if drug is not None and c["vials_reserved"]:
                drug["on_hand_vials"] += c["vials_reserved"]
                touch(drug)
            c["status"] = "WASTED"
            touch(c)

    cancel_kits_for_order(order)

    order["status"] = "DISCONTINUED"
    order["hold_reason"] = None
    touch(order)


def cancel_kits_for_order(order):
    """Auth-denied / discontinuation cascade: every PICKING SupplyKit -> CANCELLED."""
    for k in db.supply_kits.values():
        if k["order_id"] == order["id"] and k["status"] == "PICKING":
            k["status"] = "CANCELLED"
            touch(k)


def _drug_for_order(order):
    return db.drug_catalog.get(order["drug_id"])
