"""Records: registration, listing, detail, metadata correction."""
from flask import Blueprint, request

from db import db, new_id, touch, bump
from errors import err, not_found, invalid_enum
from middleware import authenticate, body_json, READ_STAFF
from response import success_object, success_list, paginate
from serializers import record_view
from services.core import (
    derive_posture, recompute_record_schedule, adjust_stale_for_record)
from utils import check_str, check_number, check_bool, check_datetime

bp = Blueprint("records", __name__)

POSTURES = {"UNSCHEDULED", "HELD", "CONFLICT_BLOCKED", "ELIGIBLE", "RETAINED"}


@bp.route("/ig/records", methods=["POST"])
def create_record():
    authenticate(["RecordsManager"])
    body = body_json()
    program_id = check_str(body, "program_id")
    record_class_id = check_str(body, "record_class_id")
    jurisdiction_id = check_str(body, "jurisdiction_id")
    title = check_str(body, "title")
    source_system = check_str(body, "source_system")
    event_date = check_datetime(body, "event_date")
    size_gb = check_number(body, "size_gb", minimum=0, min_exclusive=True)
    owner_custodian_id = check_str(body, "owner_custodian_id", required=False)
    auto_delete_enabled = check_bool(body, "auto_delete_enabled",
                                     required=False, default=True)
    # Body-referenced entity existence
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    rclass = db.record_classes.get(record_class_id)
    if rclass is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced record class does not exist")
    jur = db.jurisdictions.get(jurisdiction_id)
    if jur is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced jurisdiction does not exist")
    owner = None
    if owner_custodian_id is not None:
        owner = db.custodians.get(owner_custodian_id)
        if owner is None:
            raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                      "Referenced custodian does not exist")
    # Same-program integrity
    if (rclass["program_id"] != program_id or jur["program_id"] != program_id
            or (owner is not None and owner["program_id"] != program_id)):
        raise err("ERR_CROSS_PROGRAM_REFERENCE", 409,
                  "Referenced entity belongs to a different program")
    rec = {
        "id": new_id(),
        "program_id": program_id,
        "record_class_id": record_class_id,
        "jurisdiction_id": jurisdiction_id,
        "owner_custodian_id": owner_custodian_id,
        "title": title,
        "source_system": source_system,
        "event_date": event_date,
        "size_gb": size_gb,
        "auto_delete_enabled": True if auto_delete_enabled is None else auto_delete_enabled,
        "retention_due_date": None,
        "governing_rule_id": None,
        "destroyed_at": None,
        "status": "ACTIVE",
    }
    touch(rec)
    db.records[rec["id"]] = rec
    recompute_record_schedule(rec)
    return success_object(record_view(rec), 201)


@bp.route("/ig/records", methods=["GET"])
def list_records():
    authenticate(READ_STAFF)
    items = list(db.records.values())
    a = request.args
    posture_filter = a.get("disposition_posture")
    if posture_filter is not None and posture_filter not in POSTURES:
        invalid_enum("disposition_posture must be one of %s"
                     % sorted(POSTURES))
    for f in ("program_id", "record_class_id", "jurisdiction_id",
              "owner_custodian_id", "governing_rule_id", "status"):
        v = a.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    if posture_filter is not None:
        items = [r for r in items if derive_posture(r) == posture_filter]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([record_view(r) for r in window], limit, offset, total)


@bp.route("/ig/records/<recordId>", methods=["GET"])
def get_record(recordId):
    authenticate(READ_STAFF)
    rec = db.records.get(recordId)
    if rec is None:
        not_found("Record not found")
    return success_object(record_view(rec))


@bp.route("/ig/records/<recordId>", methods=["PATCH"])
def patch_record(recordId):
    authenticate(["RecordsManager"])
    rec = db.records.get(recordId)
    if rec is None:
        not_found("Record not found")
    body = body_json()
    # Shape
    title = check_str(body, "title", required=False)
    size_gb = check_number(body, "size_gb", required=False, minimum=0,
                           min_exclusive=True)
    event_date = check_datetime(body, "event_date", required=False)
    # Destroyed-record protection
    if rec["status"] == "DESTROYED":
        raise err("ERR_RECORD_ALREADY_DESTROYED", 409,
                  "A DESTROYED record cannot be patched")
    old_posture = derive_posture(rec)
    if title is not None:
        rec["title"] = title
    if size_gb is not None:
        rec["size_gb"] = size_gb
    event_changed = event_date is not None and event_date != rec["event_date"]
    if event_date is not None:
        rec["event_date"] = event_date
    bump(rec)
    if event_changed:
        recompute_record_schedule(rec)
        adjust_stale_for_record(rec, old_posture, derive_posture(rec))
    return success_object(record_view(rec))
