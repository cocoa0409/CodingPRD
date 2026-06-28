"""Court Reporting & Deposition API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
Behaviors trace to verbatim PRD sentences (see inline section references).
"""
import os
import secrets
from datetime import timedelta

from flask import Flask, request

from clock import clock
from db import db, new_id, stamp_create, touch
from errors import ApiError, err
from response import success, list_response, error_response
from auth import authenticate, require_role
from validate import (
    get_body, require_fields, require_str, opt_str, require_enum, opt_enum,
    require_int, opt_int, opt_bool, parse_datetime, parse_iso_value,
    pagination, paginate,
)
import lookups as L
import serialize as S
import calc

import errors as E

app = Flask(__name__)

JURISDICTIONS = {"FEDERAL", "STATE_CA", "STATE_NY", "STATE_TX"}
BAR_STATES = {"CA", "NY", "TX", "FED"}
RESOURCE_KINDS = {"REPORTER", "VIDEOGRAPHER", "INTERPRETER"}
TURNAROUND_TIERS = {"STANDARD", "EXPEDITE_14", "EXPEDITE_7", "EXPEDITE_3", "DAILY"}


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response(E.ERR_NOT_FOUND, 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response(E.ERR_NOT_FOUND, 404, "Resource not found.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response(E.ERR_INVALID_REQUEST, 400, str(e))


# =============================================================================
# Staffing posture helper with version bump on derived-field change (PRD §2.4)
# =============================================================================
def recompute_posture(job):
    job["staffing_posture"] = calc.compute_staffing_posture(job)


# =============================================================================
# Clock (PRD §2.8)
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso_value(body["to_iso8601"], "to_iso8601")
    clock.set(dt)
    from db import iso_ts
    return success({"current_utc": iso_ts(clock.now())})


# =============================================================================
# Cases (PRD §3.1)
# =============================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["caption", "docket_number", "jurisdiction", "noticing_attorney_id"])
    caption = require_str(body, "caption")
    docket = require_str(body, "docket_number")
    jurisdiction = require_enum(body, "jurisdiction", JURISDICTIONS)
    noticing_attorney_id = require_str(body, "noticing_attorney_id")
    # Existence of FK (PRD §2.5) before business uniqueness.
    L.get_attorney(noticing_attorney_id)
    # docket_number unique across Cases (PRD §3.1, §3.15).
    for c in db.cases.values():
        if c["docket_number"] == docket:
            raise err(E.ERR_DUPLICATE_KEY, "docket_number already in use.")
    e = stamp_create({
        "id": new_id(),
        "caption": caption,
        "docket_number": docket,
        "jurisdiction": jurisdiction,
        "noticing_attorney_id": noticing_attorney_id,
    })
    db.cases[e["id"]] = e
    return success(S.case_out(e), status=201)


@app.route("/cases/<cid>", methods=["GET"])
def get_case_ep(cid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    e = L.get_case(cid)
    return success(S.case_out(e))


@app.route("/cases", methods=["GET"])
def list_cases():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.cases.values())
    naid = request.args.get("noticing_attorney_id")
    if naid is not None:
        items = [c for c in items if c["noticing_attorney_id"] == naid]
    window, total = paginate(items, limit, offset)
    return list_response([S.case_out(e) for e in window], limit, offset, total)


@app.route("/cases/<cid>/jobs", methods=["GET"])
def list_case_jobs(cid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    L.get_case(cid)
    limit, offset = pagination()
    items = [j for j in db.jobs.values() if j["case_id"] == cid]
    window, total = paginate(items, limit, offset)
    return list_response([S.job_out(e) for e in window], limit, offset, total)


# =============================================================================
# Attorneys (PRD §3.1)
# =============================================================================
@app.route("/attorneys", methods=["POST"])
def create_attorney():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "firm_name", "bar_state", "email"])
    full_name = require_str(body, "full_name")
    firm_name = require_str(body, "firm_name")
    bar_state = require_enum(body, "bar_state", BAR_STATES)
    email = require_str(body, "email")
    for a in db.attorneys.values():
        if a["email"] == email:
            raise err(E.ERR_DUPLICATE_KEY, "email already in use.")
    e = stamp_create({
        "id": new_id(),
        "full_name": full_name,
        "firm_name": firm_name,
        "bar_state": bar_state,
        "email": email,
    })
    db.attorneys[e["id"]] = e
    return success(S.attorney_out(e), status=201)


@app.route("/attorneys/<aid>", methods=["GET"])
def get_attorney_ep(aid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    e = L.get_attorney(aid)
    return success(S.attorney_out(e))


@app.route("/attorneys", methods=["GET"])
def list_attorneys():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.attorneys.values())
    email = request.args.get("email")
    if email is not None:
        items = [a for a in items if a["email"] == email]
    window, total = paginate(items, limit, offset)
    return list_response([S.attorney_out(e) for e in window], limit, offset, total)


# =============================================================================
# Resources (PRD §3.1)
# =============================================================================
@app.route("/resources", methods=["POST"])
def create_resource():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "kind", "hourly_appearance_cents"])
    full_name = require_str(body, "full_name")
    kind = require_enum(body, "kind", RESOURCE_KINDS)
    hourly = require_int(body, "hourly_appearance_cents")
    if hourly < 0:
        raise err(E.ERR_INVALID_REQUEST, "hourly_appearance_cents must be >= 0.")
    certifications = body.get("certifications")
    if certifications is None:
        certifications = []
    elif not isinstance(certifications, list) or not all(isinstance(x, str) for x in certifications):
        raise err(E.ERR_INVALID_REQUEST, "certifications must be an array of strings.")
    realtime_capable = opt_bool(body, "realtime_capable", False)
    e = stamp_create({
        "id": new_id(),
        "full_name": full_name,
        "kind": kind,
        "certifications": certifications,
        "realtime_capable": realtime_capable,
        "hourly_appearance_cents": hourly,
        "active": True,
    })
    db.resources[e["id"]] = e
    return success(S.resource_out(e), status=201)


@app.route("/resources/<rid>", methods=["GET"])
def get_resource_ep(rid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    e = L.get_resource(rid)
    return success(S.resource_out(e))


@app.route("/resources", methods=["GET"])
def list_resources():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.resources.values())
    kind = request.args.get("kind")
    if kind is not None:
        items = [r for r in items if r["kind"] == kind]
    window, total = paginate(items, limit, offset)
    return list_response([S.resource_out(e) for e in window], limit, offset, total)


@app.route("/resources/<rid>/deactivate", methods=["POST"])
def deactivate_resource(rid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    e = L.get_resource(rid)
    e["active"] = False
    touch(e)
    return success(S.resource_out(e))


@app.route("/resources/<rid>/assignments", methods=["GET"])
def list_resource_assignments(rid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    L.get_resource(rid)
    limit, offset = pagination()
    items = [a for a in db.assignments.values() if a["resource_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.assignment_out(e) for e in window], limit, offset, total)


# =============================================================================
# Jobs (PRD §3.2, §3.5)
# =============================================================================
@app.route("/jobs", methods=["POST"])
def create_job():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["case_id", "deponent_name", "scheduled_start", "scheduled_end"])
    case_id = require_str(body, "case_id")
    deponent = require_str(body, "deponent_name")
    scheduled_start = parse_datetime(body, "scheduled_start")
    scheduled_end = parse_datetime(body, "scheduled_end")
    requires_videographer = opt_bool(body, "requires_videographer", False)
    requires_interpreter = opt_bool(body, "requires_interpreter", False)
    requires_realtime = opt_bool(body, "requires_realtime", False)
    interpreter_language = opt_str(body, "interpreter_language", None)
    # Existence of FK (PRD §2.5).
    L.get_case(case_id)
    # Time window check (PRD §3.2): end strictly after start.
    if not (scheduled_end > scheduled_start):
        raise err(E.ERR_INVALID_TIME_WINDOW, "scheduled_end must be strictly after scheduled_start.")
    e = stamp_create({
        "id": new_id(),
        "case_id": case_id,
        "deponent_name": deponent,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "requires_videographer": requires_videographer,
        "requires_interpreter": requires_interpreter,
        "interpreter_language": interpreter_language,
        "requires_realtime": requires_realtime,
        "status": "NOTICED",
        "staffing_posture": "UNSTAFFED",
        "actual_start": None,
        "actual_end": None,
    })
    db.jobs[e["id"]] = e
    return success(S.job_out(e), status=201)


@app.route("/jobs/<jid>", methods=["GET"])
def get_job_ep(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    e = L.get_job(jid)
    return success(S.job_out(e))


@app.route("/jobs", methods=["GET"])
def list_jobs():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.jobs.values())
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [j for j in items if j["case_id"] == case_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.job_out(e) for e in window], limit, offset, total)


def _windows_overlap(s1, e1, s2, e2):
    """Half-open [s, e) overlap; touching endpoints do NOT overlap (PRD §3.3)."""
    return s1 < e2 and s2 < e1


@app.route("/jobs/<jid>/assignments", methods=["POST"])
def create_assignment(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    job = L.get_job(jid)
    body = get_body()
    require_fields(body, ["resource_id", "role", "expected_job_version"])
    resource_id = require_str(body, "resource_id")
    assign_role = require_enum(body, "role", RESOURCE_KINDS)
    expected_version = require_int(body, "expected_job_version")
    # Existence of FK resource (PRD §2.5) — checked at existence priority.
    resource = L.get_resource(resource_id)
    # OCC after existence (PRD §3.2: OCC compared after existence).
    if expected_version != job["version"]:
        raise err(E.ERR_STALE_VERSION, "expected_job_version does not match current Job.version.")
    # Business checks in pinned order (PRD §3.2).
    # 1. role == resource.kind
    if assign_role != resource["kind"]:
        raise err(E.ERR_ROLE_KIND_MISMATCH, "Assignment role must equal the resource's kind.")
    # 2. resource active
    if not resource["active"]:
        raise err(E.ERR_RESOURCE_INACTIVE, "Cannot assign an inactive resource.")
    # 3. at most one ACTIVE assignment per role per job
    for a in db.assignments.values():
        if a["job_id"] == jid and a["status"] == "ACTIVE" and a["role"] == assign_role:
            raise err(E.ERR_ROLE_ALREADY_FILLED, "Role already filled by an active assignment.")
    # 4. interpreter language match
    if assign_role == "INTERPRETER":
        lang = job["interpreter_language"]
        if lang is None or lang not in resource.get("certifications", []):
            raise err(E.ERR_INTERPRETER_LANGUAGE_MISMATCH,
                      "Interpreter certifications do not include the job's interpreter_language.")
    # 5. realtime reporter capability
    if assign_role == "REPORTER" and job["requires_realtime"]:
        if not resource["realtime_capable"]:
            raise err(E.ERR_REALTIME_NOT_CAPABLE, "Reporter is not realtime-capable.")
    # 6. overlap check (PRD §3.3) — evaluated before reporter buffer.
    new_s, new_e = job["scheduled_start"], job["scheduled_end"]
    for a in db.assignments.values():
        if a["resource_id"] != resource_id or a["status"] != "ACTIVE":
            continue
        other_job = db.jobs.get(a["job_id"])
        if other_job is None:
            continue
        if _windows_overlap(new_s, new_e, other_job["scheduled_start"], other_job["scheduled_end"]):
            raise err(E.ERR_RESOURCE_DOUBLE_BOOKED, "Resource already booked in an overlapping window.")
    # 7. reporter 30-min buffer (PRD §3.3) — only reporter assignments.
    if assign_role == "REPORTER":
        buffer = timedelta(minutes=30)
        for a in db.assignments.values():
            if a["resource_id"] != resource_id or a["status"] != "ACTIVE":
                continue
            other_job = db.jobs.get(a["job_id"])
            if other_job is None:
                continue
            o_s, o_e = other_job["scheduled_start"], other_job["scheduled_end"]
            # gap between one job's end and the next job's start < 30 min is a conflict
            if o_e <= new_s and (new_s - o_e) < buffer:
                raise err(E.ERR_REPORTER_BUFFER_CONFLICT, "Reporter travel buffer conflict.")
            if new_e <= o_s and (o_s - new_e) < buffer:
                raise err(E.ERR_REPORTER_BUFFER_CONFLICT, "Reporter travel buffer conflict.")
    # Create assignment.
    e = stamp_create({
        "id": new_id(),
        "job_id": jid,
        "resource_id": resource_id,
        "role": assign_role,
        "status": "ACTIVE",
        "appearance_fee_cents": 0,
    })
    db.assignments[e["id"]] = e
    # Recompute posture and bump job version (PRD §3.2 side effects, §2.4).
    recompute_posture(job)
    touch(job)
    return success(S.assignment_out(e), status=201)


@app.route("/jobs/<jid>/assignments", methods=["GET"])
def list_job_assignments(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "Attorney", "PlatformAdmin"})
    L.get_job(jid)
    limit, offset = pagination()
    items = [a for a in db.assignments.values() if a["job_id"] == jid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.assignment_out(e) for e in window], limit, offset, total)


def _check_job_occ(job, body):
    """confirm/start/adjourn/cancel carry expected_job_version per endpoint table,
    but PRD §2.6 says only assignment creation requires the OCC version field.
    We accept the field if present and do not require it."""
    return


@app.route("/jobs/<jid>/confirm", methods=["POST"])
def confirm_job(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    job = L.get_job(jid)
    get_body()
    # State (PRD §3.5): NOTICED -> CONFIRMED.
    if job["status"] != "NOTICED":
        raise err(E.ERR_INVALID_STATE, "Job is not in NOTICED state.")
    recompute_posture(job)
    if job["staffing_posture"] != "READY":
        raise err(E.ERR_INVALID_STATE, "Job staffing posture is not READY.")
    if not (job["scheduled_start"] > clock.now()):
        raise err(E.ERR_INVALID_STATE, "scheduled_start must be in the future.")
    job["status"] = "CONFIRMED"
    touch(job)
    return success(S.job_out(job))


@app.route("/jobs/<jid>/start", methods=["POST"])
def start_job(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    job = L.get_job(jid)
    get_body()
    if job["status"] != "CONFIRMED":
        raise err(E.ERR_INVALID_STATE, "Job is not in CONFIRMED state.")
    if not (clock.now() >= job["scheduled_start"]):
        raise err(E.ERR_INVALID_STATE, "Logical clock has not reached scheduled_start.")
    job["status"] = "IN_SESSION"
    job["actual_start"] = clock.now()
    touch(job)
    return success(S.job_out(job))


@app.route("/jobs/<jid>/adjourn", methods=["POST"])
def adjourn_job(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    job = L.get_job(jid)
    get_body()
    if job["status"] != "IN_SESSION":
        raise err(E.ERR_INVALID_STATE, "Job is not in IN_SESSION state.")
    job["status"] = "ADJOURNED"
    job["actual_end"] = clock.now()
    # Cascade hop 1+2: ACTIVE assignments -> COMPLETED, compute appearance_fee.
    for a in db.assignments.values():
        if a["job_id"] == jid and a["status"] == "ACTIVE":
            a["status"] = "COMPLETED"
            resource = db.resources.get(a["resource_id"])
            if resource is not None:
                a["appearance_fee_cents"] = calc.appearance_fee_actual(job, resource, a["role"])
            touch(a)
    # Cascade: STARTING/LIVE RealtimeStreams -> STOPPED.
    for st in db.realtime_streams.values():
        if st["job_id"] == jid and st["status"] in ("STARTING", "LIVE"):
            st["status"] = "STOPPED"
            st["stopped_at"] = clock.now()
            touch(st)
    touch(job)
    return success(S.job_out(job))


@app.route("/jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    job = L.get_job(jid)
    get_body()
    if job["status"] not in ("NOTICED", "CONFIRMED"):
        raise err(E.ERR_INVALID_STATE, "Job can only be cancelled from NOTICED or CONFIRMED.")
    job["status"] = "CANCELLED"
    # Cascade: ACTIVE assignments -> RELEASED.
    for a in db.assignments.values():
        if a["job_id"] == jid and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)
    recompute_posture(job)  # -> UNSTAFFED
    touch(job)
    return success(S.job_out(job))


@app.route("/jobs/<jid>/appearance-estimate", methods=["GET"])
def appearance_estimate(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    job = L.get_job(jid)
    lines = {}
    total = 0
    for a in db.assignments.values():
        if a["job_id"] != jid:
            continue
        if a["status"] != "ACTIVE":
            continue
        resource = db.resources.get(a["resource_id"])
        if resource is None:
            continue
        fee = calc.appearance_fee_estimate(job, resource, a["role"])
        lines[a["id"]] = fee
        total += fee
    return success({"estimated_total_cents": total, "lines": lines})


# =============================================================================
# Assignments (peer) (PRD §3.3)
# =============================================================================
@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment_ep(aid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    e = L.get_assignment(aid)
    return success(S.assignment_out(e))


@app.route("/assignments/<aid>/release", methods=["POST"])
def release_assignment(aid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    a = L.get_assignment(aid)
    get_body()
    job = db.jobs.get(a["job_id"])
    # State (PRD §3.3): ACTIVE & parent job NOTICED/CONFIRMED.
    if a["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Assignment is not ACTIVE.")
    if job is None or job["status"] not in ("NOTICED", "CONFIRMED"):
        raise err(E.ERR_INVALID_STATE, "Parent job is not in NOTICED or CONFIRMED state.")
    a["status"] = "RELEASED"
    touch(a)
    recompute_posture(job)
    touch(job)
    return success(S.assignment_out(a))


# =============================================================================
# Realtime Streams (PRD §3.7)
# =============================================================================
@app.route("/jobs/<jid>/realtime-streams", methods=["POST"])
def create_stream(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "Reporter", "PlatformAdmin"})
    job = L.get_job(jid)
    body = get_body()
    require_fields(body, ["reporter_assignment_id"])
    reporter_assignment_id = require_str(body, "reporter_assignment_id")
    assignment = L.get_assignment(reporter_assignment_id)
    # Provisioning rules (PRD §3.7): job IN_SESSION + requires_realtime; assignment
    # ACTIVE REPORTER whose resource realtime_capable.
    if job["status"] != "IN_SESSION" or not job["requires_realtime"]:
        raise err(E.ERR_REALTIME_NOT_PROVISIONABLE, "Job is not an in-session realtime job.")
    if assignment["job_id"] != jid:
        raise err(E.ERR_REALTIME_NOT_PROVISIONABLE, "Assignment does not belong to this job.")
    if assignment["status"] != "ACTIVE" or assignment["role"] != "REPORTER":
        raise err(E.ERR_REALTIME_NOT_PROVISIONABLE, "Assignment is not an active reporter assignment.")
    resource = db.resources.get(assignment["resource_id"])
    if resource is None or not resource["realtime_capable"]:
        raise err(E.ERR_REALTIME_NOT_PROVISIONABLE, "Reporter resource is not realtime-capable.")
    e = stamp_create({
        "id": new_id(),
        "job_id": jid,
        "reporter_assignment_id": reporter_assignment_id,
        "access_token": None,
        "status": "STARTING",
        "started_at": None,
        "stopped_at": None,
    })
    db.realtime_streams[e["id"]] = e
    return success(S.stream_out(e), status=201)


@app.route("/jobs/<jid>/realtime-streams", methods=["GET"])
def list_job_streams(jid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "Reporter", "BillingClerk", "Attorney", "PlatformAdmin"})
    L.get_job(jid)
    limit, offset = pagination()
    items = [s for s in db.realtime_streams.values() if s["job_id"] == jid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.stream_out(e) for e in window], limit, offset, total)


@app.route("/realtime-streams/<sid>", methods=["GET"])
def get_stream_ep(sid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "Reporter", "BillingClerk", "Attorney", "PlatformAdmin"})
    e = L.get_stream(sid)
    return success(S.stream_out(e))


@app.route("/realtime-streams", methods=["GET"])
def list_streams():
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "Reporter", "BillingClerk", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.realtime_streams.values())
    job_id = request.args.get("job_id")
    ra_id = request.args.get("reporter_assignment_id")
    status = request.args.get("status")
    if job_id is not None:
        items = [s for s in items if s["job_id"] == job_id]
    if ra_id is not None:
        items = [s for s in items if s["reporter_assignment_id"] == ra_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.stream_out(e) for e in window], limit, offset, total)


@app.route("/realtime-streams/<sid>/go-live", methods=["POST"])
def go_live(sid):
    _, role = authenticate()
    require_role(role, {"Reporter", "PlatformAdmin"})
    st = L.get_stream(sid)
    get_body()
    # State + preconditions (PRD §3.7).
    if st["status"] != "STARTING":
        raise err(E.ERR_INVALID_STATE, "Stream is not in STARTING state.")
    job = db.jobs.get(st["job_id"])
    if job is None or job["status"] != "IN_SESSION":
        raise err(E.ERR_INVALID_STATE, "Parent job is not IN_SESSION.")
    assignment = db.assignments.get(st["reporter_assignment_id"])
    if (assignment is None or assignment["status"] != "ACTIVE"
            or assignment["role"] != "REPORTER"):
        raise err(E.ERR_INVALID_STATE, "Reporter assignment is not active.")
    resource = db.resources.get(assignment["resource_id"]) if assignment else None
    if resource is None or not resource["realtime_capable"]:
        raise err(E.ERR_INVALID_STATE, "Reporter resource is not realtime-capable.")
    st["status"] = "LIVE"
    st["started_at"] = clock.now()
    st["access_token"] = "rts_" + secrets.token_urlsafe(24)
    touch(st)
    return success(S.stream_out(st))


@app.route("/realtime-streams/<sid>/stop", methods=["POST"])
def stop_stream(sid):
    _, role = authenticate()
    require_role(role, {"Reporter", "ScheduleCoordinator", "PlatformAdmin"})
    st = L.get_stream(sid)
    get_body()
    if st["status"] not in ("STARTING", "LIVE"):
        raise err(E.ERR_INVALID_STATE, "Stream is not LIVE or STARTING.")
    st["status"] = "STOPPED"
    st["stopped_at"] = clock.now()
    touch(st)
    return success(S.stream_out(st))


# =============================================================================
# Transcript Orders (PRD §3.8, §3.10)
# =============================================================================
@app.route("/transcript-orders", methods=["POST"])
def create_transcript():
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["job_id", "ordering_attorney_id", "turnaround_tier", "estimated_pages"])
    job_id = require_str(body, "job_id")
    ordering_attorney_id = require_str(body, "ordering_attorney_id")
    turnaround = require_enum(body, "turnaround_tier", TURNAROUND_TIERS)
    estimated_pages = require_int(body, "estimated_pages")
    certified_copy = opt_bool(body, "certified_copy", True)
    # Existence (PRD §2.5).
    job = L.get_job(job_id)
    L.get_attorney(ordering_attorney_id)
    # estimated_pages >= 0 (PRD §3.8).
    if estimated_pages < 0:
        raise err(E.ERR_INVALID_PAGE_COUNT, "estimated_pages must be >= 0.")
    # Job must be ADJOURNED (PRD §3.8).
    if job["status"] != "ADJOURNED":
        raise err(E.ERR_JOB_NOT_ADJOURNED, "Job must be ADJOURNED to order a transcript.")
    e = stamp_create({
        "id": new_id(),
        "job_id": job_id,
        "ordering_attorney_id": ordering_attorney_id,
        "turnaround_tier": turnaround,
        "certified_copy": certified_copy,
        "estimated_pages": estimated_pages,
        "final_pages": None,
        "status": "ORDERED",
        "read_sign_deadline": None,
        "errata_round": 0,
    })
    db.transcript_orders[e["id"]] = e
    return success(S.transcript_out(e), status=201)


@app.route("/transcript-orders/<tid>", methods=["GET"])
def get_transcript_ep(tid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "Reporter", "PlatformAdmin"})
    e = L.get_transcript(tid)
    return success(S.transcript_out(e))


@app.route("/transcript-orders", methods=["GET"])
def list_transcripts():
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.transcript_orders.values())
    job_id = request.args.get("job_id")
    oa_id = request.args.get("ordering_attorney_id")
    status = request.args.get("status")
    if job_id is not None:
        items = [t for t in items if t["job_id"] == job_id]
    if oa_id is not None:
        items = [t for t in items if t["ordering_attorney_id"] == oa_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.transcript_out(e) for e in window], limit, offset, total)


def _jurisdiction_for_transcript(transcript):
    job = db.jobs.get(transcript["job_id"])
    case = db.cases.get(job["case_id"]) if job else None
    return case["jurisdiction"] if case else None


@app.route("/transcript-orders/<tid>/quote", methods=["GET"])
def transcript_quote(tid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    t = L.get_transcript(tid)
    jurisdiction = _jurisdiction_for_transcript(t)
    provisional = calc.compute_page_charge(
        t["estimated_pages"], jurisdiction, t["turnaround_tier"], t["certified_copy"])
    exhibit = calc.compute_exhibit_charge(tid)
    return success({"provisional_page_cents": provisional, "exhibit_cents": exhibit})


def _acting_attorney_is_case_party(user_id, transcript):
    """Acting attorney must equal ordering_attorney_id OR the job's case
    noticing_attorney_id (PRD §2.1, §3.10)."""
    if user_id == transcript["ordering_attorney_id"]:
        return True
    job = db.jobs.get(transcript["job_id"])
    case = db.cases.get(job["case_id"]) if job else None
    if case and user_id == case["noticing_attorney_id"]:
        return True
    return False


def _reporter_covered_job(user_id, job_id):
    """Acting reporter holds a COMPLETED REPORTER assignment on the order's job."""
    for a in db.assignments.values():
        if (a["job_id"] == job_id and a["role"] == "REPORTER"
                and a["status"] == "COMPLETED" and a["resource_id"] == user_id):
            return True
    return False


@app.route("/transcript-orders/<tid>/deliver-rough", methods=["POST"])
def deliver_rough(tid):
    user_id, role = authenticate()
    require_role(role, {"Reporter", "PlatformAdmin"})
    t = L.get_transcript(tid)
    get_body()
    if t["status"] != "ORDERED":
        raise err(E.ERR_INVALID_STATE, "Transcript is not in ORDERED state.")
    # Reporter must have a COMPLETED reporter assignment on the order's job (PRD §3.8).
    if role == "Reporter" and not _reporter_covered_job(user_id, t["job_id"]):
        raise err(E.ERR_FORBIDDEN_ROLE, "Reporter did not cover this job.")
    t["status"] = "ROUGH_DELIVERED"
    touch(t)
    return success(S.transcript_out(t))


@app.route("/transcript-orders/<tid>/certify", methods=["POST"])
def certify(tid):
    user_id, role = authenticate()
    require_role(role, {"Reporter", "PlatformAdmin"})
    t = L.get_transcript(tid)
    body = get_body()
    require_fields(body, ["final_pages"])
    final_pages = require_int(body, "final_pages")
    if t["status"] != "ROUGH_DELIVERED":
        raise err(E.ERR_INVALID_STATE, "Transcript is not in ROUGH_DELIVERED state.")
    if role == "Reporter" and not _reporter_covered_job(user_id, t["job_id"]):
        raise err(E.ERR_FORBIDDEN_ROLE, "Reporter did not cover this job.")
    if not t["certified_copy"]:
        raise err(E.ERR_INVALID_STATE, "Order is not a certified copy.")
    if final_pages < 1:
        raise err(E.ERR_INVALID_PAGE_COUNT, "final_pages must be >= 1.")
    t["status"] = "CERTIFIED"
    t["final_pages"] = final_pages
    t["read_sign_deadline"] = clock.now() + timedelta(days=30)
    touch(t)
    return success(S.transcript_out(t))


@app.route("/transcript-orders/<tid>/open-read-sign", methods=["POST"])
def open_read_sign(tid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    t = L.get_transcript(tid)
    get_body()
    if t["status"] not in ("CERTIFIED", "ERRATA_FILED"):
        raise err(E.ERR_INVALID_STATE, "Transcript is not in CERTIFIED or ERRATA_FILED state.")
    t["status"] = "READ_SIGN_OPEN"
    touch(t)
    return success(S.transcript_out(t))


@app.route("/transcript-orders/<tid>/errata", methods=["POST"])
def file_errata(tid):
    user_id, role = authenticate()
    require_role(role, {"Attorney", "PlatformAdmin"})
    t = L.get_transcript(tid)
    body = get_body()
    require_fields(body, ["corrections", "reason"])
    corrections = body.get("corrections")
    reason = require_str(body, "reason")
    # Case-party check (PRD §3.10, validation priority 4 before state).
    if role == "Attorney" and not _acting_attorney_is_case_party(user_id, t):
        raise err(E.ERR_NOT_CASE_PARTY, "Acting attorney is not a case party.")
    # State.
    if t["status"] != "READ_SIGN_OPEN":
        raise err(E.ERR_INVALID_STATE, "Transcript is not in READ_SIGN_OPEN state.")
    # corrections non-empty (PRD §3.10).
    if not isinstance(corrections, list) or len(corrections) == 0:
        raise err(E.ERR_INVALID_PAGE_COUNT, "corrections must be a non-empty array.")
    # Window open (PRD §3.10): clock strictly before deadline.
    if not (clock.now() < t["read_sign_deadline"]):
        raise err(E.ERR_READ_SIGN_WINDOW_CLOSED, "Read-and-sign window is closed.")
    new_round = t["errata_round"] + 1
    e = stamp_create({
        "id": new_id(),
        "transcript_order_id": tid,
        "round": new_round,
        "corrections": corrections,
        "reason": reason,
    })
    db.errata[e["id"]] = e
    t["errata_round"] = new_round
    t["status"] = "ERRATA_FILED"
    touch(t)
    return success(S.errata_out(e), status=201)


@app.route("/transcript-orders/<tid>/sign", methods=["POST"])
def sign_transcript(tid):
    user_id, role = authenticate()
    require_role(role, {"Attorney", "PlatformAdmin"})
    t = L.get_transcript(tid)
    get_body()
    if role == "Attorney" and not _acting_attorney_is_case_party(user_id, t):
        raise err(E.ERR_NOT_CASE_PARTY, "Acting attorney is not a case party.")
    if t["status"] != "READ_SIGN_OPEN":
        raise err(E.ERR_INVALID_STATE, "Transcript is not in READ_SIGN_OPEN state.")
    t["status"] = "SIGNED"
    touch(t)
    return success(S.transcript_out(t))


@app.route("/transcript-orders/<tid>/finalize-deadline", methods=["POST"])
def finalize_deadline(tid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    t = L.get_transcript(tid)
    get_body()
    if t["status"] not in ("CERTIFIED", "READ_SIGN_OPEN", "ERRATA_FILED"):
        raise err(E.ERR_INVALID_STATE, "Transcript is not in a finalizable state.")
    if t["read_sign_deadline"] is None or not (clock.now() >= t["read_sign_deadline"]):
        raise err(E.ERR_INVALID_STATE, "Read-and-sign deadline has not lapsed.")
    t["status"] = "SIGNED"
    touch(t)
    return success(S.transcript_out(t))


@app.route("/transcript-orders/<tid>/deliver", methods=["POST"])
def deliver_transcript(tid):
    _, role = authenticate()
    require_role(role, {"ScheduleCoordinator", "PlatformAdmin"})
    t = L.get_transcript(tid)
    get_body()
    if t["status"] != "SIGNED":
        raise err(E.ERR_INVALID_STATE, "Transcript is not in SIGNED state.")
    t["status"] = "DELIVERED"
    touch(t)
    return success(S.transcript_out(t))


@app.route("/transcript-orders/<tid>/cancel", methods=["POST"])
def cancel_transcript(tid):
    user_id, role = authenticate()
    require_role(role, {"Attorney", "PlatformAdmin"})
    t = L.get_transcript(tid)
    get_body()
    # Case-party check (validation priority 4 before state).
    if role == "Attorney" and not _acting_attorney_is_case_party(user_id, t):
        raise err(E.ERR_NOT_CASE_PARTY, "Acting attorney is not a case party.")
    if t["status"] not in ("ORDERED", "ROUGH_DELIVERED"):
        raise err(E.ERR_INVALID_STATE, "Transcript can only be cancelled from ORDERED or ROUGH_DELIVERED.")
    t["status"] = "CANCELLED"
    touch(t)
    return success(S.transcript_out(t))


# =============================================================================
# Exhibits (PRD §3.9)
# =============================================================================
@app.route("/transcript-orders/<tid>/exhibits", methods=["POST"])
def create_exhibit(tid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "Reporter", "PlatformAdmin"})
    t = L.get_transcript(tid)
    body = get_body()
    require_fields(body, ["marked_label", "page_count"])
    marked_label = require_str(body, "marked_label")
    page_count = require_int(body, "page_count")
    confidential = opt_bool(body, "confidential", False)
    if page_count < 1:
        raise err(E.ERR_INVALID_REQUEST, "page_count must be >= 1.")
    # Unique marked_label within transcript (PRD §3.9).
    for ex in db.exhibits.values():
        if ex["transcript_order_id"] == tid and ex["marked_label"] == marked_label:
            raise err(E.ERR_DUPLICATE_EXHIBIT_LABEL, "marked_label already used in this transcript.")
    e = stamp_create({
        "id": new_id(),
        "transcript_order_id": tid,
        "marked_label": marked_label,
        "page_count": page_count,
        "confidential": confidential,
    })
    db.exhibits[e["id"]] = e
    return success(S.exhibit_out(e), status=201)


@app.route("/transcript-orders/<tid>/exhibits", methods=["GET"])
def list_exhibits(tid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "Reporter", "PlatformAdmin"})
    L.get_transcript(tid)
    limit, offset = pagination()
    items = [ex for ex in db.exhibits.values() if ex["transcript_order_id"] == tid]
    conf = request.args.get("confidential")
    if conf is not None:
        want = conf.lower() == "true"
        items = [ex for ex in items if ex["confidential"] == want]
    window, total = paginate(items, limit, offset)
    return list_response([S.exhibit_out(e) for e in window], limit, offset, total)


@app.route("/exhibits/<eid>", methods=["GET"])
def get_exhibit_ep(eid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "Reporter", "PlatformAdmin"})
    e = L.get_exhibit(eid)
    return success(S.exhibit_out(e))


# =============================================================================
# Errata (PRD §3.10)
# =============================================================================
@app.route("/transcript-orders/<tid>/errata", methods=["GET"])
def list_errata(tid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "Reporter", "PlatformAdmin"})
    L.get_transcript(tid)
    limit, offset = pagination()
    items = [e for e in db.errata.values() if e["transcript_order_id"] == tid]
    window, total = paginate(items, limit, offset)
    return list_response([S.errata_out(e) for e in window], limit, offset, total)


@app.route("/errata/<eid>", methods=["GET"])
def get_errata_ep(eid):
    _, role = authenticate()
    require_role(role, {"Attorney", "ScheduleCoordinator", "BillingClerk", "PlatformAdmin"})
    e = L.get_errata(eid)
    return success(S.errata_out(e))


# =============================================================================
# Invoices (PRD §3.14)
# =============================================================================
def _compute_invoice_subtotals(invoice):
    job_id = invoice["job_id"]
    transcript = db.transcript_orders.get(invoice["transcript_order_id"])
    appearance = calc.appearance_subtotal(job_id)
    page = 0
    exhibit = 0
    if transcript is not None:
        jurisdiction = _jurisdiction_for_transcript(transcript)
        pages = transcript["final_pages"] if transcript["final_pages"] is not None else 0
        page = calc.compute_page_charge(
            pages, jurisdiction, transcript["turnaround_tier"], transcript["certified_copy"])
        exhibit = calc.compute_exhibit_charge(transcript["id"])
    return appearance, page, exhibit, appearance + page + exhibit


@app.route("/invoices", methods=["POST"])
def create_invoice():
    _, role = authenticate()
    require_role(role, {"BillingClerk", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["job_id", "transcript_order_id"])
    job_id = require_str(body, "job_id")
    transcript_order_id = require_str(body, "transcript_order_id")
    bill_to = opt_str(body, "bill_to_attorney_id", None)
    job = L.get_job(job_id)
    transcript = L.get_transcript(transcript_order_id)
    if bill_to is not None:
        L.get_attorney(bill_to)
    else:
        bill_to = transcript["ordering_attorney_id"]
    e = stamp_create({
        "id": new_id(),
        "job_id": job_id,
        "transcript_order_id": transcript_order_id,
        "bill_to_attorney_id": bill_to,
        "appearance_subtotal_cents": 0,
        "page_subtotal_cents": 0,
        "exhibit_subtotal_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
    })
    # Preview subtotals from current state (PRD §3.14).
    appearance, page, exhibit, total = _compute_invoice_subtotals(e)
    e["appearance_subtotal_cents"] = appearance
    e["page_subtotal_cents"] = page
    e["exhibit_subtotal_cents"] = exhibit
    e["total_cents"] = total
    db.invoices[e["id"]] = e
    return success(S.invoice_out(e), status=201)


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice_ep(iid):
    _, role = authenticate()
    require_role(role, {"BillingClerk", "Attorney", "PlatformAdmin"})
    e = L.get_invoice(iid)
    return success(S.invoice_out(e))


@app.route("/invoices", methods=["GET"])
def list_invoices():
    _, role = authenticate()
    require_role(role, {"BillingClerk", "Attorney", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(db.invoices.values())
    job_id = request.args.get("job_id")
    to_id = request.args.get("transcript_order_id")
    bill_to = request.args.get("bill_to_attorney_id")
    status = request.args.get("status")
    if job_id is not None:
        items = [i for i in items if i["job_id"] == job_id]
    if to_id is not None:
        items = [i for i in items if i["transcript_order_id"] == to_id]
    if bill_to is not None:
        items = [i for i in items if i["bill_to_attorney_id"] == bill_to]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_response([S.invoice_out(e) for e in window], limit, offset, total)


@app.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    _, role = authenticate()
    require_role(role, {"BillingClerk", "PlatformAdmin"})
    inv = L.get_invoice(iid)
    get_body()
    if inv["status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Invoice is not in DRAFT state.")
    transcript = db.transcript_orders.get(inv["transcript_order_id"])
    # Recompute & freeze subtotals from current state (PRD §3.14).
    appearance, page, exhibit, total = _compute_invoice_subtotals(inv)
    # Issue requires transcript DELIVERED and total > 0 (PRD §3.14).
    if transcript is None or transcript["status"] != "DELIVERED" or total <= 0:
        raise err(E.ERR_INVOICE_NOT_READY, "Transcript not delivered or total is zero.")
    inv["appearance_subtotal_cents"] = appearance
    inv["page_subtotal_cents"] = page
    inv["exhibit_subtotal_cents"] = exhibit
    inv["total_cents"] = total
    inv["status"] = "ISSUED"
    touch(inv)
    return success(S.invoice_out(inv))


@app.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    _, role = authenticate()
    require_role(role, {"BillingClerk", "PlatformAdmin"})
    inv = L.get_invoice(iid)
    get_body()
    if inv["status"] != "ISSUED":
        raise err(E.ERR_INVALID_STATE, "Invoice is not in ISSUED state.")
    inv["status"] = "PAID"
    touch(inv)
    return success(S.invoice_out(inv))


@app.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    _, role = authenticate()
    require_role(role, {"BillingClerk", "PlatformAdmin"})
    inv = L.get_invoice(iid)
    get_body()
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise err(E.ERR_INVALID_STATE, "Invoice can only be voided from DRAFT or ISSUED.")
    inv["status"] = "VOID"
    touch(inv)
    return success(S.invoice_out(inv))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
