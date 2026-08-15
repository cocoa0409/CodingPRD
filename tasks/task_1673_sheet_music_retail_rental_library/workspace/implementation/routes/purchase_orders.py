"""Purchase orders and institutional encumbrance (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_IN_GOOD_STANDING,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PO_HAS_OPEN_ORDERS,
    ERR_PO_NOT_FOUND,
    ERR_PO_REQUIRES_INSTITUTION,
)
from middleware import require_auth
from response import success_object
from serializers import ser_po
from services import get_or_404, _ORDER_NON_TERMINAL
from util import is_int, is_str, new_record, parse_day, touch
from routes.helpers import body, paginate, require_fields

bp = Blueprint("purchase_orders", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")
INSTITUTION_KINDS = ("SCHOOL", "INSTITUTION")


def _has_open_orders(po_id):
    return any(
        o.get("purchase_order_id") == po_id and o["status"] in _ORDER_NON_TERMINAL
        for o in db["rental_orders"].values()
    )


@bp.post("/library/purchase-orders")
def create_po():
    require_auth("Customer", "BillingManager")
    data = body()
    require_fields(data, ["account_id", "po_number", "authorized_amount_cents", "valid_from", "valid_until"])
    account = db["customer_accounts"].get(data["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "CustomerAccount not found")
    # Institution-only rule (tier 17).
    if account["account_kind"] not in INSTITUTION_KINDS:
        raise ApiError(ERR_PO_REQUIRES_INSTITUTION, 422, "Purchase orders require SCHOOL/INSTITUTION accounts")
    if not is_str(data["po_number"]):
        raise ApiError(ERR_INVALID_REQUEST, 400, "po_number is required")
    if not is_int(data["authorized_amount_cents"]) or data["authorized_amount_cents"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "authorized_amount_cents must be an integer > 0")
    valid_from = parse_day(data["valid_from"])
    valid_until = parse_day(data["valid_until"])
    if valid_from is None or valid_until is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "valid_from/valid_until must be ISO dates")
    if valid_until <= valid_from:
        raise ApiError(ERR_INVALID_REQUEST, 400, "valid_until must be later than valid_from")
    for po in db["purchase_orders"].values():
        if po["account_id"] == account["id"] and po["po_number"] == data["po_number"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, "po_number must be unique per account")
    rec = new_record()
    rec.update(
        {
            "account_id": account["id"],
            "po_number": data["po_number"],
            "authorized_amount_cents": data["authorized_amount_cents"],
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": "SUBMITTED",
        }
    )
    db["purchase_orders"][rec["id"]] = rec
    return success_object(ser_po(rec), status=201)


@bp.get("/library/purchase-orders")
def list_pos():
    require_auth(*ALL_ROLES)
    rows = list(db["purchase_orders"].values())
    aid = request.args.get("account_id")
    if aid is not None:
        rows = [p for p in rows if p["account_id"] == aid]
    return paginate(rows, ser_po)


@bp.get("/library/purchase-orders/<pid>")
def get_po(pid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("purchase_orders", pid, ERR_PO_NOT_FOUND)
    return success_object(ser_po(rec))


@bp.post("/library/purchase-orders/<pid>/approve")
def approve_po(pid):
    require_auth("BillingManager")
    rec = get_or_404("purchase_orders", pid, ERR_PO_NOT_FOUND)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUBMITTED purchase order may be approved")
    account = db["customer_accounts"].get(rec["account_id"])
    # Tier 16 (standing) before tier 17 (institution).
    if account is not None and account["standing"] != "GOOD":
        raise ApiError(ERR_ACCOUNT_NOT_IN_GOOD_STANDING, 409, "Account standing blocks approval")
    if account is not None and account["account_kind"] not in INSTITUTION_KINDS:
        raise ApiError(ERR_PO_REQUIRES_INSTITUTION, 422, "Purchase orders require SCHOOL/INSTITUTION accounts")
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(ser_po(rec))


@bp.post("/library/purchase-orders/<pid>/reject")
def reject_po(pid):
    require_auth("BillingManager")
    rec = get_or_404("purchase_orders", pid, ERR_PO_NOT_FOUND)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUBMITTED purchase order may be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(ser_po(rec))


@bp.post("/library/purchase-orders/<pid>/close")
def close_po(pid):
    require_auth("BillingManager")
    rec = get_or_404("purchase_orders", pid, ERR_PO_NOT_FOUND)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an APPROVED purchase order may be closed")
    if _has_open_orders(rec["id"]):
        raise ApiError(ERR_PO_HAS_OPEN_ORDERS, 409, "Non-terminal rental orders reference this PO")
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(ser_po(rec))
