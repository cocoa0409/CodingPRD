"""Live-space change control: MOP coverage plus cascade A and its exact compensation."""

import db
from errors import ApiError
from services import calc

TARGET_KINDS = {
    "BUSWAY": "busways",
    "COOLING_UNIT": "cooling_units",
    "CONTAINMENT_ZONE": "zones",
    "RACK": "racks",
}


def target_row(mop):
    return db.get(TARGET_KINDS[mop["target_resource_type"]], mop["target_resource_id"])


def target_state(row, target_type):
    if target_type == "CONTAINMENT_ZONE":
        return row["leakage_status"]
    return row["status"]


# ------------------------------------------------------------- coverage ----

def covering_mop(hall, resource_ids):
    for mop in db.where("mops", hall_id=hall["id"], status="IN_EXECUTION"):
        if mop["target_resource_id"] in resource_ids:
            return mop
    return None


def require_covering_mop(hall, resource_ids):
    """Validation 25: live-space work needs a covering MOP in execution."""
    if hall["status"] != "LIVE":
        return None
    mop = covering_mop(hall, resource_ids)
    if mop is None:
        raise ApiError("ERR_MOP_REQUIRED")
    return mop


# -------------------------------------------------------------- cascade ----

def degrade_cage_of(rack):
    cage_id = rack.get("cage_id")
    if not cage_id:
        return
    cage = db.get("cages", cage_id)
    if cage is None:
        return
    if cage["operational_status"] in ("SECURED", "RELEASED"):
        cage["operational_status"] = "DEGRADED"
        db.touch(cage)
    for packet in db.where("packets", cage_id=cage["id"], status="ACCEPTED"):
        packet["status"] = "SUSPENDED"
        db.touch(packet)


def execute_cascade(mop, hall):
    target_type = mop["target_resource_type"]
    target = target_row(mop)
    if target_type == "BUSWAY" and target["status"] == "ENERGIZED":
        target["status"] = "ISOLATED"
        db.touch(target)
        affected = []
        for feed in db.where("feeds", busway_id=target["id"], status="ENERGIZED"):
            feed["status"] = "DERATED"
            db.touch(feed)
            if feed["rack_id"] not in affected:
                affected.append(feed["rack_id"])
        for rack_id in affected:
            rack = db.get("racks", rack_id)
            if rack is None:
                continue
            calc.apply_rack_load(rack)
            if (
                rack["energized_feed_count"] < rack["required_feed_count"]
                and rack["status"] in ("POWERED", "RELEASED")
            ):
                rack["pre_risk_status"] = rack["status"]
                rack["status"] = "AT_RISK"
                db.touch(rack)
                degrade_cage_of(rack)
    elif target_type == "COOLING_UNIT" and target["status"] == "IN_SERVICE":
        target["status"] = "MAINTENANCE"
        db.touch(target)
    calc.rack_chain(hall)


def restore_cascade(mop, hall):
    target_type = mop["target_resource_type"]
    target = target_row(mop)
    captured = mop.get("pre_execution_target_state")
    if (
        target_type == "BUSWAY"
        and captured == "ENERGIZED"
        and target["status"] == "ISOLATED"
    ):
        target["status"] = "ENERGIZED"
        db.touch(target)
        affected = []
        for feed in db.where("feeds", busway_id=target["id"], status="DERATED"):
            feed["status"] = "ENERGIZED"
            db.touch(feed)
            if feed["rack_id"] not in affected:
                affected.append(feed["rack_id"])
        for rack_id in affected:
            rack = db.get("racks", rack_id)
            if rack is None:
                continue
            calc.apply_rack_load(rack)
            if (
                rack["status"] == "AT_RISK"
                and rack["energized_feed_count"] == rack["required_feed_count"]
            ):
                rack["status"] = rack.get("pre_risk_status") or "POWERED"
                rack["pre_risk_status"] = None
                db.touch(rack)
    elif (
        target_type == "COOLING_UNIT"
        and captured == "IN_SERVICE"
        and target["status"] == "MAINTENANCE"
    ):
        target["status"] = "IN_SERVICE"
        db.touch(target)

    for cage in db.where("cages", hall_id=hall["id"]):
        racks = db.where("racks", cage_id=cage["id"])
        if any(r["status"] == "AT_RISK" for r in racks):
            continue
        for packet in db.where("packets", cage_id=cage["id"], status="SUSPENDED"):
            packet["status"] = "ACCEPTED"
            db.touch(packet)
        if cage["operational_status"] == "DEGRADED":
            accepted = db.where("packets", cage_id=cage["id"], status="ACCEPTED")
            cage["operational_status"] = "RELEASED" if accepted else "SECURED"
            db.touch(cage)

    calc.rack_chain(hall)
