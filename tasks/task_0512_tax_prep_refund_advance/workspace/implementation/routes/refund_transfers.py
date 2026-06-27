"""RefundTransfer bank-product endpoints (PRD §3.7, §2.6)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_refund_transfer, refund_transfer_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_return, get_refund_transfer,
                           paginate, page_slice)
from services.calculations import refund_disbursement_waterfall

bp = Blueprint("refund_transfers", __name__)


@bp.post("/refund-transfers")
def create_refund_transfer():
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager"})
    body = get_json_body()

    tax_return_id = body.get("tax_return_id")
    if not isinstance(tax_return_id, str) or not tax_return_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "tax_return_id is required")
    ret = get_return(tax_return_id)

    # Bank product requires bank_product_enabled office (priority 15).
    office = db.offices.get(ret["office_id"])
    if office is None or not office["bank_product_enabled"]:
        raise errors.err(errors.ERR_BANK_PRODUCT_DISABLED, "Office is not licensed for bank products")

    rt = make_refund_transfer(tax_return_id, 0)
    return object_response(refund_transfer_dict(rt), 201)


@bp.get("/refund-transfers/<rt_id>")
def get_refund_transfer_ep(rt_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager", "TaxPreparer"})
    rt = get_refund_transfer(rt_id)
    return object_response(refund_transfer_dict(rt), 200)


@bp.get("/refund-transfers")
def list_refund_transfers():
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager", "TaxPreparer"})
    limit, offset = paginate()

    tax_return_id = request.args.get("tax_return_id")
    items = list(db.refund_transfers.values())
    if tax_return_id is not None:
        items = [t for t in items if t["tax_return_id"] == tax_return_id]

    page, total = page_slice(items, limit, offset)
    return array_response([refund_transfer_dict(t) for t in page], limit, offset, total, 200)


@bp.post("/refund-transfers/<rt_id>/adjust")
def adjust_refund_transfer(rt_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager"})
    rt = get_refund_transfer(rt_id)
    body = get_json_body()

    if rt["status"] != "PENDING_FUNDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Transfer is not PENDING_FUNDING")

    estimated = body.get("estimated_refund_cents")
    if not isinstance(estimated, int) or isinstance(estimated, bool) or estimated <= 0:
        raise errors.err(errors.ERR_INVALID_REFUND_FIGURE,
                         "estimated_refund_cents must be greater than zero")

    rt["estimated_refund_cents"] = estimated
    touch(rt)  # bumps version by one (PRD §3.7)
    return object_response(refund_transfer_dict(rt), 200)


@bp.post("/refund-transfers/<rt_id>/disburse")
def disburse_refund_transfer(rt_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer"})
    rt = get_refund_transfer(rt_id)
    body = get_json_body()

    # well-formedness of provided inputs
    expected_version = body.get("expected_refundtransfer_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "expected_refundtransfer_version is required")
    disbursed = body.get("disbursed_refund_cents")
    if not isinstance(disbursed, int) or isinstance(disbursed, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "disbursed_refund_cents is required")

    # state (409): transition must be defined from current state
    if rt["status"] != "PENDING_FUNDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Transfer is not PENDING_FUNDING")

    # OCC (412) — checked before the disburse business preconditions (PRD §2.5/§2.6)
    if expected_version != rt["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_refundtransfer_version does not match current version")

    # business preconditions
    ret = db.returns.get(rt["tax_return_id"])
    if ret is None or ret["status"] != "EFILED_ACCEPTED":
        raise errors.err(errors.ERR_RETURN_NOT_ACCEPTED, "Linked return is not EFILED_ACCEPTED")
    if disbursed <= 0:
        raise errors.err(errors.ERR_INVALID_REFUND_FIGURE,
                         "disbursed_refund_cents must be greater than zero")

    # ---- waterfall (PRD §3.7) ----
    bank_product_fee = rt["bank_product_fee_cents"]
    prep_fee = ret.get("prep_fee_cents") or 0
    audit_fee = sum(ap["fee_cents"] for ap in db.audit_protections.values()
                    if ap["tax_return_id"] == ret["id"] and ap["status"] == "ACTIVE")
    # advance repayment bucket: linked DISBURSED advance's approved_cents
    disbursed_advance = None
    for adv in db.refund_advances.values():
        if adv["tax_return_id"] == ret["id"] and adv["status"] == "DISBURSED":
            disbursed_advance = adv
            break
    advance_repay_owed = (disbursed_advance["approved_cents"] or 0) if disbursed_advance else 0

    result = refund_disbursement_waterfall(
        disbursed, bank_product_fee, prep_fee, audit_fee, advance_repay_owed)

    rt["disbursed_refund_cents"] = disbursed
    rt["net_to_taxpayer_cents"] = result["net_to_taxpayer_cents"]
    rt["fee_shortfall_cents"] = result["fee_shortfall_cents"]
    rt["status"] = "DISBURSED"
    touch(rt)  # bumps version by one

    # cascade: a DISBURSED advance -> REPAID with repaid_cents = its take
    if disbursed_advance is not None:
        disbursed_advance["repaid_cents"] = result["takes"]["advance_repay"]
        disbursed_advance["status"] = "REPAID"
        touch(disbursed_advance)

    data = refund_transfer_dict(rt)
    # disbursement surcharge is informational (reported, does not reduce net)
    data["disbursement_surcharge_cents"] = result["surcharge_cents"]
    return object_response(data, 200)


@bp.post("/refund-transfers/<rt_id>/cancel")
def cancel_refund_transfer(rt_id):
    _, role = get_identity()
    require_role(role, {"BankProductOfficer", "OfficeManager"})
    rt = get_refund_transfer(rt_id)

    if rt["status"] != "PENDING_FUNDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PENDING_FUNDING transfer can be cancelled")

    # No linked RefundAdvance may be DISBURSED.
    for adv in db.refund_advances.values():
        if adv["tax_return_id"] == rt["tax_return_id"] and adv["status"] == "DISBURSED":
            raise errors.err(errors.ERR_ADVANCE_ALREADY_DISBURSED,
                             "A linked advance is already disbursed")

    rt["status"] = "CANCELLED"
    touch(rt)
    return object_response(refund_transfer_dict(rt), 200)
