"""Program endpoints: create (Registrar) and read (any authenticated role)."""

from flask import Blueprint

import errors
from db import _new_id, now, store
from middleware import authenticate, get_body, require_roles
from response import success
from serializers import pub_program
from services import audit
from services.metrics import to_decimal

bp = Blueprint("programs", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@bp.post("/sap/programs")
def create_program():
    authenticate()
    require_roles("Registrar")
    body = get_body()

    # Business rule order: code uniqueness (19) precedes body well-formedness (22).
    code = body.get("code")
    if isinstance(code, str):
        for p in store.programs.values():
            if p["code"] == code:
                errors.fail(errors.ERR_PROGRAM_CODE_CONFLICT,
                            "Program code %s already exists" % code)

    if not isinstance(code, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "code is required")
    name = body.get("name")
    if not isinstance(name, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "name is required")
    required_credits = body.get("required_credits")
    if not _is_int(required_credits):
        errors.fail(errors.ERR_INVALID_REQUEST, "required_credits must be an integer")

    min_gpa = body.get("min_gpa", 2.0)
    if not _is_num(min_gpa):
        errors.fail(errors.ERR_INVALID_REQUEST, "min_gpa must be a number")
    min_pace_pct = body.get("min_pace_pct", 67.0)
    if not _is_num(min_pace_pct):
        errors.fail(errors.ERR_INVALID_REQUEST, "min_pace_pct must be a number")
    appeal_window_days = body.get("appeal_window_days", 14)
    if not _is_int(appeal_window_days):
        errors.fail(errors.ERR_INVALID_REQUEST, "appeal_window_days must be an integer")
    reminder_offset_days = body.get("reminder_offset_days", [7, 13])
    if (not isinstance(reminder_offset_days, list)
            or any(not _is_int(d) for d in reminder_offset_days)):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "reminder_offset_days must be an array of integers")

    ts = now()
    row = {
        "id": _new_id(),
        "code": code,
        "name": name,
        "required_credits": required_credits,
        "min_gpa": to_decimal(min_gpa),
        "min_pace_pct": to_decimal(min_pace_pct),
        "appeal_window_days": appeal_window_days,
        "reminder_offset_days": list(reminder_offset_days),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.programs[row["id"]] = row
    audit.record("PROGRAM_CREATED", "Program", row["id"], None, None, pub_program(row))
    return success(pub_program(row), status=201)


@bp.get("/sap/programs/<pid>")
def get_program(pid):
    authenticate()
    require_roles("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")
    row = store.programs.get(pid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Program %s does not exist" % pid)
    return success(pub_program(row))
