"""Schema-band helpers (PRD 2.8 band 2) and the enum vocabularies."""

from db import parse_ts
from errors import fail

VALIDATION_TYPES = ("DV", "OV", "EV")
PROFILE_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
POSTURES = ("NOMINAL", "CRL_OVERDUE")
VETTING_LEVELS = ("NONE", "OV", "EV")
REQUIRED_LEVELS = ("OV", "EV")
DCV_METHODS = ("DNS_TXT", "HTTP_TOKEN", "EMAIL_APPROVAL", "TLS_ALPN")
CHECK_DIMENSIONS = ("REGISTRY", "CALLBACK", "AUTHORITY")
CHECK_OUTCOMES = ("PASSED", "FAILED")
LOG_OPERATORS = ("GOOGLE_ARGON", "CLOUDFLARE_NIMBUS", "DIGICERT_YETI", "SECTIGO_SABRE")
CT_OUTCOMES = ("ACCEPTED", "REJECTED")
ROOT_PROGRAMS = ("MOZILLA", "CHROME", "APPLE", "MICROSOFT")
INCIDENT_CATEGORIES = ("KEY_COMPROMISE", "DOMAIN_MISISSUANCE", "ORG_MISISSUANCE", "PROCEDURAL")
REVOCATION_REASONS = (
    "KEY_COMPROMISE",
    "PRIVILEGE_WITHDRAWN",
    "AFFILIATION_CHANGED",
    "SUPERSEDED",
    "CESSATION_OF_OPERATION",
    "UNSPECIFIED",
)
FINDING_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
CSR_KEY_SIZES = (2048, 3072, 4096)


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def req_str(body, name, min_len=None, max_len=None):
    if name not in body:
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def opt_str(body, name, min_len=None, max_len=None, default=None):
    if name not in body or body[name] is None:
        return default
    return req_str(body, name, min_len, max_len)


def req_int(body, name):
    if name not in body:
        _bad(name, "is required")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    return value


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name)


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_ts(body, name):
    raw = req_str(body, name)
    parsed = parse_ts(raw)
    if parsed is None:
        _bad(name, "must be an ISO 8601 timestamp")
    return parsed


def opt_ts(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_ts(body, name)


def req_list(body, name):
    if name not in body:
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    return value


def enum_value(value, allowed, name):
    if value not in allowed:
        fail("ERR_INVALID_ENUM_VALUE", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def in_range(value, low, high, name):
    if value < low or value > high:
        fail(
            "ERR_VALUE_OUT_OF_RANGE",
            "Field '%s' must be between %s and %s." % (name, low, high),
        )
    return value


def one_of_range(value, allowed, name):
    if value not in allowed:
        fail(
            "ERR_VALUE_OUT_OF_RANGE",
            "Field '%s' must be one of %s." % (name, ", ".join(str(a) for a in allowed)),
        )
    return value


def check_domain_name(value, name="domain_name"):
    """Lowercase, 4..253 chars, at least one dot, no leading/trailing dot."""
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if len(value) < 4 or len(value) > 253:
        _bad(name, "must be between 4 and 253 characters")
    if value != value.lower():
        _bad(name, "must be lowercase")
    if "." not in value:
        _bad(name, "must contain at least one dot")
    if value.startswith(".") or value.endswith("."):
        _bad(name, "may not start or end with a dot")
    return value
