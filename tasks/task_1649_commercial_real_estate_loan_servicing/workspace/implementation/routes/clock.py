from flask import Blueprint

import db
import middleware as mw
from response import success
from services import sweep
from services.common import parse_dt
from services.validate import body_json, require_fields

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    data = body_json()
    require_fields(data, ["to_iso8601"])
    target = parse_dt(data.get("to_iso8601"), "to_iso8601")
    db.set_clock(target)
    sweep.run_sweep()
    return success({"current_utc": db.fmt_ts(db.get_clock())})
