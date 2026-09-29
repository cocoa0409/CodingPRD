"""Transitive cascades of PRD §2.9. Each touched row is version-bumped exactly
once per operation (db.touch enforces the once-per-row rule)."""
import db
from db import store
from services import derive


# ---------------------------------------------------------------------------
# slot release
# ---------------------------------------------------------------------------
def release_slot(slot):
    slot["status"] = "RELEASED"
    db.touch(slot)


def unmatch_chassis(order_id):
    for chassis in store.chassis_receipts.values():
        if chassis.get("matched_unit_order_id") == order_id and chassis["status"] == "MATCHED":
            chassis["status"] = "RECEIVED"
            chassis["matched_unit_order_id"] = None
            db.touch(chassis)
            return chassis
    return None


def expiry_release_cascade(slot):
    """Hop 1-3 of daily_close_slot_expiry_releases_order_and_chassis."""
    release_slot(slot)
    order = store.unit_orders.get(slot["unit_order_id"])
    if order is None:
        return None
    remaining = [
        s
        for s in derive.order_slots(order["id"])
        if s["status"] in ("RESERVED", "CONSUMED")
    ]
    if remaining or order["status"] != "SLOTTED":
        return None
    order["status"] = "CONFIG_VALIDATED"
    db.touch(order)
    unmatch_chassis(order["id"])
    return order


# ---------------------------------------------------------------------------
# recall quarantine cascade
# ---------------------------------------------------------------------------
def quarantine_cascade(campaign, lot_codes):
    """Hops 1-3 for the lots named by `lot_codes` that are not yet quarantined."""
    codes = set(lot_codes)
    for lot in db.ordered(list(store.component_lots.values())):
        if lot["supplier_id"] != campaign["supplier_id"]:
            continue
        if lot["part_number"] != campaign["part_number"]:
            continue
        if lot["lot_code"] not in codes:
            continue
        if lot["status"] == "QUARANTINED":
            continue
        frozen = int(lot["quantity_available"])
        lot["quantity_quarantined"] = int(lot["quantity_quarantined"]) + frozen
        lot["quantity_available"] = 0
        lot["status"] = "QUARANTINED"
        db.touch(lot)
        campaign["quarantined_piece_count"] = int(campaign["quarantined_piece_count"]) + frozen

        for installation in db.ordered(derive_installations_of_lot(lot["id"])):
            if installation["status"] != "INSTALLED":
                continue
            installation["status"] = "RECALL_AFFECTED"
            installation["recall_campaign_id"] = campaign["id"]
            db.touch(installation)
            campaign["affected_installation_count"] = (
                int(campaign["affected_installation_count"]) + 1
            )
            build = store.unit_builds.get(installation["unit_build_id"])
            if build is None:
                continue
            if not build["recall_hold"]:
                build["recall_hold"] = True
                db.touch(build)
            if campaign["ship_stop"] and build["current_station"] != "SHIPPED":
                order = store.unit_orders.get(build["unit_order_id"])
                if order is not None and order["ship_hold_reason"] != "RECALL_HOLD":
                    order["ship_hold_reason"] = "RECALL_HOLD"
                    db.touch(order)


def derive_installations_of_lot(lot_id):
    return [
        i for i in store.component_installations.values() if i["component_lot_id"] == lot_id
    ]


def clear_recall_hold_if_done(build):
    """Called after a remedy: drop the hold when nothing is RECALL_AFFECTED any more."""
    for installation in derive.build_installations(build["id"]):
        if installation["status"] == "RECALL_AFFECTED":
            return
    if build["recall_hold"]:
        build["recall_hold"] = False
        db.touch(build)
    order = store.unit_orders.get(build["unit_order_id"])
    if order is not None and order["ship_hold_reason"] == "RECALL_HOLD":
        order["ship_hold_reason"] = "NONE"
        db.touch(order)


# ---------------------------------------------------------------------------
# scrap cascade
# ---------------------------------------------------------------------------
def scrap_build(build):
    build["current_station"] = "SCRAPPED"
    db.touch(build)
    order = store.unit_orders.get(build["unit_order_id"])
    if order is not None and order["status"] == "IN_PRODUCTION":
        order["status"] = "CANCELLED"
        order["ship_hold_reason"] = "QUALITY_HOLD"
        db.touch(order)
