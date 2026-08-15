"""Timekeeper endpoints."""

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER

bp = Blueprint("timekeepers", __name__)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/timekeepers", methods=["POST"])
def create_timekeeper(deptId, firmId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, firm = helpers.resolve_firm(deptId, firmId)
    if user_id != firmId:
        raise errors.firm_mismatch()
    body = helpers.get_body()
    helpers.require_fields(body, ["full_name", "tk_class"])
    tk_class = body["tk_class"]
    if tk_class not in ("PARTNER", "ASSOCIATE", "PARALEGAL"):
        raise errors.ApiError(errors.ERR_REFERENTIAL_INTEGRITY, "tk_class must be PARTNER, ASSOCIATE, or PARALEGAL", 422)
    rec = db.base_resource({
        "panel_firm_id": firmId,
        "full_name": body["full_name"],
        "tk_class": tk_class,
        "qualification_status": "PENDING",
    })
    db.timekeepers[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/timekeepers/<tkId>", methods=["GET"])
def get_timekeeper(deptId, firmId, tkId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, tk = helpers.resolve_timekeeper(deptId, firmId, tkId)
    return resp.success_object(resp.public(tk))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/timekeepers", methods=["GET"])
def list_timekeepers(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_firm(deptId, firmId)
    limit, offset = resp.parse_pagination(request.args)
    records = [t for t in db.timekeepers.values() if t.get("panel_firm_id") == firmId]
    records = helpers.apply_filters(records, request.args, ["qualification_status", "tk_class"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/timekeepers/<tkId>/qualify", methods=["POST"])
def qualify_timekeeper(deptId, firmId, tkId):
    require_auth([ROLE_LEGAL_OPS])
    _, firm, tk = helpers.resolve_timekeeper(deptId, firmId, tkId)
    if tk.get("qualification_status") != "PENDING":
        raise errors.invalid_state()
    if firm.get("status") != "ACTIVE":
        raise errors.firm_not_active()
    tk["qualification_status"] = "QUALIFIED"
    db.touch(tk)
    return resp.success_object(resp.public(tk))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/timekeepers/<tkId>/disqualify", methods=["POST"])
def disqualify_timekeeper(deptId, firmId, tkId):
    require_auth([ROLE_LEGAL_OPS])
    _, firm, tk = helpers.resolve_timekeeper(deptId, firmId, tkId)
    if tk.get("qualification_status") != "QUALIFIED":
        raise errors.invalid_state()
    # Refused while any line item in PENDING review status references them.
    for line in db.invoice_line_items.values():
        if line.get("timekeeper_id") == tkId and line.get("review_status") == "PENDING":
            raise errors.timekeeper_has_pending_lines()
    tk["qualification_status"] = "DISQUALIFIED"
    db.touch(tk)
    return resp.success_object(resp.public(tk))
