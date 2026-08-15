from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("mileage", __name__)
COLL = "mileage_logs"


def _get_log_or_404(lid):
    log = db.collections[COLL].get(lid)
    if log is None:
        raise errors.not_found("mileage log not found")
    return log


def _recompute(log):
    rep = db.collections["reps"].get(log["rep_id"])
    if rep is None:
        return
    log["mileage_pay_cents"] = services.compute_mileage_pay_cents(log, rep)
    log["travel_time_pay_cents"] = services.compute_travel_time_pay_cents(log, rep)


@bp.post("/mileage-logs")
def create_mileage_log():
    uid, role = mw.auth()
    mw.require_role(role, {"FieldRep"})
    body = mw.get_body()
    # Priority 3: existence, left-to-right (rep_id, then assignment_id).
    rep = None
    rid = body.get("rep_id")
    if rid is not None:
        if not isinstance(rid, str) or rid not in db.collections["reps"]:
            raise errors.not_found("rep not found")
        rep = db.collections["reps"][rid]
    assignment = None
    aid = body.get("assignment_id")
    if aid is not None:
        if not isinstance(aid, str) or aid not in db.collections["assignments"]:
            raise errors.not_found("assignment not found")
        assignment = db.collections["assignments"][aid]
    # Ownership (entity-backed identity): a rep submits only their own logs.
    if rep is not None and rep["id"] != uid:
        raise errors.unauthorized("rep submitting a mileage log for another rep")
    # Priority 4: only logs whose assignment reached SUBMITTED or VERIFIED are payable.
    if assignment is not None and assignment["status"] not in ("SUBMITTED", "VERIFIED"):
        raise errors.invalid_state("assignment has not reached SUBMITTED")
    # Priority 5: the assignment must belong to the claiming rep.
    if assignment is not None and rep is not None and assignment["rep_id"] != rid:
        raise errors.cross_entity_mismatch("assignment is not owned by the claiming rep")
    # Priority 13: input sanitization.
    if rep is None:
        raise errors.invalid_request("rep_id is required")
    if assignment is None:
        raise errors.invalid_request("assignment_id is required")
    log = db.base_fields()
    log.update({
        "rep_id": rid,
        "assignment_id": aid,
        "round_trip_miles": mw.req_int(body, "round_trip_miles", min_val=0),
        "home_to_first_stop_miles": mw.req_int(body, "home_to_first_stop_miles", min_val=0),
        "drive_minutes": mw.req_int(body, "drive_minutes", min_val=0),
        "mileage_pay_cents": 0,
        "travel_time_pay_cents": 0,
        "status": "SUBMITTED",
    })
    _recompute(log)
    db.collections[COLL][log["id"]] = log
    return resp.success_object(db.serialize(log), 201)


@bp.get("/mileage-logs")
def list_mileage_logs():
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin", "ProjectManager", "FieldRep"})
    items = list(db.collections[COLL].values())
    if role == "FieldRep":
        items = [l for l in items if l["rep_id"] == uid]
    for key in ("rep_id", "assignment_id", "status"):
        v = mw.request.args.get(key)
        if v is not None:
            items = [l for l in items if l.get(key) == v]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/mileage-logs/<lid>")
def get_mileage_log(lid):
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin", "ProjectManager", "FieldRep"})
    log = _get_log_or_404(lid)
    if role == "FieldRep" and log["rep_id"] != uid:
        raise errors.unauthorized("rep acting on another rep's mileage log")
    return resp.success_object(db.serialize(log))


@bp.post("/mileage-logs/<lid>/approve")
def approve_mileage_log(lid):
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin"})
    log = _get_log_or_404(lid)
    if log["status"] != "SUBMITTED":
        raise errors.invalid_state("mileage log is not SUBMITTED")
    rep = db.collections["reps"].get(log["rep_id"])
    if rep is None or rep["status"] != "ACTIVE":
        raise errors.invalid_state("owning rep is not ACTIVE")
    # Recompute and freeze pay amounts.
    _recompute(log)
    log["status"] = "APPROVED"
    db.touch(log)
    return resp.success_object(db.serialize(log))


@bp.post("/mileage-logs/<lid>/reject")
def reject_mileage_log(lid):
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin"})
    log = _get_log_or_404(lid)
    if log["status"] != "SUBMITTED":
        raise errors.invalid_state("mileage log is not SUBMITTED")
    log["status"] = "REJECTED"
    db.touch(log)
    return resp.success_object(db.serialize(log))


@bp.post("/mileage-logs/<lid>/pay")
def pay_mileage_log(lid):
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin"})
    log = _get_log_or_404(lid)
    if log["status"] != "APPROVED":
        raise errors.invalid_state("mileage log is not APPROVED")
    log["status"] = "PAID"
    db.touch(log)
    return resp.success_object(db.serialize(log))
