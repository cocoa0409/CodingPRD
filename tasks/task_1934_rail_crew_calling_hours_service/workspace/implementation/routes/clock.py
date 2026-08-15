from flask import Blueprint

from db import store, fmt_dt
from middleware import auth, require_roles
from response import ok
from services import run_expiry_sweep
from validators import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    data = body()
    to_iso8601 = req_dt(data, "to_iso8601")
    _, role = auth()
    require_roles(role, ("CrewManager",))
    store.now = to_iso8601
    expired_ids = run_expiry_sweep()
    return ok({
        "now_iso8601": fmt_dt(store.now),
        "expired_call_ids": expired_ids,
    })
