"""Claimant CRUD."""

import re

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    get_json_body,
    get_pagination,
    new_common_fields,
    paginate,
    require_fields,
    resolve_program,
    resolve_claimant,
    sort_by_created_at,
)

bp = Blueprint("claimants", __name__)

CLAIMANT_READ_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
    "ClaimantRole",
)

CLAIMANT_LIST_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
)

VALID_INJURY_CATEGORIES = {"QUALIFYING_CAT_A", "QUALIFYING_CAT_B", "NON_QUALIFYING"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SSN_RE = re.compile(r"^\d{4}$")


@bp.route("/settlement-programs/<pid>/claimants", methods=["POST"])
def create_claimant(pid):
    user_id, role = require_role("IntakeSpecialist")
    prog = resolve_program(pid)
    body = get_json_body()
    require_fields(body, [
        "full_name", "date_of_birth", "ssn_last4",
        "date_of_exposure_start", "date_of_exposure_end",
        "date_of_diagnosis", "injury_category", "represented_by_counsel",
    ])

    # Validate ssn_last4: exactly 4 numeric chars
    ssn = body["ssn_last4"]
    if not isinstance(ssn, str) or not SSN_RE.match(ssn):
        raise ApiError(ERR_INVALID_REQUEST, "ssn_last4 must be exactly 4 numeric characters", 400)

    # Validate date fields
    for df in ["date_of_birth", "date_of_exposure_start", "date_of_exposure_end", "date_of_diagnosis"]:
        v = body[df]
        if not isinstance(v, str) or not DATE_RE.match(v):
            raise ApiError(ERR_INVALID_REQUEST, "%s must be YYYY-MM-DD" % df, 400)

    cat = body["injury_category"]
    if cat not in VALID_INJURY_CATEGORIES:
        raise ApiError(ERR_INVALID_REQUEST, "injury_category must be QUALIFYING_CAT_A, QUALIFYING_CAT_B, or NON_QUALIFYING", 400)

    if not isinstance(body["represented_by_counsel"], bool):
        raise ApiError(ERR_INVALID_REQUEST, "represented_by_counsel must be a boolean", 400)

    claimant = {
        "settlement_program_id": pid,
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "ssn_last4": body["ssn_last4"],
        "date_of_exposure_start": body["date_of_exposure_start"],
        "date_of_exposure_end": body["date_of_exposure_end"],
        "date_of_diagnosis": body["date_of_diagnosis"],
        "injury_category": cat,
        "represented_by_counsel": body["represented_by_counsel"],
        "duplicate_of_claimant_id": None,
    }
    claimant.update(new_common_fields())
    db.claimants[claimant["id"]] = claimant
    return success_envelope(claimant, 201, "object")


@bp.route("/settlement-programs/<pid>/claimants", methods=["GET"])
def list_claimants(pid):
    user_id, role = require_role(*CLAIMANT_LIST_ROLES)
    prog = resolve_program(pid)
    limit, offset = get_pagination()

    items = [c for c in db.claimants.values() if c["settlement_program_id"] == pid]

    sp_filter = request.args.get("settlement_program_id")
    if sp_filter:
        items = [c for c in items if c["settlement_program_id"] == sp_filter]

    dup_filter = request.args.get("duplicate_of_claimant_id")
    if dup_filter:
        items = [c for c in items if c.get("duplicate_of_claimant_id") == dup_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/claimants/<clid>", methods=["GET"])
def get_claimant(pid, clid):
    user_id, role = require_role(*CLAIMANT_READ_ROLES)
    prog, claimant = resolve_claimant(pid, clid)

    # ClaimantRole ownership check
    if role == "ClaimantRole" and user_id != clid:
        raise ApiError(ERR_NOT_FOUND, "Claimant not found", 404)

    return success_envelope(claimant, 200, "object")
