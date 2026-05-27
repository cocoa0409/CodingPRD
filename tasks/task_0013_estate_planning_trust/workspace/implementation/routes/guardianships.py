"""Guardianship routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    pagination_params,
    parse_iso_datetime,
    require_enum,
    require_field,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_DUPLICATE_WARD,
    ERR_WARD_OVER_AGE,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import created, list_response, success
from services.calculations import guardian_eligible
from views import view_guardianship


bp = Blueprint("guardianships", __name__)


@bp.post("/guardianships")
@require_roles("EstatePlanner")
def create_guardianship():
    body = get_body()
    estate_id = require_string(body, "estate_id")
    if estate_id not in db.estates:
        raise not_found("Estate")

    ward_full_name = require_string(body, "ward_full_name")
    ward_dob = parse_iso_datetime(require_field(body, "ward_date_of_birth"), "ward_date_of_birth")
    guardian_full_name = require_string(body, "guardian_full_name")

    # Point-uniqueness on (estate_id, ward_full_name) regardless of status.
    for g in db.guardianships.values():
        if g["estate_id"] == estate_id and g["ward_full_name"] == ward_full_name:
            raise APIError(
                ERR_DUPLICATE_WARD,
                "Another Guardianship row on this estate already names this ward.",
                422,
            )

    now = db.now_utc()
    g = {
        "estate_id": estate_id,
        "ward_full_name": ward_full_name,
        "ward_date_of_birth": ward_dob,
        "guardian_full_name": guardian_full_name,
        "status": "PROPOSED",
    }
    stamp_common_fields(g, now)
    db.guardianships[g["id"]] = g
    return created(view_guardianship(g))


@bp.get("/guardianships/<gid>")
@require_roles("EstatePlanner", "Executor", "Judge")
def get_guardianship(gid: str):
    g = db.guardianships.get(gid)
    if g is None:
        raise not_found("Guardianship")
    return success(view_guardianship(g))


@bp.get("/guardianships")
@require_roles("EstatePlanner", "Executor", "Judge")
def list_guardianships():
    limit, offset = pagination_params()
    estate_id = request.args.get("estate_id")
    status = request.args.get("status")

    items = list(db.guardianships.values())
    if estate_id is not None:
        items = [g for g in items if g["estate_id"] == estate_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]

    items.sort(key=lambda g: g["created_at"])
    total = len(items)
    page = [view_guardianship(g) for g in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


@bp.post("/guardianships/<gid>/review")
@require_roles("Judge")
def review_guardianship(gid: str):
    g = db.guardianships.get(gid)
    if g is None:
        raise not_found("Guardianship")
    if g["status"] != "COURT_REVIEW":
        raise invalid_state("Guardianship must be COURT_REVIEW to be reviewed.")

    body = get_body()
    decision = require_enum(body, "decision", {"CONFIRM", "DENY"})

    estate = db.estates.get(g["estate_id"])
    decedent = db.decedents.get(estate["decedent_id"]) if estate else None

    eligible = True
    if decedent is not None and decedent.get("date_of_death") is not None:
        eligible = guardian_eligible(g["ward_date_of_birth"], decedent["date_of_death"])

    if decision == "CONFIRM" and not eligible:
        raise APIError(
            ERR_WARD_OVER_AGE,
            "Ward is at or over 18 years on the date of death.",
            422,
        )

    now = db.now_utc()
    if decision == "CONFIRM" and eligible:
        g["status"] = "COURT_CONFIRMED"
    else:
        g["status"] = "COURT_DENIED"
    touch(g, now)
    return success(view_guardianship(g))
