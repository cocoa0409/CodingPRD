"""POST /_clock/set_current_utc — test-driving logical clock endpoint."""

from db import db
from errors import err
from middleware import require_roles
from response import success_object
from routes import bp
from services.lifecycle import sweep
from util import body, parse_dt


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"PlatformOperator"})
    data = body()
    if "to_iso8601" not in data:
        raise err("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required")
    target = parse_dt(data.get("to_iso8601"), "to_iso8601")
    with db.lock:
        db.current_utc = target
        sweep()
    # Echo the value the client supplied.
    return success_object({"current_utc": data["to_iso8601"]})
