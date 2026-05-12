"""WasteEntry registration + lifecycle."""
import db
from clock import parse_iso, iso
from errors import err
from services.audit import audit
from services.util import require_str, require_num, require_enum, check_occ


CATEGORIES = {"SHARPS", "INFECTIOUS", "PHARMACEUTICAL"}
UNITS = {"PCS", "LITERS", "KG"}


def _record_for_order(order_id: str):
    for sr in db.service_records.values():
        if sr.get("order_id") == order_id:
            return sr
    return None


def register_waste(order_id: str, user_id: str, body: dict) -> dict:
    from services.order import get_order
    order = get_order(order_id)
    sr = _record_for_order(order_id)
    if sr is None:
        raise err("ERR_INVALID_STATE", "service record does not exist for this order")
    if sr.get("nurse_id") != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "only the assigned nurse may register waste")
    if order["status"] not in ("IN_PROGRESS",):
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")

    category = require_enum(body, "category", CATEGORIES)
    quantity = require_num(body, "quantity")
    if quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity must be positive")
    unit = require_enum(body, "unit", UNITS)

    sealed = body.get("sealed", False)
    if not isinstance(sealed, bool):
        raise err("ERR_INVALID_REQUEST", "sealed must be a boolean")
    disposal_unit_id = body.get("disposal_unit_id")
    if disposal_unit_id is not None and not isinstance(disposal_unit_id, str):
        raise err("ERR_INVALID_REQUEST", "disposal_unit_id must be a string")
    handover_at_raw = body.get("handover_at")
    handover_at_iso = None
    if handover_at_raw is not None:
        if not isinstance(handover_at_raw, str):
            raise err("ERR_INVALID_REQUEST", "handover_at must be a string")
        try:
            handover_at_iso = iso(parse_iso(handover_at_raw))
        except ValueError as e:
            raise err("ERR_INVALID_REQUEST", str(e))

    w = {
        "order_id": order_id,
        "category": category,
        "quantity": float(quantity),
        "unit": unit,
        "sealed": sealed,
        "disposal_unit_id": disposal_unit_id,
        "handover_at": handover_at_iso,
        "certificate_url": None,
        "status": "REGISTERED",
    }
    db.stamp_create(w, common_fields=False)
    db.waste_entries[w["id"]] = w
    return w


def update_waste(order_id: str, waste_id: str, user_id: str, body: dict) -> dict:
    from services.order import get_order
    order = get_order(order_id)
    sr = _record_for_order(order_id)
    if sr is None or sr.get("nurse_id") != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "only the assigned nurse may update waste")
    w = db.waste_entries.get(waste_id)
    if w is None:
        raise err("ERR_WASTE_NOT_FOUND", f"waste entry {waste_id} not found")
    if w.get("order_id") != order_id:
        raise err("ERR_WASTE_NOT_FOUND", "waste entry does not belong to order")
    if w["status"] not in ("REGISTERED",):
        raise err("ERR_INVALID_STATE", f"waste entry is {w['status']}")

    if "sealed" in body:
        if not isinstance(body["sealed"], bool):
            raise err("ERR_INVALID_REQUEST", "sealed must be a boolean")
        w["sealed"] = body["sealed"]
    if "disposal_unit_id" in body:
        v = body["disposal_unit_id"]
        if v is not None and not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", "disposal_unit_id must be a string")
        w["disposal_unit_id"] = v
    if "handover_at" in body:
        v = body["handover_at"]
        if v is not None and not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", "handover_at must be a string")
        if v is None:
            w["handover_at"] = None
        else:
            try:
                w["handover_at"] = iso(parse_iso(v))
            except ValueError as e:
                raise err("ERR_INVALID_REQUEST", str(e))

    # Transition: REGISTERED -> HANDED_OVER if sealed && disposal_unit_id present
    if w["sealed"] is True and w.get("disposal_unit_id"):
        w["status"] = "HANDED_OVER"
    return w


def archive_waste_via_event(payload: dict) -> dict:
    """Move a HANDED_OVER waste entry to ARCHIVED with the supplied certificate_url."""
    if not isinstance(payload, dict):
        raise err("ERR_INVALID_REQUEST", "payload must be an object")
    waste_id = payload.get("waste_id")
    cert_url = payload.get("certificate_url")
    if not isinstance(waste_id, str) or not waste_id:
        raise err("ERR_INVALID_REQUEST", "payload.waste_id must be a non-empty string")
    if not isinstance(cert_url, str) or not cert_url:
        raise err("ERR_INVALID_REQUEST", "payload.certificate_url must be a non-empty string")
    w = db.waste_entries.get(waste_id)
    if w is None:
        raise err("ERR_WASTE_NOT_FOUND", f"waste {waste_id} not found")
    if w["status"] != "HANDED_OVER":
        raise err("ERR_INVALID_STATE", f"waste is {w['status']}")
    w["status"] = "ARCHIVED"
    w["certificate_url"] = cert_url
    audit("SERVICE_RECORD", w["id"], "WASTE_ARCHIVED",
          payload={"order_id": w["order_id"], "certificate_url": cert_url})
    return w


def list_waste_for_order(order_id: str, limit: int, offset: int):
    rows = [w for w in db.waste_entries.values() if w.get("order_id") == order_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total
