"""IRS Form 1098-C tax receipts (PRD section 3.8)."""

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import calc, domain

bp = Blueprint("receipts", __name__)

RECEIPT_STATUSES = {"DRAFT", "ISSUED", "VOIDED"}
READ_ROLES = ("FinanceOfficer", "ProgramAdmin", "Donor")


def _revalue(receipt, donation):
    receipt.update(calc.tax_receipt_valuation(donation))


@bp.post("/api/tax-receipts")
def draft_receipt():
    mw.auth("FinanceOfficer")
    data = mw.body()
    donation_id = mw.req_string(data, "donation_id")
    donation = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")

    if donation["status"] not in ("SOLD", "UNSOLD"):
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "This donation is not eligible for a receipt."
        )
    title = domain.title_for_donation(donation_id)
    if title is None or title["state"] != "CLEARED":
        raise ApiError("ERR_TITLE_NOT_CLEARED", "The donation's title is not cleared.")
    if domain.active_receipt(donation_id) is not None:
        raise ApiError(
            "ERR_RECEIPT_ALREADY_ACTIVE", "This donation already holds an active receipt."
        )
    if domain.vehicle_for_donation(donation_id) is None:
        raise ApiError("ERR_VEHICLE_RECORD_MISSING", "This donation has no asset record.")

    rec = db.new_record()
    rec["donation_id"] = donation_id
    rec["status"] = "DRAFT"
    rec["control_number"] = None
    rec["issued_at_utc"] = None
    rec["issued_by_user_id"] = None
    rec["void_reason"] = None
    rec["reissue_count"] = 0
    _revalue(rec, donation)
    db.tax_receipts[rec["id"]] = rec

    domain.create_task(
        donation_id,
        "RECEIPT_DELIVERY",
        "FinanceOfficer",
        db.now() + db.days(db.RECEIPT_DUE_DAYS),
    )
    return resp.created(rec)


@bp.get("/api/tax-receipts/<receipt_id>")
def get_receipt(receipt_id):
    mw.auth(*READ_ROLES)
    rec = mw.resolve(db.tax_receipts, receipt_id, "ERR_TAX_RECEIPT_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/tax-receipts")
def list_receipts():
    mw.auth(*READ_ROLES)
    donation_filter = request.args.get("donation_id")
    status = mw.query_enum("status", RECEIPT_STATUSES)
    limit, offset = mw.pagination()
    rows = []
    for rec in db.tax_receipts.values():
        if donation_filter is not None and rec["donation_id"] != donation_filter:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return resp.listing(db.ordered(rows), limit, offset)


@bp.post("/api/tax-receipts/<receipt_id>/issue")
def issue_receipt(receipt_id):
    user_id, _role = mw.auth("FinanceOfficer")
    rec = mw.resolve(db.tax_receipts, receipt_id, "ERR_TAX_RECEIPT_NOT_FOUND")

    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_RECEIPT_STATE", "Only a draft receipt may be issued.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] not in ("SOLD", "UNSOLD"):
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "This donation is not eligible for issue."
        )
    title = domain.title_for_donation(donation["id"])
    if title is None or title["state"] != "CLEARED":
        raise ApiError("ERR_TITLE_NOT_CLEARED", "The donation's title is not cleared.")

    rec["status"] = "ISSUED"
    rec["control_number"] = db.next_control_number()
    rec["issued_at_utc"] = db.now()
    rec["issued_by_user_id"] = user_id
    _revalue(rec, donation)
    db.touch(rec)

    donation["status"] = "CLOSED"
    donation["deduction_amount_cents"] = rec["claimed_amount_cents"]
    db.touch(donation)
    domain.complete_tasks(donation["id"], "RECEIPT_DELIVERY", "receipt issued")
    return resp.ok(rec)


@bp.post("/api/tax-receipts/<receipt_id>/void")
def void_receipt(receipt_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.tax_receipts, receipt_id, "ERR_TAX_RECEIPT_NOT_FOUND")
    data = mw.body()
    void_reason = mw.req_string(data, "void_reason")

    if rec["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_RECEIPT_STATE", "Only an issued receipt may be voided.")

    rec["status"] = "VOIDED"
    rec["void_reason"] = void_reason
    rec["control_number"] = None
    db.touch(rec)

    donation = db.donations.get(rec["donation_id"])
    if donation is not None:
        donation["status"] = "SOLD" if donation["gross_proceeds_cents"] > 0 else "UNSOLD"
        donation["deduction_amount_cents"] = None
        db.touch(donation)
    return resp.ok(rec)


@bp.post("/api/tax-receipts/<receipt_id>/reissue")
def reissue_receipt(receipt_id):
    mw.auth("FinanceOfficer")
    rec = mw.resolve(db.tax_receipts, receipt_id, "ERR_TAX_RECEIPT_NOT_FOUND")

    if rec["status"] != "VOIDED":
        raise ApiError(
            "ERR_INVALID_RECEIPT_STATE", "Only a voided receipt may be reissued."
        )
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] not in ("SOLD", "UNSOLD"):
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "This donation is not eligible for reissue."
        )

    rec["status"] = "DRAFT"
    rec["reissue_count"] += 1
    rec["void_reason"] = None
    _revalue(rec, donation)
    db.touch(rec)
    return resp.ok(rec)
