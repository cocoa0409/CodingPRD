"""Site Utility & Excavation Contracting API — Flask entry point."""
import os
from datetime import timedelta

from flask import Flask, request

import store
from core import (
    ALL_ROLES, advance_clock, apply_stop_work, audit, current_actor,
    get_or_404, groundwater_readiness_recompute, recompute_segment_compaction,
    recompute_work_posture, reinstate_permit_cascade, require_roles,
    stamp_new, suspend_permit_cascade, touch,
)
from helpers import (
    ApiError, CLOCK, ceil_div_to_int, err, error_response, format_iso,
    get_json_body, iso_now, optional, optional_enum, parse_iso,
    parse_pagination, require, require_enum, require_nonnegative_int,
    require_nonnegative_number, require_positive_int, require_positive_number,
    round_half_up, success_list, success_object,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed for this path")


@app.errorhandler(Exception)
def handle_generic(e):
    import traceback
    traceback.print_exc()
    return error_response("ERR_VALIDATION", 400, f"Unexpected: {e}")


# ---------------------------------------------------------------------------
# Filter + paginate helper
# ---------------------------------------------------------------------------
def list_response(collection, filters=None, sort_key=None):
    items = list(collection.values())
    if filters:
        for fname, fval in filters.items():
            if fval is None:
                continue
            items = [i for i in items if str(i.get(fname)) == str(fval)]
    if sort_key is None:
        # Stable sort by created_at: equal timestamps keep insertion
        # (creation) order, so the listing stays chronological.
        items.sort(key=lambda x: x.get("created_at", ""))
    else:
        items.sort(key=sort_key)
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)


# ===========================================================================
# Projects
# ===========================================================================
@app.post("/site-utility/projects")
def create_project():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    name = require(body, "name", "string")
    contract_ref = require(body, "contract_ref", "string")
    soil_class_default = require_enum(body, "soil_class_default", {"SOIL_A", "SOIL_B", "SOIL_C"})
    contingency_cents = require_nonnegative_int(body, "contingency_cents")
    single_co_cap_cents = require_nonnegative_int(body, "single_co_cap_cents")

    proj = stamp_new({
        "name": name,
        "contract_ref": contract_ref,
        "soil_class_default": soil_class_default,
        "contingency_cents": contingency_cents,
        "single_co_cap_cents": single_co_cap_cents,
        "status": "ACTIVE",
        "work_posture": "CLEAR",
        "approved_co_total_cents": 0,
        "closed_at": None,
    })
    store.projects[proj["id"]] = proj
    audit(proj["id"], actor, "POST /site-utility/projects", "Project", proj["id"], "project created (ACTIVE)")
    return success_object(proj, 201)


@app.get("/site-utility/projects")
def list_projects():
    current_actor()
    return list_response(
        store.projects,
        filters={
            "status": request.args.get("status"),
            "work_posture": request.args.get("work_posture"),
        },
    )


@app.get("/site-utility/projects/<pid>")
def get_project(pid):
    current_actor()
    proj = get_or_404(store.projects, pid, "Project")
    return success_object(proj)


@app.post("/site-utility/projects/<pid>/begin-closeout")
def begin_closeout(pid):
    actor = require_roles("ProjectManager")
    proj = get_or_404(store.projects, pid, "Project")
    if proj["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, f"Project status must be ACTIVE, is {proj['status']}")
    segments = [s for s in store.pipe_segments.values() if s["project_id"] == pid]
    for s in segments:
        if s["status"] != "COMPLETE":
            err("ERR_CLOSEOUT_INCOMPLETE", 409, f"Segment {s['id']} not COMPLETE")
        ab = next(
            (a for a in store.as_built_packages.values()
             if a["pipe_segment_id"] == s["id"] and a["status"] == "ACCEPTED"),
            None,
        )
        if not ab:
            err("ERR_CLOSEOUT_INCOMPLETE", 409, f"Segment {s['id']} missing ACCEPTED as-built")
    for c in store.unforeseen_conditions.values():
        if c["project_id"] == pid and c["status"] in ("OPEN", "MITIGATING"):
            err("ERR_CLOSEOUT_INCOMPLETE", 409, "Open or mitigating condition exists")
    for co in store.change_orders.values():
        if co["project_id"] == pid and co["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            err("ERR_CLOSEOUT_INCOMPLETE", 409, "Open change order exists")
    if proj.get("work_posture") != "CLEAR":
        err("ERR_CLOSEOUT_INCOMPLETE", 409, "Work posture not CLEAR")

    proj["status"] = "CLOSING"
    touch(proj)
    audit(pid, actor, "POST /site-utility/projects/{id}/begin-closeout", "Project", pid, "status ACTIVE->CLOSING")
    return success_object(proj)


@app.post("/site-utility/projects/<pid>/close")
def close_project(pid):
    actor = require_roles("ProjectManager")
    proj = get_or_404(store.projects, pid, "Project")
    if proj["status"] != "CLOSING":
        err("ERR_INVALID_STATE", 409, f"Project status must be CLOSING, is {proj['status']}")
    proj["status"] = "CLOSED"
    proj["closed_at"] = iso_now()
    touch(proj)
    audit(pid, actor, "POST /site-utility/projects/{id}/close", "Project", pid, "status CLOSING->CLOSED")
    return success_object(proj)


@app.get("/site-utility/projects/<pid>/audit-events")
def list_audit_events(pid):
    current_actor()
    get_or_404(store.projects, pid, "Project")
    items = [e for e in store.audit_events.values() if e["project_id"] == pid]
    et = request.args.get("entity_type")
    if et:
        items = [e for e in items if e["entity_type"] == et]
    # Stable sort by created_at keeps append order among equal timestamps,
    # so the trail stays chronological (PRD §2.4/§3.1).
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    limit, offset = parse_pagination()
    return success_list(items[offset:offset + limit], limit, offset, total)


# ===========================================================================
# Utility Owners
# ===========================================================================
@app.post("/site-utility/utility-owners")
def create_owner():
    actor = require_roles("OpsAdmin")
    body = get_json_body()
    name = require(body, "name", "string")
    owner_type = require_enum(body, "owner_type", {"WATER", "SEWER", "GAS", "ELECTRIC", "TELECOM"})
    min_notice_hours = require_nonnegative_int(body, "min_notice_hours")
    max_shutdown_hours = require_positive_int(body, "max_shutdown_hours")

    owner = stamp_new({
        "name": name,
        "owner_type": owner_type,
        "min_notice_hours": min_notice_hours,
        "max_shutdown_hours": max_shutdown_hours,
        "committed_shutdown_minutes": 0,
    })
    store.utility_owners[owner["id"]] = owner
    return success_object(owner, 201)


@app.get("/site-utility/utility-owners")
def list_owners():
    current_actor()
    return list_response(store.utility_owners)


@app.get("/site-utility/utility-owners/<oid>")
def get_owner(oid):
    current_actor()
    return success_object(get_or_404(store.utility_owners, oid, "UtilityOwner"))


# ===========================================================================
# Locate Tickets
# ===========================================================================
OPEN_TICKET_STATES = ("DRAFT", "SUBMITTED", "ACTIVE")


@app.post("/site-utility/locate-tickets")
def create_locate_ticket():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    ticket_number = require(body, "ticket_number", "string")
    legal_start_raw = require(body, "legal_start_at", "string")
    try:
        legal_start = parse_iso(legal_start_raw)
    except Exception:
        err("ERR_VALIDATION", 400, "legal_start_at must be ISO 8601")

    proj = store.projects.get(project_id)
    if not proj:
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")

    for t in store.locate_tickets.values():
        if t["project_id"] == project_id and t["status"] in OPEN_TICKET_STATES:
            err("ERR_DUPLICATE_OPEN_TICKET", 409, "Project already has an open locate ticket")

    valid_until = legal_start + timedelta(hours=672)
    ticket = stamp_new({
        "project_id": project_id,
        "ticket_number": ticket_number,
        "legal_start_at": format_iso(legal_start),
        "valid_until": format_iso(valid_until),
        "status": "DRAFT",
        "renew_count": 0,
    })
    store.locate_tickets[ticket["id"]] = ticket
    audit(project_id, actor, "POST /site-utility/locate-tickets", "LocateTicket", ticket["id"], "locate ticket created (DRAFT)")
    return success_object(ticket, 201)


@app.get("/site-utility/locate-tickets")
def list_locate_tickets():
    current_actor()
    return list_response(
        store.locate_tickets,
        filters={
            "project_id": request.args.get("project_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/locate-tickets/<tid>")
def get_locate_ticket(tid):
    current_actor()
    return success_object(get_or_404(store.locate_tickets, tid, "LocateTicket"))


@app.post("/site-utility/locate-tickets/<tid>/submit")
def submit_locate_ticket(tid):
    actor = require_roles("ProjectManager")
    ticket = get_or_404(store.locate_tickets, tid, "LocateTicket")
    if ticket["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, f"Ticket status must be DRAFT, is {ticket['status']}")
    for t in store.locate_tickets.values():
        if t["id"] != tid and t["project_id"] == ticket["project_id"] and t["status"] in OPEN_TICKET_STATES:
            err("ERR_DUPLICATE_OPEN_TICKET", 409, "Project already has another open ticket")
    ticket["status"] = "SUBMITTED"
    touch(ticket)
    audit(ticket["project_id"], actor, "POST /site-utility/locate-tickets/{id}/submit", "LocateTicket", tid, "status DRAFT->SUBMITTED")
    return success_object(ticket)


@app.post("/site-utility/locate-tickets/<tid>/renew")
def renew_locate_ticket(tid):
    actor = require_roles("ProjectManager")
    ticket = get_or_404(store.locate_tickets, tid, "LocateTicket")
    if ticket["status"] not in ("ACTIVE", "EXPIRED"):
        err("ERR_INVALID_STATE", 409, f"Ticket status must be ACTIVE or EXPIRED, is {ticket['status']}")
    old_valid = parse_iso(ticket["valid_until"])
    new_valid = old_valid + timedelta(hours=672)
    ticket["valid_until"] = format_iso(new_valid)
    ticket["renew_count"] = ticket.get("renew_count", 0) + 1
    now = CLOCK.now()
    if now < new_valid:
        ticket["status"] = "ACTIVE"
    else:
        ticket["status"] = "EXPIRED"
    touch(ticket)
    audit(ticket["project_id"], actor, "POST /site-utility/locate-tickets/{id}/renew", "LocateTicket", tid, f"renewed (renew_count={ticket['renew_count']})")
    return success_object(ticket)


# ===========================================================================
# Pothole Verifications
# ===========================================================================
UTILITY_TYPES = {"WATER", "SEWER", "GAS", "ELECTRIC", "TELECOM"}
POTHOLE_METHODS = {"VACUUM", "HAND_DIG"}
LIVE_POTHOLE_STATES = ("PLANNED", "PERFORMED", "VERIFIED")


@app.post("/site-utility/pothole-verifications")
def create_pothole():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    locate_ticket_id = require(body, "locate_ticket_id", "string")
    station_label = require(body, "station_label", "string")
    expected_utility_type = require_enum(body, "expected_utility_type", UTILITY_TYPES | {"UNKNOWN"})
    method = require_enum(body, "method", POTHOLE_METHODS)
    design_depth_in = require_positive_int(body, "design_depth_in")
    design_offset_in = require_nonnegative_int(body, "design_offset_in")

    proj = store.projects.get(project_id)
    if not proj:
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")
    ticket = store.locate_tickets.get(locate_ticket_id)
    if not ticket:
        err("ERR_NOT_FOUND", 404, f"LocateTicket not found: {locate_ticket_id}")
    if ticket["project_id"] != project_id:
        err("ERR_CROSS_PROJECT_REFERENCE", 422, "Locate ticket belongs to another project")

    # Duplicate-station rule; CONFLICT potholes get superseded
    conflict_same_station = None
    for p in store.pothole_verifications.values():
        if p["project_id"] != project_id or p["station_label"] != station_label:
            continue
        if p["status"] in LIVE_POTHOLE_STATES:
            err("ERR_DUPLICATE_STATION", 409, f"Station {station_label} already has a live pothole verification")
        if p["status"] == "CONFLICT":
            conflict_same_station = p

    if conflict_same_station:
        conflict_same_station["status"] = "SUPERSEDED"
        touch(conflict_same_station)
        audit(project_id, actor, "POST /site-utility/pothole-verifications",
              "PotholeVerification", conflict_same_station["id"],
              "status CONFLICT->SUPERSEDED (new plan)")

    pv = stamp_new({
        "project_id": project_id,
        "locate_ticket_id": locate_ticket_id,
        "station_label": station_label,
        "expected_utility_type": expected_utility_type,
        "method": method,
        "design_depth_in": design_depth_in,
        "design_offset_in": design_offset_in,
        "measured_depth_in": None,
        "measured_offset_in": None,
        "status": "PLANNED",
    })
    store.pothole_verifications[pv["id"]] = pv
    audit(project_id, actor, "POST /site-utility/pothole-verifications", "PotholeVerification", pv["id"], "pothole verification planned")
    return success_object(pv, 201)


@app.get("/site-utility/pothole-verifications")
def list_potholes():
    current_actor()
    return list_response(
        store.pothole_verifications,
        filters={
            "project_id": request.args.get("project_id"),
            "locate_ticket_id": request.args.get("locate_ticket_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/pothole-verifications/<pid>")
def get_pothole(pid):
    current_actor()
    return success_object(get_or_404(store.pothole_verifications, pid, "PotholeVerification"))


@app.post("/site-utility/pothole-verifications/<pid>/perform")
def perform_pothole(pid):
    actor = require_roles("Foreman")
    body = get_json_body()
    measured_depth_in = require_nonnegative_int(body, "measured_depth_in")
    measured_offset_in = require_nonnegative_int(body, "measured_offset_in")

    pv = get_or_404(store.pothole_verifications, pid, "PotholeVerification")
    if pv["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, f"Pothole status must be PLANNED, is {pv['status']}")
    ticket = store.locate_tickets.get(pv["locate_ticket_id"])
    if not ticket or ticket["status"] != "ACTIVE":
        err("ERR_LOCATE_NOT_ACTIVE", 409, "Locate ticket is not ACTIVE")
    proj = store.projects.get(pv["project_id"])
    if proj and proj.get("work_posture") != "CLEAR":
        err("ERR_PROJECT_STOPPED", 409, "Project posture is STOPPED")
    pv["measured_depth_in"] = measured_depth_in
    pv["measured_offset_in"] = measured_offset_in
    pv["status"] = "PERFORMED"
    touch(pv)
    audit(pv["project_id"], actor, "POST /site-utility/pothole-verifications/{id}/perform",
          "PotholeVerification", pid, "status PLANNED->PERFORMED")
    return success_object(pv)


@app.post("/site-utility/pothole-verifications/<pid>/verify")
def verify_pothole(pid):
    actor = require_roles("ProjectManager")
    pv = get_or_404(store.pothole_verifications, pid, "PotholeVerification")
    if pv["status"] != "PERFORMED":
        err("ERR_INVALID_STATE", 409, f"Pothole status must be PERFORMED, is {pv['status']}")
    dd = abs(pv["measured_depth_in"] - pv["design_depth_in"])
    do = abs(pv["measured_offset_in"] - pv["design_offset_in"])
    if dd > 6 or do > 12:
        err("ERR_POTHOLE_TOLERANCE_EXCEEDED", 422,
            f"|depth delta|={dd}in or |offset delta|={do}in exceeds tolerance")
    pv["status"] = "VERIFIED"
    touch(pv)
    audit(pv["project_id"], actor, "POST /site-utility/pothole-verifications/{id}/verify",
          "PotholeVerification", pid, "status PERFORMED->VERIFIED")
    return success_object(pv)


@app.post("/site-utility/pothole-verifications/<pid>/mark-conflict")
def mark_conflict_pothole(pid):
    actor = require_roles("ProjectManager")
    pv = get_or_404(store.pothole_verifications, pid, "PotholeVerification")
    if pv["status"] != "PERFORMED":
        err("ERR_INVALID_STATE", 409, f"Pothole status must be PERFORMED, is {pv['status']}")
    pv["status"] = "CONFLICT"
    touch(pv)
    audit(pv["project_id"], actor, "POST /site-utility/pothole-verifications/{id}/mark-conflict",
          "PotholeVerification", pid, "status PERFORMED->CONFLICT")
    return success_object(pv)


# ===========================================================================
# Pipe Segments
# ===========================================================================
PIPE_MATERIALS = {"PVC_C900", "DUCTILE_IRON", "HDPE", "RCP"}
BEDDING_CLASSES = {"CLASS_B", "CLASS_C", "CLASS_D"}
BEDDING_DEPTH_FT = {"CLASS_B": 0.5, "CLASS_C": 0.5, "CLASS_D": 0.25}


@app.post("/site-utility/pipe-segments")
def create_pipe_segment():
    actor = require_roles("Foreman")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    utility_owner_id = require(body, "utility_owner_id", "string")
    segment_label = require(body, "segment_label", "string")
    pipe_material = require_enum(body, "pipe_material", PIPE_MATERIALS)
    diameter_in = require_positive_int(body, "diameter_in")
    length_ft = require_positive_number(body, "length_ft")
    bedding_class = require_enum(body, "bedding_class", BEDDING_CLASSES)
    design_invert_depth_ft = require_positive_number(body, "design_invert_depth_ft")
    design_slope_pct = require_nonnegative_number(body, "design_slope_pct")
    requires_dewatering = optional(body, "requires_dewatering", False, "bool")

    if not store.projects.get(project_id):
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")
    if not store.utility_owners.get(utility_owner_id):
        err("ERR_NOT_FOUND", 404, f"UtilityOwner not found: {utility_owner_id}")

    bedding_ft = BEDDING_DEPTH_FT[bedding_class]
    trench_depth_ft = design_invert_depth_ft + (diameter_in / 12.0) + bedding_ft
    lifts_required = ceil_div_to_int(trench_depth_ft / 1.0)

    seg = stamp_new({
        "project_id": project_id,
        "utility_owner_id": utility_owner_id,
        "segment_label": segment_label,
        "pipe_material": pipe_material,
        "diameter_in": diameter_in,
        "length_ft": length_ft,
        "bedding_class": bedding_class,
        "design_invert_depth_ft": design_invert_depth_ft,
        "design_slope_pct": design_slope_pct,
        "requires_dewatering": requires_dewatering,
        "lifts_required": lifts_required,
        "lifts_satisfied": 0,
        "avg_compaction_pct": None,
        "min_compaction_pct": None,
        "hold_reason": "NONE",
        "resume_status": None,
        "tie_in_completed": False,
        "status": "PLANNED",
    })
    store.pipe_segments[seg["id"]] = seg
    audit(project_id, actor, "POST /site-utility/pipe-segments", "PipeSegment", seg["id"], "segment created (PLANNED)")
    return success_object(seg, 201)


@app.get("/site-utility/pipe-segments")
def list_pipe_segments():
    current_actor()
    return list_response(
        store.pipe_segments,
        filters={
            "project_id": request.args.get("project_id"),
            "utility_owner_id": request.args.get("utility_owner_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/pipe-segments/<sid>")
def get_pipe_segment(sid):
    current_actor()
    return success_object(get_or_404(store.pipe_segments, sid, "PipeSegment"))


def _require_active_locate(project_id):
    for t in store.locate_tickets.values():
        if t["project_id"] == project_id and t["status"] == "ACTIVE":
            return
    err("ERR_LOCATE_NOT_ACTIVE", 409, "Project has no ACTIVE locate ticket")


def _require_clear_posture(project):
    if project and project.get("work_posture") != "CLEAR":
        err("ERR_PROJECT_STOPPED", 409, "Project posture is STOPPED")


@app.post("/site-utility/pipe-segments/<sid>/mark-ready")
def mark_ready(sid):
    actor = require_roles("Foreman")
    seg = get_or_404(store.pipe_segments, sid, "PipeSegment")
    if seg["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, f"Segment status must be PLANNED, is {seg['status']}")
    project = store.projects.get(seg["project_id"])
    _require_clear_posture(project)
    _require_active_locate(seg["project_id"])
    plan_ok = any(
        p for p in store.trench_safety_plans.values()
        if p["pipe_segment_id"] == sid and p["status"] == "APPROVED"
    )
    if not plan_ok:
        err("ERR_PLAN_NOT_APPROVED", 409, "No APPROVED trench safety plan for segment")
    for pv in store.pothole_verifications.values():
        if pv["project_id"] == seg["project_id"] and pv["status"] in ("PLANNED", "PERFORMED", "CONFLICT"):
            err("ERR_POTHOLES_OUTSTANDING", 409, "Outstanding pothole verifications exist")
    seg["status"] = "READY"
    touch(seg)
    audit(seg["project_id"], actor, "POST /site-utility/pipe-segments/{id}/mark-ready",
          "PipeSegment", sid, "status PLANNED->READY")
    return success_object(seg)


@app.post("/site-utility/pipe-segments/<sid>/start-install")
def start_install(sid):
    actor = require_roles("Foreman")
    seg = get_or_404(store.pipe_segments, sid, "PipeSegment")
    if seg["status"] != "READY":
        err("ERR_INVALID_STATE", 409, f"Segment status must be READY, is {seg['status']}")
    project = store.projects.get(seg["project_id"])
    _require_clear_posture(project)
    _require_active_locate(seg["project_id"])
    seg["status"] = "INSTALLING"
    touch(seg)
    audit(seg["project_id"], actor, "POST /site-utility/pipe-segments/{id}/start-install",
          "PipeSegment", sid, "status READY->INSTALLING")
    return success_object(seg)


@app.post("/site-utility/pipe-segments/<sid>/complete-install")
def complete_install(sid):
    actor = require_roles("Foreman")
    seg = get_or_404(store.pipe_segments, sid, "PipeSegment")
    if seg["status"] != "INSTALLING":
        err("ERR_INVALID_STATE", 409, f"Segment status must be INSTALLING, is {seg['status']}")
    seg["status"] = "INSTALLED"
    touch(seg)
    audit(seg["project_id"], actor, "POST /site-utility/pipe-segments/{id}/complete-install",
          "PipeSegment", sid, "status INSTALLING->INSTALLED")
    return success_object(seg)


def _latest_confirmed_inspection(sid):
    confirmed = [
        i for i in store.installation_inspections.values()
        if i["pipe_segment_id"] == sid and i["status"] == "CONFIRMED"
    ]
    if not confirmed:
        return None
    # "Most recently created" (PRD §3.4): stable sort keeps insertion order
    # among equal timestamps, so [-1] is the last-created of the newest.
    confirmed.sort(key=lambda x: x["created_at"])
    return confirmed[-1]


@app.post("/site-utility/pipe-segments/<sid>/reopen-install")
def reopen_install(sid):
    actor = require_roles("Foreman")
    seg = get_or_404(store.pipe_segments, sid, "PipeSegment")
    if seg["status"] != "INSTALLED":
        err("ERR_INVALID_STATE", 409, f"Segment status must be INSTALLED, is {seg['status']}")
    latest = _latest_confirmed_inspection(sid)
    if not latest or latest["result"] != "FAIL":
        err("ERR_INVALID_STATE", 409, "Latest CONFIRMED inspection is not FAIL")
    seg["status"] = "INSTALLING"
    touch(seg)
    audit(seg["project_id"], actor, "POST /site-utility/pipe-segments/{id}/reopen-install",
          "PipeSegment", sid, "status INSTALLED->INSTALLING")
    return success_object(seg)


@app.post("/site-utility/pipe-segments/<sid>/start-backfill")
def start_backfill(sid):
    actor = require_roles("Foreman")
    seg = get_or_404(store.pipe_segments, sid, "PipeSegment")
    if seg["status"] != "INSTALLED":
        err("ERR_INVALID_STATE", 409, f"Segment status must be INSTALLED, is {seg['status']}")
    project = store.projects.get(seg["project_id"])
    _require_clear_posture(project)
    _require_active_locate(seg["project_id"])
    latest = _latest_confirmed_inspection(sid)
    if not latest or latest["result"] != "PASS":
        err("ERR_INSPECTION_NOT_PASSED", 409, "Latest CONFIRMED inspection is not PASS")
    seg["status"] = "BACKFILLING"
    touch(seg)
    audit(seg["project_id"], actor, "POST /site-utility/pipe-segments/{id}/start-backfill",
          "PipeSegment", sid, "status INSTALLED->BACKFILLING")
    return success_object(seg)


@app.post("/site-utility/pipe-segments/<sid>/complete")
def complete_segment(sid):
    actor = require_roles("Foreman")
    seg = get_or_404(store.pipe_segments, sid, "PipeSegment")
    if seg["status"] != "BACKFILLING":
        err("ERR_INVALID_STATE", 409, f"Segment status must be BACKFILLING, is {seg['status']}")
    if seg.get("lifts_satisfied", 0) != seg.get("lifts_required", 0):
        err("ERR_LIFTS_INCOMPLETE", 409,
            f"lifts_satisfied ({seg.get('lifts_satisfied', 0)}) < lifts_required ({seg.get('lifts_required', 0)})")
    seg["status"] = "COMPLETE"
    touch(seg)
    audit(seg["project_id"], actor, "POST /site-utility/pipe-segments/{id}/complete",
          "PipeSegment", sid, "status BACKFILLING->COMPLETE")
    return success_object(seg)


# ===========================================================================
# Trench Safety Plans
# ===========================================================================
PROTECTIVE_SYSTEMS = {"SLOPING", "BENCHING", "SHORING", "TRENCH_BOX"}
SOIL_CLASSES = {"SOIL_A", "SOIL_B", "SOIL_C"}
SLOPE_RATIO_REQUIRED = {"SOIL_A": 0.75, "SOIL_B": 1.0, "SOIL_C": 1.5}


@app.post("/site-utility/trench-safety-plans")
def create_trench_plan():
    actor = require_roles("Foreman")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    pipe_segment_id = require(body, "pipe_segment_id", "string")
    max_depth_ft = require_positive_number(body, "max_depth_ft")
    soil_class = require_enum(body, "soil_class", SOIL_CLASSES)
    protective_system = require_enum(body, "protective_system", PROTECTIVE_SYSTEMS)
    slope_ratio = optional(body, "slope_ratio", None, "number")
    engineered_certification = optional(body, "engineered_certification", False, "bool")

    if not store.projects.get(project_id):
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")
    seg = store.pipe_segments.get(pipe_segment_id)
    if not seg:
        err("ERR_NOT_FOUND", 404, f"PipeSegment not found: {pipe_segment_id}")
    if seg["project_id"] != project_id:
        err("ERR_CROSS_PROJECT_REFERENCE", 422, "Pipe segment belongs to another project")

    plan = stamp_new({
        "project_id": project_id,
        "pipe_segment_id": pipe_segment_id,
        "max_depth_ft": max_depth_ft,
        "soil_class": soil_class,
        "protective_system": protective_system,
        "slope_ratio": slope_ratio,
        "engineered_certification": engineered_certification,
        "revision": 1,
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    })
    store.trench_safety_plans[plan["id"]] = plan
    audit(project_id, actor, "POST /site-utility/trench-safety-plans", "TrenchSafetyPlan", plan["id"], "plan drafted")
    return success_object(plan, 201)


@app.get("/site-utility/trench-safety-plans")
def list_trench_plans():
    current_actor()
    return list_response(
        store.trench_safety_plans,
        filters={
            "project_id": request.args.get("project_id"),
            "pipe_segment_id": request.args.get("pipe_segment_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/trench-safety-plans/<pid>")
def get_trench_plan(pid):
    current_actor()
    return success_object(get_or_404(store.trench_safety_plans, pid, "TrenchSafetyPlan"))


@app.post("/site-utility/trench-safety-plans/<pid>/submit")
def submit_trench_plan(pid):
    actor = require_roles("Foreman")
    plan = get_or_404(store.trench_safety_plans, pid, "TrenchSafetyPlan")
    if plan["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, f"Plan status must be DRAFT, is {plan['status']}")
    # slope compliance
    if plan["protective_system"] in ("SLOPING", "BENCHING"):
        sr = plan.get("slope_ratio")
        required = SLOPE_RATIO_REQUIRED[plan["soil_class"]]
        if sr is None or sr < required:
            err("ERR_SLOPE_NONCOMPLIANT", 422,
                f"slope_ratio must be >= {required} for {plan['soil_class']}")
    if plan["max_depth_ft"] >= 20:
        if plan["protective_system"] not in ("SHORING", "TRENCH_BOX") or not plan.get("engineered_certification"):
            err("ERR_ENGINEERED_DESIGN_REQUIRED", 422,
                "max_depth_ft >= 20 requires SHORING or TRENCH_BOX with engineered_certification")
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = actor["user_id"]
    touch(plan)
    audit(plan["project_id"], actor, "POST /site-utility/trench-safety-plans/{id}/submit",
          "TrenchSafetyPlan", pid, "status DRAFT->SUBMITTED")
    return success_object(plan)


@app.post("/site-utility/trench-safety-plans/<pid>/review")
def review_trench_plan(pid):
    actor = require_roles("SafetyOfficer")
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    plan = get_or_404(store.trench_safety_plans, pid, "TrenchSafetyPlan")
    if plan["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, f"Plan status must be SUBMITTED, is {plan['status']}")
    if plan.get("submitted_by_user_id") == actor["user_id"]:
        err("ERR_SOD_VIOLATION", 403, "Reviewer must differ from submitter")
    plan["reviewed_by_user_id"] = actor["user_id"]
    plan["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(plan)
    audit(plan["project_id"], actor, "POST /site-utility/trench-safety-plans/{id}/review",
          "TrenchSafetyPlan", pid, f"status SUBMITTED->{plan['status']}")
    return success_object(plan)


@app.post("/site-utility/trench-safety-plans/<pid>/revise")
def revise_trench_plan(pid):
    actor = require_roles("Foreman")
    plan = get_or_404(store.trench_safety_plans, pid, "TrenchSafetyPlan")
    if plan["status"] != "REJECTED":
        err("ERR_INVALID_STATE", 409, f"Plan status must be REJECTED, is {plan['status']}")
    body = get_json_body() if request.data else {}
    if "max_depth_ft" in body and body["max_depth_ft"] is not None:
        v = body["max_depth_ft"]
        if not isinstance(v, (int, float)) or v <= 0:
            err("ERR_VALIDATION", 400, "max_depth_ft must be a positive number")
        plan["max_depth_ft"] = v
    if "soil_class" in body and body["soil_class"] is not None:
        if body["soil_class"] not in SOIL_CLASSES:
            err("ERR_VALIDATION", 400, "soil_class invalid")
        plan["soil_class"] = body["soil_class"]
    if "protective_system" in body and body["protective_system"] is not None:
        if body["protective_system"] not in PROTECTIVE_SYSTEMS:
            err("ERR_VALIDATION", 400, "protective_system invalid")
        plan["protective_system"] = body["protective_system"]
    if "slope_ratio" in body:
        plan["slope_ratio"] = body["slope_ratio"]
    if "engineered_certification" in body and body["engineered_certification"] is not None:
        if not isinstance(body["engineered_certification"], bool):
            err("ERR_VALIDATION", 400, "engineered_certification must be boolean")
        plan["engineered_certification"] = body["engineered_certification"]
    plan["status"] = "DRAFT"
    plan["revision"] = plan.get("revision", 1) + 1
    touch(plan)
    audit(plan["project_id"], actor, "POST /site-utility/trench-safety-plans/{id}/revise",
          "TrenchSafetyPlan", pid, f"status REJECTED->DRAFT (revision={plan['revision']})")
    return success_object(plan)


# ===========================================================================
# Installation Inspections
# ===========================================================================
@app.post("/site-utility/installation-inspections")
def create_inspection():
    actor = require_roles("Inspector")
    body = get_json_body()
    pipe_segment_id = require(body, "pipe_segment_id", "string")
    bedding_ok = require(body, "bedding_ok", "bool")
    joint_ok = require(body, "joint_ok", "bool")
    slope_measured_pct = require_nonnegative_number(body, "slope_measured_pct")
    cover_depth_ft = require_nonnegative_number(body, "cover_depth_ft")

    seg = store.pipe_segments.get(pipe_segment_id)
    if not seg:
        err("ERR_NOT_FOUND", 404, f"PipeSegment not found: {pipe_segment_id}")
    if seg["status"] != "INSTALLED":
        err("ERR_INVALID_STATE", 409, f"Segment must be INSTALLED, is {seg['status']}")

    slope_delta = abs(slope_measured_pct - seg["design_slope_pct"])
    result = "PASS" if (
        bedding_ok and joint_ok and slope_delta <= 0.2 and cover_depth_ft >= 0.5
    ) else "FAIL"

    insp = stamp_new({
        "pipe_segment_id": pipe_segment_id,
        "bedding_ok": bedding_ok,
        "joint_ok": joint_ok,
        "slope_measured_pct": slope_measured_pct,
        "cover_depth_ft": cover_depth_ft,
        "result": result,
        "recorded_by_user_id": actor["user_id"],
        "status": "RECORDED",
    })
    store.installation_inspections[insp["id"]] = insp
    audit(seg["project_id"], actor, "POST /site-utility/installation-inspections",
          "InstallationInspection", insp["id"], f"inspection recorded (result={result})")
    return success_object(insp, 201)


@app.get("/site-utility/installation-inspections")
def list_inspections():
    current_actor()
    return list_response(
        store.installation_inspections,
        filters={
            "pipe_segment_id": request.args.get("pipe_segment_id"),
            "status": request.args.get("status"),
            "result": request.args.get("result"),
        },
    )


@app.get("/site-utility/installation-inspections/<iid>")
def get_inspection(iid):
    current_actor()
    return success_object(get_or_404(store.installation_inspections, iid, "InstallationInspection"))


@app.post("/site-utility/installation-inspections/<iid>/confirm")
def confirm_inspection(iid):
    actor = require_roles("Inspector")
    insp = get_or_404(store.installation_inspections, iid, "InstallationInspection")
    if insp["status"] != "RECORDED":
        err("ERR_INVALID_STATE", 409, f"Inspection status must be RECORDED, is {insp['status']}")
    if insp["recorded_by_user_id"] == actor["user_id"]:
        err("ERR_SOD_VIOLATION", 403, "Confirmer must differ from recorder")
    insp["status"] = "CONFIRMED"
    touch(insp)
    seg = store.pipe_segments.get(insp["pipe_segment_id"])
    audit(seg["project_id"] if seg else None, actor,
          "POST /site-utility/installation-inspections/{id}/confirm",
          "InstallationInspection", iid, "status RECORDED->CONFIRMED")
    return success_object(insp)


@app.post("/site-utility/installation-inspections/<iid>/dispute")
def dispute_inspection(iid):
    actor = require_roles("ProjectManager")
    insp = get_or_404(store.installation_inspections, iid, "InstallationInspection")
    if insp["status"] != "RECORDED":
        err("ERR_INVALID_STATE", 409, f"Inspection status must be RECORDED, is {insp['status']}")
    insp["status"] = "DISPUTED"
    touch(insp)
    seg = store.pipe_segments.get(insp["pipe_segment_id"])
    audit(seg["project_id"] if seg else None, actor,
          "POST /site-utility/installation-inspections/{id}/dispute",
          "InstallationInspection", iid, "status RECORDED->DISPUTED")
    return success_object(insp)


# ===========================================================================
# Shutdown Windows
# ===========================================================================
@app.post("/site-utility/shutdown-windows")
def create_shutdown_window():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    utility_owner_id = require(body, "utility_owner_id", "string")
    pipe_segment_id = require(body, "pipe_segment_id", "string")
    ws_raw = require(body, "window_start", "string")
    we_raw = require(body, "window_end", "string")
    expected_project_version = require(body, "expected_project_version", "int")

    try:
        window_start = parse_iso(ws_raw)
        window_end = parse_iso(we_raw)
    except Exception:
        err("ERR_VALIDATION", 400, "window_start / window_end must be ISO 8601")

    project = store.projects.get(project_id)
    if not project:
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")
    owner = store.utility_owners.get(utility_owner_id)
    if not owner:
        err("ERR_NOT_FOUND", 404, f"UtilityOwner not found: {utility_owner_id}")
    seg = store.pipe_segments.get(pipe_segment_id)
    if not seg:
        err("ERR_NOT_FOUND", 404, f"PipeSegment not found: {pipe_segment_id}")
    if seg["project_id"] != project_id:
        err("ERR_CROSS_PROJECT_REFERENCE", 422, "Segment belongs to another project")
    if seg["utility_owner_id"] != utility_owner_id:
        err("ERR_CROSS_PROJECT_REFERENCE", 422, "Owner mismatch with segment's utility_owner_id")

    # duration in whole minutes
    delta_seconds = (window_end - window_start).total_seconds()
    duration_minutes = int(delta_seconds // 60)
    max_minutes = owner["max_shutdown_hours"] * 60
    if duration_minutes <= 0 or duration_minutes > max_minutes:
        err("ERR_VALIDATION", 400,
            f"Window duration must be in (0, {max_minutes}] minutes")

    # OCC
    if expected_project_version != project["version"]:
        err("ERR_STALE_VERSION", 412,
            f"expected_project_version {expected_project_version} != current {project['version']}")

    # Temporal rules
    now = CLOCK.now()
    if not (window_start > now):
        err("ERR_WINDOW_IN_PAST", 422, "window_start must be strictly after now")
    notice_gap_hours = (window_start - now).total_seconds() / 3600.0
    if notice_gap_hours < owner["min_notice_hours"]:
        err("ERR_INSUFFICIENT_NOTICE", 422,
            f"Notice {notice_gap_hours:.2f}h < min_notice_hours {owner['min_notice_hours']}")

    # Owner overlap (half-open)
    for w in store.shutdown_windows.values():
        if w["utility_owner_id"] != utility_owner_id:
            continue
        if w["status"] not in ("PROPOSED", "CONFIRMED", "ACTIVE"):
            continue
        ws2 = parse_iso(w["window_start"])
        we2 = parse_iso(w["window_end"])
        if window_start < we2 and ws2 < window_end:
            err("ERR_OWNER_WINDOW_OVERLAP", 409,
                f"Overlaps existing window {w['id']} for this owner")

    # Project buffer: 120 min clearance
    clearance = timedelta(minutes=120)
    for w in store.shutdown_windows.values():
        if w["project_id"] != project_id:
            continue
        if w["status"] not in ("PROPOSED", "CONFIRMED", "ACTIVE"):
            continue
        ws2 = parse_iso(w["window_start"])
        we2 = parse_iso(w["window_end"])
        # Check that [window_start, window_end) has >= 120 min clearance from
        # [ws2, we2). Treat as violated when the buffered intervals overlap.
        if (window_start - clearance) < we2 and (ws2 - clearance) < window_end and (
            window_start < we2 + clearance and ws2 < window_end + clearance
        ):
            # More precisely: gap between the two windows
            if window_end <= ws2:
                gap = (ws2 - window_end)
            elif we2 <= window_start:
                gap = (window_start - we2)
            else:
                gap = timedelta(0)
            if gap < clearance:
                err("ERR_PROJECT_WINDOW_BUFFER", 409,
                    f"Less than 120-minute clearance from window {w['id']} of same project")

    win = stamp_new({
        "project_id": project_id,
        "utility_owner_id": utility_owner_id,
        "pipe_segment_id": pipe_segment_id,
        "window_start": format_iso(window_start),
        "window_end": format_iso(window_end),
        "duration_minutes": duration_minutes,
        "status": "PROPOSED",
    })
    store.shutdown_windows[win["id"]] = win
    owner["committed_shutdown_minutes"] = owner.get("committed_shutdown_minutes", 0) + duration_minutes
    touch(owner)
    touch(project)
    audit(project_id, actor, "POST /site-utility/shutdown-windows",
          "ShutdownWindow", win["id"], "shutdown window proposed")
    return success_object(win, 201)


@app.get("/site-utility/shutdown-windows")
def list_shutdown_windows():
    current_actor()
    return list_response(
        store.shutdown_windows,
        filters={
            "project_id": request.args.get("project_id"),
            "utility_owner_id": request.args.get("utility_owner_id"),
            "pipe_segment_id": request.args.get("pipe_segment_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/shutdown-windows/<wid>")
def get_shutdown_window(wid):
    current_actor()
    return success_object(get_or_404(store.shutdown_windows, wid, "ShutdownWindow"))


def _release_window_minutes(win):
    owner = store.utility_owners.get(win["utility_owner_id"])
    if owner:
        owner["committed_shutdown_minutes"] = max(
            0, owner.get("committed_shutdown_minutes", 0) - win["duration_minutes"]
        )
        touch(owner)


@app.post("/site-utility/shutdown-windows/<wid>/review")
def review_shutdown_window(wid):
    actor = require_roles("UtilityOwnerRep")
    body = get_json_body()
    decision = require_enum(body, "decision", {"CONFIRM", "REJECT"})
    win = get_or_404(store.shutdown_windows, wid, "ShutdownWindow")
    if actor["user_id"] != win["utility_owner_id"]:
        err("ERR_UNAUTHORIZED_ROLE", 403,
            "UtilityOwnerRep X-User-ID must equal window.utility_owner_id")
    if win["status"] != "PROPOSED":
        err("ERR_INVALID_STATE", 409, f"Window status must be PROPOSED, is {win['status']}")

    if decision == "CONFIRM":
        project = store.projects.get(win["project_id"])
        _require_clear_posture(project)
        seg = store.pipe_segments.get(win["pipe_segment_id"])
        if not seg or seg["status"] not in ("READY", "INSTALLING", "INSTALLED", "BACKFILLING"):
            err("ERR_INVALID_STATE", 409,
                "Segment must be READY, INSTALLING, INSTALLED, or BACKFILLING")
        win["status"] = "CONFIRMED"
        touch(win)
        audit(win["project_id"], actor, "POST /site-utility/shutdown-windows/{id}/review",
              "ShutdownWindow", wid, "status PROPOSED->CONFIRMED")
    else:
        win["status"] = "REJECTED"
        touch(win)
        _release_window_minutes(win)
        audit(win["project_id"], actor, "POST /site-utility/shutdown-windows/{id}/review",
              "ShutdownWindow", wid, "status PROPOSED->REJECTED")
    return success_object(win)


@app.post("/site-utility/shutdown-windows/<wid>/cancel")
def cancel_shutdown_window(wid):
    actor = require_roles("ProjectManager")
    win = get_or_404(store.shutdown_windows, wid, "ShutdownWindow")
    if win["status"] == "PROPOSED":
        win["status"] = "CANCELLED"
    elif win["status"] == "CONFIRMED":
        now = CLOCK.now()
        if now >= parse_iso(win["window_end"]):
            err("ERR_INVALID_STATE", 409, "Cannot cancel a CONFIRMED window after its end")
        win["status"] = "CANCELLED"
    else:
        err("ERR_INVALID_STATE", 409, f"Window status must be PROPOSED or CONFIRMED, is {win['status']}")
    touch(win)
    _release_window_minutes(win)
    audit(win["project_id"], actor, "POST /site-utility/shutdown-windows/{id}/cancel",
          "ShutdownWindow", wid, "status ->CANCELLED")
    return success_object(win)


@app.post("/site-utility/shutdown-windows/<wid>/complete")
def complete_shutdown_window(wid):
    actor = require_roles("Foreman")
    win = get_or_404(store.shutdown_windows, wid, "ShutdownWindow")
    if win["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, f"Window status must be ACTIVE, is {win['status']}")
    win["status"] = "COMPLETED"
    touch(win)
    seg = store.pipe_segments.get(win["pipe_segment_id"])
    if seg:
        seg["tie_in_completed"] = True
        touch(seg)
    _release_window_minutes(win)
    audit(win["project_id"], actor, "POST /site-utility/shutdown-windows/{id}/complete",
          "ShutdownWindow", wid, "status ACTIVE->COMPLETED")
    return success_object(win)


# ===========================================================================
# Discharge Permits / Readings
# ===========================================================================
@app.post("/site-utility/discharge-permits")
def create_discharge_permit():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    permit_number = require(body, "permit_number", "string")
    max_flow_gpm = require_positive_int(body, "max_flow_gpm")
    turbidity_limit_ntu = require_positive_int(body, "turbidity_limit_ntu")
    daily_volume_limit_gal = require_positive_int(body, "daily_volume_limit_gal")
    eff_from_raw = require(body, "effective_from", "string")
    eff_to_raw = require(body, "effective_to", "string")
    try:
        eff_from = parse_iso(eff_from_raw)
        eff_to = parse_iso(eff_to_raw)
    except Exception:
        err("ERR_VALIDATION", 400, "effective_from / effective_to must be ISO 8601")
    if eff_from >= eff_to:
        err("ERR_VALIDATION", 400, "effective_from must be strictly before effective_to")

    if not store.projects.get(project_id):
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")

    now = CLOCK.now()
    status = "ACTIVE" if (eff_from <= now < eff_to) else "ISSUED"

    permit = stamp_new({
        "project_id": project_id,
        "permit_number": permit_number,
        "max_flow_gpm": max_flow_gpm,
        "turbidity_limit_ntu": turbidity_limit_ntu,
        "daily_volume_limit_gal": daily_volume_limit_gal,
        "effective_from": format_iso(eff_from),
        "effective_to": format_iso(eff_to),
        "exceedance_count": 0,
        "status": status,
    })
    store.discharge_permits[permit["id"]] = permit
    audit(project_id, actor, "POST /site-utility/discharge-permits",
          "DischargePermit", permit["id"], f"permit created ({status})")
    return success_object(permit, 201)


@app.get("/site-utility/discharge-permits")
def list_discharge_permits():
    current_actor()
    return list_response(
        store.discharge_permits,
        filters={
            "project_id": request.args.get("project_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/discharge-permits/<pid>")
def get_discharge_permit(pid):
    current_actor()
    return success_object(get_or_404(store.discharge_permits, pid, "DischargePermit"))


@app.post("/site-utility/discharge-permits/<pid>/reinstate")
def reinstate_permit(pid):
    actor = require_roles("ProjectManager")
    permit = get_or_404(store.discharge_permits, pid, "DischargePermit")
    if permit["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, f"Permit status must be SUSPENDED, is {permit['status']}")
    now = CLOCK.now()
    eff_from = parse_iso(permit["effective_from"])
    eff_to = parse_iso(permit["effective_to"])
    if now >= eff_to:
        permit["status"] = "EXPIRED"
        touch(permit)
        audit(permit["project_id"], actor,
              "POST /site-utility/discharge-permits/{id}/reinstate",
              "DischargePermit", pid, "status SUSPENDED->EXPIRED")
        return success_object(permit)
    project = store.projects.get(permit["project_id"])
    _require_clear_posture(project)
    permit["status"] = "ACTIVE"
    touch(permit)
    reinstate_permit_cascade(permit, actor)
    audit(permit["project_id"], actor,
          "POST /site-utility/discharge-permits/{id}/reinstate",
          "DischargePermit", pid, "status SUSPENDED->ACTIVE")
    return success_object(permit)


@app.get("/site-utility/discharge-permits/<pid>/readings")
def list_permit_readings(pid):
    current_actor()
    get_or_404(store.discharge_permits, pid, "DischargePermit")
    items = [r for r in store.discharge_readings.values() if r["discharge_permit_id"] == pid]
    cls = request.args.get("classification")
    if cls:
        items = [r for r in items if r["classification"] == cls]
    # PRD §3.6: chronological by recorded_at, then created_at; stable sort
    # keeps insertion order when both keys tie.
    items.sort(key=lambda r: (r["recorded_at"], r["created_at"]))
    total = len(items)
    limit, offset = parse_pagination()
    return success_list(items[offset:offset + limit], limit, offset, total)


@app.post("/site-utility/discharge-readings")
def create_discharge_reading():
    actor = require_roles("Foreman")
    body = get_json_body()
    discharge_permit_id = require(body, "discharge_permit_id", "string")
    recorded_at_raw = require(body, "recorded_at", "string")
    flow_gpm = require_nonnegative_int(body, "flow_gpm")
    turbidity_ntu = require_nonnegative_int(body, "turbidity_ntu")
    duration_min = require_positive_int(body, "duration_min")
    try:
        recorded_at = parse_iso(recorded_at_raw)
    except Exception:
        err("ERR_VALIDATION", 400, "recorded_at must be ISO 8601")

    permit = store.discharge_permits.get(discharge_permit_id)
    if not permit:
        err("ERR_NOT_FOUND", 404, f"DischargePermit not found: {discharge_permit_id}")
    if permit["status"] != "ACTIVE":
        err("ERR_PERMIT_NOT_ACTIVE", 409, f"Permit status is {permit['status']}")

    eff_from = parse_iso(permit["effective_from"])
    eff_to = parse_iso(permit["effective_to"])
    if not (eff_from <= recorded_at < eff_to):
        err("ERR_READING_OUTSIDE_PERMIT_WINDOW", 422,
            "recorded_at outside permit effective window")

    volume_gal = flow_gpm * duration_min

    # Daily cumulative volume — same UTC date as this reading, inclusive
    same_day = recorded_at.date()
    day_volume = 0
    for r in store.discharge_readings.values():
        if r["discharge_permit_id"] != discharge_permit_id:
            continue
        try:
            rdt = parse_iso(r["recorded_at"])
        except Exception:
            continue
        if rdt.date() == same_day:
            day_volume += r["volume_gal"]
    day_volume += volume_gal

    if turbidity_ntu >= permit["turbidity_limit_ntu"]:
        classification = "EXCEEDS_TURBIDITY"
    elif day_volume > permit["daily_volume_limit_gal"]:
        classification = "EXCEEDS_VOLUME"
    elif flow_gpm > permit["max_flow_gpm"]:
        classification = "EXCEEDS_FLOW"
    else:
        classification = "NORMAL"

    reading = stamp_new({
        "discharge_permit_id": discharge_permit_id,
        "recorded_at": format_iso(recorded_at),
        "flow_gpm": flow_gpm,
        "turbidity_ntu": turbidity_ntu,
        "duration_min": duration_min,
        "volume_gal": volume_gal,
        "classification": classification,
    })
    store.discharge_readings[reading["id"]] = reading

    if classification != "NORMAL":
        permit["exceedance_count"] = permit.get("exceedance_count", 0) + 1
        touch(permit)

    audit(permit["project_id"], actor, "POST /site-utility/discharge-readings",
          "DischargeReading", reading["id"], f"reading recorded ({classification})")

    if classification == "EXCEEDS_TURBIDITY":
        suspend_permit_cascade(permit, actor)

    return success_object(reading, 201)


# ===========================================================================
# Compaction Tests
# ===========================================================================
REQUIRED_PCT = {"CLASS_B": 95.0, "CLASS_C": 90.0, "CLASS_D": 85.0}


@app.post("/site-utility/compaction-tests")
def create_compaction_test():
    actor = require_roles("Foreman")
    body = get_json_body()
    pipe_segment_id = require(body, "pipe_segment_id", "string")
    lift_number = require_positive_int(body, "lift_number")
    proctor_max_density_pcf = require_positive_number(body, "proctor_max_density_pcf")
    field_density_pcf = require_positive_number(body, "field_density_pcf")
    moisture_pct = require_nonnegative_number(body, "moisture_pct")

    seg = store.pipe_segments.get(pipe_segment_id)
    if not seg:
        err("ERR_NOT_FOUND", 404, f"PipeSegment not found: {pipe_segment_id}")
    if seg["status"] != "BACKFILLING":
        err("ERR_INVALID_STATE", 409, f"Segment must be BACKFILLING, is {seg['status']}")

    existing = [
        t for t in store.compaction_tests.values()
        if t["pipe_segment_id"] == pipe_segment_id and t["status"] in ("RECORDED", "ACCEPTED")
    ]
    expected_next = (max([t["lift_number"] for t in existing]) + 1) if existing else 1
    if lift_number != expected_next:
        err("ERR_LIFT_SEQUENCE", 422,
            f"lift_number must be {expected_next}, got {lift_number}")

    compaction_pct = round_half_up(100.0 * field_density_pcf / proctor_max_density_pcf, 1)
    required_pct = REQUIRED_PCT[seg["bedding_class"]]
    result = "PASS" if compaction_pct >= required_pct else "FAIL"

    test = stamp_new({
        "pipe_segment_id": pipe_segment_id,
        "lift_number": lift_number,
        "proctor_max_density_pcf": proctor_max_density_pcf,
        "field_density_pcf": field_density_pcf,
        "moisture_pct": moisture_pct,
        "compaction_pct": compaction_pct,
        "required_pct": required_pct,
        "result": result,
        "recorded_by_user_id": actor["user_id"],
        "reviewed_by_user_id": None,
        "status": "RECORDED",
    })
    store.compaction_tests[test["id"]] = test
    audit(seg["project_id"], actor, "POST /site-utility/compaction-tests",
          "CompactionTest", test["id"], f"compaction test recorded (result={result})")
    return success_object(test, 201)


@app.get("/site-utility/compaction-tests")
def list_compaction_tests():
    current_actor()
    filters = {
        "pipe_segment_id": request.args.get("pipe_segment_id"),
        "status": request.args.get("status"),
        "result": request.args.get("result"),
    }
    lift = request.args.get("lift_number")
    if lift is not None:
        try:
            filters["lift_number"] = int(lift)
        except ValueError:
            err("ERR_VALIDATION", 400, "lift_number must be an integer")
    return list_response(store.compaction_tests, filters=filters)


@app.get("/site-utility/compaction-tests/<tid>")
def get_compaction_test(tid):
    current_actor()
    return success_object(get_or_404(store.compaction_tests, tid, "CompactionTest"))


@app.post("/site-utility/compaction-tests/<tid>/review")
def review_compaction_test(tid):
    actor = require_roles("Inspector")
    body = get_json_body()
    decision = require_enum(body, "decision", {"ACCEPT", "REJECT"})
    test = get_or_404(store.compaction_tests, tid, "CompactionTest")
    if test["status"] != "RECORDED":
        err("ERR_INVALID_STATE", 409, f"Test status must be RECORDED, is {test['status']}")
    if test["recorded_by_user_id"] == actor["user_id"]:
        err("ERR_SOD_VIOLATION", 403, "Reviewer must differ from recorder")
    test["reviewed_by_user_id"] = actor["user_id"]
    test["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(test)
    seg = store.pipe_segments.get(test["pipe_segment_id"])
    if seg and decision == "ACCEPT" and test["result"] == "PASS":
        recompute_segment_compaction(seg)
    audit(seg["project_id"] if seg else None, actor,
          "POST /site-utility/compaction-tests/{id}/review",
          "CompactionTest", tid, f"status RECORDED->{test['status']}")
    return success_object(test)


# ===========================================================================
# As-Built Packages
# ===========================================================================
def compute_asbuilt(measured_length_ft, measured_invert_ft, seg):
    length_variance_ft = measured_length_ft - seg["length_ft"]
    invert_variance_ft = measured_invert_ft - seg["design_invert_depth_ft"]
    length_tol_ft = max(1.0, round_half_up(0.01 * seg["length_ft"], 1))
    invert_tol_ft = max(0.1, round_half_up(0.005 * seg["design_invert_depth_ft"], 2))
    within = (abs(length_variance_ft) <= length_tol_ft) and (abs(invert_variance_ft) <= invert_tol_ft)
    return length_variance_ft, invert_variance_ft, within


@app.post("/site-utility/as-built-packages")
def create_asbuilt():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    pipe_segment_id = require(body, "pipe_segment_id", "string")
    surveyor_stamp = require(body, "surveyor_stamp", "string")
    measured_length_ft = require_positive_number(body, "measured_length_ft")
    measured_invert_ft = require_positive_number(body, "measured_invert_ft")

    seg = store.pipe_segments.get(pipe_segment_id)
    if not seg:
        err("ERR_NOT_FOUND", 404, f"PipeSegment not found: {pipe_segment_id}")
    for a in store.as_built_packages.values():
        if a["pipe_segment_id"] == pipe_segment_id and a["status"] in ("DRAFT", "SUBMITTED"):
            err("ERR_ASBUILT_ALREADY_OPEN", 409, "Segment already has an open as-built package")

    lv, iv, within = compute_asbuilt(measured_length_ft, measured_invert_ft, seg)
    pkg = stamp_new({
        "pipe_segment_id": pipe_segment_id,
        "surveyor_stamp": surveyor_stamp,
        "measured_length_ft": measured_length_ft,
        "measured_invert_ft": measured_invert_ft,
        "length_variance_ft": lv,
        "invert_variance_ft": iv,
        "within_tolerance": within,
        "revision": 1,
        "status": "DRAFT",
    })
    store.as_built_packages[pkg["id"]] = pkg
    audit(seg["project_id"], actor, "POST /site-utility/as-built-packages",
          "AsBuiltPackage", pkg["id"], "as-built drafted")
    return success_object(pkg, 201)


@app.get("/site-utility/as-built-packages")
def list_asbuilts():
    current_actor()
    return list_response(
        store.as_built_packages,
        filters={
            "pipe_segment_id": request.args.get("pipe_segment_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/as-built-packages/<aid>")
def get_asbuilt(aid):
    current_actor()
    return success_object(get_or_404(store.as_built_packages, aid, "AsBuiltPackage"))


@app.post("/site-utility/as-built-packages/<aid>/submit")
def submit_asbuilt(aid):
    actor = require_roles("ProjectManager")
    pkg = get_or_404(store.as_built_packages, aid, "AsBuiltPackage")
    if pkg["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, f"AsBuilt status must be DRAFT, is {pkg['status']}")
    seg = store.pipe_segments.get(pkg["pipe_segment_id"])
    if not seg or seg["status"] != "COMPLETE":
        err("ERR_SEGMENT_NOT_COMPLETE", 409, "Pipe segment is not COMPLETE")
    pkg["status"] = "SUBMITTED"
    touch(pkg)
    audit(seg["project_id"], actor, "POST /site-utility/as-built-packages/{id}/submit",
          "AsBuiltPackage", aid, "status DRAFT->SUBMITTED")
    return success_object(pkg)


@app.post("/site-utility/as-built-packages/<aid>/review")
def review_asbuilt(aid):
    actor = require_roles("UtilityOwnerRep")
    body = get_json_body()
    decision = require_enum(body, "decision", {"ACCEPT", "REJECT"})
    pkg = get_or_404(store.as_built_packages, aid, "AsBuiltPackage")
    seg = store.pipe_segments.get(pkg["pipe_segment_id"])
    if not seg:
        err("ERR_NOT_FOUND", 404, "PipeSegment not found")
    if actor["user_id"] != seg["utility_owner_id"]:
        err("ERR_UNAUTHORIZED_ROLE", 403,
            "UtilityOwnerRep X-User-ID must equal segment's utility_owner_id")
    if pkg["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, f"AsBuilt status must be SUBMITTED, is {pkg['status']}")
    if decision == "ACCEPT":
        if not pkg["within_tolerance"]:
            err("ERR_ASBUILT_OUT_OF_TOLERANCE", 409, "within_tolerance is false")
        pkg["status"] = "ACCEPTED"
    else:
        pkg["status"] = "REJECTED"
    touch(pkg)
    audit(seg["project_id"], actor, "POST /site-utility/as-built-packages/{id}/review",
          "AsBuiltPackage", aid, f"status SUBMITTED->{pkg['status']}")
    return success_object(pkg)


@app.post("/site-utility/as-built-packages/<aid>/revise")
def revise_asbuilt(aid):
    actor = require_roles("ProjectManager")
    pkg = get_or_404(store.as_built_packages, aid, "AsBuiltPackage")
    if pkg["status"] != "REJECTED":
        err("ERR_INVALID_STATE", 409, f"AsBuilt status must be REJECTED, is {pkg['status']}")
    body = get_json_body() if request.data else {}
    if "surveyor_stamp" in body and body["surveyor_stamp"] is not None:
        if not isinstance(body["surveyor_stamp"], str):
            err("ERR_VALIDATION", 400, "surveyor_stamp must be a string")
        pkg["surveyor_stamp"] = body["surveyor_stamp"]
    if "measured_length_ft" in body and body["measured_length_ft"] is not None:
        v = body["measured_length_ft"]
        if not isinstance(v, (int, float)) or v <= 0:
            err("ERR_VALIDATION", 400, "measured_length_ft must be positive")
        pkg["measured_length_ft"] = v
    if "measured_invert_ft" in body and body["measured_invert_ft"] is not None:
        v = body["measured_invert_ft"]
        if not isinstance(v, (int, float)) or v <= 0:
            err("ERR_VALIDATION", 400, "measured_invert_ft must be positive")
        pkg["measured_invert_ft"] = v
    seg = store.pipe_segments.get(pkg["pipe_segment_id"])
    lv, iv, within = compute_asbuilt(pkg["measured_length_ft"], pkg["measured_invert_ft"], seg)
    pkg["length_variance_ft"] = lv
    pkg["invert_variance_ft"] = iv
    pkg["within_tolerance"] = within
    pkg["revision"] = pkg.get("revision", 1) + 1
    pkg["status"] = "DRAFT"
    touch(pkg)
    audit(seg["project_id"] if seg else None, actor,
          "POST /site-utility/as-built-packages/{id}/revise",
          "AsBuiltPackage", aid, f"status REJECTED->DRAFT (revision={pkg['revision']})")
    return success_object(pkg)


# ===========================================================================
# Unforeseen Conditions
# ===========================================================================
CONDITION_TYPES = {"ROCK", "GROUNDWATER", "CONTAMINATED_SOIL", "CONFLICTING_UTILITY", "VOID"}


@app.post("/site-utility/unforeseen-conditions")
def create_condition():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    pipe_segment_id = optional(body, "pipe_segment_id", None, "string")
    condition_type = require_enum(body, "condition_type", CONDITION_TYPES)
    stop_work_required = require(body, "stop_work_required", "bool")
    description = require(body, "description", "string")

    project = store.projects.get(project_id)
    if not project:
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")
    if project["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, f"Project status must be ACTIVE, is {project['status']}")
    if pipe_segment_id is not None:
        seg = store.pipe_segments.get(pipe_segment_id)
        if not seg:
            err("ERR_NOT_FOUND", 404, f"PipeSegment not found: {pipe_segment_id}")
        if seg["project_id"] != project_id:
            err("ERR_CROSS_PROJECT_REFERENCE", 422, "Segment belongs to another project")

    cond = stamp_new({
        "project_id": project_id,
        "pipe_segment_id": pipe_segment_id,
        "condition_type": condition_type,
        "stop_work_required": stop_work_required,
        "description": description,
        "status": "OPEN",
    })
    store.unforeseen_conditions[cond["id"]] = cond
    audit(project_id, actor, "POST /site-utility/unforeseen-conditions",
          "UnforeseenCondition", cond["id"], "condition reported (OPEN)")

    if stop_work_required:
        apply_stop_work(project, actor)
    if condition_type == "GROUNDWATER":
        groundwater_readiness_recompute(project, actor)

    return success_object(cond, 201)


@app.get("/site-utility/unforeseen-conditions")
def list_conditions():
    current_actor()
    return list_response(
        store.unforeseen_conditions,
        filters={
            "project_id": request.args.get("project_id"),
            "pipe_segment_id": request.args.get("pipe_segment_id"),
            "status": request.args.get("status"),
            "condition_type": request.args.get("condition_type"),
        },
    )


@app.get("/site-utility/unforeseen-conditions/<cid>")
def get_condition(cid):
    current_actor()
    return success_object(get_or_404(store.unforeseen_conditions, cid, "UnforeseenCondition"))


@app.post("/site-utility/unforeseen-conditions/<cid>/resolve")
def resolve_condition(cid):
    actor = require_roles("ProjectManager")
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"RESOLVED", "CLOSED_NO_ACTION"})
    cond = get_or_404(store.unforeseen_conditions, cid, "UnforeseenCondition")
    if cond["status"] not in ("OPEN", "MITIGATING"):
        err("ERR_INVALID_STATE", 409, f"Condition status must be OPEN or MITIGATING, is {cond['status']}")
    # MITIGATING can only go to RESOLVED
    if cond["status"] == "MITIGATING" and outcome != "RESOLVED":
        err("ERR_INVALID_STATE", 409, "MITIGATING condition can only resolve to RESOLVED")

    cos = [c for c in store.change_orders.values() if c["unforeseen_condition_id"] == cid]
    if cond["status"] == "OPEN":
        for c in cos:
            if c["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
                err("ERR_CO_NOT_COMPLETED", 409, "Open change orders block resolution")
    else:  # MITIGATING
        for c in cos:
            if c["status"] not in ("COMPLETED", "SUPERSEDED"):
                err("ERR_CO_NOT_COMPLETED", 409,
                    "All change orders must be COMPLETED or SUPERSEDED to resolve from MITIGATING")

    cond["status"] = outcome
    touch(cond)
    audit(cond["project_id"], actor, "POST /site-utility/unforeseen-conditions/{id}/resolve",
          "UnforeseenCondition", cid, f"status ->{outcome}")

    if cond.get("stop_work_required"):
        project = store.projects.get(cond["project_id"])
        if project:
            recompute_work_posture(project, actor)
    return success_object(cond)


# ===========================================================================
# Change Orders
# ===========================================================================
TIER1_LIMIT = 2_500_000
TIER2_LIMIT = 10_000_000


def price_change_order(labor_hours, labor_rate_cents, equipment_hours, equipment_rate_cents, material_cost_cents):
    labor_cost = round_half_up(labor_hours * labor_rate_cents, 0)
    equipment_cost = round_half_up(equipment_hours * equipment_rate_cents, 0)
    direct = labor_cost + equipment_cost + material_cost_cents
    slice1 = round_half_up(min(direct, TIER1_LIMIT) * 0.15, 0)
    slice2 = round_half_up(max(0, min(direct, TIER2_LIMIT) - TIER1_LIMIT) * 0.10, 0)
    slice3 = round_half_up(max(0, direct - TIER2_LIMIT) * 0.05, 0)
    markup = slice1 + slice2 + slice3
    return direct, markup, direct + markup


@app.post("/site-utility/change-orders")
def create_change_order():
    actor = require_roles("ProjectManager")
    body = get_json_body()
    project_id = require(body, "project_id", "string")
    unforeseen_condition_id = require(body, "unforeseen_condition_id", "string")
    utility_owner_id = require(body, "utility_owner_id", "string")
    labor_hours = require_nonnegative_number(body, "labor_hours")
    labor_rate_cents = require_nonnegative_int(body, "labor_rate_cents")
    equipment_hours = require_nonnegative_number(body, "equipment_hours")
    equipment_rate_cents = require_nonnegative_int(body, "equipment_rate_cents")
    material_cost_cents = require_nonnegative_int(body, "material_cost_cents")
    expected_project_version = require(body, "expected_project_version", "int")

    project = store.projects.get(project_id)
    if not project:
        err("ERR_NOT_FOUND", 404, f"Project not found: {project_id}")
    cond = store.unforeseen_conditions.get(unforeseen_condition_id)
    if not cond:
        err("ERR_NOT_FOUND", 404, f"UnforeseenCondition not found: {unforeseen_condition_id}")
    owner = store.utility_owners.get(utility_owner_id)
    if not owner:
        err("ERR_NOT_FOUND", 404, f"UtilityOwner not found: {utility_owner_id}")

    if expected_project_version != project["version"]:
        err("ERR_STALE_VERSION", 412,
            f"expected_project_version {expected_project_version} != current {project['version']}")

    if cond["project_id"] != project_id:
        err("ERR_CROSS_PROJECT_REFERENCE", 422, "Condition belongs to another project")
    if cond["status"] != "OPEN":
        err("ERR_CONDITION_NOT_OPEN", 422, f"Condition must be OPEN, is {cond['status']}")

    direct, markup, provisional = price_change_order(
        labor_hours, labor_rate_cents, equipment_hours, equipment_rate_cents, material_cost_cents
    )
    if provisional > project["single_co_cap_cents"]:
        err("ERR_PRICE_CAP_EXCEEDED", 422,
            f"provisional_price_cents {provisional} > cap {project['single_co_cap_cents']}")

    # Supersede open COs of same condition
    for old in store.change_orders.values():
        if old["unforeseen_condition_id"] == unforeseen_condition_id and old["status"] in ("DRAFT", "SUBMITTED"):
            old["status"] = "SUPERSEDED"
            touch(old)
            audit(project_id, actor, "POST /site-utility/change-orders",
                  "ChangeOrder", old["id"], f"status {old['status']}->SUPERSEDED (new CO)".replace("SUPERSEDED->SUPERSEDED", "DRAFT->SUPERSEDED"))

    co = stamp_new({
        "project_id": project_id,
        "unforeseen_condition_id": unforeseen_condition_id,
        "utility_owner_id": utility_owner_id,
        "revision": 1,
        "labor_hours": labor_hours,
        "labor_rate_cents": labor_rate_cents,
        "equipment_hours": equipment_hours,
        "equipment_rate_cents": equipment_rate_cents,
        "material_cost_cents": material_cost_cents,
        "direct_cost_cents": direct,
        "markup_cents": markup,
        "provisional_price_cents": provisional,
        "final_price_cents": None,
        "price_delta_cents": None,
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    })
    store.change_orders[co["id"]] = co
    touch(project)
    audit(project_id, actor, "POST /site-utility/change-orders",
          "ChangeOrder", co["id"], "change order created (DRAFT)")
    return success_object(co, 201)


@app.get("/site-utility/change-orders")
def list_change_orders():
    current_actor()
    return list_response(
        store.change_orders,
        filters={
            "project_id": request.args.get("project_id"),
            "unforeseen_condition_id": request.args.get("unforeseen_condition_id"),
            "utility_owner_id": request.args.get("utility_owner_id"),
            "status": request.args.get("status"),
        },
    )


@app.get("/site-utility/change-orders/<cid>")
def get_change_order(cid):
    current_actor()
    return success_object(get_or_404(store.change_orders, cid, "ChangeOrder"))


@app.post("/site-utility/change-orders/<cid>/submit")
def submit_change_order(cid):
    actor = require_roles("ProjectManager")
    co = get_or_404(store.change_orders, cid, "ChangeOrder")
    if co["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, f"CO status must be DRAFT, is {co['status']}")
    cond = store.unforeseen_conditions.get(co["unforeseen_condition_id"])
    if not cond or cond["status"] not in ("OPEN", "MITIGATING"):
        err("ERR_CONDITION_NOT_OPEN", 422,
            f"Condition must be OPEN or MITIGATING, is {cond['status'] if cond else 'missing'}")
    project = store.projects.get(co["project_id"])
    if co["provisional_price_cents"] > project["single_co_cap_cents"]:
        err("ERR_PRICE_CAP_EXCEEDED", 422,
            f"provisional_price_cents {co['provisional_price_cents']} > cap {project['single_co_cap_cents']}")
    co["status"] = "SUBMITTED"
    co["submitted_by_user_id"] = actor["user_id"]
    touch(co)
    audit(co["project_id"], actor, "POST /site-utility/change-orders/{id}/submit",
          "ChangeOrder", cid, "status DRAFT->SUBMITTED")
    return success_object(co)


@app.post("/site-utility/change-orders/<cid>/review")
def review_change_order(cid):
    # Amount-gated role check
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    co = get_or_404(store.change_orders, cid, "ChangeOrder")
    actor = current_actor()

    large = co["provisional_price_cents"] >= TIER1_LIMIT
    if large:
        if actor["role"] != "UtilityOwnerRep":
            err("ERR_UNAUTHORIZED_ROLE", 403,
                "provisional_price_cents >= 2500000 requires UtilityOwnerRep")
        if actor["user_id"] != co["utility_owner_id"]:
            err("ERR_UNAUTHORIZED_ROLE", 403,
                "UtilityOwnerRep X-User-ID must equal change_order.utility_owner_id")
    else:
        if actor["role"] != "ProjectManager":
            err("ERR_UNAUTHORIZED_ROLE", 403,
                "provisional_price_cents < 2500000 requires ProjectManager")

    if co["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, f"CO status must be SUBMITTED, is {co['status']}")

    if co.get("submitted_by_user_id") == actor["user_id"]:
        err("ERR_SOD_VIOLATION", 403, "Reviewer must differ from submitter")

    cond = store.unforeseen_conditions.get(co["unforeseen_condition_id"])
    if not cond or cond["status"] not in ("OPEN", "MITIGATING"):
        err("ERR_CONDITION_NOT_OPEN", 422,
            f"Condition must be OPEN or MITIGATING, is {cond['status'] if cond else 'missing'}")

    project = store.projects.get(co["project_id"])

    if decision == "APPROVE":
        if project["approved_co_total_cents"] + co["provisional_price_cents"] > project["contingency_cents"]:
            err("ERR_CONTINGENCY_EXCEEDED", 409,
                "Approval would exceed project contingency")
        co["status"] = "APPROVED"
        co["reviewed_by_user_id"] = actor["user_id"]
        touch(co)
        project["approved_co_total_cents"] = project.get("approved_co_total_cents", 0) + co["provisional_price_cents"]
        touch(project)
        if cond["status"] == "OPEN":
            cond["status"] = "MITIGATING"
            touch(cond)
        audit(co["project_id"], actor, "POST /site-utility/change-orders/{id}/review",
              "ChangeOrder", cid, "status SUBMITTED->APPROVED")
    else:
        co["status"] = "REJECTED"
        co["reviewed_by_user_id"] = actor["user_id"]
        touch(co)
        audit(co["project_id"], actor, "POST /site-utility/change-orders/{id}/review",
              "ChangeOrder", cid, "status SUBMITTED->REJECTED")
    return success_object(co)


@app.post("/site-utility/change-orders/<cid>/revise")
def revise_change_order(cid):
    actor = require_roles("ProjectManager")
    co = get_or_404(store.change_orders, cid, "ChangeOrder")
    if co["status"] != "REJECTED":
        err("ERR_INVALID_STATE", 409, f"CO status must be REJECTED, is {co['status']}")
    body = get_json_body() if request.data else {}
    pricing_fields = ("labor_hours", "labor_rate_cents", "equipment_hours", "equipment_rate_cents", "material_cost_cents")
    changed = False
    for f in pricing_fields:
        if f in body and body[f] is not None:
            v = body[f]
            if f.endswith("_cents"):
                if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                    err("ERR_VALIDATION", 400, f"{f} must be a non-negative integer")
            else:
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                    err("ERR_VALIDATION", 400, f"{f} must be a non-negative number")
            co[f] = v
            changed = True
    if changed:
        direct, markup, provisional = price_change_order(
            co["labor_hours"], co["labor_rate_cents"],
            co["equipment_hours"], co["equipment_rate_cents"],
            co["material_cost_cents"],
        )
        co["direct_cost_cents"] = direct
        co["markup_cents"] = markup
        co["provisional_price_cents"] = provisional
    co["status"] = "DRAFT"
    co["revision"] = co.get("revision", 1) + 1
    touch(co)
    audit(co["project_id"], actor, "POST /site-utility/change-orders/{id}/revise",
          "ChangeOrder", cid, f"status REJECTED->DRAFT (revision={co['revision']})")
    return success_object(co)


@app.post("/site-utility/change-orders/<cid>/complete")
def complete_change_order(cid):
    actor = require_roles("ProjectManager")
    co = get_or_404(store.change_orders, cid, "ChangeOrder")
    if co["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, f"CO status must be APPROVED, is {co['status']}")
    body = get_json_body()
    actual_labor_hours = require_nonnegative_number(body, "actual_labor_hours")
    actual_labor_rate_cents = require_nonnegative_int(body, "actual_labor_rate_cents")
    actual_equipment_hours = require_nonnegative_number(body, "actual_equipment_hours")
    actual_equipment_rate_cents = require_nonnegative_int(body, "actual_equipment_rate_cents")
    actual_material_cost_cents = require_nonnegative_int(body, "actual_material_cost_cents")

    direct, markup, final_price = price_change_order(
        actual_labor_hours, actual_labor_rate_cents,
        actual_equipment_hours, actual_equipment_rate_cents,
        actual_material_cost_cents,
    )
    co["final_price_cents"] = final_price
    co["price_delta_cents"] = final_price - co["provisional_price_cents"]
    co["status"] = "COMPLETED"
    touch(co)

    project = store.projects.get(co["project_id"])
    if project:
        project["approved_co_total_cents"] = project.get("approved_co_total_cents", 0) + co["price_delta_cents"]
        touch(project)
    audit(co["project_id"], actor, "POST /site-utility/change-orders/{id}/complete",
          "ChangeOrder", cid,
          f"status APPROVED->COMPLETED (final={final_price}, delta={co['price_delta_cents']})")
    return success_object(co)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.post("/site-utility/_clock/set_current_utc")
def set_current_utc():
    actor = require_roles("OpsAdmin")
    body = get_json_body()
    raw = require(body, "to_iso8601", "string")
    try:
        to_dt = parse_iso(raw)
    except Exception:
        err("ERR_VALIDATION", 400, "to_iso8601 must be ISO 8601")
    if to_dt <= CLOCK.now():
        err("ERR_VALIDATION", 400, "to_iso8601 must be strictly greater than current clock")
    advance_clock(to_dt, actor)
    return success_object({"current_utc": format_iso(CLOCK.now())})


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
