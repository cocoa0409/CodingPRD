"""Common input validation helpers."""
import re

from errors import err
from clock import now


CLASSIFICATION_SCHEMES = {"DEWEY", "CLC"}
SUBJECT_CATEGORIES = {"GENERAL", "REFERENCE", "CHILDREN", "RARE"}
ACQUISITION_SOURCES = {"PURCHASE", "DONATION", "EXCHANGE", "ILL_PURCHASE"}
CARD_TYPES = {"REGULAR", "STUDENT", "SENIOR", "TEMPORARY"}
LOAN_CHANNELS = {"COUNTER", "KIOSK"}
RESERVATION_CHANNELS = {"ONLINE", "ON_SITE"}
WAIVE_REASONS = {"SYSTEM_FAULT", "HOLIDAY", "HARDSHIP"}
WEED_REASONS = {"DAMAGED", "LOST", "OBSOLETE", "LOW_CIRCULATION"}
ILL_PARTNER_CODES = {"PL_A", "PL_B", "PL_C"}
ILL_EVENT_TYPES = {"PAYMENT_CONFIRMED", "IDENTITY_VERIFIED",
                   "ILL_AVAILABILITY", "ILL_DELIVERED", "ILL_RETURN_INITIATED"}
DECISION_VALUES = {"ACQUIRE", "DECLINE", "DEFER"}


_ISBN_RE = re.compile(r"^\d{13}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def require_dict(body):
    if not isinstance(body, dict):
        raise err("ERR_INVALID_INPUT", "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_INPUT", f"Missing required field: {name}")
    return body[name]


def require_str(body, name, allow_empty=False):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_INPUT", f"Field {name} must be a string")
    if not allow_empty and not v.strip():
        raise err("ERR_INVALID_INPUT", f"Field {name} must be non-empty")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_INPUT", f"Field {name} must be an integer")
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        raise err("ERR_INVALID_INPUT",
                  f"Field {name} must be one of {sorted(allowed)}, got {v!r}")
    return v


def require_isbn13(value, field_name="isbn"):
    if not isinstance(value, str) or not _ISBN_RE.match(value):
        raise err("ERR_INVALID_INPUT", f"{field_name} must be exactly 13 digits")
    return value


def require_marc(value, field_name="marc_control_number"):
    if not isinstance(value, str):
        raise err("ERR_INVALID_INPUT", f"{field_name} must be a string")
    if len(value) < 8 or len(value) > 20:
        raise err("ERR_INVALID_INPUT",
                  f"{field_name} length must be between 8 and 20")
    return value


def require_publication_year(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_INPUT", "publication_year must be an integer")
    current_year = now().year
    if value < 1450 or value > current_year:
        raise err("ERR_INVALID_INPUT",
                  f"publication_year must be between 1450 and {current_year}")
    return value


def require_sha256(value, field_name="national_id_hash"):
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise err("ERR_INVALID_INPUT",
                  f"{field_name} must be a 64-character SHA-256 hex string")
    return value


def require_non_negative_int(body, name):
    v = require_int(body, name)
    if v < 0:
        raise err("ERR_INVALID_INPUT", f"{name} must be >= 0")
    return v


def require_positive_int(body, name):
    v = require_int(body, name)
    if v <= 0:
        raise err("ERR_INVALID_INPUT", f"{name} must be > 0")
    return v
