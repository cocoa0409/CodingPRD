"""Business clock endpoints (PRD section 3.4)."""
from flask import Blueprint

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, require_role
from response import success
from serialize import clock_state as ser
import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set-current-date")
def set_current_date():
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    body = validate.get_json_body()
    validate.require_fields(body, ["current_date"])
    current_date = validate.require_date(body, "current_date")

    if db.clock is None:
        db.clock = {
            "id": new_id(),
            "created_at": now_ts(),
            "current_date": current_date,
        }
    else:
        db.clock["current_date"] = current_date
    return success(ser(db.clock), status=200)


@bp.get("/_clock")
def read_clock():
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk",
                        "ScaleOperator", "PermitOfficer", "Contractor"])
    if db.clock is None:
        raise err("ERR_INVALID_REQUEST", "Business clock has not been set")
    return success(ser(db.clock), status=200)
