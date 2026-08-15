"""Course segments and role catalog entries."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import get_body, require_field, optional_field, as_string, as_int, as_number, as_enum
from services.core import (
    make_record, touch, paginate, sort_by_created,
    serialize_segment, serialize_role,
    get_event_or_404, get_segment_or_404, get_role_or_404,
    NON_TERMINAL_SIGNUP,
)

bp = Blueprint("catalog", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")

TERRAINS = {"ROAD", "TRAIL", "BRIDGE", "TRACK"}
SKILLS = {"NONE", "MEDICAL", "BIKE_MARSHAL", "TIMING_TECH", "COURSE_MARSHAL"}
MODULES = {"NONE", "SAFETY_BRIEFING", "MEDICAL_RESPONSE", "CAPTAIN_COURSE"}


# ---------------- Course Segments ----------------

@bp.post("/volunteer-ops/course-segments")
def create_segment():
    require_roles("VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    get_event_or_404(event_id)
    segment_code = as_string(require_field(body, "segment_code"), "segment_code")
    mile_start = as_number(require_field(body, "mile_start"), "mile_start")
    mile_end = as_number(require_field(body, "mile_end"), "mile_end")
    terrain = as_enum(require_field(body, "terrain_type"), "terrain_type", TERRAINS)

    if not (mile_end > mile_start):
        raise errors.invalid_request("mile_end must be strictly greater than mile_start.")
    # uniqueness of segment_code within event
    for seg in store.course_segments.values():
        if seg["event_id"] == event_id and seg["segment_code"] == segment_code:
            raise errors.invalid_request("segment_code must be unique within the event.")
    # half-open mile overlap: conflict iff mile_start < e AND s < mile_end
    for seg in store.course_segments.values():
        if seg["event_id"] != event_id:
            continue
        if mile_start < seg["mile_end"] and seg["mile_start"] < mile_end:
            raise errors.segment_mile_overlap()

    rec = make_record({
        "event_id": event_id,
        "segment_code": segment_code,
        "mile_start": mile_start,
        "mile_end": mile_end,
        "terrain_type": terrain,
    })
    store.course_segments[rec["id"]] = rec
    return success_object(serialize_segment(rec), status=201)


@bp.get("/volunteer-ops/course-segments")
def list_segments():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    items = [s for s in store.course_segments.values()
             if event_id is None or s["event_id"] == event_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_segment(s) for s in page], limit, offset, total)


@bp.get("/volunteer-ops/course-segments/<segmentId>")
def get_segment(segmentId):
    require_roles(*ANY)
    seg = get_segment_or_404(segmentId)
    return success_object(serialize_segment(seg))


# ---------------- Role Catalog Entries ----------------

@bp.post("/volunteer-ops/role-catalog-entries")
def create_role():
    require_roles("VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    get_event_or_404(event_id)
    role_code = as_string(require_field(body, "role_code"), "role_code")
    title = as_string(require_field(body, "title"), "title")
    min_age = as_int(require_field(body, "min_age_years"), "min_age_years")
    req_skill = as_enum(optional_field(body, "required_skill", "NONE"), "required_skill", SKILLS)
    req_module = as_enum(optional_field(body, "required_training_module", "NONE"),
                         "required_training_module", MODULES)
    credit_weight = optional_field(body, "credit_weight", 1.0)
    credit_weight = as_number(credit_weight, "credit_weight")

    if min_age < 0:
        raise errors.invalid_request("min_age_years must be >= 0.")
    if not (credit_weight > 0 and credit_weight <= 3):
        raise errors.invalid_request("credit_weight must be > 0 and <= 3.")
    for r in store.role_catalog_entries.values():
        if r["event_id"] == event_id and r["role_code"] == role_code:
            raise errors.invalid_request("role_code must be unique within the event.")

    rec = make_record({
        "event_id": event_id,
        "role_code": role_code,
        "title": title,
        "min_age_years": min_age,
        "required_skill": req_skill,
        "required_training_module": req_module,
        "credit_weight": credit_weight,
        "status": "ACTIVE",
    })
    store.role_catalog_entries[rec["id"]] = rec
    return success_object(serialize_role(rec), status=201)


@bp.get("/volunteer-ops/role-catalog-entries")
def list_roles():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    items = [r for r in store.role_catalog_entries.values()
             if event_id is None or r["event_id"] == event_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_role(r) for r in page], limit, offset, total)


@bp.get("/volunteer-ops/role-catalog-entries/<roleEntryId>")
def get_role(roleEntryId):
    require_roles(*ANY)
    role = get_role_or_404(roleEntryId)
    return success_object(serialize_role(role))


@bp.post("/volunteer-ops/role-catalog-entries/<roleEntryId>/suspend")
def suspend_role(roleEntryId):
    require_roles("VolunteerCoordinator")
    role = get_role_or_404(roleEntryId)
    if role["status"] != "ACTIVE":
        raise errors.role_entry_invalid_state()
    role["status"] = "SUSPENDED"
    touch(role)
    return success_object(serialize_role(role))


@bp.post("/volunteer-ops/role-catalog-entries/<roleEntryId>/reactivate")
def reactivate_role(roleEntryId):
    require_roles("VolunteerCoordinator")
    role = get_role_or_404(roleEntryId)
    if role["status"] != "SUSPENDED":
        raise errors.role_entry_invalid_state()
    role["status"] = "ACTIVE"
    touch(role)
    return success_object(serialize_role(role))


def _role_has_nonterminal_signups(role_id):
    shift_ids = {s["id"] for s in store.shifts.values() if s["role_entry_id"] == role_id}
    return any(
        su["shift_id"] in shift_ids and su["status"] in NON_TERMINAL_SIGNUP
        for su in store.signups.values()
    )


@bp.post("/volunteer-ops/role-catalog-entries/<roleEntryId>/retire")
def retire_role(roleEntryId):
    require_roles("VolunteerCoordinator")
    role = get_role_or_404(roleEntryId)
    if role["status"] not in {"ACTIVE", "SUSPENDED"}:
        raise errors.role_entry_invalid_state()
    if _role_has_nonterminal_signups(role["id"]):
        raise errors.role_in_use()
    role["status"] = "RETIRED"
    touch(role)
    return success_object(serialize_role(role))
