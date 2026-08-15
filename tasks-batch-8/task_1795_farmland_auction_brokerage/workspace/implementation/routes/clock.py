"""POST /api/_clock/set_current_utc — test-driving logical clock, plus shared helpers."""

import uuid

from flask import Blueprint

import db
from errors import raise_err, ERR_NOT_FOUND
from middleware import auth, require_roles
from response import success_object, get_body, as_datetime, fmt_dt
from services import sweeps

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    _, role = auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    to_dt = as_datetime(body, "to_iso8601")
    db.set_clock(to_dt)
    sweeps.run_all_sweeps(to_dt)
    return success_object({"current_utc": fmt_dt(db.clock_now())})


# --- shared lookup helpers used across route modules -----------------------

def get_or_404(store, entity_id, what):
    ent = store.get(entity_id)
    if ent is None:
        raise_err(ERR_NOT_FOUND, f"{what} not found: {entity_id}")
    return ent


def new_id():
    return str(uuid.uuid4())
