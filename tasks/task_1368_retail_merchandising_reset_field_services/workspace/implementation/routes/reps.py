from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("reps", __name__)
COLL = "reps"


@bp.post("/reps")
def create_rep():
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin"})
    body = mw.get_body()
    rep = db.base_fields()
    rep.update({
        "full_name": mw.req_str(body, "full_name"),
        "employment_type": mw.req_enum(body, "employment_type", {"W2", "C1099"}),
        "home_base_commute_miles": mw.req_int(body, "home_base_commute_miles", min_val=0),
        "mileage_rate_cents": mw.req_int(body, "mileage_rate_cents", min_val=0),
        "travel_minute_rate_cents": mw.req_int(body, "travel_minute_rate_cents", min_val=0),
        "mileage_policy": mw.req_enum(body, "mileage_policy", {"HOME_BASED", "FIRST_STOP"}),
        "status": "ACTIVE",
    })
    db.collections[COLL][rep["id"]] = rep
    return resp.success_object(db.serialize(rep), 201)


@bp.get("/reps")
def list_reps():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "PayrollAdmin"})
    items = list(db.collections[COLL].values())
    et = mw.request.args.get("employment_type")
    if et is not None:
        items = [r for r in items if r["employment_type"] == et]
    st = mw.request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/reps/<rid>")
def get_rep(rid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "PayrollAdmin", "FieldRep"})
    rep = db.collections[COLL].get(rid)
    if rep is None:
        raise errors.not_found("rep not found")
    if role == "FieldRep" and rep["id"] != uid:
        raise errors.unauthorized("rep acting on another rep")
    return resp.success_object(db.serialize(rep))


@bp.get("/reps/<rid>/mileage-logs")
def list_rep_mileage_logs(rid):
    uid, role = mw.auth()
    mw.require_role(role, {"PayrollAdmin", "ProjectManager", "FieldRep"})
    rep = db.collections[COLL].get(rid)
    if rep is None:
        raise errors.not_found("rep not found")
    if role == "FieldRep" and rep["id"] != uid:
        raise errors.unauthorized("rep acting on another rep")
    items = [l for l in db.collections["mileage_logs"].values() if l["rep_id"] == rid]
    st = mw.request.args.get("status")
    if st is not None:
        items = [l for l in items if l["status"] == st]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)
