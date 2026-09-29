"""Practice registration and reads."""
import re

from flask import Blueprint

from db import db, new_record
from errors import ApiError
from middleware import authorize
from response import object_response
from routes.helpers import ALL_ROLES, send
from services.domain import path_row
from services.practice import compliance_summary
from validation import read_body, v_int, v_string

bp = Blueprint("practices", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/practices")
def create_practice():
    authorize("PracticeAdministrator")
    body = read_body(
        required=("name", "state_code", "recovery_bay_count"),
        optional=("turnover_buffer_minutes", "consignment_credit_limit_cents"),
    )
    name = v_string(body, "name", min_len=1, max_len=120)
    state_code = v_string(body, "state_code")
    if not STATE_CODE_RE.match(state_code):
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'state_code' must be exactly two uppercase letters.")
    recovery_bay_count = v_int(body, "recovery_bay_count", minimum=1, maximum=12)
    turnover_buffer_minutes = v_int(body, "turnover_buffer_minutes", minimum=0, maximum=120, default=15)
    credit_limit = v_int(body, "consignment_credit_limit_cents", minimum=0, default=500000)

    practice = new_record({
        "name": name,
        "state_code": state_code,
        "recovery_bay_count": recovery_bay_count,
        "turnover_buffer_minutes": turnover_buffer_minutes,
        "consignment_credit_limit_cents": credit_limit,
        "sedation_privilege_state": "UNPERMITTED",
        "open_adverse_event_count": 0,
        "consignment_committed_cents": 0,
    })
    db.practices[practice["id"]] = practice
    return send(practice, 201)


@bp.get("/practices/<practice_id>")
def read_practice(practice_id):
    authorize(*ALL_ROLES)
    practice = path_row(db.practices, practice_id)
    return send(practice)


@bp.get("/practices/<practice_id>/compliance-summary")
def read_compliance_summary(practice_id):
    authorize(*ALL_ROLES)
    practice = path_row(db.practices, practice_id)
    return object_response(compliance_summary(practice))
