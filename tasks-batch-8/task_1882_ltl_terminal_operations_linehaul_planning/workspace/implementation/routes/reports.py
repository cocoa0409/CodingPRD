"""Service standard report endpoints (PRD section 3.7)."""
from flask import Blueprint, request

import db
from errors import err_invalid_request
from middleware import require_roles
from response import success, success_list
from routes.common import body_json, get_path, new_record, paginate, ser_report
from services.calculations import ON_TIME_TARGET_PCT, on_time_pct
from services.timeutil import day_window_utc, parse_date

bp = Blueprint("reports", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher")


@bp.route("/ltl/terminals/<terminalId>/service-standard-reports", methods=["POST"])
@require_roles("TerminalAdmin")
def create_report(terminalId):
    terminal = get_path("terminals", terminalId)
    body = body_json()
    report_date = body.get("report_date")
    try:
        parse_date(report_date)
    except (ValueError, TypeError):
        raise err_invalid_request("report_date must be a YYYY-MM-DD date")
    window_start, window_end = day_window_utc(terminal["timezone"], report_date)
    due = [
        s for s in db.store["shipments"].values()
        if s["destination_terminal_id"] == terminal["id"]
        and window_start <= s["committed_delivery_utc"] < window_end
        and s["handling_status"] in ("IN_LINEHAUL", "DELIVERED")
    ]
    on_time = [
        s for s in due
        if s["handling_status"] == "DELIVERED"
        and s["delivered_at_utc"] <= s["committed_delivery_utc"]
    ]
    pct = on_time_pct(len(on_time), len(due))
    rec = new_record({
        "terminal_id": terminal["id"], "report_date": report_date,
        "window_start_utc": window_start, "window_end_utc": window_end,
        "shipments_due": len(due), "shipments_on_time": len(on_time),
        "on_time_pct": pct,
        "service_level_met": pct >= ON_TIME_TARGET_PCT,
    }, common=False)
    db.store["service_reports"][rec["id"]] = rec
    return success(ser_report(rec), 201)


@bp.route("/ltl/terminals/<terminalId>/service-standard-reports", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_terminal_reports(terminalId):
    terminal = get_path("terminals", terminalId)
    items = [r for r in db.store["service_reports"].values()
             if r["terminal_id"] == terminal["id"]]
    page, total, limit, offset = paginate(items)
    return success_list([ser_report(r) for r in page], total, limit, offset)


@bp.route("/ltl/service-standard-reports", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_reports():
    items = list(db.store["service_reports"].values())
    for param in ("terminal_id", "report_date"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_report(r) for r in page], total, limit, offset)


@bp.route("/ltl/service-standard-reports/<reportId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_report(reportId):
    return success(ser_report(get_path("service_reports", reportId)))
