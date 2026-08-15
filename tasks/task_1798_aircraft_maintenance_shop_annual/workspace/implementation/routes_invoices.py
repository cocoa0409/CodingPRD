"""Invoice settlement lifecycle (PRD 3.8): DRAFT -> ISSUED -> PAID, or
DRAFT -> VOIDED (compensating reissue permitted by the one-active rule)."""

from flask import Blueprint, g

import db
import envelope
import ops
from errors import ApiError
from middleware import require_roles

bp = Blueprint("invoices", __name__)


def _invoice(rid):
    from validate import get_row

    return get_row(db.INVOICES, rid)


def _inv_out(inv):
    return envelope.ok(ops.pub(inv, ops.INVOICE_F))


@bp.get("/api/invoices/<rid>")
@require_roles("ShopManager", "Owner")
def get_invoice(rid):
    return _inv_out(_invoice(rid))


@bp.post("/api/invoices/<rid>/issue")
@require_roles("ShopManager")
def issue_invoice(rid):
    inv = _invoice(rid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT invoice can be issued.")
    wo = db.WORK_ORDERS.get(inv["work_order_id"])
    if wo is None or wo["status"] != "RETURNED_TO_SERVICE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Issuance requires the work order to stand RETURNED_TO_SERVICE.",
        )
    inv["status"] = "ISSUED"
    db.touch(inv)
    return _inv_out(inv)


@bp.post("/api/invoices/<rid>/pay")
@require_roles("Owner")
def pay_invoice(rid):
    inv = _invoice(rid)
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice can be paid.")
    wo = db.WORK_ORDERS.get(inv["work_order_id"])
    aircraft = db.AIRCRAFT.get(wo["aircraft_id"]) if wo else None
    if aircraft is None or aircraft["owner_id"] != g.user_id:
        raise ApiError(
            "ERR_OWNER_DECISION_REQUIRED",
            "Only the aircraft's registered owner may pay the invoice.",
        )
    inv["status"] = "PAID"
    db.touch(inv)
    return _inv_out(inv)


@bp.post("/api/invoices/<rid>/void")
@require_roles("ShopManager")
def void_invoice(rid):
    inv = _invoice(rid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT invoice can be voided.")
    inv["status"] = "VOIDED"
    db.touch(inv)
    return _inv_out(inv)
