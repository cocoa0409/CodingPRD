"""IFTA quarterly fuel-tax reporting (PRD §3.9)."""
from flask import Blueprint, g, request

import response
from db import base_record, db, touch
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, paginate, query_enum, req_str,
                        require_roles)
from services import serialize
from services.ifta import QUARTER_RE, compute, period_transactions, quarter_period
from services.store import REPORT_STATUSES, get_account, get_report
from util import fmt_dt

bp = Blueprint("ifta_reports", __name__)


@bp.post("/ifta-reports")
@require_roles("ProgramAdmin")
def generate_report():
    data = body()
    fleet_account_id = req_str(data, "fleet_account_id")
    quarter = req_str(data, "quarter")
    if not QUARTER_RE.match(quarter):
        raise err("ERR_VALIDATION", "Field 'quarter' must match ^\\d{4}-Q[1-4]$.")

    account = get_account(fleet_account_id)
    check_fleet(account["id"])

    start, end = quarter_period(quarter)
    lines, total = compute(fleet_account_id, start, end)

    record = base_record()
    record.update({
        "fleet_account_id": fleet_account_id,
        "quarter": quarter,
        "period_start": fmt_dt(start),
        "period_end": fmt_dt(end),
        "jurisdiction_lines": lines,
        "total_tax_cents": total,
        "status": "DRAFT",
        "filed_at": None,
        "_period_start_dt": start,
        "_period_end_dt": end,
    })
    db.ifta_reports[record["id"]] = record
    return response.created(serialize.ifta_report(record))


@bp.get("/ifta-reports/<report_id>")
@require_roles("ProgramAdmin", "FleetManager")
def fetch_report(report_id):
    report = get_report(report_id)
    check_fleet(report["fleet_account_id"])
    return response.ok(serialize.ifta_report(report))


@bp.get("/ifta-reports")
@require_roles("ProgramAdmin", "FleetManager")
def list_reports():
    account_filter = request.args.get("fleet_account_id")
    status_filter = query_enum("status", REPORT_STATUSES)

    if is_fleet_manager():
        if account_filter is not None and account_filter != g.user_id:
            raise err("ERR_FORBIDDEN_FLEET")
        account_filter = g.user_id

    records = list(db.ifta_reports.values())
    if account_filter is not None:
        records = [r for r in records if r["fleet_account_id"] == account_filter]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.ifta_report(r) for r in page], limit, offset, total)


@bp.post("/ifta-reports/<report_id>/file")
@require_roles("ProgramAdmin")
def file_report(report_id):
    report = get_report(report_id)

    # 5. Transition state.
    if report["status"] != "DRAFT":
        raise err("ERR_INVALID_REPORT_STATE", "Only a DRAFT report can be filed.")

    # 17. Period settlement — every in-period transaction of the account is SETTLED.
    in_period = period_transactions(
        report["fleet_account_id"], report["_period_start_dt"], report["_period_end_dt"])
    if any(t["posting_status"] != "SETTLED" for t in in_period):
        raise err("ERR_PERIOD_NOT_SETTLED")

    # Freeze the computed figures, then stamp filed_at from the logical clock.
    lines, total = compute(
        report["fleet_account_id"], report["_period_start_dt"], report["_period_end_dt"])
    report["jurisdiction_lines"] = lines
    report["total_tax_cents"] = total
    report["status"] = "FILED"
    report["filed_at"] = db.clock.now_iso()
    touch(report)
    return response.ok(serialize.ifta_report(report))
