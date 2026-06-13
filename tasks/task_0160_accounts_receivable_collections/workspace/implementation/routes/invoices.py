"""Invoice endpoints (PRD §3.1) and invoice-scoped reverse-reachability reads."""
from flask import Blueprint, request

import db
from errors import err, ERR_VALIDATION, ERR_CREDIT_HOLD
from middleware import get_identity, authorize
from response import success, list_response
from services import domain, lookup
from services.common import (
    stamp_create, get_json_body, require_str, require_int,
    parse_pagination, paginate,
)
from timeutil import parse_iso_ms

bp = Blueprint("invoices", __name__)


@bp.route("/ar/invoices", methods=["POST"])
def create_invoice():
    _, role = get_identity()
    authorize(role, ["AR_CLERK", "AR_MANAGER"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    # existence first (priority 3)
    customer = lookup.get_customer(customer_id)
    # required fields (priority 4)
    invoice_date = require_str(body, "invoice_date")
    due_date = require_str(body, "due_date")
    face = require_int(body, "face_amount_cents", minimum=1)
    invoice_date_ms = parse_iso_ms(invoice_date)
    due_date_ms = parse_iso_ms(due_date)
    # field-level constraint: due_date >= invoice_date (PRD §3.1 -> ERR_VALIDATION)
    if due_date_ms < invoice_date_ms:
        raise err(ERR_VALIDATION, "due_date must be >= invoice_date")

    # Credit gate (priority 17): evaluated against the customer's posture as it
    # stands BEFORE the new invoice; recompute live first.
    domain.recompute_customer(customer, recompute_stage=False)
    if customer["credit_status"] == "HOLD":
        raise err(ERR_CREDIT_HOLD, "customer is on credit hold")

    iv = {
        "customer_id": customer_id,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "invoice_date_ms": invoice_date_ms,
        "due_date_ms": due_date_ms,
        "face_amount_cents": face,
        "balance_cents": face,
        "disputed_amount_cents": 0,
        "status": "OPEN",
        "aging_bucket": "CURRENT",
        "dunning_stage_index": 0,
    }
    stamp_create(iv)
    iv["aging_bucket"] = domain.aging_bucket(iv, "due")
    db.invoices[iv["id"]] = iv

    # recompute customer exposure & credit_status after creation
    domain.recompute_customer(customer, recompute_stage=False)
    return success(domain.serialize_invoice(iv), status=201)


@bp.route("/ar/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "COLLECTIONS_AGENT", "AUDITOR"])
    iv = lookup.get_invoice(iid)
    return success(domain.serialize_invoice(iv), status=200)


@bp.route("/ar/invoices", methods=["GET"])
def list_invoices():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "COLLECTIONS_AGENT", "AUDITOR"])
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    aging = request.args.get("aging_bucket")

    items = list(db.invoices.values())
    if customer_id is not None:
        items = [iv for iv in items if iv["customer_id"] == customer_id]
    if status is not None:
        items = [iv for iv in items if iv["status"] == status]
    if aging is not None:
        items = [iv for iv in items if domain.aging_bucket(iv, "due") == aging]
    items.sort(key=lambda iv: (iv["created_at"], iv["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_invoice(iv) for iv in page], limit, offset, total)


# ---- invoice-scoped reverse-reachability lists (PRD §2.5) -----------------
@bp.route("/ar/invoices/<iid>/disputes", methods=["GET"])
def invoice_disputes(iid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    lookup.get_invoice(iid)
    limit, offset = parse_pagination()
    items = [d for d in db.disputes.values() if d["invoice_id"] == iid]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_dispute(d) for d in page], limit, offset, total)


@bp.route("/ar/invoices/<iid>/write-offs", methods=["GET"])
def invoice_writeoffs(iid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AUDITOR"])
    lookup.get_invoice(iid)
    limit, offset = parse_pagination()
    items = [w for w in db.write_offs.values() if w["invoice_id"] == iid]
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_writeoff(w) for w in page], limit, offset, total)


@bp.route("/ar/invoices/<iid>/payment-applications", methods=["GET"])
def invoice_applications(iid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "AUDITOR"])
    lookup.get_invoice(iid)
    limit, offset = parse_pagination()
    items = [a for a in db.payment_applications.values() if a["invoice_id"] == iid]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_application(a) for a in page], limit, offset, total)


@bp.route("/ar/invoices/<iid>/dunning-notices", methods=["GET"])
def invoice_notices(iid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    lookup.get_invoice(iid)
    limit, offset = parse_pagination()
    items = [n for n in db.dunning_notices.values() if n["invoice_id"] == iid]
    items.sort(key=lambda n: (n["created_at"], n["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_notice(n) for n in page], limit, offset, total)
