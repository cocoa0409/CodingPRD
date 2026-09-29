"""Request-shape validation (priority 3), field-value validation (priority 4)
and path/reference resolution (priorities 5 and 6)."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import fail
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT

# ---------------------------------------------------------------- body shape ----


def raw_body():
    data = request.get_data(as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = json.loads(data, parse_float=Decimal)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        if isinstance(value, bool):
            return False
        return isinstance(value, (int, Decimal, float))
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return True


def parse_body(spec):
    """spec: list of (name, kind, required). Rejects missing, mistyped and
    undeclared fields with ERR_INVALID_REQUEST (400)."""
    body = raw_body()
    declared = set(name for name, _kind, _req in spec)
    for key in body.keys():
        if key not in declared:
            fail("ERR_INVALID_REQUEST", "Undeclared field '%s'." % key)
    out = {}
    for name, kind, required in spec:
        if name not in body or body[name] is None:
            if required:
                fail("ERR_INVALID_REQUEST", "Required field '%s' is missing." % name)
            out[name] = None
            continue
        if not _type_ok(body[name], kind):
            fail("ERR_INVALID_REQUEST", "Field '%s' has the wrong JSON type." % name)
        out[name] = body[name]
    out["_present"] = set(k for k in body.keys())
    return out


def no_body():
    body = raw_body()
    if body:
        fail("ERR_INVALID_REQUEST", "This endpoint accepts no request body fields.")
    return {}


# ------------------------------------------------------------- field values ----


def check_enum(name, value, allowed):
    if value not in allowed:
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def check_str_len(name, value, lo, hi):
    if len(value) < lo or len(value) > hi:
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be %d..%d characters." % (name, lo, hi))
    return value


def check_int_range(name, value, lo=None, hi=None):
    if lo is not None and value < lo:
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be <= %s." % (name, hi))
    return value


def to_decimal(name, value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is not a valid number." % name)


def check_num_range(name, value, lo=None, hi=None, lo_strict=False, hi_strict=False):
    dec = to_decimal(name, value)
    if lo is not None:
        bound = Decimal(str(lo))
        if (dec <= bound) if lo_strict else (dec < bound):
            fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is out of range." % name)
    if hi is not None:
        bound = Decimal(str(hi))
        if (dec >= bound) if hi_strict else (dec > bound):
            fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is out of range." % name)
    return dec


def check_subset(name, values, allowed):
    if not isinstance(values, list) or len(values) == 0:
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be a non-empty array." % name)
    seen = set()
    for item in values:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_FIELD_VALUE", "Field '%s' contains an unknown member." % name)
        if item in seen:
            fail("ERR_INVALID_FIELD_VALUE", "Field '%s' contains duplicates." % name)
        seen.add(item)
    return list(values)


def parse_instant(name, value):
    if not isinstance(value, str):
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be an ISO 8601 instant." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is not a valid ISO 8601 instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ------------------------------------------------------------- query params ----


def _query_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except Exception:
        fail("ERR_INVALID_FIELD_VALUE", "Query parameter '%s' must be an integer." % name)
    if lo is not None and value < lo:
        fail("ERR_INVALID_FIELD_VALUE", "Query parameter '%s' is out of range." % name)
    if hi is not None and value > hi:
        fail("ERR_INVALID_FIELD_VALUE", "Query parameter '%s' is out of range." % name)
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_INVALID_FIELD_VALUE", "Query parameter '%s' is not a valid member." % name)
    return raw


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except Exception:
        fail("ERR_INVALID_FIELD_VALUE", "Query parameter '%s' must be an integer." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


# --------------------------------------------------------- path resolution ----


def get_client(client_id):
    row = store.S.clients.get(client_id)
    if row is None:
        fail("ERR_CLIENT_NOT_FOUND", "Client not found.")
    return row


def get_site(site_id):
    row = store.S.sites.get(site_id)
    if row is None:
        fail("ERR_SITE_NOT_FOUND", "Site not found.")
    return row


def get_contractor(contractor_id):
    row = store.S.contractors.get(contractor_id)
    if row is None:
        fail("ERR_CONTRACTOR_NOT_FOUND", "Contractor not found.")
    return row


def get_prequalification(prequalification_id):
    row = store.S.prequalifications.get(prequalification_id)
    if row is None:
        fail("ERR_PREQUALIFICATION_NOT_FOUND", "Prequalification not found.")
    return row


def get_worker(worker_id):
    row = store.S.workers.get(worker_id)
    if row is None:
        fail("ERR_WORKER_NOT_FOUND", "Worker not found.")
    return row


def get_certificate(certificate_id):
    row = store.S.insurance_certificates.get(certificate_id)
    if row is None:
        fail("ERR_INSURANCE_CERTIFICATE_NOT_FOUND", "Insurance certificate not found.")
    return row


def get_plan(plan_id):
    row = store.S.improvement_plans.get(plan_id)
    if row is None:
        fail("ERR_IMPROVEMENT_PLAN_NOT_FOUND", "Improvement plan not found.")
    return row


def get_leaf(table, row_id):
    row = table.get(row_id)
    if row is None:
        fail("ERR_RECORD_NOT_FOUND", "Record not found.")
    return row
