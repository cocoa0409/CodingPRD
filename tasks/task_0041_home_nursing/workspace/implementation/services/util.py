"""Shared utilities: OCC, geo, money rounding."""
import math
from decimal import Decimal, ROUND_HALF_UP

from errors import err


# -------------------------------------------------------------------- Money --
def round_half_up_int(value) -> int:
    """Round a numeric value to the nearest integer using ROUND_HALF_UP."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimals(value, places: int) -> Decimal:
    """Round to `places` decimal places using ROUND_HALF_UP."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    quant = Decimal(1).scaleb(-places)
    return d.quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------- Geo --
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance between two coords in kilometres."""
    lat1_r = math.radians(float(lat1))
    lat2_r = math.radians(float(lat2))
    dlat = math.radians(float(lat2) - float(lat1))
    dlng = math.radians(float(lng2) - float(lng1))
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def haversine_km_3dp(lat1, lng1, lat2, lng2) -> float:
    """Distance in km, rounded to 3 decimals (used for storage on Dispatch.distance_km)."""
    raw = haversine_km(lat1, lng1, lat2, lng2)
    return float(round_half_up_decimals(raw, 3))


# ---------------------------------------------------------------- OCC check --
def check_occ(entity: dict, body: dict) -> None:
    """When body provides `version`, compare with entity['version']."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body.get("version") is None:
        return
    try:
        provided = int(body["version"])
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "version must be an integer")
    current = entity.get("version")
    if current is None:
        return
    if provided != current:
        raise err("ERR_VERSION_CONFLICT", "version mismatch")


# ----------------------------------------------------------- Field helpers --
def require_str(body: dict, key: str) -> str:
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing field: {key}")
    val = body[key]
    if not isinstance(val, str) or not val.strip():
        raise err("ERR_INVALID_REQUEST", f"{key} must be a non-empty string")
    return val


def require_int(body: dict, key: str) -> int:
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing field: {key}")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{key} must be an integer")
    return val


def require_num(body: dict, key: str):
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing field: {key}")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{key} must be a number")
    return val


def require_bool(body: dict, key: str) -> bool:
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing field: {key}")
    val = body[key]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{key} must be a boolean")
    return val


def require_enum(body: dict, key: str, allowed: set) -> str:
    val = require_str(body, key)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{key} must be one of {sorted(allowed)}")
    return val


def require_list(body: dict, key: str) -> list:
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing field: {key}")
    val = body[key]
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", f"{key} must be an array")
    return val
