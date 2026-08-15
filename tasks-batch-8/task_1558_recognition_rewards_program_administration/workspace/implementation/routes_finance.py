"""Routes: accrual runs, abuse flags, anniversary scans/events, tax-year
finalization, and the test-driving logical clock (PRD sections 3.4, 3.6-3.8)."""
from datetime import date

import db
import serialize as ser
import services as svc
import calc
from db import now, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_NOT_ACTIVE, ERR_INVALID_TAX_YEAR, ERR_DUPLICATE_ACCRUAL_RUN,
    ERR_ACCRUAL_VARIANCE, ERR_PERIODS_NOT_CLOSED, ERR_TAX_YEAR_FINALIZED,
)
from flask import Blueprint, request
from response import success
from validate import (
    auth_context, require_role, get_or_404, body, req_str, req_int, req_enum,
    parse_iso_datetime,
)
from routes_core import READ_ROLES, _sorted_rows, _paginate, require_active_program

bp = Blueprint("finance", __name__)

RULE_CODES = {"VELOCITY_EXCEEDED", "DUPLICATE_ATTEMPT", "SELF_NOMINATION",
              "MANAGER_QUID_PRO_QUO", "REDEMPTION_ANOMALY", "MANUAL_REVIEW"}


# ---------------------------------------------------------------------------
# Anniversary scans + events
# ---------------------------------------------------------------------------

def _anniversary_matches(hire, scan_date):
    """(month, day) match; Feb 29 hires observed on Feb 28 in non-leap years."""
    m, d = hire.month, hire.day
    if m == 2 and d == 29:
        leap = (scan_date.year % 4 == 0 and scan_date.year % 100 != 0) \
            or scan_date.year % 400 == 0
        if not leap:
            m, d = 2, 28
    return (m, d) == (scan_date.month, scan_date.day)


@bp.route("/api/programs/<programId>/anniversary-scans", methods=["POST"])
def anniversary_scan(programId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    program = get_or_404(db.programs, programId, "Program")
    require_active_program(program)
    scan_date = now().date()
    milestones = {m["years"]: m["points"]
                  for m in program["anniversary_milestones"]}
    events = []
    eligible = svc_eligible_employees_for_program(program["id"])
    for emp in eligible:
        hire = emp["hire_date"]
        if not _anniversary_matches(hire, scan_date):
            continue
        years = scan_date.year - hire.year
        # Ordered evaluation: DUPLICATE -> INELIGIBLE -> NO_MILESTONE ->
        # BUDGET_EXHAUSTED -> PROCESSED.
        status = None
        award_id = None
        if any(ev["program_id"] == program["id"]
               and ev["employee_id"] == emp["id"]
               and ev["milestone_years"] == years
               for ev in db.anniversary_events.values()):
            status = "SKIPPED_DUPLICATE"
        elif emp["program_status"] == "SUSPENDED":
            status = "SKIPPED_INELIGIBLE"
        elif years not in milestones:
            status = "SKIPPED_NO_MILESTONE"
        else:
            points = milestones[years]
            budget = svc.select_budget(program["id"], emp["department_id"],
                                       scan_date)
            room = False
            if budget is not None:
                try:
                    svc.budget_gate_check(budget, points)
                    room = True
                except Exception:
                    room = False
            if not room:
                status = "SKIPPED_BUDGET_EXHAUSTED"
            else:
                award = svc.create_award(program["id"], emp, points,
                                         "ANNIVERSARY", nomination_id=None)
                svc.post_ledger(emp, "GRANT_ANNIVERSARY", points, "AWARD",
                                award["id"],
                                "anniversary:%s:GRANT_ANNIVERSARY" % award["id"],
                                "Service anniversary %d years: +%d points"
                                % (years, points))
                svc.emp_grant(emp, points)
                budget["committed_points"] += points
                svc.budget_mutated(budget)
                status = "PROCESSED"
                award_id = award["id"]
        ev = {
            "id": db.new_id(),
            "program_id": program["id"],
            "employee_id": emp["id"],
            "milestone_years": years,
            "scheduled_date": scan_date,
            "status": status,
            "award_id": award_id,
        }
        db.stamp(ev)
        db.anniversary_events[ev["id"]] = ev
        events.append(ev)
    return success([ser.anniversary_event(e) for e in events])


def svc_eligible_employees_for_program(program_id):
    """Every employee whose department holds any budget in the program (any
    window, any posture)."""
    dept_ids = set()
    for b in db.budgets.values():
        if b["program_id"] == program_id:
            dept_ids.add(b["department_id"])
    rows = [e for e in db.employees.values()
            if e["department_id"] in dept_ids]
    rows.sort(key=lambda e: e["created_at"])
    return rows


@bp.route("/api/anniversary-events/<anniversaryEventId>", methods=["GET"])
def get_anniversary_event(anniversaryEventId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    ev = get_or_404(db.anniversary_events, anniversaryEventId,
                    "AnniversaryEvent")
    return success(ser.anniversary_event(ev))


@bp.route("/api/anniversary-events", methods=["GET"])
def list_anniversary_events():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.anniversary_events.values())
    for param, field in (("program_id", "program_id"),
                         ("employee_id", "employee_id"),
                         ("award_id", "award_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            rows = [e for e in rows if e[field] == v]
    return _paginate(rows, ser.anniversary_event)


# ---------------------------------------------------------------------------
# Tax-year finalization
# ---------------------------------------------------------------------------

@bp.route("/api/programs/<programId>/finalize-tax-year", methods=["POST"])
def finalize_tax_year(programId):
    _, role = auth_context()
    require_role(role, ["PayrollSpecialist"])
    program = get_or_404(db.programs, programId, "Program")
    b = body()
    tax_year = req_int(b, "tax_year")
    if tax_year < 2000 or tax_year > 2100:
        raise_err(ERR_INVALID_TAX_YEAR, "tax_year must be in 2000..2100")
    # Every month's run must exist and be CLOSED or VOIDED.
    for month in range(1, 13):
        runs = [r for r in db.accrual_runs.values()
                if r["program_id"] == program["id"]
                and r["period_year"] == tax_year
                and r["period_month"] == month]
        live = [r for r in runs if r["status"] != "VOIDED"]
        if live:
            if any(r["status"] != "CLOSED" for r in live):
                raise_err(ERR_PERIODS_NOT_CLOSED,
                          "Accrual run for %d-%02d is not CLOSED"
                          % (tax_year, month))
        elif not runs:
            raise_err(ERR_PERIODS_NOT_CLOSED,
                      "No accrual run for %d-%02d" % (tax_year, month))
        # only VOIDED runs -> month satisfied
    if (program["id"], tax_year) in db.finalized_tax_years:
        raise_err(ERR_TAX_YEAR_FINALIZED,
                  "Tax year %d already finalized for this program" % tax_year)
    records = []
    total_delta = 0
    for t in db.tax_records.values():
        if t["program_id"] == program["id"] and t["tax_year"] == tax_year \
                and t["status"] == "ESTIMATED":
            emp = db.employees[t["employee_id"]]
            final = calc.gross_up_cents(program, emp, t["taxable_value_cents"])
            t["final_gross_up_cents"] = final
            t["delta_cents"] = final - t["estimated_gross_up_cents"]
            t["status"] = "FINALIZED"
            touch(t)
            total_delta += t["delta_cents"]
            records.append(t)
    db.finalized_tax_years.add((program["id"], tax_year))
    records.sort(key=lambda t: t["created_at"])
    return success({
        "finalized_count": len(records),
        "records": [ser.tax_record(t) for t in records],
        "total_delta_cents": total_delta,
    })


# ---------------------------------------------------------------------------
# Accrual runs
# ---------------------------------------------------------------------------

@bp.route("/api/accrual-runs", methods=["POST"])
def create_accrual_run():
    _, role = auth_context()
    require_role(role, ["FinanceAdmin"])
    b = body()
    program_id = b.get("program_id")
    period_year = req_int(b, "period_year")
    period_month = req_int(b, "period_month")
    if period_month < 1 or period_month > 12:
        raise_err(ERR_INVALID_REQUEST, "period_month must be in 1..12")
    if not isinstance(program_id, str) or program_id not in db.programs:
        raise_err(ERR_NOT_FOUND, "Program not found: %s" % program_id)
    program = db.programs[program_id]
    if any(r["program_id"] == program_id and r["period_year"] == period_year
           and r["period_month"] == period_month and r["status"] != "VOIDED"
           for r in db.accrual_runs.values()):
        raise_err(ERR_DUPLICATE_ACCRUAL_RUN,
                  "A non-VOIDED run already exists for %d-%02d"
                  % (period_year, period_month))
    breakdown = calc.compute_department_breakdown(program, period_year,
                                                  period_month)
    total_accrual, total_net = calc.totals(breakdown)
    run = {
        "id": db.new_id(),
        "program_id": program_id,
        "period_year": period_year,
        "period_month": period_month,
        "status": "OPEN",
        "accrual_method_used": program["accrual_method"],
        "department_breakdown": breakdown,
        "total_accrual_cents": total_accrual,
        "total_net_chargeback_cents": total_net,
        "variance_cents": 0,
    }
    db.stamp(run)
    db.accrual_runs[run["id"]] = run
    return success(ser.accrual_run(run), 201)


@bp.route("/api/accrual-runs/<accrualRunId>", methods=["GET"])
def get_accrual_run(accrualRunId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    r = get_or_404(db.accrual_runs, accrualRunId, "AccrualRun")
    return success(ser.accrual_run(r))


@bp.route("/api/accrual-runs", methods=["GET"])
def list_accrual_runs():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.accrual_runs.values())
    pid = request.args.get("program_id")
    status = request.args.get("status")
    year = request.args.get("period_year")
    if pid is not None:
        rows = [r for r in rows if r["program_id"] == pid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if year is not None:
        try:
            year_i = int(year)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "period_year must be an integer")
        rows = [r for r in rows if r["period_year"] == year_i]
    return _paginate(rows, ser.accrual_run)


@bp.route("/api/accrual-runs/<accrualRunId>/reconcile", methods=["POST"])
def reconcile_accrual_run(accrualRunId):
    _, role = auth_context()
    require_role(role, ["FinanceAdmin"])
    run = get_or_404(db.accrual_runs, accrualRunId, "AccrualRun")
    if run["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only OPEN runs can be reconciled")
    program = db.programs[run["program_id"]]
    breakdown = calc.compute_department_breakdown(program, run["period_year"],
                                                  run["period_month"])
    _, recomputed_net = calc.totals(breakdown)
    variance = recomputed_net - run["total_net_chargeback_cents"]
    run["variance_cents"] = variance
    touch(run)
    if variance != 0:
        raise_err(ERR_ACCRUAL_VARIANCE,
                  "Recomputed net chargeback differs by %d cents" % variance)
    run["status"] = "RECONCILED"
    return success(ser.accrual_run(run))


@bp.route("/api/accrual-runs/<accrualRunId>/close", methods=["POST"])
def close_accrual_run(accrualRunId):
    _, role = auth_context()
    require_role(role, ["FinanceAdmin"])
    run = get_or_404(db.accrual_runs, accrualRunId, "AccrualRun")
    if run["status"] != "RECONCILED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only RECONCILED runs can be closed")
    run["status"] = "CLOSED"
    touch(run)
    return success(ser.accrual_run(run))


@bp.route("/api/accrual-runs/<accrualRunId>/void", methods=["POST"])
def void_accrual_run(accrualRunId):
    _, role = auth_context()
    require_role(role, ["FinanceAdmin"])
    run = get_or_404(db.accrual_runs, accrualRunId, "AccrualRun")
    if run["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only OPEN runs can be voided")
    run["status"] = "VOIDED"
    touch(run)
    return success(ser.accrual_run(run))


# ---------------------------------------------------------------------------
# Abuse flags
# ---------------------------------------------------------------------------

@bp.route("/api/abuse-flags", methods=["POST"])
def create_abuse_flag():
    user_id, role = auth_context()
    require_role(role, ["HRAdmin"])
    b = body()
    employee_id = b.get("employee_id")
    program_id = b.get("program_id")
    rule_code = req_enum(b, "rule_code", RULE_CODES)
    details = b.get("details")
    if details is not None and not isinstance(details, dict):
        raise_err(ERR_INVALID_REQUEST, "details must be an object")
    if not isinstance(employee_id, str) or employee_id not in db.employees:
        raise_err(ERR_NOT_FOUND, "Employee not found: %s" % employee_id)
    if not isinstance(program_id, str) or program_id not in db.programs:
        raise_err(ERR_NOT_FOUND, "Program not found: %s" % program_id)
    flag = {
        "id": db.new_id(),
        "employee_id": employee_id,
        "program_id": program_id,
        "rule_code": rule_code,
        "details": details if details is not None else {},
        "status": "OPEN",
        "raised_by": user_id,
        "resolved_by": None,
    }
    db.stamp(flag)
    db.abuse_flags[flag["id"]] = flag
    return success(ser.abuse_flag(flag), 201)


@bp.route("/api/abuse-flags/<abuseFlagId>", methods=["GET"])
def get_abuse_flag(abuseFlagId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    f = get_or_404(db.abuse_flags, abuseFlagId, "AbuseFlag")
    return success(ser.abuse_flag(f))


@bp.route("/api/abuse-flags", methods=["GET"])
def list_abuse_flags():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.abuse_flags.values())
    for param, field in (("employee_id", "employee_id"),
                         ("program_id", "program_id"),
                         ("rule_code", "rule_code"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            rows = [f for f in rows if f[field] == v]
    return _paginate(rows, ser.abuse_flag)


@bp.route("/api/abuse-flags/<abuseFlagId>/review", methods=["POST"])
def review_abuse_flag(abuseFlagId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    f = get_or_404(db.abuse_flags, abuseFlagId, "AbuseFlag")
    if f["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only OPEN flags can move to UNDER_REVIEW")
    f["status"] = "UNDER_REVIEW"
    touch(f)
    return success(ser.abuse_flag(f))


@bp.route("/api/abuse-flags/<abuseFlagId>/confirm", methods=["POST"])
def confirm_abuse_flag(abuseFlagId):
    user_id, role = auth_context()
    require_role(role, ["HRAdmin"])
    f = get_or_404(db.abuse_flags, abuseFlagId, "AbuseFlag")
    if f["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only OPEN or UNDER_REVIEW flags can be confirmed")
    emp = db.employees[f["employee_id"]]
    # Pinned cascade order (PRD 3.8):
    # (1) cancel the employee's PENDING_SUBMISSION orders (full refund +
    #     inventory restore);
    from routes_commerce import cancel_order_effects
    for o in list(db.orders.values()):
        if o["employee_id"] == emp["id"] \
                and o["fulfillment_status"] == "PENDING_SUBMISSION":
            cancel_order_effects(o, emp,
                                 note="Order cancelled by abuse-flag cascade")
    # (2) revoke all ACTIVE awards in granted_at ASC / created_at ASC order,
    #     each firing its own clawback side effects referencing the flag;
    for award in svc.active_awards(emp["id"]):
        svc.revoke_award(award, emp, flag_id=f["id"],
                         idem_base="abuse:%s:%s" % (f["id"], award["id"]))
    # (3) tier recompute happens inside each clawback; ensure final state.
    svc.recompute_tier(emp)
    emp["program_status"] = "SUSPENDED"
    touch(emp)
    f["status"] = "CONFIRMED"
    f["resolved_by"] = user_id
    touch(f)
    return success(ser.abuse_flag(f))


@bp.route("/api/abuse-flags/<abuseFlagId>/dismiss", methods=["POST"])
def dismiss_abuse_flag(abuseFlagId):
    user_id, role = auth_context()
    require_role(role, ["HRAdmin"])
    f = get_or_404(db.abuse_flags, abuseFlagId, "AbuseFlag")
    if f["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only OPEN or UNDER_REVIEW flags can be dismissed")
    f["status"] = "DISMISSED"
    f["resolved_by"] = user_id
    touch(f)
    return success(ser.abuse_flag(f))


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    b = body()
    target = parse_iso_datetime(b.get("to_iso8601"), "to_iso8601")
    if target < now():
        raise_err(ERR_INVALID_REQUEST, "The logical clock never moves backward")
    db.set_clock(target)
    svc.run_clock_sweep(target)
    return success({"current_utc": db.iso_ms(db.now())})
