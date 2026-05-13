"""Reservation list/get/cancel endpoints."""
from flask import Blueprint, request, g

import db
from clock import now
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.reservations_svc import cancel_reservation_cascade
from services.util import parse_dt
from datetime import timedelta


bp = Blueprint("reservations", __name__)


def _serialize(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.route("/shuttle/reservations", methods=["GET"])
@require_auth(roles={"Dispatcher", "Employee", "Auditor"})
def list_reservations():
    limit, offset = get_pagination()
    emp = request.args.get("employee_id")
    rsid = request.args.get("run_sheet_id")
    status = request.args.get("status")
    items = list(db.reservations.values())
    # If Employee, restrict to own reservations
    if g.user_role == "Employee":
        items = [r for r in items if r.get("employee_id") == g.user_id]
    if emp:
        items = [r for r in items if r.get("employee_id") == emp]
    if rsid:
        items = [r for r in items if r.get("run_sheet_id") == rsid]
    if status:
        items = [r for r in items if r.get("status") == status]
    items.sort(key=lambda r: r.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize(r) for r in page], limit, offset, len(items))


@bp.route("/shuttle/reservations/<rid>", methods=["GET"])
@require_auth(roles={"Dispatcher", "Employee", "Auditor"})
def get_reservation(rid):
    r = db.reservations.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Reservation not found")
    if g.user_role == "Employee" and r.get("employee_id") != g.user_id:
        raise err("ERR_NOT_FOUND", "Reservation not found")
    return success(_serialize(r))


@bp.route("/shuttle/reservations/<rid>", methods=["DELETE"])
@require_auth(roles={"Employee", "Dispatcher"})
def cancel_reservation(rid):
    # PRD §2.8 priority:
    #   4. Path-id existence (ERR_NOT_FOUND).
    r = db.reservations.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Reservation not found")

    #   3. RBAC / ownership check (ERR_FORBIDDEN) — Employee can only cancel
    #      their own reservation per PRD §3.6 ("Cancellation is initiated by
    #      the owning Employee or by a Dispatcher").
    if g.user_role == "Employee":
        if r.get("employee_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Cannot cancel another employee's reservation")

    #   6. State-machine eligibility (ERR_INVALID_STATE /
    #      ERR_RESERVATION_ALREADY_CHECKED_IN). Per PRD §2.8 this precedes
    #      business-temporal validations like ERR_CANCEL_WINDOW_CLOSED.
    #      Per PRD §3.6, only CONFIRMED and WAITLISTED reservations may be
    #      cancelled; CHECKED_IN surfaces as ERR_RESERVATION_ALREADY_CHECKED_IN
    #      (the race-loser error); other terminal states surface as
    #      ERR_INVALID_STATE (idempotent re-cancel and terminal states).
    status = r.get("status")
    if status == "CHECKED_IN":
        raise err("ERR_RESERVATION_ALREADY_CHECKED_IN",
                  "Reservation already checked in")
    if status not in ("CONFIRMED", "WAITLISTED"):
        raise err("ERR_INVALID_STATE",
                  f"Reservation in status {status} cannot be cancelled")

    #   7. Endpoint-specific business validations (ERR_CANCEL_WINDOW_CLOSED)
    #      — only applies to Employee-initiated cancellation per PRD §3.6.
    if g.user_role == "Employee":
        rs = db.run_sheets.get(r.get("run_sheet_id"))
        if rs:
            sd = parse_dt(rs["scheduled_departure"])
            if not (now() <= sd - timedelta(minutes=15)):
                raise err("ERR_CANCEL_WINDOW_CLOSED",
                          "Cancel window has closed")

    cancel_reservation_cascade(r, actor_role=g.user_role, actor_id=g.user_id,
                                cause="manual_cancel")
    return success(_serialize(r))
