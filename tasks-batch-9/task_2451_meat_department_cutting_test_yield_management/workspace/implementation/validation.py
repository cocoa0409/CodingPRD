"""Request-body and query-string validation helpers (ladder rungs 3, 4, 5)."""

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import errors
from errors import ApiError
from db import db

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        bad("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object")
    return parsed


def _present(payload, key):
    return key in payload and payload[key] is not None


def field_str(payload, key, required=False, min_len=None, max_len=None,
              default=None, forbidden=False, forbidden_msg=None):
    if forbidden:
        if _present(payload, key):
            bad(forbidden_msg or ("'%s' must not be supplied here" % key))
        return None
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        bad("'%s' must be a string" % key)
    if min_len is not None and len(value) < min_len:
        bad("'%s' must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("'%s' must be at most %d characters" % (key, max_len))
    return value


def field_enum(payload, key, allowed, required=False, default=None):
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        bad("'%s' must be one of %s" % (key, ", ".join(allowed)))
    return value


def field_int(payload, key, required=False, minimum=None, maximum=None, default=None):
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("'%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("'%s' must be at least %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("'%s' must be at most %s" % (key, maximum))
    return value


def field_num(payload, key, required=False, minimum=None, maximum=None,
              gt=None, lt=None, default=None, places=None,
              forbidden=False, forbidden_msg=None):
    """Numeric field. Returns a ``Decimal`` (never a float)."""
    if forbidden:
        if _present(payload, key):
            bad(forbidden_msg or ("'%s' must not be supplied here" % key))
        return None
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return default
    value = payload[key]
    if isinstance(value, bool):
        bad("'%s' must be a number" % key)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        try:
            value = Decimal(str(value))
        except InvalidOperation:
            bad("'%s' must be a number" % key)
    else:
        bad("'%s' must be a number" % key)
    if not value.is_finite():
        bad("'%s' must be a finite number" % key)
    if minimum is not None and value < minimum:
        bad("'%s' must be at least %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("'%s' must be at most %s" % (key, maximum))
    if gt is not None and value <= gt:
        bad("'%s' must be greater than %s" % (key, gt))
    if lt is not None and value >= lt:
        bad("'%s' must be less than %s" % (key, lt))
    if places is not None:
        from calc import rhu
        value = rhu(value, places)
    return value


def parse_instant(text, key):
    if not isinstance(text, str):
        bad("'%s' must be an ISO 8601 timestamp string" % key)
    candidate = text.strip()
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        bad("'%s' must be a well-formed ISO 8601 timestamp" % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def field_instant(payload, key, required=False):
    """Returns ``(raw_string, datetime)`` so the echo keeps the client's text."""
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return None, None
    raw = payload[key]
    return raw, parse_instant(raw, key)


def field_date(payload, key, required=False):
    """Returns ``(YYYY-MM-DD string, date)``."""
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return None, None
    raw = payload[key]
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        bad("'%s' must be a YYYY-MM-DD date" % key)
    try:
        parsed = date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        bad("'%s' must be a valid calendar date" % key)
    return raw, parsed


def field_id(payload, key, required=False):
    if not _present(payload, key):
        if required:
            bad("'%s' is required" % key)
        return None
    value = payload[key]
    if not isinstance(value, str) or value == "":
        bad("'%s' must be a non-empty identifier string" % key)
    return value


# --------------------------------------------------------------------------
# resolution helpers (rungs 3 and 5)
# --------------------------------------------------------------------------

_TABLES = {
    "department": ("departments", errors.ERR_DEPARTMENT_NOT_FOUND),
    "primal_purchase": ("primal_purchases", errors.ERR_PRIMAL_PURCHASE_NOT_FOUND),
    "cutting_test": ("cutting_tests", errors.ERR_CUTTING_TEST_NOT_FOUND),
    "cutting_test_line": ("cutting_test_lines", errors.ERR_CUTTING_TEST_LINE_NOT_FOUND),
    "retail_item": ("retail_items", errors.ERR_RETAIL_ITEM_NOT_FOUND),
    "case_plan": ("case_plans", errors.ERR_CASE_PLAN_NOT_FOUND),
    "case_plan_line": ("case_plan_lines", errors.ERR_CASE_PLAN_LINE_NOT_FOUND),
    "trim_lot": ("trim_lots", errors.ERR_TRIM_LOT_NOT_FOUND),
    "grind_run": ("grind_runs", errors.ERR_GRIND_RUN_NOT_FOUND),
    "grind_input": ("grind_inputs", errors.ERR_GRIND_INPUT_NOT_FOUND),
    "temperature_log": ("temperature_logs", errors.ERR_TEMPERATURE_LOG_NOT_FOUND),
    "case_failure": ("case_failures", errors.ERR_CASE_FAILURE_NOT_FOUND),
    "pre_order": ("pre_orders", errors.ERR_PRE_ORDER_NOT_FOUND),
    "shrink_reconciliation": ("shrink_reconciliations",
                              errors.ERR_SHRINK_RECONCILIATION_NOT_FOUND),
}


def resolve(kind, identifier):
    table_name, error_id = _TABLES[kind]
    table = getattr(db, table_name)
    row = table.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, 404, "%s does not exist" % kind.replace("_", " "))
    return row


def resolve_optional(kind, identifier):
    if identifier is None:
        return None
    return resolve(kind, identifier)


# --------------------------------------------------------------------------
# query-string helpers
# --------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            bad("'limit' must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("'limit' must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            bad("'offset' must be an integer")
        if offset < 0:
            bad("'offset' must be at least 0")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("'%s' must be true or false" % name)
