"""Pay periods, the payroll cycle and pay lines."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import serial
from auth import ALL_ROLES, authorize, check_employee_scope, scope_rows_by_employee
from envelope import object_response
from errors import ApiError, invalid
from serial import apply_filters, paged, view
from store import db, parse_instant, sort_key, stamp_new, touch

bp = Blueprint("periods", __name__)

PERIOD_STATUSES = {"OPEN", "COMPUTED", "APPROVED"}
LINE_STATUSES = {"DRAFT", "FINAL", "SUPERSEDED"}
VARIANTS = {"WEEKLY_AGGREGATE", "PER_SHIFT"}

from validators import f, parse_body, parse_query  # noqa: E402


def shift_order(shift):
    return (shift["business_date"], shift["created_at"], shift["_seq"])


def closed_shifts_of(period_id):
    return [
        s
        for s in cascades.period_shifts(period_id)
        if s["time_status"] == "CLOSED"
    ]


def employee_shifts(period_id, employee_id):
    return sorted(
        [s for s in closed_shifts_of(period_id) if s["employee_id"] == employee_id],
        key=shift_order,
    )


def new_pay_line(period, employee):
    record = {
        "pay_period_id": period["id"],
        "employee_id": employee["id"],
        "variant": "WEEKLY_AGGREGATE",
        "status": "DRAFT",
        "total_minutes": 0,
        "tip_credit_eligible_minutes": 0,
        "non_tip_credit_minutes": 0,
        "regular_minutes": 0,
        "overtime_minutes": 0,
        "straight_cash_cents": 0,
        "service_charge_wages_cents": 0,
        "regular_rate_cents_per_hour": 0,
        "overtime_premium_cents": 0,
        "minimum_wage_obligation_cents": 0,
        "tips_available_cents": 0,
        "pool_tips_cents": 0,
        "retained_tips_cents": 0,
        "tipped_employee_qualified": False,
        "tip_credit_cents": 0,
        "topup_cents": 0,
        "total_gross_cents": 0,
        "reported_tips_cents": 0,
        "allocated_tips_cents": 0,
        "correction_applied_cents": 0,
        "pending_correction_cents": 0,
        "open_dispute_count": 0,
    }
    stamp_new(record)
    db.pay_lines[record["id"]] = record
    return record


# ---------------------------------------------------------------------------
# create / read / list
# ---------------------------------------------------------------------------

PERIOD_SPEC = [
    f("location_id", "id", True),
    f("start_date", "date", True),
    f("end_date", "date", True),
]


@bp.post("/pay-periods")
def create_pay_period():
    authorize(["PayrollAdmin", "PayrollPreparer"])
    body, _present = parse_body(PERIOD_SPEC)
    if body["end_date"] < body["start_date"]:
        raise invalid("Field 'end_date' may not be before 'start_date'.")
    if body["location_id"] not in db.locations:
        raise ApiError("ERR_LOCATION_NOT_FOUND")

    # rung 39
    for existing in cascades.rows("pay_periods"):
        if existing["location_id"] != body["location_id"]:
            continue
        if (
            body["start_date"] <= existing["end_date"]
            and existing["start_date"] <= body["end_date"]
        ):
            raise ApiError("ERR_PAY_PERIOD_OVERLAP")

    # rung 43
    expected_end = parse_instant(body["start_date"]) + timedelta(days=6)
    if parse_instant(body["end_date"]) != expected_end:
        raise ApiError("ERR_PAY_PERIOD_LENGTH")

    record = {
        "location_id": body["location_id"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "status": "OPEN",
        "compute_variant": None,
        "computed_by_user_id": None,
        "approved_by_user_id": None,
        "total_credited_minutes": 0,
        "total_tip_credit_cents": 0,
        "total_topup_cents": 0,
        "total_correction_cents": 0,
        "gross_receipts_cents": 0,
        "reported_tips_cents": 0,
        "allocation_shortfall_cents": 0,
    }
    stamp_new(record)
    db.pay_periods[record["id"]] = record
    return object_response(view(record, serial.PAY_PERIOD), 201)


@bp.get("/pay-periods/<pay_period_id>")
def read_pay_period(pay_period_id):
    authorize(ALL_ROLES)
    record = db.pay_periods.get(pay_period_id)
    if record is None:
        raise ApiError("ERR_PAY_PERIOD_NOT_FOUND")
    return object_response(view(record, serial.PAY_PERIOD))


@bp.get("/pay-periods")
def list_pay_periods():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [f("location_id", "id"), f("status", "enum", domain=PERIOD_STATUSES)]
    )
    rows = apply_filters(cascades.rows("pay_periods"), filters)
    return paged(rows, serial.PAY_PERIOD, limit, offset)


# ---------------------------------------------------------------------------
# pay lines
# ---------------------------------------------------------------------------

@bp.get("/pay-lines/<pay_line_id>")
def read_pay_line(pay_line_id):
    actor = authorize(ALL_ROLES)
    record = db.pay_lines.get(pay_line_id)
    if record is None:
        raise ApiError("ERR_PAY_LINE_NOT_FOUND")
    check_employee_scope(actor, record["employee_id"])
    return object_response(view(record, serial.PAY_LINE))


@bp.get("/pay-lines")
def list_pay_lines():
    actor = authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("pay_period_id", "id"),
            f("employee_id", "id"),
            f("status", "enum", domain=LINE_STATUSES),
            f("variant", "enum", domain=VARIANTS),
        ]
    )
    rows = apply_filters(cascades.rows("pay_lines"), filters)
    rows = scope_rows_by_employee(actor, rows)
    return paged(rows, serial.PAY_LINE, limit, offset)


# ---------------------------------------------------------------------------
# the service-charge wages allocation (3.6), run inside a compute
# ---------------------------------------------------------------------------

def wages_charges_of(period):
    """Every RECORDED, WAGES-treated charge of the unit inside the period."""
    return [
        c
        for c in cascades.rows("service_charges")
        if c["location_id"] == period["location_id"]
        and c["status"] == "RECORDED"
        and c["treatment"] == "WAGES"
        and cascades.date_in_period(period, c["business_date"])
    ]


def closed_shifts_on(location_id, business_date):
    return [
        s
        for s in cascades.rows("shifts")
        if s["location_id"] == location_id
        and s["business_date"] == business_date
        and s["time_status"] == "CLOSED"
    ]


def _employee_tiebreak(shift):
    employee = db.employees.get(shift["employee_id"])
    if employee is None:
        return ("", 0, shift["created_at"], shift["_seq"])
    return (
        employee["created_at"],
        employee["_seq"],
        shift["created_at"],
        shift["_seq"],
    )


def allocate_service_charge_wages(period, lines):
    """Split each qualifying event on its own across that date's CLOSED shifts."""
    for charge in wages_charges_of(period):
        day_shifts = closed_shifts_on(charge["location_id"], charge["business_date"])
        items = [
            (s["id"], s["scheduled_minutes"], _employee_tiebreak(s)) for s in day_shifts
        ]
        for shift_id, share, _won in calc.largest_remainder(
            charge["amount_cents"], items
        ):
            shift = db.shifts.get(shift_id)
            if shift is None:
                continue
            line = lines.get(shift["employee_id"])
            if line is not None:
                line["service_charge_wages_cents"] += share
        charge["status"] = "ALLOCATED"
        charge["allocated_pay_period_id"] = period["id"]
        touch(charge)


def line_totals(line):
    line["total_gross_cents"] = (
        line["straight_cash_cents"]
        + line["service_charge_wages_cents"]
        + line["overtime_premium_cents"]
        + line["topup_cents"]
        + line["correction_applied_cents"]
    )


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------

@bp.post("/pay-periods/<pay_period_id>/compute")
def compute_pay_period(pay_period_id):
    actor = authorize(["PayrollPreparer"])
    parse_body([])
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise ApiError("ERR_PAY_PERIOD_NOT_FOUND")

    if period["status"] != "OPEN":                              # rung 12
        raise ApiError("ERR_PAY_PERIOD_NOT_OPEN")

    closed = closed_shifts_of(period["id"])

    # rung 18: a night that should have been pooled but was not
    pairs = []
    for shift in closed:
        key = (shift["location_id"], shift["business_date"])
        if key not in pairs:
            pairs.append(key)
    policies = cascades.rows("policies")
    pools = cascades.rows("pools")
    for location_id, business_date in pairs:
        active = [
            p
            for p in policies
            if p["location_id"] == location_id and p["status"] == "ACTIVE"
        ]
        if not active:
            continue
        settled = [
            pool
            for pool in pools
            if pool["location_id"] == location_id
            and pool["business_date"] == business_date
            and pool["contribution_status"] == "CONTRIBUTED"
            and pool["distribution_status"] == "DISTRIBUTED"
        ]
        if not settled:
            raise ApiError("ERR_POOL_NOT_DISTRIBUTED")

    # rung 35
    for shift in closed:
        if shift["declaration_status"] not in ("DECLARED", "AMENDED"):
            raise ApiError("ERR_UNDECLARED_SHIFT_IN_PERIOD")

    # rung 36
    for charge in wages_charges_of(period):
        if not closed_shifts_on(charge["location_id"], charge["business_date"]):
            raise ApiError("ERR_SERVICE_CHARGE_UNALLOCATABLE")

    location = db.locations.get(period["location_id"])

    # (1) supersede the previous set before inserting the new one
    cascades.supersede_period_lines(period["id"])

    # (2) one line per employee holding at least one CLOSED shift
    worked = set(shift["employee_id"] for shift in closed)
    lines = {}
    for employee in cascades.rows("employees"):
        if employee["id"] in worked:
            lines[employee["id"]] = new_pay_line(period, employee)

    # (3) the service-charge allocation runs before the wage computation
    allocate_service_charge_wages(period, lines)

    # (4) the wage computation, WEEKLY_AGGREGATE
    for employee_id, line in lines.items():
        employee = db.employees[employee_id]
        shifts = employee_shifts(period["id"], employee_id)
        tips = cascades.net_pool_tips_by_shift(employee_id, period)
        base = calc.wage_common(
            location, employee, shifts, tips, line["service_charge_wages_cents"]
        )
        line.update(base)
        line.update(calc.wage_weekly_aggregate(location, base))
        cascades.recompute_line_corrections(line)
        line_totals(line)

    period["compute_variant"] = "WEEKLY_AGGREGATE"
    period["computed_by_user_id"] = actor.user_id
    period["status"] = "COMPUTED"
    touch(period)
    cascades.recompute_period_shift_rollups(period)
    cascades.recompute_period_line_rollups(period)
    return object_response(view(period, serial.PAY_PERIOD))


# ---------------------------------------------------------------------------
# the reporting test and allocated tips (3.8)
# ---------------------------------------------------------------------------

def directly_tipped(period, employee_id):
    """True when the employee worked a CLOSED shift on a tipped, non-management role."""
    for shift in employee_shifts(period["id"], employee_id):
        role = db.job_roles.get(shift["job_role_id"])
        if role is None:
            continue
        if role["tip_status"] == "TIPPED" and not role["is_management"]:
            return True
    return False


def reporting_test(period, lines):
    threshold = calc.allocated_tips_threshold(period["gross_receipts_cents"])
    reported = sum(line["reported_tips_cents"] for line in lines)
    period["reported_tips_cents"] = reported

    for line in lines:
        line["allocated_tips_cents"] = 0

    if reported >= threshold:
        period["allocation_shortfall_cents"] = 0
        return
    shortfall = threshold - reported
    period["allocation_shortfall_cents"] = shortfall

    items = []
    by_id = {}
    for line in lines:
        if not directly_tipped(period, line["employee_id"]):
            continue
        sales = sum(
            s["gross_sales_cents"]
            for s in employee_shifts(period["id"], line["employee_id"])
        )
        employee = db.employees.get(line["employee_id"])
        tiebreak = (
            (employee["created_at"], employee["_seq"])
            if employee is not None
            else ("", 0)
        )
        by_id[line["id"]] = line
        items.append((line["id"], sales, tiebreak))

    for line_id, share, _won in calc.largest_remainder(shortfall, items):
        by_id[line_id]["allocated_tips_cents"] = share


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

@bp.post("/pay-periods/<pay_period_id>/approve")
def approve_pay_period(pay_period_id):
    actor = authorize(["ComplianceOfficer"])
    parse_body([])
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise ApiError("ERR_PAY_PERIOD_NOT_FOUND")

    if actor.user_id == period["computed_by_user_id"]:            # rung 7
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if period["status"] != "COMPUTED":                            # rung 13
        raise ApiError("ERR_PAY_PERIOD_NOT_COMPUTED")

    location = db.locations.get(period["location_id"])
    lines = cascades.live_lines(period["id"])

    for line in lines:
        shifts = employee_shifts(period["id"], line["employee_id"])
        tips = cascades.net_pool_tips_by_shift(line["employee_id"], period)
        credit, topup, per_shift = calc.wage_per_shift(location, line, shifts, tips)
        line["tip_credit_cents"] = credit
        line["topup_cents"] = topup
        line["variant"] = "PER_SHIFT"
        line["status"] = "FINAL"
        line_totals(line)
        touch(line)
        for shift in shifts:
            shift["shift_tip_credit_cents"] = per_shift.get(shift["id"], 0)
            touch(shift)

    reporting_test(period, lines)

    period["compute_variant"] = "PER_SHIFT"
    period["approved_by_user_id"] = actor.user_id
    period["status"] = "APPROVED"
    touch(period)
    cascades.recompute_period_line_rollups(period)
    return object_response(view(period, serial.PAY_PERIOD))


# ---------------------------------------------------------------------------
# reopen
# ---------------------------------------------------------------------------

@bp.post("/pay-periods/<pay_period_id>/reopen")
def reopen_pay_period(pay_period_id):
    authorize(["ComplianceOfficer"])
    parse_body([f("reason", "str")])
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise ApiError("ERR_PAY_PERIOD_NOT_FOUND")

    if period["status"] not in ("COMPUTED", "APPROVED"):          # rung 14
        raise ApiError("ERR_PAY_PERIOD_NOT_COMPUTED")

    line_ids = set(line["id"] for line in cascades.period_lines(period["id"]))
    for correction in cascades.rows("corrections"):               # rung 15
        if correction["pay_line_id"] in line_ids and correction["status"] == "PENDING":
            raise ApiError("ERR_PENDING_CORRECTION_EXISTS")

    cascades.supersede_period_lines(period["id"])
    period["compute_variant"] = None
    period["computed_by_user_id"] = None
    period["approved_by_user_id"] = None
    period["allocation_shortfall_cents"] = 0
    period["total_tip_credit_cents"] = 0
    period["total_topup_cents"] = 0
    period["reported_tips_cents"] = 0
    period["status"] = "OPEN"
    touch(period)

    # a client reopen releases the WAGES charges it had absorbed
    for charge in cascades.rows("service_charges"):
        if charge["allocated_pay_period_id"] == period["id"]:
            charge["status"] = "RECORDED"
            charge["allocated_pay_period_id"] = None
            touch(charge)
    return object_response(view(period, serial.PAY_PERIOD))
