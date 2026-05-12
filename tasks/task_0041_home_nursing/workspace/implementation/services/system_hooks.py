"""Test hooks: /_clock/advance and /_events/emit."""
from datetime import timedelta

import db
from clock import now, parse_iso, set_now, iso
from errors import err
from services.audit import audit
from services.constants import EXPIRY_WARNING_DAYS


SYSTEMS = {"identity-verification", "medical-waste-disposal", "payment", "im"}


# ----------------------------------------------------------- Clock advance --
def advance_clock(body: dict):
    if "to" not in body:
        raise err("ERR_INVALID_REQUEST", "missing field: to")
    to_raw = body["to"]
    if not isinstance(to_raw, str):
        raise err("ERR_INVALID_REQUEST", "to must be a string")
    try:
        to_dt = parse_iso(to_raw)
    except ValueError as e:
        raise err("ERR_INVALID_REQUEST", str(e))

    set_now(to_dt)

    # 1) Expire any OFFERED dispatches whose accept_deadline has been crossed
    affected_orders_for_redispatch = []
    for d in list(db.dispatches.values()):
        if d.get("status") != "OFFERED":
            continue
        deadline = parse_iso(d["accept_deadline"])
        if to_dt >= deadline:
            d["status"] = "EXPIRED"
            affected_orders_for_redispatch.append(d["order_id"])

    # 2) Nurses whose certified_until has been crossed → PENDING; cancel OFFERED dispatches
    for n in db.nurses.values():
        cu = n.get("certified_until")
        if not cu:
            continue
        cu_dt = parse_iso(cu)
        if to_dt >= cu_dt:
            if n["certification_status"] in ("CERTIFIED", "EXPIRING"):
                n["certification_status"] = "PENDING"
                db.stamp_update(n)
                # Cancel OFFERED dispatches for this nurse and add their orders for re-dispatch
                for d in list(db.dispatches.values()):
                    if d.get("nurse_id") == n["id"] and d.get("status") == "OFFERED":
                        d["status"] = "CANCELLED"
                        affected_orders_for_redispatch.append(d["order_id"])
                audit("NURSE", n["id"], "CERT_LAPSED", payload={"certified_until": cu})
        else:
            # Warning window
            warn_dt = cu_dt - timedelta(days=EXPIRY_WARNING_DAYS)
            if to_dt >= warn_dt and n["certification_status"] == "CERTIFIED":
                n["certification_status"] = "EXPIRING"
                db.stamp_update(n)
                audit("NURSE", n["id"], "EXPIRY_WARNING", payload={"certified_until": cu})

    # 3) Trigger re-dispatch on each affected order (deduped, in stable order)
    seen = set()
    for oid in affected_orders_for_redispatch:
        if oid in seen:
            continue
        seen.add(oid)
        order = db.orders.get(oid)
        if order is None:
            continue
        if order["status"] not in ("DISPATCHED", "AWAITING_DISPATCH"):
            continue
        from services.dispatch import _trigger_redispatch
        _trigger_redispatch(order)


# ------------------------------------------------------------ Events emit --
def emit_event(body: dict):
    system = body.get("system")
    event_type = body.get("event_type")
    payload = body.get("payload", {}) or {}
    if system not in SYSTEMS:
        raise err("ERR_INVALID_REQUEST", f"system must be one of {SYSTEMS}")
    if not isinstance(event_type, str) or not event_type:
        raise err("ERR_INVALID_REQUEST", "event_type required")
    if not isinstance(payload, dict):
        raise err("ERR_INVALID_REQUEST", "payload must be an object")

    if system == "identity-verification":
        _handle_identity(event_type, payload)
    elif system == "medical-waste-disposal":
        _handle_waste(event_type, payload)
    elif system == "payment":
        _handle_payment(event_type, payload)
    elif system == "im":
        # Audit-only: no state change
        pass


def _handle_identity(event_type: str, payload: dict):
    nurse_id = payload.get("nurse_id")
    if not isinstance(nurse_id, str) or not nurse_id:
        raise err("ERR_INVALID_REQUEST", "payload.nurse_id required")
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        raise err("ERR_NURSE_NOT_FOUND", f"nurse {nurse_id} not found")
    if event_type in ("LICENSE_VERIFIED",):
        nurse["license_verified"] = True
        db.stamp_update(nurse)
    elif event_type in ("HOSPITAL_AFFILIATION_VERIFIED",):
        nurse["hospital_affiliation_verified"] = True
        db.stamp_update(nurse)
    else:
        raise err("ERR_INVALID_REQUEST",
                  f"unknown identity-verification event_type: {event_type}")


def _handle_waste(event_type: str, payload: dict):
    if event_type != "CERTIFICATE_ISSUED":
        raise err("ERR_INVALID_REQUEST",
                  f"unknown medical-waste-disposal event_type: {event_type}")
    from services.waste import archive_waste_via_event
    archive_waste_via_event(payload)


def _handle_payment(event_type: str, payload: dict):
    if event_type not in ("AUTHORIZED", "CAPTURED", "REFUNDED"):
        raise err("ERR_INVALID_REQUEST", f"unknown payment event_type: {event_type}")
    order_id = payload.get("order_id")
    if not isinstance(order_id, str):
        raise err("ERR_INVALID_REQUEST", "payload.order_id required")
    order = db.orders.get(order_id)
    if order is None:
        raise err("ERR_ORDER_NOT_FOUND", f"order {order_id} not found")
    order["payment_status"] = event_type
    db.stamp_update(order)
