"""Generic request-body parsing helpers and Decimal-precision math."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err


def get_body() -> dict:
    """Return the JSON body of the current request as a dict (or empty dict)."""
    try:
        body = request.get_json(silent=True, force=False)
    except Exception:
        raise err("ERR_BAD_REQUEST", "Body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "Body must be a JSON object")
    return body


def require_field(body: dict, field: str):
    if field not in body:
        raise err("ERR_BAD_REQUEST", f"Missing required field: {field}")
    return body[field]


def round_half_up(x) -> int:
    """Round half away from zero to integer.

    Implemented with Decimal ROUND_HALF_UP semantics (which is half-away-from-zero,
    matching the PRD's "12.5 cents becomes 13 cents" example).
    """
    if isinstance(x, Decimal):
        d = x
    else:
        # Use repr to avoid float-printing artefacts; for ints this is fine too.
        d = Decimal(str(x))
    return int(d.to_integral_value(rounding=ROUND_HALF_UP))
