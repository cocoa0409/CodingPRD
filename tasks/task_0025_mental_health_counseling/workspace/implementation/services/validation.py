"""Validation helpers, common predicates, and request body utilities."""
import re

from flask import request

from errors import err


SPECIALTY_TAGS = {"ANXIETY", "DEPRESSION", "TRAUMA", "FAMILY", "ADDICTION",
                  "ADOLESCENT", "EATING_DISORDER", "GRIEF"}
CHANNELS = {"TEXT", "AUDIO", "VIDEO"}
APPOINTMENT_TYPES = {"INTAKE", "STANDARD", "FOLLOW_UP"}
PAYMENT_MODES = {"PAY_PER_SESSION", "PACKAGE"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
DETECTION_SOURCES = {"KEYWORD_DETECTOR", "COUNSELOR_TRIGGERED"}

E164_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")


def get_body() -> dict:
    """Parse JSON body; empty body -> {}; bad JSON -> ERR_VALIDATION."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise err("ERR_VALIDATION", "Body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Body must be a JSON object")
    return body


def require_field(d: dict, name: str):
    if name not in d or d[name] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {name}")
    return d[name]


def require_str(d: dict, name: str) -> str:
    v = require_field(d, name)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"{name} must be a string")
    return v


def require_int(d: dict, name: str) -> int:
    v = require_field(d, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"{name} must be an integer")
    return v


def require_number(d: dict, name: str):
    v = require_field(d, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"{name} must be a number")
    return v


def optional_str(d: dict, name: str):
    v = d.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"{name} must be a string")
    return v


def validate_email(email: str):
    if not isinstance(email, str) or len(email) < 3 or "@" not in email:
        raise err("ERR_VALIDATION", "email must be a valid email address")
    if email != email.lower():
        raise err("ERR_VALIDATION", "email must be lowercase")


def validate_e164(phone: str):
    if not isinstance(phone, str) or not E164_RE.match(phone):
        raise err("ERR_VALIDATION",
                  "emergency_contact_phone must match E.164 format")


def validate_specialty_tags(tags):
    if not isinstance(tags, list) or len(tags) == 0:
        raise err("ERR_VALIDATION", "specialty_tags must be a non-empty array")
    for t in tags:
        if t not in SPECIALTY_TAGS:
            raise err("ERR_VALIDATION", f"invalid specialty tag: {t}")


def validate_supported_channels(channels):
    if not isinstance(channels, list) or len(channels) == 0:
        raise err("ERR_VALIDATION", "supported_channels must be a non-empty array")
    for c in channels:
        if c not in CHANNELS:
            raise err("ERR_VALIDATION", f"invalid channel: {c}")


def check_version(stored: dict, body: dict):
    """OCC: when body carries 'version', it must match stored. When omitted, skip."""
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_VALIDATION", "version must be an integer")
        if v != stored.get("version"):
            raise err("ERR_VERSION_CONFLICT",
                      f"version mismatch (expected {stored.get('version')}, got {v})")
