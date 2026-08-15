"""Logical clock + Association endpoints."""
from flask import Blueprint

from db import STORE, set_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_object
from serialize import ser_association
from services.core import run_periodic_review, stamp_new, touch
from util import as_dt, as_str, as_str_list, body, fmt_iso, need, new_id

bp = Blueprint("associations", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth_uid, role = auth()
    require_role(role, ["System"])
    b = body()
    to = as_dt(need(b, "to_iso8601"), "to_iso8601")
    set_clock(to)
    return ok_object({"current_utc": fmt_iso(to)}, code=200)


@bp.route("/associations", methods=["POST"])
def create_association():
    auth_uid, role = auth()
    require_role(role, ["AssociationBoard"])
    b = body()
    name = as_str(need(b, "name"), "name")
    charter = as_str(need(b, "charter_number"), "charter_number")
    assoc = stamp_new({
        "id": new_id(),
        "name": name,
        "charter_number": charter,
        "review_index": 0,
        "active_disaster_declarations": [],
    })
    STORE.associations[assoc["id"]] = assoc
    return ok_object(ser_association(assoc), code=201)


@bp.route("/associations/<aid>", methods=["GET"])
def get_association(aid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    assoc = STORE.associations.get(aid)
    if assoc is None:
        raise_err("ERR_NOT_FOUND", "Association not found")
    return ok_object(ser_association(assoc))


@bp.route("/associations/<aid>/declare_disaster", methods=["POST"])
def declare_disaster(aid):
    auth_uid, role = auth()
    require_role(role, ["AssociationBoard"])
    b = body()
    disaster_ref = as_str(need(b, "disaster_ref"), "disaster_ref")
    counties = as_str_list(need(b, "counties"), "counties")
    start_date = as_dt(need(b, "start_date"), "start_date")
    end_date = as_dt(need(b, "end_date"), "end_date")
    if end_date <= start_date:
        raise_err("ERR_INVALID_REQUEST", "end_date must be after start_date")
    assoc = STORE.associations.get(aid)
    if assoc is None:
        raise_err("ERR_NOT_FOUND", "Association not found")
    assoc["active_disaster_declarations"].append({
        "disaster_ref": disaster_ref, "counties": list(counties),
        "start_date": start_date, "end_date": end_date,
    })
    touch(assoc)
    return ok_object(ser_association(assoc))


@bp.route("/associations/<aid>/run_periodic_review", methods=["POST"])
def periodic_review(aid):
    auth_uid, role = auth()
    require_role(role, ["System", "LoanOfficer"])
    assoc = STORE.associations.get(aid)
    if assoc is None:
        raise_err("ERR_NOT_FOUND", "Association not found")
    run_periodic_review(assoc)
    return ok_object(ser_association(assoc))
