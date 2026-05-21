"""Shared helpers for route handlers: body parsing, version check, etc."""
import re

from flask import request

from ..errors import raise_error


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
_POSTAL_RE = re.compile(r"^\d{5}$")
_TC_CODE_RE = re.compile(r"^[A-Z]{3}$")
_PLANNED_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_json_body():
    """Return JSON body as dict (empty dict if no body)."""
    if request.method == "GET" or request.method == "DELETE":
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error("ERR_REFERENCE_NOT_FOUND", "Request body must be a JSON object")
    return data


def require(body: dict, key: str):
    if key not in body or body[key] is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", f"Missing required field: {key}")
    return body[key]


def check_version(body: dict, entity: dict):
    """Optimistic concurrency: if 'version' is in body, must equal entity.version."""
    if body is None:
        return
    if "version" in body and body["version"] is not None:
        try:
            requested = int(body["version"])
        except Exception:
            raise_error("ERR_VERSION_CONFLICT")
        if requested != entity.get("version"):
            raise_error("ERR_VERSION_CONFLICT")


def parse_pagination():
    try:
        limit_raw = request.args.get("limit", "10")
        offset_raw = request.args.get("offset", "0")
        limit = int(limit_raw)
        offset = int(offset_raw)
    except Exception:
        raise_error("ERR_REFERENCE_NOT_FOUND", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_error("ERR_REFERENCE_NOT_FOUND", "limit out of range [1, 100]")
    if offset < 0:
        raise_error("ERR_REFERENCE_NOT_FOUND", "offset must be >= 0")
    return limit, offset


def is_email(value):
    return isinstance(value, str) and bool(_EMAIL_RE.match(value))


def is_phone(value):
    return isinstance(value, str) and bool(_E164_RE.match(value))


def is_postal(value):
    return isinstance(value, str) and bool(_POSTAL_RE.match(value))


def is_tc_code(value):
    return isinstance(value, str) and bool(_TC_CODE_RE.match(value))


def is_planned_date(value):
    return isinstance(value, str) and bool(_PLANNED_DATE_RE.match(value))
