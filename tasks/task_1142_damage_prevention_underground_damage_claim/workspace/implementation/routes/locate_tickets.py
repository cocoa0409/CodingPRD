"""LocateTicket endpoints."""

from flask import Blueprint, request

import clock
from db import db
from errors import (err_invalid_state, err_not_found, err_ownership,
                    err_program_suspended, err_window_conflict,
                    err_window_invalid)
from middleware import require_roles
from serializers import ticket_out
from util import (get_pagination, new_id, paginate, parse_body, parse_dt,
                  require_string, success_envelope)

bp = Blueprint("locate_tickets", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; touching boundaries do not overlap."""
    return a_start < b_end and b_start < a_end


def _check_overlap(excavator_id, address, start, end, exclude_id=None):
    for t in db.locate_tickets.values():
        if t["excavator_id"] != excavator_id or t["dig_site_address"] != address:
            continue
        if t["status"] != "OPEN":
            continue
        if exclude_id is not None and t["id"] == exclude_id:
            continue
        if _overlaps(start, end, t["work_start_at"], t["work_end_at"]):
            raise err_window_conflict()


@bp.route("/damage-recovery/locate-tickets", methods=["POST"])
def create_ticket():
    user_id, _ = require_roles("Excavator")
    body = parse_body(required_fields=["excavator_id", "dig_site_address", "work_start_at", "work_end_at"])
    excavator_id = require_string(body["excavator_id"], "excavator_id")
    if excavator_id != user_id:
        raise err_ownership("excavator_id must equal X-User-ID")
    exc = db.excavators.get(excavator_id)
    if exc is None:
        raise err_not_found("excavator not found")
    address = require_string(body["dig_site_address"], "dig_site_address")
    work_start = parse_dt(body["work_start_at"], "work_start_at")
    work_end = parse_dt(body["work_end_at"], "work_end_at")
    if work_end <= work_start:
        raise err_window_invalid("work_end_at must be strictly after work_start_at")
    _check_overlap(excavator_id, address, work_start, work_end)
    if exc["program_status"] == "SUSPENDED":
        raise err_program_suspended()
    now = clock.get_current_utc()
    tid = new_id()
    ticket = {
        "id": tid,
        "excavator_id": excavator_id,
        "dig_site_address": address,
        "work_start_at": work_start,
        "work_end_at": work_end,
        "ticket_number": db.next_ticket_number(),
        "status": "OPEN",
        "renewal_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.locate_tickets[tid] = ticket
    return success_envelope(ticket_out(ticket), "object", 201)


@bp.route("/damage-recovery/locate-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    require_roles(*ALL_ROLES)
    t = db.locate_tickets.get(tid)
    if t is None:
        raise err_not_found("locate ticket not found")
    return success_envelope(ticket_out(t), "object", 200)


@bp.route("/damage-recovery/locate-tickets", methods=["GET"])
def list_tickets():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.locate_tickets.values())
    excavator_id = request.args.get("excavator_id")
    status = request.args.get("status")
    address = request.args.get("dig_site_address")
    if excavator_id is not None:
        items = [t for t in items if t["excavator_id"] == excavator_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if address is not None:
        items = [t for t in items if t["dig_site_address"] == address]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([ticket_out(t) for t in page], "array", 200, meta)


@bp.route("/damage-recovery/locate-tickets/<tid>/renew", methods=["POST"])
def renew_ticket(tid):
    user_id, _ = require_roles("Excavator")
    t = db.locate_tickets.get(tid)
    if t is None:
        raise err_not_found("locate ticket not found")
    if t["excavator_id"] != user_id:
        raise err_ownership("ticket belongs to another excavator")
    body = parse_body(required_fields=["new_work_end_at"])
    new_end = parse_dt(body["new_work_end_at"], "new_work_end_at")
    if t["status"] != "OPEN":
        raise err_invalid_state("only an OPEN ticket can be renewed")
    if new_end <= t["work_end_at"]:
        raise err_window_invalid("new_work_end_at must be strictly after current work_end_at")
    _check_overlap(t["excavator_id"], t["dig_site_address"], t["work_start_at"], new_end, exclude_id=t["id"])
    t["work_end_at"] = new_end
    t["renewal_count"] += 1
    t["updated_at"] = clock.get_current_utc()
    t["version"] += 1
    return success_envelope(ticket_out(t), "object", 200)
