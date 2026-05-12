"""PayrollPeriod endpoints."""

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from errors import (
    raise_error,
    ERR_PERIOD_NOT_FOUND,
    ERR_INVALID_PARAMETER,
)
from services.serializers import payroll_period_view, ledger_view
from services import payroll as payroll_svc


bp = Blueprint("payroll", __name__)


def _get_period(period_id: str) -> dict:
    p = db.find_by_id("payroll_periods", period_id)
    if not p:
        raise_error(ERR_PERIOD_NOT_FOUND, "Period not found.")
    return p


@bp.route("/payroll-periods", methods=["POST"])
def create_period():
    require_role("ProjectManager")
    body = request.get_json(silent=True) or {}
    p = payroll_svc.create_period(
        cycle_label=body.get("cycle_label"),
        opens_at=body.get("opens_at"),
        closes_at=body.get("closes_at"),
        tax_rate=body.get("tax_rate"),
    )
    return success(payroll_period_view(p), status_code=201)


@bp.route("/payroll-periods", methods=["GET"])
def list_periods():
    require_role("ProjectManager")
    limit, offset = parse_pagination(request.args)
    filters = {}
    status = request.args.get("status")
    if status:
        filters["status"] = status
    rows, total = db.query("payroll_periods", filters=filters,
                           limit=limit, offset=offset)
    return success_list([payroll_period_view(r) for r in rows], total, limit, offset)


@bp.route("/payroll-periods/<period_id>/lock", methods=["POST"])
def lock_period(period_id):
    require_role("ProjectManager")
    p = _get_period(period_id)
    out = payroll_svc.lock_period(p)
    return success(payroll_period_view(out))


@bp.route("/payroll-periods/<period_id>/settle", methods=["POST"])
def settle_period(period_id):
    require_role("ProjectManager")
    p = _get_period(period_id)
    out = payroll_svc.settle_period(p)
    return success(payroll_period_view(out))


@bp.route("/payroll-periods/<period_id>/ledger-entries", methods=["GET"])
def list_ledger(period_id):
    require_role("ProjectManager", "Annotator")
    _get_period(period_id)
    limit, offset = parse_pagination(request.args)
    annotator_id = request.args.get("annotator_id")

    rows = [
        e for e in db.all_rows("ledger_entries")
        if e.get("payroll_period_id") == period_id
    ]
    if annotator_id:
        rows = [e for e in rows if e.get("annotator_id") == annotator_id]
    elif g.role == "Annotator":
        rows = [e for e in rows if e.get("annotator_id") == g.user_id]
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = len(rows)
    rows = rows[offset:offset + limit]
    return success_list([ledger_view(r) for r in rows], total, limit, offset)
