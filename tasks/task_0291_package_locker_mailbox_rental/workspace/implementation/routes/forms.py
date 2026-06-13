"""Form1583 + AuthorizedRecipient endpoints."""
from flask import Blueprint, request, g

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_enum, fk_or_404,
                    get_or_404, touch, parse_pagination, paginate, require_customer_owns)
import constants as C
import clock
import serializers as S

bp = Blueprint("forms", __name__)


@bp.post("/forms-1583")
def create_form():
    require_roles("FacilityOperator", "Customer")
    body = get_json()
    require_fields(body, ["facility_id", "customer_id", "primary_id_type", "address_proof_type"])
    facility_id = require_str(body, "facility_id")
    customer_id = require_str(body, "customer_id")
    primary_id_type = require_enum(body, "primary_id_type", C.PRIMARY_ID_TYPES)
    address_proof_type = require_enum(body, "address_proof_type", C.ADDRESS_PROOF_TYPES)
    fk_or_404(db.facilities, facility_id)
    customer = fk_or_404(db.customers, customer_id)
    require_customer_owns(customer["id"])
    fid = new_id()
    form = {
        "id": fid,
        "facility_id": facility_id,
        "customer_id": customer_id,
        "primary_id_type": primary_id_type,
        "address_proof_type": address_proof_type,
        "status": "DRAFT",
        "submission_count": 0,
        "verified_at": None,
        "rejection_reason": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.forms_1583[fid] = form
    return success(S.form_out(form), status=201)


@bp.get("/forms-1583/<fid>")
def get_form(fid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    form = get_or_404(db.forms_1583, fid)
    require_customer_owns(form["customer_id"])
    return success(S.form_out(form))


@bp.get("/forms-1583")
def list_forms():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.forms_1583.values())
    if g.role == "Customer":
        items = [x for x in items if x["customer_id"] == g.user_id]
    fid = request.args.get("facility_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if customer_id is not None:
        items = [x for x in items if x["customer_id"] == customer_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([S.form_out(x) for x in page], limit, offset, total)


@bp.post("/forms-1583/<fid>/recipients")
def add_recipient(fid):
    require_roles("FacilityOperator", "Customer")
    form = get_or_404(db.forms_1583, fid)
    require_customer_owns(form["customer_id"])
    body = get_json()
    require_fields(body, ["recipient_name", "relationship"])
    recipient_name = require_str(body, "recipient_name")
    relationship = require_enum(body, "relationship", C.RELATIONSHIPS)
    rid = new_id()
    recipient = {
        "id": rid,
        "form_1583_id": fid,
        "recipient_name": recipient_name,
        "relationship": relationship,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.authorized_recipients[rid] = recipient
    return success(S.recipient_out(recipient), status=201)


@bp.get("/forms-1583/<fid>/recipients")
def list_recipients(fid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    form = get_or_404(db.forms_1583, fid)
    require_customer_owns(form["customer_id"])
    limit, offset = parse_pagination()
    items = [r for r in db.authorized_recipients.values() if r["form_1583_id"] == fid]
    page, total = paginate(items, limit, offset)
    return list_response([S.recipient_out(x) for x in page], limit, offset, total)


def _has_recipient(fid):
    return any(r["form_1583_id"] == fid for r in db.authorized_recipients.values())


@bp.post("/forms-1583/<fid>/submit")
def submit_form(fid):
    require_roles("Customer", "FacilityOperator")
    form = get_or_404(db.forms_1583, fid)
    require_customer_owns(form["customer_id"])
    if form["status"] not in ("DRAFT", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Form must be DRAFT or REJECTED to submit")
    if not _has_recipient(fid):
        raise err("ERR_NO_RECIPIENTS", "At least one authorized recipient required")
    was_rejected = form["status"] == "REJECTED"
    form["status"] = "SUBMITTED"
    form["submission_count"] += 1
    if was_rejected:
        form["rejection_reason"] = None
    touch(form)
    return success(S.form_out(form))


@bp.post("/forms-1583/<fid>/verify")
def verify_form(fid):
    require_roles("ComplianceOfficer")
    form = get_or_404(db.forms_1583, fid)
    if form["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Form must be SUBMITTED to verify")
    facility = db.facilities[form["facility_id"]]
    form["status"] = "VERIFIED"
    form["verified_at"] = facility["current_utc"]
    touch(form)
    return success(S.form_out(form))


@bp.post("/forms-1583/<fid>/reject")
def reject_form(fid):
    require_roles("ComplianceOfficer")
    form = get_or_404(db.forms_1583, fid)
    body = get_json()
    require_fields(body, ["rejection_reason"])
    reason = require_str(body, "rejection_reason")
    if form["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Form must be SUBMITTED to reject")
    form["status"] = "REJECTED"
    form["rejection_reason"] = reason
    touch(form)
    return success(S.form_out(form))
