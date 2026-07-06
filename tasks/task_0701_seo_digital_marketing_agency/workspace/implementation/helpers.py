"""Shared request-handling helpers: body parsing, field validation, ownership,
existence lookups, and pagination."""
from flask import request

from db import store
from errors import err

# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------


def get_body():
    """Return the parsed JSON body as a dict (empty dict if none / not object)."""
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validators (ERR_INVALID_REQUEST, priority 5)
# ---------------------------------------------------------------------------


def require_str(body, field, allow_empty=False):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    if not allow_empty and not v.strip():
        raise err("ERR_INVALID_REQUEST", f"Field {field} must not be empty")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def require_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum {maximum}")
    return v


def require_number(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum {maximum}")
    return v


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum {maximum}")
    return v


def require_enum(body, field, choices):
    v = require_str(body, field)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(choices)}")
    return v


def opt_enum(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(choices)}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


# ---------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, priority 4)
# ---------------------------------------------------------------------------

_COLLECTIONS = {
    "reseller": lambda: store.resellers,
    "client": lambda: store.clients,
    "site_audit": lambda: store.site_audits,
    "keyword_target": lambda: store.keyword_targets,
    "rank_snapshot": lambda: store.rank_snapshots,
    "retainer": lambda: store.retainers,
    "contract": lambda: store.contracts,
    "sprint": lambda: store.sprints,
    "deliverable": lambda: store.deliverables,
    "ad_campaign": lambda: store.ad_campaigns,
    "ad_spend_dispute": lambda: store.ad_spend_disputes,
    "gbp_listing": lambda: store.gbp_listings,
    "report": lambda: store.reports,
}


def find(kind, rec_id):
    """Return the record or raise ERR_NOT_FOUND."""
    if rec_id is None:
        raise err("ERR_NOT_FOUND", f"{kind} not found")
    coll = _COLLECTIONS[kind]()
    rec = coll.get(rec_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", f"{kind} '{rec_id}' not found")
    return rec


# ---------------------------------------------------------------------------
# Ownership (ERR_NOT_RESOURCE_OWNER, priority 3)
# ---------------------------------------------------------------------------


def client_owner_id(client):
    return client["id"]


def assert_owns_client(principal, client):
    """Entity-backed ownership check for a client resource.

    Client role: X-User-ID must equal client.id.
    Reseller role: X-User-ID must equal client.reseller_id.
    Opaque roles: always permitted.
    """
    if principal.role == "Client":
        if client["id"] != principal.user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this resource")
    elif principal.role == "Reseller":
        if client.get("reseller_id") != principal.user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Reseller does not own this client")


def assert_owns_reseller(principal, reseller):
    if principal.role == "Reseller":
        if reseller["id"] != principal.user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Reseller does not own this resource")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (stable via _seq) and apply limit/offset."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
