"""Habitat assessments and mitigation actions."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, biologist_is_senior
from constants import (HABITAT_FEATURES, ACTION_TYPES, MITIGATION_STATUSES,
                       MANDATORY_MITIGATION_THRESHOLD)
from db import store
from services import hazard_is_critical, recompute_airport
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, now)

bp = Blueprint("habitat", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent")


def _get_assessment(rid):
    return get_or_404(store.habitat_assessments, rid, "habitat assessment")


def _get_mitigation(rid):
    return get_or_404(store.mitigation_actions, rid, "mitigation action")


def _assessment_of(m):
    return store.habitat_assessments.get(m["habitat_assessment_id"])


# ------------------------------------------------------------- assessments
@bp.post("/habitat-assessments")
def create_assessment():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("assessed_by_biologist_id", "str", True),
        ("assessed_at", "datetime", True),
        ("habitat_feature", "enum", True, {"values": HABITAT_FEATURES}),
        ("attractiveness_score", "int", True, {"min": 1, "max": 10}),
        ("severity_score", "int", True, {"min": 1, "max": 10}),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    check_fk("assessed_by_biologist_id", data["assessed_by_biologist_id"], store.biologists, "biologist")
    # composite_habitat_score
    composite = data["attractiveness_score"] * data["severity_score"]
    # ERR_MITIGATION_REQUIRED: a >= 60 composite with no non-REJECTED mitigation
    # (a brand-new assessment has none) is rejected at creation time.
    if composite >= MANDATORY_MITIGATION_THRESHOLD:
        raise E.ApiError(E.ERR_MITIGATION_REQUIRED,
                         "composite_score >= 60 requires at least one non-REJECTED mitigation action", 422)
    rec = new_entity(store.habitat_assessments, {
        "airport_id": data["airport_id"],
        "assessed_by_biologist_id": data["assessed_by_biologist_id"],
        "assessed_at": data["assessed_at"],
        "habitat_feature": data["habitat_feature"],
        "attractiveness_score": data["attractiveness_score"],
        "severity_score": data["severity_score"],
        "composite_score": composite,
    })
    return ok_object(serialize(rec), 201)


@bp.get("/habitat-assessments")
def list_assessments():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    feature = args.get("habitat_feature")
    if feature is not None and feature not in HABITAT_FEATURES:
        raise E.invalid_enum("habitat_feature", feature)
    min_comp_raw = args.get("min_composite_score")
    min_comp = None
    if min_comp_raw is not None:
        try:
            min_comp = int(min_comp_raw)
        except (TypeError, ValueError):
            raise E.invalid_request("min_composite_score must be an integer")
    rows = [a for a in store.habitat_assessments.values()
            if (args.get("airport_id") is None or a["airport_id"] == args.get("airport_id"))
            and (args.get("assessed_by_biologist_id") is None or a["assessed_by_biologist_id"] == args.get("assessed_by_biologist_id"))
            and (feature is None or a["habitat_feature"] == feature)
            and (min_comp is None or a["composite_score"] >= min_comp)]
    return list_response(rows)


@bp.get("/habitat-assessments/<rid>")
def get_assessment(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_assessment(rid)))


# ------------------------------------------------------------- mitigations
@bp.post("/habitat-assessments/<rid>/mitigation-actions")
def create_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    assessment = _get_assessment(rid)
    data = validate_payload(body(), [
        ("action_type", "enum", True, {"values": ACTION_TYPES}),
        ("proposed_by_biologist_id", "str", True),
        ("target_completion_date", "date", True),
    ])
    check_fk("proposed_by_biologist_id", data["proposed_by_biologist_id"], store.biologists, "biologist")
    rec = new_entity(store.mitigation_actions, {
        "habitat_assessment_id": assessment["id"],
        "action_type": data["action_type"],
        "status": "PROPOSED",
        "proposed_by_biologist_id": data["proposed_by_biologist_id"],
        "reviewed_by_biologist_id": None,
        "target_completion_date": data["target_completion_date"],
        "completed_at": None,
        "effectiveness_rating": None,
    })
    return ok_object(serialize(rec), 201)


@bp.get("/habitat-assessments/<rid>/mitigation-actions")
def list_mitigations_for_assessment(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    assessment = _get_assessment(rid)
    rows = [m for m in store.mitigation_actions.values()
            if m["habitat_assessment_id"] == assessment["id"]]
    return list_response(rows)


@bp.get("/mitigation-actions")
def list_mitigations():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    if status is not None and status not in MITIGATION_STATUSES:
        raise E.invalid_enum("status", status)
    rows = [m for m in store.mitigation_actions.values()
            if (args.get("habitat_assessment_id") is None or m["habitat_assessment_id"] == args.get("habitat_assessment_id"))
            and (status is None or m["status"] == status)
            and (args.get("proposed_by_biologist_id") is None or m["proposed_by_biologist_id"] == args.get("proposed_by_biologist_id"))
            and (args.get("reviewed_by_biologist_id") is None or m.get("reviewed_by_biologist_id") == args.get("reviewed_by_biologist_id"))]
    return list_response(rows)


@bp.get("/mitigation-actions/<rid>")
def get_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_mitigation(rid)))


def _segregation(m, uid, verb):
    if uid == m["proposed_by_biologist_id"]:
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         f"the proposer cannot {verb} their own mitigation action", 403)


def _senior(uid, verb):
    if not biologist_is_senior(uid):
        raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                         f"{verb} a mitigation action requires a senior biologist", 403)


@bp.post("/mitigation-actions/<rid>/approve")
def approve_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    m = _get_mitigation(rid)
    if m["status"] != "PROPOSED":
        raise E.invalid_state("mitigation action must be in PROPOSED to approve")
    _segregation(m, uid, "approve")
    _senior(uid, "approving")
    parent = _assessment_of(m)
    composite = parent["composite_score"] if parent else 0
    if composite < MANDATORY_MITIGATION_THRESHOLD:
        override = body().get("override_note")
        if not (isinstance(override, str) and override.strip()):
            raise E.invalid_request(
                "parent assessment composite_score is below the mandatory threshold (60); "
                "approving requires a documented override (override_note)")
    m["status"] = "APPROVED"
    m["reviewed_by_biologist_id"] = uid
    touch(m)
    return ok_object(serialize(m))


@bp.post("/mitigation-actions/<rid>/reject")
def reject_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    m = _get_mitigation(rid)
    if m["status"] != "PROPOSED":
        raise E.invalid_state("mitigation action must be in PROPOSED to reject")
    _segregation(m, uid, "reject")
    _senior(uid, "rejecting")
    m["status"] = "REJECTED"
    touch(m)
    return ok_object(serialize(m))


@bp.post("/mitigation-actions/<rid>/start-work")
def start_work(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    m = _get_mitigation(rid)
    if m["status"] != "APPROVED":
        raise E.invalid_state("mitigation action must be in APPROVED to start work")
    parent = _assessment_of(m)
    if parent and hazard_is_critical(parent["airport_id"]):
        raise E.ApiError(E.ERR_HAZARD_CRITICAL_BLOCK,
                         "airport is at CRITICAL hazard level; starting mitigation work is blocked", 409)
    m["status"] = "IN_PROGRESS"
    touch(m)
    return ok_object(serialize(m))


@bp.post("/mitigation-actions/<rid>/verify")
def verify_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    m = _get_mitigation(rid)
    if m["status"] != "IN_PROGRESS":
        raise E.invalid_state("mitigation action must be in IN_PROGRESS to verify")
    _segregation(m, uid, "verify")
    m["status"] = "VERIFIED"
    touch(m)
    return ok_object(serialize(m))


@bp.post("/mitigation-actions/<rid>/complete")
def complete_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    m = _get_mitigation(rid)
    if m["status"] != "VERIFIED":
        raise E.invalid_state("mitigation action must be in VERIFIED to complete")
    _segregation(m, uid, "complete")
    _senior(uid, "completing")
    rating = body().get("effectiveness_rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or rating < 1 or rating > 5:
        raise E.invalid_request("effectiveness_rating is required and must be an integer in 1..5")
    m["effectiveness_rating"] = rating
    m["completed_at"] = now()
    m["status"] = "COMPLETED"
    touch(m)
    parent = _assessment_of(m)
    if parent:
        ap = store.airports.get(parent["airport_id"])
        if ap:
            recompute_airport(ap)
    return ok_object(serialize(m))


@bp.post("/mitigation-actions/<rid>/cancel")
def cancel_mitigation(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    m = _get_mitigation(rid)
    if m["status"] != "PROPOSED":
        raise E.invalid_state("mitigation action must be in PROPOSED to cancel")
    if uid != m["proposed_by_biologist_id"]:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         "only the proposer may cancel a mitigation action", 403)
    m["status"] = "CANCELLED"
    touch(m)
    return ok_object(serialize(m))
