"""Collections, adjustments, close-collection, buyback, write-off, settlement
reads (§3.6-§3.8)."""

from flask import Blueprint, request

import db
import errors
from common import (public, req_int, req_enum, req_datetime, opt_enum,
                    stamp_common, touch)
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response
from services import calc, transitions
from services.views import invoice_view

bp = Blueprint("collections", __name__)

PAYERS = {"DEBTOR", "CLIENT"}
ADJ_TYPES = {"DILUTION", "CREDIT_MEMO", "CHARGEBACK_FEE"}
BUYBACK_REASONS = {"RECOURSE_OVERDUE", "DEBTOR_DISPUTE", "CLIENT_REQUEST"}


def _check_client_occ(client, body):
    """Priority-8 OCC check: expected_client_version must match Client.version."""
    if "expected_client_version" not in body or body["expected_client_version"] is None:
        raise errors.invalid_request("expected_client_version is required")
    expected = body["expected_client_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_client_version must be an integer")
    if expected != client["version"]:
        raise errors.stale_version()


# ---------------------------------------------------------------------------
# POST /factoring/invoices/{invoiceId}/postings
# ---------------------------------------------------------------------------
@bp.post("/factoring/invoices/<invoice_id>/postings")
def post_collection(invoice_id):
    _, role = authenticate()
    authorize(role, ("CollectionsOfficer",))
    invoice = lookup(db.invoices, invoice_id)
    body = get_body()
    amount = req_int(body, "amount_cents", positive=True)
    req_datetime(body, "received_at")
    payer = opt_enum(body, "payer", PAYERS, default="DEBTOR")
    client = db.clients.get(invoice["client_id"])

    # OCC (priority 8) before state validity (priority 10).
    _check_client_occ(client, body)

    if invoice["status"] not in ("FUNDED", "OUTSTANDING"):
        raise errors.invalid_state("Invoice is not in a collectible state")

    # Overpayment guard: amount may not exceed remaining collectible face.
    dilution = calc.dilution_cents(invoice_id)
    collected = calc.amount_collected(invoice_id)
    remaining = invoice["face_amount_cents"] - dilution - collected
    if amount > remaining:
        raise errors.ApiError(errors.ERR_OVERPAYMENT, 409,
                              "Posting amount exceeds remaining collectible face")

    posting = {
        "invoice_id": invoice_id,
        "amount_cents": amount,
        "received_at": body["received_at"],
        "payer": payer,
        "status": "POSTED",
    }
    stamp_common(posting)
    db.collection_postings[posting["id"]] = posting
    touch(invoice)

    # Auto-settle when fully collected.
    new_collected = calc.amount_collected(invoice_id)
    collectible = invoice["face_amount_cents"] - calc.dilution_cents(invoice_id)
    if new_collected >= collectible:
        debtor = db.debtors.get(invoice["debtor_id"])
        program = db.programs.get(client["program_id"])
        transitions.settle_invoice(invoice, client, debtor, program)

    # Every posting is an OCC-guarded write against the client: bump version so
    # a later posting reusing the caller's prior version sees ERR_STALE_VERSION.
    touch(client)

    return success(public(posting), status=201)


@bp.get("/factoring/collection-postings")
def list_postings():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    invoice_id = request.args.get("invoice_id")
    status = request.args.get("status")
    records = []
    for p in db.collection_postings.values():
        if invoice_id is not None and p["invoice_id"] != invoice_id:
            continue
        if status is not None and p["status"] != status:
            continue
        records.append(p)
    return list_response(records)


@bp.get("/factoring/collection-postings/<posting_id>")
def read_posting(posting_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    posting = lookup(db.collection_postings, posting_id)
    return success(public(posting), status=200)


@bp.post("/factoring/postings/<posting_id>/reverse")
def reverse_posting(posting_id):
    _, role = authenticate()
    authorize(role, ("CollectionsOfficer",))
    posting = lookup(db.collection_postings, posting_id)
    if posting["status"] != "POSTED":
        raise errors.ApiError(errors.ERR_OVERPAYMENT, 409,
                              "Only a POSTED posting may be reversed")
    posting["status"] = "REVERSED"
    touch(posting)
    invoice = db.invoices.get(posting["invoice_id"])
    if invoice is not None:
        touch(invoice)
    return success(public(posting), status=200)


# ---------------------------------------------------------------------------
# POST /factoring/invoices/{invoiceId}/adjustments
# ---------------------------------------------------------------------------
@bp.post("/factoring/invoices/<invoice_id>/adjustments")
def create_adjustment(invoice_id):
    _, role = authenticate()
    authorize(role, ("CollectionsOfficer", "FundingOfficer"))
    invoice = lookup(db.invoices, invoice_id)
    body = get_body()
    adj_type = req_enum(body, "type", ADJ_TYPES)
    amount = req_int(body, "amount_cents", positive=True)
    from common import req_str
    reason = req_str(body, "reason")

    adj = {
        "invoice_id": invoice_id,
        "type": adj_type,
        "amount_cents": amount,
        "reason": reason,
    }
    stamp_common(adj)
    db.adjustments[adj["id"]] = adj
    touch(invoice)
    return success(public(adj), status=201)


@bp.get("/factoring/adjustments")
def list_adjustments():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    invoice_id = request.args.get("invoice_id")
    adj_type = request.args.get("type")
    records = []
    for a in db.adjustments.values():
        if invoice_id is not None and a["invoice_id"] != invoice_id:
            continue
        if adj_type is not None and a["type"] != adj_type:
            continue
        records.append(a)
    return list_response(records)


@bp.get("/factoring/adjustments/<adjustment_id>")
def read_adjustment(adjustment_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    adj = lookup(db.adjustments, adjustment_id)
    return success(public(adj), status=200)


# ---------------------------------------------------------------------------
# POST /factoring/invoices/{invoiceId}/close-collection (OUTSTANDING->SHORT_PAID)
# ---------------------------------------------------------------------------
@bp.post("/factoring/invoices/<invoice_id>/close-collection")
def close_collection(invoice_id):
    _, role = authenticate()
    authorize(role, ("CollectionsOfficer",))
    invoice = lookup(db.invoices, invoice_id)
    if invoice["status"] != "OUTSTANDING":
        raise errors.invalid_state("Invoice is not OUTSTANDING")
    collected = calc.amount_collected(invoice_id)
    collectible = invoice["face_amount_cents"] - calc.dilution_cents(invoice_id)
    if not (0 < collected < collectible):
        raise errors.invalid_state("Invoice is not partially collected")

    client = db.clients.get(invoice["client_id"])
    debtor = db.debtors.get(invoice["debtor_id"])
    program = db.programs.get(client["program_id"])
    transitions.short_pay_invoice(invoice, client, debtor, program)
    touch(client)
    return success(invoice_view(invoice), status=200)


# ---------------------------------------------------------------------------
# POST /factoring/invoices/{invoiceId}/buyback
# ---------------------------------------------------------------------------
@bp.post("/factoring/invoices/<invoice_id>/buyback")
def buyback(invoice_id):
    _, role = authenticate()
    authorize(role, ("CollectionsOfficer",))
    invoice = lookup(db.invoices, invoice_id)
    body = get_body()
    trigger_reason = req_enum(body, "trigger_reason", BUYBACK_REASONS)

    if invoice["status"] not in ("SHORT_PAID", "OUTSTANDING"):
        raise errors.invalid_state("Invoice is not SHORT_PAID or OUTSTANDING")

    rel = db.relationships.get(invoice["relationship_id"]) if invoice["relationship_id"] else None
    recourse_type = rel["recourse_type"] if rel else None
    has_dilution = any(a["invoice_id"] == invoice_id and a["type"] == "DILUTION"
                       for a in db.adjustments.values())

    client = db.clients.get(invoice["client_id"])
    debtor = db.debtors.get(invoice["debtor_id"])
    program = db.programs.get(client["program_id"])

    if invoice["status"] == "SHORT_PAID":
        # Eligible when RECOURSE or a DILUTION adjustment exists.
        if recourse_type != "RECOURSE" and not has_dilution:
            raise errors.ApiError(errors.ERR_NON_RECOURSE_NO_BUYBACK, 409,
                                  "Buyback not permitted on NON_RECOURSE with no dilution")
    else:  # OUTSTANDING
        if recourse_type != "RECOURSE":
            raise errors.ApiError(errors.ERR_NON_RECOURSE_NO_BUYBACK, 409,
                                  "OUTSTANDING buyback requires RECOURSE")
        # Grace window: clock now > due_date + recourse_grace_days.
        due = db.parse_iso(invoice["due_date"])
        grace_seconds = program["recourse_grace_days"] * 86400
        from datetime import timedelta
        threshold = due + timedelta(seconds=grace_seconds)
        if not (db.clock_now() > threshold):
            raise errors.ApiError(errors.ERR_RECOURSE_GRACE_ACTIVE, 409,
                                  "Recourse grace window is still active")

    transitions.buyback_invoice(invoice, client, debtor, program, trigger_reason)
    touch(client)
    return success(invoice_view(invoice), status=200)


@bp.get("/factoring/buybacks")
def list_buybacks():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    invoice_id = request.args.get("invoice_id")
    records = [b for b in db.buybacks.values()
               if invoice_id is None or b["invoice_id"] == invoice_id]
    return list_response(records)


@bp.get("/factoring/buybacks/<buyback_id>")
def read_buyback(buyback_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    buyback_rec = lookup(db.buybacks, buyback_id)
    return success(public(buyback_rec), status=200)


# ---------------------------------------------------------------------------
# POST /factoring/invoices/{invoiceId}/write-off
# ---------------------------------------------------------------------------
@bp.post("/factoring/invoices/<invoice_id>/write-off")
def write_off(invoice_id):
    _, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    invoice = lookup(db.invoices, invoice_id)
    if invoice["status"] not in ("OUTSTANDING", "SHORT_PAID"):
        raise errors.invalid_state("Invoice is not OUTSTANDING or SHORT_PAID")

    rel = db.relationships.get(invoice["relationship_id"]) if invoice["relationship_id"] else None
    recourse_type = rel["recourse_type"] if rel else None
    debtor = db.debtors.get(invoice["debtor_id"])
    has_dilution = any(a["invoice_id"] == invoice_id and a["type"] == "DILUTION"
                       for a in db.adjustments.values())

    if (recourse_type != "NON_RECOURSE" or debtor is None
            or debtor["status"] != "INSOLVENT" or has_dilution):
        raise errors.ApiError(errors.ERR_WRITEOFF_NOT_ELIGIBLE, 409,
                              "Write-off requires NON_RECOURSE, INSOLVENT debtor, no DILUTION")

    client = db.clients.get(invoice["client_id"])
    program = db.programs.get(client["program_id"])
    transitions.write_off_invoice(invoice, client, debtor, program)
    touch(client)
    return success(invoice_view(invoice), status=200)


# --- Settlement reads ------------------------------------------------------
@bp.get("/factoring/settlements")
def list_settlements():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    invoice_id = request.args.get("invoice_id")
    records = [s for s in db.settlements.values()
               if invoice_id is None or s["invoice_id"] == invoice_id]
    return list_response(records)


@bp.get("/factoring/settlements/<settlement_id>")
def read_settlement(settlement_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    settlement = lookup(db.settlements, settlement_id)
    return success(public(settlement), status=200)
