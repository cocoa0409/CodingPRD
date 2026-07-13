from flask import Blueprint

import db
import core
import ser
import find
from core import ApiError

bp = Blueprint("drivers", __name__)


@bp.post("/drivers")
@core.require_auth(["ProgramAdmin"])
def create_driver():
    body = core.get_body()
    full_name = core.require_field(body, "full_name", "str")
    phone = core.require_field(body, "phone", "str")
    rec = db.base_record()
    rec.update({"full_name": full_name, "phone": phone, "status": "PENDING"})
    db.drivers[rec["id"]] = rec
    return core.ok_object(ser.driver(rec), 201)


@bp.get("/drivers")
@core.require_auth(core.ALL_ROLES)
def list_drivers():
    status = core.request.args.get("status")
    items = list(db.drivers.values())
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.driver(d) for d in page], limit, offset, total)


@bp.post("/drivers/<did>/activate")
@core.require_auth(["ProgramAdmin"])
def activate_driver(did):
    d = find.driver(did)
    if d["status"] != "PENDING":
        raise ApiError("ERR_DRIVER_NOT_PENDING", 409, "driver must be PENDING to activate")
    d["status"] = "ACTIVE"
    db.touch(d)
    return core.ok_object(ser.driver(d))
