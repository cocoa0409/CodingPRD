"""Caretaker registration and reads (PRD §3.1, §3.8)."""

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_UNIQUENESS_VIOLATION, not_found
from middleware import json_body, require_roles
from response import paginate, success_object
from util import opt_bool, public, req_str, sorted_created, stamp_common

bp = Blueprint("caretakers", __name__)


@bp.post("/tnr/caretakers")
@require_roles("ProgramCoordinator")
def create_caretaker(user_id, role):
    body = json_body()
    full_name = req_str(body, "full_name")
    phone = req_str(body, "phone")
    email = req_str(body, "email")
    certified_tnr = opt_bool(body, "certified_tnr", False)

    if any(c["email"] == email for c in db.caretakers.values()):
        raise ApiError(ERR_UNIQUENESS_VIOLATION, 409,
                       f"A caretaker with email {email!r} already exists.")

    caretaker = stamp_common({
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "certified_tnr": certified_tnr,
        "status": "ACTIVE",
    })
    db.caretakers[caretaker["id"]] = caretaker
    return success_object(public(caretaker), status=201)


@bp.get("/tnr/caretakers/<cid>")
@require_roles("ProgramCoordinator", "Caretaker", "AnimalControlOfficer")
def get_caretaker(cid, user_id, role):
    caretaker = db.caretakers.get(cid)
    if caretaker is None:
        raise not_found("caretaker")
    return success_object(public(caretaker))


@bp.get("/tnr/caretakers/<cid>/vouchers")
@require_roles("ProgramCoordinator", "Caretaker")
def list_caretaker_vouchers(cid, user_id, role):
    if cid not in db.caretakers:
        raise not_found("caretaker")
    rows = [v for v in db.vouchers.values() if v["caretaker_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    return paginate([public(v) for v in sorted_created(rows)])
