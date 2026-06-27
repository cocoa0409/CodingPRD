"""Request parsing, pagination, calculations. All money is integer cents and
all percentage math uses Decimal + ROUND_HALF_UP (PRD §2.6)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import db, serialize


def body():
    """Parse the JSON body, tolerating an empty body (-> {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def round_half_up(value):
    """Round a Decimal/number to a whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct(base_cents, rate):
    """round_half_up(base_cents * rate) as an integer number of cents."""
    return round_half_up(Decimal(base_cents) * Decimal(str(rate)))


def paginate(items):
    """Apply limit/offset pagination (PRD §2.3). Defaults limit=10 (1..100),
    offset=0. Returns (window, limit, offset, total_count)."""
    limit = _int_param("limit", 10, minimum=1, maximum=100)
    offset = _int_param("offset", 0, minimum=0, maximum=None)
    total = len(items)
    window = items[offset:offset + limit]
    return window, limit, offset, total


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid %s" % name)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s below minimum" % name)
    if maximum is not None and val > maximum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s above maximum" % name)
    return val


def sort_created(items):
    """Default list sort: created_at ascending. Tie-break on id for stability."""
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))


def out(entity):
    return serialize(entity)


def out_list(entities):
    return [serialize(e) for e in entities]


# --- Existence helpers (ERR_NOT_FOUND, priority 3) ---

def get_or_404(collection, _id):
    ent = collection.get(_id)
    if ent is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return ent


def find_license_class_by_code(code):
    for lc in db.license_classes.values():
        if lc["code"] == code:
            return lc
    return None


def find_quota_region_by_code(region_code):
    for r in db.quota_regions.values():
        if r["region_code"] == region_code:
            return r
    return None
