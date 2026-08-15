"""Volunteer registration and screening clearance (PRD 3.2)."""

from flask import Blueprint

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        new_common_fields, new_audit_fields, touch)
from validation import (get_body, as_str, as_int_range, pagination_params,
                        paginate, sort_by_creation, as_enum, present)
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SCREENING_NOT_CLEARED
from services import calc
from services.serialize import volunteer_view, screening_event_view

bp = Blueprint("volunteers", __name__)

EVENT_KINDS = ("BACKGROUND_CHECK", "REFERENCE_CHECK", "INTERVIEW")
EVENT_OUTCOMES = ("PASS", "FLAG", "FAIL")


@bp.post("/volunteers")
def create_volunteer():
    role, user_id = authenticate(["ProgramAdmin"])
    body = get_body()
    # Priority 3: referenced identifiers exist (body order: club_id).
    if isinstance(body.get("club_id"), str):
        must_find("clubs", body["club_id"], "Club")
    resolve_caller(role, user_id)  # ProgramAdmin: no-op resolution
    # Priority 14: request shape.
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    base_clearance = as_int_range(body, "base_clearance", lo=0, hi=100)
    risk_flags = 0
    if "risk_flags" in body and body["risk_flags"] is not None:
        risk_flags = as_int_range(body, "risk_flags", lo=0)
    years_service = 0
    if "years_service" in body and body["years_service"] is not None:
        years_service = as_int_range(body, "years_service", lo=0)
    club_id = present(body, "club_id")
    if not isinstance(club_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'club_id': must be a string")
    club = must_find("clubs", club_id, "Club")
    # Email is unique across all volunteers (PRD 3.2).
    for existing in db.table("volunteers").values():
        if existing["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "A volunteer with email '%s' already exists" % email)
    rec = new_common_fields()
    rec.update({
        "full_name": full_name,
        "email": email,
        "base_clearance": base_clearance,
        "risk_flags": risk_flags,
        "years_service": years_service,
        "screening_score": calc.volunteer_screening_score(base_clearance, risk_flags, years_service),
        "screening_status": "PENDING",
        "club_id": club["id"],
    })
    db.table("volunteers")[rec["id"]] = rec
    return response.success(volunteer_view(rec), status=201)


@bp.get("/volunteers/<vid>")
def get_volunteer(vid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    rec = must_find("volunteers", vid, "Volunteer")
    resolve_caller(role, user_id)
    return response.success(volunteer_view(rec))


@bp.post("/volunteers/<vid>/clear")
def clear_volunteer(vid):
    role, user_id = authenticate(["ProgramAdmin"])
    rec = must_find("volunteers", vid, "Volunteer")
    resolve_caller(role, user_id)
    # Priority 5: state precondition.
    if rec["screening_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Volunteer screening_status must be PENDING to clear")
    # Priority 7: clearance requires score >= 40 and no FAIL screening event.
    has_fail = any(e["volunteer_id"] == rec["id"] and e["outcome"] == "FAIL"
                   for e in db.table("screening_events").values())
    if rec["screening_score"] < calc.CLEARANCE_THRESHOLD or has_fail:
        raise ApiError(ERR_SCREENING_NOT_CLEARED, 422,
                       "Clearance requires screening_score >= 40 and no FAIL screening event")
    rec["screening_status"] = "CLEARED"
    touch(rec)
    return response.success(volunteer_view(rec))


@bp.post("/volunteers/<vid>/deny")
def deny_volunteer(vid):
    role, user_id = authenticate(["ProgramAdmin"])
    rec = must_find("volunteers", vid, "Volunteer")
    resolve_caller(role, user_id)
    if rec["screening_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Volunteer screening_status must be PENDING to deny")
    rec["screening_status"] = "DENIED"
    touch(rec)
    return response.success(volunteer_view(rec))


@bp.get("/volunteers/<vid>/screening-events")
def list_screening_events(vid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    vol = must_find("volunteers", vid, "Volunteer")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [e for e in db.table("screening_events").values()
         if e["volunteer_id"] == vol["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([screening_event_view(e) for e in page],
                            response_type="array", pagination=meta)


@bp.post("/screening-events")
def create_screening_event():
    role, user_id = authenticate(["ProgramAdmin"])
    body = get_body()
    # Priority 3: referenced identifiers exist.
    if isinstance(body.get("volunteer_id"), str):
        must_find("volunteers", body["volunteer_id"], "Volunteer")
    resolve_caller(role, user_id)
    # Priority 14: request shape.
    volunteer_id = present(body, "volunteer_id")
    if not isinstance(volunteer_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'volunteer_id': must be a string")
    vol = must_find("volunteers", volunteer_id, "Volunteer")
    event_kind = as_enum(body, "event_kind", EVENT_KINDS)
    outcome = as_enum(body, "outcome", EVENT_OUTCOMES)
    rec = new_audit_fields()
    rec.update({
        "volunteer_id": vol["id"],
        "event_kind": event_kind,
        "outcome": outcome,
    })
    db.table("screening_events")[rec["id"]] = rec
    # Side effect: recompute the volunteer's screening_score from the same
    # three inputs; each recomputation increments the volunteer's version.
    vol["screening_score"] = calc.volunteer_screening_score(
        vol["base_clearance"], vol["risk_flags"], vol["years_service"])
    touch(vol)
    return response.success(screening_event_view(rec), status=201)
