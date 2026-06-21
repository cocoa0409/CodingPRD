"""MailItem + ForwardingRequest endpoints."""
from flask import Blueprint, request, g

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_enum, fk_or_404,
                    get_or_404, touch, parse_pagination, paginate, require_customer_owns)
import constants as C
import calculations as calc
import serializers as S
from services import billing
from services import packages as pkg_svc

bp = Blueprint("mail", __name__)


# --- MailItem ---
@bp.post("/mail-items")
def create_mail_item():
    require_roles("FacilityOperator")
    body = get_json()
    require_fields(body, ["facility_id", "rental_agreement_id", "mail_class"])
    facility_id = require_str(body, "facility_id")
    rental_agreement_id = require_str(body, "rental_agreement_id")
    mail_class = require_enum(body, "mail_class", C.MAIL_CLASSES)
    fk_or_404(db.facilities, facility_id)
    fk_or_404(db.rental_agreements, rental_agreement_id)
    mid = new_id()
    item = {
        "id": mid,
        "facility_id": facility_id,
        "rental_agreement_id": rental_agreement_id,
        "mail_class": mail_class,
        "status": "STORED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.mail_items[mid] = item
    return success(S.mail_item_out(item), status=201)


@bp.get("/mail-items/<mid>")
def get_mail_item(mid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    item = get_or_404(db.mail_items, mid)
    agreement = db.rental_agreements.get(item["rental_agreement_id"])
    if agreement is not None:
        require_customer_owns(agreement["customer_id"])
    return success(S.mail_item_out(item))


@bp.get("/mail-items")
def list_mail_items():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.mail_items.values())
    if g.role == "Customer":
        owned = {a["id"] for a in db.rental_agreements.values()
                 if a["customer_id"] == g.user_id}
        items = [x for x in items if x["rental_agreement_id"] in owned]
    for key in ("facility_id", "rental_agreement_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, total = paginate(items, limit, offset)
    return list_response([S.mail_item_out(x) for x in page], limit, offset, total)


# --- ForwardingRequest ---
def _agreement_of_request(fr):
    mi = db.mail_items.get(fr["mail_item_id"])
    if mi is None:
        return None
    return db.rental_agreements.get(mi["rental_agreement_id"])


@bp.post("/forwarding-requests")
def create_forwarding():
    require_roles("Customer", "FacilityOperator")
    body = get_json()
    require_fields(body, ["mail_item_id", "kind"])
    mail_item_id = require_str(body, "mail_item_id")
    kind = require_enum(body, "kind", C.FORWARDING_KINDS)
    destination = body.get("destination_address")
    if kind == "FORWARD":
        if not isinstance(destination, str) or destination == "":
            raise err("ERR_INVALID_REQUEST", "destination_address required for FORWARD")
    mail_item = fk_or_404(db.mail_items, mail_item_id)
    agreement = db.rental_agreements.get(mail_item["rental_agreement_id"])
    if agreement is not None:
        require_customer_owns(agreement["customer_id"])
    fid = new_id()
    fr = {
        "id": fid,
        "facility_id": mail_item["facility_id"],
        "mail_item_id": mail_item_id,
        "kind": kind,
        "destination_address": destination if kind == "FORWARD" else None,
        "fee_cents": calc.forwarding_fee_cents(kind),
        "status": "REQUESTED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.forwarding_requests[fid] = fr
    return success(S.forwarding_out(fr), status=201)


@bp.get("/forwarding-requests/<fid>")
def get_forwarding(fid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    fr = get_or_404(db.forwarding_requests, fid)
    agreement = _agreement_of_request(fr)
    if agreement is not None:
        require_customer_owns(agreement["customer_id"])
    return success(S.forwarding_out(fr))


@bp.get("/forwarding-requests")
def list_forwarding():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.forwarding_requests.values())
    if g.role == "Customer":
        owned = {a["id"] for a in db.rental_agreements.values()
                 if a["customer_id"] == g.user_id}
        items = [x for x in items
                 if (db.mail_items.get(x["mail_item_id"]) or {}).get("rental_agreement_id") in owned]
    for key in ("facility_id", "mail_item_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, total = paginate(items, limit, offset)
    return list_response([S.forwarding_out(x) for x in page], limit, offset, total)


@bp.post("/forwarding-requests/<fid>/complete")
def complete_forwarding(fid):
    require_roles("FacilityOperator")
    fr = get_or_404(db.forwarding_requests, fid)
    if fr["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Request must be REQUESTED to complete")
    mail_item = db.mail_items.get(fr["mail_item_id"])
    agreement = db.rental_agreements.get(mail_item["rental_agreement_id"]) if mail_item else None
    if agreement is None or agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Owning agreement must be ACTIVE")
    fr["status"] = "COMPLETED"
    if fr["kind"] == "FORWARD":
        mail_item["status"] = "FORWARDED"
    else:
        mail_item["status"] = "SCANNED"
    touch(mail_item)
    invoice = pkg_svc.invoice_for_agreement(agreement["id"])
    if invoice is not None:
        billing.post_ledger_entry(invoice, "CHARGE", "FORWARDING", fr["fee_cents"], fr["id"])
        billing.capture_autopay(agreement, invoice)
    touch(fr)
    return success(S.forwarding_out(fr))


@bp.post("/forwarding-requests/<fid>/cancel")
def cancel_forwarding(fid):
    require_roles("Customer", "FacilityOperator")
    fr = get_or_404(db.forwarding_requests, fid)
    agreement = _agreement_of_request(fr)
    if agreement is not None:
        require_customer_owns(agreement["customer_id"])
    if fr["status"] not in ("REQUESTED", "ON_HOLD"):
        raise err("ERR_INVALID_STATE", "Request must be REQUESTED or ON_HOLD to cancel")
    fr["status"] = "CANCELLED"
    touch(fr)
    return success(S.forwarding_out(fr))
