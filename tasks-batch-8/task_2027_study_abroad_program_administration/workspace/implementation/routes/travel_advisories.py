"""Travel advisory endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role
from response import success_object
from utils import require_string, require_enum, parse_dt
from errors import not_found, invalid_request, invalid_state, ApiError, ERR_ADVISORY_WINDOW_OVERLAP
from services.cascade import suspend_program_cascade

bp = Blueprint("travel_advisories", __name__)

LEVELS = {"CAUTION", "WARNING", "DO_NOT_TRAVEL"}


@bp.route("/api/v1/travel-advisories", methods=["POST"])
def create_travel_advisory():
    user_id, role = get_auth()
    require_role(role, ["SafetyOfficer"])

    body = request.get_json(silent=True) or {}
    country_code = require_string(body, "country_code")
    level = require_enum(body, "level", LEVELS)
    effective_from = require_string(body, "effective_from")
    effective_to = require_string(body, "effective_to")

    ef = parse_dt(effective_from, "effective_from")
    et = parse_dt(effective_to, "effective_to")
    if not ef < et:
        raise invalid_request("effective_from must be strictly before effective_to")

    # half-open window overlap check against ACTIVE advisories for same country
    for adv in db.travel_advisories.values():
        if adv["country_code"] != country_code or adv["status"] != "ACTIVE":
            continue
        af = parse_dt(adv["effective_from"], "effective_from")
        at = parse_dt(adv["effective_to"], "effective_to")
        # half-open [ef, et) intersects [af, at): ef < at AND af < et
        if ef < at and af < et:
            raise ApiError(
                ERR_ADVISORY_WINDOW_OVERLAP,
                "Advisory window overlaps an ACTIVE advisory for the same country_code",
                409,
            )

    ts = now_iso()
    rec = {
        "id": new_id(),
        "country_code": country_code,
        "level": level,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.travel_advisories[rec["id"]] = rec

    # DO_NOT_TRAVEL cascade: suspend fully-contained OPEN programs for matching country
    if level == "DO_NOT_TRAVEL":
        for program in list(db.programs.values()):
            if program["country_code"] != country_code:
                continue
            if program["status"] != "OPEN":
                continue
            ps = parse_dt(program["start_date"], "start_date")
            pe = parse_dt(program["end_date"], "end_date")
            # advisory window fully contains program dates
            if ef <= ps and et >= pe:
                suspend_program_cascade(program)

    return success_object(rec, 201)


@bp.route("/api/v1/travel-advisories/<id>/lift", methods=["POST"])
def lift_travel_advisory(id):
    user_id, role = get_auth()
    require_role(role, ["SafetyOfficer"])

    rec = db.travel_advisories.get(id)
    if not rec:
        raise not_found("TravelAdvisory not found")

    if rec["status"] != "ACTIVE":
        raise invalid_state("TravelAdvisory is not in ACTIVE status")

    rec["status"] = "LIFTED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)
