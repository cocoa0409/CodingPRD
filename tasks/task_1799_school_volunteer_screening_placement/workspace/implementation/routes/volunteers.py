"""Volunteer endpoints."""

from flask import request

import db
import clock
from errors import APIError, not_found, invalid_request, ERR_EMAIL_TAKEN
from middleware import require_roles, check_volunteer_ownership
from pagination import parse_pagination, paginate
from response import success_object, success_list

CONTACT_TYPES = ("SUPERVISED", "UNSUPERVISED")


def _new_volunteer(body):
    ct = body["contact_type"]
    return {
        "id": db.new_id(),
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "full_name": body["full_name"],
        "email": body["email"],
        "contact_type": ct,
        "status": "APPLIED",
        "required_check_level": "BASIC" if ct == "SUPERVISED" else "ENHANCED",
        "restriction_flags": [],
        "clearance_expires_at": None,
        "total_verified_hours": 0,
        "total_provisional_hours": 0,
        "recognition_points": 0,
        "recognition_tier": "NONE",
        "prior_status": None,
        "suspension_incident_id": None,
    }


def register(app):
    @app.route("/volunteers", methods=["POST"])
    def create_volunteer():
        require_roles("DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p8 uniqueness
        email = body.get("email")
        if email is not None:
            for v in db.volunteers.values():
                if v["email"] == email:
                    raise APIError(ERR_EMAIL_TAKEN, "Volunteer email already registered (any status)", 409)

        # p10 shape
        full_name = body.get("full_name")
        ct = body.get("contact_type")
        if not full_name or not isinstance(full_name, str):
            raise invalid_request("full_name is required")
        if not email or not isinstance(email, str):
            raise invalid_request("email is required")
        if ct not in CONTACT_TYPES:
            raise invalid_request("contact_type must be SUPERVISED or UNSUPERVISED")

        vol = _new_volunteer(body)
        db.volunteers[vol["id"]] = vol
        return success_object(vol, 201)

    @app.route("/volunteers", methods=["GET"])
    def list_volunteers():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.volunteers.values())
        status = request.args.get("status")
        contact_type = request.args.get("contact_type")
        tier = request.args.get("recognition_tier")
        if status is not None:
            items = [v for v in items if v["status"] == status]
        if contact_type is not None:
            items = [v for v in items if v["contact_type"] == contact_type]
        if tier is not None:
            items = [v for v in items if v["recognition_tier"] == tier]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/volunteers/<vid>", methods=["GET"])
    def get_volunteer(vid):
        role, user_id = require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        # p2 ownership: Volunteer may only read own record
        if role == "Volunteer":
            check_volunteer_ownership(role, user_id, vid)
        vol = db.volunteers.get(vid)
        if vol is None:
            raise not_found()
        return success_object(vol, 200)
