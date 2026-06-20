"""Borrower endpoints (§3.2)."""
import re

from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common

bp = Blueprint("borrowers", __name__)

READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return val


@bp.route("/borrowers", methods=["POST"])
def create_borrower():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["lender_id", "full_name", "birthdate"])
    lender = db.lenders.get(body["lender_id"])
    if lender is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lender not found")
    if not isinstance(body["full_name"], str) or body["full_name"].strip() == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "full_name must be a non-empty string")
    birthdate = body["birthdate"]
    if not isinstance(birthdate, str) or not _DATE_RE.match(birthdate):
        raise errors.err(errors.ERR_INVALID_REQUEST, "birthdate must be YYYY-MM-DD")
    is_nbs = _require_bool(body, "is_non_borrowing_spouse", False)
    nbs_qual = _require_bool(body, "nbs_qualifies", False)
    rec = {
        "lender_id": body["lender_id"],
        "full_name": body["full_name"],
        "birthdate": birthdate,
        "is_non_borrowing_spouse": is_nbs,
        "nbs_qualifies": nbs_qual,
        "occupancy_status": "OCCUPYING",
    }
    db.stamp_create(rec)
    db.borrowers[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/borrowers/<borrower_id>", methods=["GET"])
def get_borrower(borrower_id):
    user_id, role = get_user_context()
    require_role(role, {"ServicerOps", "ComplianceOfficer", "HudAuditor", "Borrower"})
    rec = db.borrowers.get(borrower_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Borrower not found")
    if role == "Borrower" and user_id != borrower_id:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Borrower may only access own record")
    return success(public(rec))


@bp.route("/borrowers", methods=["GET"])
def list_borrowers():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.borrowers.values())
    lender_id = request.args.get("lender_id")
    if lender_id is not None:
        rows = [r for r in rows if r["lender_id"] == lender_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)
