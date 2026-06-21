"""W-4 form endpoints."""
from flask import Blueprint, request

import db
import response
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_EMPLOYEE_NOT_ACTIVE,
    ERR_SUPERSEDE_TARGET_INVALID,
)
from middleware import require_roles
from services import serialize, pagination
from services import validation as V


bp = Blueprint("w4_forms", __name__)


def _check_supersede_target(supersedes_id, employee_id, tax_year):
    """Priority-10 ERR_SUPERSEDE_TARGET_INVALID."""
    if not supersedes_id:
        return
    target = db.w4_forms.get(supersedes_id)
    if not target:
        # Priority 4 FK existence already handled by caller; here we only validate
        # business referential rule when target exists but is wrong.
        return
    if (target["status"] != "FILED"
            or target["employee_id"] != employee_id
            or target["tax_year"] != tax_year):
        raise APIError(ERR_SUPERSEDE_TARGET_INVALID, 422, "supersede target invalid")


@bp.post("/w4-forms")
@require_roles("HRClerk", "PayrollPreparer")
def create_w4():
    body = V.require_dict(request.get_json(silent=True) or {})
    employee_id = V.require_str(body, "employee_id")
    tax_year = V.require_int(body, "tax_year")
    filing_status = V.require_enum(body, "filing_status", V.FILING_STATUSES)
    if tax_year not in V.TAX_YEARS:
        raise APIError("ERR_INVALID_REQUEST", 400, "tax_year must be 2025 or 2026")

    dependents = V.opt_int(body, "dependents_amount_cents", 0)
    other_income = V.opt_int(body, "other_income_cents", 0)
    deductions = V.opt_int(body, "deductions_cents", 0)
    extra = V.opt_int(body, "extra_withholding_cents", 0)
    supersedes_id = V.opt_str(body, "supersedes_w4_id", default=None)

    # Priority 4 — FK existence
    employee = db.employees.get(employee_id)
    if not employee:
        raise APIError(ERR_FK_NOT_FOUND, 404, "employee_id not found")
    if supersedes_id is not None:
        if supersedes_id not in db.w4_forms:
            raise APIError(ERR_FK_NOT_FOUND, 404, "supersedes_w4_id not found")

    # Priority 6 — employee not ACTIVE/ON_LEAVE
    if employee["status"] == "TERMINATED":
        raise APIError(ERR_EMPLOYEE_NOT_ACTIVE, 409, "employee is TERMINATED")

    # Priority 10 — supersede target validity
    _check_supersede_target(supersedes_id, employee_id, tax_year)

    w = {
        "id": db.new_id(),
        "employee_id": employee_id,
        "tax_year": tax_year,
        "filing_status": filing_status,
        "dependents_amount_cents": dependents,
        "other_income_cents": other_income,
        "deductions_cents": deductions,
        "extra_withholding_cents": extra,
        "supersedes_w4_id": supersedes_id,
        "status": "DRAFT",
        "filed_at": None,
    }
    db.stamp_common(w)
    db.w4_forms[w["id"]] = w
    return response.success_object(serialize.w4_form(w), status=201)


@bp.post("/w4-forms/<wid>/file")
@require_roles("HRClerk", "PayrollPreparer")
def file_w4(wid):
    w = db.w4_forms.get(wid)
    if not w:
        raise APIError(ERR_NOT_FOUND, 404, "W4Form not found")

    # Priority 5 — state guard
    if w["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "W4Form is not in DRAFT")

    # Priority 6 — employee not ACTIVE/ON_LEAVE
    employee = db.employees.get(w["employee_id"])
    if employee is None:
        # Defensive — shouldn't happen with referential integrity.
        raise APIError(ERR_NOT_FOUND, 404, "Employee not found")
    if employee["status"] == "TERMINATED":
        raise APIError(ERR_EMPLOYEE_NOT_ACTIVE, 409, "employee is TERMINATED")

    # Priority 10 — supersede target validity (re-checked at file time per scaffold)
    _check_supersede_target(w.get("supersedes_w4_id"), w["employee_id"], w["tax_year"])

    # Transition: DRAFT -> FILED
    w["status"] = "FILED"
    w["filed_at"] = db.now_utc()
    db.bump(w)

    # Cascade hop 1: prior W-4 -> SUPERSEDED
    sup_id = w.get("supersedes_w4_id")
    if sup_id:
        prior = db.w4_forms.get(sup_id)
        if prior and prior["status"] == "FILED":
            prior["status"] = "SUPERSEDED"
            db.bump(prior)

    # Cascade hop 2: recompute fed_withheld_cents for PENDING paychecks under DRAFT runs
    # for this employee, in this paycheck's pay_date.tax_year.
    from services import paycheck_pipeline
    for p in list(db.paychecks.values()):
        if p["employee_id"] != w["employee_id"]:
            continue
        if p["status"] != "PENDING":
            continue
        parent_run = db.paycheck_runs.get(p["paycheck_run_id"])
        if not parent_run or parent_run["status"] != "DRAFT":
            continue
        # Pay-date year must match this W-4's tax_year for the recompute to be
        # relevant; otherwise different tax-year W-4s drive different paychecks.
        from services import lookups
        if lookups.pay_date_year(parent_run["pay_date"]) != w["tax_year"]:
            continue
        # Recompute the entire pipeline so all dependents bump consistently.
        # Note: gross stays the same; the recompute changes fed_withheld and
        # downstream net_pay/garnishment (garnishment depends on disposable
        # earnings which include fed). Garnishment deductions are recomputed
        # accordingly.
        deductions = paycheck_pipeline.compute_paycheck_derived(p)
        db.bump(p)
        # Replace child garnishment deductions for this paycheck.
        existing_ids = [d["id"] for d in db.garnishment_deductions.values()
                        if d["paycheck_id"] == p["id"]]
        for did in existing_ids:
            del db.garnishment_deductions[did]
        for d in deductions:
            ded = {
                "id": db.new_id(),
                "paycheck_id": p["id"],
                "garnishment_order_id": d["garnishment_order_id"],
                "amount_cents": d["amount_cents"],
                "applied_at": None,
            }
            ded["created_at"] = db.now_utc()
            db.garnishment_deductions[ded["id"]] = ded
        # Update parent run total
        parent_run["total_gross_cents"] = sum(
            pp["gross_wages_cents"] for pp in db.paychecks.values()
            if pp["paycheck_run_id"] == parent_run["id"]
        )
        db.bump(parent_run)

    return response.success_object(serialize.w4_form(w))


@bp.get("/w4-forms/<wid>")
@require_roles("HRClerk", "PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def get_w4(wid):
    w = db.w4_forms.get(wid)
    if not w:
        raise APIError(ERR_NOT_FOUND, 404, "W4Form not found")
    return response.success_object(serialize.w4_form(w))


@bp.get("/w4-forms")
@require_roles("HRClerk", "PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def list_w4():
    limit, offset = pagination.parse_limit_offset()
    employee_id = V.opt_str(request.args, "employee_id")
    raw_year = request.args.get("tax_year")
    tax_year = None
    if raw_year is not None:
        try:
            tax_year = int(raw_year)
        except (TypeError, ValueError):
            raise APIError("ERR_INVALID_REQUEST", 400, "tax_year must be an integer")
    status = V.opt_enum(request.args, "status", V.W4_STATUSES)
    supersedes_id = V.opt_str(request.args, "supersedes_w4_id")

    items = list(db.w4_forms.values())
    if employee_id is not None:
        items = [w for w in items if w["employee_id"] == employee_id]
    if tax_year is not None:
        items = [w for w in items if w["tax_year"] == tax_year]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if supersedes_id is not None:
        items = [w for w in items if w.get("supersedes_w4_id") == supersedes_id]

    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.w4_form(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )
