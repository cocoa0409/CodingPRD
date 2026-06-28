"""Crew endpoints."""
from flask import Blueprint

import errors
from db import db, base_fields, public
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_int,
                        parse_pagination, paginate)

bp = Blueprint("crews", __name__)


def _get_crew_or_404(crew_id):
    rec = db.crews.get(crew_id)
    if rec is None:
        raise errors.not_found("Crew not found")
    return rec


@bp.post("/crews")
def create_crew():
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    body = get_json_body()
    crew_name = require_str(body, "crew_name")
    daily_capacity_minutes = require_int(body, "daily_capacity_minutes", minimum=1)
    home_base_zip = require_str(body, "home_base_zip")

    rec = base_fields()
    rec.update({
        "crew_name": crew_name,
        "daily_capacity_minutes": daily_capacity_minutes,
        "home_base_zip": home_base_zip,
        "planned_utilization_pct": 0,
        "actual_utilization_pct": 0,
    })
    db.crews[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/crews/<id>")
def get_crew(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    rec = _get_crew_or_404(id)
    return success(public(rec))


@bp.get("/crews")
def list_crews():
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    limit, offset = parse_pagination()
    page, total = paginate(list(db.crews.values()), limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)
