"""Authentication / authorisation (PRD §2.1) and request-shape validation (§2.10 step 3)."""
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import (ROLES, store, PAGINATION_DEFAULT_LIMIT, PAGINATION_MAX_LIMIT,
                   PAGINATION_MIN_LIMIT, PAGINATION_DEFAULT_OFFSET)

_SENTINEL = object()


# ------------------------------------------------------------------ auth (1, 2)
class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authorize(*allowed_roles):
    """Step 1: both headers present and role recognised.  Step 2: role allowed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and a recognised X-User-Role are required")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return Actor(user_id, role)


# ------------------------------------------------------------------ body access
def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def present(b, name):
    return name in b and b[name] is not None


# ------------------------------------------------------------- field extractors
def f_str(b, name, required=False, default=None, max_len=None, allow_empty=False):
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return default
    v = b[name]
    if not isinstance(v, str):
        bad("%s must be a string" % name)
    if not allow_empty and v.strip() == "":
        bad("%s must be a non-empty string" % name)
    if max_len is not None and len(v) > max_len:
        bad("%s exceeds %d characters" % (name, max_len))
    return v


def f_enum(b, name, allowed, required=False, default=None):
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return default
    v = b[name]
    if not isinstance(v, str) or v not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return v


def f_bool(b, name, required=False, default=None):
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return default
    v = b[name]
    if not isinstance(v, bool):
        bad("%s must be a boolean" % name)
    return v


def f_int(b, name, required=False, default=None, minimum=None, maximum=None):
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("%s must be an integer" % name)
    if minimum is not None and v < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return v


def f_num(b, name, required=False, default=None, minimum=None, exclusive_min=None):
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("%s must be a number" % name)
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        bad("%s must be a number" % name)
    if minimum is not None and d < Decimal(str(minimum)):
        bad("%s must be >= %s" % (name, minimum))
    if exclusive_min is not None and d <= Decimal(str(exclusive_min)):
        bad("%s must be > %s" % (name, exclusive_min))
    return d


def parse_iso(value, name):
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be an ISO 8601 datetime string" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        bad("%s must be an ISO 8601 datetime string" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f_dt(b, name, required=False, default=None):
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return default
    return parse_iso(b[name], name)


# --------------------------------------------------------------------- querying
def q_pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            bad("limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("limit must be between %d and %d" % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def q_str(name, required=False, default=None):
    if name not in request.args:
        if required:
            bad("%s is required" % name)
        return default
    v = request.args.get(name)
    if v is None or v == "":
        if required:
            bad("%s is required" % name)
        return default
    return v


def q_enum(name, allowed, required=False, default=None):
    v = q_str(name, required=required, default=None)
    if v is None:
        return default
    if v not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return v


def q_bool(name, default=None):
    if name not in request.args:
        return default
    v = request.args.get(name)
    low = (v or "").lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad("%s must be a boolean" % name)


# --------------------------------------------------------- existence resolution
def _find(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id, "resource %s not found" % row_id)
    return row


def get_company(cid):
    return _find(store.companies, cid, "ERR_COMPANY_NOT_FOUND")


def get_contact(cid):
    return _find(store.contacts, cid, "ERR_CONTACT_NOT_FOUND")


def get_disclosure(did):
    return _find(store.disclosures, did, "ERR_DISCLOSURE_NOT_FOUND")


def get_inquiry(iid):
    return _find(store.inquiries, iid, "ERR_INQUIRY_NOT_FOUND")


def get_draft(did):
    return _find(store.drafts, did, "ERR_RESPONSE_DRAFT_NOT_FOUND")


def get_event(eid):
    return _find(store.events, eid, "ERR_ROADSHOW_EVENT_NOT_FOUND")


def get_meeting_request(mid):
    return _find(store.meeting_requests, mid, "ERR_MEETING_REQUEST_NOT_FOUND")


def get_instruction(iid):
    return _find(store.instructions, iid, "ERR_INSTRUCTION_NOT_FOUND")


def own_contact(actor, contact_id):
    """Step 6: acting-identity ownership for the entity-backed Investor role."""
    if actor.role == "Investor" and actor.user_id != contact_id:
        raise ApiError("ERR_CONTACT_OWNERSHIP_MISMATCH",
                       "an Investor may only act on its own contact record")
