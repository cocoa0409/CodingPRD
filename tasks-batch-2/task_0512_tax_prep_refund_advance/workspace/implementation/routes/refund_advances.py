"""RefundAdvance (refund-anticipation loan) endpoints (PRD §3.8)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_refund_advance, refund_advance_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_return, get_refund_advance,
                           paginate, page_slice)
from services.calculations import advance_max_eligible

bp = Blueprint("refund_advances", __name__)


@bp.post("/refund-advances")
def request_refund_advance():
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager"})
    body = get_json_body()

    tax_return_id = body.get("tax_return_id")
    if not isinstance(tax_return_id, str) or not tax_return_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "tax_return_id is required")
    ret = get_return(tax_return_id)

    requested_cents = body.get("requested_cents")
    if not isinstance(requested_cents, int) or isinstance(requested_cents, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "requested_cents is required")

    # Bank product requires bank_product_enabled office (priority 15).
    office = db.offices.get(ret["office_id"])
    if office is None or not office["bank_product_enabled"]:
        raise errors.err(errors.ERR_BANK_PRODUCT_DISABLED, "Office is not licensed for bank products")

    adv = make_refund_advance(tax_return_id, requested_cents)
    return object_response(refund_advance_dict(adv), 201)


@bp.get("/refund-advances/<ra_id>")
def get_refund_advance_ep(ra_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager", "TaxPreparer"})
    adv = get_refund_advance(ra_id)
    return object_response(refund_advance_dict(adv), 200)


@bp.get("/refund-advances")
def list_refund_advances():
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager", "TaxPreparer"})
    limit, offset = paginate()

    tax_return_id = request.args.get("tax_return_id")
    items = list(db.refund_advances.values())
    if tax_return_id is not None:
        items = [a for a in items if a["tax_return_id"] == tax_return_id]

    page, total = page_slice(items, limit, offset)
    return array_response([refund_advance_dict(a) for a in page], limit, offset, total, 200)


@bp.post("/refund-advances/<ra_id>/underwrite")
def underwrite_refund_advance(ra_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer"})
    adv = get_refund_advance(ra_id)
    body = get_json_body()

    decision = body.get("decision")
    if decision not in ("APPROVE", "DENY"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")

    # state (409): underwrite is only defined from REQUESTED.
    if adv["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Advance is not in REQUESTED state")

    ret = db.returns.get(adv["tax_return_id"])

    if decision == "DENY":
        adv["approved_cents"] = 0
        adv["status"] = "DENIED"
        touch(adv)
        return object_response(refund_advance_dict(adv), 200)

    # APPROVE
    office = db.offices.get(ret["office_id"]) if ret else None
    if office is None or not office["bank_product_enabled"]:
        raise errors.err(errors.ERR_BANK_PRODUCT_DISABLED, "Office is not licensed for bank products")

    client = db.clients.get(ret["client_id"])
    max_eligible = advance_max_eligible(ret["expected_refund_cents"], client["risk_band"])
    if adv["requested_cents"] <= 0 or max_eligible <= 0:
        raise errors.err(errors.ERR_ADVANCE_INELIGIBLE, "Advance is ineligible")

    adv["approved_cents"] = min(adv["requested_cents"], max_eligible)
    adv["status"] = "APPROVED"
    touch(adv)
    return object_response(refund_advance_dict(adv), 200)


@bp.post("/refund-advances/<ra_id>/disburse")
def disburse_refund_advance(ra_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer"})
    adv = get_refund_advance(ra_id)

    if adv["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Advance is not in APPROVED state")

    ret = db.returns.get(adv["tax_return_id"])
    if ret is None or ret["status"] != "EFILED_ACCEPTED":
        raise errors.err(errors.ERR_RETURN_NOT_ACCEPTED, "Linked return is not EFILED_ACCEPTED")

    has_pending_transfer = any(
        rt["tax_return_id"] == ret["id"] and rt["status"] == "PENDING_FUNDING"
        for rt in db.refund_transfers.values()
    )
    if not has_pending_transfer:
        raise errors.err(errors.ERR_NO_REFUND_TRANSFER,
                         "No PENDING_FUNDING refund-transfer exists for the return")

    adv["status"] = "DISBURSED"
    touch(adv)
    return object_response(refund_advance_dict(adv), 200)
