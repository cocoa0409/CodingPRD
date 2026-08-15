"""TrainingClass endpoints: create (with overlap guards), get, list, complete, cancel."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("classes", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")
TURNOVER = ledger.TURNOVER_MINUTES


def class_view(c):
    return {
        "id": c["id"],
        "trust_fund_id": c["trust_fund_id"],
        "course_code": c["course_code"],
        "instructor_user_id": c["instructor_user_id"],
        "instructor_name": c["instructor_name"],
        "instructor_rate_cents_per_hour": c["instructor_rate_cents_per_hour"],
        "facility": c["facility"],
        "rti_credit_value": c["rti_credit_value"],
        "capacity": c["capacity"],
        "enrolled_count": c["enrolled_count"],
        "start_minute": c["start_minute"],
        "end_minute": c["end_minute"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def get_class_or_404(cid):
    c = db.training_classes.get(cid)
    if c is None:
        raise errors.err_class_not_found()
    return c


@bp.route("/classes", methods=["POST"])
def create_class():
    mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["trust_fund_id", "course_code", "instructor_user_id",
                             "instructor_name", "instructor_rate_cents_per_hour",
                             "facility", "rti_credit_value", "capacity",
                             "start_minute", "end_minute"])
    if not mw.is_str(body["trust_fund_id"]):
        raise errors.err_invalid_request("trust_fund_id must be a string")
    if body["trust_fund_id"] not in db.trust_funds:
        raise errors.err_fund_not_found()
    for f in ("course_code", "instructor_user_id", "instructor_name", "facility"):
        if not mw.is_str(body[f]):
            raise errors.err_invalid_request(f"{f} must be a string")
    rate = body["instructor_rate_cents_per_hour"]
    if not mw.is_int(rate) or rate < 0:
        raise errors.err_invalid_request("instructor_rate_cents_per_hour must be a non-negative integer")
    rti = body["rti_credit_value"]
    if not mw.is_int(rti) or rti < 1:
        raise errors.err_invalid_request("rti_credit_value must be an integer >= 1")
    cap = body["capacity"]
    if not mw.is_int(cap) or cap < 1:
        raise errors.err_invalid_request("capacity must be an integer >= 1")
    start = body["start_minute"]
    end = body["end_minute"]
    if not mw.is_int(start) or start < 0:
        raise errors.err_invalid_request("start_minute must be an integer >= 0")
    if not mw.is_int(end):
        raise errors.err_invalid_request("end_minute must be an integer")
    if end <= start:
        raise errors.err_invalid_class_window()

    fid = body["trust_fund_id"]
    # Overlap guards: only SCHEDULED classes of the same fund block
    for c in db.training_classes.values():
        if c["trust_fund_id"] != fid or c["status"] != "SCHEDULED":
            continue
        # Instructor buffered overlap (30-min turnover buffer)
        if c["instructor_user_id"] == body["instructor_user_id"]:
            if start < c["end_minute"] + TURNOVER and c["start_minute"] < end + TURNOVER:
                raise errors.err_instructor_conflict()
        # Facility half-open overlap [start, end)
        if c["facility"] == body["facility"]:
            if start < c["end_minute"] and c["start_minute"] < end:
                raise errors.err_facility_conflict()

    cid = db.new_id()
    now = db.now_iso()
    cls = {
        "id": cid,
        "trust_fund_id": fid,
        "course_code": body["course_code"],
        "instructor_user_id": body["instructor_user_id"],
        "instructor_name": body["instructor_name"],
        "instructor_rate_cents_per_hour": rate,
        "facility": body["facility"],
        "rti_credit_value": rti,
        "capacity": cap,
        "enrolled_count": 0,
        "start_minute": start,
        "end_minute": end,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.training_classes[cid] = cls
    return success_object(class_view(cls), 201)


@bp.route("/classes/<cid>", methods=["GET"])
def get_class(cid):
    mw.require_roles(*ALL_ROLES)
    return success_object(class_view(get_class_or_404(cid)), 200)


@bp.route("/classes", methods=["GET"])
def list_classes():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    tf = request.args.get("trust_fund_id")
    iid = request.args.get("instructor_user_id")
    fac = request.args.get("facility")
    status = request.args.get("status")
    items = list(db.training_classes.values())
    if tf is not None:
        items = [c for c in items if c["trust_fund_id"] == tf]
    if iid is not None:
        items = [c for c in items if c["instructor_user_id"] == iid]
    if fac is not None:
        items = [c for c in items if c["facility"] == fac]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (db._parse_iso(c["created_at"]), c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([class_view(c) for c in page], limit, offset, total)


@bp.route("/classes/<cid>/complete", methods=["POST"])
def complete_class(cid):
    mw.require_roles("TrustAdmin")
    cls = get_class_or_404(cid)
    body = mw.get_body()
    mw.require_fields(body, ["attended_enrollment_ids"])
    attended = body["attended_enrollment_ids"]
    if not isinstance(attended, list) or any(not isinstance(x, str) for x in attended):
        raise errors.err_invalid_request("attended_enrollment_ids must be an array of strings")
    if cls["status"] != "SCHEDULED":
        raise errors.err_class_not_scheduled()
    # Attendee list integrity: every id must be an ENROLLED enrollment of this class
    for eid in attended:
        e = db.class_enrollments.get(eid)
        if e is None or e["class_id"] != cls["id"] or e["status"] != "ENROLLED":
            raise errors.err_invalid_attendee_list()

    attended_set = set(attended)
    for e in list(db.class_enrollments.values()):
        if e["class_id"] != cls["id"] or e["status"] != "ENROLLED":
            continue
        if e["id"] in attended_set:
            e["status"] = "CREDITED"
            appr = db.apprentices.get(e["apprentice_id"])
            if appr is not None:
                appr["rti_credits_accumulated"] += cls["rti_credit_value"]
                ledger.recompute_wage(appr)
                ledger.touch(appr)
        else:
            e["status"] = "NO_SHOW"
        ledger.touch(e)
    cls["status"] = "COMPLETED"
    ledger.touch(cls)
    ledger.recompute_enrolled_count(cls)
    return success_object(class_view(cls), 200)


@bp.route("/classes/<cid>/cancel", methods=["POST"])
def cancel_class(cid):
    mw.require_roles("TrustAdmin")
    cls = get_class_or_404(cid)
    if cls["status"] != "SCHEDULED":
        raise errors.err_class_not_scheduled()
    # Refused while any pay claim for the class sits in SUBMITTED or APPROVED
    for claim in db.instructor_pay_claims.values():
        if claim["class_id"] == cls["id"] and claim["status"] in ("SUBMITTED", "APPROVED"):
            raise errors.err_invalid_state(
                "class has an open pay claim and cannot be cancelled")
    for e in list(db.class_enrollments.values()):
        if e["class_id"] == cls["id"] and e["status"] == "ENROLLED":
            e["status"] = "DROPPED"
            ledger.touch(e)
    cls["status"] = "CANCELLED"
    ledger.touch(cls)
    ledger.recompute_enrolled_count(cls)
    return success_object(class_view(cls), 200)
