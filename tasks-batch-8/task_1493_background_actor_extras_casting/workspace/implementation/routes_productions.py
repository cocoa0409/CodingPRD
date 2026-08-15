"""Production endpoints."""
from flask import Blueprint

from db import STORE
from domain import _base, ser_production, touch
from errors import ApiError, ERR_PRODUCTION_NOT_ACTIVE, ERR_PRODUCTION_NOT_FOUND, ERR_PRODUCTION_NOT_WRAPPABLE
from middleware import ALL_ROLES, auth, body, req_str
from response import ok_list, ok_obj, paginate

bp = Blueprint("productions", __name__)


def get_production(pid):
    p = STORE.productions.get(pid)
    if p is None:
        raise ApiError(ERR_PRODUCTION_NOT_FOUND, 404, "Production not found")
    return p


@bp.post("/central-casting/productions")
def create_production():
    auth(["AgencyAdmin"])
    data = body()
    p = _base()
    p.update(
        {
            "title": req_str(data, "title"),
            "studio_code": req_str(data, "studio_code"),
            "payroll_company_name": req_str(data, "payroll_company_name"),
            "status": "SETUP",
            "compliance_index": 100,
        }
    )
    STORE.productions[p["id"]] = p
    return ok_obj(ser_production(p), code=201)


@bp.get("/central-casting/productions")
def list_productions():
    auth(ALL_ROLES)
    rows = sorted(STORE.productions.values(), key=lambda p: p["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_production(p) for p in page], total, limit, offset)


@bp.get("/central-casting/productions/<pid>")
def get_production_route(pid):
    auth(ALL_ROLES)
    return ok_obj(ser_production(get_production(pid)))


@bp.post("/central-casting/productions/<pid>/activate")
def activate_production(pid):
    auth(["AgencyAdmin"])
    p = get_production(pid)
    if p["status"] != "SETUP":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production is not in SETUP")
    p["status"] = "ACTIVE"
    touch(p)
    return ok_obj(ser_production(p))


@bp.post("/central-casting/productions/<pid>/wrap")
def wrap_production(pid):
    auth(["CastingDirector"])
    p = get_production(pid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production is not ACTIVE")
    calls = [c for c in STORE.casting_calls.values() if c["production_id"] == pid]
    if any(c["status"] not in ("WRAPPED", "CANCELLED") for c in calls):
        raise ApiError(
            ERR_PRODUCTION_NOT_WRAPPABLE,
            409,
            "Every casting call must be WRAPPED or CANCELLED before production wrap",
        )
    p["status"] = "WRAPPED"
    # Standby cascade: remaining ACTIVE entries across this production's calls expire.
    call_ids = {c["id"] for c in calls}
    for s in STORE.standby_entries.values():
        if s["casting_call_id"] in call_ids and s["status"] == "ACTIVE":
            s["status"] = "EXPIRED"
            touch(s)
    touch(p)
    return ok_obj(ser_production(p))
