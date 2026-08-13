"""Environmental events and compliance holds (PRD 3.8, 3.9)."""

from flask import Blueprint, g, request

import clock
import db
import response
from errors import (
    not_found, invalid_state, already_terminal, unauthorized, ApiError,
)
from middleware import require_roles, check_owner_job
from money import VIOLATION_PPM, ADVISORY_PPM
from services import lifecycle
from validation import (
    get_body, req_str, req_enum, req_bool, req_number, parse_pagination, page,
)
from .jobs import get_job_or_404, TERMINAL_JOB_STATES

bp = Blueprint("compliance", __name__)

EVENT_KINDS = ("WASHDOWN", "SANDING", "PAINT_SPRAY")
HOLD_KINDS = ("ENVIRONMENTAL", "PAYMENT")
# Environmental events may be logged only against on-hard jobs.
LOGGABLE_JOB_STATES = ("ON_HARD", "WORK_IN_PROGRESS", "READY_FOR_SPLASH")
# Kind-segregated hold roles.
HOLD_KIND_ROLES = {"ENVIRONMENTAL": "EnvironmentalOfficer", "PAYMENT": "Accountant"}
# Terminal event states (scaffold 1.2).
TERMINAL_EVENT_STATES = ("LOGGED", "ADVISORY", "REMEDIATED")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if ev is None:
        raise not_found(f"EnvironmentalEvent '{event_id}' does not exist")
    return ev


def get_hold_or_404(hold_id):
    hold = db.holds.get(hold_id)
    if hold is None:
        raise not_found(f"ComplianceHold '{hold_id}' does not exist")
    return hold


@bp.post("/yard/environmental-events")
@require_roles("EnvironmentalOfficer")
def create_event():
    body = get_body()
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    kind = req_enum(body, "kind", EVENT_KINDS)
    containment = req_bool(body, "containment_used")
    ppm = req_number(body, "runoff_tss_ppm", ge=0)

    if job["status"] not in LOGGABLE_JOB_STATES:
        raise invalid_state(
            f"Environmental events require the job on the hard (job is {job['status']})")

    # runoff_compliance_check: >= 100 is a violation (boundary inclusive);
    # >= 50 advisory; below 50 simply logged.
    if ppm >= VIOLATION_PPM:
        status = "VIOLATION_FLAGGED"
    elif ppm >= ADVISORY_PPM:
        status = "ADVISORY"
    else:
        status = "LOGGED"

    now = db.now_iso()
    event = {
        "id": db.new_id(),
        "job_id": job["id"],
        "kind": kind,
        "containment_used": containment,
        "runoff_tss_ppm": ppm,
        "occurred_at": clock.today().isoformat(),
        "status": status,
        "remediation_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.events[event["id"]] = event

    if status == "VIOLATION_FLAGGED":
        # Four-hop violation cascade (hold creation revokes readiness, cancels
        # BOOKED splash slots, and pauses IN_PROGRESS work orders).
        lifecycle.open_hold(
            job, "ENVIRONMENTAL", "AUTO_VIOLATION",
            note=f"Automatic hold: environmental violation event {event['id']}",
            source_event_id=event["id"],
        )
    return response.success_object(db.pub(event), status=201)


@bp.get("/yard/refit-jobs/<jobId>/environmental-events")
@require_roles("EnvironmentalOfficer", "YardManager", "ServiceWriter")
def list_events(jobId):
    job = get_job_or_404(jobId)
    limit, offset = parse_pagination()
    items = [e for e in db.events.values() if e["job_id"] == job["id"]]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/environmental-events/<eventId>/remediate")
@require_roles("EnvironmentalOfficer")
def remediate_event(eventId):
    event = get_event_or_404(eventId)
    body = get_body()
    note = req_str(body, "remediation_note")
    if event["status"] in TERMINAL_EVENT_STATES:
        raise already_terminal(f"EnvironmentalEvent is in terminal state {event['status']}")
    event["status"] = "REMEDIATED"
    event["remediation_note"] = note
    db.touch(event)
    # Remediation releases the AUTO_VIOLATION hold this event created.
    job = db.jobs.get(event["job_id"])
    if job is not None:
        for h in db.holds.values():
            if (h.get("source_event_id") == event["id"]
                    and h["source"] == "AUTO_VIOLATION" and h["status"] == "OPEN"):
                lifecycle.release_hold(job, h)
                break
    return response.success_object(db.pub(event))


@bp.post("/yard/compliance-holds")
@require_roles("Accountant", "EnvironmentalOfficer")
def create_hold():
    body = get_body()
    kind = body.get("kind")
    # Kind-conditional segregation (authorization) is enforced before
    # body-existence/shape when the kind is determinable.
    if isinstance(kind, str) and kind in HOLD_KIND_ROLES:
        if HOLD_KIND_ROLES[kind] != g.user_role:
            raise unauthorized(f"A {kind} hold may be placed only by {HOLD_KIND_ROLES[kind]}")
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    kind = req_enum(body, "kind", HOLD_KINDS)
    note = req_str(body, "note")
    if HOLD_KIND_ROLES[kind] != g.user_role:
        raise unauthorized(f"A {kind} hold may be placed only by {HOLD_KIND_ROLES[kind]}")
    if job["status"] in TERMINAL_JOB_STATES:
        raise invalid_state("A hold cannot be placed on a terminal job")
    hold = lifecycle.open_hold(job, kind, "MANUAL", note)
    return response.success_object(db.pub(hold), status=201)


@bp.get("/yard/refit-jobs/<jobId>/compliance-holds")
@require_roles("ServiceWriter", "YardManager", "Accountant", "EnvironmentalOfficer", "Owner")
def list_holds(jobId):
    job = get_job_or_404(jobId)
    check_owner_job(job)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [h for h in db.holds.values() if h["job_id"] == job["id"]]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/compliance-holds/<holdId>/release")
@require_roles("Accountant", "EnvironmentalOfficer")
def release_hold(holdId):
    hold = get_hold_or_404(holdId)
    if HOLD_KIND_ROLES.get(hold["kind"]) != g.user_role:
        raise unauthorized(
            f"A {hold['kind']} hold may be released only by {HOLD_KIND_ROLES.get(hold['kind'])}")
    if hold["status"] == "RELEASED":
        raise already_terminal("ComplianceHold is already RELEASED")
    if hold["source"] == "AUTO_VIOLATION":
        raise invalid_state(
            "An AUTO_VIOLATION hold is released only by remediating its source event")
    job = db.jobs.get(hold["job_id"])
    lifecycle.release_hold(job, hold)
    return response.success_object(db.pub(hold))
