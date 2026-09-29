"""Request-shape validation (priority 4), entity lookup (priorities 5 and 7)
and pagination parsing."""

from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import ApiError, bad_request
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from util import D, parse_iso

_MISSING = object()


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------

def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object")
    return parsed


def reject_unknown(*_args, **_kwargs):
    """Unknown members are ignored, never rejected."""
    return None


# ---------------------------------------------------------------------------
# scalar field validators
# ---------------------------------------------------------------------------

def _present(src, name, required, default):
    """Returns the supplied value, or _MISSING when the caller omitted it.

    A supplied ``default`` is returned as-is (unvalidated) for omitted fields.
    """
    if name not in src or src.get(name) is None:
        if required:
            raise bad_request("Field '%s' is required" % name)
        return _MISSING if default is _MISSING else _Defaulted(default)
    return src[name]


class _Defaulted(object):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def _short_circuit(value):
    """(should_return, value) for omitted / defaulted fields."""
    if value is _MISSING:
        return True, None
    if isinstance(value, _Defaulted):
        return True, value.value
    if value is None:
        return True, None
    return False, value


def f_str(src, name, required=True, min_len=1, max_len=None, default=_MISSING):
    done, value = _short_circuit(_present(src, name, required, default))
    if done:
        return value
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' must be at most %d characters" % (name, max_len))
    return value


def f_enum(src, name, choices, required=True, default=_MISSING):
    done, value = _short_circuit(_present(src, name, required, default))
    if done:
        return value
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if value not in choices:
        raise bad_request(
            "Field '%s' must be one of %s" % (name, ", ".join(sorted(choices)))
        )
    return value


def f_bool(src, name, required=False, default=_MISSING):
    done, value = _short_circuit(_present(src, name, required, default))
    if done:
        return value
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean" % name)
    return value


def f_int(src, name, required=True, minimum=None, maximum=None, choices=None,
          default=_MISSING):
    done, value = _short_circuit(_present(src, name, required, default))
    if done:
        return value
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be an integer" % name)
    if isinstance(value, int):
        parsed = value
    else:
        try:
            dec = D(value)
        except (InvalidOperation, ValueError, TypeError):
            raise bad_request("Field '%s' must be an integer" % name)
        if dec != dec.to_integral_value():
            raise bad_request("Field '%s' must be an integer" % name)
        parsed = int(dec)
    if minimum is not None and parsed < minimum:
        raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and parsed > maximum:
        raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    if choices is not None and parsed not in choices:
        raise bad_request(
            "Field '%s' must be one of %s" % (name, ", ".join(str(c) for c in choices))
        )
    return parsed


def f_dec(src, name, required=True, scale=2, minimum=None, maximum=None,
          exclusive_min=None, default=_MISSING):
    done, value = _short_circuit(_present(src, name, required, default))
    if done:
        return value
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be a number" % name)
    if not isinstance(value, (int, float, str, Decimal)):
        raise bad_request("Field '%s' must be a number" % name)
    try:
        dec = D(value)
    except (InvalidOperation, ValueError, TypeError):
        raise bad_request("Field '%s' must be a number" % name)
    if not dec.is_finite():
        raise bad_request("Field '%s' must be a finite number" % name)
    exponent = dec.as_tuple().exponent
    if scale is not None and exponent < -int(scale):
        # trailing zeros beyond the declared scale are harmless
        if dec != dec.quantize(Decimal(1).scaleb(-int(scale))):
            raise bad_request(
                "Field '%s' must have at most %d decimal places" % (name, scale)
            )
        dec = dec.quantize(Decimal(1).scaleb(-int(scale)))
    if minimum is not None and dec < D(minimum):
        raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and dec > D(maximum):
        raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    if exclusive_min is not None and dec <= D(exclusive_min):
        raise bad_request("Field '%s' must be greater than %s" % (name, exclusive_min))
    return dec


def f_dt(src, name, required=True, default=_MISSING):
    """Returns (datetime, raw_string) so responses can echo the exact input."""
    done, value = _short_circuit(_present(src, name, required, default))
    if done:
        return value, None
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO-8601 timestamp string" % name)
    parsed = parse_iso(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO-8601 timestamp string" % name)
    return parsed, value


def f_version(src, name):
    """OCC fields are required, non-optional integer inputs."""
    if name not in src or src.get(name) is None:
        raise bad_request("Field '%s' is required" % name)
    return f_int(src, name, required=True)


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(str(args.get("limit")).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad_request(
                "Query parameter 'limit' must be between %d and %d"
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(str(args.get("offset")).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]


# ---------------------------------------------------------------------------
# entity lookup
# ---------------------------------------------------------------------------

_LOOKUPS = (
    ("brewers", "ERR_BREWER_NOT_FOUND"),
    ("programs", "ERR_CROP_YEAR_PROGRAM_NOT_FOUND"),
    ("varieties", "ERR_HOP_VARIETY_NOT_FOUND"),
    ("contracts", "ERR_HOP_CONTRACT_NOT_FOUND"),
    ("offers", "ERR_SUBSTITUTION_OFFER_NOT_FOUND"),
    ("malt_products", "ERR_MALT_PRODUCT_NOT_FOUND"),
    ("malt_lots", "ERR_MALT_LOT_NOT_FOUND"),
    ("strains", "ERR_YEAST_STRAIN_NOT_FOUND"),
    ("recipes", "ERR_BREWER_RECIPE_NOT_FOUND"),
    ("jobs", "ERR_YEAST_JOB_NOT_FOUND"),
    ("orders", "ERR_SALES_ORDER_NOT_FOUND"),
    ("lines", "ERR_ORDER_LINE_NOT_FOUND"),
    ("zones", "ERR_COLD_STORAGE_ZONE_NOT_FOUND"),
    ("shipments", "ERR_COLD_CHAIN_SHIPMENT_NOT_FOUND"),
)

_ERROR_FOR = dict(_LOOKUPS)


def must_exist(collection, entity_id):
    if entity_id is None:
        raise ApiError(_ERROR_FOR[collection], "%s not found" % collection)
    found = getattr(db, collection).get(entity_id)
    if found is None:
        raise ApiError(_ERROR_FOR[collection], "Referenced resource not found")
    return found


def filter_exists(collection, entity_id):
    """A filter value that names an identifier must resolve or 404."""
    if entity_id is None:
        return None
    return must_exist(collection, entity_id)
