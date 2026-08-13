"""Tier matrix CRUD + publish."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    bump,
    get_json_body,
    get_pagination,
    new_common_fields,
    paginate,
    require_fields,
    resolve_program,
    resolve_tier_matrix,
    sort_by_created_at,
)

bp = Blueprint("tier_matrices", __name__)

MATRIX_READ_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
)

VALID_CATEGORIES = {"QUALIFYING_CAT_A", "QUALIFYING_CAT_B"}


@bp.route("/settlement-programs/<pid>/tier-matrices", methods=["POST"])
def create_tier_matrix(pid):
    user_id, role = require_role("ProgramAdministrator")
    prog = resolve_program(pid)
    body = get_json_body()
    require_fields(
        body,
        ["injury_category", "severity_score_min", "severity_score_max", "base_award_cents"],
    )

    cat = body["injury_category"]
    if cat not in VALID_CATEGORIES:
        raise ApiError(ERR_INVALID_REQUEST, "injury_category must be QUALIFYING_CAT_A or QUALIFYING_CAT_B", 400)

    tm = {
        "settlement_program_id": pid,
        "injury_category": cat,
        "severity_score_min": body["severity_score_min"],
        "severity_score_max": body["severity_score_max"],
        "base_award_cents": body["base_award_cents"],
        "matrix_state": "DRAFT",
    }
    tm.update(new_common_fields())
    db.tier_matrices[tm["id"]] = tm
    return success_envelope(tm, 201, "object")


@bp.route("/settlement-programs/<pid>/tier-matrices", methods=["GET"])
def list_tier_matrices(pid):
    user_id, role = require_role(*MATRIX_READ_ROLES)
    prog = resolve_program(pid)
    limit, offset = get_pagination()

    items = [t for t in db.tier_matrices.values() if t["settlement_program_id"] == pid]

    # Optional filters
    state_filter = request.args.get("matrix_state")
    if state_filter:
        items = [t for t in items if t["matrix_state"] == state_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/tier-matrices/<tmid>", methods=["GET"])
def get_tier_matrix(pid, tmid):
    user_id, role = require_role(*MATRIX_READ_ROLES)
    prog, tm = resolve_tier_matrix(pid, tmid)
    return success_envelope(tm, 200, "object")


@bp.route("/settlement-programs/<pid>/tier-matrices/<tmid>/publish", methods=["POST"])
def publish_tier_matrix(pid, tmid):
    user_id, role = require_role("ProgramAdministrator")
    prog, tm = resolve_tier_matrix(pid, tmid)

    if tm["matrix_state"] != "DRAFT":
        raise ApiError(ERR_INVALID_REQUEST, "Only DRAFT matrix rows can be published", 400)

    # Supersede overlapping PUBLISHED rows of the same category
    for other in db.tier_matrices.values():
        if (
            other["settlement_program_id"] == pid
            and other["id"] != tmid
            and other["matrix_state"] == "PUBLISHED"
            and other["injury_category"] == tm["injury_category"]
        ):
            # Check overlap: ranges overlap if max(min1,min2) <= min(max1,max2)
            lo = max(tm["severity_score_min"], other["severity_score_min"])
            hi = min(tm["severity_score_max"], other["severity_score_max"])
            if lo <= hi:
                other["matrix_state"] = "SUPERSEDED"
                bump(other)

    tm["matrix_state"] = "PUBLISHED"
    bump(tm)

    # Update program matrix_published flag
    if not prog["matrix_published"]:
        prog["matrix_published"] = True
        bump(prog)

    return success_envelope(tm, 200, "object")
