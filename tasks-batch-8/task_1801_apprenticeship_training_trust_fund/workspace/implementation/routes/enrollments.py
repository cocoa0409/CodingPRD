"""ClassEnrollment endpoints: create, get, list, drop."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("enrollments", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def enrollment_view(e):
    return {
        "id": e["id"],
        "class_id": e["class_id"],
        "apprentice_id": e["apprentice_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def get_enrollment_or_404(eid):
    e = db.class_enrollments.get(eid)
    if e is None:
        raise errors.err_enrollment_not_found()
    return e


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["class_id", "apprentice_id"])
    if not mw.is_str(body["class_id"]):
        raise errors.err_invalid_request("class_id must be a string")
    cls = db.training_classes.get(body["class_id"])
    if cls is None:
        raise errors.err_class_not_found()
    if not mw.is_str(body["apprentice_id"]):
        raise errors.err_invalid_request("apprentice_id must be a string")
    appr = db.apprentices.get(body["apprentice_id"])
    if appr is None:
        raise errors.err_apprentice_not_found()

    if appr["program_status"] != "INDENTURED":
        raise errors.err_apprentice_not_indentured()
    if appr["registration_status"] != "REGISTERED":
        raise errors.err_registration_required()
    # One ENROLLED enrollment per apprentice per class
    for e in db.class_enrollments.values():
        if (e["class_id"] == cls["id"] and e["apprentice_id"] == appr["id"]
                and e["status"] == "ENROLLED"):
            raise errors.err_duplicate_enrollment()
    ledger.recompute_enrolled_count(cls)
    if cls["enrolled_count"] >= cls["capacity"]:
        raise errors.err_class_full()

    eid = db.new_id()
    now = db.now_iso()
    enr = {
        "id": eid,
        "class_id": cls["id"],
        "apprentice_id": appr["id"],
        "status": "ENROLLED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.class_enrollments[eid] = enr
    ledger.recompute_enrolled_count(cls)
    return success_object(enrollment_view(enr), 201)


@bp.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    mw.require_roles(*ALL_ROLES)
    return success_object(enrollment_view(get_enrollment_or_404(eid)), 200)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    cid = request.args.get("class_id")
    aid = request.args.get("apprentice_id")
    status = request.args.get("status")
    items = list(db.class_enrollments.values())
    if cid is not None:
        items = [e for e in items if e["class_id"] == cid]
    if aid is not None:
        items = [e for e in items if e["apprentice_id"] == aid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: (db._parse_iso(e["created_at"]), e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([enrollment_view(e) for e in page], limit, offset, total)


@bp.route("/enrollments/<eid>/drop", methods=["POST"])
def drop_enrollment(eid):
    mw.require_roles("TrustAdmin")
    enr = get_enrollment_or_404(eid)
    if enr["status"] != "ENROLLED":
        raise errors.err_enrollment_not_open()
    enr["status"] = "DROPPED"
    ledger.touch(enr)
    cls = db.training_classes.get(enr["class_id"])
    if cls is not None:
        ledger.recompute_enrolled_count(cls)
    return success_object(enrollment_view(enr), 200)
