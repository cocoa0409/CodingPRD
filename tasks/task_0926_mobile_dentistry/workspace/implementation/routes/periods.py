"""The logical clock control and the programme-period axis."""

from flask import Blueprint

import clock
import serializers
import store
import validation as v
from envelope import object_response
from errors import ApiError
from constants import ENUM_PERIOD_TO_STATUS
from timefmt import render_instant

bp = Blueprint("periods", __name__)


# --------------------------------------------------------------------------
# POST /_clock/set_current_utc
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    v.authenticate(["ProgramAdmin"])
    body = v.body()
    instant = v.req_instant(body, "to_iso8601")
    clock.set_now(instant)
    return object_response({"current_utc": render_instant(clock.now())}, 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/program-periods
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/program-periods", methods=["POST"])
def create_program_period():
    v.authenticate(["ProgramAdmin"])
    body = v.body()
    name = v.req_string(body, "name", min_len=1, max_len=120)
    starts_on = v.req_date(body, "starts_on")
    ends_on = v.req_date(body, "ends_on")
    if not starts_on < ends_on:
        raise ApiError("ERR_VALIDATION", "starts_on must be strictly before ends_on.")
    row = store.insert("program_periods", {
        "name": name,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "status": "OPEN",
        "frozen_at": None,
        "state_submission_ref": None,
    })
    v.mark_minted(row)
    return object_response(serializers.program_period(row), 201)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/program-periods/{id}
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/program-periods/<period_id>", methods=["GET"])
def read_program_period(period_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "BillingSpecialist", "FieldDentist"])
    row = v.path_row("program_periods", period_id)
    return object_response(serializers.program_period(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/program-periods/{id}/status
# --------------------------------------------------------------------------
DECLARED_PERIOD_LEGS = {
    ("OPEN", "REPORTING"),
    ("REPORTING", "OPEN"),
    ("SUBMITTED", "REPORTING"),
    ("SUBMITTED", "CLOSED"),
}


@bp.route("/mobile-dentistry/program-periods/<period_id>/status", methods=["POST"])
def change_program_period_status(period_id):
    v.authenticate(["ProgramAdmin"])
    row = v.path_row("program_periods", period_id)
    body = v.body()
    v.enum_type_check(body, "to_status", required=True)
    to_status = v.check_enum(body, "to_status", ENUM_PERIOD_TO_STATUS)

    # Rung 11 -- only the declared legs move.
    if (row["status"], to_status) not in DECLARED_PERIOD_LEGS:
        raise ApiError("ERR_INVALID_STATE")

    if row["status"] == "SUBMITTED" and to_status == "REPORTING":
        row["frozen_at"] = None
    row["status"] = to_status
    v.touch(row)
    return object_response(serializers.program_period(row), 200)
