"""Program configuration (PRD §3.1).

A Program has a unique code in {PRECHECK, GLOBAL_ENTRY}, a name, base_fee_cents
>= 0, validity_years in {3,4,5}, three thresholds in 0..100 with
vetting_deny_threshold strictly > vetting_risk_threshold, redress_min_score in
0..100, and renewal_window_days >= 0 (default 180).
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_int,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
)
from services.lookups import get_or_404, program_by_code

bp = Blueprint("programs", __name__)

READ_ROLES = ["SchedulingAdmin", "VettingOfficer", "EnrollmentOfficer", "AppealsOfficer", "Applicant"]


@bp.route("/programs", methods=["POST"])
def create_program():
    require_auth(["SchedulingAdmin"])
    body = get_body()
    require_fields(body, [
        "code", "name", "base_fee_cents", "validity_years",
        "vetting_risk_threshold", "vetting_deny_threshold", "redress_min_score",
    ])
    code = require_enum(body, "code", ["PRECHECK", "GLOBAL_ENTRY"])
    name = require_str(body, "name")
    base_fee_cents = require_int(body, "base_fee_cents", minimum=0)
    validity_years = require_int(body, "validity_years")
    if validity_years not in (3, 4, 5):
        raise APIError(ERR_INVALID_REQUEST, 422, "validity_years must be one of {3,4,5}")
    risk_threshold = require_int(body, "vetting_risk_threshold", minimum=0, maximum=100)
    deny_threshold = require_int(body, "vetting_deny_threshold", minimum=0, maximum=100)
    if deny_threshold <= risk_threshold:
        raise APIError(ERR_INVALID_REQUEST, 422,
                       "vetting_deny_threshold must be strictly greater than vetting_risk_threshold")
    redress_min = require_int(body, "redress_min_score", minimum=0, maximum=100)
    renewal_window = optional_int(body, "renewal_window_days", default=180, minimum=0)

    if program_by_code(code) is not None:
        raise APIError(ERR_INVALID_REQUEST, 422, "Program code must be unique across all programs")

    rec = {
        "code": code,
        "name": name,
        "base_fee_cents": base_fee_cents,
        "validity_years": validity_years,
        "vetting_risk_threshold": risk_threshold,
        "vetting_deny_threshold": deny_threshold,
        "redress_min_score": redress_min,
        "renewal_window_days": renewal_window,
    }
    stamp_create(rec)
    db.programs[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/programs", methods=["GET"])
def list_programs():
    require_auth(READ_ROLES)
    limit, offset = parse_pagination()
    code = request.args.get("code")
    items = list(db.programs.values())
    if code is not None:
        items = [p for p in items if p.get("code") == code]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_auth(READ_ROLES)
    rec = get_or_404(db.programs, pid, "Program")
    return ok_object(serialize(rec), 200)
