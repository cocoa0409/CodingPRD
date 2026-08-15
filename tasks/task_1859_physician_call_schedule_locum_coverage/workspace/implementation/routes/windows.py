"""Unavailability windows: request/list/get/approve/cancel (PRD §3.2)."""
from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles, ownership_violation
from response import ok, created, paginate
from services import domain as D

bp = Blueprint("windows", __name__)

ADMIN = ["SchedulerAdmin"]
ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_window_or_404(window_id):
    window = store.windows.get(window_id)
    if window is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND", 404, "UnavailabilityWindow id does not exist")
    return window


@bp.route("/api/unavailability-windows", methods=["POST"])
def create_window():
    uid, role = require_roles(["Physician", "SchedulerAdmin"])
    body = V.json_body()
    # Ownership (priority 3): a Physician caller may create only for self.
    if role == "Physician":
        pid = body.get("physician_id")
        if isinstance(pid, str) and pid != uid:
            ownership_violation("A Physician may create unavailability windows only for self")
    physician_id = V.req_str(body, "physician_id")
    start_date = V.req_date(body, "start_date")
    end_date = V.req_date(body, "end_date")
    kind = V.opt_enum(body, "kind", ("VACATION", "CME", "PERSONAL"), "VACATION")
    if D.parse_date(end_date) < D.parse_date(start_date):
        V._bad("end_date must be >= start_date")
    # Existence (priority 5): the referenced physician must exist.
    if physician_id not in store.physicians:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND", 404, "Physician id does not exist")
    window = db.new_common({
        "physician_id": physician_id,
        "start_date": start_date,
        "end_date": end_date,
        "kind": kind,
        "status": "REQUESTED",
    })
    store.windows[window["id"]] = window
    return created(window)


@bp.route("/api/unavailability-windows", methods=["GET"])
def list_windows():
    require_roles(ALL)
    rows = list(store.windows.values())
    rows = paginate.filter(rows, "physician_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/unavailability-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    require_roles(ALL)
    return ok(get_window_or_404(window_id))


@bp.route("/api/unavailability-windows/<window_id>/approve", methods=["POST"])
def approve_window(window_id):
    require_roles(ADMIN)
    V.json_body()
    window = get_window_or_404(window_id)
    if window["status"] != "REQUESTED":
        raise ApiError("ERR_WINDOW_NOT_REQUESTED", 409, "approve requires the window REQUESTED")
    start = D.parse_date(window["start_date"])
    end = D.parse_date(window["end_date"])
    # Business safety (priority 8): no ACTIVATED/SERVED assignment inside the window.
    for a in D.assignments_of_physician(window["physician_id"], ("ACTIVATED", "SERVED")):
        slot = D.slot_of(a)
        if slot is not None and start <= D.parse_date(slot["date"]) <= end:
            raise ApiError("ERR_WINDOW_COVERS_SERVED_ASSIGNMENT", 409,
                           "Window would cover an ACTIVATED or SERVED assignment")
    # Temporal (priority 9): no other APPROVED window overlapping under
    # closed-interval semantics (touching dates overlap).
    for w in store.windows.values():
        if w["id"] == window["id"] or w["physician_id"] != window["physician_id"] \
                or w["status"] != "APPROVED":
            continue
        if not (D.parse_date(w["end_date"]) < start or D.parse_date(w["start_date"]) > end):
            raise ApiError("ERR_WINDOW_OVERLAP", 409,
                           "Another APPROVED window overlaps under closed-interval semantics")
    # Cascade: cancel conflicting SCHEDULED assignments (slots reopen, gaps open,
    # reserve releases, referencing non-terminal swaps cancel).
    for a in D.assignments_of_physician(window["physician_id"], ("SCHEDULED",)):
        slot = D.slot_of(a)
        if slot is not None and start <= D.parse_date(slot["date"]) <= end:
            D.cancel_assignment_cascade(a, "ASSIGNMENT_CANCELLED")
    window["status"] = "APPROVED"
    db.touch(window)
    return ok(window)


@bp.route("/api/unavailability-windows/<window_id>/cancel", methods=["POST"])
def cancel_window(window_id):
    uid, role = require_roles(["Physician", "SchedulerAdmin"])
    V.json_body()
    window = get_window_or_404(window_id)
    if role == "Physician" and window["physician_id"] != uid:
        ownership_violation("A Physician may cancel only their own unavailability windows")
    if window["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError("ERR_WINDOW_NOT_CANCELLABLE", 409,
                       "cancel requires the window REQUESTED or APPROVED")
    # No side effects: cancelling an APPROVED window does not restore assignments.
    window["status"] = "CANCELLED"
    db.touch(window)
    return ok(window)
