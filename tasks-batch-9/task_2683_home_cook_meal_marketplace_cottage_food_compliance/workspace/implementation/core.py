"""Foundation: in-memory store, logical clock, response envelope, error catalog."""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify

# ---------------------------------------------------------------- logical clock
# PRD 2.5: the server keeps a single logical UTC clock; on boot it is
# 2026-08-01T00:00:00Z. Nothing in the system reads wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns a tz-aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD). Returns date or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


# ------------------------------------------------------------------- money math
def rhu(value):
    """Round a Decimal to a whole integer, half-up (PRD 2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct(cents, rate):
    """round_half_up(cents * rate) -> int cents."""
    return rhu(Decimal(int(cents)) * Decimal(str(rate)))


def ceil_div_pct(value, rate):
    """ceil(value * rate) using exact decimal arithmetic."""
    prod = Decimal(int(value)) * Decimal(str(rate))
    whole = int(prod.to_integral_value(rounding="ROUND_FLOOR"))
    return whole if prod == whole else whole + 1


# ------------------------------------------------------------------ error model
class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 422)


ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_MISSING_USER_ID": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SOD_SAME_OFFICER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STATE_POLICY_NOT_FOUND": 404,
    "ERR_COOK_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_MENU_ITEM_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_HUB_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_REFUND_NOT_FOUND": 404,
    "ERR_STALE_COOK_VERSION": 412,
    "ERR_STALE_WINDOW_VERSION": 412,
    "ERR_INVALID_COOK_TRANSITION": 409,
    "ERR_INVALID_DOCUMENT_TRANSITION": 409,
    "ERR_INVALID_MENU_ITEM_TRANSITION": 409,
    "ERR_INVALID_WINDOW_TRANSITION": 409,
    "ERR_INVALID_ORDER_TRANSITION": 409,
    "ERR_INVALID_INCIDENT_TRANSITION": 409,
    "ERR_INVALID_STATEMENT_TRANSITION": 409,
    "ERR_COOK_NOT_ACTIVE": 409,
    "ERR_MENU_ITEM_NOT_APPROVED": 409,
    "ERR_WINDOW_CUTOFF_PASSED": 409,
    "ERR_DOC_ALREADY_REVIEWED": 409,
    "ERR_INCIDENT_NOT_TRIAGED": 409,
    "ERR_CUTOFF_NOT_REACHED": 409,
    "ERR_HANDOFF_NOT_STARTED": 409,
    "ERR_HANDOFF_NOT_FINISHED": 409,
    "ERR_ORDER_NOT_REFUNDABLE": 409,
    "ERR_COOK_SUSPENDED": 409,
    "ERR_CERT_EXPIRED": 409,
    "ERR_KITCHEN_TYPE_NOT_ALLOWED": 422,
    "ERR_TCS_REQUIRES_COMMERCIAL_KITCHEN": 422,
    "ERR_ALLERGEN_DISCLOSURE_MISSING": 422,
    "ERR_COLD_CHAIN_INFEASIBLE": 422,
    "ERR_OPEN_INCIDENT_BLOCKS_PAYOUT": 409,
    "ERR_SHELF_LIFE_EXCEEDS_POLICY": 422,
    "ERR_LABEL_FIELDS_INCOMPLETE": 422,
    "ERR_DOC_FIELDS_INVALID_FOR_TYPE": 422,
    "ERR_CERT_VALIDITY_TOO_LONG": 422,
    "ERR_CUTOFF_AFTER_HANDOFF": 422,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_HUB_SLOT_CONFLICT": 409,
    "ERR_WINDOW_CAPACITY_ABOVE_COOK_LIMIT": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_DUPLICATE_STATE_POLICY": 409,
    "ERR_DUPLICATE_ZONE_CODE": 409,
    "ERR_DUPLICATE_COOK_EMAIL": 409,
    "ERR_DUPLICATE_FINALIZED_STATEMENT": 409,
    "ERR_ZONE_STATE_MISMATCH": 422,
    "ERR_INCIDENT_SUBJECT_MISMATCH": 422,
    "ERR_HUB_ZONE_INELIGIBLE": 422,
    "ERR_COTTAGE_CAP_EXCEEDED": 422,
    "ERR_WINDOW_CAPACITY_EXCEEDED": 422,
    "ERR_REFUND_EXCEEDS_REMAINING": 422,
    "ERR_PAYOUT_HOLD_ACTIVE": 409,
    "ERR_NO_ELIGIBLE_HUB": 422,
    "ERR_NO_ELIGIBLE_ORDERS": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADER": "X-User-Role header is missing or empty",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not a recognised role",
    "ERR_MISSING_USER_ID": "X-User-ID header is required for this role",
    "ERR_ROLE_NOT_PERMITTED": "role is not permitted to perform this operation",
    "ERR_NOT_RESOURCE_OWNER": "acting user does not own the target resource",
    "ERR_INVALID_REQUEST": "request body or query parameters are malformed",
}


# ------------------------------------------------------------- in-memory store
class Store(object):
    """Pure in-memory store. Starts completely empty on every boot."""

    COLLECTIONS = (
        "state_policies",
        "cooks",
        "documents",
        "menu_items",
        "windows",
        "zones",
        "hubs",
        "orders",
        "incidents",
        "statements",
        "refunds",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_dt(self.clock)


db = Store()


def new_row(collection, fields):
    """Create a row with server-minted id and the three common system fields."""
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    stamp = db.now_iso()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """PRD 2.4: version increments on every mutation of the row; cascade-touched
    rows behave exactly as if written directly. A row is bumped at most once per
    request so a multi-field cascade write counts as a single mutation."""
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    row["updated_at"] = db.now_iso()
    if row["id"] not in seen:
        seen.add(row["id"])
        row["version"] = int(row["version"]) + 1


def ordered(rows):
    """Lists are always ordered by created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


# --------------------------------------------------------------------- envelope
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": db.now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [public(r) for r in rows]}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
