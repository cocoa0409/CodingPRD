from flask import Blueprint

import db
import middleware as mw
import response as resp
import services

bp = Blueprint("clock", __name__)


@bp.post("/set_current_utc")
def set_current_utc():
    """Test-driving endpoint: advance the server's logical clock. Runs the
    rework-authorization expiry sweep against the new current date."""
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    target = mw.req_datetime(body, "to_iso8601")
    db.set_clock(target)
    services.rework_expiry_sweep()
    return resp.success_object({"current_utc": db.fmt_ts(db.now())})
