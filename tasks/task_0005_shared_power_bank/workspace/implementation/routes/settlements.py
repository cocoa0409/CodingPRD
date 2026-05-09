import secrets
import string
from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields, bump
from envelope import success, created
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_SETTLEMENT_PERIOD_INVALID,
)
from validation import need_body, require_str, require_timestamp, occ_check
from serializers import serialize_settlement
from services.settlements_calc import compute_provisional, compute_settled

bp = Blueprint("settlements", __name__)


def _new_invoice_number() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"INV-{suffix}"


@bp.post("/settlements")
def create_settlement():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))
    location_partner_id = require_str(body, "location_partner_id")
    period_start = require_timestamp(body, "period_start")
    period_end = require_timestamp(body, "period_end")

    if period_end <= period_start:
        raise APIError(ERR_SETTLEMENT_PERIOD_INVALID, 422, "period_end must be > period_start")

    partner = db.location_partners.get(location_partner_id)
    if partner is None:
        raise APIError(ERR_NOT_FOUND, 404, "Location partner not found")

    cf = make_common_fields()
    settlement = {
        **cf,
        "location_partner_id": location_partner_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_revenue": None,
        "partner_amount": None,
        "refund_adjustment": None,
        "status": "DRAFT",
        "invoice_number": None,
    }
    prov = compute_provisional(settlement, partner)
    settlement["gross_revenue"] = prov["gross_revenue"]
    settlement["partner_amount"] = prov["partner_amount"]
    settlement["refund_adjustment"] = prov["refund_adjustment"]
    db.settlements[settlement["id"]] = settlement
    return created(serialize_settlement(settlement))


@bp.get("/settlements/<settlement_id>")
def get_settlement(settlement_id):
    uid, role = require_role({"Admin", "Partner"})
    s = db.settlements.get(settlement_id)
    if s is None:
        raise APIError(ERR_NOT_FOUND, 404, "Settlement not found")
    if role == "Partner" and s["location_partner_id"] != uid:
        raise APIError(ERR_FORBIDDEN, 403, "Cannot read another partner's settlement")
    return success(serialize_settlement(s))


@bp.post("/settlements/<settlement_id>/approve")
def approve_settlement(settlement_id):
    require_role({"Admin"})
    s = db.settlements.get(settlement_id)
    if s is None:
        raise APIError(ERR_NOT_FOUND, 404, "Settlement not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(s, body)
    if s["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Settlement not in DRAFT")
    s["status"] = "APPROVED"
    bump(s)
    return success(serialize_settlement(s))


@bp.post("/settlements/<settlement_id>/issue-invoice")
def issue_invoice(settlement_id):
    require_role({"Admin"})
    s = db.settlements.get(settlement_id)
    if s is None:
        raise APIError(ERR_NOT_FOUND, 404, "Settlement not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(s, body)
    if s["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "Settlement not in APPROVED")

    partner = db.location_partners.get(s["location_partner_id"])
    settled = compute_settled(s, partner)
    s["gross_revenue"] = settled["gross_revenue"]
    s["partner_amount"] = settled["partner_amount"]
    s["refund_adjustment"] = settled["refund_adjustment"]
    s["invoice_number"] = _new_invoice_number()
    s["status"] = "INVOICED"
    bump(s)
    return success(serialize_settlement(s))
