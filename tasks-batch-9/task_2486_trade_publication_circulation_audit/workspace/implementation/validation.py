"""Request-shape (PRD 2.12 step 5) and enum-membership (step 6) validation.

Every shape failure is reported before any enum failure, which is why parsing
runs in two explicit phases with an optional cross-field hook in between.
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_dt, round_half_up

# ---------------------------------------------------------------- enum sets
FREQUENCIES = ("WEEKLY", "MONTHLY", "QUARTERLY")
RULE_DIMENSIONS = ("JOB_FUNCTION", "INDUSTRY", "PURCHASING_AUTHORITY")
PURCHASING_AUTHORITIES = ("NONE", "RECOMMENDS", "SPECIFIES", "APPROVES")
SUBSCRIPTION_CLASSES = ("PAID", "QUALIFIED_NON_PAID", "CONTROLLED")
QUALIFICATION_STATUSES = (
    "UNQUALIFIED", "PENDING_QUALIFICATION", "QUALIFIED", "LAPSED",
    "REQUALIFICATION_REQUIRED",
)
DELIVERY_STATUSES = ("DELIVERABLE", "UNDELIVERABLE", "REMOVED")
DOC_TYPES = ("SIGNED_REQUEST_CARD", "WEB_FORM_CAPTURE", "TELEPHONE_SCRIPT_LOG", "EMAIL_CONFIRMATION")
PURGE_STATUSES = ("RETAINED", "PURGED")
REQUEST_CHANNELS = ("DIRECT_MAIL", "WEB", "TELEPHONE", "EMAIL")
REQUEST_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "VERIFIED", "REJECTED")
STATEMENT_TYPES = ("PUBLISHER_STATEMENT", "AUDITED")
STATEMENT_BASES = ("AS_OF_PERIOD_END", "AUDIT_VERIFIED")
STATEMENT_STATUSES = (
    "DRAFT", "FILED", "UNDER_AUDIT", "FINDINGS_OPEN", "RESTATEMENT_REQUIRED",
    "AUDIT_CLEARED", "SUPERSEDED",
)
ENGAGEMENT_STATUSES = ("SCHEDULED", "FIELDWORK", "RECONCILIATION", "REPORT_ISSUED")
FINDING_TYPES = (
    "MISSING_SOURCE_DOC", "EXPIRED_QUALIFICATION", "UNDELIVERABLE_NOT_REMOVED",
    "CLASSIFICATION_ERROR", "DIGITAL_METRIC_UNSUPPORTED",
)
SEVERITIES = ("MINOR", "MATERIAL", "CRITICAL")
FINDING_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "ACCEPTED_RESOLVED", "REJECTED_REOPENED")
GUARANTEE_STATUSES = ("ACTIVE", "SUSPENDED_PENDING_RESTATEMENT")
MAKEGOOD_STATUSES = ("PENDING", "OFFERED", "ACCEPTED", "WAIVED", "VOID")
SNAPSHOT_SOURCES = ("INTERNAL_ANALYTICS", "THIRD_PARTY_CERTIFIED")
SNAPSHOT_STATUSES = ("RECORDED", "VALIDATED", "REJECTED")
RUN_TYPES = ("UNDELIVERABLE_SWEEP", "EXPIRY_SWEEP")
VALIDATE_DECISIONS = ("VALIDATE", "REJECT")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")

_MISSING = object()


def body():
    """The JSON request body as a dict (an absent body reads as empty)."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        payload = None
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


# ------------------------------------------------------------- field specs

def f_str(name, required=True, min_len=1, max_len=None, default=_MISSING):
    return {"name": name, "kind": "str", "required": required, "min_len": min_len,
            "max_len": max_len, "default": default}


def f_int(name, required=True, minimum=None, maximum=None, default=_MISSING):
    return {"name": name, "kind": "int", "required": required, "min": minimum,
            "max": maximum, "default": default}


def f_pct(name, required=True, minimum="0.00", maximum="100.00", default=_MISSING):
    return {"name": name, "kind": "pct", "required": required, "min": minimum,
            "max": maximum, "default": default}


def f_bool(name, required=True, default=_MISSING):
    return {"name": name, "kind": "bool", "required": required, "default": default}


def f_dt(name, required=True, default=_MISSING):
    return {"name": name, "kind": "dt", "required": required, "default": default}


def f_enum(name, values, required=True, default=_MISSING):
    return {"name": name, "kind": "enum", "values": values, "required": required,
            "default": default}


def f_id(name, required=True, nullable=False, default=_MISSING):
    return {"name": name, "kind": "id", "required": required, "nullable": nullable,
            "default": default}


def f_strlist(name, required=True, min_items=1, max_items=None, max_len=None):
    return {"name": name, "kind": "strlist", "required": required,
            "min_items": min_items, "max_items": max_items, "max_len": max_len,
            "default": _MISSING}


def _bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (name, detail))


def _check_str(spec, value):
    name = spec["name"]
    if not isinstance(value, str):
        _bad(name, "must be a string.")
    if spec.get("min_len") is not None and len(value) < spec["min_len"]:
        _bad(name, "must be at least %d characters." % spec["min_len"])
    if spec.get("max_len") is not None and len(value) > spec["max_len"]:
        _bad(name, "must be at most %d characters." % spec["max_len"])
    return value


def _check_int(spec, value):
    name = spec["name"]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer.")
    if spec.get("min") is not None and value < spec["min"]:
        _bad(name, "must be at least %s." % spec["min"])
    if spec.get("max") is not None and value > spec["max"]:
        _bad(name, "must be at most %s." % spec["max"])
    return value


def _check_pct(spec, value):
    name = spec["name"]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        _bad(name, "must be a number.")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number.")
        return None
    if not dec.is_finite():
        _bad(name, "must be a finite number.")
    if spec.get("min") is not None and dec < Decimal(spec["min"]):
        _bad(name, "must be at least %s." % spec["min"])
    if spec.get("max") is not None and dec > Decimal(spec["max"]):
        _bad(name, "must be at most %s." % spec["max"])
    return round_half_up(dec, 2)


def _check_bool(spec, value):
    if not isinstance(value, bool):
        _bad(spec["name"], "must be a boolean.")
    return value


def _check_dt(spec, value):
    parsed = parse_dt(value)
    if parsed is None:
        _bad(spec["name"], "must be an ISO-8601 UTC timestamp.")
    return parsed


def _check_id(spec, value):
    if value is None:
        if spec.get("nullable"):
            return None
        _bad(spec["name"], "is required.")
    if not isinstance(value, str) or not value.strip():
        _bad(spec["name"], "must be a non-empty string identifier.")
    return value


def _check_strlist(spec, value):
    name = spec["name"]
    if not isinstance(value, list):
        _bad(name, "must be an array of strings.")
    if spec.get("min_items") is not None and len(value) < spec["min_items"]:
        _bad(name, "must contain at least %d values." % spec["min_items"])
    if spec.get("max_items") is not None and len(value) > spec["max_items"]:
        _bad(name, "must contain at most %d values." % spec["max_items"])
    for item in value:
        if not isinstance(item, str) or not item:
            _bad(name, "must contain only non-empty strings.")
        if spec.get("max_len") is not None and len(item) > spec["max_len"]:
            _bad(name, "values must be at most %d characters." % spec["max_len"])
    return list(value)


_CHECKERS = {
    "str": _check_str,
    "int": _check_int,
    "pct": _check_pct,
    "bool": _check_bool,
    "dt": _check_dt,
    "id": _check_id,
    "strlist": _check_strlist,
}


def parse(payload, specs, cross=None):
    """Two-phase parse: shape first, then enum membership."""
    values = {}
    enums = []
    for spec in specs:
        name = spec["name"]
        raw = payload.get(name, _MISSING)
        if raw is _MISSING or (raw is None and not spec.get("nullable")):
            if spec.get("required"):
                if raw is None and spec.get("nullable"):
                    values[name] = None
                    continue
                raise ApiError("ERR_INVALID_REQUEST", "%s is required." % name)
            default = spec.get("default", _MISSING)
            values[name] = None if default is _MISSING else default
            continue
        if spec["kind"] == "enum":
            if not isinstance(raw, str):
                _bad(name, "must be a string.")
            values[name] = raw
            enums.append(spec)
            continue
        values[name] = _CHECKERS[spec["kind"]](spec, raw)
    if cross is not None:
        cross(values)
    for spec in enums:
        if values[spec["name"]] not in spec["values"]:
            raise ApiError(
                "ERR_INVALID_ENUM_VALUE",
                "%s must be one of %s." % (spec["name"], ", ".join(spec["values"])),
            )
    return values


def filter_enum(name, values):
    """Read an enum-valued query-string filter (PRD 2.3)."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        raise ApiError(
            "ERR_INVALID_ENUM_VALUE",
            "%s filter must be one of %s." % (name, ", ".join(values)),
        )
    return raw


def filter_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
