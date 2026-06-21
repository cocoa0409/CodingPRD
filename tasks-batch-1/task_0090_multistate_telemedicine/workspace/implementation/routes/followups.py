"""Follow-up reads + fulfill/lapse, and the test-driving logical clock."""
from flask import Blueprint, request

import db
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NOT_DUE, ERR_FORBIDDEN
from middleware import require_auth, require_role, DECLARED_ROLES
from response import success_object
from services import store, serializers, lookup, validate
from .common import list_response

bp = Blueprint("followups", __name__)


@bp.route("/follow-ups/<fid>", methods=["GET"])
def get_follow_up(fid):
    with db.lock:
        f = lookup.follow_up(fid)
        return success_object(serializers.follow_up(f))


@bp.route("/visits/<vid>/follow-ups", methods=["GET"])
def list_visit_follow_ups(vid):
    with db.lock:
        lookup.visit(vid)
        records = [f for f in db.follow_ups.values() if f["source_visit_id"] == vid]
        return list_response(records, serializers.follow_up)


@bp.route("/follow-ups", methods=["GET"])
def list_follow_ups():
    with db.lock:
        records = list(db.follow_ups.values())
        linked_visit_id = request.args.get("linked_visit_id")
        if linked_visit_id is not None:
            records = [f for f in records if f.get("linked_visit_id") == linked_visit_id]
        return list_response(records, serializers.follow_up)


@bp.route("/follow-ups/<fid>/fulfill", methods=["POST"])
def fulfill_follow_up(fid):
    _user_id, role = require_auth()
    require_role(role, {"Physician"})
    with db.lock:
        f = lookup.follow_up(fid)
        body = validate.get_body()
        linked_visit_id = validate.require_str(body, "linked_visit_id")
        # Body FK existence (priority 3).
        if linked_visit_id not in db.visits:
            raise err(ERR_NOT_FOUND, "linked_visit_id not found.")
        if f["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Follow-up must be OPEN to fulfill.")
        f["linked_visit_id"] = linked_visit_id
        f["status"] = "FULFILLED"
        store.touch(f)
        return success_object(serializers.follow_up(f))


@bp.route("/follow-ups/<fid>/lapse", methods=["POST"])
def lapse_follow_up(fid):
    _user_id, role = require_auth()
    require_role(role, {"ComplianceOfficer"})
    with db.lock:
        f = lookup.follow_up(fid)
        if f["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Follow-up must be OPEN to lapse.")
        # Only when clock >= due_at (priority: ERR_NOT_DUE).
        now = db.clock_now()
        due = db.parse_iso(f["due_at"])
        if now < due:
            raise err(ERR_NOT_DUE, "Follow-up is not yet due.")
        f["status"] = "LAPSED"
        store.touch(f)
        return success_object(serializers.follow_up(f))


# ---------------- Logical clock (test-driving) ----------------

def _ensure_clock():
    if db.clock["id"] is None:
        db.clock["id"] = db.new_id()
        db.clock["created_at"] = db.iso_millis(db.now_dt())


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    # Anonymous or ComplianceOfficer. If auth headers present, validate role.
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is not None or user_id is not None:
        from errors import ERR_UNAUTHENTICATED
        if not user_id or not role or role not in DECLARED_ROLES:
            raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
        if role not in ("Anonymous", "ComplianceOfficer"):
            raise err(ERR_FORBIDDEN, "Role %s may not set the clock." % role)

    body = validate.get_body()
    current_utc = validate.require_datetime(body, "current_utc")
    with db.lock:
        _ensure_clock()
        # Normalize to ISO millis Z.
        db.clock["current_utc"] = db.iso_millis(db.parse_iso(current_utc))
        return success_object(serializers.clock_state(db.clock))


@bp.route("/_clock", methods=["GET"])
def get_clock():
    with db.lock:
        _ensure_clock()
        return success_object(serializers.clock_state(db.clock))
