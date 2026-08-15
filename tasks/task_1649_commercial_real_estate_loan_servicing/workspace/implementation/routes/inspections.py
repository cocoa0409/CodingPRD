from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import posture
from services.common import parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import inspection as ser_insp, inspector as ser_inspector
from services.validate import body_json, opt_str, require_fields, req_enum, req_str

bp = Blueprint("inspections", __name__)

RATINGS = ("GOOD", "FAIR", "POOR", "CRITICAL")


@bp.post("/inspectors")
def create_inspector():
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    data = body_json()
    require_fields(data, ["full_name", "license_no"])
    name = req_str(data, "full_name")
    lic = req_str(data, "license_no")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise errors.invalid_request("active must be a boolean")
    for i in db.inspectors.values():
        if i["license_no"] == lic:
            raise errors.invalid_request("license_no must be unique across inspectors")
    insp = {
        "id": db.new_id(),
        "full_name": name,
        "license_no": lic,
        "active": active,
    }
    stamp_new(insp)
    db.inspectors[insp["id"]] = insp
    return success(ser_inspector(insp), status=201)


@bp.get("/inspectors/<iid>")
def get_inspector(iid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Inspector"])
    insp = db.inspectors.get(iid)
    if not mw.read_scope_allows(actor, "inspector", insp):
        raise errors.not_found("Inspector not found")
    return success(ser_inspector(insp))


@bp.get("/inspectors/<iid>/inspections")
def inspector_schedule(iid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Inspector"])
    insp = db.inspectors.get(iid)
    if insp is None:
        raise errors.not_found("Inspector not found")
    if actor["role"] == "Inspector" and actor["user_id"] != iid:
        raise errors.not_found("Inspector not found")
    limit, offset = get_pagination()
    items = [i for i in db.inspections.values() if i["inspector_id"] == iid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    page, pg = paginate([ser_insp(i) for i in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/properties/<pid>/inspections")
def schedule_inspection(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")
    data = body_json()
    require_fields(data, ["inspector_id", "scheduled_start", "scheduled_end"])
    inspector_id = req_str(data, "inspector_id")
    if inspector_id not in db.inspectors:
        raise errors.not_found("inspector_id does not reference an existing inspector")
    start = parse_dt(data.get("scheduled_start"), "scheduled_start")
    end = parse_dt(data.get("scheduled_end"), "scheduled_end")
    if end <= start:
        raise errors.invalid_request("scheduled_end must be strictly after scheduled_start")
    # Half-open [start, end) conflict among the inspector's SCHEDULED inspections.
    for i in db.inspections.values():
        if i["inspector_id"] != inspector_id or i["status"] != "SCHEDULED":
            continue
        if start < i["scheduled_end_dt"] and i["scheduled_start_dt"] < end:
            raise errors.ApiError(
                errors.ERR_INSPECTOR_SCHEDULE_CONFLICT,
                "Inspector has a conflicting scheduled inspection", 409)
    insp = {
        "id": db.new_id(),
        "property_id": pid,
        "inspector_id": inspector_id,
        "scheduled_start": db.fmt_ts(start),
        "scheduled_start_dt": start,
        "scheduled_end": db.fmt_ts(end),
        "scheduled_end_dt": end,
        "status": "SCHEDULED",
        "condition_rating": None,
        "findings": None,
        "completed_at": None,
        "completed_at_dt": None,
    }
    stamp_new(insp)
    db.inspections[insp["id"]] = insp
    return success(ser_insp(insp), status=201)


@bp.get("/properties/<pid>/inspections")
def list_property_inspections(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    prop = db.properties.get(pid)
    if not mw.read_scope_allows(actor, "property", prop):
        raise errors.not_found("Property not found")
    limit, offset = get_pagination()
    items = [i for i in db.inspections.values() if i["property_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    page, pg = paginate([ser_insp(i) for i in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/inspections/<iid>/close")
def close_inspection(iid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "Inspector"])
    insp = db.inspections.get(iid)
    if insp is None:
        raise errors.not_found("PropertyInspection not found")
    data = body_json()
    require_fields(data, ["outcome"])
    outcome = req_enum(data, "outcome", ("COMPLETED", "CANCELLED"))
    # Role/outcome fit: Inspector completes; MasterServicer cancels.
    if outcome == "COMPLETED" and actor["role"] != "Inspector":
        raise errors.unauthorized("Only the assigned Inspector may complete an inspection")
    if outcome == "CANCELLED" and actor["role"] != "MasterServicer":
        raise errors.unauthorized("Only a MasterServicer may cancel an inspection")
    if outcome == "COMPLETED":
        # Inspector self-assignment ownership (priority 3).
        if actor["user_id"] != insp["inspector_id"]:
            raise errors.ownership("Inspector may only complete its own assigned inspections")
        if "condition_rating" not in data or data["condition_rating"] is None:
            raise errors.invalid_request("condition_rating is required for COMPLETED")
        rating = req_enum(data, "condition_rating", RATINGS)
        findings = opt_str(data, "findings", default=None)
    else:
        rating = None
        findings = opt_str(data, "findings", default=None)
    if insp["status"] != "SCHEDULED":
        raise errors.invalid_state("Inspection is no longer SCHEDULED")
    prop = db.properties.get(insp["property_id"])
    loan = db.loans.get(prop["loan_id"]) if prop else None
    if outcome == "COMPLETED":
        insp["status"] = "COMPLETED"
        insp["condition_rating"] = rating
        insp["findings"] = findings
        insp["completed_at_dt"] = db.get_clock()
        insp["completed_at"] = db.fmt_ts(db.get_clock())
        touch(insp)
        if loan is not None:
            if rating in ("POOR", "CRITICAL"):
                posture.create_watchlist_entry(
                    loan, "POOR_INSPECTION", source_ref=insp["id"])
            posture.reevaluate_servicing(loan)
            posture.reevaluate_risk(loan)
            posture.reevaluate_servicing(loan)
    else:
        insp["status"] = "CANCELLED"
        touch(insp)
    return success(ser_insp(insp))
