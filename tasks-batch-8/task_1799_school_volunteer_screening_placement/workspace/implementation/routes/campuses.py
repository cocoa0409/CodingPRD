"""Campus endpoints."""

import re
from flask import request

import db
import clock
from errors import APIError, not_found, invalid_request, ERR_CAMPUS_CODE_TAKEN
from middleware import require_roles
from pagination import parse_pagination, paginate
from response import success_object, success_list

BADGE_PREFIX_RE = re.compile(r"^[A-Z0-9]{1,8}$")


def register(app):
    @app.route("/campuses", methods=["POST"])
    def create_campus():
        require_roles("DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p8 uniqueness
        code = body.get("campus_code")
        if code is not None:
            for c in db.campuses.values():
                if c["campus_code"] == code:
                    raise APIError(ERR_CAMPUS_CODE_TAKEN, "campus_code already in use", 409)

        # p10 shape
        name = body.get("name")
        badge_prefix = body.get("badge_prefix")
        if not name or not isinstance(name, str):
            raise invalid_request("name is required")
        if not code or not isinstance(code, str):
            raise invalid_request("campus_code is required")
        if not badge_prefix or not isinstance(badge_prefix, str) or not BADGE_PREFIX_RE.match(badge_prefix):
            raise invalid_request("badge_prefix must be 1-8 uppercase alphanumeric characters")

        campus = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "name": name,
            "campus_code": code,
            "badge_prefix": badge_prefix,
        }
        db.campuses[campus["id"]] = campus
        return success_object(campus, 201)

    @app.route("/campuses/<cid>", methods=["GET"])
    def get_campus(cid):
        require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        campus = db.campuses.get(cid)
        if campus is None:
            raise not_found()
        return success_object(campus, 200)
