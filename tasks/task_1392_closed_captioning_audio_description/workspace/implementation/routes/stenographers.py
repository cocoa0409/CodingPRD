"""Stenographer roster endpoints (PRD §3.6)."""
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, stamp_new, touch
from errors import invalid_transition, not_found, validation
from respond import list_response, ok_object
from util import opt_int, req_dt, req_enum, req_str

bp = Blueprint("stenographers", __name__)

CERTIFICATIONS = {"CERT_CBC", "CERT_CART"}


def get_stenographer(steno_id):
    s = DB.stenographers.get(steno_id)
    if s is None:
        raise not_found("Stenographer not found")
    return s


@bp.post("/caption-ad/stenographers")
@guarded({"Scheduler"})
def create_stenographer(_user_id, _role):
    data = body()
    display_name = req_str(data, "display_name")
    certification = req_enum(data, "certification", CERTIFICATIONS)
    certified_since = req_dt(data, "certified_since")
    cert_valid_until = req_dt(data, "cert_valid_until")
    if cert_valid_until <= certified_since:
        raise validation("Field 'cert_valid_until' must be after 'certified_since'")
    max_daily = opt_int(data, "max_daily_live_minutes", default=300, minimum=1)
    rec = {
        "display_name": display_name,
        "certification": certification,
        "certified_since": certified_since,
        "cert_valid_until": cert_valid_until,
        "max_daily_live_minutes": max_daily,
        "steno_status": "ACTIVE",
        "make_up_minutes_credited": 0,
        "no_show_count": 0,
    }
    stamp_new(rec)
    DB.stenographers[rec["id"]] = rec
    return ok_object(serialize.stenographer(rec), status=201)


@bp.get("/caption-ad/stenographers")
@guarded(set(ALL_ROLES))
def list_stenographers(_user_id, _role):
    records = list(DB.stenographers.values())
    for param, field in (("steno_status", "steno_status"), ("certification", "certification")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.stenographer)


@bp.get("/caption-ad/stenographers/<stenographerId>")
@guarded(set(ALL_ROLES))
def get_one_stenographer(stenographerId, _user_id, _role):
    return ok_object(serialize.stenographer(get_stenographer(stenographerId)))


@bp.post("/caption-ad/stenographers/<stenographerId>/suspend")
@guarded({"Scheduler"})
def suspend_stenographer(stenographerId, _user_id, _role):
    s = get_stenographer(stenographerId)
    if s["steno_status"] != "ACTIVE":
        raise invalid_transition("Only an ACTIVE stenographer can be suspended")
    s["steno_status"] = "SUSPENDED"
    touch(s)
    return ok_object(serialize.stenographer(s))


@bp.post("/caption-ad/stenographers/<stenographerId>/reinstate")
@guarded({"Scheduler"})
def reinstate_stenographer(stenographerId, _user_id, _role):
    s = get_stenographer(stenographerId)
    if s["steno_status"] != "SUSPENDED":
        raise invalid_transition("Only a SUSPENDED stenographer can be reinstated")
    s["steno_status"] = "ACTIVE"
    touch(s)
    return ok_object(serialize.stenographer(s))


@bp.post("/caption-ad/stenographers/<stenographerId>/renew-certification")
@guarded({"Scheduler"})
def renew_certification(stenographerId, _user_id, _role):
    from util import req_dt as _req_dt
    s = get_stenographer(stenographerId)
    new_until = _req_dt(body(), "cert_valid_until")
    if s["steno_status"] != "CERTIFICATION_LAPSED":
        raise invalid_transition("Only a CERTIFICATION_LAPSED stenographer can renew")
    if new_until <= now():
        raise invalid_transition("The new cert_valid_until must be later than the current instant")
    s["cert_valid_until"] = new_until
    s["steno_status"] = "ACTIVE"
    touch(s)
    return ok_object(serialize.stenographer(s))
