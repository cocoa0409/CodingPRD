"""Auth, body validation, pagination, and path-resolution helpers.

Validation order follows PRD §2.8 / scaffold validations priority:
  1 auth (401) -> 2 role (403) -> 3 path existence (404) ->
  4 body FK resolution (422) -> 5 field shape (400) -> 6 state (409) ->
  7 OCC (412) -> 8 temporal (422) -> 9 fiscal-year-closed (409) ->
  10 suspended (409) -> endpoint-specific business rules (11..18).
"""
import re
from flask import request

import errors
from db import store
from util import parse_iso

ROLES = ("AirportFinance", "AirportDirector", "SignatoryAirline", "AirportAuditor")
READ_ROLES = ROLES  # every role may call every read endpoint

IATA_RE = re.compile(r"^[A-Z]{2}$")

METHODOLOGIES = ("RESIDUAL", "COMPENSATORY", "HYBRID")
CARRIER_CLASSES = ("PASSENGER", "CARGO", "CHARTER")
SIGNATURE_STATUSES = ("SIGNATORY", "NON_SIGNATORY")
COST_CENTERS = ("AIRFIELD", "TERMINAL")
BALLOTS = ("APPROVE", "REJECT")
PAYMENT_OUTCOMES = ("PAID", "CREDITED")
PFC_DECISIONS_ACCEPT = ("ACCEPT", "ACCEPTED")
PFC_DECISIONS_REJECT = ("REJECT", "REJECTED")


# ---------------------------------------------------------------------------
# priority 1 + 2: authentication & role authorization
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Validate X-User-ID and X-User-Role; enforce endpoint role permission."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise errors.unauthenticated()
    if not uid:
        raise errors.unauthenticated("X-User-ID header missing")
    if role not in allowed_roles:
        raise errors.forbidden()
    return uid, role


def require_ownership(uid, airline_id):
    """SignatoryAirline ownership: acting user must own the airline resource."""
    if airline_id != uid:
        raise errors.forbidden("Acting airline does not own this resource")


# ---------------------------------------------------------------------------
# request body
# ---------------------------------------------------------------------------
def json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise errors.invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_string(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise errors.invalid_request(f"Field '{field}' must be a string")
    return v


def req_int(body, field, minimum=None, maximum=None, strictly_positive=False):
    v = body.get(field)
    if not _is_int(v):
        raise errors.invalid_request(f"Field '{field}' is required and must be an integer")
    if strictly_positive and v <= 0:
        raise errors.invalid_request(f"Field '{field}' must be > 0")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"Field '{field}' must be <= {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not _is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            f"Field '{field}' must be one of {list(allowed)}")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean")
    return v


def req_iso_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field '{field}' is required and must be an ISO 8601 string")
    dt = parse_iso(v)
    if dt is None:
        raise errors.invalid_request(f"Field '{field}' is not a valid ISO 8601 timestamp")
    return v, dt


# ---------------------------------------------------------------------------
# priority 3: path-parameter existence, left to right
# ---------------------------------------------------------------------------
def get_path(collection, entity_id, what="resource"):
    ent = collection.get(entity_id)
    if ent is None:
        raise errors.not_found(f"{what} '{entity_id}' does not exist")
    return ent


# ---------------------------------------------------------------------------
# priority 4: body FK resolution (a present, string FK must resolve)
# ---------------------------------------------------------------------------
def resolve_fk(body, field, collection, required=True):
    """Returns the resolved entity. Missing -> None (shape check fires later if
    required); present-but-wrong-type -> shape error at priority 5; present,
    string, unresolvable -> ERR_FK_NOT_FOUND (422)."""
    v = body.get(field)
    if v is None:
        if required:
            # missing required FK -> handled as shape error at priority 5;
            # nothing to resolve here
            return None
        return None
    if not isinstance(v, str):
        return None  # let priority-5 shape validation report the type error
    ent = collection.get(v)
    if ent is None:
        raise errors.fk_not_found(f"Referenced {field} '{v}' does not exist")
    return ent


# ---------------------------------------------------------------------------
# pagination (limit/offset; defaults 10/0; limit min 1 max 100)
# ---------------------------------------------------------------------------
def pagination_params():
    def parse_int(name, raw):
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request(f"Query parameter '{name}' must be an integer")

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10 if limit_raw is None else parse_int("limit", limit_raw)
    offset = 0 if offset_raw is None else parse_int("offset", offset_raw)
    if limit < 1 or limit > 100:
        raise errors.invalid_request("Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, serializer):
    """Sort by (created_at, insertion seq) ascending and paginate."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [serializer(e) for e in page], meta
