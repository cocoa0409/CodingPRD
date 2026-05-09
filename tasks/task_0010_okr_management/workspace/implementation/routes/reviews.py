"""ReviewScore endpoints + review chain transitions."""

from flask import Blueprint

import db
from audit import write_audit
from auth import require_role, is_owner_or_co_owner
from clock import now, format_ts
from envelope import success_object
from errors import ApiError
from serialize import s_review, s_objective
from util import (get_json_body, require_fields, stamp_create, stamp_update,
                  actor_id, actor_role, round4)


bp = Blueprint("reviews", __name__)

MIN_CALIBRATION_DELTA = 0.05


def _audit_review(r, action, before=None, after=None, system=False):
    write_audit(entity_type="REVIEW_SCORE", entity_id=r["id"], action=action,
                before=before, after=after,
                actor_override="SYSTEM" if system else None,
                role_override="SYSTEM" if system else None)


def _create_review_for_objective(objective: dict, *, system=False):
    """Used by /cycles/{id}/start-review."""
    r = {
        "objective_id": objective["id"],
        "cycle_id": objective["cycle_id"],
        "status": "PENDING_SELF",
        "self_score": None,
        "self_submitted_at": None,
        "manager_score": None,
        "manager_submitted_at": None,
        "calibration_score": None,
        "calibration_adjusted_at": None,
        "final_score": None,
        "revision_count": 0,
        "locked_at": None,
    }
    stamp_create(r)
    db.review_scores[r["id"]] = r
    _audit_review(r, "CREATE", after=s_review(r), system=system)
    return r


def _aggregate(r):
    """For GET /reviews/{id} aggregate view (informational, on top of stored fields)."""
    if r.get("calibration_score") is not None:
        return round4(r["calibration_score"])
    if r.get("manager_score") is None:
        return None
    if r.get("self_score") is None:
        return round4(r["manager_score"])
    delta = abs(r["manager_score"] - r["self_score"])
    if delta > 0.20:
        return round4(r["self_score"] * 0.3 + r["manager_score"] * 0.7)
    return round4(r["manager_score"])


def _serialize_review(r):
    out = s_review(r)
    out["aggregate_score"] = _aggregate(r)
    return out


def _validate_score_range(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "score must be number")
    if not (0 <= v <= 1):
        raise ApiError("ERR_INVALID_REQUEST", 400, "score must be in [0,1]")
    return v


def _check_review_cycle_in_review(r):
    cycle = db.cycles.get(r["cycle_id"])
    if not cycle or cycle["status"] != "IN_REVIEW":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "cycle not IN_REVIEW")


@bp.get("/reviews/<id>")
def read_review(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    arole = actor_role()
    aid = actor_id()
    o = db.objectives.get(r["objective_id"])
    if arole == "Employee":
        if not o or not is_owner_or_co_owner(o, aid):
            raise ApiError("ERR_FORBIDDEN", 403, "Employee may only read own review")
    elif arole == "Manager":
        # Manager: either owner of obj, or direct manager of owner
        owner = db.users.get(o["owner_user_id"]) if o else None
        if not (is_owner_or_co_owner(o, aid) or (owner and owner.get("manager_id") == aid)):
            raise ApiError("ERR_FORBIDDEN", 403, "Manager not owner or owner's manager")
    return success_object(_serialize_review(r))


@bp.post("/reviews/<id>/self-submit")
def self_submit(id):
    require_role("Manager", "Employee")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    o = db.objectives.get(r["objective_id"])
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    if not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    _check_review_cycle_in_review(r)
    if o["status"] != "IN_REVIEW":
        raise ApiError("ERR_OBJECTIVE_NOT_ACTIVE", 409, f"objective {o['status']}")
    if r["status"] != "PENDING_SELF":
        raise ApiError("ERR_INVALID_STATE", 409, f"review status {r['status']}")
    body = get_json_body()
    require_fields(body, "self_score")
    v = _validate_score_range(body["self_score"])
    before = s_review(r)
    r["self_score"] = round4(v)
    r["self_submitted_at"] = format_ts(now())
    r["status"] = "PENDING_MANAGER"
    stamp_update(r)
    _audit_review(r, "STATE_TRANSITION", before=before, after=s_review(r))
    return success_object(_serialize_review(r))


@bp.post("/reviews/<id>/manager-submit")
def manager_submit(id):
    require_role("Manager")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    o = db.objectives.get(r["objective_id"])
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    owner = db.users.get(o["owner_user_id"])
    if not owner or owner.get("manager_id") != aid:
        raise ApiError("ERR_NOT_MANAGER_OF_OWNER", 403, "not direct manager of owner")
    _check_review_cycle_in_review(r)
    if r["status"] != "PENDING_MANAGER":
        raise ApiError("ERR_INVALID_STATE", 409, f"review status {r['status']}")
    body = get_json_body()
    require_fields(body, "manager_score")
    v = _validate_score_range(body["manager_score"])
    before = s_review(r)
    r["manager_score"] = round4(v)
    r["manager_submitted_at"] = format_ts(now())
    r["status"] = "PENDING_CALIBRATION"
    stamp_update(r)
    _audit_review(r, "STATE_TRANSITION", before=before, after=s_review(r))
    return success_object(_serialize_review(r))


@bp.post("/reviews/<id>/manager-return")
def manager_return(id):
    require_role("Manager")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    o = db.objectives.get(r["objective_id"])
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    owner = db.users.get(o["owner_user_id"])
    if not owner or owner.get("manager_id") != aid:
        raise ApiError("ERR_NOT_MANAGER_OF_OWNER", 403, "not direct manager of owner")
    _check_review_cycle_in_review(r)
    if r["status"] != "PENDING_MANAGER":
        raise ApiError("ERR_INVALID_STATE", 409, f"review status {r['status']}")
    before = s_review(r)
    r["self_score"] = None
    r["self_submitted_at"] = None
    r["revision_count"] = int(r.get("revision_count", 0)) + 1
    r["status"] = "PENDING_SELF"
    stamp_update(r)
    _audit_review(r, "STATE_TRANSITION", before=before, after=s_review(r))
    return success_object(_serialize_review(r))


@bp.post("/reviews/<id>/calibrate")
def calibrate(id):
    require_role("HRBP")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    _check_review_cycle_in_review(r)
    if r["status"] != "PENDING_CALIBRATION":
        raise ApiError("ERR_INVALID_STATE", 409, f"review status {r['status']}")
    body = get_json_body()
    require_fields(body, "calibration_score")
    v = _validate_score_range(body["calibration_score"])
    if r.get("manager_score") is None:
        raise ApiError("ERR_INVALID_STATE", 409, "manager_score not set")
    # Compare at 4dp precision (PRD §2.5) so floating-point representation
    # doesn't make delta=0.05 appear as 0.05000000000000004.
    delta = round4(abs(v - float(r["manager_score"])))
    if delta <= MIN_CALIBRATION_DELTA:
        raise ApiError("ERR_DELTA_TOO_SMALL", 422, f"delta {delta} <= 0.05")
    before = s_review(r)
    r["calibration_score"] = round4(v)
    r["calibration_adjusted_at"] = format_ts(now())
    stamp_update(r)
    _audit_review(r, "CALIBRATION", before=before, after=s_review(r))
    return success_object(_serialize_review(r))


@bp.post("/reviews/<id>/calibration-return")
def calibration_return(id):
    require_role("HRBP")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    _check_review_cycle_in_review(r)
    if r["status"] != "PENDING_CALIBRATION":
        raise ApiError("ERR_INVALID_STATE", 409, f"review status {r['status']}")
    before = s_review(r)
    r["manager_score"] = None
    r["manager_submitted_at"] = None
    r["status"] = "PENDING_MANAGER"
    stamp_update(r)
    _audit_review(r, "STATE_TRANSITION", before=before, after=s_review(r))
    return success_object(_serialize_review(r))


@bp.post("/reviews/<id>/lock")
def lock_review(id):
    require_role("HRBP")
    r = db.review_scores.get(id)
    if not r:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "review not found")
    _check_review_cycle_in_review(r)
    if r["status"] != "PENDING_CALIBRATION":
        raise ApiError("ERR_INVALID_STATE", 409, f"review status {r['status']}")
    if r.get("calibration_score") is None and r.get("manager_score") is None:
        raise ApiError("ERR_INVALID_STATE", 409, "neither calibration nor manager score set")
    before = s_review(r)
    final = r["calibration_score"] if r["calibration_score"] is not None else r["manager_score"]
    r["final_score"] = round4(final)
    r["locked_at"] = format_ts(now())
    r["status"] = "LOCKED"
    stamp_update(r)
    # Cascade: Objective IN_REVIEW -> LOCKED, set final_score
    o = db.objectives.get(r["objective_id"])
    if o and o["status"] == "IN_REVIEW":
        ob_before = s_objective(o)
        o["status"] = "LOCKED"
        o["final_score"] = r["final_score"]
        stamp_update(o)
        write_audit(entity_type="OBJECTIVE", entity_id=o["id"],
                    action="STATE_TRANSITION", before=ob_before, after=s_objective(o),
                    actor_override="SYSTEM", role_override="SYSTEM")
    _audit_review(r, "STATE_TRANSITION", before=before, after=s_review(r))
    return success_object(_serialize_review(r))
