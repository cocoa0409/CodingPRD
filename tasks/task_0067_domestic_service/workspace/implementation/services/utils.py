"""Shared business utilities: distance, rounding, pagination, OCC."""
from decimal import Decimal, ROUND_HALF_UP
from math import radians, sin, cos, asin, sqrt
from flask import request

from db import store
from errors import (
    ERR_VERSION_CONFLICT, ERR_VALIDATION_ERROR, raise_error,
)


def haversine_km(lat1, lon1, lat2, lon2) -> Decimal:
    """Great-circle distance between two lat/lng pairs, in km, to 6 decimal places."""
    R = Decimal("6371")  # earth radius km
    lat1f, lon1f, lat2f, lon2f = float(lat1), float(lon1), float(lat2), float(lon2)
    phi1, phi2 = radians(lat1f), radians(lat2f)
    dphi = radians(lat2f - lat1f)
    dlam = radians(lon2f - lon1f)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    c = 2 * asin(sqrt(a))
    d_km = float(R) * c
    return Decimal(str(d_km)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def round_half_up_int(value) -> int:
    """Round a numeric value half-up to integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    """Round to 4 decimal places half-up. Returns a Decimal."""
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def decimal_to_float4(d: Decimal) -> float:
    """Render a 4-decimal Decimal as a float for the response payload."""
    return float(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------- Pagination ----------
def parse_pagination():
    """Parse limit/offset from request query string per PRD §2.3.
    Returns (limit, offset). Defaults: limit=10 (min 1, max 100), offset=0.
    Invalid values raise ERR_VALIDATION_ERROR (422)."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    try:
        limit = int(limit_s) if limit_s is not None else 10
        offset = int(offset_s) if offset_s is not None else 0
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION_ERROR, "Invalid limit or offset")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC and apply window. Items must have 'created_at'.

    For entities without created_at (append-only logs), the caller should sort
    explicitly before calling this; we still sort by created_at if present.
    Returns (window, pagination_dict)."""
    def sort_key(x):
        return (x.get("created_at") or "", x.get("id") or "")
    sorted_items = sorted(items, key=sort_key)
    total = len(sorted_items)
    window = sorted_items[offset:offset + limit]
    has_more = (offset + limit) < total
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


# ---------- Common fields ----------
def stamp_create(record: dict, with_version=True):
    """Set id, created_at, updated_at, version=1."""
    if "id" not in record:
        record["id"] = store.new_id()
    record["created_at"] = store.now_iso()
    record["updated_at"] = store.now_iso()
    if with_version:
        record["version"] = 1
    return record


def stamp_update(record: dict, with_version=True):
    record["updated_at"] = store.now_iso()
    if with_version and "version" in record:
        record["version"] = int(record.get("version", 1)) + 1
    return record


def check_occ(record: dict, body: dict):
    """If body contains 'version' AND record has version, compare exact.
    Mismatch raises ERR_VERSION_CONFLICT."""
    if body and "version" in body and body["version"] is not None:
        if int(body["version"]) != int(record.get("version", 1)):
            raise_error(ERR_VERSION_CONFLICT, "Version conflict on optimistic concurrency check")
