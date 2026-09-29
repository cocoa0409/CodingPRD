"""Request-shape validation (precedence rule 5) and existence resolution (rule 3)."""
import re

from flask import request

from db import db
from errors import ApiError
from util import dec, parse_iso_date

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

SENTINEL = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw and raw.strip():
            invalid("request body is not valid JSON")
        data = {}
    if not isinstance(data, dict):
        invalid("request body must be a JSON object")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, min_len=1, max_len=None, pattern=None):
    if not present(body, key):
        invalid("%s is required" % key)
    value = body[key]
    if not isinstance(value, str):
        invalid("%s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        invalid("%s is too short" % key)
    if max_len is not None and len(value) > max_len:
        invalid("%s is too long" % key)
    if pattern is not None and not re.match(pattern, value):
        invalid("%s has an invalid format" % key)
    return value


def opt_str(body, key, default=None, min_len=1, max_len=None, pattern=None):
    if not present(body, key):
        return default
    return req_str(body, key, min_len=min_len, max_len=max_len, pattern=pattern)


def req_int(body, key, minimum=None, maximum=None):
    if not present(body, key):
        invalid("%s is required" % key)
    value = body[key]
    if not _is_int(value):
        invalid("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        invalid("%s is below the permitted minimum" % key)
    if maximum is not None and value > maximum:
        invalid("%s is above the permitted maximum" % key)
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if not present(body, key):
        return default
    return req_int(body, key, minimum=minimum, maximum=maximum)


def req_fraction(body, key, minimum, maximum, max_decimals=None):
    if not present(body, key):
        invalid("%s is required" % key)
    value = body[key]
    if not _is_number(value):
        invalid("%s must be a number" % key)
    as_dec = dec(value)
    if as_dec < dec(minimum) or as_dec > dec(maximum):
        invalid("%s is outside its permitted range" % key)
    if max_decimals is not None:
        exponent = as_dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            invalid("%s carries too many decimal places" % key)
    return value


def req_bool(body, key):
    if not present(body, key):
        invalid("%s is required" % key)
    value = body[key]
    if not isinstance(value, bool):
        invalid("%s must be a boolean" % key)
    return value


def req_number(body, key, minimum=None, maximum=None):
    if not present(body, key):
        invalid("%s is required" % key)
    value = body[key]
    if not _is_number(value):
        invalid("%s must be a number" % key)
    if minimum is not None and dec(value) < dec(minimum):
        invalid("%s is below the permitted minimum" % key)
    if maximum is not None and dec(value) > dec(maximum):
        invalid("%s is above the permitted maximum" % key)
    return value


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        invalid("%s is not a recognised value" % key)
    return value


def opt_enum(body, key, allowed, default=None):
    if not present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_date(body, key):
    value = req_str(body, key)
    parsed = parse_iso_date(value)
    if parsed is None:
        invalid("%s must be an ISO date (YYYY-MM-DD)" % key)
    return value, parsed


def req_enum_list(body, key, allowed):
    if not present(body, key):
        invalid("%s is required" % key)
    value = body[key]
    if not isinstance(value, list) or len(value) == 0:
        invalid("%s must be a non-empty array" % key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("%s contains an unrecognised value" % key)
    return value


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            invalid("limit must lie between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset may not be negative")
    return limit, offset


# --------------------------------------------------------------- existence

_COLLECTIONS = {
    "publisher": ("publishers", "ERR_PUBLISHER_NOT_FOUND"),
    "journal": ("journals", "ERR_JOURNAL_NOT_FOUND"),
    "agreement": ("agreements", "ERR_AGREEMENT_NOT_FOUND"),
    "coverage": ("coverages", "ERR_COVERAGE_NOT_FOUND"),
    "author": ("authors", "ERR_AUTHOR_NOT_FOUND"),
    "funder": ("funders", "ERR_FUNDER_NOT_FOUND"),
    "grant": ("grants", "ERR_GRANT_NOT_FOUND"),
    "fund": ("funds", "ERR_FUND_NOT_FOUND"),
    "article": ("articles", "ERR_ARTICLE_NOT_FOUND"),
    "determination": ("determinations", "ERR_DETERMINATION_NOT_FOUND"),
    "fund_request": ("fund_requests", "ERR_FUND_REQUEST_NOT_FOUND"),
    "invoice": ("invoices", "ERR_INVOICE_NOT_FOUND"),
    "deposit": ("deposits", "ERR_DEPOSIT_NOT_FOUND"),
}


def resolve(kind, identifier):
    """Rule 3: resolve an identifier or raise the entity's own not-found code."""
    collection_name, error_id = _COLLECTIONS[kind]
    collection = getattr(db, collection_name)
    if not isinstance(identifier, str) or identifier not in collection:
        raise ApiError(error_id, 404)
    return collection[identifier]


def resolve_body_fk(body, key, kind, required=False):
    """Resolve a foreign key carried in the request body.

    A missing key is left to the request-shape stage (rule 5) so that the
    documented precedence -- existence before shape -- is preserved for the
    identifiers that were actually supplied.
    """
    if not present(body, key):
        if required:
            return None
        return None
    return resolve(kind, body[key])


def resolve_filter(kind, arg_name):
    """Identifiers supplied as list filters resolve on the same terms (PRD 2.5)."""
    raw = request.args.get(arg_name)
    if raw is None or raw == "":
        return None
    resolve(kind, raw)
    return raw


def filter_enum(arg_name, allowed):
    raw = request.args.get(arg_name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        invalid("%s is not a recognised value" % arg_name)
    return raw
