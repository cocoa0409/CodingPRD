"""Request schema validation (band 5, ERR_INVALID_REQUEST / 400) and FK
resolution (bands 3 and 4)."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from db import store
from errors import fail

COHORT_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
PLAN_CODE_RE = re.compile(r"^[A-Z0-9_]+$")
LAST4_RE = re.compile(r"^[0-9]{4}$")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def bad(field, why="is invalid"):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field):
    if not present(data, field):
        bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty string")
    return value


def opt_str(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        bad(field, "must be a string")
    return value


def req_bool(data, field):
    if not present(data, field):
        bad(field, "is required")
    value = data[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def opt_bool(data, field, default):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def _as_int(field, value):
    if isinstance(value, bool):
        bad(field, "must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            bad(field, "must be an integer")
    bad(field, "must be an integer")


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad(field, "is required")
    value = _as_int(field, data[field])
    _range(field, value, minimum, maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    value = _as_int(field, data[field])
    _range(field, value, minimum, maximum)
    return value


def _range(field, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be <= %s" % maximum)


def _as_dec(field, value):
    if isinstance(value, bool):
        bad(field, "must be a number")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            bad(field, "must be a number")
    bad(field, "must be a number")


def dec4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def req_frac(data, field, minimum=Decimal("0"), maximum=None, exclusive_max=None):
    if not present(data, field):
        bad(field, "is required")
    return _frac(field, data[field], minimum, maximum, exclusive_max)


def opt_frac(data, field, default, minimum=Decimal("0"), maximum=None, exclusive_max=None):
    if not present(data, field):
        return default
    return _frac(field, data[field], minimum, maximum, exclusive_max)


def _frac(field, raw, minimum, maximum, exclusive_max):
    value = _as_dec(field, raw)
    if minimum is not None and value < minimum:
        bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be <= %s" % maximum)
    if exclusive_max is not None and value >= exclusive_max:
        bad(field, "must be < %s" % exclusive_max)
    return dec4(value)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def parse_dt(field, raw):
    if not isinstance(raw, str):
        bad(field, "must be an ISO 8601 datetime string")
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        bad(field, "must be an ISO 8601 datetime string")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def req_dt(data, field):
    if not present(data, field):
        bad(field, "is required")
    return parse_dt(field, data[field])


def opt_dt(data, field, default=None):
    if not present(data, field):
        return default
    return parse_dt(field, data[field])


def req_array(data, field, default=None):
    if not present(data, field):
        if default is None:
            bad(field, "is required")
        return list(default)
    value = data[field]
    if not isinstance(value, list):
        bad(field, "must be an array")
    return value


def opt_array(data, field, default):
    if not present(data, field):
        return list(default)
    value = data[field]
    if not isinstance(value, list):
        bad(field, "must be an array")
    return value


def cohort_month(data, field="cohort_month"):
    value = req_str(data, field)
    if not COHORT_MONTH_RE.match(value):
        bad(field, "must match YYYY-MM with a month between 01 and 12")
    return value


# --------------------------------------------------------------------------
# Existence resolution
# --------------------------------------------------------------------------
_NOT_FOUND = {
    "plans": "ERR_PLAN_NOT_FOUND",
    "subscribers": "ERR_SUBSCRIBER_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "payment_methods": "ERR_PAYMENT_METHOD_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "cancellation_sessions": "ERR_CANCELLATION_SESSION_NOT_FOUND",
    "save_offer_grants": "ERR_SAVE_OFFER_GRANT_NOT_FOUND",
    "save_offer_templates": "ERR_SAVE_OFFER_TEMPLATE_NOT_FOUND",
    "subscription_modifications": "ERR_MODIFICATION_NOT_FOUND",
    "compliance_notices": "ERR_COMPLIANCE_NOTICE_NOT_FOUND",
    "winback_campaigns": "ERR_WINBACK_CAMPAIGN_NOT_FOUND",
    "winback_targets": "ERR_WINBACK_TARGET_NOT_FOUND",
    "dunning_attempts": "ERR_DUNNING_ATTEMPT_NOT_FOUND",
    "cohort_snapshots": "ERR_COHORT_SNAPSHOT_NOT_FOUND",
}


def must_exist(collection, resource_id):
    rec = getattr(store, collection).get(resource_id) if isinstance(resource_id, str) else None
    if rec is None:
        fail(_NOT_FOUND[collection], "%s does not resolve" % collection[:-1])
    return rec


def fk(data, field, collection, required=True):
    """Body foreign-key resolution (band 4)."""
    if not present(data, field):
        if required:
            return None  # absence is a band-5 schema concern
        return None
    return must_exist(collection, data[field])
