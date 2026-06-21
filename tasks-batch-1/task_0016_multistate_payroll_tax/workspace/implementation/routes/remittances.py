"""Remittance endpoints (read, list, close-period, remit)."""
from flask import Blueprint, request

import db
import response
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_REMITTANCE_AMOUNT_MISMATCH,
    ERR_OPEN_RUN_BLOCKS_CLOSE,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from services import serialize, pagination, lookups
from services import validation as V


bp = Blueprint("remittances", __name__)


@bp.get("/remittances/<rid>")
@require_roles("PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def get_remittance(rid):
    r = db.remittances.get(rid)
    if not r:
        raise APIError(ERR_NOT_FOUND, 404, "Remittance not found")
    return response.success_object(serialize.remittance(r))


@bp.get("/remittances")
@require_roles("PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def list_remittances():
    limit, offset = pagination.parse_limit_offset()
    period_month = V.opt_str(request.args, "period_month")
    jurisdiction = V.opt_str(request.args, "jurisdiction")
    tax_type = V.opt_enum(request.args, "tax_type", V.TAX_TYPES)
    status = V.opt_enum(request.args, "status", V.REMITTANCE_STATUSES)

    items = list(db.remittances.values())
    if period_month:
        items = [r for r in items if r["period_month"] == period_month]
    if jurisdiction:
        items = [r for r in items if r["jurisdiction"] == jurisdiction]
    if tax_type:
        items = [r for r in items if r["tax_type"] == tax_type]
    if status:
        items = [r for r in items if r["status"] == status]

    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.remittance(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/remittances/<rid>/close-period")
@require_roles("ComplianceOfficer")
def close_period(rid):
    r = db.remittances.get(rid)
    if not r:
        raise APIError(ERR_NOT_FOUND, 404, "Remittance not found")

    # Priority 5 — state guard
    if r["status"] != "ACCRUING":
        raise APIError(ERR_INVALID_STATE, 409, "Remittance is not in ACCRUING")

    # Priority 14 — open-run blocks close
    period_month = r["period_month"]
    for run in db.paycheck_runs.values():
        if lookups.period_month_of(run["pay_date"]) != period_month:
            continue
        if run["status"] in ("DRAFT", "APPROVED"):
            raise APIError(ERR_OPEN_RUN_BLOCKS_CLOSE, 409,
                           "PaycheckRun still DRAFT or APPROVED in this period_month")
        # Also: no Paycheck in PENDING under this run's pay_date.month
        for p in db.paychecks.values():
            if p["paycheck_run_id"] == run["id"] and p["status"] == "PENDING":
                raise APIError(ERR_OPEN_RUN_BLOCKS_CLOSE, 409,
                               "Paycheck still PENDING in this period_month")

    # Reconciled aggregation: full re-scan over PAID paychecks in this month
    # whose jurisdiction/tax_type match r.
    bucket_total = 0
    paychecks_ordered = sorted(db.paychecks.values(), key=lambda p: p["created_at"])
    for p in paychecks_ordered:
        if p["status"] != "PAID":
            continue
        run = db.paycheck_runs.get(p["paycheck_run_id"])
        if not run:
            continue
        if lookups.period_month_of(run["pay_date"]) != period_month:
            continue
        for jur, tax_type, value in lookups.remittance_jurisdictions_for(p):
            if jur == r["jurisdiction"] and tax_type == r["tax_type"]:
                bucket_total += value

    r["reconciled_cents"] = bucket_total
    r["status"] = "RECONCILED"
    db.bump(r)
    return response.success_object(serialize.remittance(r))


@bp.post("/remittances/<rid>/remit")
@require_roles("ComplianceOfficer")
def remit(rid):
    r = db.remittances.get(rid)
    if not r:
        raise APIError(ERR_NOT_FOUND, 404, "Remittance not found")

    body = V.require_dict(request.get_json(silent=True) or {})
    paid_cents = V.require_int(body, "paid_cents")
    expected_version = V.require_int(body, "expected_remittance_version")

    # Priority 5 — state guard
    if r["status"] != "RECONCILED":
        raise APIError(ERR_INVALID_STATE, 409, "Remittance is not in RECONCILED")

    # Priority 13 — exact-amount remittance check (also: must be > 0)
    if paid_cents <= 0:
        raise APIError(ERR_REMITTANCE_AMOUNT_MISMATCH, 422,
                       "paid_cents must be greater than zero")
    if paid_cents != r["reconciled_cents"]:
        raise APIError(ERR_REMITTANCE_AMOUNT_MISMATCH, 422,
                       "paid_cents must equal reconciled_cents")

    # Priority 15 — OCC stale-version check
    if expected_version != r["version"]:
        raise APIError(ERR_STALE_VERSION, 412,
                       "expected_remittance_version is stale")

    r["status"] = "REMITTED"
    r["paid_cents"] = paid_cents
    db.bump(r)
    return response.success_object(serialize.remittance(r))
