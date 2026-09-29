"""Request-shape validation (PRD section 2.8 rungs 7-10)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

UTC = timezone.utc
_STATE_CODE = re.compile(r"^[A-Z]{2}$")

# --- enum vocabularies (PRD section 3 / scaffold entity constraints) --------
ENUM_FILING_TYPE = ("ABSTRACT_OF_JUDGMENT", "JUDGMENT_LIEN")
ENUM_FILING_OUTCOME = ("RECORDED", "REJECTED")
ENUM_ASSET_TYPE = ("REAL_PROPERTY", "BANK_ACCOUNT", "EMPLOYMENT", "VEHICLE")
ENUM_FINDING_SOURCE = ("SKIP_TRACE", "PUBLIC_RECORD", "CREDIT_HEADER", "DEBTOR_EXAM")
ENUM_ACTION_TYPE = ("WAGE_GARNISHMENT", "BANK_LEVY")
ENUM_CLAIM_TYPE = ("HEAD_OF_HOUSEHOLD", "SOCIAL_SECURITY", "WAGE_CAP", "HOMESTEAD")
ENUM_CLAIM_OUTCOME = ("SUSTAINED", "OVERRULED")
ENUM_RECIPIENT_TYPE = ("DEBTOR", "THIRD_PARTY_BANK", "EMPLOYER")
ENUM_EXAM_OUTCOME = ("HELD", "NO_SHOW", "CONTINUED")
ENUM_OFFERED_BY = ("CREDITOR", "DEBTOR")
ENUM_OFFER_KIND = ("LUMP_SUM", "INSTALLMENT")
ENUM_APPLICATION_ORDER = ("STATUTORY_ORDER", "PRINCIPAL_FIRST")
ENUM_PAYMENT_SOURCE = ("DEBTOR_DIRECT", "GARNISHMENT", "LEVY", "SETTLEMENT")


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def present(body, name):
    return name in body and body[name] is not None


def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_string(body, name, optional=False):
    if not present(body, name):
        if optional:
            return None
        bad_request("Field '%s' is required." % name)
    v = body[name]
    if not isinstance(v, str):
        bad_request("Field '%s' must be a string." % name)
    return v


def require_int(body, name, optional=False, default=None):
    if not present(body, name):
        if optional:
            return default
        bad_request("Field '%s' is required." % name)
    v = body[name]
    if not is_int(v):
        bad_request("Field '%s' must be an integer." % name)
    return v


def require_bool(body, name, optional=False, default=None):
    if not present(body, name):
        if optional:
            return default
        bad_request("Field '%s' is required." % name)
    v = body[name]
    if not isinstance(v, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return v


def require_state_code(body, name, optional=False):
    v = require_string(body, name, optional=optional)
    if v is None:
        return None
    if not _STATE_CODE.match(v):
        bad_request("Field '%s' must be exactly two uppercase letters." % name)
    return v


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10]) if len(text) >= 10 and text[4] == "-" else date.fromisoformat(text)
    except (ValueError, IndexError):
        pass
    dt = parse_instant(value)
    return dt.date() if dt else None


def parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def require_date(body, name, optional=False):
    v = require_string(body, name, optional=optional)
    if v is None:
        return None
    d = parse_date(v)
    if d is None:
        bad_request("Field '%s' must be an ISO 8601 calendar date." % name)
    return d


def require_instant(body, name, optional=False):
    v = require_string(body, name, optional=optional)
    if v is None:
        return None
    dt = parse_instant(v)
    if dt is None:
        bad_request("Field '%s' must be an ISO 8601 UTC instant." % name)
    return dt


def check_enum(body, name, allowed, optional=False):
    """rung 8 - enum-typed inputs.  Presence/type already checked at rung 7."""
    if not present(body, name):
        if optional:
            return None
        raise ApiError("ERR_INVALID_ENUM", "Field '%s' is required." % name)
    v = body[name]
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return v


def positive(value, name):
    """rung 9 - strictly positive monetary / count inputs."""
    if value is not None and value <= 0:
        raise ApiError("ERR_NON_POSITIVE_AMOUNT", "Field '%s' must be strictly greater than zero." % name)
    return value


def non_negative(value, name):
    """rung 9 - monetary inputs that may be zero but never negative."""
    if value is not None and value < 0:
        raise ApiError("ERR_NON_POSITIVE_AMOUNT", "Field '%s' may not be negative." % name)
    return value


def pagination(args):
    """rung 10 - limit in [1,100], offset >= 0, both integral."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset may not be negative.")
    return limit, offset
