"""Invoice submission/verification/reject endpoints + verification reads
(§3.4)."""

from flask import Blueprint, request

import db
import errors
from common import (public, req_str, req_int, req_enum, req_datetime,
                    stamp_common, stamp_audit, touch)
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response
from services import calc
from services.views import invoice_view

bp = Blueprint("invoices", __name__)

VERIFY_METHODS = {"PHONE", "EMAIL", "PORTAL", "WAIVED"}


def _active_relationship(client_id, debtor_id):
    for rel in db.relationships.values():
        if (rel["client_id"] == client_id and rel["debtor_id"] == debtor_id
                and rel["status"] == "ACTIVE"):
            return rel
    return None


@bp.post("/factoring/invoices")
def submit_invoice():
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    body = get_body()
    client_id = req_str(body, "client_id")
    debtor_id = req_str(body, "debtor_id")
    if client_id not in db.clients:
        raise errors.not_found("client_id does not resolve")
    if debtor_id not in db.debtors:
        raise errors.not_found("debtor_id does not resolve")
    invoice_number = req_str(body, "invoice_number")
    face = req_int(body, "face_amount_cents", positive=True)
    issue_date = req_datetime(body, "issue_date")
    due_date = req_datetime(body, "due_date")
    if not (due_date > issue_date):
        raise errors.invalid_request("due_date must be strictly later than issue_date")

    # Uniqueness: invoice_number per client across non-REJECTED invoices.
    for inv in db.invoices.values():
        if (inv["client_id"] == client_id and inv["invoice_number"] == invoice_number
                and inv["status"] != "REJECTED"):
            raise errors.ApiError(errors.ERR_DUPLICATE_INVOICE_NUMBER, 409,
                                  "invoice_number already used by a non-REJECTED invoice")

    rel = _active_relationship(client_id, debtor_id)
    invoice = {
        "client_id": client_id,
        "debtor_id": debtor_id,
        "relationship_id": rel["id"] if rel else None,
        "invoice_number": invoice_number,
        "face_amount_cents": face,
        "issue_date": body["issue_date"],
        "due_date": body["due_date"],
        "advance_rate_pct": None,
        "fee_rate_per_day": None,
        "advance_amount_cents": 0,
        "reserve_held_cents": 0,
        "amount_collected_cents": 0,
        "dilution_cents": 0,
        "advance_outstanding_cents": 0,
        "accrued_fee_cents": 0,
        "final_fee_cents": None,
        "funded_at": None,
        "aging_bucket": "CURRENT",
        "status": "SUBMITTED",
    }
    stamp_common(invoice)
    db.invoices[invoice["id"]] = invoice
    return success(invoice_view(invoice), status=201)


@bp.get("/factoring/invoices")
def list_invoices():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    client_id = request.args.get("client_id")
    debtor_id = request.args.get("debtor_id")
    relationship_id = request.args.get("relationship_id")
    status = request.args.get("status")
    records = []
    for inv in db.invoices.values():
        if client_id is not None and inv["client_id"] != client_id:
            continue
        if debtor_id is not None and inv["debtor_id"] != debtor_id:
            continue
        if relationship_id is not None and inv["relationship_id"] != relationship_id:
            continue
        if status is not None and inv["status"] != status:
            continue
        records.append(inv)
    return list_response(records, view_fn=invoice_view)


@bp.get("/factoring/invoices/<invoice_id>")
def read_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    invoice = lookup(db.invoices, invoice_id)
    return success(invoice_view(invoice), status=200)


@bp.post("/factoring/invoices/<invoice_id>/verify")
def verify_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    invoice = lookup(db.invoices, invoice_id)
    body = get_body()
    method = req_enum(body, "method", VERIFY_METHODS)
    confirmed = req_int(body, "confirmed_amount_cents")

    if invoice["status"] != "SUBMITTED":
        raise errors.invalid_state("Invoice is not SUBMITTED")

    rel = db.relationships.get(invoice["relationship_id"]) if invoice["relationship_id"] else None
    if rel is None or rel["notice_status"] != "NOTICED":
        raise errors.ApiError(errors.ERR_NOTICE_NOT_SENT, 409,
                              "Relationship notice_status is not NOTICED")

    debtor = db.debtors.get(invoice["debtor_id"])
    if debtor and debtor["verification_required"]:
        if confirmed != invoice["face_amount_cents"]:
            raise errors.ApiError(errors.ERR_VERIFICATION_MISMATCH, 409,
                                  "confirmed_amount_cents must equal face_amount_cents")

    invoice["status"] = "VERIFIED"
    touch(invoice)

    verification = {
        "invoice_id": invoice_id,
        "method": method,
        "confirmed_amount_cents": confirmed,
        "notice_of_assignment_sent": True,
        "verified_at": db.clock_now().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    stamp_audit(verification)
    db.verifications[verification["id"]] = verification

    return success(invoice_view(invoice), status=200)


@bp.post("/factoring/invoices/<invoice_id>/reject")
def reject_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    invoice = lookup(db.invoices, invoice_id)
    if invoice["status"] != "SUBMITTED":
        raise errors.invalid_state("Invoice is not SUBMITTED")
    invoice["status"] = "REJECTED"
    touch(invoice)
    return success(invoice_view(invoice), status=200)


# --- Verification reads ----------------------------------------------------
@bp.get("/factoring/verifications")
def list_verifications():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    invoice_id = request.args.get("invoice_id")
    records = [v for v in db.verifications.values()
               if invoice_id is None or v["invoice_id"] == invoice_id]
    return list_response(records)


@bp.get("/factoring/verifications/<verification_id>")
def read_verification(verification_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    verification = lookup(db.verifications, verification_id)
    return success(public(verification), status=200)
