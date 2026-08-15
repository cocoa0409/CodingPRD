"""Call assignments: manual create (backfill), list/get, cancel, mark-served,
activate-backup (PRD §3.3). Validation ladder follows PRD §2.11 priority levels.
"""
from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles, ownership_violation
from response import ok, created, paginate
from services import domain as D
from routes.physicians import get_physician_or_404
from routes.slots import get_slot_or_404

bp = Blueprint("assignments", __name__)

ADMIN = ["SchedulerAdmin"]
ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_assignment_or_404(assignment_id):
    assignment = store.assignments.get(assignment_id)
    if assignment is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "CallAssignment id does not exist")
    return assignment


@bp.route("/api/call-assignments", methods=["POST"])
def create_assignment():
    require_roles(ADMIN)
    body = V.json_body()
    slot_id = V.req_str(body, "slot_id")
    physician_id = V.req_str(body, "physician_id")
    # Existence (priority 5): body ids in declared input order — slot_id first.
    slot = get_slot_or_404(slot_id)
    physician = get_physician_or_404(physician_id)
    program = store.programs.get(slot["program_id"])
    # State (priority 6): program PUBLISHED, then slot OPEN.
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED", 409,
                       "Manual assignment requires the program PUBLISHED")
    if slot["status"] != "OPEN":
        raise ApiError("ERR_SLOT_NOT_OPEN", 409, "Manual assignment requires the slot OPEN")
    # Business safety (priority 8): active physician, unavailability, moonlight cap.
    if physician["status"] != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_INACTIVE", 409,
                       "An INACTIVE physician cannot receive a new commitment")
    if D.has_approved_window_covering(physician["id"], slot["date"]):
        raise ApiError("ERR_UNAVAILABILITY_CONFLICT", 409,
                       "An APPROVED unavailability window covers the slot date")
    D.check_moonlight_cap(physician, slot["date"])
    # Temporal (priority 9): half-open overlap, then slot window not ended.
    if D.has_overlapping_assignment(physician["id"], slot):
        raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                       "Physician holds an assignment whose half-open window overlaps")
    if db.now_logical() >= slot["window_end"]:
        raise ApiError("ERR_SLOT_WINDOW_PASSED", 409, "The slot window has ended")
    # Business constraint (priority 10): specialty match, then STAFF-only.
    if physician["specialty"] != program["service_line"]:
        raise ApiError("ERR_SPECIALTY_MISMATCH", 409,
                       "Physician specialty != program.service_line")
    if physician["employment_type"] != "STAFF":
        raise ApiError("ERR_MANUAL_ASSIGNMENT_STAFF_ONLY", 409,
                       "LOCUM physicians are placed only via the requisition flow")
    # Fiscal gate (priority 11), evaluated last.
    projected = D.compute_projected_pay(program, slot, physician)
    D.check_payroll_budget(program, projected)
    assignment = D.create_assignment(program, slot, physician, "MANUAL")
    db.touch(program)  # program version +1 per endpoint side effects
    return created(assignment)


@bp.route("/api/call-assignments", methods=["GET"])
def list_assignments():
    require_roles(ALL)
    rows = list(store.assignments.values())
    rows = paginate.filter(rows, "program_id")
    rows = paginate.filter(rows, "slot_id")
    rows = paginate.filter(rows, "physician_id")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "origin")
    rows = paginate.filter(rows, "source_swap_id")
    rows = paginate.filter(rows, "source_requisition_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/call-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_roles(ALL)
    return ok(get_assignment_or_404(assignment_id))


@bp.route("/api/call-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    require_roles(ADMIN)
    V.json_body()
    assignment = get_assignment_or_404(assignment_id)
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_ASSIGNMENT_NOT_SCHEDULED", 409,
                       "cancel requires the assignment SCHEDULED")
    program = D.cancel_assignment_cascade(assignment, "ASSIGNMENT_CANCELLED")
    db.touch(program)  # program version +1
    return ok(assignment)


@bp.route("/api/call-assignments/<assignment_id>/mark-served", methods=["POST"])
def mark_served(assignment_id):
    require_roles(ADMIN)
    V.json_body()
    assignment = get_assignment_or_404(assignment_id)
    if assignment["status"] not in ("SCHEDULED", "ACTIVATED"):
        raise ApiError("ERR_ASSIGNMENT_NOT_SERVABLE", 409,
                       "mark-served requires the assignment SCHEDULED or ACTIVATED")
    slot = D.slot_of(assignment)
    program = store.programs.get(assignment["program_id"])
    physician = get_physician_or_404(assignment["physician_id"])
    now = db.now_logical()
    if now < slot["window_end"]:
        raise ApiError("ERR_SERVE_BEFORE_WINDOW_END", 409,
                       "mark-served before slot.window_end")
    was_activated = assignment["status"] == "ACTIVATED"
    amount, prem_hit = D.compute_actual_pay(program, slot, physician, was_activated)
    assignment["status"] = "SERVED"
    assignment["served_at"] = now
    db.touch(assignment)
    slot["status"] = "COVERED"
    db.touch(slot)
    entry = db.new_common({
        "assignment_id": assignment["id"],
        "physician_id": physician["id"],
        "program_id": program["id"],
        "slot_date": slot["date"],
        "call_type": slot["call_type"],
        "date_type": slot["date_type"],
        "base_rate_cents": D.base_rate_for(program, slot),
        "activation_applied": was_activated,
        "premium_applied": prem_hit,
        "amount_cents": amount,
        "status": "ACCRUED",
    })
    store.pay_entries[entry["id"]] = entry
    D.sync_program_totals(program)  # reserve release + accrual increase
    db.touch(program)  # program version +1
    return ok(assignment)


@bp.route("/api/call-assignments/<assignment_id>/activate-backup", methods=["POST"])
def activate_backup(assignment_id):
    uid, role = require_roles(["Physician", "SchedulerAdmin"])
    body = V.json_body()
    assignment = get_assignment_or_404(assignment_id)
    # Ownership (priority 3): a Physician caller must be the assignee.
    if role == "Physician" and assignment["physician_id"] != uid:
        ownership_violation("A Physician may activate only their own backup assignment")
    V.req_str(body, "reason")
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVATABLE", 409,
                       "activate-backup requires the assignment SCHEDULED")
    slot = D.slot_of(assignment)
    now = db.now_logical()
    # Temporal (priority 9): [window_start, window_end + 2h], both bounds inclusive.
    if not (slot["window_start"] <= now <= slot["window_end"] + D.ACTIVATION_GRACE):
        raise ApiError("ERR_ACTIVATION_WINDOW_CLOSED", 409,
                       "Backup activation outside [window_start, window_end + 2h]")
    # Business constraint (priority 10).
    if slot["call_type"] != "BACKUP":
        raise ApiError("ERR_ACTIVATION_REQUIRES_BACKUP_SLOT", 409,
                       "activate-backup requires a BACKUP slot")
    assignment["status"] = "ACTIVATED"
    assignment["activated_at"] = now
    db.touch(assignment)
    return ok(assignment)
