"""PilotProgram endpoints + teacher reviews (PRD §3.3)."""

from flask import Blueprint, request

import serializers
from db import bump, new_id, now_clock, refresh, stamp_new, store
from errors import (ERR_DUPLICATE_REVIEW, ERR_PILOT_NOT_STARTED, conflict,
                    invalid_state)
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, req_enum,
                        req_int, require_roles)
from response import paginate, sort_created, success_object
from services.calculations import (recompute_provisional, review_composite)

bp = Blueprint("pilots", __name__)


def _get_pilot(pilot_id):
    return get_or_404(store.pilots, pilot_id, "PilotProgram")


@bp.route("/pilots", methods=["GET"])
def list_pilots():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.pilots.values())
    cycle_id = request.args.get("cycle_id")
    material_id = request.args.get("material_id")
    school_code = request.args.get("school_code")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [p for p in items if p["cycle_id"] == cycle_id]
    if material_id is not None:
        items = [p for p in items if p["material_id"] == material_id]
    if school_code is not None:
        items = [p for p in items if p["school_code"] == school_code]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(sort_created(items), serializers.pilot)


@bp.route("/pilots/<pilotId>", methods=["GET"])
def get_pilot(pilotId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.pilot(_get_pilot(pilotId)))


@bp.route("/pilots/<pilotId>/transitions", methods=["POST"])
def pilot_transition(pilotId):
    user_id, role = auth_context()
    require_roles(role, ("CurriculumDirector",))
    pilot = _get_pilot(pilotId)
    body = get_body()
    to_state = req_enum(body, "to_state", ("ACTIVE", "CLOSED", "CANCELLED"))

    if to_state == "ACTIVE":
        if pilot["status"] != "PLANNED":
            raise invalid_state("only a PLANNED pilot may be activated")
        cycle = store.cycles.get(pilot["cycle_id"])
        if cycle is None or cycle["status"] != "PILOT_OPEN":
            raise invalid_state("pilot activation requires the cycle PILOT_OPEN")
        # Tier 7 temporal: the logical clock's date must have reached starts_on.
        if now_clock().date() < pilot["starts_on"]:
            raise conflict(ERR_PILOT_NOT_STARTED,
                           "the pilot's starts_on date has not been reached")
    elif to_state == "CLOSED":
        if pilot["status"] != "ACTIVE":
            raise invalid_state("only an ACTIVE pilot may be closed")
    elif to_state == "CANCELLED":
        if pilot["status"] != "PLANNED":
            raise invalid_state("only a PLANNED pilot may be cancelled")

    pilot["status"] = to_state
    bump(pilot)
    if to_state == "ACTIVE":
        # Activation promotes a still-VETTED material to PILOT_CANDIDATE.
        material = store.materials.get(pilot["material_id"])
        if material is not None and material["adoption_status"] == "VETTED":
            material["adoption_status"] = "PILOT_CANDIDATE"
            bump(material)
    return success_object(serializers.pilot(pilot))


# ---------------------------------------------------------------------------
# Teacher reviews (PRD §3.3)
# ---------------------------------------------------------------------------


@bp.route("/pilots/<pilotId>/reviews", methods=["POST"])
def create_review(pilotId):
    user_id, role = auth_context()
    require_roles(role, ("Teacher",))
    pilot = _get_pilot(pilotId)
    body = get_body()
    pedagogy = req_int(body, "pedagogy_score", minimum=1, maximum=4)
    alignment = req_int(body, "alignment_score", minimum=1, maximum=4)
    usability = req_int(body, "usability_score", minimum=1, maximum=4)
    equity = req_int(body, "equity_score", minimum=1, maximum=4)
    if pilot["status"] != "ACTIVE":
        raise invalid_state("reviews may only be submitted while the pilot is "
                            "ACTIVE")
    duplicate = any(
        rv["pilot_id"] == pilot["id"] and rv["teacher_user_id"] == user_id
        and rv["status"] == "SUBMITTED"
        for rv in store.reviews.values()
    )
    if duplicate:
        raise conflict(ERR_DUPLICATE_REVIEW,
                       "the teacher already holds a SUBMITTED review for this "
                       "pilot")
    review = {
        "id": new_id(),
        "pilot_id": pilot["id"],
        "teacher_user_id": user_id,
        "pedagogy_score": pedagogy,
        "alignment_score": alignment,
        "usability_score": usability,
        "equity_score": equity,
        "review_composite": review_composite(pedagogy, alignment, usability,
                                             equity),
        "status": "SUBMITTED",
        "submitted_at": now_clock(),
    }
    stamp_new(review)
    store.reviews[review["id"]] = review
    # Live recomputes: pilot submitted_review_count is derived on read; the
    # material's provisional_composite is refreshed (PRD §3.3).
    material = store.materials.get(pilot["material_id"])
    if material is not None:
        recompute_provisional(material)
        refresh(material)
    refresh(pilot)
    return success_object(serializers.review(review), status=201)


@bp.route("/pilots/<pilotId>/reviews", methods=["GET"])
def list_reviews(pilotId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    pilot = _get_pilot(pilotId)
    items = [rv for rv in store.reviews.values() if rv["pilot_id"] == pilot["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [rv for rv in items if rv["status"] == status]
    return paginate(sort_created(items), serializers.review)
