"""Early Childhood Enrichment API — entry point and all routes.

In-memory only. The store starts empty on every boot; nothing is seeded.
All routes are mounted under the /enrichment prefix (PRD 2). Validation ordering
follows PRD 2.12: auth -> authz/ownership -> existence -> body -> state ->
business rules -> OCC.
"""
import os
from datetime import timedelta

from flask import Flask

import errors
import middleware
import helpers
import serialize
import services as svc
import calculations as calc
from clock import clock
from util import (
    new_id, iso_ms, parse_instant, parse_date, get_body,
)
from db import db, stamp_create, touch
from response import success, list_success, error_response

app = Flask(__name__)
PREFIX = "/enrichment"

ALL_ROLES = {"StudioAdmin", "FrontDeskStaff", "Parent"}
STAFF_ADMIN = {"StudioAdmin", "FrontDeskStaff"}
ADMIN_ONLY = {"StudioAdmin"}


# ============================================================================
# Error handling
# ============================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e)), 400


# ============================================================================
# Existence helpers (raise ERR_NOT_FOUND)
# ============================================================================
def _need(row):
    if row is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Referenced resource does not exist")
    return row


# ============================================================================
# Logical clock
# ============================================================================
@app.route(PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ADMIN_ONLY)
    body = get_body()
    if "to_iso8601" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing to_iso8601")
    dt = parse_instant(body.get("to_iso8601"))
    clock.set(dt)
    return success({}, status=200)


# ============================================================================
# Family
# ============================================================================
@app.route(PREFIX + "/families", methods=["POST"])
def create_family():
    _, role = middleware.authenticate()
    middleware.require_roles(role, STAFF_ADMIN)
    body = get_body()
    email = helpers.require_str(body, "account_email")
    name = helpers.require_str(body, "primary_contact_name")
    # account_email unique across families.
    for f in db.families.values():
        if f.get("account_email") == email:
            raise errors.err(errors.ERR_INVALID_REQUEST, "account_email already in use")
    row = stamp_create({
        "account_email": email,
        "primary_contact_name": name,
        "child_count": 0,
    })
    db.families[row["id"]] = row
    return success(serialize.family(row), status=201)


@app.route(PREFIX + "/families/<fid>", methods=["GET"])
def get_family_route(fid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    fam = _need(svc.get_family(fid))
    middleware.require_owner(role, _uid(), fam["id"])
    return success(serialize.family(fam), status=200)


@app.route(PREFIX + "/families/<fid>/children", methods=["GET"])
def list_family_children(fid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    fam = _need(svc.get_family(fid))
    middleware.require_owner(role, _uid(), fam["id"])
    items = [c for c in db.children.values() if c.get("family_id") == fid]
    return _list(items, serialize.child)


@app.route(PREFIX + "/families/<fid>/memberships", methods=["GET"])
def list_family_memberships(fid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    fam = _need(svc.get_family(fid))
    middleware.require_owner(role, _uid(), fam["id"])
    items = [m for m in db.memberships.values() if m.get("family_id") == fid]
    return _list(items, serialize.membership)


# ============================================================================
# Child
# ============================================================================
@app.route(PREFIX + "/children", methods=["POST"])
def create_child():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    body = get_body()
    family_id = helpers.require_str(body, "family_id")
    full_name = helpers.require_str(body, "full_name")
    birth_raw = helpers.require_str(body, "birth_date")
    # existence (priority 3) before body semantics
    fam = _need(svc.get_family(family_id))
    middleware.require_owner(role, _uid(), fam["id"])
    # body semantics (priority 4)
    bdate = parse_date(birth_raw)
    if bdate > clock.now().date():
        raise errors.err(errors.ERR_INVALID_REQUEST, "birth_date is in the future")
    row = stamp_create({
        "family_id": family_id,
        "full_name": full_name,
        "birth_date": birth_raw,
        "current_level": 0,
        "status": "ENROLLED_ELIGIBLE",
    })
    db.children[row["id"]] = row
    svc.reconcile_child_count(family_id)
    return success(serialize.child(row), status=201)


@app.route(PREFIX + "/children/<cid>", methods=["GET"])
def get_child_route(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    child = _need(svc.get_child(cid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_child(child))
    return success(serialize.child(child), status=200)


@app.route(PREFIX + "/children/<cid>/enrollments", methods=["GET"])
def list_child_enrollments(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    child = _need(svc.get_child(cid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_child(child))
    items = [e for e in db.enrollments.values() if e.get("child_id") == cid]
    return _list(items, serialize.enrollment)


@app.route(PREFIX + "/children/<cid>/advance", methods=["POST"])
def advance_child(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, STAFF_ADMIN)
    body = get_body()
    target_pid = helpers.require_str(body, "target_program_id")
    child = _need(svc.get_child(cid))
    program = _need(svc.get_program(target_pid))
    svc.advance_child_cascade(child, program)
    return success(serialize.child(child), status=200)


@app.route(PREFIX + "/children/<cid>/withdraw", methods=["POST"])
def withdraw_child(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    child = _need(svc.get_child(cid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_child(child))
    if child.get("status") != "ENROLLED_ELIGIBLE":
        raise errors.err(errors.ERR_INVALID_STATE, "Child is not ENROLLED_ELIGIBLE")
    svc.withdraw_child_cascade(child)
    return success(serialize.child(child), status=200)


# ============================================================================
# Membership
# ============================================================================
@app.route(PREFIX + "/memberships", methods=["POST"])
def create_membership():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    body = get_body()
    family_id = helpers.require_str(body, "family_id")
    tier = helpers.require_enum(body, "tier", ("CORE", "PLUS", "UNLIMITED"))
    anchor = helpers.require_int(body, "cycle_anchor_day")
    fam = _need(svc.get_family(family_id))
    middleware.require_owner(role, _uid(), fam["id"])
    if anchor < 1 or anchor > 28:
        raise errors.err(errors.ERR_INVALID_REQUEST, "cycle_anchor_day must be in [1,28]")
    row = stamp_create({
        "family_id": family_id,
        "tier": tier,
        "status": "PENDING_PAYMENT",
        "cycle_anchor_day": anchor,
        "current_cycle_start": None,
        "makeup_credit_balance": 0,
        "monthly_base_fee_cents": 0,
        "_reactivated_from_frozen": False,
    })
    db.memberships[row["id"]] = row
    return success(serialize.membership(row), status=201)


@app.route(PREFIX + "/memberships/<mid>", methods=["GET"])
def get_membership_route(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    m = _need(svc.get_membership(mid))
    middleware.require_owner(role, _uid(), m["family_id"])
    return success(serialize.membership(m), status=200)


@app.route(PREFIX + "/memberships/<mid>/makeup-credits", methods=["GET"])
def list_membership_credits(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    m = _need(svc.get_membership(mid))
    middleware.require_owner(role, _uid(), m["family_id"])
    items = [c for c in db.credits.values() if c.get("membership_id") == mid]
    return _list(items, serialize.credit)


@app.route(PREFIX + "/memberships/<mid>/invoices", methods=["GET"])
def list_membership_invoices(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    m = _need(svc.get_membership(mid))
    middleware.require_owner(role, _uid(), m["family_id"])
    items = [i for i in db.invoices.values() if i.get("membership_id") == mid]
    return _list(items, serialize.invoice)


@app.route(PREFIX + "/memberships/<mid>/activate", methods=["POST"])
def activate_membership(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    m = _need(svc.get_membership(mid))
    middleware.require_owner(role, _uid(), m["family_id"])
    status = m.get("status")
    if status not in ("PENDING_PAYMENT", "FROZEN"):
        raise errors.err(errors.ERR_INVALID_STATE, "Membership cannot be activated from its current state")
    if status == "PENDING_PAYMENT":
        m["monthly_base_fee_cents"] = calc.MEMBERSHIP_BASE_FEE_CENTS[m["tier"]]
    # A reactivation from FROZEN lands mid-cycle, so its next renewal prorates
    # (PRD 3.6 mid_cycle_prorated). A first activation from PENDING_PAYMENT bills
    # full-cycle. Track which path set current_cycle_start.
    m["_reactivated_from_frozen"] = (status == "FROZEN")
    m["current_cycle_start"] = iso_ms(clock.now())
    m["status"] = "ACTIVE"
    touch(m)
    return success(serialize.membership(m), status=200)


@app.route(PREFIX + "/memberships/<mid>/freeze", methods=["POST"])
def freeze_membership(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    m = _need(svc.get_membership(mid))
    middleware.require_owner(role, _uid(), m["family_id"])
    if m.get("status") != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE membership can be frozen")
    m["status"] = "FROZEN"
    touch(m)
    return success(serialize.membership(m), status=200)


@app.route(PREFIX + "/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    m = _need(svc.get_membership(mid))
    middleware.require_owner(role, _uid(), m["family_id"])
    status = m.get("status")
    if status not in ("ACTIVE", "FROZEN"):
        raise errors.err(errors.ERR_INVALID_STATE, "Membership cannot be cancelled from its current state")
    svc.cancel_membership_cascade(m, was_active=(status == "ACTIVE"))
    return success(serialize.membership(m), status=200)


@app.route(PREFIX + "/memberships/<mid>/renew", methods=["POST"])
def renew_membership(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, STAFF_ADMIN)
    m = _need(svc.get_membership(mid))
    if m.get("status") != "ACTIVE":
        raise errors.err(errors.ERR_MEMBERSHIP_NOT_ACTIVE, "Membership must be ACTIVE to renew")

    cycle_start_dt = parse_instant(m["current_cycle_start"])
    renew_instant = clock.now()

    # Proration applies only when this cycle began with a FROZEN reactivation
    # that landed partway through the cycle (PRD 3.6 mid_cycle_prorated). A
    # first activation from PENDING_PAYMENT bills full-cycle, as does any cycle
    # following a prior renew.
    prorated = bool(m.get("_reactivated_from_frozen"))
    active_days = calc.active_days_for(cycle_start_dt, renew_instant) if prorated else calc.CYCLE_DAYS

    # Billable roster: distinct children with an ENROLLED RECURRING enrollment.
    seen_children = set()
    child_lines = []
    for e in db.enrollments.values():
        if e.get("membership_id") != mid:
            continue
        if e.get("status") != "ENROLLED" or e.get("kind") != "RECURRING":
            continue
        cid = e.get("child_id")
        if cid in seen_children:
            continue
        seen_children.add(cid)
        session = db.sessions.get(e.get("session_id"))
        if session is None:
            continue
        program = db.programs.get(session.get("program_id"))
        if program is None:
            continue
        tuition = program.get("tuition_cents", 0)
        if prorated:
            line = calc.child_line_prorated(tuition, active_days)
        else:
            line = calc.child_line_full(tuition)
        child_lines.append(line)

    billed_child_count = _billed_child_count(mid)
    subtotal, discount, total = calc.compute_invoice(
        m.get("monthly_base_fee_cents", 0), child_lines, billed_child_count
    )

    # Advance current_cycle_start by one cycle to the next cycle_anchor_day.
    # After a renewal the next cycle is a normal full cycle.
    m["current_cycle_start"] = iso_ms(renew_instant)
    m["_reactivated_from_frozen"] = False
    touch(m)

    inv = stamp_create({
        "membership_id": mid,
        "cycle_start": iso_ms(renew_instant),
        "subtotal_cents": subtotal,
        "sibling_discount_cents": discount,
        "total_cents": total,
        "status": "OPEN",
    })
    db.invoices[inv["id"]] = inv
    return success(serialize.invoice(inv), status=201)


def _billed_child_count(mid):
    """Family.child_count semantics for billing: ENROLLED_ELIGIBLE children with
    >=1 ENROLLED RECURRING enrollment on this membership (PRD 3.6)."""
    children = set()
    for e in db.enrollments.values():
        if e.get("membership_id") != mid:
            continue
        if e.get("status") != "ENROLLED" or e.get("kind") != "RECURRING":
            continue
        child = db.children.get(e.get("child_id"))
        if child and child.get("status") == "ENROLLED_ELIGIBLE":
            children.add(child["id"])
    return len(children)


# ============================================================================
# Program
# ============================================================================
@app.route(PREFIX + "/programs", methods=["POST"])
def create_program():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ADMIN_ONLY)
    body = get_body()
    name = helpers.require_str(body, "name")
    level_index = helpers.require_int(body, "level_index")
    min_age = helpers.require_int(body, "min_age_months")
    max_age = helpers.require_int(body, "max_age_months")
    tuition = helpers.require_int(body, "tuition_cents")
    participation = body.get("participation_required", True)
    if not isinstance(participation, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "participation_required must be boolean")
    next_pid = body.get("next_program_id", None)
    if next_pid is not None and not isinstance(next_pid, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "next_program_id must be a string or null")

    if level_index < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "level_index must be >= 0")
    if min_age < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "min_age_months must be >= 0")
    if max_age <= min_age:
        raise errors.err(errors.ERR_INVALID_REQUEST, "max_age_months must be > min_age_months")
    if tuition < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "tuition_cents must be >= 0")
    for p in db.programs.values():
        if p.get("level_index") == level_index:
            raise errors.err(errors.ERR_INVALID_REQUEST, "level_index must be unique")

    row = stamp_create({
        "name": name,
        "level_index": level_index,
        "min_age_months": min_age,
        "max_age_months": max_age,
        "participation_required": participation,
        "tuition_cents": tuition,
        "next_program_id": next_pid,
    })
    db.programs[row["id"]] = row
    return success(serialize.program(row), status=201)


@app.route(PREFIX + "/programs/<pid>", methods=["GET"])
def get_program_route(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    p = _need(svc.get_program(pid))
    return success(serialize.program(p), status=200)


@app.route(PREFIX + "/programs", methods=["GET"])
def list_programs():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    items = list(db.programs.values())
    from flask import request
    npid = request.args.get("next_program_id")
    if npid is not None:
        items = [p for p in items if p.get("next_program_id") == npid]
    return _list(items, serialize.program)


# ============================================================================
# Room
# ============================================================================
@app.route(PREFIX + "/rooms", methods=["POST"])
def create_room():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ADMIN_ONLY)
    body = get_body()
    name = helpers.require_str(body, "name")
    cap = helpers.require_int(body, "physical_capacity")
    if cap < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "physical_capacity must be >= 1")
    row = stamp_create({"name": name, "physical_capacity": cap})
    db.rooms[row["id"]] = row
    return success(serialize.room(row), status=201)


@app.route(PREFIX + "/rooms/<rid>", methods=["GET"])
def get_room_route(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    r = _need(svc.get_room(rid))
    return success(serialize.room(r), status=200)


@app.route(PREFIX + "/rooms/<rid>/sessions", methods=["GET"])
def list_room_sessions(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    _need(svc.get_room(rid))
    items = [s for s in db.sessions.values() if s.get("room_id") == rid]
    return _list(items, serialize.session)


@app.route(PREFIX + "/rooms/<rid>/facility-bookings", methods=["GET"])
def list_room_bookings(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    _need(svc.get_room(rid))
    items = [b for b in db.bookings.values() if b.get("room_id") == rid]
    return _list(items, serialize.booking)


# ============================================================================
# Instructor
# ============================================================================
@app.route(PREFIX + "/instructors", methods=["POST"])
def create_instructor():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ADMIN_ONLY)
    body = get_body()
    full_name = helpers.require_str(body, "full_name")
    certs = body.get("certified_level_indices")
    if (not isinstance(certs, list) or len(certs) == 0
            or any(isinstance(x, bool) or not isinstance(x, int) for x in certs)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "certified_level_indices must be a non-empty integer array")
    buffer_minutes = helpers.optional_int(body, "buffer_minutes", 15)
    if buffer_minutes < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "buffer_minutes must be >= 0")
    row = stamp_create({
        "full_name": full_name,
        "certified_level_indices": sorted(certs),
        "buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
    })
    db.instructors[row["id"]] = row
    return success(serialize.instructor(row), status=201)


@app.route(PREFIX + "/instructors/<iid>", methods=["GET"])
def get_instructor_route(iid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    i = _need(svc.get_instructor(iid))
    return success(serialize.instructor(i), status=200)


@app.route(PREFIX + "/instructors/<iid>/sessions", methods=["GET"])
def list_instructor_sessions(iid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    _need(svc.get_instructor(iid))
    items = [s for s in db.sessions.values() if s.get("instructor_id") == iid]
    return _list(items, serialize.session)


@app.route(PREFIX + "/instructors/<iid>/deactivate", methods=["POST"])
def deactivate_instructor(iid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ADMIN_ONLY)
    i = _need(svc.get_instructor(iid))
    i["status"] = "INACTIVE"
    touch(i)
    return success(serialize.instructor(i), status=200)


# ============================================================================
# ClassSession
# ============================================================================
@app.route(PREFIX + "/sessions", methods=["POST"])
def create_session():
    _, role = middleware.authenticate()
    middleware.require_roles(role, STAFF_ADMIN)
    body = get_body()
    program_id = helpers.require_str(body, "program_id")
    room_id = helpers.require_str(body, "room_id")
    instructor_id = helpers.require_str(body, "instructor_id")
    start_raw = helpers.require_str(body, "start_at")
    end_raw = helpers.require_str(body, "end_at")
    capacity = helpers.require_int(body, "capacity")

    # existence left-to-right: Program, Room, Instructor (priority 3)
    program = _need(svc.get_program(program_id))
    room = _need(svc.get_room(room_id))
    instructor = _need(svc.get_instructor(instructor_id))

    # body semantics (priority 4)
    start_dt = parse_instant(start_raw)
    end_dt = parse_instant(end_raw)
    if end_dt <= start_dt:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_at must be after start_at")
    if capacity < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "capacity must be >= 1")
    if capacity > room.get("physical_capacity", 0):
        raise errors.err(errors.ERR_INVALID_REQUEST, "capacity exceeds room physical_capacity")

    # certification (priority 6)
    if program.get("level_index") not in instructor.get("certified_level_indices", []):
        raise errors.err(errors.ERR_INSTRUCTOR_NOT_CERTIFIED,
                         "Instructor not certified for this program level")
    # instructor schedule conflict (priority 7)
    if svc.instructor_conflict(instructor, start_dt, end_dt):
        raise errors.err(errors.ERR_INSTRUCTOR_SCHEDULE_CONFLICT, "Instructor schedule conflict")
    # room schedule conflict (priority 8)
    if svc.room_conflict_for_session(room, start_dt, end_dt):
        raise errors.err(errors.ERR_ROOM_SCHEDULE_CONFLICT, "Room schedule conflict")

    row = stamp_create({
        "program_id": program_id,
        "room_id": room_id,
        "instructor_id": instructor_id,
        "start_at": start_raw,
        "end_at": end_raw,
        "capacity": capacity,
        "enrolled_count": 0,
        "status": "SCHEDULED",
    })
    db.sessions[row["id"]] = row
    return success(serialize.session(row), status=201)


@app.route(PREFIX + "/sessions", methods=["GET"])
def list_sessions():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    from flask import request
    items = list(db.sessions.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [s for s in items if s.get("program_id") == pid]
    return _list(items, serialize.session)


@app.route(PREFIX + "/sessions/<sid>", methods=["GET"])
def get_session_route(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    s = _need(svc.get_session(sid))
    return success(serialize.session(s), status=200)


@app.route(PREFIX + "/sessions/<sid>/enrollments", methods=["GET"])
def list_session_enrollments(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    _need(svc.get_session(sid))
    items = [e for e in db.enrollments.values() if e.get("session_id") == sid]
    return _list(items, serialize.enrollment)


@app.route(PREFIX + "/sessions/<sid>/attendance", methods=["GET"])
def list_session_attendance(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    _need(svc.get_session(sid))
    items = [a for a in db.attendance.values() if a.get("session_id") == sid]
    return _list(items, serialize.attendance)


@app.route(PREFIX + "/attendance-records", methods=["GET"])
def list_attendance_records():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    from flask import request
    items = list(db.attendance.values())
    enr = request.args.get("enrollment_id")
    sid = request.args.get("session_id")
    if enr is not None:
        items = [a for a in items if a.get("enrollment_id") == enr]
    if sid is not None:
        items = [a for a in items if a.get("session_id") == sid]
    return _list(items, serialize.attendance)


@app.route(PREFIX + "/sessions/<sid>/hold", methods=["POST"])
def hold_session(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, STAFF_ADMIN)
    s = _need(svc.get_session(sid))
    # state (priority 5)
    if s.get("status") != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")
    # instructor must be ACTIVE at hold time (priority 6)
    instructor = db.instructors.get(s.get("instructor_id"))
    if instructor is None or instructor.get("status") != "ACTIVE":
        raise errors.err(errors.ERR_INSTRUCTOR_NOT_CERTIFIED, "Instructor is not ACTIVE")
    # clock must have reached start_at; too-early hold -> invalid state
    if clock.now() < parse_instant(s["start_at"]):
        raise errors.err(errors.ERR_INVALID_STATE, "Session start instant not yet reached")
    body = get_body()
    attendance_map = body.get("attendance", {}) or {}
    if not isinstance(attendance_map, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "attendance must be an object")
    # validate provided outcomes
    for v in attendance_map.values():
        if v not in ("PRESENT", "ABSENT"):
            raise errors.err(errors.ERR_INVALID_REQUEST, "attendance outcome must be PRESENT or ABSENT")
    svc.hold_session_cascade(s, attendance_map)
    return success(serialize.session(s), status=200)


@app.route(PREFIX + "/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, STAFF_ADMIN)
    s = _need(svc.get_session(sid))
    if s.get("status") != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")
    svc.cancel_session_cascade(s)
    return success(serialize.session(s), status=200)


# ============================================================================
# Enrollment
# ============================================================================
@app.route(PREFIX + "/enrollments", methods=["POST"])
def create_enrollment():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    body = get_body()
    child_id = helpers.require_str(body, "child_id")
    session_id = helpers.require_str(body, "session_id")
    membership_id = helpers.require_str(body, "membership_id")

    # existence left-to-right: Child, ClassSession, Membership (priority 3)
    child = _need(svc.get_child(child_id))
    session = _need(svc.get_session(session_id))
    membership = _need(svc.get_membership(membership_id))

    # ownership: Parent acts on own family (child's family)
    middleware.require_owner(role, _uid(), svc.owning_family_of_child(child))

    # body semantics (priority 4)
    kind = body.get("kind", "RECURRING")
    if kind not in ("TRIAL", "RECURRING"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "kind must be TRIAL or RECURRING")
    if "expected_session_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_session_version is required")
    expected_version = body.get("expected_session_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_session_version must be an integer")
    accompanying = body.get("accompanying_adult")

    program = db.programs.get(session.get("program_id"))

    # state: session must be SCHEDULED (priority 5)
    if session.get("status") != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")

    # age eligibility (priority 9)
    bdate = parse_date(child["birth_date"])
    session_start = parse_instant(session["start_at"])
    if not calc.age_eligible(bdate, session_start,
                             program.get("min_age_months"), program.get("max_age_months")):
        raise errors.err(errors.ERR_AGE_BAND_MISMATCH, "Child age outside program band")

    # level match for RECURRING (priority 10)
    if kind == "RECURRING" and child.get("current_level") != program.get("level_index"):
        raise errors.err(errors.ERR_LEVEL_MISMATCH, "Child not on this program level")

    # membership active for RECURRING (priority 11)
    if kind == "RECURRING" and membership.get("status") != "ACTIVE":
        raise errors.err(errors.ERR_MEMBERSHIP_NOT_ACTIVE, "Membership is not ACTIVE")

    # capacity (priority 12)
    at_capacity = session.get("enrolled_count", 0) >= session.get("capacity", 0)
    if kind == "TRIAL" and at_capacity:
        raise errors.err(errors.ERR_SESSION_FULL, "Session is at capacity")

    # parent-participation (priority 13)
    if program.get("participation_required") and not accompanying:
        raise errors.err(errors.ERR_PARTICIPATION_REQUIRED, "accompanying_adult required")

    # OCC stale-version (priority 15)
    if expected_version != session.get("version"):
        raise errors.err(errors.ERR_STALE_VERSION, "Stale session version")

    # Create.
    will_waitlist = (kind == "RECURRING" and at_capacity)
    row = stamp_create({
        "child_id": child_id,
        "session_id": session_id,
        "membership_id": membership_id,
        "kind": kind,
        "status": "WAITLISTED" if will_waitlist else "ENROLLED",
        "waitlist_seq": None,
        "redeemed_credit_id": None,
        "residual_owed_cents": 0,
    })
    if will_waitlist:
        row["waitlist_seq"] = svc.max_waitlist_seq(session_id) + 1
    else:
        session["enrolled_count"] = session.get("enrolled_count", 0) + 1
    db.enrollments[row["id"]] = row
    # Every successful create bumps the session version.
    touch(session)
    return success(serialize.enrollment(row), status=201)


@app.route(PREFIX + "/enrollments/<eid>", methods=["GET"])
def get_enrollment_route(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    e = _need(svc.get_enrollment(eid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_enrollment(e))
    return success(serialize.enrollment(e), status=200)


@app.route(PREFIX + "/enrollments/<eid>/attendance", methods=["GET"])
def list_enrollment_attendance(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    e = _need(svc.get_enrollment(eid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_enrollment(e))
    items = [a for a in db.attendance.values() if a.get("enrollment_id") == eid]
    return _list(items, serialize.attendance)


@app.route(PREFIX + "/enrollments", methods=["GET"])
def list_enrollments():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    from flask import request
    items = list(db.enrollments.values())
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [e for e in items if e.get("membership_id") == mid]
    return _list(items, serialize.enrollment)


@app.route(PREFIX + "/enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    e = _need(svc.get_enrollment(eid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_enrollment(e))
    status = e.get("status")
    if status == "ENROLLED":
        session = db.sessions.get(e.get("session_id"))
        if session is None or session.get("status") != "SCHEDULED":
            raise errors.err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")
        svc.cancel_enrollment_row(e, promote=True)
    elif status == "WAITLISTED":
        svc.cancel_enrollment_row(e, promote=True)
    else:
        raise errors.err(errors.ERR_INVALID_STATE, "Enrollment cannot be cancelled")
    return success(serialize.enrollment(e), status=200)


@app.route(PREFIX + "/enrollments/<eid>/redeem-makeup", methods=["POST"])
def redeem_makeup(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    e = _need(svc.get_enrollment(eid))
    owning_family = svc.owning_family_of_enrollment(e)
    middleware.require_owner(role, _uid(), owning_family)

    body = get_body()
    target_sid = helpers.require_str(body, "target_session_id")
    if "expected_session_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_session_version is required")
    expected_version = body.get("expected_session_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_session_version must be an integer")

    target = _need(svc.get_session(target_sid))
    membership = db.memberships.get(e.get("membership_id"))
    child = db.children.get(e.get("child_id"))
    target_program = db.programs.get(target.get("program_id"))

    # state: target session must be SCHEDULED (priority 5)
    if target.get("status") != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Target session is not SCHEDULED")

    # age eligibility (priority 9)
    bdate = parse_date(child["birth_date"])
    if not calc.age_eligible(bdate, parse_instant(target["start_at"]),
                             target_program.get("min_age_months"), target_program.get("max_age_months")):
        raise errors.err(errors.ERR_AGE_BAND_MISMATCH, "Child age outside target program band")

    # membership active (priority 11)
    if membership is None or membership.get("status") != "ACTIVE":
        raise errors.err(errors.ERR_MEMBERSHIP_NOT_ACTIVE, "Membership is not ACTIVE")

    # capacity: target must have a free seat (priority 12)
    if target.get("enrolled_count", 0) >= target.get("capacity", 0):
        raise errors.err(errors.ERR_SESSION_FULL, "Target session is at capacity")

    # availability of a usable (non-expired AVAILABLE) credit (priority 14)
    now = clock.now()
    usable = [
        c for c in db.credits.values()
        if c.get("membership_id") == membership["id"]
        and c.get("status") == "AVAILABLE"
        and parse_instant(c["expires_at"]) > now
    ]
    if not usable:
        raise errors.err(errors.ERR_NO_CREDIT_AVAILABLE, "No available makeup credit")

    # OCC (priority 15)
    if expected_version != target.get("version"):
        raise errors.err(errors.ERR_STALE_VERSION, "Stale session version")

    # Select credit: earliest expires_at, then created_at ASC (seq).
    usable.sort(key=lambda c: (c["expires_at"], c.get("_seq", 0)))
    credit = usable[0]
    credit["status"] = "REDEEMED"
    svc.reconcile_credit_balance(membership["id"])
    touch(membership)

    residual = calc.redemption_residual(
        credit.get("issued_tuition_cents", 0), target_program.get("tuition_cents", 0)
    )
    new_enr = stamp_create({
        "child_id": e.get("child_id"),
        "session_id": target_sid,
        "membership_id": membership["id"],
        "kind": "RECURRING",
        "status": "ENROLLED",
        "waitlist_seq": None,
        "redeemed_credit_id": credit["id"],
        "residual_owed_cents": residual,
    })
    db.enrollments[new_enr["id"]] = new_enr
    target["enrolled_count"] = target.get("enrolled_count", 0) + 1
    touch(target)
    return success(serialize.enrollment(new_enr), status=201)


# ============================================================================
# FacilityBooking
# ============================================================================
@app.route(PREFIX + "/facility-bookings", methods=["POST"])
def create_booking():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    body = get_body()
    room_id = helpers.require_str(body, "room_id")
    family_id = helpers.require_str(body, "family_id")
    booking_type = helpers.require_enum(body, "booking_type", ("BIRTHDAY_PARTY", "OPEN_GYM"))
    start_raw = helpers.require_str(body, "start_at")
    end_raw = helpers.require_str(body, "end_at")

    # existence left-to-right: Room, Family (priority 3)
    room = _need(svc.get_room(room_id))
    fam = _need(svc.get_family(family_id))
    middleware.require_owner(role, _uid(), fam["id"])

    # body semantics (priority 4)
    head_count = helpers.optional_int(body, "head_count", 1)
    if head_count < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "head_count must be >= 1")
    start_dt = parse_instant(start_raw)
    end_dt = parse_instant(end_raw)
    if end_dt <= start_dt:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_at must be after start_at")
    if "expected_room_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_room_version is required")
    expected_version = body.get("expected_room_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_room_version must be an integer")

    # room schedule conflict (priority 8)
    if svc.room_conflict_for_booking(room, booking_type, start_dt, end_dt, head_count):
        raise errors.err(errors.ERR_ROOM_SCHEDULE_CONFLICT, "Room schedule conflict")

    # OCC stale-version (priority 15)
    if expected_version != room.get("version"):
        raise errors.err(errors.ERR_STALE_VERSION, "Stale room version")

    row = stamp_create({
        "room_id": room_id,
        "family_id": family_id,
        "booking_type": booking_type,
        "start_at": start_raw,
        "end_at": end_raw,
        "head_count": head_count,
        "status": "CONFIRMED",
    })
    db.bookings[row["id"]] = row
    touch(room)
    return success(serialize.booking(row), status=201)


@app.route(PREFIX + "/facility-bookings", methods=["GET"])
def list_bookings():
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    from flask import request
    items = list(db.bookings.values())
    fid = request.args.get("family_id")
    if fid is not None:
        items = [b for b in items if b.get("family_id") == fid]
    return _list(items, serialize.booking)


@app.route(PREFIX + "/facility-bookings/<bid>", methods=["GET"])
def get_booking_route(bid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    b = _need(svc.get_booking(bid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_booking(b))
    return success(serialize.booking(b), status=200)


@app.route(PREFIX + "/facility-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    b = _need(svc.get_booking(bid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_booking(b))
    if b.get("status") != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Booking is not CONFIRMED")
    b["status"] = "CANCELLED"
    touch(b)
    room = db.rooms.get(b.get("room_id"))
    if room is not None:
        touch(room)
    return success(serialize.booking(b), status=200)


# ============================================================================
# Invoice
# ============================================================================
@app.route(PREFIX + "/invoices/<iid>", methods=["GET"])
def get_invoice_route(iid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    inv = _need(svc.get_invoice(iid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_invoice(inv))
    return success(serialize.invoice(inv), status=200)


@app.route(PREFIX + "/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, ALL_ROLES)
    inv = _need(svc.get_invoice(iid))
    middleware.require_owner(role, _uid(), svc.owning_family_of_invoice(inv))
    # state (priority 5)
    if inv.get("status") != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice is not OPEN")
    # membership active (priority 11)
    membership = db.memberships.get(inv.get("membership_id"))
    if membership is None or membership.get("status") != "ACTIVE":
        raise errors.err(errors.ERR_MEMBERSHIP_NOT_ACTIVE, "Membership is not ACTIVE")
    inv["status"] = "PAID"
    touch(inv)
    return success(serialize.invoice(inv), status=200)


# ============================================================================
# Shared helpers
# ============================================================================
def _uid():
    from flask import request
    return request.headers.get("X-User-ID")


def _list(items, serializer):
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return list_success([serializer(r) for r in page], limit, offset, total)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
