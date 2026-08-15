"""PayrollPeriod endpoints: open, get, list, export (the waterfall)."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, public
from errors import (
    raise_err, ERR_DISTRICT_NOT_FOUND, ERR_PAYROLL_PERIOD_NOT_FOUND,
    ERR_PAYROLL_PERIOD_INVALID_STATE, ERR_INVALID_DATE_RANGE,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from util import parse_date
from validate import body, req_str, req_date

bp = Blueprint("payroll", __name__)


@bp.route("/payroll-periods", methods=["POST"])
def create_payroll_period():
    _, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    require_role(role, ["PayrollClerk"])
    if district_id not in STORE.districts:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    if parse_date(period_end) < parse_date(period_start):
        raise_err(ERR_INVALID_DATE_RANGE, "period_end must not precede period_start")
    p = new_entity(STORE.payroll_periods, {
        "district_id": district_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "total_payout_cents": None,
        "assignments_paid_count": None,
        "coverages_compensated_count": None,
        "exported_at": None,
    })
    return ok(public(p), status=201)


@bp.route("/payroll-periods/<pid>", methods=["GET"])
def get_payroll_period(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    p = STORE.payroll_periods.get(pid)
    if p is None:
        raise_err(ERR_PAYROLL_PERIOD_NOT_FOUND, "payroll period id does not exist")
    return ok(public(p))


@bp.route("/payroll-periods", methods=["GET"])
def list_payroll_periods():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    district_id = request.args.get("district_id")
    items = sorted(STORE.payroll_periods.values(), key=lambda p: (p["created_at"], p["_seq"]))
    if district_id is not None:
        items = [p for p in items if p["district_id"] == district_id]
    page, meta = paginated(items)
    return ok([public(p) for p in page], pagination=meta)


@bp.route("/payroll-periods/<pid>/export", methods=["POST"])
def export_payroll_period(pid):
    _, role = auth_context()
    body()
    require_role(role, ["PayrollClerk"])
    p = STORE.payroll_periods.get(pid)
    if p is None:
        raise_err(ERR_PAYROLL_PERIOD_NOT_FOUND, "payroll period id does not exist")
    if p["status"] != "OPEN":
        raise_err(ERR_PAYROLL_PERIOD_INVALID_STATE, "export requires status OPEN")

    def in_district(absence):
        d = domain.absence_district(absence)
        return d is not None and d["id"] == p["district_id"]

    # Refuse to run dirty: unreviewed timesheets anywhere in the district.
    for t in STORE.timesheets.values():
        if t["status"] == "SUBMITTED":
            asg = STORE.assignments.get(t["assignment_id"])
            if asg is not None and in_district(domain.assignment_absence(asg)):
                raise_err(ERR_PAYROLL_PERIOD_INVALID_STATE,
                          "unreviewed SUBMITTED timesheets exist in this district")
    p_start = parse_date(p["period_start"])
    p_end = parse_date(p["period_end"])
    for asg in STORE.assignments.values():
        if asg["status"] in ("ACCEPTED", "WORKED"):
            absence = domain.assignment_absence(asg)
            if in_district(absence) and p_start <= parse_date(absence["end_date"]) <= p_end:
                raise_err(ERR_PAYROLL_PERIOD_INVALID_STATE,
                          "an ACCEPTED or WORKED assignment ends inside this period")
    domain.export_payroll_period(p)
    return ok(public(p))
