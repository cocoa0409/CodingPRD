from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_roles
from response import success, list_success
from services import validate as V
from services.common import new_common, touch, paginate, page_slice
from services.serialize import interchange_out

bp = Blueprint("interchange", __name__)

READ_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}


@bp.post("/interchange-agreements")
def create_agreement():
    _, role = authenticate()
    require_roles(role, {"NetworkAdmin"})
    body = V.get_body(request)
    resort_id = V.require_str(body, "resort_id")
    if db.resorts.get(resort_id) is None:
        raise errors.not_found("Resort not found")
    max_days = V.require_int(body, "max_interchange_days", minimum=1)
    rec = new_common({
        "resort_id": resort_id,
        "max_interchange_days": max_days,
        "status": "ACTIVE",
    })
    db.interchange_agreements[rec["id"]] = rec
    return success(interchange_out(rec), status=201)


@bp.get("/interchange-agreements")
def list_agreements():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = paginate(request.args)
    resort_id = request.args.get("resort_id")
    records = list(db.interchange_agreements.values())
    if resort_id is not None:
        records = [a for a in records if a["resort_id"] == resort_id]
    window, total = page_slice(records, limit, offset)
    return list_success([interchange_out(a) for a in window], limit, offset, total)


@bp.get("/interchange-agreements/<aid>")
def get_agreement(aid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.interchange_agreements.get(aid)
    if rec is None:
        raise errors.not_found("Interchange agreement not found")
    return success(interchange_out(rec))


@bp.post("/interchange-agreements/<aid>/terminate")
def terminate_agreement(aid):
    _, role = authenticate()
    require_roles(role, {"NetworkAdmin"})
    rec = db.interchange_agreements.get(aid)
    if rec is None:
        raise errors.not_found("Interchange agreement not found")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Agreement is not ACTIVE")
    rec["status"] = "TERMINATED"
    touch(rec)
    return success(interchange_out(rec))
