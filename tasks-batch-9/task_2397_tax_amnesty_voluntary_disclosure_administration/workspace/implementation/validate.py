"""Request body validation helpers (PRD 2.4 and precedence rule 8).

Every failure here raises ERR_INVALID_REQUEST (400).  Nothing in this module
looks at business state; it only enforces presence, type, enum membership,
date/timestamp form, integer-cents positivity and percentage bounds.
"""

from flask import request

import clock
from errors import err

TAX_TYPES = ("SALES_USE", "CORPORATE_INCOME", "PERSONAL_INCOME", "WITHHOLDING", "EXCISE_FUEL")
TAXPAYER_TYPES = ("INDIVIDUAL", "BUSINESS")
CASE_TYPES = ("FIELD_AUDIT", "DESK_AUDIT", "CRIMINAL_INVESTIGATION", "COLLECTION")
PLAN_TYPES = ("LUMP_SUM", "INSTALLMENT")
ACTION_TYPES = ("NOTICE", "ASSESSMENT", "LIEN_REFERRAL")


def bad():
    return err("ERR_INVALID_REQUEST")


def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def present(body, name):
    return name in body and body[name] is not None


def _missing(body, name, required, default):
    """Shared prologue: returns (True, value) when the caller should stop."""
    if not present(body, name):
        if required:
            raise bad()
        return True, default
    return False, None


def vstr(body, name, required=True, default=None, allow_blank=False):
    stop, value = _missing(body, name, required, default)
    if stop:
        return value
    raw = body[name]
    if not isinstance(raw, str):
        raise bad()
    if not allow_blank and not raw.strip():
        raise bad()
    return raw


def vint(body, name, required=True, default=None, minimum=None, maximum=None):
    stop, value = _missing(body, name, required, default)
    if stop:
        return value
    raw = body[name]
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise bad()
    if minimum is not None and raw < minimum:
        raise bad()
    if maximum is not None and raw > maximum:
        raise bad()
    return raw


def vnumber(body, name, required=True, default=None, minimum=None, maximum=None):
    stop, value = _missing(body, name, required, default)
    if stop:
        return value
    raw = body[name]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise bad()
    if minimum is not None and raw < minimum:
        raise bad()
    if maximum is not None and raw > maximum:
        raise bad()
    return raw


def vpct(body, name, required=True, default=None):
    """A fraction in the inclusive range 0.00 .. 1.00 (PRD 2.7)."""
    return vnumber(body, name, required=required, default=default, minimum=0, maximum=1)


def vbool(body, name, required=True, default=None):
    stop, value = _missing(body, name, required, default)
    if stop:
        return value
    raw = body[name]
    if not isinstance(raw, bool):
        raise bad()
    return raw


def venum(body, name, allowed, required=True, default=None):
    stop, value = _missing(body, name, required, default)
    if stop:
        return value
    raw = body[name]
    if not isinstance(raw, str) or raw not in allowed:
        raise bad()
    return raw


def vdate(body, name, required=True, default=None):
    """Strict YYYY-MM-DD.  Returns a datetime.date."""
    stop, value = _missing(body, name, required, default)
    if stop:
        return value
    parsed = clock.parse_date(body[name])
    if parsed is None:
        raise bad()
    return parsed


def vtimestamp(body, name, required=True, default=None):
    """ISO 8601 instant.  Returns (raw_string, aware_datetime)."""
    stop, value = _missing(body, name, required, default)
    if stop:
        return value, None
    raw = body[name]
    parsed = clock.parse_timestamp(raw)
    if parsed is None:
        raise bad()
    return raw, parsed


def vtax_types(body, name):
    """A non-empty array drawn from the tax type enumeration."""
    if not present(body, name):
        raise bad()
    raw = body[name]
    if not isinstance(raw, list) or not raw:
        raise bad()
    for member in raw:
        if not isinstance(member, str) or member not in TAX_TYPES:
            raise bad()
    return list(raw)


def vtin_last4(body, name):
    raw = vstr(body, name)
    if len(raw) != 4 or not raw.isdigit():
        raise bad()
    return raw


def vid(body, name, required=True):
    """A foreign key string.  Body FK resolution (rule 6) runs before this."""
    return vstr(body, name, required=required)


def query_bool(name):
    """Optional boolean list filter from the query string."""
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw.strip().lower() == "true"
