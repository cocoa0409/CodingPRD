"""Record endpoints (PRD §3.3)."""
from flask import Blueprint

from db import STORE, now_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    paginate, path_case, path_record, touch,
    transcripts_for_record,
)
from services.workflows import create_filing

bp = Blueprint("records", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
TERMINAL_RECORD = ("FILED",)


@bp.get("/appellate/cases/<cid>/record")
def get_case_record(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [r for r in STORE.records.values() if r["case_id"] == case["id"]]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/records/<rid>")
def get_record(rid):
    auth = get_auth()
    require_roles(auth, ALL)
    rec = path_record(rid)
    out = dict(rec)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/records/<rid>/designate")
def designate_record(rid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    rec = path_record(rid)
    if rec["status"] in TERMINAL_RECORD:
        raise ApiError("ERR_ALREADY_TERMINAL", "Record is in a terminal state", 409)
    case = STORE.cases.get(rec["case_id"])
    if rec["status"] != "PENDING_DESIGNATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Record must be PENDING_DESIGNATION to designate", 409)
    # Preconditions: no transcripts yet; case posture RECORD_PENDING
    orders = transcripts_for_record(rec["id"])
    if any(o["status"] != "CANCELLED" for o in orders):
        raise ApiError("ERR_INVALID_STATE",
                       "Transcript orders already exist under this record", 409)
    if case and case.get("posture") != "RECORD_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Case posture must be RECORD_PENDING to designate", 409)
    rec["status"] = "DESIGNATED"
    rec["designated_at"] = now_iso()
    touch(rec)
    out = dict(rec)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/records/<rid>/revoke-designation")
def revoke_designation(rid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    rec = path_record(rid)
    if rec["status"] in TERMINAL_RECORD:
        raise ApiError("ERR_ALREADY_TERMINAL", "Record is in a terminal state", 409)
    if rec["status"] != "DESIGNATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Record must be DESIGNATED to revoke designation", 409)
    orders = transcripts_for_record(rec["id"])
    if any(o["status"] in ("DELIVERED", "FILED") for o in orders):
        raise ApiError("ERR_INVALID_STATE",
                       "Cannot revoke: transcripts already delivered", 409)
    rec["status"] = "PENDING_DESIGNATION"
    rec["designated_at"] = None
    touch(rec)
    for o in orders:
        if o["status"] in ("ORDERED", "IN_PREPARATION"):
            o["status"] = "CANCELLED"
            touch(o)
    out = dict(rec)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/records/<rid>/file")
def file_record(rid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    rec = path_record(rid)
    if rec["status"] in TERMINAL_RECORD:
        raise ApiError("ERR_ALREADY_TERMINAL", "Record is in a terminal state", 409)
    if rec["status"] != "COMPLETE":
        raise ApiError("ERR_INVALID_STATE",
                       "Record must be COMPLETE to file", 409)
    rec["status"] = "FILED"
    touch(rec)
    case = STORE.cases.get(rec["case_id"])
    create_filing(case, "RECORD", "EFILE", [], brief_id=None)
    out = dict(rec)
    out.pop("_seq", None)
    return success_object(out)
