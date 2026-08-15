"""SurveyVendor endpoints (PRD 3.1): OCC-guarded registration with supersede,
list, get, suspend."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_STALE_PROGRAM_VERSION, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list
from serializers import vendor_view
from services.core import active_vendor_for_program
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    get_or_404, parse_pagination, paginate, sort_created, query_arg,
    is_int, require_field,
)
from errors import ERR_INVALID_REQUEST

bp = Blueprint("vendors", __name__)


@bp.route("/api/vendors", methods=["POST"])
@require_roles("ProgramAdmin")
def create_vendor(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(
        body, {"program_id", "name", "cycle_budget_cents", "expected_program_version"})
    program_id = require_string(body, "program_id")
    name = require_string(body, "name")
    budget = require_int(body, "cycle_budget_cents", minimum=0)
    expected = require_field(body, "expected_program_version")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "Field expected_program_version must be an integer")

    program = get_or_404(db.programs, program_id, "SurveyProgram")

    # OCC (priority 3.6): checked before any business rule.
    if expected != program["version"]:
        raise_err(
            ERR_STALE_PROGRAM_VERSION,
            f"expected_program_version {expected} does not match current program version",
        )

    vendor = db.stamp_new({
        "program_id": program["id"],
        "name": name,
        "cycle_budget_cents": budget,
        "cycle_budget_remaining_cents": budget,
        "status": "ACTIVE",
        "superseded_at": None,
    })
    db.vendors[vendor["id"]] = vendor

    # Supersede the previously ACTIVE vendor (PRD 3.1).
    prior = active_vendor_for_program(program["id"])
    if prior is not None and prior["id"] != vendor["id"]:
        prior["status"] = "SUPERSEDED"
        prior["superseded_at"] = db.clock_now()
        db.touch(prior)

    program["active_vendor_id"] = vendor["id"]
    db.touch(program)  # registration increments SurveyProgram.version by 1

    return success_object(vendor_view(vendor), 201)


@bp.route("/api/vendors", methods=["GET"])
@require_roles("Any")
def list_vendors(_user_id: str, _role: str):
    items = list(db.vendors.values())
    program_id = query_arg("program_id")
    status = query_arg("status")
    if program_id is not None:
        items = [v for v in items if v["program_id"] == program_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([vendor_view(v) for v in page], limit, offset, total)


@bp.route("/api/vendors/<vendorId>", methods=["GET"])
@require_roles("Any")
def get_vendor(vendorId: str, _user_id: str, _role: str):
    vendor = get_or_404(db.vendors, vendorId, "SurveyVendor")
    return success_object(vendor_view(vendor))


@bp.route("/api/vendors/<vendorId>/suspend", methods=["POST"])
@require_roles("ProgramAdmin")
def suspend_vendor(vendorId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    vendor = get_or_404(db.vendors, vendorId, "SurveyVendor")
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE vendor can be suspended")
    vendor["status"] = "SUSPENDED"
    db.touch(vendor)

    # Recompute the program's active_vendor_id (null when this was the only
    # ACTIVE vendor).
    program = db.programs.get(vendor["program_id"])
    if program is not None:
        successor = active_vendor_for_program(program["id"])
        program["active_vendor_id"] = successor["id"] if successor else None
        db.touch(program)

    return success_object(vendor_view(vendor))
