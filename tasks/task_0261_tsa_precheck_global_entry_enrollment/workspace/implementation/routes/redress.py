"""Redress cases via DHS TRIP (PRD §3.7).

Resolution turns on the program's redress_min_score: a match_strength_score at
or below it CLEARS (offset = 60 * watchlist_hits, added to the check's
redress_offset_applied); strictly above CONFIRMS (offset 0).
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_STATE, ERR_REFERENCED_ENTITY_NOT_FOUND
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.audit import write_audit
from services.calculations import compute_redress_offset
from services.lookups import get_or_404, program_by_code

bp = Blueprint("redress", __name__)

REDRESS_READ_ROLES = ["Applicant", "AppealsOfficer", "SchedulingAdmin", "VettingOfficer"]


@bp.route("/redress-cases", methods=["POST"])
def file_redress():
    require_auth(["Applicant", "AppealsOfficer"])
    body = get_body()
    require_fields(body, ["application_id", "trip_number", "match_strength_score"])
    application_id = require_str(body, "application_id")
    trip_number = require_str(body, "trip_number")
    match_strength = require_int(body, "match_strength_score", minimum=0, maximum=100)

    if application_id not in db.applications:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, "application_id does not exist")

    rec = {
        "application_id": application_id,
        "trip_number": trip_number,
        "match_strength_score": match_strength,
        "resolution": None,
        "risk_offset": 0,
        "status": "FILED",
    }
    stamp_create(rec)
    db.redress_cases[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/applications/<app_id>/redress-cases", methods=["GET"])
def list_redress(app_id):
    require_auth(REDRESS_READ_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [r for r in db.redress_cases.values() if r.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/redress-cases/<rid>", methods=["GET"])
def get_redress(rid):
    require_auth(REDRESS_READ_ROLES)
    rec = get_or_404(db.redress_cases, rid, "RedressCase")
    return ok_object(serialize(rec), 200)


@bp.route("/redress-cases/<rid>/resolve", methods=["POST"])
def resolve_redress(rid):
    require_auth(["AppealsOfficer"])
    rec = get_or_404(db.redress_cases, rid, "RedressCase")

    if rec["status"] != "FILED":
        raise APIError(ERR_INVALID_STATE, 409, "RedressCase must be FILED to resolve")

    app = db.applications.get(rec["application_id"])
    program = program_by_code(app["program_code"]) if app is not None else None
    redress_min = program["redress_min_score"] if program is not None else 0
    bc = _the_check(rec["application_id"])
    watchlist_hits = bc["watchlist_hits"] if bc is not None else 0

    resolution, risk_offset = compute_redress_offset(
        rec["match_strength_score"], redress_min, watchlist_hits)

    rec["resolution"] = resolution
    rec["risk_offset"] = risk_offset
    rec["status"] = "RESOLVED"
    touch(rec)

    if resolution == "CLEARED" and bc is not None:
        bc["redress_offset_applied"] += risk_offset
        touch(bc)
        write_audit(rec["application_id"], "REDRESS_CLEARED",
                    "Redress cleared; risk offset applied")
    else:
        write_audit(rec["application_id"], "REDRESS_CONFIRMED",
                    "Redress confirmed; no offset")

    return ok_object(serialize(rec), 200)


def _the_check(app_id: str):
    for bc in db.background_checks.values():
        if bc.get("application_id") == app_id:
            return bc
    return None
