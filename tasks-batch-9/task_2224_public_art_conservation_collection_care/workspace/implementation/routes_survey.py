"""Condition surveys and routine maintenance visits (PRD 3.2, 3.3)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import services as svc
from db import (
    create_record,
    db,
    fmt_date,
    fmt_instant,
    now,
    ordered,
    parse_instant,
    touch,
)
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, listing, ok
from validate import (
    apply_filters,
    bad,
    field,
    paging,
    parse_input,
)

bp = Blueprint("survey", __name__)


# ---------------------------------------------------------------------------
# ConditionAssessment
# ---------------------------------------------------------------------------

@bp.post("/public-art/condition-assessments")
@endpoint(("ConditionSurveyor",))
def create_assessment():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "cycle_year": field("int", required=True, minimum=2000, maximum=2100),
        "assessed_on": field("date", required=True),
        "surface_score": field("int", required=True, minimum=0, maximum=4),
        "structural_score": field("int", required=True, minimum=0, maximum=4),
        "coating_score": field("int", required=True, minimum=0, maximum=4),
        "mount_score": field("int", required=True, minimum=0, maximum=4),
        "graffiti_score": field("int", required=True, minimum=0, maximum=4),
    })
    artwork = svc.artwork_or_404(body["artwork_id"])
    svc.require_in_collection(artwork)
    record = create_record(db.assessments, {
        "artwork_id": artwork["id"],
        "cycle_year": body["cycle_year"],
        "assessed_on": body["assessed_on"],
        "surface_score": body["surface_score"],
        "structural_score": body["structural_score"],
        "coating_score": body["coating_score"],
        "mount_score": body["mount_score"],
        "graffiti_score": body["graffiti_score"],
        "photo_count": 0,
        "photo_view_codes": [],
        "condition_index": None,
        "recommendation": "NONE",
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "finalized_by_user_id": None,
        "revision_rounds": 0,
    })
    return created(record)


@bp.get("/public-art/condition-assessments/<assessment_id>")
@endpoint(ANY_ROLE)
def read_assessment(assessment_id):
    return ok(svc.assessment_or_404(assessment_id))


@bp.get("/public-art/condition-assessments")
@endpoint(ANY_ROLE)
def list_assessments():
    limit, offset = paging()
    rows = apply_filters(db.assessments.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("cycle_year", "cycle_year", "int"),
        ("status", "status", "string"),
        ("recommendation", "recommendation", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/condition-assessments/<assessment_id>/photos")
@endpoint(("ConditionSurveyor",))
def attach_photo(assessment_id):
    assessment = svc.assessment_or_404(assessment_id)
    body = parse_input({
        "view_code": field("string", required=True),
        "media_ref": field("string", required=True),
        "caption": field("string"),
    })
    svc.require_state(
        assessment["status"], ("DRAFT", "REVISION_REQUESTED"), "ERR_ASSESSMENT_INVALID_STATE"
    )
    assessment["photo_count"] = int(assessment["photo_count"]) + 1
    if body["view_code"] not in assessment["photo_view_codes"]:
        assessment["photo_view_codes"].append(body["view_code"])
    touch(assessment)
    return ok(assessment)


@bp.post("/public-art/condition-assessments/<assessment_id>/submit")
@endpoint(("ConditionSurveyor",))
def submit_assessment(assessment_id):
    assessment = svc.assessment_or_404(assessment_id)
    parse_input({"surveyor_note": field("string")})
    svc.require_state(
        assessment["status"], ("DRAFT", "REVISION_REQUESTED"), "ERR_ASSESSMENT_INVALID_STATE"
    )
    first_pass = assessment["status"] == "DRAFT"
    if first_pass:
        svc.require_in_collection(svc.artwork_or_404(assessment["artwork_id"]))
    if int(assessment["photo_count"]) < calc.MIN_ASSESSMENT_PHOTOS:
        raise ApiError("ERR_PHOTO_DOCUMENTATION_INSUFFICIENT")
    assessment["status"] = "SUBMITTED"
    assessment["submitted_by_user_id"] = g.user_id
    touch(assessment)
    return ok(assessment)


@bp.post("/public-art/condition-assessments/<assessment_id>/request-revision")
@endpoint(("ChiefConservator",))
def request_assessment_revision(assessment_id):
    assessment = svc.assessment_or_404(assessment_id)
    parse_input({"reviewer_note": field("string", required=True)})
    svc.require_state(assessment["status"], ("SUBMITTED",), "ERR_ASSESSMENT_INVALID_STATE")
    if int(assessment["revision_rounds"]) >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")
    assessment["status"] = "REVISION_REQUESTED"
    assessment["revision_rounds"] = int(assessment["revision_rounds"]) + 1
    touch(assessment)
    return ok(assessment)


@bp.post("/public-art/condition-assessments/<assessment_id>/finalize")
@endpoint(("ChiefConservator",))
def finalize_assessment(assessment_id):
    assessment = svc.assessment_or_404(assessment_id)
    parse_input({"finalization_note": field("string")})
    svc.require_state(assessment["status"], ("SUBMITTED",), "ERR_ASSESSMENT_INVALID_STATE")
    if g.user_id == assessment.get("submitted_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    artwork = svc.artwork_or_404(assessment["artwork_id"])
    svc.require_in_collection(artwork)

    site = svc.site_of(artwork)
    index = calc.condition_index(assessment, artwork, site)
    assessment["condition_index"] = index
    assessment["recommendation"] = calc.recommendation_band(index)
    assessment["status"] = "FINALIZED"
    assessment["finalized_by_user_id"] = g.user_id
    touch(assessment)

    svc.cascade_a(assessment, artwork)
    return ok(assessment)


# ---------------------------------------------------------------------------
# MaintenanceVisit
# ---------------------------------------------------------------------------

def _windows_collide_closed(start_a, end_a, start_b, end_b):
    """Site work windows are CLOSED intervals: touching endpoints collide."""
    return start_a <= end_b and start_b <= end_a


@bp.post("/public-art/maintenance-visits")
@endpoint(("MaintenanceCrew", "ChiefConservator"))
def create_visit():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "protocol_id": field("id", required=True),
        "window_start": field("datetime", required=True),
        "window_end": field("datetime", required=True),
        "graffiti_reported_at": field("datetime"),
        "crew_note": field("string"),
    })
    window_start = parse_instant(body["window_start"])
    window_end = parse_instant(body["window_end"])
    if window_end <= window_start:
        bad("window_end must be strictly after window_start.")

    artwork = svc.artwork_or_404(body["artwork_id"])
    protocol = svc.protocol_or_404(body["protocol_id"])
    svc.require_in_collection(artwork)
    if protocol["material_class"] != artwork["material_class"]:
        raise ApiError("ERR_PROTOCOL_MATERIAL_MISMATCH")
    if window_start < now():
        raise ApiError("ERR_WINDOW_IN_PAST")

    site = svc.site_of(artwork)
    if site is not None:
        colliding = 0
        for other in db.visits.values():
            if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            other_art = db.artworks.get(other["artwork_id"])
            if other_art is None or other_art["site_id"] != site["id"]:
                continue
            if _windows_collide_closed(
                window_start,
                window_end,
                parse_instant(other["window_start"]),
                parse_instant(other["window_end"]),
            ):
                colliding += 1
        if colliding >= int(site["concurrent_work_capacity"]):
            raise ApiError("ERR_SITE_WORK_CAPACITY_CONFLICT")

    sla_deadline = None
    if body["graffiti_reported_at"] is not None:
        hours = calc.GRAFFITI_SLA_HOURS[artwork["material_class"]]
        sla_deadline = fmt_instant(
            parse_instant(body["graffiti_reported_at"]) + timedelta(hours=hours)
        )

    record = create_record(db.visits, {
        "artwork_id": artwork["id"],
        "protocol_id": protocol["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "graffiti_reported_at": body["graffiti_reported_at"],
        "crew_note": body["crew_note"],
        "status": "SCHEDULED",
        "abort_reason": "NONE",
        "started_at": None,
        "completed_at": None,
        "sla_deadline_at": sla_deadline,
        "sla_breached": False,
    })
    return created(record)


@bp.get("/public-art/maintenance-visits/<visit_id>")
@endpoint(ANY_ROLE)
def read_visit(visit_id):
    return ok(svc.visit_or_404(visit_id))


@bp.get("/public-art/maintenance-visits")
@endpoint(ANY_ROLE)
def list_visits():
    limit, offset = paging()
    rows = apply_filters(db.visits.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("protocol_id", "protocol_id", "string"),
        ("status", "status", "string"),
        ("abort_reason", "abort_reason", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/maintenance-visits/<visit_id>/start")
@endpoint(("MaintenanceCrew",))
def start_visit(visit_id):
    visit = svc.visit_or_404(visit_id)
    body = parse_input({"crew_note": field("string")})
    svc.require_state(visit["status"], ("SCHEDULED",), "ERR_VISIT_INVALID_STATE")
    artwork = svc.artwork_or_404(visit["artwork_id"])
    svc.require_in_collection(artwork)
    if artwork["custody_status"] not in ("ON_VIEW", "IN_STORAGE"):
        raise ApiError("ERR_ARTWORK_CUSTODY_INVALID")
    if now() < parse_instant(visit["window_start"]):
        raise ApiError("ERR_VISIT_WINDOW_NOT_OPEN")

    visit["status"] = "IN_PROGRESS"
    visit["started_at"] = fmt_instant(now())
    if body["crew_note"] is not None:
        visit["crew_note"] = body["crew_note"]
    touch(visit)
    svc.advance_allocations(svc.allocations_for_visit(visit["id"]), "RESERVED", "COMMITTED")
    return ok(visit)


@bp.post("/public-art/maintenance-visits/<visit_id>/complete")
@endpoint(("MaintenanceCrew",))
def complete_visit(visit_id):
    visit = svc.visit_or_404(visit_id)
    parse_input({"completion_note": field("string")})
    svc.require_state(visit["status"], ("IN_PROGRESS",), "ERR_VISIT_INVALID_STATE")
    artwork = svc.artwork_or_404(visit["artwork_id"])
    svc.require_in_collection(artwork)
    protocol = db.protocols.get(visit["protocol_id"])

    year = now().year
    completed_this_year = 0
    for other in db.visits.values():
        if (
            other["artwork_id"] == visit["artwork_id"]
            and other["protocol_id"] == visit["protocol_id"]
            and other["status"] == "COMPLETED"
            and other.get("completed_at")
        ):
            try:
                if parse_instant(other["completed_at"]).year == year:
                    completed_this_year += 1
            except Exception:
                continue
    ceiling = int(protocol["max_annual_applications"]) if protocol else 0
    if completed_this_year >= ceiling:
        raise ApiError("ERR_MAX_ANNUAL_APPLICATIONS")

    completed_at = now()
    visit["status"] = "COMPLETED"
    visit["completed_at"] = fmt_instant(completed_at)
    if visit.get("sla_deadline_at"):
        visit["sla_breached"] = completed_at > parse_instant(visit["sla_deadline_at"])
    touch(visit)

    artwork["last_maintenance_completed_on"] = fmt_date(completed_at)
    cycle_days = int(protocol["cycle_days"]) if protocol else 0
    artwork["next_maintenance_due_on"] = fmt_date(completed_at + timedelta(days=cycle_days))
    touch(artwork)
    svc.recompute_maintenance_ytd(artwork)

    svc.advance_allocations(svc.allocations_for_visit(visit["id"]), "COMMITTED", "DISBURSED")
    return ok(visit)
