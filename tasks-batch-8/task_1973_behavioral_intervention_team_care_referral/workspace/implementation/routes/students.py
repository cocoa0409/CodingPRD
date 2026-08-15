from flask import Blueprint

import errors as E
import response
from db import store, new_record, touch, serialize
from errors import ApiError
from middleware import require_auth, ALL_ROLES
from routes.util import body, get_or_404

bp = Blueprint("students", __name__)


@bp.post("/bit/students")
def create_student():
    require_auth(["SystemAdmin"])
    b = body()
    external_ref = b.get("external_ref")
    full_name = b.get("full_name")
    if not isinstance(external_ref, str) or not external_ref:
        raise ApiError(E.ERR_VALIDATION, 400, "external_ref is required")
    if not isinstance(full_name, str) or not full_name:
        raise ApiError(E.ERR_VALIDATION, 400, "full_name is required")
    rec = new_record()
    rec.update(
        {"external_ref": external_ref, "full_name": full_name, "enrollment_status": "ENROLLED"}
    )
    store.students[rec["id"]] = rec
    return response.obj(serialize(rec), 201)


@bp.get("/bit/students/<sid>")
def get_student(sid):
    require_auth(list(ALL_ROLES))
    rec = get_or_404(store.students, sid, "student")
    return response.obj(serialize(rec))


@bp.patch("/bit/students/<sid>")
def patch_student(sid):
    require_auth(["SystemAdmin"])
    rec = get_or_404(store.students, sid, "student")
    b = body()
    if "enrollment_status" in b:
        value = b.get("enrollment_status")
        # LEAVE_OF_ABSENCE is owned by the leave/re-entry cascades; a direct
        # administrative edit attempting to set it is an invalid value.
        if value not in ("ENROLLED", "WITHDRAWN"):
            raise ApiError(
                E.ERR_VALIDATION,
                400,
                "enrollment_status may only be set to ENROLLED or WITHDRAWN administratively",
            )
        rec["enrollment_status"] = value
        touch(rec)
    return response.obj(serialize(rec))
