"""Reference-data routes: jurisdictions, statutes, departments, associations."""
from datetime import date

from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_FEE_EXCEEDS_STATUTORY_CAP,
    ERR_NO_STATUTE_IN_FORCE,
    ERR_STATUTE_WINDOW_OVERLAP,
    ERR_DUPLICATE_DEPARTMENT_TYPE,
)
from helpers import (
    body, req_str, opt_str, req_int, opt_int, opt_bool, req_date, opt_date, paginate,
)
from middleware import require_roles, require_any_role
from response import success

bp = Blueprint("reference", __name__)

FAR_FUTURE = date(9999, 12, 31)


# ---------------------------------------------------------------- jurisdictions

@bp.post("/jurisdictions")
def create_jurisdiction():
    require_roles("ProviderAdmin")
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    state_code = req_str(b, "state_code")
    capacity = opt_int(b, "rush_daily_capacity", 5, minimum=0)
    j = {
        "id": db.new_id(), "code": code, "name": name, "state_code": state_code,
        "rush_daily_capacity": capacity, "status": "ACTIVE",
    }
    db.stamp(j)
    db.jurisdictions[j["id"]] = j
    return success(services.ser_jurisdiction(j), 201)


@bp.get("/jurisdictions/<jid>")
def get_jurisdiction(jid):
    require_any_role()
    j = db.jurisdictions.get(jid)
    if j is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    return success(services.ser_jurisdiction(j))


@bp.get("/jurisdictions/<jid>/search-orders")
def list_jurisdiction_search_orders(jid):
    require_any_role()
    if jid not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    items = [o for o in db.search_orders.values() if o["jurisdiction_id"] == jid]
    page, meta = paginate(items)
    return success([services.ser_order(o) for o in page], pagination=meta)


@bp.post("/jurisdictions/<jid>/deactivate")
def deactivate_jurisdiction(jid):
    require_roles("ProviderAdmin")
    j = db.jurisdictions.get(jid)
    if j is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    if j["status"] != "INACTIVE":
        j["status"] = "INACTIVE"
        touch(j)
    return success(services.ser_jurisdiction(j))


# ---------------------------------------------------------------- statutes

@bp.post("/statutes")
def create_statute():
    require_roles("ProviderAdmin")
    b = body()
    jurisdiction_id = req_str(b, "jurisdiction_id")
    effective_from = req_date(b, "effective_from")
    effective_to = opt_date(b, "effective_to")
    response_days = req_int(b, "estoppel_response_days", minimum=0)
    fee_cap = req_int(b, "estoppel_fee_cap_cents", minimum=0)
    validity_days = req_int(b, "estoppel_validity_days", minimum=0)
    if jurisdiction_id not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    # Half-open window overlap; adjacency (new.from == old.to) is allowed.
    new_from, new_to = effective_from, effective_to or FAR_FUTURE
    for s in db.statutes.values():
        if s["jurisdiction_id"] != jurisdiction_id:
            continue
        old_from, old_to = s["effective_from"], s["effective_to"] or FAR_FUTURE
        if new_from < old_to and old_from < new_to:
            raise ApiError(
                ERR_STATUTE_WINDOW_OVERLAP, 422,
                "Statute window overlaps an existing window of this jurisdiction",
            )
    s = {
        "id": db.new_id(), "jurisdiction_id": jurisdiction_id,
        "effective_from": effective_from, "effective_to": effective_to,
        "estoppel_response_days": response_days,
        "estoppel_fee_cap_cents": fee_cap,
        "estoppel_validity_days": validity_days,
    }
    db.stamp(s)
    db.statutes[s["id"]] = s
    return success(services.ser_statute(s), 201)


@bp.get("/statutes/<sid>")
def get_statute(sid):
    require_any_role()
    s = db.statutes.get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Statute not found")
    return success(services.ser_statute(s))


@bp.get("/jurisdictions/<jid>/statutes")
def list_jurisdiction_statutes(jid):
    require_any_role()
    if jid not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    items = [s for s in db.statutes.values() if s["jurisdiction_id"] == jid]
    page, meta = paginate(items)
    return success([services.ser_statute(s) for s in page], pagination=meta)


@bp.get("/statutes/<sid>/search-orders")
def list_statute_search_orders(sid):
    require_any_role()
    if sid not in db.statutes:
        raise ApiError(ERR_NOT_FOUND, 404, "Statute not found")
    items = [o for o in db.search_orders.values() if o["statute_id"] == sid]
    page, meta = paginate(items)
    return success([services.ser_order(o) for o in page], pagination=meta)


# ---------------------------------------------------------------- departments

@bp.post("/departments")
def create_department():
    require_roles("ProviderAdmin")
    b = body()
    jurisdiction_id = req_str(b, "jurisdiction_id")
    dept_type = req_str(b, "dept_type")
    if dept_type not in services.DEPT_TYPES:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "dept_type must be one of " + ", ".join(services.DEPT_TYPES),
        )
    name = req_str(b, "name")
    research_fee = req_int(b, "research_fee_cents", minimum=0)
    rush_surcharge = opt_int(b, "rush_surcharge_cents", 0, minimum=0)
    supports_rush = opt_bool(b, "supports_rush", True)
    if jurisdiction_id not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    for d in db.departments.values():
        if (d["jurisdiction_id"] == jurisdiction_id
                and d["dept_type"] == dept_type and d["status"] == "ACTIVE"):
            raise ApiError(
                ERR_DUPLICATE_DEPARTMENT_TYPE, 409,
                "An ACTIVE department with this dept_type already exists for the jurisdiction",
            )
    d = {
        "id": db.new_id(), "jurisdiction_id": jurisdiction_id, "dept_type": dept_type,
        "name": name, "research_fee_cents": research_fee,
        "rush_surcharge_cents": rush_surcharge, "supports_rush": supports_rush,
        "status": "ACTIVE",
    }
    db.stamp(d)
    db.departments[d["id"]] = d
    return success(services.ser_department(d), 201)


@bp.get("/departments/<did>")
def get_department(did):
    require_any_role()
    d = db.departments.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Department not found")
    return success(services.ser_department(d))


@bp.get("/jurisdictions/<jid>/departments")
def list_jurisdiction_departments(jid):
    require_any_role()
    if jid not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    items = [d for d in db.departments.values() if d["jurisdiction_id"] == jid]
    page, meta = paginate(items)
    return success([services.ser_department(d) for d in page], pagination=meta)


@bp.get("/departments/<did>/research-tasks")
def list_department_research_tasks(did):
    require_any_role()
    if did not in db.departments:
        raise ApiError(ERR_NOT_FOUND, 404, "Department not found")
    items = [t for t in db.research_tasks.values() if t["department_id"] == did]
    page, meta = paginate(items)
    return success([services.ser_task(t) for t in page], pagination=meta)


@bp.post("/departments/<did>/deactivate")
def deactivate_department(did):
    require_roles("ProviderAdmin")
    d = db.departments.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Department not found")
    if d["status"] != "INACTIVE":
        d["status"] = "INACTIVE"
        touch(d)
    return success(services.ser_department(d))


# ---------------------------------------------------------------- associations

@bp.post("/associations")
def create_association():
    require_roles("ProviderAdmin")
    b = body()
    jurisdiction_id = req_str(b, "jurisdiction_id")
    name = req_str(b, "name")
    management_company = req_str(b, "management_company")
    fee = req_int(b, "estoppel_fee_cents", minimum=0)
    validity_days = req_int(b, "estoppel_validity_days", minimum=0)
    if jurisdiction_id not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    statute = services.covering_statute(jurisdiction_id, db.today())
    if statute is None:
        raise ApiError(
            ERR_NO_STATUTE_IN_FORCE, 422,
            "No statute window covers the current clock date for this jurisdiction",
        )
    if fee > statute["estoppel_fee_cap_cents"]:
        raise ApiError(
            ERR_FEE_EXCEEDS_STATUTORY_CAP, 422,
            "Association fee exceeds the in-force statute fee cap",
        )
    a = {
        "id": db.new_id(), "jurisdiction_id": jurisdiction_id, "name": name,
        "management_company": management_company, "estoppel_fee_cents": fee,
        "estoppel_validity_days": validity_days,
    }
    db.stamp(a)
    db.associations[a["id"]] = a
    return success(services.ser_association(a), 201)


@bp.get("/associations/<aid>")
def get_association(aid):
    require_any_role()
    a = db.associations.get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Association not found")
    return success(services.ser_association(a))


@bp.get("/jurisdictions/<jid>/associations")
def list_jurisdiction_associations(jid):
    require_any_role()
    if jid not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    items = [a for a in db.associations.values() if a["jurisdiction_id"] == jid]
    page, meta = paginate(items)
    return success([services.ser_association(a) for a in page], pagination=meta)


@bp.get("/associations/<aid>/search-orders")
def list_association_search_orders(aid):
    require_any_role()
    if aid not in db.associations:
        raise ApiError(ERR_NOT_FOUND, 404, "Association not found")
    items = [o for o in db.search_orders.values() if o["association_id"] == aid]
    page, meta = paginate(items)
    return success([services.ser_order(o) for o in page], pagination=meta)


@bp.get("/associations/<aid>/estoppel-orders")
def list_association_estoppel_orders(aid):
    require_any_role()
    if aid not in db.associations:
        raise ApiError(ERR_NOT_FOUND, 404, "Association not found")
    items = [e for e in db.estoppel_orders.values() if e["association_id"] == aid]
    page, meta = paginate(items)
    return success([services.ser_estoppel(e) for e in page], pagination=meta)
