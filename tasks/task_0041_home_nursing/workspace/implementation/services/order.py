"""Order, fee estimate, and lifecycle logic."""
import hashlib
import json
import math
from decimal import Decimal

from flask import request

import db
from clock import now, parse_iso, iso
from errors import err
from services.audit import audit
from services.constants import (
    DIST_FREE_KM, DIST_PRICE_PER_KM_CENTS,
    DAY_BPS, NIGHT_BPS, WEEKEND_BPS, TAX_BPS,
    DEFAULT_ORIGIN_LAT, DEFAULT_ORIGIN_LNG, WASTE_PRODUCING_SKILLS,
)
from services.util import (
    require_str, require_num, check_occ,
    haversine_km, round_half_up_int,
)


PREF_GENDERS = {"M", "F", "ANY"}


# ---------------------------------------------------------- Idempotency --
def _payload_signature(body: dict) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _resolve_idempotency(patient_id: str, body: dict):
    """Return (existing_order_or_None, key_for_storage) or raise on conflict."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None
    sig = _payload_signature(body)
    composite = (patient_id, key)
    rec = db.idempotency.get(composite)
    if rec is None:
        return None, composite
    if rec["sig"] != sig:
        raise err("ERR_IDEMPOTENCY_KEY_REUSED",
                  "Idempotency-Key already used with a different payload")
    # Same payload, same key -> return original order
    return db.orders.get(rec["order_id"]), composite


# --------------------------------------------------------------- Fee est --
def _tod_multiplier_bps(dt) -> int:
    h = dt.hour
    if h < 6 or h >= 22:
        return NIGHT_BPS
    if dt.weekday() >= 5:  # 5=Sat, 6=Sun
        return WEEKEND_BPS
    return DAY_BPS


def _surcharge(base: int, multiplier_bps: int) -> int:
    if multiplier_bps == DAY_BPS:
        return 0
    delta = multiplier_bps - DAY_BPS
    raw = Decimal(base) * Decimal(delta) / Decimal(10000)
    return round_half_up_int(raw)


def _distance_surcharge(distance_km: float) -> int:
    excess = max(0.0, float(distance_km) - DIST_FREE_KM)
    km_units = int(math.ceil(excess))
    return km_units * DIST_PRICE_PER_KM_CENTS


def compute_estimated_fee(order: dict, item: dict, package_to_use):
    base = int(item["base_price_cents"])
    # PRD §3.2: 'the kilometre estimate from a default origin to the service
    # address'. The default origin is the service address itself for the
    # forward-looking estimate; the actual distance surcharge is reapplied
    # at settlement time using Dispatch.distance_km (PRD §3.5).
    distance_km = haversine_km(
        order["service_lat"], order["service_lng"],
        order["service_lat"], order["service_lng"],
    )
    distance_surcharge = _distance_surcharge(distance_km)
    sched_dt = parse_iso(order["scheduled_start"])
    multiplier = _tod_multiplier_bps(sched_dt)
    tod_surcharge = _surcharge(base, multiplier)
    package_deduction = base if (package_to_use is not None) else 0
    net = max(0, base + distance_surcharge + tod_surcharge - package_deduction)
    tax = round_half_up_int(Decimal(net) * Decimal(TAX_BPS) / Decimal(10000))
    return net + tax


# ----------------------------------------------------------- Create order --
def create_order(patient_id: str, body: dict):
    """Create an order; returns (order, was_replay_bool)."""
    code = require_str(body, "service_item_code")
    address = require_str(body, "service_address")
    lat = require_num(body, "service_lat")
    lng = require_num(body, "service_lng")
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise err("ERR_INVALID_REQUEST", "service_lat/service_lng out of range")
    sched_raw = require_str(body, "scheduled_start")
    try:
        sched_dt = parse_iso(sched_raw)
    except ValueError as e:
        raise err("ERR_INVALID_REQUEST", str(e))

    pref_gender = body.get("preferred_gender", "ANY")
    if pref_gender not in PREF_GENDERS:
        raise err("ERR_INVALID_REQUEST", f"preferred_gender must be one of {PREF_GENDERS}")
    pref_lang = body.get("preferred_language", "any")
    if not isinstance(pref_lang, str) or not pref_lang.strip():
        raise err("ERR_INVALID_REQUEST", "preferred_language must be a non-empty string")
    medical_doc_url = body.get("medical_doc_url")
    if medical_doc_url is not None and not isinstance(medical_doc_url, str):
        raise err("ERR_INVALID_REQUEST", "medical_doc_url must be a string")
    package_id = body.get("package_id")
    if package_id is not None and not isinstance(package_id, str):
        raise err("ERR_INVALID_REQUEST", "package_id must be a string")

    # Idempotency check first (after auth + body shape)
    existing, idem_key = _resolve_idempotency(patient_id, body)
    if existing is not None:
        return existing, True

    # ServiceItem must exist + active
    item = db.service_items.get(code)
    if item is None:
        raise err("ERR_RESOURCE_LINK_INVALID", "service_item_code does not exist")
    if not item.get("active", True):
        raise err("ERR_RESOURCE_LINK_INVALID", "service item is inactive")

    # Medical doc requirement
    if item.get("requires_medical_doc"):
        if not medical_doc_url or not medical_doc_url.strip():
            raise err("ERR_MEDICAL_DOC_REQUIRED",
                      "this service requires a medical document URL")

    # Package validation
    package_obj = None
    if package_id is not None:
        package_obj = db.packages.get(package_id)
        if package_obj is None:
            raise err("ERR_PACKAGE_NOT_FOUND", f"package {package_id} not found")
        if package_obj.get("patient_id") != patient_id:
            raise err("ERR_RESOURCE_LINK_INVALID", "package does not belong to caller")
        if package_obj.get("service_item_code") != code:
            raise err("ERR_RESOURCE_LINK_INVALID",
                      "package service_item_code mismatch")
        if package_obj.get("status") != "ACTIVE":
            raise err("ERR_INSUFFICIENT_PACKAGE_CREDIT", "package is not ACTIVE")
        if int(package_obj.get("used_credits") or 0) >= int(package_obj.get("total_credits") or 0):
            raise err("ERR_INSUFFICIENT_PACKAGE_CREDIT", "no credits remaining")

    order = {
        "patient_id": patient_id,
        "service_item_code": code,
        "service_address": address,
        "service_lat": float(lat),
        "service_lng": float(lng),
        "scheduled_start": iso(sched_dt),
        "preferred_gender": pref_gender,
        "preferred_language": pref_lang,
        "medical_doc_url": medical_doc_url,
        "package_id": package_id,
        "estimated_fee_cents": 0,
        "final_fee_cents": None,
        "status": "SUBMITTED",
        "payment_status": "UNPAID",
        "cancelled_reason": None,
        "dispatch_attempt_count": 0,
    }
    db.stamp_create(order, common_fields=True)
    db.orders[order["id"]] = order

    # Compute estimated fee
    order["estimated_fee_cents"] = compute_estimated_fee(order, item, package_obj)

    # Authorize payment if estimate > 0
    if order["estimated_fee_cents"] > 0:
        order["payment_status"] = "AUTHORIZED"

    # Auto-route
    if item.get("requires_eligibility_review"):
        order["status"] = "UNDER_REVIEW"
        db.stamp_update(order)
    else:
        order["status"] = "AWAITING_DISPATCH"
        db.stamp_update(order)
        # Trigger dispatch creation
        from services.dispatch import select_and_dispatch
        select_and_dispatch(order)

    # Persist idempotency
    if idem_key is not None:
        db.idempotency[idem_key] = {
            "sig": _payload_signature(body),
            "order_id": order["id"],
        }

    return order, False


# ------------------------------------------------------ Eligibility review --
def eligibility_review(order_id: str, body: dict) -> dict:
    order = get_order(order_id)
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT")
    if order["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")
    check_occ(order, body or {})
    if decision == "APPROVE":
        order["status"] = "AWAITING_DISPATCH"
        db.stamp_update(order)
        from services.dispatch import select_and_dispatch
        select_and_dispatch(order)
    else:
        order["status"] = "REJECTED"
        if order.get("payment_status") == "AUTHORIZED":
            order["payment_status"] = "REFUNDED"
        db.stamp_update(order)
    return order


# ------------------------------------------------------------------ Cancel --
def cancel_order(order_id: str, patient_id: str, body: dict) -> dict:
    order = get_order(order_id)
    if order.get("patient_id") != patient_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "cannot cancel another patient's order")
    if order["status"] not in ("SUBMITTED", "UNDER_REVIEW", "AWAITING_DISPATCH"):
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")
    check_occ(order, body or {})
    reason = (body or {}).get("cancelled_reason")
    if reason is not None and not isinstance(reason, str):
        raise err("ERR_INVALID_REQUEST", "cancelled_reason must be a string")
    order["cancelled_reason"] = reason
    order["status"] = "CANCELLED"
    if order.get("payment_status") == "AUTHORIZED":
        order["payment_status"] = "REFUNDED"
    db.stamp_update(order)
    # Cancel any OFFERED dispatches
    from services.dispatch import cancel_offered_dispatches_for_order
    cancel_offered_dispatches_for_order(order_id)
    return order


# ----------------------------------------------------- Confirm completion --
def confirm_completion(order_id: str, patient_id: str, body: dict) -> dict:
    order = get_order(order_id)
    if order.get("patient_id") != patient_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "cannot confirm another patient's order")
    if order["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")
    sr = _record_for_order(order_id)
    if sr is None or sr["status"] != "AWAITING_PATIENT_CONFIRM":
        raise err("ERR_INVALID_STATE", "service record not awaiting confirmation")
    item = db.service_items.get(order["service_item_code"])
    if item is not None and item["required_skill"] in WASTE_PRODUCING_SKILLS:
        # All waste entries must be ARCHIVED
        for w in db.waste_entries.values():
            if w.get("order_id") == order_id and w.get("status") != "ARCHIVED":
                raise err("ERR_WASTE_NOT_ARCHIVED",
                          "all waste entries must be ARCHIVED before confirmation")

    check_occ(order, body or {})

    # Finalize: order → COMPLETED, sr → COMPLETED, settle, capture, package++
    order["status"] = "COMPLETED"
    sr["status"] = "COMPLETED"
    db.stamp_update(sr)

    # Compute settlement
    from services.settlement import build_final_settlement
    settlement = build_final_settlement(order, sr)
    order["final_fee_cents"] = int(settlement["gross_fee_cents"]) + int(settlement["tax_cents"])
    if order.get("payment_status") == "AUTHORIZED":
        order["payment_status"] = "CAPTURED"
    db.stamp_update(order)

    # Package consumption
    if order.get("package_id"):
        pkg = db.packages.get(order["package_id"])
        if pkg is not None:
            pkg["used_credits"] = int(pkg.get("used_credits") or 0) + 1
            if pkg["used_credits"] >= int(pkg["total_credits"]):
                pkg["status"] = "EXHAUSTED"
            db.stamp_update(pkg)

    # Recompute nurse rating
    from services.rating import recompute_rating
    nurse_id = sr.get("nurse_id")
    if nurse_id:
        recompute_rating(nurse_id)

    audit("ORDER", order_id, "COMPLETE",
          payload={"final_fee_cents": order["final_fee_cents"]})
    return order


# ------------------------------------------------------------ Lookups --
def get_order(order_id: str) -> dict:
    o = db.orders.get(order_id)
    if o is None:
        raise err("ERR_ORDER_NOT_FOUND", f"order {order_id} not found")
    return o


def _record_for_order(order_id: str):
    for sr in db.service_records.values():
        if sr.get("order_id") == order_id:
            return sr
    return None


def list_orders_scoped(role: str, user_id: str, limit: int, offset: int, status=None):
    rows = list(db.orders.values())
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if role == "Patient":
        rows = [r for r in rows if r.get("patient_id") == user_id]
    elif role == "Nurse":
        # Show only orders dispatched/assigned to this nurse (any dispatch where nurse_id matches)
        own_order_ids = set()
        for d in db.dispatches.values():
            if d.get("nurse_id") == user_id:
                own_order_ids.add(d["order_id"])
        rows = [r for r in rows if r["id"] in own_order_ids]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total


def get_order_scoped(order_id: str, role: str, user_id: str) -> dict:
    o = get_order(order_id)
    if role == "Patient":
        if o.get("patient_id") != user_id:
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your order")
    elif role == "Nurse":
        # Allowed if any dispatch on this order has nurse_id == user
        has_dispatch = any(
            d.get("nurse_id") == user_id and d.get("order_id") == o["id"]
            for d in db.dispatches.values()
        )
        if not has_dispatch:
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your order")
    return o
