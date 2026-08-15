"""Crew endpoints: register, get, start_shift, end_shift."""
from flask import Blueprint

from db import db, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object
from errors import raise_err, ERR_INVALID_STATE_TRANSITION
from services.core import (
    get_body, req_string, req_enum, req_int, new_common, bump,
    get_crew, serialize_crew, CREW_TYPES,
)

bp = Blueprint("crews", __name__)


@bp.route("/om/crews", methods=["POST"])
def create_crew():
    require_roles(["Dispatcher"])
    body = get_body()
    code = req_string(body, "crew_code")
    ctype = req_enum(body, "crew_type", CREW_TYPES)
    base = req_string(body, "home_base")
    rate = req_int(body, "hourly_rate_cents", minimum=0)
    c = new_common()
    c.update({
        "crew_code": code,
        "crew_type": ctype,
        "home_base": base,
        "hourly_rate_cents": rate,
        "crew_status": "OFF_DUTY",
        "shift_started_at": None,
    })
    db.crews[c["id"]] = c
    return success_object(serialize_crew(c), status=201)


@bp.route("/om/crews/<cid>", methods=["GET"])
def get_one(cid):
    require_roles(ALL_ROLES)
    c = get_crew(cid)
    return success_object(serialize_crew(c))


@bp.route("/om/crews/<cid>/start_shift", methods=["POST"])
def start_shift(cid):
    require_roles(["Dispatcher"])
    c = get_crew(cid)
    if c["crew_status"] != "OFF_DUTY":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Crew in {c['crew_status']} cannot start a shift")
    c["crew_status"] = "AVAILABLE"
    c["shift_started_at"] = iso_ms(db.now())
    bump(c)
    return success_object(serialize_crew(c))


@bp.route("/om/crews/<cid>/end_shift", methods=["POST"])
def end_shift(cid):
    require_roles(["Dispatcher"])
    c = get_crew(cid)
    # Only AVAILABLE -> OFF_DUTY is accepted: a crew EN_ROUTE or ON_SITE on any
    # non-terminal work order cannot go off duty.
    if c["crew_status"] in ("EN_ROUTE", "ON_SITE"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Crew EN_ROUTE or ON_SITE cannot go off duty")
    for w in db.work_orders.values():
        if w.get("assigned_crew_id") == cid and \
                w["execution_status"] in ("DISPATCHED", "IN_PROGRESS"):
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "Crew has non-terminal work orders in flight")
    if c["crew_status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Crew in {c['crew_status']} cannot end a shift")
    c["crew_status"] = "OFF_DUTY"
    bump(c)
    return success_object(serialize_crew(c))
