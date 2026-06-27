"""Validation helpers: existence lookups, body parsing, pagination, numeric checks."""
from flask import request
from db import db
from errors import err
from util import parse_dt, clock

# entity-collection -> not-found error id
NOT_FOUND = {
    "project": "ERR_PROJECT_NOT_FOUND",
    "assessment": "ERR_ASSESSMENT_NOT_FOUND",
    "sample": "ERR_SAMPLE_NOT_FOUND",
    "zone": "ERR_ZONE_NOT_FOUND",
    "order": "ERR_ABATEMENT_ORDER_NOT_FOUND",
    "manifest": "ERR_MANIFEST_NOT_FOUND",
    "clearance": "ERR_CLEARANCE_NOT_FOUND",
    "permit": "ERR_PERMIT_NOT_FOUND",
    "claim": "ERR_CLAIM_NOT_FOUND",
    "worker": "ERR_WORKER_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
}

COLLECTIONS = {
    "project": lambda: db.projects,
    "assessment": lambda: db.assessments,
    "sample": lambda: db.samples,
    "zone": lambda: db.zones,
    "order": lambda: db.orders,
    "manifest": lambda: db.manifests,
    "clearance": lambda: db.clearances,
    "permit": lambda: db.permits,
    "claim": lambda: db.claims,
    "worker": lambda: db.workers,
    "assignment": lambda: db.assignments,
}


def get_or_404(kind, rid):
    coll = COLLECTIONS[kind]()
    rec = coll.get(rid)
    if rec is None:
        raise err(NOT_FOUND[kind])
    return rec


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def positive_number(body, field, integer=False):
    val = body.get(field)
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if integer and not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if val <= 0:
        raise err("ERR_INVALID_REQUEST", "%s must be positive" % field)
    return val


def nonneg_int(body, field):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if val < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be non-negative" % field)
    return val


def valid_enum(body, field, choices):
    val = body.get(field)
    if val not in choices:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(choices)))
    return val


def parse_required_dt(body, field):
    raw = body.get(field)
    dt = parse_dt(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "%s must be a valid ISO 8601 timestamp" % field)
    return dt


def not_future(dt, field=""):
    if dt > clock.get():
        raise err("ERR_TIMESTAMP_IN_FUTURE", "%s is after the logical clock now" % field)


def pagination():
    """Read limit/offset query params (PRD §2.3). Default limit=10 (min1,max100),
    offset default 0. Out-of-range -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    """items already filtered & sorted; return the page slice + total."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
