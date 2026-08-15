"""Participant endpoints."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, auth, check_ownership
from response import ok
from services import (
    get_participant,
    list_response,
    ser_enrollment,
    ser_participant,
    stamp,
)
from util import as_bool, as_str, body, required

bp = Blueprint("participants", __name__)


@bp.post("/participants")
def create_participant():
    auth(ADMIN)
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    email = as_str(required(data, "email"), "email")
    fee_waiver_eligible = as_bool(
        data.get("fee_waiver_eligible", False), "fee_waiver_eligible"
    )
    for p in DB["participants"].values():
        if p["email"] == email:
            raise ApiError(
                "ERR_VALIDATION", 400, "email must be unique across participants"
            )
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "fee_waiver_eligible": fee_waiver_eligible,
    }
    stamp(rec)
    DB["participants"][rec["id"]] = rec
    return ok(ser_participant(rec), status=201)


@bp.get("/participants/<pid>")
def get_one_participant(pid):
    user_id, role = auth(ANY_ROLE)
    # A participant may only address their own id (priority: authz first).
    check_ownership(pid, user_id, role)
    return ok(ser_participant(get_participant(pid)))


@bp.get("/participants/<pid>/enrollments")
def list_participant_enrollments(pid):
    user_id, role = auth(ANY_ROLE)
    check_ownership(pid, user_id, role)
    get_participant(pid)
    items = [
        e for e in DB["enrollments"].values() if e["participant_id"] == pid
    ]
    return list_response(items, ser_enrollment)
