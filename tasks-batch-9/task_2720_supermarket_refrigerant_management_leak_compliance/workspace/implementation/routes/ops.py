"""Compliance sweep and the logical clock (PRD 2.4, 3.6)."""
from flask import Blueprint

import constants
import db
import response
import util
import validate
from middleware import PLATFORM_ADMIN, endpoint
from services import posture

bp = Blueprint("ops", __name__)


def _event_store_id(event):
    system = db.get("systems", event["system_id"])
    return system["store_id"] if system else None


@bp.post("/compliance-runs")
@endpoint([PLATFORM_ADMIN])
def run_compliance_sweep():
    payload = validate.body()
    store_id = validate.opt_id(payload, "store_id")
    if store_id is not None:
        db.require("stores", store_id)
    as_of = db.now()
    touched_stores = []

    def note(store_key):
        if store_key is not None and store_key not in touched_stores:
            touched_stores.append(store_key)

    def in_scope(store_key):
        return store_id is None or store_key == store_id

    # Pass 1 -- repair deadlines.
    swept_repair = []
    candidates = [
        event for event in db.values("leak_events")
        if event["status"] in ("OPEN", "VERIFICATION_FAILED")
        and event["repair_deadline"] is not None
        and event["repair_deadline"] < as_of
        and in_scope(_event_store_id(event))
    ]
    candidates.sort(key=lambda e: (e["repair_deadline"], e["created_at"], e["_seq"]))
    for event in candidates:
        snap = db.snapshot(event)
        event["status"] = "REPAIR_OVERDUE"
        db.commit(event, snap)
        swept_repair.append(event["id"])
        note(_event_store_id(event))

    # Pass 2 -- verification deadlines.
    swept_verification = []
    candidates = [
        event for event in db.values("leak_events")
        if event["status"] in ("VERIFICATION_PENDING", "FOLLOWUP_PENDING")
        and event["verification_deadline"] is not None
        and event["verification_deadline"] < as_of
        and in_scope(_event_store_id(event))
    ]
    candidates.sort(key=lambda e: (e["verification_deadline"], e["created_at"], e["_seq"]))
    for event in candidates:
        snap = db.snapshot(event)
        event["status"] = "VERIFICATION_OVERDUE"
        db.commit(event, snap)
        swept_verification.append(event["id"])
        note(_event_store_id(event))

    # Pass 3 -- undecided extension requests.
    expired_extensions = []
    candidates = []
    for extension in db.values("extension_requests"):
        if extension["status"] != "PENDING":
            continue
        if extension["expires_at"] >= as_of:
            continue
        event = db.get("leak_events", extension["leak_event_id"])
        store_key = _event_store_id(event) if event else None
        if not in_scope(store_key):
            continue
        candidates.append((extension, store_key))
    candidates.sort(key=lambda pair: (pair[0]["expires_at"], pair[0]["created_at"],
                                      pair[0]["_seq"]))
    for extension, store_key in candidates:
        snap = db.snapshot(extension)
        extension["status"] = "EXPIRED"
        db.commit(extension, snap)
        expired_extensions.append(extension["id"])
        note(store_key)

    # Pass 4 -- recovery equipment verification lapses.
    overdue_equipment = []
    candidates = [
        equipment for equipment in db.values("recovery_equipment")
        if equipment["status"] == "CERTIFIED"
        and util.add_days(equipment["last_verification_on"],
                          constants.EQUIPMENT_VERIFICATION_WINDOW_DAYS) < as_of
        and in_scope(equipment["store_id"])
    ]
    candidates.sort(key=lambda e: (
        util.add_days(e["last_verification_on"],
                      constants.EQUIPMENT_VERIFICATION_WINDOW_DAYS),
        e["created_at"], e["_seq"]))
    for equipment in candidates:
        snap = db.snapshot(equipment)
        equipment["status"] = "VERIFICATION_OVERDUE"
        db.commit(equipment, snap)
        overdue_equipment.append(equipment["id"])
        note(equipment["store_id"])

    # Pass 5 -- unanswered inspections.
    escalated_inspections = []
    candidates = [
        inspection for inspection in db.values("inspections")
        if inspection["status"] == "OPEN"
        and inspection["response_deadline"] < as_of
        and in_scope(inspection["store_id"])
    ]
    candidates.sort(key=lambda i: (i["response_deadline"], i["created_at"], i["_seq"]))
    for inspection in candidates:
        snap = db.snapshot(inspection)
        inspection["status"] = "ESCALATED"
        inspection["escalated_at"] = as_of
        db.commit(inspection, snap)
        escalated_inspections.append(inspection["id"])
        note(inspection["store_id"])

    for store_key in touched_stores:
        posture.recompute_store_by_id(store_key)

    return response.ok({
        "swept_repair_overdue_leak_event_ids": swept_repair,
        "swept_verification_overdue_leak_event_ids": swept_verification,
        "expired_extension_request_ids": expired_extensions,
        "overdue_equipment_ids": overdue_equipment,
        "escalated_inspection_ids": escalated_inspections,
        "stores_recomputed_count": len(touched_stores),
        "as_of": as_of,
    })


@bp.post("/_clock/set_current_utc")
@endpoint([PLATFORM_ADMIN], header_exempt=True)
def set_clock():
    payload = validate.body()
    current_utc = validate.req_instant(payload, "current_utc")
    previous = db.db.clock
    db.db.clock = current_utc
    return response.ok({
        "current_utc": current_utc,
        "previous_utc": previous,
    })
