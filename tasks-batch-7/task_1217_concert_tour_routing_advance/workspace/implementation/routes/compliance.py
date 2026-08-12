"""ComplianceHold endpoints (PRD 3.8): open manual hold, list/get, resolve,
plus flat fetch/search. Opening or resolving recomputes the tour's posture
on the spot."""
from flask import Blueprint, request

from db import store, new_entity, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body, v_str, v_enum,
)
from response import success_object, list_response
from services import (
    HOLD_KINDS, HOLD_SEVERITIES,
    compliance_hold_json, resolve_tour, resolve_compliance_hold,
    recompute_tour_posture,
)

bp = Blueprint("compliance", __name__)

TM_ONLY = frozenset({ROLE_TOUR_MANAGER})


@bp.post("/tours/<tourId>/compliance-holds")
def create_compliance_hold(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    b = get_body()
    hold_kind = v_enum(b, "hold_kind", HOLD_KINDS)
    severity = v_enum(b, "severity", HOLD_SEVERITIES)
    related_show_id = v_str(b, "related_show_id", required=False)
    if related_show_id is not None:
        rel = store["shows"].get(related_show_id)
        if rel is None or rel["tour_id"] != t["id"]:
            raise ApiError(
                "ERR_REFERENTIAL_INTEGRITY",
                422,
                "related_show_id does not resolve within the same tour",
            )
    reason = v_str(b, "reason")
    h = new_entity()
    h.update(
        {
            "tour_id": t["id"],
            "hold_kind": hold_kind,
            "severity": severity,
            "related_show_id": related_show_id,
            "reason": reason,
            "status": "ACTIVE",
        }
    )
    store["compliance_holds"][h["id"]] = h
    if recompute_tour_posture(t):
        touch(t)
    return success_object(compliance_hold_json(h), 201)


@bp.get("/tours/<tourId>/compliance-holds")
def list_compliance_holds(tourId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    status = request.args.get("status")
    severity = request.args.get("severity")
    items = [h for h in store["compliance_holds"].values() if h["tour_id"] == t["id"]]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    if severity is not None:
        items = [h for h in items if h["severity"] == severity]
    return list_response(items, compliance_hold_json)


@bp.get("/tours/<tourId>/compliance-holds/<holdId>")
def get_compliance_hold(tourId, holdId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    return success_object(compliance_hold_json(resolve_compliance_hold(t, holdId)))


@bp.post("/tours/<tourId>/compliance-holds/<holdId>/resolve")
def resolve_compliance_hold_endpoint(tourId, holdId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    h = resolve_compliance_hold(t, holdId)
    if h["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "resolve requires ComplianceHold.status == ACTIVE"
        )
    h["status"] = "RESOLVED"
    touch(h)
    if recompute_tour_posture(t):
        touch(t)
    return success_object(compliance_hold_json(h))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/compliance-holds/<holdId>")
def flat_get_compliance_hold(holdId):
    authenticate(READ_ROLES)
    h = store["compliance_holds"].get(holdId)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ComplianceHold not found")
    return success_object(compliance_hold_json(h))


@bp.get("/tours/compliance-holds")
def flat_search_compliance_holds():
    authenticate(READ_ROLES)
    tour_id = request.args.get("tour_id")
    items = list(store["compliance_holds"].values())
    if tour_id is not None:
        items = [h for h in items if h["tour_id"] == tour_id]
    return list_response(items, compliance_hold_json)
