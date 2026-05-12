"""Shared validation and rounding helpers."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_DOWN
from flask import request

from errors import err


def get_body() -> dict:
    if not request.data:
        return {}
    try:
        b = request.get_json(silent=True)
    except Exception:
        b = None
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return b


def require_field(body: dict, field: str):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")


def require_int(body: dict, field: str, allow_none: bool = False):
    if body.get(field) is None:
        if allow_none:
            return None
        raise err("ERR_VALIDATION", f"Missing required integer: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"{field} must be integer")
    return v


def round_half_up(num, denom) -> int:
    """Integer half-up division: (num/denom) rounded HALF_UP to nearest integer."""
    d = Decimal(num) / Decimal(denom)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_down(num, denom) -> int:
    d = Decimal(num) / Decimal(denom)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_DOWN))


# Optimistic concurrency check
def check_version(body: dict, entity: dict):
    if body is None:
        return
    if "version" in body and body["version"] is not None:
        client_v = body["version"]
        if not isinstance(client_v, int) or isinstance(client_v, bool):
            raise err("ERR_VERSION_CONFLICT", "version must be integer")
        if entity.get("version") != client_v:
            raise err("ERR_VERSION_CONFLICT", "Version mismatch")


# Risk index helpers
RISK_TOLERANCE_INDEX = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 5}
RISK_RATING_INDEX = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
