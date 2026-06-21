"""ServicingReport (1502) endpoints — PRD §3.9, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_int, require_nonneg_int,
    optional_nonneg_int, paginate, sort_by_created,
)

bp = Blueprint("servicing_reports", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/servicing-reports")
def create_servicing_report():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    period_index = require_nonneg_int(body, "period_index")
    period_start = require_nonneg_int(body, "period_start_month")
    period_end = require_nonneg_int(body, "period_end_month")
    principal_paid = require_nonneg_int(body, "principal_paid_cents")
    interest_paid = require_nonneg_int(body, "interest_paid_cents")
    days_past_due = optional_nonneg_int(body, "days_past_due", default=0)
    # Closed interval must be well-ordered: start <= end.
    if period_start > period_end:
        raise errors.invalid_request("period_start_month must be <= period_end_month")
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.invalid_request("application_id does not reference an existing Application")
        rec = db.init_record({
            "application_id": application_id,
            "period_index": period_index,
            "period_start_month": period_start,
            "period_end_month": period_end,
            "principal_paid_cents": principal_paid,
            "interest_paid_cents": interest_paid,
            "days_past_due": days_past_due,
            "ongoing_fee_cents": 0,
            "status": "PENDING",
        })
        db.servicing_reports[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/servicing-reports")
def list_servicing_reports(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [r for r in db.servicing_reports.values() if r["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/sba/servicing-reports/<report_id>/accept")
def accept_servicing_report(report_id):
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer"])
    with db.LOCK:
        rep = db.servicing_reports.get(report_id)
        if rep is None:
            raise errors.not_found("ServicingReport not found")
        app = db.applications.get(rep["application_id"])
        if rep["status"] != "PENDING":
            raise errors.invalid_state("ServicingReport is not PENDING")
        # business preconditions in PRD §3.9 order:
        # 1. contiguous interval.
        accepted = [r for r in db.servicing_reports.values()
                    if r["application_id"] == app["id"] and r["status"] == "ACCEPTED"]
        if accepted:
            expected_start = max(r["period_end_month"] for r in accepted) + 1
        else:
            expected_start = 0
        if rep["period_start_month"] != expected_start:
            raise errors.err(errors.ERR_PERIOD_OUT_OF_ORDER, 409,
                             "Coverage interval is not contiguous with prior accepted reports")
        # 2. principal overpay.
        if rep["principal_paid_cents"] > app["outstanding_principal_cents"]:
            raise errors.err(errors.ERR_PRINCIPAL_OVERPAY, 422,
                             "principal_paid_cents exceeds outstanding principal")
        # cascade in fixed order (PRD §3.9):
        # 1. ongoing fee computed on outstanding BEFORE this report's principal.
        fee = calc.ongoing_fee(app["outstanding_principal_cents"], app["guaranty_pct"])
        rep["ongoing_fee_cents"] = fee
        rep["status"] = "ACCEPTED"
        db.touch(rep)
        # 2. credit lender pool.
        lender = db.lenders[app["lender_id"]]
        lender["ongoing_fee_pool_cents"] += fee
        db.touch(lender)
        # 3. reduce outstanding principal.
        app["outstanding_principal_cents"] -= rep["principal_paid_cents"]
        # 4. re-evaluate servicing axis.
        if app["outstanding_principal_cents"] == 0 and app["servicing_status"] == "CURRENT":
            app["servicing_status"] = "PAID_IN_FULL"
        elif rep["days_past_due"] >= 60:
            if app["servicing_status"] == "CURRENT":
                app["servicing_status"] = "DELINQUENT"
        else:  # days_past_due < 60 (cure edge)
            if app["servicing_status"] == "DELINQUENT":
                app["servicing_status"] = "CURRENT"
        db.touch(app)
        return object_response(serialize(rep), 200)


@bp.post("/sba/servicing-reports/<report_id>/reject")
def reject_servicing_report(report_id):
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer"])
    with db.LOCK:
        rep = db.servicing_reports.get(report_id)
        if rep is None:
            raise errors.not_found("ServicingReport not found")
        if rep["status"] != "PENDING":
            raise errors.invalid_state("ServicingReport is not PENDING")
        rep["status"] = "REJECTED"
        db.touch(rep)
        return object_response(serialize(rep), 200)
