"""Run-sheet endpoints (including delays, dispatch-substitute, statistics, reservations, check-in)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services.run_sheets_svc import (
    create_run_sheet, start_boarding, depart, complete, resume,
    cancel_run_sheet_cascade, report_delay, dispatch_substitute,
    recompute_capacity_remaining,
)
from services.reservations_svc import create_reservation, check_in_reservation


bp = Blueprint("run_sheets", __name__)


def _serialize(rs):
    out = {k: v for k, v in rs.items() if not k.startswith("_")}
    return out


def _refresh(rs):
    recompute_capacity_remaining(rs)
    return rs


@bp.route("/shuttle/run-sheets", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def create_rs():
    body = get_json_body()
    rs = create_run_sheet(body, actor_role=g.user_role, actor_id=g.user_id)
    return success(_serialize(rs), status=201)


@bp.route("/shuttle/run-sheets", methods=["GET"])
@require_auth(roles={"Dispatcher", "Driver", "Employee", "Auditor"})
def list_rs():
    limit, offset = get_pagination()
    route_id = request.args.get("route_id")
    scheduled_date = request.args.get("scheduled_date")
    status_filter = request.args.get("status")
    items = list(db.run_sheets.values())
    if route_id:
        items = [r for r in items if r.get("route_id") == route_id]
    if scheduled_date:
        items = [r for r in items if (r.get("scheduled_date") or "").startswith(scheduled_date[:10])]
    if status_filter:
        items = [r for r in items if r.get("status") == status_filter]
    items.sort(key=lambda r: r.get("_seq", 0))
    for it in items:
        _refresh(it)
    page = items[offset:offset + limit]
    return success_list([_serialize(r) for r in page], limit, offset, len(items))


@bp.route("/shuttle/run-sheets/<rid>", methods=["GET"])
@require_auth(roles={"Dispatcher", "Driver", "Employee", "Auditor"})
def get_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/start-boarding", methods=["POST"])
@require_auth(roles={"Dispatcher", "Driver"})
def start_boarding_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    start_boarding(rs, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/depart", methods=["POST"])
@require_auth(roles={"Dispatcher", "Driver"})
def depart_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    depart(rs, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/complete", methods=["POST"])
@require_auth(roles={"Dispatcher", "Driver"})
def complete_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    complete(rs, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/cancel", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def cancel_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    cancel_run_sheet_cascade(rs, actor_role=g.user_role, actor_id=g.user_id,
                             cause="dispatcher_cancelled")
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/delays", methods=["POST"])
@require_auth(roles={"Dispatcher", "Driver"})
def delays_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    body = get_json_body()
    ev = report_delay(rs, body, actor_role=g.user_role, actor_id=g.user_id)
    return success({k: v for k, v in ev.items() if not k.startswith("_")}, status=201)


@bp.route("/shuttle/run-sheets/<rid>/resume", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def resume_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    resume(rs, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/dispatch-substitute", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def dispatch_sub(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    body = get_json_body()
    dispatch_substitute(rs, body, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success(_serialize(rs))


@bp.route("/shuttle/run-sheets/<rid>/statistics", methods=["GET"])
@require_auth(roles={"Dispatcher", "Auditor"})
def stats_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    actual = sum(1 for rr in db.ridership_records.values()
                 if rr.get("run_sheet_id") == rid)
    expected = sum(1 for r in db.reservations.values()
                   if r.get("run_sheet_id") == rid
                   and r.get("status") in ("CHECKED_IN", "COMPLETED", "NO_SHOW"))
    no_show = sum(1 for r in db.reservations.values()
                  if r.get("run_sheet_id") == rid and r.get("status") == "NO_SHOW")
    denom = max(expected, 1)
    raw_rate = Decimal(actual) / Decimal(denom)
    rate = raw_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return success({
        "run_sheet_id": rid,
        "ridership_actual": actual,
        "ridership_expected": expected,
        "no_show_count": no_show,
        "match_rate": float(rate),
    })


# Reservations under run-sheets
@bp.route("/shuttle/run-sheets/<rid>/reservations", methods=["POST"])
@require_auth(roles={"Employee", "Dispatcher"})
def create_reservation_under_rs(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    body = get_json_body()
    # If Employee, force employee_id to X-User-ID per PRD §2.1
    if g.user_role == "Employee":
        body["employee_id"] = g.user_id
    res = create_reservation(rs, body, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success({k: v for k, v in res.items() if not k.startswith("_")}, status=201)


# Check-in under run-sheets
@bp.route("/shuttle/run-sheets/<rid>/check-in", methods=["POST"])
@require_auth(roles={"Driver", "Dispatcher"})
def check_in(rid):
    rs = db.run_sheets.get(rid)
    if not rs:
        raise err("ERR_NOT_FOUND", "Run-sheet not found")
    body = get_json_body()
    rr = check_in_reservation(rs, body, actor_role=g.user_role, actor_id=g.user_id)
    _refresh(rs)
    return success({k: v for k, v in rr.items() if not k.startswith("_")}, status=201)
