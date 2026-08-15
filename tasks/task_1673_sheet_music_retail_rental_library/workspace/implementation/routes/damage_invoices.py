"""Damage invoices: DRAFT creation, issue (segregation of duties), payment,
dispute resolution, and reissue against a superseding assessment (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_CONDITION_REPORT_NOT_FOUND,
    ERR_DAMAGE_INVOICE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REASSESSMENT_REQUIRED,
    ERR_RENTAL_LINE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_auth
from response import success_object
from serializers import ser_invoice
from services import (
    apply_hold,
    compute_exposures,
    get_or_404,
    maybe_restore_standing,
)
from util import new_record, touch
from routes.helpers import body, paginate, require_fields

bp = Blueprint("damage_invoices", __name__)

READ_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "Customer")

_ACCEPT_TOKENS = {"RESOLVED_ACCEPTED", "ACCEPT", "ACCEPTED"}
_WAIVE_TOKENS = {"RESOLVED_WAIVED", "WAIVE", "WAIVED"}


def _supporting_report(invoice):
    return db["condition_reports"].get(invoice["condition_report_id"])


def _segregation_check(uid, invoice):
    report = _supporting_report(invoice)
    if report is not None and report["assessor_user_id"] == uid:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "Invoice issuer/resolver must differ from the condition assessor",
        )


def _account_of(invoice):
    return db["customer_accounts"].get(invoice["account_id"])


@bp.post("/library/damage-invoices")
def create_invoice():
    require_auth("BillingManager")
    data = body()
    require_fields(data, ["rental_line_id", "condition_report_id"])
    line = db["rental_lines"].get(data["rental_line_id"])
    if line is None:
        raise ApiError(ERR_RENTAL_LINE_NOT_FOUND, 404, "RentalLine not found")
    report = db["condition_reports"].get(data["condition_report_id"])
    if report is None:
        raise ApiError(ERR_CONDITION_REPORT_NOT_FOUND, 404, "ConditionReport not found")
    if report["rental_line_id"] != line["id"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Condition report does not belong to the given line")
    order = db["rental_orders"].get(line["rental_order_id"])
    rec = new_record()
    rec.update(
        {
            "rental_line_id": line["id"],
            "condition_report_id": report["id"],
            "account_id": order["account_id"] if order else None,
            "amount_cents": report["assessed_charge_cents"],
            "issuer_user_id": None,
            "status": "DRAFT",
        }
    )
    db["damage_invoices"][rec["id"]] = rec
    account = _account_of(rec)
    if account is not None:
        touch(account)  # open exposure recompute at creation
    return success_object(ser_invoice(rec), status=201)


@bp.get("/library/damage-invoices")
def list_invoices():
    require_auth(*READ_ROLES)
    rows = list(db["damage_invoices"].values())
    for param, field in (
        ("account_id", "account_id"),
        ("rental_line_id", "rental_line_id"),
        ("condition_report_id", "condition_report_id"),
    ):
        v = request.args.get(param)
        if v is not None:
            rows = [i for i in rows if i.get(field) == v]
    return paginate(rows, ser_invoice)


@bp.get("/library/damage-invoices/<iid>")
def get_invoice(iid):
    require_auth(*READ_ROLES)
    rec = get_or_404("damage_invoices", iid, ERR_DAMAGE_INVOICE_NOT_FOUND)
    return success_object(ser_invoice(rec))


@bp.post("/library/damage-invoices/<iid>/issue")
def issue_invoice(iid):
    uid, _ = require_auth("BillingManager")
    rec = get_or_404("damage_invoices", iid, ERR_DAMAGE_INVOICE_NOT_FOUND)
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT invoice may be issued")
    _segregation_check(uid, rec)  # tier 5
    rec["status"] = "ISSUED"
    rec["issuer_user_id"] = uid
    touch(rec)
    report = _supporting_report(rec)
    if report is not None and report["status"] == "FILED":
        report["status"] = "INVOICED"
        touch(report)
    account = _account_of(rec)
    if account is not None:
        touch(account)  # exposure recompute (invoice now counts in both sets)
        # If settled exposure reached a positive credit limit, flip to HOLD
        # with the PO suspension cascade.
        if account["credit_limit_cents"] > 0:
            _, settled = compute_exposures(account["id"])
            if settled >= account["credit_limit_cents"]:
                apply_hold(account)
    return success_object(ser_invoice(rec))


@bp.post("/library/damage-invoices/<iid>/record-payment")
def record_payment(iid):
    require_auth("BillingManager")
    rec = get_or_404("damage_invoices", iid, ERR_DAMAGE_INVOICE_NOT_FOUND)
    if rec["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ISSUED or DISPUTED invoice may be paid")
    rec["status"] = "PAID"
    touch(rec)
    account = _account_of(rec)
    if account is not None:
        touch(account)  # exposure recompute (leaves both sets)
        maybe_restore_standing(account)
    return success_object(ser_invoice(rec))


@bp.post("/library/damage-invoices/<iid>/resolve")
def resolve_invoice(iid):
    uid, _ = require_auth("BillingManager")
    rec = get_or_404("damage_invoices", iid, ERR_DAMAGE_INVOICE_NOT_FOUND)
    if rec["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DISPUTED invoice may be resolved")
    _segregation_check(uid, rec)  # tier 5
    data = body()
    resolution = data.get("resolution")
    if resolution in _ACCEPT_TOKENS:
        rec["status"] = "RESOLVED_ACCEPTED"  # amount stands
    elif resolution in _WAIVE_TOKENS:
        rec["status"] = "RESOLVED_WAIVED"  # collected 0, record preserved
    else:
        raise ApiError(ERR_INVALID_REQUEST, 400, "resolution must accept or waive")
    touch(rec)
    account = _account_of(rec)
    if account is not None:
        touch(account)  # exposure recompute (as if paid)
        maybe_restore_standing(account)
    return success_object(ser_invoice(rec))


@bp.post("/library/damage-invoices/<iid>/reissue")
def reissue_invoice(iid):
    require_auth("BillingManager")
    rec = get_or_404("damage_invoices", iid, ERR_DAMAGE_INVOICE_NOT_FOUND)
    if rec["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DISPUTED invoice may be re-issued")
    data = body()
    require_fields(data, ["new_condition_report_id"])
    new_report = db["condition_reports"].get(data["new_condition_report_id"])
    if new_report is None:
        raise ApiError(ERR_CONDITION_REPORT_NOT_FOUND, 404, "ConditionReport not found")
    # Requires a superseding assessment: FILED, same line, different charge.
    if (
        new_report["status"] != "FILED"
        or new_report["rental_line_id"] != rec["rental_line_id"]
        or new_report["assessed_charge_cents"] == rec["amount_cents"]
    ):
        raise ApiError(ERR_REASSESSMENT_REQUIRED, 409, "No superseding FILED report with a different charge")
    old_report = _supporting_report(rec)
    if old_report is not None:
        old_report["status"] = "SUPERSEDED"
        touch(old_report)
    new_report["status"] = "INVOICED"
    touch(new_report)
    rec["condition_report_id"] = new_report["id"]
    rec["amount_cents"] = new_report["assessed_charge_cents"]
    rec["status"] = "ISSUED"
    touch(rec)
    account = _account_of(rec)
    if account is not None:
        touch(account)  # exposure recompute
        maybe_restore_standing(account)
    return success_object(ser_invoice(rec))
