"""InteractionSession booking and transitions."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("sessions", __name__)

PROGRAM_TYPES = ("TOUCH_POOL_CONTACT", "FEEDING_ENCOUNTER", "DIVE_ENCOUNTER")
ACTIONS = ("ACTIVATE", "COMPLETE", "CANCEL", "SUSPEND", "REINSTATE")
ACTION_ROLES = {
    "ACTIVATE": (M.AQUARIST,),
    "COMPLETE": (M.AQUARIST,),
    "CANCEL": (M.AQUARIST,),
    "SUSPEND": (M.DIRECTOR,),
    "REINSTATE": (M.DIRECTOR,),
}
LEGAL_ACTIONS = {
    "SCHEDULED": ("ACTIVATE", "SUSPEND", "CANCEL"),
    "ACTIVE": ("COMPLETE", "SUSPEND"),
    "SUSPENDED": ("REINSTATE", "CANCEL"),
}
BLOCKING_HEALTH = ("CRITICAL_CARE", "DECEASED_PENDING_NECROPSY")

SESSION_COMPUTED = ("status", "suspension_reason")


@bp.route("/aquarium/interaction-sessions", methods=["POST"])
def create_session():
    M.authenticate({M.AQUARIST})
    body = M.json_body()
    exhibit = M.fetch_body_fk(body, "exhibit_id", "exhibits")

    V.reject_computed(body, SESSION_COMPUTED)
    V.as_id(body, "exhibit_id", required=True)
    program_type = V.as_enum(body, "program_type", PROGRAM_TYPES, required=True)
    starts_at = V.as_dt(body, "starts_at", required=True)
    ends_at = V.as_dt(body, "ends_at", required=True)
    max_guests = V.as_int(body, "max_guests", required=True, minimum=1)
    guest_count = V.as_int(body, "guest_count", default=0, minimum=0)
    briefing = V.as_bool(body, "safety_briefing_confirmed", default=False)

    if exhibit["posture"] == "CLOSED":
        raise ApiError("ERR_EXHIBIT_CLOSED")
    if not exhibit["interaction_program_enabled"]:
        raise ApiError("ERR_INTERACTION_PROGRAM_DISABLED")
    if starts_at <= db.db.clock:
        raise ApiError("ERR_SESSION_IN_PAST")
    if ends_at <= starts_at:
        raise ApiError("ERR_INTERVAL_INVALID")
    if calc.find_session_conflict(exhibit["id"], starts_at, ends_at) is not None:
        raise ApiError("ERR_SESSION_BUFFER_CONFLICT")
    if guest_count > max_guests:
        raise ApiError("ERR_GUEST_CAPACITY_EXCEEDED")

    row = db.new_row()
    row.update({
        "exhibit_id": exhibit["id"],
        "program_type": program_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_guests": max_guests,
        "guest_count": guest_count,
        "safety_briefing_confirmed": briefing,
        "status": "SCHEDULED",
        "suspension_reason": None,
    })
    db.insert("interaction_sessions", row)
    return response.object_response(S.interaction_session(row), 201)


@bp.route("/aquarium/interaction-sessions/<row_id>", methods=["GET"])
def get_session(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("interaction_sessions", row_id)
    return response.object_response(S.interaction_session(row))


@bp.route("/aquarium/interaction-sessions/<row_id>/transitions", methods=["POST"])
def transition_session(row_id):
    _user_id, role = M.authenticate({M.AQUARIST, M.DIRECTOR})
    session = M.fetch("interaction_sessions", row_id)
    body = M.json_body()
    action = V.as_enum(body, "action", ACTIONS, required=True)
    M.require_action_role(role, action, ACTION_ROLES)
    V.reject_computed(body, SESSION_COMPUTED)
    V.as_str(body, "reason")

    if session["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if action not in LEGAL_ACTIONS.get(session["status"], ()):
        raise ApiError("ERR_INVALID_ACTION")

    exhibit = db.db.exhibits.get(session["exhibit_id"])

    if action == "ACTIVATE":
        if exhibit is None or exhibit["posture"] == "CLOSED":
            raise ApiError("ERR_EXHIBIT_CLOSED")
        system = engine.serving_system(exhibit)
        if (system is None or system["alarm_state"] != "NORMAL"
                or engine.redundancy_overdue(system)):
            raise ApiError("ERR_LIFE_SUPPORT_ALARM")
        if not session["safety_briefing_confirmed"]:
            raise ApiError("ERR_SAFETY_BRIEFING_REQUIRED")
        if session["program_type"] == "DIVE_ENCOUNTER":
            for specimen in db.db.specimens.values():
                if (specimen["exhibit_id"] == exhibit["id"]
                        and specimen["health_status"] in BLOCKING_HEALTH):
                    raise ApiError("ERR_DIVE_ENCOUNTER_BLOCKED")
        if int(session["guest_count"]) > int(session["max_guests"]):
            raise ApiError("ERR_GUEST_CAPACITY_EXCEEDED")
        session["status"] = "ACTIVE"
        db.touch(session)
    elif action == "COMPLETE":
        session["status"] = "COMPLETED"
        db.touch(session)
    elif action == "CANCEL":
        session["status"] = "CANCELLED"
        db.touch(session)
    elif action == "SUSPEND":
        engine.suspend_session(session, exhibit, "DIRECTOR_ACTION")
        db.touch(exhibit)
    else:
        if exhibit is None or exhibit["posture"] == "CLOSED":
            raise ApiError("ERR_EXHIBIT_CLOSED")
        if not exhibit["interaction_program_enabled"]:
            raise ApiError("ERR_INTERACTION_PROGRAM_DISABLED")
        conflict = calc.find_session_conflict(
            exhibit["id"], session["starts_at"], session["ends_at"], exclude_id=session["id"])
        if conflict is not None:
            raise ApiError("ERR_SESSION_BUFFER_CONFLICT")
        session["status"] = "SCHEDULED"
        session["suspension_reason"] = None
        db.touch(session)

    return response.object_response(S.interaction_session(session))
