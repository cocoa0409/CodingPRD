"""SupervisionVisit endpoints (PRD §3.5), including the UNANNOUNCED-visit
opacity rule: unannounced inspections are absent from ClientContact list
responses and return 404 on direct fetch."""
from datetime import timedelta

from flask import Blueprint, g

from db import logical_now, new_common, store, touch
from errors import err
from middleware import (get_or_404, require_roles, require_visit_assignment)
from response import Paginator, created, ok
from services.domain import (compromise_facility_lines, recompute_client_nc,
                             suspend_facility_cascade)
from validation import (body_json, req_datetime, req_enum, req_str,
                        require_end_after_start)

bp = Blueprint("visits", __name__)

VISIT_TYPES = ("INITIAL", "ROUTINE", "UNANNOUNCED", "SPECIAL_HOLIDAY")
TRAVEL_BUFFER_HOURS = 2


def _visible_visit(visit_id):
    """Existence check with the UNANNOUNCED opacity rule for ClientContact."""
    visit = store.visits.get(visit_id)
    if visit is None:
        err("ERR_NOT_FOUND", "Visit not found")
    if g.user_role == "ClientContact" and visit["visit_type"] == "UNANNOUNCED":
        err("ERR_NOT_FOUND", "Visit not found")
    return visit


def _apply_opacity(rows):
    if g.user_role == "ClientContact":
        return [v for v in rows if v["visit_type"] != "UNANNOUNCED"]
    return rows


@bp.post("/visits")
def create_visit():
    data = body_json()
    facility_id = req_str(data, "facility_id")
    visit_type = req_enum(data, "visit_type", VISIT_TYPES)
    inspector_user_id = req_str(data, "inspector_user_id")
    scheduled_start = req_datetime(data, "scheduled_start")
    scheduled_end = req_datetime(data, "scheduled_end")
    require_end_after_start(scheduled_start, scheduled_end,
                            "scheduled_start", "scheduled_end")
    require_roles("AccountManager", "CertificationReviewer")
    if visit_type == "UNANNOUNCED" and g.user_role != "CertificationReviewer":
        err("ERR_FORBIDDEN_ROLE",
            "UNANNOUNCED visits may be created only by CertificationReviewer")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    if visit_type == "INITIAL":
        if facility["status"] != "PENDING_REVIEW":
            err("ERR_FACILITY_INVALID_STATE",
                "INITIAL visits require facility status PENDING_REVIEW")
    elif facility["status"] == "DECOMMISSIONED":
        err("ERR_FACILITY_INVALID_STATE",
            "Visits may not be scheduled at a DECOMMISSIONED facility")
    # Inspector double-booking guard: reject iff new_start < existing_end + 2h
    # AND new_end > existing_start - 2h (both strict).
    buffer = timedelta(hours=TRAVEL_BUFFER_HOURS)
    for v in store.visits.values():
        if v["inspector_user_id"] != inspector_user_id:
            continue
        if v["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if (scheduled_start < v["scheduled_end"] + buffer
                and scheduled_end > v["scheduled_start"] - buffer):
            err("ERR_INSPECTOR_SCHEDULE_CONFLICT",
                "The inspector has an overlapping SCHEDULED/IN_PROGRESS visit "
                "within the two-hour travel buffer")
    visit = new_common({
        "facility_id": facility_id,
        "visit_type": visit_type,
        "inspector_user_id": inspector_user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
    })
    store.visits[visit["id"]] = visit
    return created(visit)


@bp.get("/visits")
def list_visits():
    p = Paginator()
    rows = _apply_opacity(list(store.visits.values()))
    rows = p.filter(rows, "facility_id")
    rows = p.filter(rows, "inspector_user_id")
    rows = p.filter(rows, "status")
    rows = p.filter(rows, "visit_type")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/visits/<visit_id>")
def get_visit(visit_id):
    return ok(_visible_visit(visit_id))


@bp.get("/facilities/<facility_id>/visits")
def list_facility_visits(facility_id):
    get_or_404(store.facilities, facility_id, "Facility")
    p = Paginator()
    rows = [v for v in store.visits.values() if v["facility_id"] == facility_id]
    rows = _apply_opacity(rows)
    return ok(p(rows), rtype="array", pagination=p)


@bp.post("/visits/<visit_id>/start")
def start_visit(visit_id):
    require_roles("FieldSupervisor")
    visit = _visible_visit(visit_id)
    require_visit_assignment(visit)
    if visit["status"] != "SCHEDULED":
        err("ERR_VISIT_INVALID_STATE", "start requires visit status SCHEDULED")
    now = logical_now()
    if not (visit["scheduled_start"] <= now <= visit["scheduled_end"]):
        err("ERR_VISIT_WINDOW_NOT_ACTIVE",
            "The current instant lies outside the scheduled window")
    visit["status"] = "IN_PROGRESS"
    touch(visit)
    return ok(visit)


@bp.post("/visits/<visit_id>/complete")
def complete_visit(visit_id):
    require_roles("FieldSupervisor")
    visit = _visible_visit(visit_id)
    require_visit_assignment(visit)
    if visit["status"] != "IN_PROGRESS":
        err("ERR_VISIT_INVALID_STATE", "complete requires visit status IN_PROGRESS")
    visit["status"] = "COMPLETED"
    touch(visit)
    return ok(visit)


def _no_access_side_effects(visit):
    """Auto-create the CRITICAL finding and fire the facility cascade."""
    now = logical_now()
    facility = store.facilities.get(visit["facility_id"])
    finding = new_common({
        "visit_id": visit["id"],
        "facility_id": visit["facility_id"],
        "severity": "CRITICAL",
        "description": "Inspector denied access to the facility",
        "remediation_deadline": now + timedelta(days=7),
        "origin": "AUTO_NO_ACCESS",
        "status": "OPEN",
    })
    store.findings[finding["id"]] = finding
    if facility is None:
        return
    client = store.clients.get(facility["client_id"])
    if client is not None:
        recompute_client_nc(client)
    suspend_facility_cascade(facility)
    compromise_facility_lines(facility)


@bp.post("/visits/<visit_id>/no-access")
def no_access_visit(visit_id):
    require_roles("FieldSupervisor")
    visit = _visible_visit(visit_id)
    require_visit_assignment(visit)
    if visit["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        err("ERR_VISIT_INVALID_STATE",
            "no-access requires visit status SCHEDULED or IN_PROGRESS")
    visit["status"] = "NO_ACCESS"
    touch(visit)
    _no_access_side_effects(visit)
    return ok(visit)


@bp.post("/visits/<visit_id>/cancel")
def cancel_visit(visit_id):
    require_roles("AccountManager")
    visit = _visible_visit(visit_id)
    if visit["status"] != "SCHEDULED":
        err("ERR_VISIT_INVALID_STATE", "cancel requires visit status SCHEDULED")
    visit["status"] = "CANCELLED"
    touch(visit)
    return ok(visit)
