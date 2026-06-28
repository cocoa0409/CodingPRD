"""Time-entry and expense-entry capture, listing, and write-down."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from common import (get_json_body, stamp_create, touch, require_int,
                    require_datetime, paginate)
from clock import parse_iso8601
from middleware import authenticate, require_role
from middleware import ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY
from response import object_response, array_response
import serializers
from services import resolve_rate, time_entry_amount, latest_conflict_check

bp = Blueprint("entries", __name__)

ALL_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}
CAPTURE_ROLES = {ROLE_ATTORNEY, ROLE_BILLING_CLERK, ROLE_PLATFORM_ADMIN}


def _conflict_gate(matter):
    latest = latest_conflict_check(matter["id"])
    if latest is None or latest["result"] not in ("CLEAR", "WAIVED"):
        raise errors.conflict_not_cleared()


# ---------------- Time entries ----------------

@bp.route("/firm/time-entries", methods=["POST"])
def create_time_entry():
    _uid, role = authenticate()
    require_role(role, CAPTURE_ROLES)
    body = get_json_body()

    matter_id = body.get("matter_id")
    timekeeper_id = body.get("timekeeper_id")
    if matter_id is None or not isinstance(matter_id, str):
        raise errors.invalid_request("Missing required field 'matter_id'.")
    if timekeeper_id is None or not isinstance(timekeeper_id, str):
        raise errors.invalid_request("Missing required field 'timekeeper_id'.")
    worked_at = require_datetime(body, "worked_at")
    minutes = require_int(body, "minutes", positive=True)
    task_code = body.get("utbms_task_code")
    activity_code = body.get("utbms_activity_code")
    if task_code is None or not isinstance(task_code, str):
        raise errors.invalid_request("Missing required field 'utbms_task_code'.")
    if activity_code is None or not isinstance(activity_code, str):
        raise errors.invalid_request("Missing required field 'utbms_activity_code'.")

    # Existence (priority 3): matter, timekeeper, billing codes (by code value).
    matter = db.matters.get(matter_id)
    if matter is None:
        raise errors.not_found("Matter not found.")
    timekeeper = db.timekeepers.get(timekeeper_id)
    if timekeeper is None:
        raise errors.not_found("Timekeeper not found.")
    task_bc = _find_code(task_code)
    if task_bc is None:
        raise errors.not_found("utbms_task_code not found.")
    activity_bc = _find_code(activity_code)
    if activity_bc is None:
        raise errors.not_found("utbms_activity_code not found.")

    # Referential kind checks (priority 4).
    if task_bc["kind"] != "TASK":
        raise errors.code_kind_mismatch("utbms_task_code must reference a TASK code.")
    if activity_bc["kind"] != "ACTIVITY":
        raise errors.code_kind_mismatch("utbms_activity_code must reference an ACTIVITY code.")

    # State (priority 5): matter OPEN for capture.
    if matter["status"] != "OPEN":
        raise errors.invalid_state("Time may only be captured against an OPEN matter.")

    # Conflict gate (priority 8).
    _conflict_gate(matter)

    # Time-entry overlap (priority 11).
    with db.LOCK:
        new_start = worked_at
        new_end = worked_at + timedelta(minutes=minutes)
        for te in db.time_entries.values():
            if te["timekeeper_id"] != timekeeper_id:
                continue
            if te["status"] == "WRITTEN_DOWN":
                continue
            ex_start = parse_iso8601(te["worked_at"])
            ex_end = ex_start + timedelta(minutes=te["minutes"])
            # Half-open overlap: [a,b) overlaps [c,d) iff a < d and c < b.
            if new_start < ex_end and ex_start < new_end:
                raise errors.time_overlap()

        # Timekeeper active (priority 16).
        if not timekeeper["is_active"]:
            raise errors.timekeeper_inactive()

        client = db.clients.get(matter["client_id"])
        resolved = resolve_rate(matter, client, timekeeper)
        amount = time_entry_amount(resolved, minutes)

        rec = {
            "matter_id": matter_id,
            "timekeeper_id": timekeeper_id,
            "worked_at": body["worked_at"],
            "minutes": minutes,
            "utbms_task_code": task_code,
            "utbms_activity_code": activity_code,
            "resolved_rate_cents": resolved,
            "billable_amount_cents": amount,
            "status": "CAPTURED",
            "invoice_id": None,
        }
        stamp_create(rec)
        db.time_entries[rec["id"]] = rec
        matter["wip_fees_cents"] += amount
        touch(matter)
    return object_response(serializers.s_time_entry(rec), status=201)


@bp.route("/firm/time-entries/<tid>", methods=["GET"])
def get_time_entry(tid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.time_entries.get(tid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_time_entry(rec))


@bp.route("/firm/time-entries", methods=["GET"])
def list_time_entries():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.time_entries.values())
    for key in ("matter_id", "timekeeper_id", "invoice_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_time_entry(t) for t in page], limit, offset, total)


@bp.route("/firm/time-entries/<tid>/write-down", methods=["POST"])
def write_down_time_entry(tid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY})
    rec = db.time_entries.get(tid)
    if rec is None:
        raise errors.not_found()
    if rec["status"] != "CAPTURED":
        raise errors.invalid_state("Only a CAPTURED time entry may be written down.")
    with db.LOCK:
        rec["status"] = "WRITTEN_DOWN"
        touch(rec)
        matter = db.matters.get(rec["matter_id"])
        if matter is not None:
            matter["wip_fees_cents"] -= rec["billable_amount_cents"]
            touch(matter)
    return object_response(serializers.s_time_entry(rec))


# ---------------- Expense entries ----------------

@bp.route("/firm/expense-entries", methods=["POST"])
def create_expense_entry():
    _uid, role = authenticate()
    require_role(role, CAPTURE_ROLES)
    body = get_json_body()

    matter_id = body.get("matter_id")
    if matter_id is None or not isinstance(matter_id, str):
        raise errors.invalid_request("Missing required field 'matter_id'.")
    expense_code = body.get("utbms_expense_code")
    if expense_code is None or not isinstance(expense_code, str):
        raise errors.invalid_request("Missing required field 'utbms_expense_code'.")
    amount_cents = require_int(body, "amount_cents", positive=True)

    matter = db.matters.get(matter_id)
    if matter is None:
        raise errors.not_found("Matter not found.")
    code_bc = _find_code(expense_code)
    if code_bc is None:
        raise errors.not_found("utbms_expense_code not found.")
    if code_bc["kind"] != "EXPENSE":
        raise errors.code_kind_mismatch("utbms_expense_code must reference an EXPENSE code.")
    if matter["status"] != "OPEN":
        raise errors.invalid_state("Expense may only be captured against an OPEN matter.")
    _conflict_gate(matter)

    with db.LOCK:
        rec = {
            "matter_id": matter_id,
            "utbms_expense_code": expense_code,
            "amount_cents": amount_cents,
            "status": "CAPTURED",
            "invoice_id": None,
        }
        stamp_create(rec)
        db.expense_entries[rec["id"]] = rec
        matter["wip_expenses_cents"] += amount_cents
        touch(matter)
    return object_response(serializers.s_expense_entry(rec), status=201)


@bp.route("/firm/expense-entries/<eid>", methods=["GET"])
def get_expense_entry(eid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.expense_entries.get(eid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_expense_entry(rec))


@bp.route("/firm/expense-entries", methods=["GET"])
def list_expense_entries():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.expense_entries.values())
    for key in ("matter_id", "invoice_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_expense_entry(e) for e in page], limit, offset, total)


def _find_code(code_str):
    for bc in db.billing_codes.values():
        if bc["code"] == code_str:
            return bc
    return None
