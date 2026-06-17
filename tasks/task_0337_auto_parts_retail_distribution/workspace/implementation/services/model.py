"""Entity lifecycle helpers: common-field stamping, mutation bumping, lookups,
and serialization that strips internal bookkeeping keys.
"""
from __future__ import annotations

import datetime

from db import db, new_id, now_iso
from errors import (
    not_found,
    ERR_PART_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND,
    ERR_FITMENT_NOT_FOUND,
    ERR_CROSS_REFERENCE_NOT_FOUND,
    ERR_PRICE_TIER_NOT_FOUND,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_SALES_ORDER_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_CORE_RETURN_NOT_FOUND,
    ERR_WARRANTY_CLAIM_NOT_FOUND,
    ERR_REORDER_REQUEST_NOT_FOUND,
    ERR_DRIVER_NOT_FOUND,
    ERR_BAY_NOT_FOUND,
    ERR_DELIVERY_RUN_NOT_FOUND,
)

# Keys that are bookkeeping-only and must never appear in API responses.
_INTERNAL_KEYS = {"_seq", "_shipped_at", "_shipped_at_us", "_created_us"}


def stamp_common(record: dict) -> dict:
    """Add id, created_at, updated_at, version (full mutable record)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    # High-resolution creation instant for time-window comparisons that the
    # millisecond-precision created_at string cannot disambiguate (e.g. a
    # warranty claim filed in the same millisecond as ship on a 0-day window).
    record["_created_us"] = datetime.datetime.now(datetime.timezone.utc)
    return record


def stamp_immutable(record: dict) -> dict:
    """Add id and created_at only (Fitment, CrossReference — PRD §2.4)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record: dict) -> None:
    """Mark a mutable record modified: refresh updated_at, bump version."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def serialize(record: dict) -> dict:
    """Return a copy of a record without internal bookkeeping keys."""
    return {k: v for k, v in record.items() if k not in _INTERNAL_KEYS}


# --- Existence lookups (left-to-right, per PRD §2.7) ---

def get_part(pid: str) -> dict:
    rec = db.parts.get(pid)
    if rec is None:
        raise not_found(ERR_PART_NOT_FOUND)
    return rec


def get_vehicle(vid: str) -> dict:
    rec = db.vehicles.get(vid)
    if rec is None:
        raise not_found(ERR_VEHICLE_NOT_FOUND)
    return rec


def get_fitment(fid: str) -> dict:
    rec = db.fitments.get(fid)
    if rec is None:
        raise not_found(ERR_FITMENT_NOT_FOUND)
    return rec


def get_cross_reference(xid: str) -> dict:
    rec = db.cross_references.get(xid)
    if rec is None:
        raise not_found(ERR_CROSS_REFERENCE_NOT_FOUND)
    return rec


def get_price_tier(tid: str) -> dict:
    rec = db.price_tiers.get(tid)
    if rec is None:
        raise not_found(ERR_PRICE_TIER_NOT_FOUND)
    return rec


def get_account(aid: str) -> dict:
    rec = db.accounts.get(aid)
    if rec is None:
        raise not_found(ERR_ACCOUNT_NOT_FOUND)
    return rec


def get_sales_order(oid: str) -> dict:
    rec = db.sales_orders.get(oid)
    if rec is None:
        raise not_found(ERR_SALES_ORDER_NOT_FOUND)
    return rec


def get_order_line(lid: str) -> dict:
    rec = db.order_lines.get(lid)
    if rec is None:
        raise not_found(ERR_ORDER_LINE_NOT_FOUND)
    return rec


def get_core_return(cid: str) -> dict:
    rec = db.core_returns.get(cid)
    if rec is None:
        raise not_found(ERR_CORE_RETURN_NOT_FOUND)
    return rec


def get_warranty_claim(wid: str) -> dict:
    rec = db.warranty_claims.get(wid)
    if rec is None:
        raise not_found(ERR_WARRANTY_CLAIM_NOT_FOUND)
    return rec


def get_reorder_request(rid: str) -> dict:
    rec = db.reorder_requests.get(rid)
    if rec is None:
        raise not_found(ERR_REORDER_REQUEST_NOT_FOUND)
    return rec


def get_driver(did: str) -> dict:
    rec = db.drivers.get(did)
    if rec is None:
        raise not_found(ERR_DRIVER_NOT_FOUND)
    return rec


def get_bay(bid: str) -> dict:
    rec = db.bays.get(bid)
    if rec is None:
        raise not_found(ERR_BAY_NOT_FOUND)
    return rec


def get_delivery_run(rid: str) -> dict:
    rec = db.delivery_runs.get(rid)
    if rec is None:
        raise not_found(ERR_DELIVERY_RUN_NOT_FOUND)
    return rec
