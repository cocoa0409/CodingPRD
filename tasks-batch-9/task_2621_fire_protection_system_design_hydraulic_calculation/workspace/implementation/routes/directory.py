"""The firm's directories and the logical clock (PRD 3.1, 2.10)."""
from flask import Blueprint

import clock
import db
import response
import validate
from middleware import authenticate
from utils import fmt_dt

bp = Blueprint("directory", __name__)

LICENSE_STATUSES = ["ACTIVE", "EXPIRED", "SUSPENDED"]
ENGINEER_DISCIPLINES = ["FIRE_PROTECTION", "MECHANICAL", "ELECTRICAL"]
REVIEWER_DISCIPLINES = ["FIRE", "BUILDING", "ELECTRICAL"]


@bp.post("/engineers")
def create_engineer():
    authenticate(["FirmAdmin"])
    data = validate.body()
    row = {
        "full_name": validate.req_str(data, "full_name"),
        "license_state": validate.state_code(data, "license_state"),
        "license_number": validate.req_str(data, "license_number"),
        "license_status": validate.opt_str(
            data, "license_status", enum=LICENSE_STATUSES, default="ACTIVE"
        ),
        "discipline": validate.opt_str(
            data, "discipline", enum=ENGINEER_DISCIPLINES, default="FIRE_PROTECTION"
        ),
    }
    db.stamp_create(row, common_fields=False)
    db.engineers[row["id"]] = row
    return response.created(response.public(row))


@bp.post("/ahj-reviewers")
def create_reviewer():
    authenticate(["FirmAdmin"])
    data = validate.body()
    row = {
        "full_name": validate.req_str(data, "full_name"),
        "jurisdiction_code": validate.req_str(data, "jurisdiction_code"),
        "discipline": validate.opt_str(
            data, "discipline", enum=REVIEWER_DISCIPLINES, default="FIRE"
        ),
    }
    db.stamp_create(row, common_fields=False)
    db.ahj_reviewers[row["id"]] = row
    return response.created(response.public(row))


@bp.post("/_clock/set_current_utc")
def set_clock():
    # The sole endpoint that does not require X-User-ID (PRD 2.1).
    authenticate(["FirmAdmin"], require_user_id=False)
    data = validate.body()
    current = validate.req_dt(data, "current_utc")
    clock.set_now(current)
    return response.ok({"current_utc": fmt_dt(clock.now())})
