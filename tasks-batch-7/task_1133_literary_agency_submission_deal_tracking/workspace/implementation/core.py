"""Core infrastructure: in-memory store, errors, response envelope, auth, validation."""
import threading
import uuid
from datetime import datetime, timezone

from flask import g, jsonify, request

LOCK = threading.RLock()

DB = {
    "agencies": {},
    "agents": {},
    "authors": {},
    "editors": {},
    "query_letters": {},
    "manuscripts": {},
    "client_agreements": {},
    "submission_rounds": {},
    "submissions": {},
    "offers": {},
    "deals": {},
    "royalty_statements": {},
    "advance_installments": {},
}

_SEQ = [0]


def _next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def new_record():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": _next_seq()}


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------- errors ----
ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"
ERR_BODY = "ERR_INVALID_REQUEST"
ERR_NF = "ERR_NOT_FOUND"
ERR_STALE = "ERR_STALE_VERSION"
ERR_STATE = "ERR_INVALID_STATE"
ERR_SOD = "ERR_SEGREGATION_OF_DUTIES"
ERR_NOT_ASSIGNED = "ERR_NOT_ASSIGNED_AGENT"
ERR_AGENT_INACTIVE = "ERR_AGENT_INACTIVE"
ERR_EDITOR_INACTIVE = "ERR_EDITOR_INACTIVE"
ERR_INTAKE = "ERR_INTAKE_PAUSED"
ERR_SCORE = "ERR_SCORE_BELOW_THRESHOLD"
ERR_REVISION = "ERR_REVISION_LIMIT_REACHED"
ERR_MS_NOT_ACCEPTED = "ERR_MANUSCRIPT_NOT_ACCEPTED"
ERR_AGR_SIGNED = "ERR_AGREEMENT_ALREADY_SIGNED"
ERR_AGR_NOT_SIGNED = "ERR_AGREEMENT_NOT_SIGNED"
ERR_DEAL_OPEN = "ERR_DEAL_STILL_OPEN"
ERR_ROUND_OPEN = "ERR_ROUND_ALREADY_OPEN"
ERR_EMPTY_ROUND = "ERR_EMPTY_ROUND"
ERR_ROUND_CAP = "ERR_ROUND_CAPACITY_EXCEEDED"
ERR_ROUND_NOT_OPEN = "ERR_ROUND_NOT_OPEN"
ERR_DUP_SUB = "ERR_DUPLICATE_SUBMISSION"
ERR_EXCL = "ERR_EDITOR_EXCLUSIVE_WINDOW"
ERR_ROUND_LIVE_SUBS = "ERR_ROUND_HAS_LIVE_SUBMISSIONS"
ERR_ROUND_LIVE_OFFERS = "ERR_ROUND_HAS_LIVE_OFFERS"
ERR_OFFER_LIVE = "ERR_OFFER_STILL_LIVE"
ERR_NOT_TOP = "ERR_NOT_TOP_RANKED_OFFER"
ERR_DEAL_NOT_LIVE = "ERR_DEAL_NOT_LIVE"
ERR_STMT_UNRESOLVED = "ERR_STATEMENTS_UNRESOLVED"
ERR_FUTURE = "ERR_FUTURE_STATEMENT"
ERR_BOOKS = "ERR_BOOKS_CLOSED"
ERR_VAR_WITHIN = "ERR_VARIANCE_WITHIN_TOLERANCE"
ERR_VAR_UNRESOLVED = "ERR_VARIANCE_UNRESOLVED"


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


def not_found(msg="resource not found"):
    raise ApiError(ERR_NF, 404, msg)


def bad_request(msg):
    raise ApiError(ERR_BODY, 400, msg)


# --------------------------------------------------------------- envelope ----
def _rid():
    rid = getattr(g, "rid", None)
    if not rid:
        rid = "req_" + uuid.uuid4().hex[:20]
        g.rid = rid
    return rid


def success(data, code=200, is_list=False, pagination=None):
    meta = {"api_request_id": _rid(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _rid(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ------------------------------------------------------------------- auth ----
ROLES = ("AgencyAdmin", "Agent", "ContractsManager", "RoyaltiesAccountant")


class Ctx:
    __slots__ = ("uid", "role", "agent")

    def __init__(self, uid, role, agent):
        self.uid = uid
        self.role = role
        self.agent = agent


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (not uid or not isinstance(uid, str) or not uid.strip()
            or not role or role not in ROLES):
        fail(ERR_AUTH, 400, "X-User-ID and X-User-Role headers missing or malformed")
    agent = None
    if role == "Agent":
        # An unknown acting agent is not an auth failure (headers are
        # well-formed); every tenancy check below treats their resources as
        # out of scope, and role admission (priority 2) still runs first.
        agent = DB["agents"].get(uid)
    return Ctx(uid, role, agent)


def acting_agency(ctx):
    """Agency id of the acting Agent; unknown agents see nothing (404)."""
    if ctx.agent is None:
        not_found("acting agent does not exist")
    return ctx.agent["agency_id"]


def guard(*roles):
    """Authenticate (priority 1) then check role admission (priority 2)."""
    ctx = authenticate()
    if ctx.role not in roles:
        fail(ERR_ROLE, 403, "role %s is not permitted for this endpoint" % ctx.role)
    return ctx


def scope_of(coll, rec):
    return rec["id"] if coll == "agencies" else rec.get("agency_id")


def get_scoped(coll, rec_id, ctx):
    """Existence + Agent tenancy check (priority 4)."""
    rec = DB[coll].get(rec_id)
    if rec is None:
        not_found("resource not found: %s" % rec_id)
    if ctx.role == "Agent":
        if ctx.agent is None or scope_of(coll, rec) != ctx.agent["agency_id"]:
            not_found("resource not found: %s" % rec_id)
    return rec


def get_ref(coll, rec_id, agency_id):
    """Body cross-reference: must exist and belong to the given agency."""
    rec = DB[coll].get(rec_id)
    if rec is None:
        not_found("referenced %s not found: %s" % (coll, rec_id))
    if agency_id is not None and scope_of(coll, rec) != agency_id:
        not_found("referenced %s not found: %s" % (coll, rec_id))
    return rec


# ------------------------------------------------------------- validation ----
def F(name, kind, required=False, default=None, lo=None, hi=None, enum=None,
      nullable=False):
    return {"name": name, "kind": kind, "required": required, "default": default,
            "lo": lo, "hi": hi, "enum": enum, "nullable": nullable}


def parse_body(spec):
    """Body shape validation (priority 3). spec is a list of F() field specs."""
    raw = request.get_json(silent=True)
    if raw is None:
        if request.data and request.data.strip():
            bad_request("request body is not valid JSON")
        raw = {}
    if not isinstance(raw, dict):
        bad_request("request body must be a JSON object")
    allowed = {s["name"] for s in spec}
    extra = sorted(set(raw.keys()) - allowed)
    if extra:
        bad_request("undeclared field(s): %s" % ", ".join(extra))
    out = {}
    for s in spec:
        name = s["name"]
        if name not in raw:
            if s["required"]:
                bad_request("missing required field: %s" % name)
            out[name] = s["default"]
            continue
        val = raw[name]
        if val is None:
            if s["nullable"]:
                out[name] = None
                continue
            bad_request("field may not be null: %s" % name)
        kind = s["kind"]
        if kind == "bool":
            if not isinstance(val, bool):
                bad_request("field must be a boolean: %s" % name)
        elif kind == "int":
            if isinstance(val, bool) or not isinstance(val, int):
                bad_request("field must be an integer: %s" % name)
        elif kind == "num":
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                bad_request("field must be a number: %s" % name)
        elif kind == "str":
            if not isinstance(val, str) or val == "":
                bad_request("field must be a non-empty string: %s" % name)
        elif kind == "enum":
            if not isinstance(val, str) or val not in s["enum"]:
                bad_request("field must be one of %s: %s"
                            % (sorted(s["enum"]), name))
        if kind in ("int", "num"):
            if s["lo"] is not None and val < s["lo"]:
                bad_request("field below minimum: %s" % name)
            if s["hi"] is not None and val > s["hi"]:
                bad_request("field above maximum: %s" % name)
        out[name] = val
    return out


# ------------------------------------------------------------- pagination ----
def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        bad_request("invalid pagination parameters")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def list_response(coll, ctx, filter_kinds):
    items = list(DB[coll].values())
    if ctx.role == "Agent":
        if ctx.agent is None:
            items = []
        else:
            aid = ctx.agent["agency_id"]
            items = [r for r in items if r.get("agency_id") == aid]
    for fname, kind in filter_kinds.items():
        raw = request.args.get(fname)
        if raw is None:
            continue
        if kind == "int":
            try:
                val = int(raw)
            except (TypeError, ValueError):
                bad_request("invalid filter value: %s" % fname)
            items = [r for r in items if r.get(fname) == val]
        else:
            items = [r for r in items if r.get(fname) == raw]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, pag = paginate(items)
    return success([public(r) for r in page], 200, is_list=True, pagination=pag)
