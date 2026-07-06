"""Shared helpers: body parsing, pagination, common-field mutation, ownership."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request, g

from errors import (err, ERR_INVALID_REQUEST, ERR_VALIDATION_LIMIT,
                    ERR_NOT_FOUND, ERR_FORBIDDEN_ROLE)
from store import new_id, now_iso, next_seq


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict (empty dict if none / not an object)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Missing or invalid field: %s" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid integer field: %s" % field)
    return v


def opt_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Invalid integer field: %s" % field)
    return v


def require_field_present(body, field):
    if field not in body or body.get(field) is None:
        raise err(ERR_INVALID_REQUEST, "Missing field: %s" % field)
    return body[field]


# ---------------------------------------------------------------------------
# Rounding (half up, away from zero)
# ---------------------------------------------------------------------------
def round_half_up(value, places=0):
    """Round a numeric value half-up to the given decimal places.

    Returns an int when places == 0, else a float (used for percentages).
    """
    q = Decimal(1).scaleb(-places)  # 10^-places
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def base_record(extra):
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a mutation: bump updated_at and version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal fields (those starting with _) for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


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
            raise err(ERR_VALIDATION_LIMIT, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION_LIMIT, "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION_LIMIT, "offset must not be negative.")
    return limit, offset


def paginate(rows):
    """Sort by created_at asc (tie-break on _seq) and apply limit/offset."""
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Lookup / ownership
# ---------------------------------------------------------------------------
def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return rec


def client_contact_guard(client_id):
    """For a ClientContact, the acting client must own the resource (PRD §2.1)."""
    if g.role == "ClientContact" and g.user_id != client_id:
        raise err(ERR_FORBIDDEN_ROLE, "ClientContact may only act on its own client.")
