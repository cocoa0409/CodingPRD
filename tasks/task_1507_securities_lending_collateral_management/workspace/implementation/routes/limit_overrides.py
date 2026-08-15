"""Limit override endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import _touch
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_date_string,
    get_or_404, paginate, serialize_common,
)

bp = Blueprint("limit_overrides", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "RiskOfficer", "OpsSettler"]


@bp.route("/api/borrowers/<borrower_id>/limit-overrides", methods=["POST"])
def create_override(borrower_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    borrower = get_or_404(db.borrowers, borrower_id, "Borrower")
    body = get_json_body()
    require_fields(body, ["new_limit_cents", "effective_from", "expires_at"])
    validate_positive_int(body["new_limit_cents"], "new_limit_cents")
    validate_date_string(body["effective_from"], "effective_from")
    validate_date_string(body["expires_at"], "expires_at")

    if body["effective_from"] >= body["expires_at"]:
        raise errors.make_error(errors.ERR_INVALID_WINDOW, "effective_from must be strictly before expires_at")

    override = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "borrower_id": borrower_id,
        "new_limit_cents": body["new_limit_cents"],
        "effective_from": body["effective_from"],
        "expires_at": body["expires_at"],
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "status": "REQUESTED",
    }
    db.limit_overrides[override["id"]] = override
    return success_object(serialize_common(override), 201)


@bp.route("/api/limit-overrides/<override_id>", methods=["GET"])
def get_override(override_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    ov = get_or_404(db.limit_overrides, override_id, "LimitOverride")
    return success_object(serialize_common(ov))


@bp.route("/api/limit-overrides", methods=["GET"])
def list_overrides():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.limit_overrides.values())
    borrower_filter = request.args.get("borrower_id")
    status_filter = request.args.get("status")
    if borrower_filter:
        items = [o for o in items if o["borrower_id"] == borrower_filter]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(o) for o in page], limit, offset, total)


@bp.route("/api/limit-overrides/<override_id>/approve", methods=["POST"])
def approve_override(override_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    ov = get_or_404(db.limit_overrides, override_id, "LimitOverride")
    if ov["status"] != "REQUESTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Override is not REQUESTED")

    # SoD: approver != requester
    if user_id == ov["requested_by_user_id"]:
        raise errors.make_error(errors.ERR_SOD_VIOLATION, "Approver cannot be the requester")

    # Window overlap check vs APPROVED overrides for same borrower
    for other in db.limit_overrides.values():
        if (other["id"] != ov["id"]
                and other["borrower_id"] == ov["borrower_id"]
                and other["status"] == "APPROVED"):
            # Half-open overlap: [a_start, a_end) overlaps [b_start, b_end) iff a_start < b_end and b_start < a_end
            if ov["effective_from"] < other["expires_at"] and other["effective_from"] < ov["expires_at"]:
                raise errors.make_error(errors.ERR_OVERRIDE_WINDOW_OVERLAP, "Window overlaps an APPROVED override")

    ov["status"] = "APPROVED"
    ov["decided_by_user_id"] = user_id
    _touch(ov)

    # Recompute borrower effective limit
    borrower = db.borrowers[ov["borrower_id"]]
    calc.recompute_borrower_derived(borrower)

    return success_object(serialize_common(ov))


@bp.route("/api/limit-overrides/<override_id>/reject", methods=["POST"])
def reject_override(override_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    ov = get_or_404(db.limit_overrides, override_id, "LimitOverride")
    if ov["status"] != "REQUESTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Override is not REQUESTED")
    ov["status"] = "REJECTED"
    ov["decided_by_user_id"] = user_id
    _touch(ov)
    return success_object(serialize_common(ov))
