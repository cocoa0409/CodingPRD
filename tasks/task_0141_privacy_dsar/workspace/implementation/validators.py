"""Request-body integrity, existence lookups, and pagination parsing.

Body integrity (PRD §2.9): required fields present and well-typed, enum members
valid, record_count >= 1 -> ERR_INVALID_REQUEST (400). Existence (PRD §2.5):
referenced resources resolved left-to-right -> ERR_NOT_FOUND (404). Pagination
(PRD §2.3): limit default 10, min 1, max 100; offset default 0.
"""

from flask import request

from db import store
from errors import err

# Enum domains (SCAFFOLD §1.1)
JURISDICTIONS = {"GDPR", "CCPA"}
RESIDENCIES = {"EU", "CALIFORNIA", "OTHER"}
PURPOSES = {"MARKETING", "ANALYTICS", "SALE_OF_DATA", "ESSENTIAL"}
DATA_CATEGORIES = {"IDENTITY", "FINANCIAL", "BEHAVIORAL", "CONTACT", "HEALTH"}
REQUEST_TYPES = {"ACCESS", "DELETION", "OPT_OUT"}
CONFIDENCES = {"EXACT", "PROBABLE"}
EXEMPTION_BASES = {"LEGAL_OBLIGATION", "FREEDOM_OF_EXPRESSION", "LEGAL_HOLD", "TRADE_SECRET"}
EXEMPTION_DECISIONS = {"UPHELD", "OVERRULED"}
EVENT_TYPES = {
    "IDENTITY_VERIFIED", "IDENTITY_REJECTED", "DISCOVERY_RECORDED",
    "EXEMPTION_DECIDED", "FULFILLMENT_DISPATCHED", "REQUEST_CLOSED",
    "DEADLINE_EXTENDED",
}


def get_body():
    """Return the JSON body as a dict; an empty/absent body becomes {}.
    A malformed JSON body (or a non-object JSON value) is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string" % field)
    return val


def require_enum(body, field, domain):
    val = require_str(body, field)
    if val not in domain:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s" % (field, sorted(domain)))
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    # bool is an int subclass; reject it explicitly.
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %d" % (field, minimum))
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, minimum=minimum)


def require_iso(body, field):
    from timeutil import parse_iso
    raw = body.get(field)
    if not isinstance(raw, str) or raw == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be an ISO 8601 string" % field)
    dt = parse_iso(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a valid ISO 8601 instant" % field)
    return dt


def require_category_array(body, field):
    val = body.get(field)
    if not isinstance(val, list) or len(val) == 0:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array" % field)
    for member in val:
        if member not in DATA_CATEGORIES:
            raise err("ERR_INVALID_REQUEST", "Field '%s' members must be valid data categories" % field)
    return list(val)


# --- Existence lookups (raise ERR_NOT_FOUND) -------------------------------
def get_controller(cid):
    c = store.controllers.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Controller not found")
    return c


def get_data_subject(sid):
    s = store.data_subjects.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "DataSubject not found")
    return s


def get_processor(pid):
    p = store.processors.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "Processor not found")
    return p


def get_consent_record(cid):
    c = store.consent_records.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "ConsentRecord not found")
    return c


def get_legal_hold(hid):
    h = store.legal_holds.get(hid)
    if h is None:
        raise err("ERR_NOT_FOUND", "LegalHold not found")
    return h


def get_dsar_request(rid):
    r = store.dsar_requests.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "DsarRequest not found")
    return r


def get_finding(fid):
    f = store.discovery_findings.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", "DiscoveryFinding not found")
    return f


def get_exemption(eid):
    e = store.exemption_claims.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "ExemptionClaim not found")
    return e


def get_fulfillment_item(iid):
    i = store.fulfillment_items.get(iid)
    if i is None:
        raise err("ERR_NOT_FOUND", "FulfillmentItem not found")
    return i


def get_notification(nid):
    n = store.processor_notifications.get(nid)
    if n is None:
        raise err("ERR_NOT_FOUND", "ProcessorNotification not found")
    return n


def request_arg(name):
    """Return a query-string filter value, treating an empty string as absent."""
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v


# --- Pagination (PRD §2.3) -------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at asc (tie-break by insertion seq), then window."""
    ordered = sorted(rows, key=lambda x: (x["created_at"], x.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
