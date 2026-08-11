"""Venue routes."""
from flask import request

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import get_caller, require_role, get_json_body
from response import success, success_list, parse_pagination, paginate
from services.common import get_venue_or_404, require_body_fields, require_string, require_int
from services.serialize import venue_out, ceremony_out, session_out


def register(bp):
    @bp.route("/venues", methods=["POST"])
    def create_venue():
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        body = get_json_body()
        require_body_fields(body, ["name", "address", "total_capacity", "accessible_capacity", "indoor"])
        require_string(body, "name")
        require_string(body, "address")
        require_int(body, "total_capacity", 1)
        require_int(body, "accessible_capacity", 0)
        if body["accessible_capacity"] > body["total_capacity"]:
            raise_err(ERR_INVALID_REQUEST, "accessible_capacity must be <= total_capacity")
        if not isinstance(body["indoor"], bool):
            raise_err(ERR_INVALID_REQUEST, "indoor must be a boolean")

        now = db.now_iso()
        vid = db.new_id()
        venue = {
            "id": vid,
            "name": body["name"],
            "address": body["address"],
            "total_capacity": body["total_capacity"],
            "accessible_capacity": body["accessible_capacity"],
            "indoor": body["indoor"],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.venues[vid] = venue
        return success(venue_out(venue), status=201)

    @bp.route("/venues/<vid>", methods=["GET"])
    def get_venue(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate", "Vendor"])
        v = get_venue_or_404(vid)
        return success(venue_out(v))

    @bp.route("/venues/<vid>/ceremonies", methods=["GET"])
    def list_venue_ceremonies(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_venue_or_404(vid)
        limit, offset = parse_pagination(request.args)
        items = [
            c for c in db.ceremonies.values()
            if c["venue_id"] == vid or c.get("rain_venue_id") == vid
        ]
        items.sort(key=lambda c: c["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([ceremony_out(c) for c in page], limit, offset, total)

    @bp.route("/venues/<vid>/rehearsal-sessions", methods=["GET"])
    def list_venue_rehearsal_sessions(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_venue_or_404(vid)
        limit, offset = parse_pagination(request.args)
        items = [s for s in db.rehearsal_sessions.values() if s["venue_id"] == vid]
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([session_out(s) for s in page], limit, offset, total)
