"""Shrinkage audits: the zone count and the batch write-off approval (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import envelope
import serializers as ser
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("audits", __name__)

NON_TERMINAL_AUDIT = ("COUNTED",)


@bp.post("/shrinkage-audits")
def create_audit():
    user_id, role = auth.require("FloorOperator")
    data = v.body()

    # ladder 5: body foreign keys, in input order
    raw_zone = v.raw_fk(data, "floor_zone_id")
    if raw_zone is not None and raw_zone not in db.zones:
        fail("ERR_ZONE_NOT_FOUND")
    raw_counted = data.get("counted_item_ids")
    if isinstance(raw_counted, list):
        for entry in raw_counted:
            if isinstance(entry, str) and entry.strip() and entry not in db.items:
                fail("ERR_ITEM_NOT_FOUND")

    floor_zone_id = v.req_id(data, "floor_zone_id")
    counted_item_ids = v.req_id_list(data, "counted_item_ids")

    zone = db.zones.get(floor_zone_id)
    if zone is None:
        fail("ERR_ZONE_NOT_FOUND")
    for entry in counted_item_ids:
        if entry not in db.items:
            fail("ERR_ITEM_NOT_FOUND")

    # ladder 32
    if zone["status"] != "OPEN":
        fail("ERR_ZONE_CLOSED")

    # ladder 35: no duplicates, and every counted id is placed in this zone
    if len(set(counted_item_ids)) != len(counted_item_ids):
        fail("ERR_AUDIT_COUNT_INVALID")
    for entry in counted_item_ids:
        if db.items[entry].get("placement_zone_id") != zone["id"]:
            fail("ERR_AUDIT_COUNT_INVALID")

    expected = services.items_in_zone(zone["id"])
    expected_ids = [i["id"] for i in expected]
    counted_set = set(counted_item_ids)
    missing = [i for i in expected if i["id"] not in counted_set]
    counted_item_count = len([i for i in expected_ids if i in counted_set])

    row = store.new_row(
        db.shrinkage_audits,
        {
            "floor_zone_id": zone["id"],
            "counted_item_ids": list(counted_item_ids),
            "expected_item_count": len(expected_ids),
            "counted_item_count": counted_item_count,
            "variance_count": len(expected_ids) - counted_item_count,
            "missing_item_ids": [i["id"] for i in missing],
            "write_off_total_cents": 0,
            "status": "COUNTED",
            "counted_by_user_id": user_id,
            "approved_by_user_id": None,
        },
    )

    # a zone carries at most one non-terminal audit
    for other in store.ordered(db.shrinkage_audits):
        if (
            other["id"] != row["id"]
            and other["floor_zone_id"] == zone["id"]
            and other["status"] in NON_TERMINAL_AUDIT
        ):
            other["status"] = "ABANDONED"
            store.touch(other)

    for item in missing:
        if item["inventory_state"] != "SHRINKAGE_MISSING":
            item["inventory_state"] = "SHRINKAGE_MISSING"
            store.touch(item)

    if row["variance_count"] == 0:
        row["status"] = "RECONCILED"
        row["write_off_total_cents"] = 0
    return envelope.created(ser.shrinkage_audit(row))


@bp.post("/shrinkage-audits/<audit_id>/approve-write-off")
def approve_write_off(audit_id):
    user_id, role = auth.require("GalleryManager")
    row = v.lookup(db.shrinkage_audits, audit_id, "ERR_AUDIT_NOT_FOUND")

    # ladder 3, ahead of the audit's own state precondition
    if row["counted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if row["status"] != "COUNTED":
        fail("ERR_AUDIT_STATE_INVALID")

    total = 0
    touched_zones = set()
    for item_id in row["missing_item_ids"]:
        item = db.items.get(item_id)
        if item is None:
            continue
        credit = calc.shrinkage_credit(item["current_price_cents"])
        total += credit
        if item.get("placement_zone_id"):
            touched_zones.add(item["placement_zone_id"])
        item["inventory_state"] = "WRITTEN_OFF_INV"
        item["lifecycle_state"] = "WRITTEN_OFF"
        item["placement_zone_id"] = None
        consignor = services.consignor_of_item(item)
        if consignor is not None:
            services.mint_entry(
                consignor,
                "SHRINKAGE_CREDIT",
                credit,
                "shrinkage write-off credit for item %s on audit %s" % (item["id"], row["id"]),
                item_id=item["id"],
            )
        store.touch(item)

    row["write_off_total_cents"] = total
    row["status"] = "RECONCILED"
    row["approved_by_user_id"] = user_id
    store.touch(row)
    # occupancy and utilisation are derived at read time; recomputed once here
    for zone_id in touched_zones:
        zone = db.zones.get(zone_id)
        if zone is not None:
            services.zone_utilization(zone)
    return envelope.ok(ser.shrinkage_audit(row))
