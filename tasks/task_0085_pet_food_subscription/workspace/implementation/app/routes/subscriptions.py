"""Subscription endpoints."""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any, Dict, List

from flask import Blueprint, request

from app.audit import append_audit
from app.auth import assert_customer_owns, require_role
from app.calculations import verify_address_inplace
from app.clock import logical_clock
from app.errors import api_error
from app.response import success_object
from app.services.recommendations import create_pending_recommendation, supersede
from app.services.subscriptions import compute_next_cycle_iso, derive_cycle_days, get_next_scheduled_order
from app.services.orders import cancel_order_fulfillment
from app.store import store
from app.utils import (
    format_iso,
    is_int,
    is_nonempty_str,
    logical_now_iso,
    new_id,
    parse_iso,
)


bp = Blueprint("subscriptions", __name__)


VALID_FREQ = {"WEEKLY", "BIWEEKLY", "MONTHLY"}
VALID_CANCEL_REASONS = {"PRICE", "QUALITY", "PET_NO_LONGER", "OTHER"}


def _normalize_address(addr):
    if not isinstance(addr, dict):
        raise api_error("ERR_INVALID_REQUEST", "shipping_address must be object")
    return {
        "line1": addr.get("line1"),
        "line2": addr.get("line2"),
        "city": addr.get("city"),
        "region": addr.get("region"),
        "postal_code": addr.get("postal_code"),
        "country": addr.get("country"),
        "verified": False,
    }


def _validate_pet_list(customer_id: str, pet_ids: List[str]) -> List[Dict[str, Any]]:
    if not isinstance(pet_ids, list) or len(pet_ids) == 0:
        raise api_error("ERR_INVALID_PET_LIST", "pet_ids must be non-empty list")
    if len(set(pet_ids)) != len(pet_ids):
        raise api_error("ERR_INVALID_PET_LIST", "pet_ids must be unique")
    pets = []
    for pid in pet_ids:
        pet = store.pets.get(pid)
        if not pet or pet.get("customer_id") != customer_id:
            raise api_error("ERR_INVALID_PET_LIST", f"Pet {pid} does not belong to customer")
        if pet.get("status") != "ACTIVE":
            raise api_error("ERR_PET_NOT_ACTIVE", f"Pet {pid} is not active")
        pets.append(pet)
    return pets


def _ensure_subscription(sub_id, user_id, role):
    sub = store.subscriptions.get(sub_id)
    if not sub:
        raise api_error("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found")
    assert_customer_owns(sub["customer_id"], user_id, role)
    return sub


@bp.route("/customers/<customer_id>/subscriptions", methods=["POST"])
@require_role("Customer")
def create_subscription(customer_id, user_id: str, role: str):
    cust = store.customers.get(customer_id)
    if not cust:
        raise api_error("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    assert_customer_owns(customer_id, user_id, role)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")

    pet_ids = body.get("pet_ids")
    frequency = body.get("frequency")
    shipping_address = body.get("shipping_address")
    is_trial = bool(body.get("is_trial", False))

    if frequency not in VALID_FREQ:
        raise api_error("ERR_INVALID_REQUEST", "frequency must be WEEKLY|BIWEEKLY|MONTHLY")
    if shipping_address is None:
        raise api_error("ERR_INVALID_REQUEST", "shipping_address is required")
    addr = _normalize_address(shipping_address)

    _validate_pet_list(customer_id, pet_ids or [])

    sub_id = new_id()
    now = logical_now_iso()
    sub = {
        "id": sub_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "customer_id": customer_id,
        "pet_ids": list(pet_ids),
        "frequency": frequency,
        "cycle_days": derive_cycle_days(frequency),
        "shipping_address": addr,
        "is_trial": is_trial,
        "status": "DRAFT",
        "paused_until": None,
        "cancel_reason": None,
        "retention_offer_applied": False,
        "scheduled_order_count": 0,
        "skipped_count": 0,
        "total_cycles_elapsed": 0,
        "modification_deadline_hours": 48,
        "next_cycle_at": None,
    }
    store.subscriptions[sub_id] = sub
    store.pause_windows.setdefault(sub_id, [])
    return success_object(sub, status=201)


@bp.route("/subscriptions/<sub_id>", methods=["GET"])
@require_role("Customer", "AdminOps")
def get_subscription(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>", methods=["PATCH"])
@require_role("Customer")
def patch_subscription(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")

    # Modification window if ACTIVE
    if sub["status"] == "ACTIVE":
        order = get_next_scheduled_order(sub_id)
        if order:
            ship_at = parse_iso(order["scheduled_ship_at"])
            cutoff = ship_at - timedelta(hours=int(sub["modification_deadline_hours"]))
            if logical_clock.now() >= cutoff:
                raise api_error("ERR_MODIFICATION_DEADLINE_PASSED", "Past modification deadline")

    new_freq = body.get("frequency")
    new_pet_ids = body.get("pet_ids")
    new_addr = body.get("shipping_address")

    if new_freq is not None and new_freq not in VALID_FREQ:
        raise api_error("ERR_INVALID_REQUEST", "frequency invalid")
    if new_pet_ids is not None:
        _validate_pet_list(sub["customer_id"], new_pet_ids)

    if "version" in body:
        if not is_int(body["version"]):
            raise api_error("ERR_INVALID_REQUEST", "version must be integer")
        if body["version"] != sub["version"]:
            raise api_error("ERR_VERSION_CONFLICT", "version mismatch")

    before = {
        k: copy.deepcopy(sub.get(k))
        for k in ("frequency", "pet_ids", "shipping_address", "cycle_days", "next_cycle_at")
    }

    if new_freq is not None and new_freq != sub["frequency"]:
        sub["frequency"] = new_freq
        sub["cycle_days"] = derive_cycle_days(new_freq)
        if sub["status"] == "ACTIVE":
            sub["next_cycle_at"] = compute_next_cycle_iso(logical_clock.now(), sub["cycle_days"])
    if new_pet_ids is not None:
        sub["pet_ids"] = list(new_pet_ids)
    if new_addr is not None:
        sub["shipping_address"] = _normalize_address(new_addr)

    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1
    after = {k: copy.deepcopy(sub.get(k)) for k in before.keys()}
    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Subscription",
        entity_id=sub_id,
        event_type="PLAN_MODIFIED",
        before=before,
        after=after,
    )
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>/shipping-address/verify", methods=["POST"])
@require_role("Customer")
def verify_sub_address(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    if not sub.get("shipping_address"):
        raise api_error("ERR_ADDRESS_VERIFICATION_FAILED", "No address to verify")
    ok = verify_address_inplace(sub["shipping_address"])
    if not ok:
        raise api_error("ERR_ADDRESS_VERIFICATION_FAILED", "Address verification failed")
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>/activate", methods=["POST"])
@require_role("Customer")
def activate(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    if sub["status"] not in ("DRAFT", "REACTIVATING"):
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Not in DRAFT or REACTIVATING")
    if not bool((sub.get("shipping_address") or {}).get("verified", False)):
        raise api_error("ERR_ADDRESS_NOT_VERIFIED", "Shipping address not verified")
    for pid in sub["pet_ids"]:
        pet = store.pets.get(pid)
        if not pet or pet.get("status") != "ACTIVE":
            raise api_error("ERR_PET_NOT_ACTIVE", f"Pet {pid} is not active")

    before = {"status": sub["status"]}
    came_from_reactivating = sub["status"] == "REACTIVATING"
    sub["status"] = "ACTIVE"
    sub["next_cycle_at"] = compute_next_cycle_iso(logical_clock.now(), sub["cycle_days"])
    if came_from_reactivating:
        sub["retention_offer_applied"] = False
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1

    # Generate initial PENDING recommendations for each pet (cycle 1)
    for pid in sub["pet_ids"]:
        pet = store.pets.get(pid)
        if pet:
            try:
                create_pending_recommendation(sub, pet, cycle_index=1)
            except Exception:
                # Eligibility error — surface? PRD only mentions ERR_NO_RECIPE_AVAILABLE
                # during order generation. We skip silently here so activation succeeds and
                # cycle scheduler will retry.
                pass

    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Subscription",
        entity_id=sub_id,
        event_type="REACTIVATED" if came_from_reactivating else "PLAN_MODIFIED",
        before=before,
        after={"status": "ACTIVE", "next_cycle_at": sub["next_cycle_at"]},
    )
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>/pause", methods=["POST"])
@require_role("Customer")
def pause(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    if sub["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Not ACTIVE")
    # Pause-in-transit: any order SHIPPED but not DELIVERED on this subscription?
    for o in store.orders.values():
        if o["subscription_id"] == sub_id and o["fulfillment_status"] == "SHIPPED":
            raise api_error("ERR_PAUSE_BLOCKED_IN_TRANSIT", "Order in transit")
    body = request.get_json(silent=True) or {}
    pause_until_raw = body.get("pause_until") if isinstance(body, dict) else None
    pause_until = parse_iso(pause_until_raw) if pause_until_raw else None
    if pause_until is None:
        raise api_error("ERR_INVALID_REQUEST", "pause_until required")
    now = logical_clock.now()
    if pause_until <= now:
        raise api_error("ERR_INVALID_PAUSE_WINDOW", "pause_until must be in the future")

    # Overlap check
    pu_existing = store.pause_windows.setdefault(sub_id, [])
    new_from = now
    new_to = pause_until
    for w in pu_existing:
        wf = parse_iso(w["from"])
        wt = parse_iso(w["to"])
        if wf and wt and new_from < wt and wf < new_to:
            raise api_error("ERR_PAUSE_WINDOW_OVERLAP", "Pause window overlaps")

    before = {"status": "ACTIVE", "next_cycle_at": sub.get("next_cycle_at")}
    sub["status"] = "PAUSED"
    sub["paused_until"] = format_iso(pause_until)
    sub["next_cycle_at"] = None
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1
    pu_existing.append({"from": format_iso(new_from), "to": format_iso(new_to)})

    # Cascade SCHEDULED+PENDING orders with scheduled_ship_at < paused_until → CANCELLED
    for o in list(store.orders.values()):
        if (
            o["subscription_id"] == sub_id
            and o["fulfillment_status"] == "SCHEDULED"
            and o["payment_status"] == "PENDING"
        ):
            sa = parse_iso(o["scheduled_ship_at"])
            if sa and sa < pause_until:
                cancel_order_fulfillment(o)

    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Subscription",
        entity_id=sub_id,
        event_type="PAUSED",
        before=before,
        after={"status": "PAUSED", "paused_until": sub["paused_until"], "next_cycle_at": None},
    )
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>/resume", methods=["POST"])
@require_role("Customer")
def resume(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    if sub["status"] != "PAUSED":
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Not PAUSED")
    before = {"status": "PAUSED", "paused_until": sub["paused_until"]}
    sub["status"] = "ACTIVE"
    sub["paused_until"] = None
    sub["next_cycle_at"] = compute_next_cycle_iso(logical_clock.now(), sub["cycle_days"])
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1
    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Subscription",
        entity_id=sub_id,
        event_type="RESUMED",
        before=before,
        after={"status": "ACTIVE", "next_cycle_at": sub["next_cycle_at"]},
    )
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>/cancel", methods=["POST"])
@require_role("Customer")
def cancel(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    reason = body.get("cancel_reason")
    force = bool(body.get("force", False))
    if reason not in VALID_CANCEL_REASONS:
        raise api_error("ERR_INVALID_CANCEL_REASON", "Invalid cancel_reason")
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Cannot cancel from current state")

    # Retention deflection
    if reason == "PRICE" and not sub.get("retention_offer_applied", False) and not force:
        sub["retention_offer_applied"] = True
        sub["updated_at"] = logical_now_iso()
        sub["version"] = sub.get("version", 1) + 1
        return success_object(sub)

    before = {"status": sub["status"]}
    sub["status"] = "CANCELLED"
    sub["cancel_reason"] = reason
    sub["next_cycle_at"] = None
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1

    # Cascade non-terminal orders to CANCELLED
    for o in list(store.orders.values()):
        if o["subscription_id"] == sub_id and o["fulfillment_status"] not in ("DELIVERED", "CANCELLED"):
            cancel_order_fulfillment(o)
    # Supersede PENDING/FROZEN recommendations
    for rec in list(store.recommendations.values()):
        if rec.get("subscription_id") == sub_id and rec.get("status") in ("PENDING", "FROZEN"):
            supersede(rec)

    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Subscription",
        entity_id=sub_id,
        event_type="CANCELLED",
        before=before,
        after={"status": "CANCELLED", "cancel_reason": reason},
    )
    return success_object(sub)


@bp.route("/subscriptions/<sub_id>/reactivate", methods=["POST"])
@require_role("Customer")
def reactivate(sub_id, user_id: str, role: str):
    sub = _ensure_subscription(sub_id, user_id, role)
    if sub["status"] != "CANCELLED":
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Not CANCELLED")
    for pid in sub["pet_ids"]:
        pet = store.pets.get(pid)
        if not pet or pet.get("status") != "ACTIVE":
            raise api_error("ERR_PET_NOT_ACTIVE", f"Pet {pid} not active")
    before = {"status": "CANCELLED"}
    sub["status"] = "REACTIVATING"
    sub["cancel_reason"] = None
    # Re-verify shipping address requirement: force verified to false
    if sub.get("shipping_address"):
        sub["shipping_address"]["verified"] = False
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1
    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Subscription",
        entity_id=sub_id,
        event_type="PLAN_MODIFIED",
        before=before,
        after={"status": "REACTIVATING"},
    )
    return success_object(sub)
