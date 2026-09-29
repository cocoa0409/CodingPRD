"""Request-schema validation (validation priority 3) and pagination."""
import json
import re

from flask import request

from db import parse_iso
from errors import ApiError, validation_error

# ---------------------------------------------------------------------------
# enumerations
# ---------------------------------------------------------------------------
MEMBER_CLASSES = ("ACUTE", "NON_ACUTE", "SURGERY_CENTER")
ROOM_TYPES = ("OR_CORE", "ICU", "GENERAL_STORE", "PHARMACY_VAULT")
LICENSE_STATUSES = ("ACTIVE", "LAPSED", "NONE")
UOMS = ("EA", "BX", "CS")
HANDLING_CLASSES = ("AMBIENT", "COLD_CHAIN", "CONTROLLED", "CONTROLLED_COLD")
ITEM_STATUSES = ("ACTIVE", "DISCONTINUED")
TIERS = ("TIER_1", "TIER_2", "TIER_3")
CONTRACT_STATUSES = (
    "DRAFT", "PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "SUPERSEDED", "EXPIRED",
)
CONTRACT_TARGET_STATUSES = ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "EXPIRED")
ACTIVATION_STATES = ("PENDING", "ACTIVE", "BLOCKED")
FORMULARY_STATUSES = ("REQUESTED", "APPROVED", "RESTRICTED", "DELISTED")
FORMULARY_DECISIONS = ("APPROVED", "RESTRICTED", "DELISTED")
LOT_STATUSES = ("AVAILABLE", "EXCURSION_HOLD", "QUARANTINED", "DESTROYED")
EXCURSION_ACTIONS = ("FLAG", "RELEASE", "DESTROY")
FULFILLMENT_STATUSES = (
    "DRAFT", "SUBMITTED", "ALLOCATED", "IN_TRANSIT", "HELD", "DELIVERED", "CANCELLED",
)
SETTLEMENT_STATUSES = ("UNBILLED", "CLAIMED", "REBILL_REQUIRED", "RECONCILED")
LINE_STATUSES = (
    "OPEN", "ALLOCATED", "BACKORDERED", "SUBSTITUTED", "SHORTED", "DELIVERED", "CANCELLED",
)
SUBSTITUTION_STATUSES = ("PENDING", "INFO_REQUESTED", "APPROVED", "REJECTED", "WITHDRAWN")
CLINICIAN_ACTIONS = ("REQUEST_INFO", "APPROVE", "REJECT")
REQUESTER_ACTIONS = ("RESPOND", "WITHDRAW")
RECALL_CLASSES = ("CLASS_I", "CLASS_II", "CLASS_III")
RECALL_STATUSES = ("ISSUED", "CASCADED", "CLOSED")
RECALL_ACTIONS = ("CASCADE", "CLOSE")
VEHICLE_CLASSES = ("AMBIENT_VAN", "REEFER_VAN")
ROUTE_STATUSES = ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED")
CLAIM_STATUSES = ("SUBMITTED", "ACCEPTED", "DISPUTED", "REBILL_REQUIRED", "RECONCILED")
CLAIM_OUTCOMES = ("ACCEPT", "DISPUTE")
CLAIM_SETTLE_ACTIONS = ("RECONCILE", "RESUBMIT")
SUGGESTION_VARIANTS = ("STANDARD_TOPOFF", "LUM_SPLIT")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# body helpers
# ---------------------------------------------------------------------------
def get_body():
    raw = request.get_data()
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise validation_error("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise validation_error("Request body must be a JSON object.")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, allow_empty=False, max_len=None, min_len=None):
    if not _present(body, name):
        raise validation_error("'%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        raise validation_error("'%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        raise validation_error("'%s' must be a non-empty string." % name)
    if min_len is not None and len(value) < min_len:
        raise validation_error("'%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise validation_error("'%s' is longer than %d characters." % (name, max_len))
    return value


def opt_str(body, name, default=None, allow_empty=True):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise validation_error("'%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        raise validation_error("'%s' must be a non-empty string." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise validation_error("'%s' is required." % name)
    return _as_int(body[name], name, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return _as_int(body[name], name, minimum, maximum)


def _as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation_error("'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise validation_error("'%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise validation_error("'%s' must be <= %d." % (name, maximum))
    return value


def req_bool(body, name):
    if not _present(body, name):
        raise validation_error("'%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        raise validation_error("'%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise validation_error("'%s' must be a boolean." % name)
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        raise validation_error(
            "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise validation_error(
            "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_id(body, name):
    return req_str(body, name)


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        raise validation_error("'%s' must be a non-empty string." % name)
    return value


def req_datetime(body, name):
    value = req_str(body, name)
    try:
        parsed = parse_iso(value)
    except Exception:
        raise validation_error("'%s' must be an ISO 8601 datetime." % name)
    return value, parsed


def req_date(body, name):
    value = req_str(body, name)
    if not _DATE_RE.match(value):
        raise validation_error("'%s' must be a YYYY-MM-DD date." % name)
    try:
        import datetime as _dt
        _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except Exception:
        raise validation_error("'%s' must be a YYYY-MM-DD date." % name)
    return value


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except Exception:
            raise validation_error("'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise validation_error("'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except Exception:
            raise validation_error("'offset' must be an integer.")
        if offset < 0:
            raise validation_error("'offset' must be >= 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise validation_error(
            "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_required_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        raise validation_error("'%s' query parameter is required." % name)
    if value not in allowed:
        raise validation_error(
            "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value
