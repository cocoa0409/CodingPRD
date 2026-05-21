"""Shared validation/serialization helpers."""
from __future__ import annotations

import math
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from flask import request

from errors import ApiError
from store import iso_z


# ---- Body parsing ---------------------------------------------------------

def get_json_body() -> dict[str, Any]:
    """Return the JSON request body as a dict, or {} on no body. Raise ERR_VALIDATION on malformed JSON."""
    raw = request.get_data(cache=True, as_text=True) or ""
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Body must be a JSON object.")
    return body


# ---- Pagination -----------------------------------------------------------

def parse_pagination() -> tuple[int, int]:
    """Return (limit, offset). Raises ERR_VALIDATION on bad values."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit/offset must be integers.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    """Slice an already-sorted list and produce the meta extras."""
    total = len(items)
    window = items[offset : offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


# ---- Field validation -----------------------------------------------------

def require_field(body: dict, key: str) -> Any:
    if key not in body:
        raise ApiError("ERR_VALIDATION", f"Missing required field '{key}'.")
    return body[key]


def require_str(body: dict, key: str, max_len: int | None = None) -> str:
    v = require_field(body, key)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a non-empty string.")
    if max_len is not None and len(v) > max_len:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' exceeds maximum length {max_len}.")
    return v


def require_number(body: dict, key: str) -> float:
    v = require_field(body, key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a number.")
    return float(v)


def require_int(body: dict, key: str) -> int:
    v = require_field(body, key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be an integer.")
    return v


def optional_int(body: dict, key: str) -> int | None:
    if key not in body:
        return None
    v = body[key]
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be an integer.")
    return v


def optional_str(body: dict, key: str, max_len: int | None = None) -> str | None:
    if key not in body:
        return None
    v = body[key]
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a string.")
    if max_len is not None and len(v) > max_len:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' exceeds maximum length {max_len}.")
    return v


def optional_number(body: dict, key: str) -> float | None:
    if key not in body:
        return None
    v = body[key]
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a number.")
    return float(v)


def validate_lat_lng(lat: float, lng: float) -> None:
    if not (-90.0 <= lat <= 90.0):
        raise ApiError("ERR_VALIDATION", "lat must be in [-90, 90].")
    if not (-180.0 <= lng <= 180.0):
        raise ApiError("ERR_VALIDATION", "lng must be in [-180, 180].")


def validate_commission_rate(rate: float) -> None:
    if not (0.05 <= rate <= 0.35):
        raise ApiError("ERR_VALIDATION", "commission_rate_override must be in [0.05, 0.35].")


# ---- Geo helpers ----------------------------------------------------------

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return haversine_km(lat1, lng1, lat2, lng2) * 1000.0


def round_distance_km(d_km: float) -> float:
    """Round to 1 decimal place, half-up."""
    return float(Decimal(repr(d_km)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---- Money helpers --------------------------------------------------------

def round_half_up_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- Time helpers ---------------------------------------------------------

def is_peak(dt) -> bool:
    """Peak windows: 11:00-13:00 UTC and 18:00-20:00 UTC. Inclusive of start, exclusive of end."""
    h, m = dt.hour, dt.minute
    minutes = h * 60 + m
    if 11 * 60 <= minutes < 13 * 60:
        return True
    if 18 * 60 <= minutes < 20 * 60:
        return True
    return False
