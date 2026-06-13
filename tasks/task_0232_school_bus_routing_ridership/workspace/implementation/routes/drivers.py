"""Driver endpoints (PRD §3.5)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import err, ERR_INVALID_REFERENCE
from services import validate as v
from services.common import (
    stamp_create, parse_pagination, sorted_by_creation, paginate,
)
from services.domain import driver_public
from services.lookup import get_driver

bp = Blueprint("drivers", __name__)


@bp.post("/drivers")
def create_driver():
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    body = v.get_body()

    district_id = v.require_str(body, "district_id")
    full_name = v.require_str(body, "full_name")
    is_substitute = v.optional_bool(body, "is_substitute", False)

    if district_id not in DB.districts:
        raise err(ERR_INVALID_REFERENCE, "district_id does not resolve")

    rec = {
        "district_id": district_id,
        "full_name": full_name,
        "is_substitute": is_substitute,
        "status": "AVAILABLE",
    }
    stamp_create(rec)
    DB.drivers[rec["id"]] = rec
    return ok(driver_public(rec), 201)


@bp.get("/drivers/<driver_id>")
def get_driver_ep(driver_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Driver"})
    rec = get_driver(driver_id)
    return ok(driver_public(rec), 200)


@bp.get("/drivers")
def list_drivers():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Driver"})
    limit, offset = parse_pagination(request.args)

    district_id = request.args.get("district_id")
    status = request.args.get("status")

    records = list(DB.drivers.values())
    if district_id is not None:
        records = [d for d in records if d["district_id"] == district_id]
    if status is not None:
        records = [d for d in records if d["status"] == status]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([driver_public(d) for d in page], limit, offset, total)
