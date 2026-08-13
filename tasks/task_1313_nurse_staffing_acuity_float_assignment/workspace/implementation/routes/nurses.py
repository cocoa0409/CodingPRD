"""Nurse endpoints, including the weekly hours ledger."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NURSE_NOT_FOUND,
    ERR_HOME_UNIT_RULE_VIOLATED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import UNIT_TYPES, EMPLOYMENT_TYPES, projected_hours, completed_hours
from util import (
    get_json_body,
    req_str,
    req_enum,
    req_int,
    opt_bool,
    parse_iso_date,
    parse_pagination,
    paginate,
    apply_filters,
)

bp = Blueprint("nurses", __name__)


@bp.post("/nurses")
@require_roles("NurseAdmin")
def create_nurse(_user_id: str, _role: str):
    body = get_json_body()
    full_name = req_str(body, "full_name")
    employment_type = req_enum(body, "employment_type", EMPLOYMENT_TYPES)

    if "competencies" not in body or body["competencies"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: competencies")
    competencies = body["competencies"]
    if not isinstance(competencies, list) or len(competencies) == 0:
        raise_err(ERR_INVALID_REQUEST, "competencies must be a non-empty array")
    for c in competencies:
        if not isinstance(c, str) or c not in UNIT_TYPES:
            raise_err(ERR_INVALID_REQUEST, "competencies entries must be valid unit types")

    charge_qualified = opt_bool(body, "charge_qualified", False)
    base_hourly_rate_cents = req_int(body, "base_hourly_rate_cents")
    if base_hourly_rate_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "base_hourly_rate_cents must be > 0")

    home_unit_id = None
    if "home_unit_id" in body and body["home_unit_id"] is not None:
        if not isinstance(body["home_unit_id"], str) or body["home_unit_id"] == "":
            raise_err(ERR_INVALID_REQUEST, "home_unit_id must be a string")
        home_unit_id = body["home_unit_id"]

    # Home-unit conditional rule (PRD 3.1): CORE requires one, FLOAT_POOL forbids one.
    if employment_type == "CORE" and home_unit_id is None:
        raise_err(ERR_HOME_UNIT_RULE_VIOLATED, "CORE nurse requires a home_unit_id")
    if employment_type == "FLOAT_POOL" and home_unit_id is not None:
        raise_err(ERR_HOME_UNIT_RULE_VIOLATED, "FLOAT_POOL nurse must not have a home_unit_id")

    nurse = {
        "full_name": full_name,
        "employment_type": employment_type,
        "competencies": competencies,
        "charge_qualified": charge_qualified,
        "base_hourly_rate_cents": base_hourly_rate_cents,
        "home_unit_id": home_unit_id,
    }
    db.stamp_new(nurse)
    db.nurses[nurse["id"]] = nurse
    from services.core import pub
    return success_object(pub(nurse), 201)


@bp.get("/nurses")
@require_roles(*ALL_ROLES)
def list_nurses(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.nurses.values(), key=lambda n: n["created_at"])
    items = apply_filters(items, {
        "home_unit_id": request.args.get("home_unit_id"),
        "employment_type": request.args.get("employment_type"),
    })
    page, total = paginate(items, limit, offset)
    from services.core import pub
    return success_list([pub(n) for n in page], limit, offset, total)


@bp.get("/nurses/<nurseId>")
@require_roles(*ALL_ROLES)
def get_nurse(nurseId: str, _user_id: str, _role: str):
    nurse = db.nurses.get(nurseId)
    if nurse is None:
        raise_err(ERR_NURSE_NOT_FOUND, "Nurse not found")
    from services.core import pub
    return success_object(pub(nurse))


@bp.get("/nurses/<nurseId>/week-ledger")
@require_roles(*ALL_ROLES)
def nurse_week_ledger(nurseId: str, _user_id: str, _role: str):
    nurse = db.nurses.get(nurseId)
    if nurse is None:
        raise_err(ERR_NURSE_NOT_FOUND, "Nurse not found")
    raw = request.args.get("week_start")
    if raw is None or raw == "":
        raise_err(ERR_INVALID_REQUEST, "Missing required query parameter: week_start")
    week_start = parse_iso_date(raw, "week_start")
    if week_start.weekday() != 0:
        raise_err(ERR_INVALID_REQUEST, "week_start must be a Monday")
    data = {
        "week_start": week_start.isoformat(),
        "projected_hours": projected_hours(nurseId, week_start),
        "completed_hours": completed_hours(nurseId, week_start),
    }
    return success_object(data)
