"""Load endpoints (PRD §3.5, §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DELIVERY_BEFORE_PICKUP,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_enum,
    require_int_or_str_int,
    lookup_path_or_404,
    parse_iso_or_400,
)
from services.calculations import (
    compute_detention_charge,
    compute_invoice_total,
    recompute_load_accessorial_total,
)


bp = Blueprint("loads", __name__)

ACCESSORIAL_CODES = {"LUMPER", "TARPS", "EXTRA_STOP", "REWEIGH", "LAYOVER", "DETENTION"}


def _shipper_id_for_load(load):
    q = db.quote_requests.get(load.get("quote_request_id"))
    return q.get("shipper_id") if q else None


def _load_visible_to(load, role: str, uid: str) -> bool:
    if role == "BrokerOps":
        return True
    if role == "Carrier":
        return load.get("carrier_id") == uid
    if role == "Shipper":
        return _shipper_id_for_load(load) == uid
    return False


@bp.get("/freight/loads/<lid>")
def get_load(lid: str):
    require_auth(["BrokerOps", "Carrier", "Shipper"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if not _load_visible_to(load, current_role(), current_user_id()):
        raise APIError(ERR_UNAUTHORIZED, 403, "Not permitted to view this load")
    return ok_object(load, 200)


@bp.get("/freight/loads")
def list_loads():
    require_auth(["BrokerOps", "Carrier", "Shipper"])()
    limit, offset = paginate_params(request.args)
    qid_filter = request.args.get("quote_request_id")
    carrier_filter = request.args.get("carrier_id")
    status_filter = request.args.get("status")
    items = list(db.loads.values())
    role = current_role()
    uid = current_user_id()
    if role == "Carrier":
        items = [ld for ld in items if ld.get("carrier_id") == uid]
    elif role == "Shipper":
        items = [ld for ld in items if _shipper_id_for_load(ld) == uid]
    if qid_filter:
        items = [ld for ld in items if ld.get("quote_request_id") == qid_filter]
    if carrier_filter:
        items = [ld for ld in items if ld.get("carrier_id") == carrier_filter]
    if status_filter:
        items = [ld for ld in items if ld.get("status") == status_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/freight/loads/<lid>/pickup")
def pickup_load(lid: str):
    require_auth(["Carrier"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if load.get("carrier_id") != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Carrier may only pickup own loads")
    if load.get("status") != "AWARDED":
        raise APIError(ERR_INVALID_STATE, 409, "Load must be AWARDED to pickup")
    body = get_json_body()
    require_fields(body, ["actual_pickup_at_utc"])
    parse_iso_or_400(body["actual_pickup_at_utc"], "actual_pickup_at_utc")  # validate format

    load["status"] = "IN_TRANSIT"
    load["actual_pickup_at_utc"] = body["actual_pickup_at_utc"]
    db.bump(load)
    return ok_object(load, 200)


@bp.post("/freight/loads/<lid>/deliver")
def deliver_load(lid: str):
    require_auth(["Carrier"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if load.get("carrier_id") != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Carrier may only deliver own loads")
    if load.get("status") != "IN_TRANSIT":
        raise APIError(ERR_INVALID_STATE, 409, "Load must be IN_TRANSIT to deliver")
    body = get_json_body()
    require_fields(body, ["actual_delivery_at_utc"])
    delivery_dt = parse_iso_or_400(body["actual_delivery_at_utc"], "actual_delivery_at_utc")
    pickup_dt = db.parse_iso_dt(load.get("actual_pickup_at_utc"))
    if pickup_dt is None or delivery_dt <= pickup_dt:
        raise APIError(ERR_DELIVERY_BEFORE_PICKUP, 422, "actual_delivery_at_utc must be after actual_pickup_at_utc")

    load["status"] = "DELIVERED"
    load["actual_delivery_at_utc"] = body["actual_delivery_at_utc"]
    load["pod_received_at_utc"] = db.now_iso()
    # Detention calc runs against the load.
    load["detention_charge_cents"] = compute_detention_charge(load)
    db.bump(load)
    return ok_object(load, 200)


@bp.post("/freight/loads/<lid>/cancel")
def cancel_load(lid: str):
    require_auth(["BrokerOps"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if load.get("status") != "AWARDED":
        raise APIError(ERR_INVALID_STATE, 409, "Load must be AWARDED to cancel")
    load["status"] = "CANCELLED"
    db.bump(load)
    # Cascade: parent QuoteRequest -> WITHDRAWN
    qr = db.quote_requests.get(load.get("quote_request_id"))
    if qr is not None:
        qr["status"] = "WITHDRAWN"
        db.bump(qr)
    return ok_object(load, 200)


@bp.post("/freight/loads/<lid>/invoice")
def invoice_load(lid: str):
    require_auth(["BrokerOps"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if load.get("status") != "DELIVERED":
        raise APIError(ERR_INVALID_STATE, 409, "Load must be DELIVERED to invoice")
    if not load.get("pod_received_at_utc"):
        raise APIError(ERR_INVALID_STATE, 409, "POD must be received before invoicing")

    # Create the invoice row with total computed by calc invoice_total_cents.
    total = compute_invoice_total(load, None)
    invoice = {
        "load_id": load["id"],
        "total_cents": total,
        "factored": False,
        "status": "ISSUED",
        "amount_paid_cents": 0,
    }
    db.stamp_common(invoice)
    db.invoices[invoice["id"]] = invoice

    # Load INVOICED
    load["status"] = "INVOICED"
    db.bump(load)

    # Recompute shipper open AR (cascade).
    from services.calculations import recompute_shipper_open_ar
    q = db.quote_requests.get(load.get("quote_request_id"))
    if q is not None:
        recompute_shipper_open_ar(q.get("shipper_id"))

    return ok_object(invoice, 201)


@bp.post("/freight/loads/<lid>/accessorials")
def add_accessorial(lid: str):
    require_auth(["BrokerOps", "Carrier"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if current_role() == "Carrier" and load.get("carrier_id") != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Carrier may only attach accessorials to own loads")
    if load.get("status") != "DELIVERED":
        raise APIError(ERR_INVALID_STATE, 409, "Accessorials only allowed on DELIVERED loads")
    body = get_json_body()
    require_fields(body, ["code", "amount_cents"])
    require_enum(body["code"], ACCESSORIAL_CODES, "code")
    amount = require_int_or_str_int(body["amount_cents"], "amount_cents")
    if amount <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "amount_cents must be > 0")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "note must be a string")

    acc = {
        "load_id": load["id"],
        "code": body["code"],
        "amount_cents": amount,
        "note": note,
    }
    db.stamp_immutable(acc)
    db.accessorials[acc["id"]] = acc

    # Recompute load accessorial total + bump.
    recompute_load_accessorial_total(load)
    db.bump(load)
    return ok_object(acc, 201)


@bp.get("/freight/loads/<lid>/accessorials")
def list_accessorials(lid: str):
    require_auth(["BrokerOps", "Carrier", "Shipper"])()
    load = lookup_path_or_404(db.loads, lid, "Load")
    if not _load_visible_to(load, current_role(), current_user_id()):
        raise APIError(ERR_UNAUTHORIZED, 403, "Not permitted to view this load")
    limit, offset = paginate_params(request.args)
    items = [a for a in db.accessorials.values() if a.get("load_id") == lid]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
