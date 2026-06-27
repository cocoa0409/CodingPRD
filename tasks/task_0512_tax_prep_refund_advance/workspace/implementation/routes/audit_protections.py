"""AuditProtection add-on endpoints (PRD §3.6)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_audit_protection, audit_protection_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_return, get_audit_protection,
                           paginate, page_slice)
from constants import AUDIT_PROTECTION_FEE_CENTS

bp = Blueprint("audit_protections", __name__)


@bp.post("/audit-protections")
def create_audit_protection():
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager"})
    body = get_json_body()

    tax_return_id = body.get("tax_return_id")
    if not isinstance(tax_return_id, str) or not tax_return_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "tax_return_id is required")
    get_return(tax_return_id)

    fee_cents = body.get("fee_cents", AUDIT_PROTECTION_FEE_CENTS)
    if not isinstance(fee_cents, int) or isinstance(fee_cents, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "fee_cents must be an integer")

    ap = make_audit_protection(tax_return_id, fee_cents)
    return object_response(audit_protection_dict(ap), 201)


@bp.get("/audit-protections/<ap_id>")
def get_audit_protection_ep(ap_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager", "TaxPreparer"})
    ap = get_audit_protection(ap_id)
    return object_response(audit_protection_dict(ap), 200)


@bp.get("/audit-protections")
def list_audit_protections():
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager", "TaxPreparer"})
    limit, offset = paginate()

    tax_return_id = request.args.get("tax_return_id")
    items = list(db.audit_protections.values())
    if tax_return_id is not None:
        items = [a for a in items if a["tax_return_id"] == tax_return_id]

    page, total = page_slice(items, limit, offset)
    return array_response([audit_protection_dict(a) for a in page], limit, offset, total, 200)


@bp.post("/audit-protections/<ap_id>/cancel")
def cancel_audit_protection(ap_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager"})
    ap = get_audit_protection(ap_id)

    if ap["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE add-on can be cancelled")

    ret = db.returns.get(ap["tax_return_id"])
    if ret is not None and ret["status"] == "EFILED_ACCEPTED":
        raise errors.err(errors.ERR_RETURN_ALREADY_ACCEPTED,
                         "Cannot cancel protection once the return is accepted")

    ap["status"] = "CANCELLED"
    touch(ap)
    return object_response(audit_protection_dict(ap), 200)
