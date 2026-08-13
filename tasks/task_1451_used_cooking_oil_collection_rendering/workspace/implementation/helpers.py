"""Auth middleware, body validation, pagination, entity lookup, lazy transitions."""

from datetime import timedelta
from functools import wraps

from flask import g, request

from db import parse_date, parse_dt, store
from errors import err

ROLES = {
    "SystemAdmin",
    "FieldOpsManager",
    "RouteDispatcher",
    "Driver",
    "BillingAnalyst",
    "PlantOperator",
    "CustomerContact",
}

CONTRACT_TERMINAL = {"TERMINATED_VOLUNTARY", "TERMINATED_POACHED", "EXPIRED"}
CONTRACT_ACTIVE_ERA = {"ACTIVE", "AT_RISK", "RENEWAL_OFFERED"}


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, validation priorities 1-2)
# ---------------------------------------------------------------------------
def require_roles(*roles):
    """Category 1 (authentication) + endpoint-level category 2 (role list)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise err(
                    "ERR_UNAUTHENTICATED",
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in roles:
                raise err(
                    "ERR_FORBIDDEN_ROLE",
                    "Role %s is not authorized for this endpoint" % role,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def forbid_role(message="Ownership rule violated"):
    return err("ERR_FORBIDDEN_ROLE", message)


def cc_check(customer_id):
    """CustomerContact may act only on resources of the customer == X-User-ID."""
    if g.role == "CustomerContact" and customer_id != g.user_id:
        raise forbid_role("CustomerContact may only act on its own customer")


# ---------------------------------------------------------------------------
# Body validation (validation priority 4)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field '%s' must be a string" % field)
    return v


def req_int(body, field, min_v=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, min_v))
    return v


def opt_int(body, field, default=None, min_v=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, min_v=min_v)


def req_num(body, field, min_v=None, strict_gt=None, max_v=None):
    v = body.get(field)
    if not _is_num(v):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a number" % field)
    if min_v is not None and v < min_v:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, min_v))
    if strict_gt is not None and not v > strict_gt:
        raise err("ERR_VALIDATION", "Field '%s' must be > %s" % (field, strict_gt))
    if max_v is not None and v > max_v:
        raise err("ERR_VALIDATION", "Field '%s' must be <= %s" % (field, max_v))
    return v


def opt_num(body, field, default=None, min_v=None, strict_gt=None, max_v=None):
    if field not in body or body[field] is None:
        return default
    return req_num(body, field, min_v=min_v, strict_gt=strict_gt, max_v=max_v)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(
            "ERR_VALIDATION",
            "Field '%s' must be one of %s" % (field, sorted(allowed)),
        )
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    """Required ISO calendar date; returns the normalized YYYY-MM-DD string."""
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be an ISO date" % field)
    try:
        return parse_date(v).isoformat()
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field '%s' is not a valid ISO date" % field)


def req_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be an ISO-8601 timestamp" % field)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field '%s' is not a valid ISO-8601 timestamp" % field)


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a list of strings" % field)
    return v


def fk_exists(table, value, field):
    """Body foreign-key existence: a body id that names nothing is a schema error."""
    if value not in table:
        raise err("ERR_VALIDATION", "Field '%s' does not reference an existing resource" % field)
    return table[value]


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    if not (isinstance(raw_limit, str) and raw_limit.strip().lstrip("+-").isdigit()):
        raise err("ERR_VALIDATION", "Query parameter 'limit' must be an integer")
    if not (isinstance(raw_offset, str) and raw_offset.strip().lstrip("+-").isdigit()):
        raise err("ERR_VALIDATION", "Query parameter 'offset' must be an integer")
    limit = int(raw_limit)
    offset = int(raw_offset)
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION", "Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION", "Query parameter 'offset' must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def sorted_items(records):
    """created_at ascending, ties broken by creation sequence (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Lazy state transitions (PRD 2.4)
# ---------------------------------------------------------------------------
def fresh_contract(rec):
    """Lazy expiry: ACTIVE/AT_RISK/RENEWAL_OFFERED -> EXPIRED once the logical
    clock date is strictly past term_end. Evaluated on any access (PRD 3.2)."""
    if rec["status"] in CONTRACT_ACTIVE_ERA:
        if store.clock_date() > parse_date(rec["term_end"]):
            rec["status"] = "EXPIRED"
            store.bump(rec)
    return rec


def fresh_complaint(rec):
    """Lazy auto-close: RESOLVED -> CLOSED once the logical clock is strictly
    more than 7 days past resolved_at. Evaluated on any access (PRD 3.8)."""
    if rec["status"] == "RESOLVED" and rec.get("resolved_at"):
        if store.clock > parse_dt(rec["resolved_at"]) + timedelta(days=7):
            rec["status"] = "CLOSED"
            store.bump(rec)
    return rec


# ---------------------------------------------------------------------------
# Entity getters (validation priority 3, path resources left to right)
# ---------------------------------------------------------------------------
def _get(table, rid, label):
    rec = table.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s %s not found" % (label, rid))
    return rec


def get_customer(rid):
    return _get(store.customers, rid, "Customer")


def get_contract(rid):
    return fresh_contract(_get(store.contracts, rid, "Contract"))


def get_container(rid):
    return _get(store.containers, rid, "Container")


def get_truck(rid):
    return _get(store.trucks, rid, "Truck")


def get_manifest(rid):
    return _get(store.manifests, rid, "RouteManifest")


def get_visit(rid):
    return _get(store.visits, rid, "PickupVisit")


def get_sample(rid):
    return _get(store.samples, rid, "QualitySample")


def get_quote(rid):
    return _get(store.quotes, rid, "MarketIndexQuote")


def get_settlement(rid):
    return _get(store.settlements, rid, "Settlement")


def get_complaint(rid):
    return fresh_complaint(_get(store.complaints, rid, "Complaint"))


def get_theft(rid):
    return _get(store.thefts, rid, "TheftIncident")


def get_batch(rid):
    return _get(store.batches, rid, "ProcessingBatch")
