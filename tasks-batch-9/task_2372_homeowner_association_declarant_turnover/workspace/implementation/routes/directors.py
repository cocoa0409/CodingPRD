"""Board seats: seating (shared dispatcher on seat_type) and rescission."""
from flask import Blueprint

import auth
import cascades
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("directors", __name__)


@bp.post("/hoa/directors")
def seat_director():
    auth.require_roles(constants.ROLE_DECLARANT, constants.ROLE_ELECTION_INSPECTOR)
    body = v.body()
    auth.require_discriminator_role(body.get("seat_type"), constants.SEAT_TYPE_ROLES)

    case = common.body_turnover_case_or_404(v.get_fk(body, "turnover_case_id"))
    if case is not None and case["trigger_certified_by_user_id"] == auth.current_user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if case is None:
        raise ApiError("ERR_INVALID_REQUEST", "turnover_case_id is required.")

    full_name = v.get_str(body, "full_name", min_len=1, max_len=80)
    seat_type = v.get_enum(body, "seat_type", constants.SEAT_TYPES)

    cascades.require_not_settled_locked(case["association_id"])

    if case["vacant_seats"] < 1:
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED")

    director = new_record({
        "turnover_case_id": case["id"],
        "full_name": full_name,
        "seat_type": seat_type,
        "status": "SEATED",
        "seated_by_user_id": auth.current_user_id(),
        "vacated_at": None,
    })
    db.directors[director["id"]] = director

    cascades.apply_seat_ledger_and_bubble(case)
    return response.object_response(serialize(director), 201)


@bp.post("/hoa/directors/<director_id>/rescind")
def rescind_director(director_id):
    auth.require_roles(constants.ROLE_ELECTION_INSPECTOR)
    director = common.director_or_404(director_id, scoped=True)

    if director["status"] != "SEATED":
        raise ApiError("ERR_DIRECTOR_STATE_INVALID")
    if director["seat_type"] != "OWNER_ELECTED":
        raise ApiError("ERR_DIRECTOR_STATE_INVALID")

    director["status"] = "RESCINDED"
    director["vacated_at"] = util.fmt_dt(clock.now())
    touch(director)

    case = db.turnover_cases.get(director["turnover_case_id"])
    if case is not None:
        cascades.apply_seat_ledger_and_bubble(case)

    return response.object_response(serialize(director))
