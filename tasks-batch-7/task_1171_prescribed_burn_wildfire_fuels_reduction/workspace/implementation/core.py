"""Core plumbing: in-memory store, logical clock, envelope, errors, auth, validation."""
import re
import secrets
import string
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import request

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; no seeding)
# ---------------------------------------------------------------------------

DB = {
    "associations": {},
    "landowners": {},
    "parcels": {},
    "bosses": {},
    "contractors": {},
    "plans": {},
    "permits": {},
    "notifications": {},
    "smoke_approvals": {},
    "contingencies": {},
    "ignition_plans": {},
    "orders": {},
    "assignments": {},
    "executions": {},
    "observations": {},
    "checklists": {},
    "incidents": {},
    "reports": {},
    "agreements": {},
    "claims": {},
}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK = [DEFAULT_CLOCK]


def clock():
    return _CLOCK[0]


def set_clock(dt):
    _CLOCK[0] = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(clock())


def parse_datetime(s):
    """Parse an ISO 8601 datetime into an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD date, or None."""
    if not isinstance(s, str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _req_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}


def ok(data, code=200):
    return {"meta": meta(), "response_type": "object", "data": data}, code


def ok_list(items, total, limit, offset):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return {"meta": m, "response_type": "array", "data": items}, 200


def err_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = {
    "AssociationAdmin",
    "Landowner",
    "BurnBoss",
    "AgencyReviewer",
    "AirQualityOfficer",
    "IncidentCommander",
    "Contractor",
}


def auth():
    """Priority 1: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid.strip() == "" or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid.strip(), role.strip()


def require_role(role, allowed):
    """Priority 2: role must be listed for the endpoint. `allowed=None` -> Any."""
    if allowed is None:
        if role not in ROLES:
            raise ApiError(
                "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint"
            )
        return
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint"
        )


# ---------------------------------------------------------------------------
# Body parsing & field validation (field-level checks run LAST per PRD 2.7)
# ---------------------------------------------------------------------------


def body():
    """Return the JSON object body. A body that cannot be parsed at all is
    malformed and reported before authentication (PRD 2.7)."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = None
    try:
        import json

        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed request body")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed request body")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class Validator:
    """Collects field-level shape errors; raised only when finish() is called,
    so business/state/auth errors surface first for well-formed bodies."""

    RANK = {"ERR_INVALID_REQUEST": 0, "ERR_INVALID_ENUM": 1, "ERR_INVALID_PRESCRIPTION_PARAMS": 2}

    def __init__(self, data, allowed_fields):
        self.b = data if isinstance(data, dict) else {}
        self.best = None
        unknown = sorted(set(self.b.keys()) - set(allowed_fields))
        if unknown:
            self._set("ERR_INVALID_REQUEST", f"Unknown field: {unknown[0]}")

    def _set(self, eid, msg):
        cand = (self.RANK[eid], eid, msg)
        if self.best is None or cand[0] < self.best[0]:
            self.best = cand

    # -- raw access for business checks (typed or None) --------------------
    def get(self, k):
        return self.b.get(k)

    def present(self, k):
        return k in self.b and self.b[k] is not None

    def typed(self, k, typ):
        v = self.b.get(k)
        if typ is int:
            return v if is_int(v) else None
        if typ is str:
            return v if isinstance(v, str) else None
        if typ is bool:
            return v if isinstance(v, bool) else None
        if typ is list:
            return v if isinstance(v, list) else None
        return None

    # -- deferred field-level checks ---------------------------------------
    def req(self, k, typ):
        if k not in self.b or self.b[k] is None:
            self._set("ERR_INVALID_REQUEST", f"Missing required field: {k}")
        elif self.typed(k, typ) is None:
            self._set("ERR_INVALID_REQUEST", f"Field {k} has an invalid type")

    def opt(self, k, typ):
        if k in self.b and self.b[k] is not None and self.typed(k, typ) is None:
            self._set("ERR_INVALID_REQUEST", f"Field {k} has an invalid type")

    def enum(self, k, members, required=True):
        v = self.b.get(k)
        if v is None:
            if required:
                self._set("ERR_INVALID_REQUEST", f"Missing required field: {k}")
            return
        if not isinstance(v, str):
            self._set("ERR_INVALID_REQUEST", f"Field {k} has an invalid type")
        elif v not in members:
            self._set(
                "ERR_INVALID_ENUM",
                f"Field {k} must be one of {sorted(members)}",
            )

    def date(self, k, required=True):
        v = self.b.get(k)
        if v is None:
            if required:
                self._set("ERR_INVALID_REQUEST", f"Missing required field: {k}")
            return
        if parse_date(v) is None:
            self._set("ERR_INVALID_REQUEST", f"Field {k} must be an ISO date (YYYY-MM-DD)")

    def datetime(self, k, required=True):
        v = self.b.get(k)
        if v is None:
            if required:
                self._set("ERR_INVALID_REQUEST", f"Missing required field: {k}")
            return
        if parse_datetime(v) is None:
            self._set("ERR_INVALID_REQUEST", f"Field {k} must be an ISO 8601 datetime")

    def prescription(self, msg):
        self._set("ERR_INVALID_PRESCRIPTION_PARAMS", msg)

    def invalid(self, msg):
        self._set("ERR_INVALID_REQUEST", msg)

    def finish(self):
        if self.best is not None:
            _, eid, msg = self.best
            status = 400
            raise ApiError(eid, status, msg)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, serializer, sort_key=None):
    if sort_key is None:
        sort_key = lambda e: (e["created_at"], e["_seq"])
    items = sorted(items, key=sort_key)
    limit, offset = pagination()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------


def stamp_new(e, with_version=True):
    e["id"] = new_id()
    e["_seq"] = next_seq()
    e["created_at"] = now_iso()
    if with_version:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def touch(e):
    """version +1 and updated_at refresh (standard mutation bookkeeping)."""
    e["version"] += 1
    e["updated_at"] = now_iso()
