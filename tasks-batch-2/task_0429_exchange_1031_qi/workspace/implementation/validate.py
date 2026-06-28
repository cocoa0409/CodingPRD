"""Request-body validation helpers (priority 4 -> ERR_INVALID_REQUEST, PRD §2.10).

Required fields present and correctly typed, enums within declared sets, numeric
bounds satisfied. Raises ApiError(ERR_INVALID_REQUEST, 422) on any violation.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import errors
import util


def body():
    """Parse the JSON body; an absent/invalid body is treated as an empty object.

    Endpoints with no input accept an empty/absent body. Endpoints with required
    fields detect missing fields via require_*.
    """
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_str(data, field, allow_empty=False):
    if field not in data:
        raise errors.invalid_request(f"Missing required field: {field}.")
    value = data[field]
    if not isinstance(value, str):
        raise errors.invalid_request(f"Field {field} must be a string.")
    if not allow_empty and value.strip() == "":
        raise errors.invalid_request(f"Field {field} must be non-empty.")
    return value


def require_enum(data, field, allowed):
    if field not in data:
        raise errors.invalid_request(f"Missing required field: {field}.")
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(allowed)}."
        )
    return value


def _coerce_number(field, value):
    if isinstance(value, bool):
        raise errors.invalid_request(f"Field {field} must be a number.")
    if isinstance(value, (int, float)):
        try:
            return util.to_decimal(value)
        except (ValueError, InvalidOperation):
            raise errors.invalid_request(f"Field {field} must be a number.")
    raise errors.invalid_request(f"Field {field} must be a number.")


def require_number(data, field, gt=None, gte=None):
    if field not in data:
        raise errors.invalid_request(f"Missing required field: {field}.")
    dec = _coerce_number(field, data[field])
    _check_bounds(field, dec, gt, gte)
    return util.money(dec)


def optional_number(data, field, default, gt=None, gte=None):
    if field not in data or data[field] is None:
        return util.money(default)
    dec = _coerce_number(field, data[field])
    _check_bounds(field, dec, gt, gte)
    return util.money(dec)


def _check_bounds(field, dec, gt, gte):
    if gt is not None and not (dec > Decimal(str(gt))):
        raise errors.invalid_request(f"Field {field} must be greater than {gt}.")
    if gte is not None and not (dec >= Decimal(str(gte))):
        raise errors.invalid_request(f"Field {field} must be greater than or equal to {gte}.")


def require_int(data, field):
    if field not in data:
        raise errors.invalid_request(f"Missing required field: {field}.")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    return value
