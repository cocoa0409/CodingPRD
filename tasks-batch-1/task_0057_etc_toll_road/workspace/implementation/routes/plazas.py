from flask import Blueprint
import errors
from errors import err
from db import db, init_common
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, paginate, sorted_by_created)
from serialize import public, public_list

bp = Blueprint("plazas", __name__)


@bp.post("/etc/plazas")
def create_plaza():
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    base_rate = require_int(body, "base_rate_cents", gt=0)
    peak_mult = require_int(body, "peak_multiplier_bps", required=False, default=0, min_value=0)
    axle_surcharge = require_int(body, "axle_surcharge_cents", required=False, default=0, min_value=0)
    hov_min = require_int(body, "hov_min_occupants", required=False, default=3, min_value=2)
    plate_surcharge = require_int(body, "plate_surcharge_bps", required=False, default=5000, min_value=0)

    plaza = {
        "name": name,
        "state_code": state_code,
        "base_rate_cents": base_rate,
        "peak_multiplier_bps": peak_mult,
        "axle_surcharge_cents": axle_surcharge,
        "hov_min_occupants": hov_min,
        "plate_surcharge_bps": plate_surcharge,
    }
    init_common(plaza)
    db.plazas[plaza["id"]] = plaza
    return success(public(plaza), status=201)


@bp.get("/etc/plazas/<pid>")
def get_plaza(pid):
    _, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    p = db.plazas.get(pid)
    if p is None:
        raise err(errors.ERR_NOT_FOUND, "Plaza not found")
    return success(public(p))


@bp.get("/etc/plazas/<pid>/toll-transactions")
def list_plaza_transactions(pid):
    _, role = get_auth()
    require_roles(role, {"TollOperator", "SystemAdmin"})
    p = db.plazas.get(pid)
    if p is None:
        raise err(errors.ERR_NOT_FOUND, "Plaza not found")
    items = [t for t in db.toll_transactions.values() if t["plaza_id"] == pid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)
