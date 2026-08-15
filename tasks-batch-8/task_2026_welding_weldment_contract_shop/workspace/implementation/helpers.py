"""Shared helpers: timestamps, pagination, request-body parsing, serialization."""

import re
import uuid
from datetime import datetime, timezone

from flask import request
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import invalid_request


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def wall_timestamp():
    """Wall-clock UTC timestamp with three fractional digits (PRD §2.4)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def parse_datetime(value, field):
    """Parse an ISO-8601 datetime input; normalize to UTC, second granularity."""
    if not isinstance(value, str):
        raise invalid_request(f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    dt = None
    try:
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        dt = None
    if dt is None:
        raise invalid_request(f"{field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Datetime comparisons are made at second granularity (PRD §2.5).
    return dt.replace(microsecond=0)


def format_logical(dt):
    """Serialize a logical-clock datetime (second precision, Z suffix)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def parse_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request(f"{field} must be a number")
    return value


def parse_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request(f"{field} must be an integer")
    return value


def kg(value):
    """Decimal for kilogram quantities (2 decimal places)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise invalid_request("invalid kilogram quantity")


def kg_out(dec_value):
    """Serialize a kg Decimal at 2dp, half-up."""
    q = dec_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def pct_out(dec_value):
    q = dec_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Request body / pagination
# ---------------------------------------------------------------------------

def json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request(f"Missing required field: {f}")


def pagination_params():
    """limit: default 10, min 1, max 100. offset: default 0, min 0. Values clamped."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records):
    """Sort by (created_at wall time, insertion seq) ascending and paginate."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["_created_wall"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def clean(rec):
    """Strip internal bookkeeping fields before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

PROCESSES = {"SMAW", "GMAW", "FCAW", "GTAW", "SAW"}
NDT_METHODS = {"VT", "UT", "RT"}
OWNER_PARTIES = {"SHOP", "CUSTOMER"}
DISPOSITIONS = {"REWORK", "USE_AS_IS", "SCRAP"}
STEP_CODES = {"FIT_UP", "WELD_OUT", "VT", "NDT", "FINAL"}
INSPECTION_RESULTS = {"PASS", "FAIL"}

ALL_ROLES = {
    "ShopAdmin", "QCManager", "WeldLead", "Welder", "CWI",
    "MaterialController", "ProductionPlanner", "QualityInspector",
    "ShippingClerk", "Any",
}
