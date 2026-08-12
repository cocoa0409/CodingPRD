"""Seat assignment routes."""
import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEAT_CONFLICT,
    ERR_SEAT_CAPACITY_EXCEEDED,
    ERR_ACCESSIBLE_CAPACITY_EXCEEDED,
)
from middleware import get_caller, require_role, get_json_body, require_graduate_ownership
from response import success
from services.common import (
    get_ceremony_or_404,
    get_graduate_or_404,
    get_seat_or_404,
    require_body_fields,
    require_string,
    require_int,
    graduate_eligible_gate,
)
from services.pools import recompute_ceremony_pools, effective_venue
from services.serialize import seat_out


def register(bp):
    @bp.route("/seat-assignments", methods=["POST"])
    def create_seat():
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        body = get_json_body()
        require_body_fields(body, ["ceremony_id", "graduate_id", "section", "row_label", "seat_number"])
        require_string(body, "section")
        require_string(body, "row_label")
        require_int(body, "seat_number", 1)
        ceremony = get_ceremony_or_404(body["ceremony_id"])
        g = get_graduate_or_404(body["graduate_id"])
        accessible = body.get("accessible", False)
        if not isinstance(accessible, bool):
            raise_err(ERR_INVALID_REQUEST, "accessible must be a boolean")

        graduate_eligible_gate(g)

        # seat-position uniqueness + one-seat-per-graduate
        for s in db.seat_assignments.values():
            if s["ceremony_id"] == ceremony["id"] and s["status"] == "ASSIGNED":
                if (s["section"] == body["section"] and s["row_label"] == body["row_label"]
                        and s["seat_number"] == body["seat_number"]):
                    raise_err(ERR_SEAT_CONFLICT, "Seat position already assigned")
                if s["graduate_id"] == g["id"]:
                    raise_err(ERR_SEAT_CONFLICT, "Graduate already holds an ASSIGNED seat")

        assigned_count = sum(
            1 for s in db.seat_assignments.values()
            if s["ceremony_id"] == ceremony["id"] and s["status"] == "ASSIGNED"
        )
        if assigned_count >= ceremony["effective_capacity"]:
            raise_err(ERR_SEAT_CAPACITY_EXCEEDED, "Ceremony seat capacity reached")

        if accessible:
            venue = effective_venue(ceremony)
            accessible_assigned = sum(
                1 for s in db.seat_assignments.values()
                if s["ceremony_id"] == ceremony["id"] and s["status"] == "ASSIGNED" and s["accessible"]
            )
            if venue is None or accessible_assigned >= venue["accessible_capacity"]:
                raise_err(ERR_ACCESSIBLE_CAPACITY_EXCEEDED, "Accessible seat pool exhausted")

        now = db.now_iso()
        sid = db.new_id()
        seat = {
            "id": sid,
            "ceremony_id": ceremony["id"],
            "graduate_id": g["id"],
            "section": body["section"],
            "row_label": body["row_label"],
            "seat_number": body["seat_number"],
            "accessible": accessible,
            "status": "ASSIGNED",
            "evicted_reason": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.seat_assignments[sid] = seat
        recompute_ceremony_pools(ceremony)
        return success(seat_out(seat), status=201)

    @bp.route("/seat-assignments/<sid>", methods=["GET"])
    def get_seat(sid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        s = get_seat_or_404(sid)
        require_graduate_ownership(user_id, role, s["graduate_id"])
        return success(seat_out(s))

    @bp.route("/seat-assignments/<sid>/evict", methods=["POST"])
    def evict_seat(sid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        s = get_seat_or_404(sid)
        if s["status"] != "ASSIGNED":
            raise_err(ERR_INVALID_STATE, "Seat is not ASSIGNED")
        s["status"] = "EVICTED"
        s["evicted_reason"] = "MANUAL"
        s["version"] += 1
        db.touch(s)
        ceremony = get_ceremony_or_404(s["ceremony_id"])
        recompute_ceremony_pools(ceremony)
        return success(seat_out(s))
