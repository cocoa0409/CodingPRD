"""FactoringRequest endpoints (PRD §3.8)."""
from __future__ import annotations

from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FACTORING_FEE_BELOW_MIN,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_number,
    lookup_path_or_404,
    lookup_fk_or_422,
)
from services.calculations import (
    factoring_floor_pct,
    compute_factoring_advance,
)


bp = Blueprint("factoring_requests", __name__)


@bp.post("/freight/factoring-requests")
def create_factoring_request():
    require_auth(["Carrier"])()
    body = get_json_body()
    require_fields(body, ["invoice_id", "carrier_id", "factoring_fee_pct"])

    # priority 4: FK existence
    invoice = lookup_fk_or_422(db.invoices, body["invoice_id"], "Invoice")
    carrier = lookup_fk_or_422(db.carriers, body["carrier_id"], "Carrier")

    # Carrier-role ownership: must request for own carrier_id, and must own the load.
    if body["carrier_id"] != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Carrier may only factor for own carrier_id")
    load = db.loads.get(invoice.get("load_id"))
    if load is None or load.get("carrier_id") != body["carrier_id"]:
        raise APIError(ERR_UNAUTHORIZED, 403, "Carrier does not own the invoice's load")

    fee_pct_raw = require_number(body["factoring_fee_pct"], "factoring_fee_pct")
    if fee_pct_raw <= 0.0 or fee_pct_raw > 10.0:
        raise APIError(ERR_INVALID_REQUEST, 400, "factoring_fee_pct must be in (0.0, 10.0]")
    fee_pct = Decimal(str(fee_pct_raw))

    # priority 5: invoice must be ISSUED or PARTIALLY_PAID, not already factored.
    if invoice.get("status") not in {"ISSUED", "PARTIALLY_PAID"}:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice not eligible for factoring")
    if invoice.get("factored"):
        raise APIError(ERR_INVALID_STATE, 409, "Invoice already factored")
    # Carrier must be QUALIFIED.
    if carrier.get("qualification_status") != "QUALIFIED":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier must be QUALIFIED to factor")

    # priority 19: fee floor.
    safety = float(carrier.get("safety_score", 0.0))
    floor = factoring_floor_pct(safety)
    if fee_pct < floor:
        raise APIError(ERR_FACTORING_FEE_BELOW_MIN, 422, f"factoring_fee_pct below floor {floor}")

    advance = compute_factoring_advance(int(invoice["total_cents"]), fee_pct, safety)

    fr = {
        "invoice_id": invoice["id"],
        "carrier_id": carrier["id"],
        "factoring_fee_pct": float(fee_pct),
        "advance_cents": advance,
        "status": "REQUESTED",
    }
    db.stamp_common(fr)
    db.factoring_requests[fr["id"]] = fr
    return ok_object(fr, 201)


def _fr_visible_to(fr, role: str, uid: str) -> bool:
    if role == "BrokerOps":
        return True
    if role == "Carrier":
        return fr.get("carrier_id") == uid
    return False


@bp.get("/freight/factoring-requests/<fid>")
def get_factoring_request(fid: str):
    require_auth(["BrokerOps", "Carrier"])()
    fr = lookup_path_or_404(db.factoring_requests, fid, "FactoringRequest")
    if not _fr_visible_to(fr, current_role(), current_user_id()):
        raise APIError(ERR_UNAUTHORIZED, 403, "Not permitted to view this factoring request")
    return ok_object(fr, 200)


@bp.get("/freight/factoring-requests")
def list_factoring_requests():
    require_auth(["BrokerOps", "Carrier"])()
    limit, offset = paginate_params(request.args)
    carrier_filter = request.args.get("carrier_id")
    invoice_filter = request.args.get("invoice_id")
    status_filter = request.args.get("status")
    items = list(db.factoring_requests.values())
    role = current_role()
    uid = current_user_id()
    if role == "Carrier":
        items = [f for f in items if f.get("carrier_id") == uid]
    if carrier_filter:
        items = [f for f in items if f.get("carrier_id") == carrier_filter]
    if invoice_filter:
        items = [f for f in items if f.get("invoice_id") == invoice_filter]
    if status_filter:
        items = [f for f in items if f.get("status") == status_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/freight/factoring-requests/<fid>/approve")
def approve_factoring(fid: str):
    require_auth(["BrokerOps"])()
    fr = lookup_path_or_404(db.factoring_requests, fid, "FactoringRequest")
    invoice = db.invoices.get(fr.get("invoice_id"))

    if fr.get("status") != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "FactoringRequest must be REQUESTED to approve")
    if invoice is None or invoice.get("status") not in {"ISSUED", "PARTIALLY_PAID"}:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice not in eligible status")
    if invoice.get("factored"):
        raise APIError(ERR_INVALID_STATE, 409, "Invoice already factored")
    carrier = db.carriers.get(fr.get("carrier_id"))
    if carrier is None or carrier.get("qualification_status") != "QUALIFIED":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier not QUALIFIED")

    fr["status"] = "APPROVED"
    db.bump(fr)
    invoice["factored"] = True
    db.bump(invoice)
    return ok_object(fr, 200)


@bp.post("/freight/factoring-requests/<fid>/advance")
def advance_factoring(fid: str):
    require_auth(["BrokerOps"])()
    fr = lookup_path_or_404(db.factoring_requests, fid, "FactoringRequest")
    if fr.get("status") != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "FactoringRequest must be APPROVED to advance")
    fr["status"] = "ADVANCED"
    db.bump(fr)
    return ok_object(fr, 200)


@bp.post("/freight/factoring-requests/<fid>/reject")
def reject_factoring(fid: str):
    require_auth(["BrokerOps"])()
    fr = lookup_path_or_404(db.factoring_requests, fid, "FactoringRequest")
    if fr.get("status") != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "FactoringRequest must be REQUESTED to reject")
    fr["status"] = "REJECTED"
    db.bump(fr)
    return ok_object(fr, 200)
