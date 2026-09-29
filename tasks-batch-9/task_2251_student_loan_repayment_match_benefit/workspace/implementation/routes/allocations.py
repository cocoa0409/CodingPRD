"""Match allocations, corrections, adjustments and forfeitures
(PRD 3.5, 3.7, 3.9)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, body, opt_str, req_enum, req_int
from response import object_response, paginated
from services import calc, effects, lookup, serialize

bp = Blueprint("allocations", __name__)

REASON_CODES = ("ERRONEOUS_MATCH", "CERTIFICATION_VOID", "TRUE_UP_RECOUPMENT",
                "ACP_CORRECTIVE_FORFEITURE")

ALLOCATION_FILTERS = ("employee_id", "plan_year_id", "certification_id",
                      "payroll_period_id", "funding_batch_id",
                      "allocation_type", "funding_status", "vesting_status")


@bp.get("/match-allocations")
def list_allocations():
    user_id, role = auth("BenefitsAdministrator", "Recordkeeper",
                         "ComplianceAuditor", "Employee")
    rows = lookup.scope_to_owner(db.rows("match_allocations"), role, user_id)
    for name in ALLOCATION_FILTERS:
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return paginated(rows, serialize.match_allocation)


@bp.get("/match-allocations/<allocation_id>")
def get_allocation(allocation_id):
    user_id, role = auth("BenefitsAdministrator", "Recordkeeper",
                         "ComplianceAuditor", "Employee")
    row = lookup.allocation(allocation_id)
    lookup.require_owner(role, user_id, row["employee_id"])
    return object_response(serialize.match_allocation(row))


@bp.post("/match-allocations/<allocation_id>/corrections")
def correct_allocation(allocation_id):
    user_id, _role = auth("BenefitsAdministrator")
    payload = body()
    reason_code = req_enum(payload, "reason_code", REASON_CODES)
    expected_version = req_int(payload, "expected_plan_year_version")
    note = opt_str(payload, "note")

    alloc = lookup.allocation(allocation_id)
    plan_year = db.db.plan_years.get(alloc["plan_year_id"])

    if plan_year is None or expected_version != plan_year["version"]:
        current = plan_year["version"] if plan_year else None
        fail("ERR_STALE_PLAN_YEAR_VERSION",
             "expected_plan_year_version %s does not match the plan year's "
             "current version %s" % (expected_version, current))

    if alloc["funding_status"] not in calc.LIVE_FUNDING_STATUSES:
        fail("ERR_CORRECTION_NOT_ALLOWED",
             "an allocation in %s may not be corrected"
             % alloc["funding_status"])

    alloc["funding_status"] = "REVERSED"
    db.touch(alloc)
    adjustment = effects.create_adjustment(
        reason_code=reason_code,
        amount_cents=-alloc["amount_cents"],
        employee_id=alloc["employee_id"],
        plan_year_id=alloc["plan_year_id"],
        created_by_user_id=user_id,
        match_allocation_id=alloc["id"],
        note=note,
    )
    effects.stale_completed_tests(plan_year["id"])
    db.touch(plan_year)
    employee = db.db.employees.get(alloc["employee_id"])
    if employee is not None:
        db.touch(employee)

    return object_response(serialize.correction_adjustment(adjustment), 201)


# --------------------------------------------------------------------------
# correction adjustments
# --------------------------------------------------------------------------

@bp.get("/correction-adjustments")
def list_adjustments():
    auth("BenefitsAdministrator", "ComplianceAuditor")
    rows = db.rows("correction_adjustments")
    for name in ("match_allocation_id", "employee_id", "plan_year_id",
                 "nondiscrimination_test_id", "reason_code"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return paginated(rows, serialize.correction_adjustment)


@bp.get("/correction-adjustments/<correction_id>")
def get_adjustment(correction_id):
    auth("BenefitsAdministrator", "ComplianceAuditor")
    row = lookup.audit_row("correction_adjustments", correction_id)
    return object_response(serialize.correction_adjustment(row))


# --------------------------------------------------------------------------
# forfeiture records
# --------------------------------------------------------------------------

@bp.get("/forfeiture-records")
def list_forfeitures():
    auth("BenefitsAdministrator", "ComplianceAuditor")
    rows = db.rows("forfeiture_records")
    for name in ("employee_id", "plan_year_id", "match_allocation_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return paginated(rows, serialize.forfeiture_record)


@bp.get("/forfeiture-records/<forfeiture_id>")
def get_forfeiture(forfeiture_id):
    auth("BenefitsAdministrator", "ComplianceAuditor")
    row = lookup.audit_row("forfeiture_records", forfeiture_id)
    return object_response(serialize.forfeiture_record(row))
