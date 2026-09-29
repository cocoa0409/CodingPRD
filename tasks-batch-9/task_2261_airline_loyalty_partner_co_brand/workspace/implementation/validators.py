"""Ladder rung 7 -- request body well-formedness (ERR_INVALID_REQUEST, 400)."""

import re
from datetime import date, datetime, timezone

from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")


def bad(name, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def present(body, name):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return body[name]


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be at most %d" % maximum)
    return value


def req_int(body, name, minimum=None, maximum=None):
    return as_int(present(body, name), name, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return as_int(body[name], name, minimum, maximum)


def as_str(value, name, allow_empty=False, max_len=None):
    if not isinstance(value, str):
        bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        bad(name, "must be non-empty")
    if max_len is not None and len(value) > max_len:
        bad(name, "must be at most %d characters" % max_len)
    return value


def req_str(body, name, allow_empty=False, max_len=None):
    return as_str(present(body, name), name, allow_empty, max_len)


def opt_str(body, name, default=None, allow_empty=False, max_len=None):
    if name not in body or body[name] is None:
        return default
    return as_str(body[name], name, allow_empty, max_len)


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def req_enum(body, name, allowed):
    return as_enum(present(body, name), name, allowed)


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return as_enum(body[name], name, allowed)


def parse_date(value, name):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        bad(name, "must be an ISO-8601 date (YYYY-MM-DD)")
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad(name, "must be a valid calendar date")


def req_date(body, name):
    return parse_date(present(body, name), name)


def opt_date(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return parse_date(body[name], name)


def parse_dt(value, name):
    if not isinstance(value, str) or value.strip() == "":
        bad(name, "must be an ISO-8601 instant")
    text = value.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        bad(name, "must be an ISO-8601 instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(body, name):
    return parse_dt(present(body, name), name)


def opt_dt(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return parse_dt(body[name], name)


def req_period(body, name):
    value = present(body, name)
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        bad(name, "must be a YYYY-MM accounting period")
    return value


def opt_period(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        bad(name, "must be a YYYY-MM accounting period")
    return value


def opt_currency(body, name, default="USD"):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or not _CURRENCY_RE.match(value):
        bad(name, "must be a three-letter ISO-4217 code")
    return value.upper()


def req_tier_schedule(body, name="tier_schedule"):
    """PRD 2.9 rung 7 -- array of {threshold_miles, price_per_mile_centicents};
    first threshold 0, strictly increasing thresholds, strictly decreasing
    prices."""
    raw = present(body, name)
    if not isinstance(raw, list) or len(raw) < 1:
        bad(name, "must be a non-empty array")
    out = []
    prev_threshold = None
    prev_price = None
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            bad(name, "entries must be objects")
        label = "%s[%d].threshold_miles" % (name, index)
        if "threshold_miles" not in entry or entry["threshold_miles"] is None:
            bad(label, "is required")
        threshold = as_int(entry["threshold_miles"], label, minimum=0)
        label = "%s[%d].price_per_mile_centicents" % (name, index)
        if "price_per_mile_centicents" not in entry or entry["price_per_mile_centicents"] is None:
            bad(label, "is required")
        price = as_int(entry["price_per_mile_centicents"], label, minimum=0)
        if index == 0 and threshold != 0:
            bad("%s[0].threshold_miles" % name, "must be 0")
        if prev_threshold is not None and threshold <= prev_threshold:
            bad("%s.threshold_miles" % name, "must strictly increase")
        if prev_price is not None and price >= prev_price:
            bad("%s.price_per_mile_centicents" % name, "must strictly decrease")
        prev_threshold = threshold
        prev_price = price
        out.append({"threshold_miles": threshold, "price_per_mile_centicents": price})
    return out
