"""Common utility helpers — precision/rounding, OCC, JSON canonicalisation."""
from decimal import Decimal, ROUND_HALF_UP
import json

from errors import err


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bools are ints in Python — guard
        raise err("ERR_AWARDED_OUT_OF_RANGE", "Expected number, got bool")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise err("ERR_AWARDED_OUT_OF_RANGE", "Expected number")


def round_half_up_2dp(value) -> float:
    """Round to 2 decimals half-up. Returns Python float (always two decimals)."""
    d = to_decimal(value)
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def occ_check(resource: dict, body: dict, *, error_id: str = "ERR_INVALID_STATE") -> None:
    """If the body provides a `version` field, ensure it matches the resource's
    current version. On mismatch raise APIError(error_id). If absent, skip."""
    if body is None:
        return
    if "version" not in body:
        return
    given = body["version"]
    if not isinstance(given, int) or isinstance(given, bool):
        raise err(error_id, "version mismatch")
    if int(resource.get("version", 0)) != given:
        raise err(error_id, "version mismatch")


def canonical_json(obj) -> str:
    """Deterministic JSON dump with sorted keys, used for paper hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
