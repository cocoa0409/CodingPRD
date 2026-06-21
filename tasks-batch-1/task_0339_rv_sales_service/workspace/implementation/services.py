"""Derived-field reconciliation and cross-entity cascades (PRD 2.8, 3.x)."""

import db
from common import touch


# --- PartItem derived fields --------------------------------------------------
def recompute_part(part):
    """qty_reserved = sum of RESERVED reservation quantities; qty_available floored at 0."""
    reserved = 0
    for res in db.store["part_reservations"].values():
        if res["part_item_id"] == part["id"] and res["status"] == "RESERVED":
            reserved += res["quantity"]
    part["qty_reserved"] = reserved
    part["qty_available"] = max(part["qty_on_hand"] - reserved, 0)


# --- Unit recall exposure -----------------------------------------------------
def recompute_open_recall_count(unit):
    """Count non-CLEARED remedies on the unit for campaigns still OPEN."""
    count = 0
    for remedy in db.store["recall_remedies"].values():
        if remedy["unit_id"] != unit["id"]:
            continue
        if remedy["status"] == "CLEARED":
            continue
        campaign = db.store["recall_campaigns"].get(remedy["recall_campaign_id"])
        if campaign and campaign["status"] == "OPEN":
            count += 1
    unit["open_recall_count"] = count


def has_open_stop_sale(unit):
    """True if the unit has a non-CLEARED remedy under an OPEN STOP_SALE campaign."""
    for remedy in db.store["recall_remedies"].values():
        if remedy["unit_id"] != unit["id"] or remedy["status"] == "CLEARED":
            continue
        campaign = db.store["recall_campaigns"].get(remedy["recall_campaign_id"])
        if campaign and campaign["status"] == "OPEN" and campaign["severity"] == "STOP_SALE":
            return True
    return False


# --- Unit hold cascades -------------------------------------------------------
def place_hold(unit, deal_id):
    unit["status"] = "HELD"
    unit["active_hold_deal_id"] = deal_id
    touch(unit)


def release_hold(unit):
    unit["status"] = "AVAILABLE"
    unit["active_hold_deal_id"] = None
    touch(unit)


def mark_sold(unit):
    unit["status"] = "SOLD"
    touch(unit)
