"""RemittanceReport endpoints."""

from flask import Blueprint, request

import db
from calculations import remittance_aggregation
from errors import (
    ApiError, ERR_RESOURCE_INVALID_STATE, ERR_BATCH_NOT_DISBURSED,
)
from helpers import new_id, now_timestamp, require_string, err_validation
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("remittance_reports", __name__)


@bp.post("/payroll/remittance-reports")
def create_remittance_report():
    require_roles({"PayrollClerk"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    pay_batch_id = require_string(body, "pay_batch_id")
    union_agreement_id = require_string(body, "union_agreement_id")

    # FK existence (priority 3), left to right
    batch = get_or_404(db.pay_batches, pay_batch_id, "PayBatch")
    get_or_404(db.union_agreements, union_agreement_id, "UnionAgreement")

    # Batch must be DISBURSED (priority 27)
    if batch["status"] != "DISBURSED":
        raise ApiError(
            ERR_BATCH_NOT_DISBURSED,
            "Remittance creation requires the batch to be DISBURSED",
            409,
        )

    pension, health, welfare = remittance_aggregation(pay_batch_id, union_agreement_id)

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "pay_batch_id": pay_batch_id,
        "union_agreement_id": union_agreement_id,
        "pension_cents": pension,
        "health_cents": health,
        "welfare_cents": welfare,
        "status": "DRAFT",
    }
    db.remittance_reports[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/remittance-reports")
def list_remittance_reports():
    require_roles(ALL_ROLES)
    items = list(db.remittance_reports.values())
    pay_batch_id = request.args.get("pay_batch_id")
    if pay_batch_id is not None:
        items = [r for r in items if r["pay_batch_id"] == pay_batch_id]
    union_agreement_id = request.args.get("union_agreement_id")
    if union_agreement_id is not None:
        items = [r for r in items if r["union_agreement_id"] == union_agreement_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response([serialize(r) for r in items], request.args)


@bp.get("/payroll/remittance-reports/<report_id>")
def get_remittance_report(report_id):
    require_roles(ALL_ROLES)
    report = get_or_404(db.remittance_reports, report_id, "RemittanceReport")
    return success_object(serialize(report), 200)


@bp.post("/payroll/remittance-reports/<report_id>/submit")
def submit_remittance_report(report_id):
    require_roles({"PayrollClerk"})
    report = get_or_404(db.remittance_reports, report_id, "RemittanceReport")

    if report["status"] != "DRAFT":
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Remittance submit requires status DRAFT",
            409,
        )

    report["status"] = "SUBMITTED"
    bump_version(report)
    return success_object(serialize(report), 200)


@bp.post("/payroll/remittance-reports/<report_id>/acknowledge")
def acknowledge_remittance_report(report_id):
    require_roles({"PayrollAdmin"})
    report = get_or_404(db.remittance_reports, report_id, "RemittanceReport")

    if report["status"] != "SUBMITTED":
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Remittance acknowledge requires status SUBMITTED",
            409,
        )

    report["status"] = "ACKNOWLEDGED"
    bump_version(report)
    return success_object(serialize(report), 200)
