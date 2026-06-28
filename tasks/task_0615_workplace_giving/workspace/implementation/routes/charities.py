"""Charity vetting endpoints (PRD §3.3)."""
import re

from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_EIN,
    ERR_CHARITY_NOT_ELIGIBLE,
    ERR_MAX_REVIEW_ROUNDS,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_ein,
    optional_bool,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
    EIN_RE,
)

bp = Blueprint("charities", __name__)


def _ein_in_use(program_id, ein, exclude_id=None):
    for c in db.charities.values():
        if c["program_id"] != program_id:
            continue
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        if c["status"] == "REJECTED":
            continue
        if c["ein"] == ein:
            return True
    return False


@bp.route("/charities", methods=["POST"])
def submit_charity():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "legal_name", "ein"])
    program_id = require_string(body, "program_id")
    legal_name = require_string(body, "legal_name")
    ein = require_ein(body, "ein")
    claimed = optional_bool(body, "claimed_501c3", True)

    find_or_404(db.programs, program_id)

    if _ein_in_use(program_id, ein):
        raise err(ERR_DUPLICATE_EIN,
                  "EIN already used by a non-rejected charity in this program")

    rec = {
        "program_id": program_id,
        "legal_name": legal_name,
        "ein": ein,
        "claimed_501c3": claimed,
        "total_received_cents": 0,
        "review_rounds": 0,
        "status": "SUBMITTED",
    }
    stamp_create(rec)
    db.charities[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/charities/<charity_id>", methods=["GET"])
def get_charity(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.charities, charity_id)
    return object_response(serialize(rec), 200)


@bp.route("/charities", methods=["GET"])
def list_charities():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = []
    for c in db.charities.values():
        if program_id is not None and c["program_id"] != program_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(c) for c in page], limit, offset, total, 200)


@bp.route("/charities/<charity_id>/start-review", methods=["POST"])
def start_review(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.charities, charity_id)
    # Allowed from SUBMITTED, or from NEEDS_INFO (revision loop).
    if rec["status"] not in ("SUBMITTED", "NEEDS_INFO"):
        raise err(ERR_INVALID_STATE, "Charity must be SUBMITTED or NEEDS_INFO to start review")
    # Revision loop bound: from NEEDS_INFO only while review_rounds < 3.
    if rec["status"] == "NEEDS_INFO" and rec["review_rounds"] >= 3:
        raise err(ERR_MAX_REVIEW_ROUNDS, "Charity vetting loop exceeded review_rounds < 3 bound")
    rec["status"] = "UNDER_REVIEW"
    rec["review_rounds"] += 1
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/charities/<charity_id>/request-info", methods=["POST"])
def request_info(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.charities, charity_id)
    if rec["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Charity must be UNDER_REVIEW to request info")
    rec["status"] = "NEEDS_INFO"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/charities/<charity_id>/approve", methods=["POST"])
def approve_charity(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.charities, charity_id)
    if rec["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Charity must be UNDER_REVIEW to approve")
    # Eligibility: claimed_501c3 true AND ein well-formed.
    if not rec.get("claimed_501c3") or not EIN_RE.match(rec["ein"]):
        raise err(ERR_CHARITY_NOT_ELIGIBLE,
                  "Charity not eligible: claimed_501c3 must be true and EIN well-formed")
    rec["status"] = "APPROVED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/charities/<charity_id>/reject", methods=["POST"])
def reject_charity(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.charities, charity_id)
    if rec["status"] not in ("UNDER_REVIEW", "NEEDS_INFO"):
        raise err(ERR_INVALID_STATE, "Charity must be UNDER_REVIEW or NEEDS_INFO to reject")
    rec["status"] = "REJECTED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/charities/<charity_id>/suspend", methods=["POST"])
def suspend_charity(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.charities, charity_id)
    if rec["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Charity must be APPROVED to suspend")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/charities/<charity_id>/reinstate", methods=["POST"])
def reinstate_charity(charity_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.charities, charity_id)
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Charity must be SUSPENDED to reinstate")
    rec["status"] = "APPROVED"
    touch(rec)
    return object_response(serialize(rec), 200)
