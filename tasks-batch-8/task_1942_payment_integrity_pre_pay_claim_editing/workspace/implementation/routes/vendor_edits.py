"""VendorEdit endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize

bp = Blueprint("vendor_edits", __name__)
PREFIX = "/payment-integrity"


@bp.route(PREFIX + "/vendor-edits", methods=["POST"])
def create_vendor_edit():
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "vendor_name": (True, "string", None),
            "vendor_edit_key": (True, "string", None),
            "description": (False, "string", None),
        },
    )
    ve = db.create_resource(
        "vendor_edits",
        {
            "vendor_name": vals["vendor_name"],
            "vendor_edit_key": vals["vendor_edit_key"],
            "description": vals.get("description", ""),
            "mapped_edit_rule_id": None,
            "comparison_status": "UNMAPPED",
            "conflict_policy": "INTERNAL_FIRST",
        },
    )
    return success_object(serialize(ve), status=201)


@bp.route(PREFIX + "/vendor-edits", methods=["GET"])
def list_vendor_edits():
    require_auth()
    limit, offset = pagination_params()
    vendor_name = request.args.get("vendor_name")
    comparison_status = request.args.get("comparison_status")
    mapped_rule = request.args.get("mapped_edit_rule_id")
    rows = db.all_records("vendor_edits")
    if vendor_name is not None:
        rows = [r for r in rows if r["vendor_name"] == vendor_name]
    if comparison_status is not None:
        if comparison_status not in ("UNMAPPED", "DUPLICATE", "COMPLEMENTARY"):
            raise_err("ERR_INVALID_ENUM", "comparison_status filter carries undeclared member")
        rows = [r for r in rows if r["comparison_status"] == comparison_status]
    if mapped_rule is not None:
        rows = [r for r in rows if r.get("mapped_edit_rule_id") == mapped_rule]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/vendor-edits/<vid>", methods=["GET"])
def get_vendor_edit(vid):
    require_auth()
    ve = db.get("vendor_edits", vid)
    if ve is None:
        raise_err("ERR_VENDOR_EDIT_NOT_FOUND", "Vendor edit not found")
    return success_object(serialize(ve))


@bp.route(PREFIX + "/vendor-edits/<vid>/map", methods=["POST"])
def map_vendor_edit(vid):
    user_id, role = require_auth()
    require_role(role, ["PaymentIntegrityAnalyst"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "edit_rule_id": (True, "string", None),
            "comparison_status": (True, "string", {"DUPLICATE", "COMPLEMENTARY"}),
        },
    )
    ve = db.get("vendor_edits", vid)
    if ve is None:
        raise_err("ERR_VENDOR_EDIT_NOT_FOUND", "Vendor edit not found")
    rule = db.get("edit_rules", vals["edit_rule_id"])
    if rule is None:
        raise_err("ERR_EDIT_RULE_NOT_FOUND", "Edit rule not found")
    ve["mapped_edit_rule_id"] = vals["edit_rule_id"]
    ve["comparison_status"] = vals["comparison_status"]
    db.touch(ve)
    return success_object(serialize(ve))
