"""Permit endpoints: applications, lifecycle events, renewals."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import fmt_dt, fmt_date, now, parse_date, parse_dt, touch
from domain import (
    NON_TERMINAL_PERMIT_STATUSES, get_or_404, serialize_permit, serialize_renewal,
    lot_bookable, lot_available, open_cycle_for_program, post_permit_fee,
    truncate_pending_fee, suspend_permit, reinstate_permit, revoke_permit,
    promotion_pass, gross_fee_for_permit, permit_program, permit_employee,
    employee_standing, unpaid_violation_count,
)
from errors import raise_error
from middleware import require_roles, get_auth
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("permits", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


@bp.route("/parking/permits", methods=["POST"])
def create_permit():
    user_id, role = get_auth()
    if role not in ("Employee", "ParkingAdmin"):
        raise_error("ERR_FORBIDDEN_ROLE", "Role not allowed on this endpoint")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("employee_id", "lot_id", "vehicle_plate"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    # Priority 3: Employee body-ownership
    if role == "Employee" and body["employee_id"] != user_id:
        raise_error("ERR_NOT_RESOURCE_OWNER", "employee_id must equal the caller's X-User-ID")
    # Priority 4: existence (body FKs)
    employee = get_or_404(db.employees, body["employee_id"])
    lot = get_or_404(db.lots, body["lot_id"])
    program = db.programs.get(lot["program_id"])
    # Priority 6: posture gate + lot bookable
    if program["posture"] in ("PROGRAM_FROZEN", "PROGRAM_CLOSED"):
        raise_error("ERR_PROGRAM_FROZEN", "Program posture blocks new permit applications")
    if not lot_bookable(lot):
        raise_error("ERR_LOT_NOT_BOOKABLE", "Lot is not bookable")
    # Priority 9: one non-terminal permit per employee
    for p in db.permits.values():
        if p["employee_id"] == employee["id"] and p["status"] in NON_TERMINAL_PERMIT_STATUSES:
            raise_error("ERR_DUPLICATE_ACTIVE_PERMIT", "Employee already holds a non-terminal permit")
    rec = db.new_record({
        "employee_id": employee["id"],
        "lot_id": lot["id"],
        "vehicle_plate": body["vehicle_plate"],
        "queue_shift_pattern": employee["shift_pattern"],
        "status": "REQUESTED",
        "offered_at": None,
        "offer_expires_at": None,
        "activated_at": None,
        "suspended_at": None,
        "suspension_reason": None,
        "monthly_fee_cents": None,
        "term_end": None,
    })
    db.permits[rec["id"]] = rec
    # Synchronous evaluation: OFFERED if available_slots >= 1 else WAITLISTED
    if lot_available(lot) >= 1:
        rec["status"] = "OFFERED"
        rec["offered_at"] = fmt_dt(now())
        rec["offer_expires_at"] = fmt_dt(now() + timedelta(hours=program["waitlist_offer_ttl_hours"]))
    else:
        rec["status"] = "WAITLISTED"
    touch(rec)
    return success_object(serialize_permit(rec), 201)


@bp.route("/parking/permits/<pid>", methods=["GET"])
def get_permit(pid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.permits, pid)
    return success_object(serialize_permit(rec), 200)


@bp.route("/parking/permits", methods=["GET"])
def list_permits():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    employee_id = request.args.get("employee_id")
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    items = sorted(db.permits.values(), key=lambda p: p["created_at"])
    out = []
    for p in items:
        if employee_id is not None and p["employee_id"] != employee_id:
            continue
        if lot_id is not None and p["lot_id"] != lot_id:
            continue
        if status is not None and p["status"] != status:
            continue
        out.append(serialize_permit(p))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


# ---------------------------------------------------------------------------
# Permit lifecycle events
# ---------------------------------------------------------------------------

@bp.route("/parking/permits/<pid>/events", methods=["POST"])
def permit_event(pid):
    user_id, role = get_auth()
    if role not in ("Employee", "ParkingAdmin"):
        raise_error("ERR_FORBIDDEN_ROLE", "Role not allowed on this endpoint")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    valid_events = ("ACCEPT", "DECLINE", "CANCEL", "SUSPEND", "REINSTATE", "REVOKE")
    if event_type not in valid_events:
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    # Priority 2: event-verb role restrictions
    if event_type in ("SUSPEND", "REINSTATE", "REVOKE") and role != "ParkingAdmin":
        raise_error("ERR_FORBIDDEN_ROLE", "This event is ParkingAdmin-only")
    # Priority 4: existence, then path-ownership
    permit = get_or_404(db.permits, pid)
    if role == "Employee" and permit["employee_id"] != user_id:
        raise_error("ERR_NOT_RESOURCE_OWNER", "Permit belongs to a different employee")

    if event_type == "ACCEPT":
        return _accept(permit)
    if event_type == "DECLINE":
        return _decline(permit)
    if event_type == "CANCEL":
        return _cancel(permit)
    if event_type == "SUSPEND":
        return _suspend(permit, body)
    if event_type == "REINSTATE":
        return _reinstate(permit)
    if event_type == "REVOKE":
        return _revoke(permit)
    raise_error("ERR_INVALID_REQUEST", "invalid event_type")


def _accept(permit):
    # Priority 6: state gate
    if permit["status"] != "OFFERED":
        raise_error("ERR_PERMIT_NOT_OFFERED", "ACCEPT requires the permit to be OFFERED")
    employee = permit_employee(permit)
    program = permit_program(permit)
    # Priority 7: compliance
    if employee["employment_status"] != "ACTIVE":
        raise_error("ERR_EMPLOYEE_NOT_ACTIVE", "Employee is not ACTIVE")
    # Priority 8: temporal — expiry instant itself remains acceptable
    exp = parse_dt(permit["offer_expires_at"])
    if exp is not None and now() > exp:
        raise_error("ERR_OFFER_EXPIRED", "Offer has expired")
    # Priority 10: fiscal gates
    if employee_standing(employee["id"]) != "GOOD_STANDING":
        raise_error("ERR_BILLING_HOLD", "Employee has an outstanding balance")
    cycle = open_cycle_for_program(program["id"])
    if cycle is None:
        raise_error("ERR_NO_OPEN_BILLING_CYCLE", "No OPEN billing cycle for the program")
    # Side effects
    permit["status"] = "ACTIVE"
    permit["activated_at"] = fmt_dt(now())
    activation_date = now().date()
    try:
        permit["term_end"] = fmt_date(activation_date.replace(year=activation_date.year + 1))
    except ValueError:  # Feb 29 -> Feb 28 next year
        permit["term_end"] = fmt_date(activation_date.replace(year=activation_date.year + 1, day=28))
    permit["monthly_fee_cents"] = gross_fee_for_permit(permit)
    touch(permit)
    period_end = parse_date(cycle["period_end"])
    post_permit_fee(permit, cycle, activation_date, period_end, is_truncation=False)
    return success_object(serialize_permit(permit), 200)


def _decline(permit):
    if permit["status"] != "OFFERED":
        raise_error("ERR_INVALID_STATE", "DECLINE requires the permit to be OFFERED")
    permit["status"] = "DECLINED"
    touch(permit)
    promotion_pass(permit["lot_id"])
    return success_object(serialize_permit(permit), 200)


def _cancel(permit):
    if permit["status"] not in ("REQUESTED", "WAITLISTED", "OFFERED"):
        raise_error("ERR_INVALID_STATE", "CANCEL requires REQUESTED, WAITLISTED, or OFFERED")
    was_offered = permit["status"] == "OFFERED"
    permit["status"] = "CANCELLED"
    touch(permit)
    if was_offered:
        promotion_pass(permit["lot_id"])
    return success_object(serialize_permit(permit), 200)


def _suspend(permit, body):
    if permit["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE", "SUSPEND requires the permit to be ACTIVE")
    reason = body.get("suspension_reason", "ADMIN")
    if reason is None:
        reason = "ADMIN"
    if reason not in ("ADMIN", "BILLING_HOLD"):
        raise_error("ERR_INVALID_REQUEST", "suspension_reason must be ADMIN or BILLING_HOLD")
    suspend_permit(permit, reason)
    return success_object(serialize_permit(permit), 200)


def _reinstate(permit):
    if permit["status"] != "SUSPENDED":
        raise_error("ERR_INVALID_STATE", "REINSTATE requires the permit to be SUSPENDED")
    program = permit_program(permit)
    lot = db.lots.get(permit["lot_id"])
    employee = permit_employee(permit)
    reason = permit.get("suspension_reason")
    if reason == "VIOLATION_THRESHOLD":
        if unpaid_violation_count(permit["id"]) >= program["violation_suspension_threshold"]:
            raise_error("ERR_REINSTATE_BLOCKED", "Unpaid violation count still at or above threshold")
    elif reason == "LOT_CLOSURE":
        if not lot_bookable(lot):
            raise_error("ERR_REINSTATE_BLOCKED", "Lot is not bookable")
    elif reason in ("BILLING_HOLD", "ADMIN"):
        if employee_standing(employee["id"]) != "GOOD_STANDING":
            raise_error("ERR_REINSTATE_BLOCKED", "Employee standing is not GOOD_STANDING")
    cycle = open_cycle_for_program(program["id"])
    if cycle is None:
        raise_error("ERR_NO_OPEN_BILLING_CYCLE", "No OPEN billing cycle for the program")
    reinstate_permit(permit)
    return success_object(serialize_permit(permit), 200)


def _revoke(permit):
    if permit["status"] in ("REVOKED", "DECLINED", "EXPIRED", "CANCELLED", "REQUESTED"):
        raise_error("ERR_INVALID_STATE", "REVOKE not allowed from the current status")
    revoke_permit(permit, run_promotion=True)
    return success_object(serialize_permit(permit), 200)


# ---------------------------------------------------------------------------
# Renewals
# ---------------------------------------------------------------------------

@bp.route("/parking/permits/<pid>/renewals", methods=["POST"])
def create_renewal(pid):
    user_id, role = get_auth()
    if role not in ("Employee", "ParkingAdmin"):
        raise_error("ERR_FORBIDDEN_ROLE", "Role not allowed on this endpoint")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body.get("expected_permit_version") is None:
        raise_error("ERR_INVALID_REQUEST", "expected_permit_version is required")
    if not isinstance(body["expected_permit_version"], int) or isinstance(body["expected_permit_version"], bool):
        raise_error("ERR_INVALID_REQUEST", "expected_permit_version must be an integer")
    # Priority 4: existence + path ownership
    permit = get_or_404(db.permits, pid)
    if role == "Employee" and permit["employee_id"] != user_id:
        raise_error("ERR_NOT_RESOURCE_OWNER", "Permit belongs to a different employee")
    # Priority 5: OCC
    if body["expected_permit_version"] != permit["version"]:
        raise_error("ERR_STALE_PERMIT_VERSION", "expected_permit_version does not match Permit.version")
    # Priority 6: posture gate
    program = permit_program(permit)
    if program["posture"] in ("PROGRAM_FROZEN", "PROGRAM_CLOSED"):
        raise_error("ERR_PROGRAM_FROZEN", "Program posture blocks renewal creation")
    # Priority 7: compliance
    employee = permit_employee(permit)
    if employee["employment_status"] != "ACTIVE":
        raise_error("ERR_EMPLOYEE_NOT_ACTIVE", "Employee is not ACTIVE")
    # Supersede existing PENDING renewals of the same permit
    for r in db.renewals.values():
        if r["permit_id"] == permit["id"] and r["status"] == "PENDING":
            r["status"] = "SUPERSEDED"
            touch(r)
    rec = db.new_record({
        "permit_id": permit["id"],
        "status": "PENDING",
        "requested_at": fmt_dt(now()),
        "decided_by": None,
    })
    db.renewals[rec["id"]] = rec
    touch(permit)  # increments Permit.version by 1
    return success_object(serialize_renewal(rec), 201)


@bp.route("/parking/permits/<pid>/renewals", methods=["GET"])
def list_renewals(pid):
    require_roles(*ALL_ROLES)
    permit = get_or_404(db.permits, pid)
    limit, offset = parse_pagination()
    items = sorted(
        (r for r in db.renewals.values() if r["permit_id"] == permit["id"]),
        key=lambda r: r["created_at"],
    )
    out = [serialize_renewal(r) for r in items]
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/renewals/<rid>/decide", methods=["POST"])
def decide_renewal(rid):
    user_id, role = require_roles("ParkingAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_error("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT")
    renewal = get_or_404(db.renewals, rid)
    if renewal["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE", "Renewal is not PENDING")
    permit = db.permits.get(renewal["permit_id"])
    if decision == "APPROVE":
        if permit is None or permit["status"] != "ACTIVE":
            raise_error("ERR_INVALID_STATE", "APPROVE requires the permit to be ACTIVE")
        renewal["status"] = "APPROVED"
        renewal["decided_by"] = user_id
        touch(renewal)
        # Extend term_end by 12 months
        term = parse_date(permit["term_end"])
        try:
            new_term = term.replace(year=term.year + 1)
        except ValueError:
            new_term = term.replace(year=term.year + 1, day=28)
        permit["term_end"] = fmt_date(new_term)
        touch(permit)
    else:
        renewal["status"] = "REJECTED"
        renewal["decided_by"] = user_id
        touch(renewal)
    return success_object(serialize_renewal(renewal), 200)
