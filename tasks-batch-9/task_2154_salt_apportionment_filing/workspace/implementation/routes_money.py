"""Estimated remittances, their application lifecycle, and extensions."""
from flask import Blueprint

from calc import (compute_installment_figures, derive_posture, extensions_of,
                  group_of_filing, installment_due_date, payments_of_registration,
                  recompute_balance, recompute_registration_pools,
                  registration_of_filing, EXTENSION_PREPAY_PCT)
from errors import ApiError, invalid
from models import (find_extension, find_filing, find_payment, find_registration,
                    ser_extension, ser_payment)
from routes_reg import guard_not_withdrawn
from store import db
from util import (add_months, money, opt_str, req_dt, req_enum, req_int, req_num,
                  req_str, D, ZERO)
from web import (ANY_ROLE, body_json, bump, created, endpoint, new_record, ok,
                 paginate, query_int, query_str, sort_created)

bp = Blueprint("money", __name__)

DECISIONS = ("GRANTED", "DENIED")


# --------------------------------------------------------------------------
# EstimatedPayment
# --------------------------------------------------------------------------
@bp.route("/salt/registrations/<rid>/payments", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def create_payment(rid):
    reg = find_registration(rid)
    body = body_json()
    tax_year = req_int(body, "tax_year")
    installment_number = req_int(body, "installment_number", minv=1, maxv=4)
    amount = req_num(body, "amount")
    if amount <= 0:
        raise invalid("'amount' must be greater than zero")
    paid_on_date = req_dt(body, "paid_on_date")
    expected_registration_version = req_int(body, "expected_registration_version")

    if expected_registration_version != reg["version"]:
        raise ApiError("ERR_STALE_REGISTRATION_VERSION",
                       "expected_registration_version does not match the registration's "
                       "current version.")

    guard_not_withdrawn(reg)

    for other in payments_of_registration(reg["id"]):
        if (other["tax_year"] == tax_year
                and other["installment_number"] == installment_number):
            raise ApiError("ERR_DUPLICATE_INSTALLMENT",
                           "An installment already occupies this slot.")

    payment = new_record()
    payment.update({
        "registration_id": reg["id"],
        "applied_filing_id": None,
        "tax_year": tax_year,
        "installment_number": installment_number,
        "amount": amount,
        "paid_on_date": paid_on_date,
        "due_date": installment_due_date(tax_year, installment_number),
        "is_timely": True,
        "safe_harbor_required_amount": money(ZERO),
        "underpayment_amount": money(ZERO),
        "underpayment_penalty": money(ZERO),
        "status": "RECEIVED",
    })
    payment["is_timely"] = paid_on_date <= payment["due_date"]
    db.payments[payment["id"]] = payment

    compute_installment_figures(reg, payment)
    recompute_registration_pools(reg)
    bump(reg)
    return created(ser_payment(payment))


@bp.route("/salt/payments/<pid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_payment(pid):
    return ok(ser_payment(find_payment(pid)))


@bp.route("/salt/payments", methods=["GET"])
@endpoint(ANY_ROLE)
def list_payments():
    registration_id = query_str("registration_id")
    applied_filing_id = query_str("applied_filing_id")
    status = query_str("status")
    tax_year = query_int("tax_year")
    rows = list(db.payments.values())
    if registration_id is not None:
        rows = [p for p in rows if p["registration_id"] == registration_id]
    if applied_filing_id is not None:
        rows = [p for p in rows if p["applied_filing_id"] == applied_filing_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if tax_year is not None:
        rows = [p for p in rows if p["tax_year"] == tax_year]
    return paginate(sort_created(rows), ser_payment)


@bp.route("/salt/payments/<pid>/apply", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def apply_payment(pid):
    payment = find_payment(pid)
    body = body_json()

    raw_filing = body.get("filing_id")
    filing = find_filing(raw_filing) if raw_filing is not None else None
    if filing is None:
        raise invalid("'filing_id' is required")

    if payment["status"] not in ("RECEIVED", "UNAPPLIED"):
        raise ApiError("ERR_INVALID_PAYMENT_STATE",
                       "Only a received or unapplied remittance may be applied.")
    if filing["registration_id"] != payment["registration_id"]:
        raise ApiError("ERR_FILING_REGISTRATION_MISMATCH",
                       "The target return belongs to a different state registration.")
    if filing["tax_year"] != payment["tax_year"]:
        raise ApiError("ERR_PAYMENT_TAX_YEAR_MISMATCH",
                       "The target return covers a different tax year.")
    if filing["preparation_status"] == "DRAFT":
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "Money may not be applied to a return that is still in DRAFT.")

    payment["status"] = "APPLIED"
    payment["applied_filing_id"] = filing["id"]
    recompute_registration_pools(db.registrations[payment["registration_id"]])
    recompute_balance(filing)
    bump(payment)
    bump(filing)
    derive_posture(group_of_filing(filing))
    return ok(ser_payment(payment))


@bp.route("/salt/payments/<pid>/unapply", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def unapply_payment(pid):
    payment = find_payment(pid)
    body = body_json()
    req_str(body, "reason")

    if payment["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_PAYMENT_STATE",
                       "Only an applied remittance may be detached.")

    filing = db.filings.get(payment.get("applied_filing_id"))
    if filing is not None and filing["payment_status"] == "REFUND_CLAIMED":
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "The return has already reached REFUND_CLAIMED.")

    payment["status"] = "UNAPPLIED"
    payment["applied_filing_id"] = None
    recompute_registration_pools(db.registrations[payment["registration_id"]])
    bump(payment)
    if filing is not None:
        recompute_balance(filing)
        bump(filing)
        derive_posture(group_of_filing(filing))
    return ok(ser_payment(payment))


# --------------------------------------------------------------------------
# ExtensionRequest
# --------------------------------------------------------------------------
@bp.route("/salt/filings/<fid>/extensions", methods=["POST"])
@endpoint(["StateAnalyst", "TaxManager"])
def create_extension(fid):
    filing = find_filing(fid)
    body = body_json()
    estimated_tax_paid = req_num(body, "estimated_tax_paid", minv=0)

    if filing["preparation_status"] not in ("FACTORS_LOCKED", "IN_REVIEW", "APPROVED"):
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "An extension may only be requested on a frozen, in-review or approved "
                       "return.")

    if db.clock > filing["original_due_date"]:
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED",
                       "The extension window for this return has closed.")

    required_prepayment = money(D(filing["tax_before_credits"]) * EXTENSION_PREPAY_PCT)
    if estimated_tax_paid < required_prepayment:
        raise ApiError("ERR_EXTENSION_PREPAYMENT_INSUFFICIENT",
                       "The extension prepayment threshold has not been met.")

    extension = new_record()
    extension.update({
        "filing_id": filing["id"],
        "estimated_tax_paid": estimated_tax_paid,
        "requested_on_date": db.clock,
        "required_prepayment": required_prepayment,
        "status": "REQUESTED",
        "new_due_date": None,
        "state_confirmation": None,
    })
    db.extensions[extension["id"]] = extension
    return created(ser_extension(extension))


@bp.route("/salt/filings/<fid>/extensions", methods=["GET"])
@endpoint(ANY_ROLE)
def list_extensions(fid):
    filing = find_filing(fid)
    return paginate(extensions_of(filing), ser_extension)


@bp.route("/salt/extensions/<xid>/acknowledge", methods=["POST"])
@endpoint(["TaxManager"])
def acknowledge_extension(xid):
    extension = find_extension(xid)
    body = body_json()
    decision = req_enum(body, "decision", DECISIONS)
    state_confirmation = opt_str(body, "state_confirmation", None)

    if extension["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_EXTENSION_STATE",
                       "This extension request has already been acknowledged.")

    filing = db.filings[extension["filing_id"]]
    reg = registration_of_filing(filing)
    extension["state_confirmation"] = state_confirmation
    if decision == "GRANTED":
        new_due_date = add_months(filing["original_due_date"], reg["extension_months"])
        extension["status"] = "GRANTED"
        extension["new_due_date"] = new_due_date
        filing["extended_due_date"] = new_due_date
        bump(filing)
    else:
        extension["status"] = "DENIED"
    bump(extension)
    return ok(ser_extension(extension))
