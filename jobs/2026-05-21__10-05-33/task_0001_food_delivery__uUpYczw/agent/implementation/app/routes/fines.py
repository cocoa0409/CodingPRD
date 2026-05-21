"""Fines — read / list / waive."""
from __future__ import annotations

from flask import Blueprint, request

from .. import cascade
from ..auth import require_role
from ..envelope import envelope_array, envelope_object
from ..errors import ApiError
from ..pagination import apply as apply_pagination, parse as parse_pagination
from ..store import get_clock, get_store

bp = Blueprint("fines", __name__, url_prefix="/api")


SUBJECT_TYPES = {"RIDER", "RESTAURANT", "CUSTOMER"}
SETTLEMENT_STATUSES = {"PENDING", "SETTLED", "WAIVED"}


def _ensure_fine(store, fid):
    rec = store.fines.get(fid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Fine {fid} not found")
    return rec


def _can_read(uid, role, fine):
    if role in {"PlatformAdmin", "CustomerService"}:
        return True
    if role == "Rider":
        return fine["subject_type"] == "RIDER" and fine["subject_id"] == uid
    if role == "Restaurant":
        return fine["subject_type"] == "RESTAURANT" and fine["subject_id"] == uid
    if role == "Customer":
        return fine["subject_type"] == "CUSTOMER" and fine["subject_id"] == uid
    return False


@bp.get("/fines/<fid>")
def read_fine(fid):
    uid, role = require_role({"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"})
    store = get_store()
    with store.lock:
        rec = _ensure_fine(store, fid)
        if not _can_read(uid, role, rec):
            raise ApiError("ERR_FORBIDDEN", "not your fine")
    return envelope_object(rec)


@bp.get("/fines")
def list_fines():
    uid, role = require_role({"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"})
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")
    if subject_type and subject_type not in SUBJECT_TYPES:
        raise ApiError("ERR_VALIDATION", "invalid subject_type")
    if settlement_status and settlement_status not in SETTLEMENT_STATUSES:
        raise ApiError("ERR_VALIDATION", "invalid settlement_status")

    if role in {"Rider", "Restaurant", "Customer"} and subject_id and subject_id != uid:
        raise ApiError("ERR_FORBIDDEN", "subject_id must match X-User-ID")

    store = get_store()
    with store.lock:
        items = list(store.fines.values())
        if role == "Rider":
            items = [f for f in items if f["subject_type"] == "RIDER" and f["subject_id"] == uid]
        elif role == "Restaurant":
            items = [f for f in items if f["subject_type"] == "RESTAURANT" and f["subject_id"] == uid]
        elif role == "Customer":
            items = [f for f in items if f["subject_type"] == "CUSTOMER" and f["subject_id"] == uid]
        if subject_type:
            items = [f for f in items if f["subject_type"] == subject_type]
        if subject_id:
            items = [f for f in items if f["subject_id"] == subject_id]
        if settlement_status:
            items = [f for f in items if f["settlement_status"] == settlement_status]
        window, total = apply_pagination(items, limit, offset)
    return envelope_array(window, limit=limit, offset=offset, total_count=total)


@bp.post("/fines/<fid>/waive")
def waive_fine(fid):
    require_role({"CustomerService", "PlatformAdmin"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_fine(store, fid)
        if rec["settlement_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "fine not PENDING")
        # Reverse ledger effect by subject type
        if rec["subject_type"] == "RIDER":
            rider = store.riders.get(rec["subject_id"])
            if rider:
                rider["wallet_balance_cents"] += rec["amount_cents"]
                cascade.touch(rider, clock)
        elif rec["subject_type"] == "CUSTOMER":
            customer = store.customers.get(rec["subject_id"])
            if customer:
                customer["credit_balance_cents"] += rec["amount_cents"]
                cascade.touch(customer, clock)
        elif rec["subject_type"] == "RESTAURANT":
            restaurant = store.restaurants.get(rec["subject_id"])
            if restaurant:
                restaurant["pending_settlement_cents"] += rec["amount_cents"]
                cascade.touch(restaurant, clock)
        rec["settlement_status"] = "WAIVED"
    return envelope_object(rec)
