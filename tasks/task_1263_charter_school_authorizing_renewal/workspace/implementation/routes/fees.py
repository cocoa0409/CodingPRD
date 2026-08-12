"""Authorizer fee invoices (PRD §3.8)."""
from flask import Blueprint

import db
import errors
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    check_operator_owns,
    require_int,
    require_roles,
)
from response import success_object
from routes.common import get_or_404, paginate
from services import calc

bp = Blueprint("fees", __name__)


@bp.post("/authorizer/schools/<id>/fee-invoices")
def create_invoice(id):
    require_roles(["AuthorizerStaff"])
    school = get_or_404("schools", id)
    if school["status"] not in ("OPEN", "CLOSING"):
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "Fee invoice requires an OPEN or CLOSING school")
    data = body()
    fiscal_year = require_int(data, "fiscal_year")
    estimated_enrollment = require_int(data, "estimated_enrollment")
    base_per_pupil_cents = require_int(data, "base_per_pupil_cents")
    qualifying_supplemental_pupils = require_int(data, "qualifying_supplemental_pupils")
    if estimated_enrollment < 0 or base_per_pupil_cents < 0 or qualifying_supplemental_pupils < 0:
        raise_error(errors.ERR_INVALID_REQUEST, "Enrollment and cents fields must be >= 0")
    for inv in db.all_records("fee_invoices"):
        if inv["school_id"] == id and inv["fiscal_year"] == fiscal_year:
            raise_error(errors.ERR_DUPLICATE_RECORD, "Duplicate (school, fiscal_year) invoice")
    amounts = calc.compute_invoice_amounts(
        estimated_enrollment, base_per_pupil_cents, qualifying_supplemental_pupils
    )
    record = db.stamp_new({
        "school_id": id,
        "fiscal_year": fiscal_year,
        "estimated_enrollment": estimated_enrollment,
        "audited_enrollment": None,
        "base_per_pupil_cents": base_per_pupil_cents,
        "qualifying_supplemental_pupils": qualifying_supplemental_pupils,
        "base_funding_cents": amounts["base_funding_cents"],
        "supplemental_cents": amounts["supplemental_cents"],
        "total_funding_cents": amounts["total_funding_cents"],
        "fee_rate": amounts["fee_rate"],
        "billed_amount_cents": amounts["billed_amount_cents"],
        "billed_variant": "ESTIMATED",
        "paid_cents": 0,
        "waived_cents": 0,
        "status": "ESTIMATED",
    })
    db.insert("fee_invoices", record)
    return success_object(record, 201)


@bp.get("/authorizer/schools/<id>/fee-invoices")
def list_invoices(id):
    require_roles(ALL_ROLES)
    get_or_404("schools", id)
    records = [i for i in db.all_records("fee_invoices") if i["school_id"] == id]
    return paginate(records)


@bp.post("/authorizer/fee-invoices/<id>/finalize")
def finalize_invoice(id):
    require_roles(["AuthorizerStaff"])
    invoice = get_or_404("fee_invoices", id)
    if invoice["status"] != "ESTIMATED":
        raise_error(errors.ERR_INVOICE_INVALID_STATE, "Invoice is not ESTIMATED")
    data = body()
    audited = require_int(data, "audited_enrollment")
    if audited < 0:
        raise_error(errors.ERR_INVALID_REQUEST, "audited_enrollment must be >= 0")
    invoice["audited_enrollment"] = audited
    invoice["billed_variant"] = "FINAL"
    amounts = calc.compute_invoice_amounts(
        audited, invoice["base_per_pupil_cents"], invoice["qualifying_supplemental_pupils"]
    )
    invoice["base_funding_cents"] = amounts["base_funding_cents"]
    invoice["supplemental_cents"] = amounts["supplemental_cents"]
    invoice["total_funding_cents"] = amounts["total_funding_cents"]
    invoice["fee_rate"] = amounts["fee_rate"]
    invoice["billed_amount_cents"] = amounts["billed_amount_cents"]
    invoice["status"] = "FINALIZED"
    db.touch(invoice)
    return success_object(invoice)


@bp.post("/authorizer/fee-invoices/<id>/pay")
def pay_invoice(id):
    user_id, role = require_roles(["SchoolOperator"])
    invoice = get_or_404("fee_invoices", id)
    check_operator_owns(user_id, role, invoice["school_id"])
    if invoice["status"] != "FINALIZED":
        raise_error(errors.ERR_INVOICE_INVALID_STATE, "Invoice is not FINALIZED")
    invoice["paid_cents"] = invoice["billed_amount_cents"]
    invoice["status"] = "PAID"
    db.touch(invoice)
    return success_object(invoice)


@bp.post("/authorizer/fee-invoices/<id>/waive")
def waive_invoice(id):
    require_roles(["BoardMember"])
    invoice = get_or_404("fee_invoices", id)
    if invoice["status"] != "FINALIZED" or invoice["paid_cents"] != 0:
        raise_error(errors.ERR_INVOICE_INVALID_STATE, "Invoice is not FINALIZED with zero paid")
    invoice["waived_cents"] = invoice["billed_amount_cents"]
    invoice["status"] = "WAIVED"
    db.touch(invoice)
    return success_object(invoice)
