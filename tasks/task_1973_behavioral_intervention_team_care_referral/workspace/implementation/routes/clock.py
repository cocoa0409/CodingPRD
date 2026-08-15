from flask import Blueprint

import errors as E
import response
from db import store, iso_z, parse_dt
from errors import ApiError
from middleware import require_auth
from routes.util import body
from services.domain import run_sweeps

bp = Blueprint("clock", __name__)


@bp.post("/bit/_clock/set_current_utc")
def set_current_utc():
    require_auth(["SystemAdmin"])
    target = parse_dt(body().get("to_iso8601"))
    if target is None:
        raise ApiError(E.ERR_VALIDATION, 400, "to_iso8601 must be an ISO 8601 UTC timestamp")
    store.clock = target
    run_sweeps()
    return response.obj({"current_utc": iso_z(store.clock)})
