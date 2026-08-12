"""Equipment declaration/withdrawal and the inspection pipeline."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import (
    authenticate,
    get_equipment,
    get_inspection,
    get_participant,
)
from response import success
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import MINUTES_15, MINUTES_45, body, req_dt, req_enum, req_str, opt_str

bp = Blueprint("equipment", __name__)

ITEM_TYPES = ("FIREARM", "EDGED", "CANNON", "CAMP_FLAME", "TENTAGE", "OTHER")
ITEM_READ_ROLES = ["SafetyOfficer", "EventOrganizer", "UnitCommander", "Participant"]
ITEM_WRITE_ROLES = ["Participant", "UnitCommander", "EventOrganizer"]


def _check_item_ownership(uid, role, item):
    if role == "EventOrganizer":
        return
    owner = db.participants.get(item["participant_id"])
    if role == "Participant":
        if item["participant_id"] != uid:
            fail("ERR_FORBIDDEN", "participant may act only on its own equipment")
    elif role == "UnitCommander":
        if owner is None or owner["unit_id"] != uid:
            fail("ERR_FORBIDDEN", "unit commander may act only on its own unit's equipment")


@bp.post("/equipment-items")
def create_equipment_item():
    uid, role = authenticate(ITEM_WRITE_ROLES, creation=True)
    data = body(request)
    participant_id = data.get("participant_id")
    # Ownership (priority 2) precedes existence where it is a pure comparison.
    if role == "Participant" and participant_id != uid:
        fail("ERR_FORBIDDEN", "participant declares equipment only for itself")
    owner = get_participant(participant_id) if participant_id else None
    if owner is None:
        fail("ERR_VALIDATION", "missing required field: participant_id")
    if role == "UnitCommander" and owner["unit_id"] != uid:
        fail("ERR_FORBIDDEN", "unit commander declares equipment only for its own unit's members")
    # Participant state (priority 5)
    if owner["status"] in ("REJECTED", "WITHDRAWN"):
        fail("ERR_INVALID_PARTICIPANT_STATUS", "equipment cannot be declared for a terminal participant")
    item_type = req_enum(data, "item_type", ITEM_TYPES)
    description = req_str(data, "description")
    rec = new_record()
    rec.update(
        participant_id=owner["id"],
        item_type=item_type,
        description=description,
        status="DECLARED",
        failure_count=0,
    )
    db.equipment[rec["id"]] = rec
    return success(serializers.equipment_item(rec), 201)


@bp.get("/equipment-items/<item_id>")
def read_equipment_item(item_id):
    uid, role = authenticate(ITEM_READ_ROLES)
    it = get_equipment(item_id)
    _check_item_ownership(uid, role, it)
    return success(serializers.equipment_item(it), 200)


@bp.get("/participants/<participant_id>/equipment-items")
def list_participant_equipment(participant_id):
    uid, role = authenticate(ITEM_READ_ROLES)
    p = get_participant(participant_id)
    if role == "Participant":
        if p["id"] != uid:
            fail("ERR_FORBIDDEN", "participant may read only its own equipment")
    elif role == "UnitCommander":
        if p["unit_id"] != uid:
            fail("ERR_FORBIDDEN", "unit commander may read only its own unit's equipment")
    items = sorted_all(i for i in db.equipment.values() if i["participant_id"] == p["id"])
    page, meta = paginate(items)
    return success([serializers.equipment_item(i) for i in page], 200, pagination=meta)


@bp.post("/equipment-items/<item_id>/withdraw")
def withdraw_equipment_item(item_id):
    uid, role = authenticate(ITEM_WRITE_ROLES)
    it = get_equipment(item_id)
    _check_item_ownership(uid, role, it)
    if it["status"] not in ("DECLARED", "INSPECTION_DUE", "FAILED"):
        fail("ERR_INVALID_EQUIPMENT_STATUS", f"item in {it['status']} cannot be withdrawn")
    it["status"] = "WITHDRAWN"
    touch(it)
    for ins in db.inspections.values():
        if ins["equipment_item_id"] == it["id"] and ins["status"] == "SCHEDULED":
            ins["status"] = "CANCELLED"
            touch(ins)
    return success(serializers.equipment_item(it), 200)


@bp.post("/equipment-items/<item_id>/inspections")
def schedule_inspection(item_id):
    authenticate(["SafetyOfficer"], creation=True)
    it = get_equipment(item_id)
    if it["status"] not in ("DECLARED", "INSPECTION_DUE", "FAILED"):
        fail("ERR_INVALID_EQUIPMENT_STATUS", f"item in {it['status']} cannot be scheduled for inspection")
    data = body(request)
    scheduled_for = req_dt(data, "scheduled_for")
    kind = req_enum(data, "inspection_kind", ("SAFETY", "AUTHENTICITY"))
    # Buffered-window conflict: new window expanded by 15 min on both sides vs
    # other SCHEDULED windows of the same item; touching counts as conflict.
    new_start = scheduled_for - MINUTES_15
    new_end = scheduled_for + MINUTES_45 + MINUTES_15
    for ins in db.inspections.values():
        if ins["equipment_item_id"] != it["id"] or ins["status"] != "SCHEDULED":
            continue
        ex_start = ins["scheduled_for"]
        ex_end = ex_start + MINUTES_45
        if new_start <= ex_end and ex_start <= new_end:
            fail("ERR_INSPECTION_WINDOW_CONFLICT", "inspection window conflicts with an existing one")
    if it["status"] in ("DECLARED", "FAILED"):
        it["status"] = "INSPECTION_DUE"
        touch(it)
    rec = new_record()
    rec.update(
        equipment_item_id=it["id"],
        inspection_kind=kind,
        scheduled_for=scheduled_for,
        status="SCHEDULED",
        recorded_by_user_id=None,
        failure_reason=None,
        waived_by_user_id=None,
        waiver_reason=None,
    )
    db.inspections[rec["id"]] = rec
    return success(serializers.inspection(rec), 201)


@bp.get("/equipment-items/<item_id>/inspections")
def list_item_inspections(item_id):
    authenticate(["SafetyOfficer", "EventOrganizer"])
    it = get_equipment(item_id)
    items = sorted_all(i for i in db.inspections.values() if i["equipment_item_id"] == it["id"])
    page, meta = paginate(items)
    return success([serializers.inspection(i) for i in page], 200, pagination=meta)


def _cancel_other_scheduled(item_id, keep_id):
    for ins in db.inspections.values():
        if (
            ins["equipment_item_id"] == item_id
            and ins["status"] == "SCHEDULED"
            and ins["id"] != keep_id
        ):
            ins["status"] = "CANCELLED"
            touch(ins)


@bp.post("/inspections/<inspection_id>/record")
def record_inspection(inspection_id):
    uid, _ = authenticate(["SafetyOfficer"])
    ins = get_inspection(inspection_id)
    if ins["status"] != "SCHEDULED":
        fail("ERR_INVALID_INSPECTION_STATUS", "only a SCHEDULED inspection can be recorded")
    data = body(request)
    outcome = req_enum(data, "outcome", ("PASS", "FAIL"))
    if outcome == "FAIL":
        reason = data.get("failure_reason")
        if not isinstance(reason, str) or reason == "":
            fail("ERR_VALIDATION", "failure_reason is required when outcome is FAIL")
    else:
        reason = None
    it = db.equipment[ins["equipment_item_id"]]
    ins["recorded_by_user_id"] = uid
    if outcome == "PASS":
        ins["status"] = "RECORDED_PASS"
        if it["status"] == "INSPECTION_DUE":
            it["status"] = "PASSED"
            touch(it)
    else:
        ins["status"] = "RECORDED_FAIL"
        ins["failure_reason"] = reason
        if it["status"] == "INSPECTION_DUE":
            it["failure_count"] += 1
            it["status"] = "BANNED" if it["failure_count"] == 2 else "FAILED"
            touch(it)
    touch(ins)
    _cancel_other_scheduled(it["id"], ins["id"])
    return success(serializers.inspection(ins), 200)


@bp.post("/inspections/<inspection_id>/waive")
def waive_inspection(inspection_id):
    uid, _ = authenticate(["SafetyOfficer"])
    ins = get_inspection(inspection_id)
    if ins["status"] != "RECORDED_FAIL":
        fail("ERR_INVALID_INSPECTION_STATUS", "only a RECORDED_FAIL inspection can be waived")
    # Segregation of duties (priority 6) precedes body shape (priority 7).
    if uid == ins["recorded_by_user_id"]:
        fail("ERR_SOD_SELF_WAIVER", "the recording officer cannot waive their own failure")
    waiver_reason = req_str(body(request), "waiver_reason")
    ins["status"] = "WAIVED"
    ins["waived_by_user_id"] = uid
    ins["waiver_reason"] = waiver_reason
    touch(ins)
    it = db.equipment[ins["equipment_item_id"]]
    if it["status"] == "FAILED":
        it["status"] = "WAIVED"
        touch(it)
    return success(serializers.inspection(ins), 200)
