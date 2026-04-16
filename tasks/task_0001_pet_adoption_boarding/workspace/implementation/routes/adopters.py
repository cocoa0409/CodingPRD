"""Adopter and home-visit routes."""

from flask import Blueprint, request, g

from db import store, new_id, now_dt, lock
from middleware import auth_required
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SCORE,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_STATE,
    ERR_HOME_VISIT_NOT_FOUND,
)
from services.validation import (
    get_json_body, require_field, pagination,
    get_adopter_or_404, get_home_visit_or_404, parse_required_dt,
)
from services.serializers import serialize_adopter, serialize_home_visit

bp = Blueprint("adopters", __name__)


@bp.route("/adopters", methods=["POST"])
@auth_required(allowed_roles={"Adopter", "ShelterAdmin"})
def create_adopter():
    body = get_json_body(required=True)
    name = require_field(body, "full_name", types=str)
    hh = require_field(body, "household_size", types=int)
    has_yard = require_field(body, "has_yard", types=bool)
    if isinstance(hh, bool) or hh < 0:
        raise_err(ERR_INVALID_REQUEST, "household_size invalid")
    with lock:
        aid = new_id()
        now = now_dt()
        rec = {
            "id": aid,
            "full_name": name,
            "household_size": hh,
            "has_yard": has_yard,
            "disqualified": False,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.adopters[aid] = rec
    return success_object(serialize_adopter(rec), status_code=201)


@bp.route("/adopters/<aid>", methods=["GET"])
@auth_required(allowed_roles={"Adopter", "AdoptionReviewer", "AdoptionApprover", "ShelterAdmin"})
def get_adopter(aid):
    rec = get_adopter_or_404(aid)
    return success_object(serialize_adopter(rec))


@bp.route("/adopters/<aid>/home-visits", methods=["POST"])
@auth_required(allowed_roles={"AdoptionReviewer"})
def schedule_home_visit(aid):
    get_adopter_or_404(aid)
    body = get_json_body(required=True)
    scheduled_for = parse_required_dt(body, "scheduled_for")
    inspector_id = require_field(body, "inspector_id", types=str)
    with lock:
        hvid = new_id()
        now = now_dt()
        rec = {
            "id": hvid,
            "adopter_id": aid,
            "scheduled_for": scheduled_for,
            "completed_at": None,
            "safety_score": None,
            "yard_verified": False,
            "inspector_id": inspector_id,
            "status": "SCHEDULED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.home_visits[hvid] = rec
    return success_object(serialize_home_visit(rec), status_code=201)


@bp.route("/adopters/<aid>/home-visits", methods=["GET"])
@auth_required(allowed_roles={"AdoptionReviewer", "AdoptionApprover", "Adopter"})
def list_home_visits(aid):
    get_adopter_or_404(aid)
    limit, offset = pagination()
    recs = [v for v in store.home_visits.values() if v["adopter_id"] == aid]
    recs.sort(key=lambda r: r["created_at"])
    total = len(recs)
    page = recs[offset: offset + limit]
    return success_array([serialize_home_visit(v) for v in page], limit, offset, total)


@bp.route("/adopters/<aid>/home-visits/<hvid>/submit", methods=["POST"])
@auth_required(allowed_roles={"HomeVisitInspector"})
def submit_home_visit(aid, hvid):
    get_adopter_or_404(aid)
    hv = get_home_visit_or_404(hvid)
    if hv["adopter_id"] != aid:
        raise_err(ERR_HOME_VISIT_NOT_FOUND, "Home visit does not belong to adopter")
    # State check
    if hv["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"Home visit not SCHEDULED (current: {hv['status']})")
    body = get_json_body(required=True)
    # Validate safety_score first (specialized error ERR_INVALID_SCORE)
    if "safety_score" not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing safety_score")
    ss = body["safety_score"]
    if isinstance(ss, bool) or not isinstance(ss, int):
        raise_err(ERR_INVALID_SCORE, "safety_score must be integer 0-100")
    if ss < 0 or ss > 100:
        raise_err(ERR_INVALID_SCORE, "safety_score out of [0..100]")
    yard_verified = body.get("yard_verified", False)
    if not isinstance(yard_verified, bool):
        raise_err(ERR_INVALID_REQUEST, "yard_verified must be boolean")
    # Inspector must be the assigned one
    if g.user_id != hv["inspector_id"]:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "Inspector mismatch")
    with lock:
        now = now_dt()
        hv["safety_score"] = ss
        hv["yard_verified"] = yard_verified
        hv["completed_at"] = now
        # SCHEDULED -> SUBMITTED -> PASSED/FAILED auto
        if ss >= 70:
            hv["status"] = "PASSED"
        else:
            hv["status"] = "FAILED"
            # Cascade: applications in HOME_VISIT_REQUIRED for this adopter -> REJECTED
            for app in store.applications.values():
                if app["adopter_id"] == aid and app["status"] == "HOME_VISIT_REQUIRED":
                    app["status"] = "REJECTED"
                    app["rejection_reason"] = "ERR_HOME_VISIT_FAILED"
                    app["updated_at"] = now
                    app["version"] += 1
                    # Release animal hold if applicable
                    _maybe_release_animal(app)
        hv["updated_at"] = now
        hv["version"] += 1
    return success_object(serialize_home_visit(hv))


def _maybe_release_animal(app):
    """If animal was HELD for this application and no other APPROVED app exists, release it."""
    animal = store.animals.get(app["animal_id"])
    if animal is None:
        return
    if animal["status"] != "HELD":
        return
    # Check for any OTHER APPROVED or FINALIZED app for this animal
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["animal_id"] == app["animal_id"] and other["status"] in ("APPROVED", "FINALIZED"):
            return  # some other holds it
    animal["status"] = "AVAILABLE"
    animal["updated_at"] = now_dt()
    animal["version"] += 1


@bp.route("/adopters/<aid>/home-visits/<hvid>/cancel", methods=["POST"])
@auth_required(allowed_roles={"Adopter", "HomeVisitInspector"})
def cancel_home_visit(aid, hvid):
    get_adopter_or_404(aid)
    hv = get_home_visit_or_404(hvid)
    if hv["adopter_id"] != aid:
        raise_err(ERR_HOME_VISIT_NOT_FOUND, "Home visit does not belong to adopter")
    if hv["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"Cannot cancel visit in state {hv['status']}")
    with lock:
        hv["status"] = "CANCELLED"
        hv["updated_at"] = now_dt()
        hv["version"] += 1
    return success_object(serialize_home_visit(hv))
