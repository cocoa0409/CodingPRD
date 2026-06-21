"""Common helpers: UUID, version stamp helpers, pagination parsing, OCC check."""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db
from errors import raise_api


def new_id() -> str:
    return str(uuid.uuid4())


def stamp_common_create(entity: dict) -> dict:
    """Populate id/created_at/updated_at/version for a fresh business entity.

    Caller is responsible for assigning entity['id'] beforehand if it wants
    a pre-allocated id; otherwise this helper assigns one.
    """
    if "id" not in entity or not entity["id"]:
        entity["id"] = new_id()
    now = db.current_utc_iso()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> dict:
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = db.current_utc_iso()
    entity["version"] = int(entity.get("version", 1)) + 1
    return entity


# ---------- Pagination ----------

def parse_pagination(default_limit: int = 10, min_limit: int = 1, max_limit: int = 100):
    """Read limit/offset from query string; raise ERR_INVALID_REQUEST on bad values."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    if raw_limit is None:
        limit = default_limit
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < min_limit or limit > max_limit:
            raise_api("ERR_INVALID_REQUEST", f"limit must be in [{min_limit}, {max_limit}]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_api("ERR_INVALID_REQUEST", "offset must be non-negative")
    return limit, offset


def page(items, limit: int, offset: int):
    """Slice an already-sorted list and return (page_items, total_count)."""
    total_count = len(items)
    return items[offset: offset + limit], total_count


def sort_by_created_at(items):
    """Stable sort ascending by created_at then id."""
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))


# ---------- Body / JSON helpers ----------

def get_json_body() -> dict:
    """Return a JSON body dict. Empty body -> {}. Bad JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_api("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_api("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body: dict, *fields):
    missing = [f for f in fields if f not in body]
    if missing:
        raise_api("ERR_INVALID_REQUEST", f"Missing required field(s): {', '.join(missing)}")


# ---------- OCC ----------

def check_occ(body: dict, field: str, current_version: int, required: bool = True):
    """Compare expected version. Mismatch -> ERR_STALE_VERSION (412).

    If the field is missing and `required` is True -> ERR_INVALID_REQUEST.
    If not required and missing -> skip the check (no-op).
    """
    if field not in body or body[field] is None:
        if required:
            raise_api("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return
    raw = body[field]
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise_api("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if raw != int(current_version):
        raise_api("ERR_STALE_VERSION", f"{field} does not match current version")


# ---------- Rounding ----------

def round_half_up_2(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------- Lookups (raise ERR_NOT_FOUND on miss) ----------

def get_jurisdiction(jid: str) -> dict:
    j = db.jurisdictions.get(jid)
    if not j:
        raise_api("ERR_NOT_FOUND", f"Jurisdiction not found: {jid}")
    return j


def get_applicant(aid: str) -> dict:
    a = db.applicants.get(aid)
    if not a:
        raise_api("ERR_NOT_FOUND", f"Applicant not found: {aid}")
    return a


def get_application(aid: str) -> dict:
    a = db.applications.get(aid)
    if not a:
        raise_api("ERR_NOT_FOUND", f"Application not found: {aid}")
    return a


def get_consent(cid: str) -> dict:
    c = db.consents.get(cid)
    if not c:
        raise_api("ERR_NOT_FOUND", f"Consent not found: {cid}")
    return c


def get_order(oid: str) -> dict:
    o = db.orders.get(oid)
    if not o:
        raise_api("ERR_NOT_FOUND", f"BackgroundCheckOrder not found: {oid}")
    return o


def get_verification(vid: str) -> dict:
    v = db.verifications.get(vid)
    if not v:
        raise_api("ERR_NOT_FOUND", f"Verification not found: {vid}")
    return v


def get_adverse_action(aid: str) -> dict:
    a = db.adverse_actions.get(aid)
    if not a:
        raise_api("ERR_NOT_FOUND", f"AdverseAction not found: {aid}")
    return a
