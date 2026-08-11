"""Core infrastructure: errors, logical clock, in-memory store, response envelope,
canonical instant rendering, and the global nine-gate request pipeline.

Every structural name here is read from PRD.md / SCAFFOLD.yaml:
  identity headers  : X-User-ID, X-User-Role
  envelope          : meta / response_type / data, error body error_id + message
  pagination        : limit, offset, total_count, has_more (default 10 / 0)
  concurrency field : version
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import g, jsonify, request

API_PREFIX = "/water-service"

ROLES = [
    "PlatformAdmin",
    "Dispatcher",
    "Estimator",
    "Technician",
    "ComplianceOfficer",
    "BillingClerk",
    "CustomerContact",
]

JURISDICTION_CODES = ["JUR_ALPHA", "JUR_BRAVO", "JUR_CHARLIE", "JUR_DELTA"]

# --------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACTOR_SCOPE_VIOLATION": 403,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_WELL_PROFILE_NOT_FOUND": 404,
    "ERR_SHARED_WELL_AGREEMENT_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_PART_CATALOG_ITEM_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_WATER_TEST_NOT_FOUND": 404,
    "ERR_TREATMENT_RECOMMENDATION_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_QUOTE_LINE_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_EMERGENCY_TICKET_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_PARTS_CONSUMPTION_ENTRY_NOT_FOUND": 404,
    "ERR_WARRANTY_COVERAGE_NOT_FOUND": 404,
    "ERR_CALLBACK_CLAIM_NOT_FOUND": 404,
    "ERR_MAINTENANCE_PLAN_NOT_FOUND": 404,
    "ERR_MAINTENANCE_VISIT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVOICE_LINE_NOT_FOUND": 404,
    "ERR_INSPECTION_INVALID_STATE": 409,
    "ERR_WATER_TEST_INVALID_STATE": 409,
    "ERR_TREATMENT_RECOMMENDATION_INVALID_STATE": 409,
    "ERR_QUOTE_INVALID_STATE": 409,
    "ERR_QUOTE_LINE_INVALID_STATE": 409,
    "ERR_EMERGENCY_DISPATCH_INVALID_STATE": 409,
    "ERR_EMERGENCY_AUTH_INVALID_STATE": 409,
    "ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE": 409,
    "ERR_WORK_ORDER_INVALID_BILLING_STATE": 409,
    "ERR_PERMIT_INVALID_STATE": 409,
    "ERR_CALLBACK_CLAIM_INVALID_STATE": 409,
    "ERR_INVOICE_INVALID_STATE": 409,
    "ERR_MAINTENANCE_PLAN_INVALID_STATE": 409,
    "ERR_WARRANTY_ALREADY_SUPERSEDED": 409,
    "ERR_PERMIT_JURISDICTION_MISMATCH": 422,
    "ERR_POST_HOC_PERMIT_WINDOW_EXPIRED": 422,
    "ERR_PERMIT_REQUIRED_NOT_APPROVED": 422,
    "ERR_TECHNICIAN_TIER_INSUFFICIENT": 403,
    "ERR_RETEST_WINDOW_EXPIRED": 422,
    "ERR_WATER_TEST_HOLD_TIME_EXCEEDED": 422,
    "ERR_CONFIRMATORY_SAME_OFFICER": 403,
    "ERR_CALLBACK_ADJUDICATOR_CONFLICT": 403,
    "ERR_STALE_WELL_PROFILE_VERSION": 412,
    "ERR_STALE_QUOTE_VERSION": 412,
    "ERR_STALE_INVOICE_VERSION": 412,
    "ERR_STALE_MAINTENANCE_PLAN_VERSION": 412,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_TIMESTAMP": 400,
    "ERR_NEGATIVE_QUANTITY": 400,
    "ERR_INVALID_DATE_RANGE": 400,
    "ERR_CLOCK_BACKWARD": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_NO_TREATMENT_INDICATED": 422,
    "ERR_POTABILITY_PENDING_CONFIRMATION": 422,
    "ERR_TREATMENT_RECOMMENDATION_EXPIRED": 422,
    "ERR_RETEST_WINDOW_STILL_OPEN": 409,
    "ERR_YIELD_INSUFFICIENT_FOR_PUMP": 422,
    "ERR_INSPECTION_REQUIRED": 422,
    "ERR_INSPECTION_STALE": 422,
    "ERR_QUOTE_HAS_NO_ACTIVE_LINES": 422,
    "ERR_QUOTE_LINE_YIELD_EXCEEDED": 409,
    "ERR_QUOTE_NOT_APPROVED": 422,
    "ERR_WORK_ORDER_ORIGIN_CONFLICT": 422,
    "ERR_EMERGENCY_TICKET_ALREADY_LINKED": 409,
    "ERR_TECHNICIAN_UNAVAILABLE": 409,
    "ERR_TECHNICIAN_SCHEDULE_CONFLICT": 409,
    "ERR_WELL_SERVICE_WINDOW_CONFLICT": 409,
    "ERR_NON_WELL_CAUSE_BLOCKS_PARTS": 422,
    "ERR_AUTHORIZATION_REQUIRED": 402,
    "ERR_PREAUTH_CAP_EXCEEDED": 402,
    "ERR_PART_DISCONTINUED": 422,
    "ERR_PART_OUT_OF_STOCK": 409,
    "ERR_PART_CATEGORY_MISMATCH": 422,
    "ERR_QUANTITY_EXCEEDS_LIMIT": 422,
    "ERR_CALLBACK_OUT_OF_WARRANTY": 409,
    "ERR_CALLBACK_ALREADY_CONSUMED": 409,
    "ERR_CALLBACK_LIMIT_REACHED": 409,
    "ERR_PERMIT_ALREADY_ON_FILE": 409,
    "ERR_OUT_OF_SERVICE_AREA": 422,
    "ERR_PAYMENT_AMOUNT_INVALID": 400,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_ACCOUNT_ON_CREDIT_HOLD": 402,
    "ERR_DUPLICATE_SHARED_WELL_AGREEMENT": 409,
    "ERR_SHARED_WELL_SPLIT_INVALID": 422,
    "ERR_SALT_DELIVERY_EXCEEDS_CAPACITY": 422,
    "ERR_FILTER_CHANGE_TOO_SOON": 422,
    "ERR_PLAN_ALREADY_EXISTS_FOR_WELL": 409,
    "ERR_RETEST_CONFIRMED_POSITIVE": 422,
}


class ApiError(Exception):
    """Carries an error_id, a message and the catalogue's HTTP status.

    ``persist`` marks the three PRD section 2.11 mutate-then-reject rungs: the
    durable writes already made by the handler are flushed and are NOT rolled
    back before the error response goes out.
    """

    def __init__(self, error_id, message=None, persist=False):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.persist = persist


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# --------------------------------------------------------------------------
# Canonical instant rendering / parsing (PRD 2.4)
# --------------------------------------------------------------------------

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)


def parse_instant(value):
    """Parse any parseable ISO 8601 UTC instant.  Returns an aware datetime or
    None when the value cannot be parsed.

    Two things are deliberately *not* accepted, because a string missing
    either one does not denote a UTC instant at all:

    * a space in place of the literal ``T`` date/time separator, and
    * a bare local datetime with no zone designator.

    ``2026-06-01 12:00`` fails on both counts and is an ERR_INVALID_TIMESTAMP,
    while reduced precision (``2026-06-01T12:00Z``), a comma decimal mark and
    a numeric offset all remain parseable ISO 8601 UTC forms.
    """
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def iso(dt):
    """The one canonical renderer.  Exactly three fractional digits and a Z.

    Every instant in every response body -- server stamped or client supplied --
    goes through here, so a client instant is never echoed back byte-for-byte.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def whole_days_between(a, b):
    """Whole days from a to b, floored (may be negative).

    timedelta normalises so that 0 <= seconds < 86400, which makes .days the
    exact floor of the elapsed days even when the interval is negative.
    """
    return (b - a).days


def hours_between(a, b):
    return Decimal(str((b - a).total_seconds())) / Decimal(3600)


# --------------------------------------------------------------------------
# Rounding helpers (PRD 2.9 -- every rounding is round half up)
# --------------------------------------------------------------------------

def d(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return d(value).quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def floor_div(value):
    return int(d(value).to_integral_value(rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------
# In-memory store.  Empty on every boot -- nothing is ever seeded.
# --------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

KIND_NOT_FOUND = {
    "Account": "ERR_ACCOUNT_NOT_FOUND",
    "Property": "ERR_PROPERTY_NOT_FOUND",
    "WellProfile": "ERR_WELL_PROFILE_NOT_FOUND",
    "SharedWellAgreement": "ERR_SHARED_WELL_AGREEMENT_NOT_FOUND",
    "Technician": "ERR_TECHNICIAN_NOT_FOUND",
    "PartCatalogItem": "ERR_PART_CATALOG_ITEM_NOT_FOUND",
    "Inspection": "ERR_INSPECTION_NOT_FOUND",
    "WaterTest": "ERR_WATER_TEST_NOT_FOUND",
    "TreatmentRecommendation": "ERR_TREATMENT_RECOMMENDATION_NOT_FOUND",
    "Quote": "ERR_QUOTE_NOT_FOUND",
    "QuoteLine": "ERR_QUOTE_LINE_NOT_FOUND",
    "EmergencyTicket": "ERR_EMERGENCY_TICKET_NOT_FOUND",
    "WorkOrder": "ERR_WORK_ORDER_NOT_FOUND",
    "Permit": "ERR_PERMIT_NOT_FOUND",
    "PartsConsumptionEntry": "ERR_PARTS_CONSUMPTION_ENTRY_NOT_FOUND",
    "WarrantyCoverage": "ERR_WARRANTY_COVERAGE_NOT_FOUND",
    "CallbackClaim": "ERR_CALLBACK_CLAIM_NOT_FOUND",
    "MaintenancePlan": "ERR_MAINTENANCE_PLAN_NOT_FOUND",
    "MaintenanceVisit": "ERR_MAINTENANCE_VISIT_NOT_FOUND",
    "Invoice": "ERR_INVOICE_NOT_FOUND",
    "InvoiceLine": "ERR_INVOICE_LINE_NOT_FOUND",
}

# The two entity kinds that carry only id and created_at (PRD 2.5).
NO_COMMON_FIELDS = {"MaintenanceVisit", "InvoiceLine"}


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK_UTC
        self.rows = {k: {} for k in KIND_NOT_FOUND}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def create(self, kind, fields):
        row = dict(fields)
        row["_kind"] = kind
        row["id"] = str(uuid.uuid4())
        row["created_at"] = self.clock
        row["_seq"] = self.next_seq()
        if kind not in NO_COMMON_FIELDS:
            row["updated_at"] = self.clock
            row["version"] = 1
        self.rows[kind][row["id"]] = row
        return row

    def get(self, kind, row_id):
        if not isinstance(row_id, str):
            return None
        return self.rows[kind].get(row_id)

    def all(self, kind):
        """Every row of a kind in created_at ascending order (insertion order
        breaks ties -- the logical clock can stamp many rows identically)."""
        return sorted(self.rows[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))


db = Store()


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(db.clock)}


def success(data, code=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# G8 payload field specification
# --------------------------------------------------------------------------

MISSING = object()


class F(object):
    """One declared body field.

    ``enum`` routes a bad member to ERR_INVALID_ENUM -- the closed list of
    PRD 2.7.  ``one_of`` is a *string* constraint (the four jurisdiction-code
    fields) and routes to ERR_VALIDATION instead.
    """

    def __init__(self, name, type, required=True, enum=None, one_of=None,
                 minimum=None, maximum=None, min_len=None, max_len=None,
                 nonneg=False, default=None, contains=None):
        self.name = name
        self.type = type
        self.required = required
        self.enum = enum
        self.one_of = one_of
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.nonneg = nonneg
        self.default = default
        self.contains = contains


def _type_ok(field, value):
    t = field.type
    if t == "string" or t == "datetime":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    return True


def validate_body(fields, raw):
    """Run G8 over the declared field list and return the coerced values.

    Pass order: presence/type -> enum membership -> timestamp format ->
    strictly-negative quantity -> value constraints (string one-of, ranges,
    lengths).  Unknown keys are ignored silently.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")

    present = {}
    out = {}

    # pass 1 -- presence and JSON type
    for f in fields:
        value = raw.get(f.name, MISSING)
        if value is MISSING or value is None:
            if f.required and value is None:
                raise ApiError("ERR_VALIDATION", "Field '%s' must not be null." % f.name)
            if f.required:
                raise ApiError("ERR_VALIDATION", "Field '%s' is required." % f.name)
            out[f.name] = f.default
            continue
        if not _type_ok(f, value):
            raise ApiError("ERR_VALIDATION", "Field '%s' has the wrong type." % f.name)
        present[f.name] = value
        out[f.name] = value

    # pass 2 -- enum membership (closed ERR_INVALID_ENUM list)
    for f in fields:
        if f.enum and f.name in present:
            if present[f.name] not in f.enum:
                raise ApiError("ERR_INVALID_ENUM",
                               "Field '%s' is not a declared member." % f.name)

    # pass 3 -- timestamp format
    for f in fields:
        if f.type == "datetime" and f.name in present:
            parsed = parse_instant(present[f.name])
            if parsed is None:
                raise ApiError("ERR_INVALID_TIMESTAMP",
                               "Field '%s' is not an ISO 8601 UTC instant." % f.name)
            out[f.name] = parsed

    # pass 4 -- strictly negative quantity / amount / pounds
    for f in fields:
        if f.nonneg and f.name in present:
            if d(present[f.name]) < 0:
                raise ApiError("ERR_NEGATIVE_QUANTITY",
                               "Field '%s' must not be negative." % f.name)

    # pass 5 -- remaining value constraints
    for f in fields:
        if f.name not in present:
            continue
        value = present[f.name]
        if f.one_of is not None and value not in f.one_of:
            raise ApiError("ERR_VALIDATION",
                           "Field '%s' is outside its declared value set." % f.name)
        if f.minimum is not None and d(value) < d(f.minimum):
            raise ApiError("ERR_VALIDATION", "Field '%s' is below its minimum." % f.name)
        if f.maximum is not None and d(value) > d(f.maximum):
            raise ApiError("ERR_VALIDATION", "Field '%s' is above its maximum." % f.name)
        if f.min_len is not None and len(value) < f.min_len:
            raise ApiError("ERR_VALIDATION", "Field '%s' is too short." % f.name)
        if f.max_len is not None and len(value) > f.max_len:
            raise ApiError("ERR_VALIDATION", "Field '%s' is too long." % f.name)
        if f.contains is not None and f.contains not in value:
            raise ApiError("ERR_VALIDATION", "Field '%s' is malformed." % f.name)

    return out


# --------------------------------------------------------------------------
# Pagination (G8_QUERY)
# --------------------------------------------------------------------------

def _pag_int(raw, default, minimum, maximum):
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not re.match(r"^[+-]?\d+$", text):
        raise ApiError("ERR_INVALID_PAGINATION", "Pagination parameters must be integers.")
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_PAGINATION", "Pagination parameter out of range.")
    return value


def read_pagination(args):
    limit = _pag_int(args.get("limit"), 10, 1, 100)
    offset = _pag_int(args.get("offset"), 0, 0, None)
    return limit, offset


def paginate(rows, args):
    limit, offset = read_pagination(args)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def apply_filters(rows, args, filters):
    """Exact-match filters.  A filter value outside the field's member set is
    never an error -- it simply matches no rows (PRD 2.3)."""
    out = rows
    for name in filters:
        raw = args.get(name)
        if raw is None:
            continue
        wanted = raw.strip()
        kept = []
        for row in out:
            value = row.get(name)
            if isinstance(value, bool):
                if wanted.lower() == ("true" if value else "false"):
                    kept.append(row)
            elif value is None:
                if wanted.lower() == "null":
                    kept.append(row)
            elif str(value) == wanted:
                kept.append(row)
        out = kept
    return out


# --------------------------------------------------------------------------
# Request context and the nine-gate pipeline
# --------------------------------------------------------------------------

class Ctx(object):
    def __init__(self, role, user_id, args):
        self.role = role
        self.user_id = user_id
        self.args = args
        self.path = {}
        self.body = {}
        self.raw_body = {}
        self.touched = {}
        self.created = set()

    def touch(self, row):
        """Mark a row mutated by this request and raise its version once.

        PRD 2.5: ``version`` increments by exactly one per entity per
        successful request -- not once per mutation step and not once per
        cascade hop -- so the bump is applied on the FIRST touch of a row and
        the ``touched`` map makes every later touch of the same row a no-op.

        The bump has to happen here rather than at the end of the request:
        a handler builds its response body by serialising the row it just
        mutated, so a deferred bump would ship the pre-mutation ``version``
        and a client echoing it back into the next ``expected_*_version``
        would be told its own fresh read was stale.
        """
        if row is not None and id(row) not in self.touched:
            self.touched[id(row)] = row
            if (row["id"] not in self.created
                    and row["_kind"] not in NO_COMMON_FIELDS):
                row["version"] = row.get("version", 1) + 1
                row["updated_at"] = db.clock
        return row

    def new(self, kind, fields):
        row = db.create(kind, fields)
        self.created.add(row["id"])
        return row

    def flush(self):
        """Retained as the explicit end-of-request marker.

        Every bump is already applied by :meth:`touch`, which is what the
        PRD 2.11 mutate-then-reject rungs need: the writes they made -- the
        version counters included -- are already durable when the error is
        raised, so nothing has to be replayed here.
        """
        return None


def peek_json():
    """Body peek used by gates that run BEFORE G8 (a regulatory check may need a
    body instant).  It never raises: a malformed body is left for G8 to answer."""
    try:
        return _read_json()
    except ApiError:
        return {}


def _read_json():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    return parsed


class Endpoint(object):
    def __init__(self, method, path, roles, handler, code=200, path_params=None,
                 scope=None, read=False, filters=None, paginated=False,
                 g5=None, g6=None, occ=None, fields=None, g8_post=None):
        self.method = method
        self.path = path
        self.roles = roles
        self.handler = handler
        self.code = code
        self.path_params = path_params or []
        self.scope = scope
        self.read = read
        self.filters = filters or []
        self.paginated = paginated
        self.g5 = g5
        self.g6 = g6
        self.occ = occ
        self.fields = fields or []
        self.g8_post = g8_post


REGISTRY = []


def endpoint(method, path, roles, **kwargs):
    def decorate(fn):
        REGISTRY.append(Endpoint(method, path, roles, fn, **kwargs))
        return fn
    return decorate


def run_endpoint(ep, path_values):
    # ---- G1 authentication ------------------------------------------------
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognised identity headers.")

    # ---- G2 role ----------------------------------------------------------
    if role not in ep.roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not use this endpoint." % role)

    ctx = Ctx(role, user_id, request.args)

    # ---- G3 path existence (left to right) --------------------------------
    for name, kind in ep.path_params:
        row = db.get(kind, path_values.get(name))
        if row is None:
            raise ApiError(KIND_NOT_FOUND[kind])
        ctx.path[name] = row

    # ---- G4 actor scope ---------------------------------------------------
    if ep.scope is not None:
        ep.scope(ctx)

    if ep.read:
        # Read endpoints run G1, G2, G3, G4 and G8_QUERY only.
        if ep.paginated:
            from serialize import dump_all
            rows = ep.handler(ctx)
            rows = apply_filters(rows, ctx.args, ep.filters)
            page, meta = paginate(rows, ctx.args)
            return dump_all(page), meta
        return ep.handler(ctx), None

    # ---- G5 entity state --------------------------------------------------
    if ep.g5 is not None:
        ep.g5(ctx)

    # ---- G6 regulatory ----------------------------------------------------
    if ep.g6 is not None:
        ep.g6(ctx)

    ctx.raw_body = _read_json()

    # ---- G7 optimistic concurrency ----------------------------------------
    if ep.occ is not None:
        field_name, error_id, parent_of = ep.occ
        raw = ctx.raw_body.get(field_name) if isinstance(ctx.raw_body, dict) else None
        if isinstance(raw, int) and not isinstance(raw, bool):
            parent = parent_of(ctx)
            if parent is not None and raw != parent.get("version"):
                raise ApiError(error_id, "Stale version.")

    # ---- G8 payload -------------------------------------------------------
    ctx.body = validate_body(ep.fields, ctx.raw_body)
    if ep.g8_post is not None:
        ep.g8_post(ctx)

    # ---- G9 business + side effects ---------------------------------------
    try:
        result = ep.handler(ctx)
    except ApiError as err:
        if err.persist:
            ctx.flush()
        raise
    ctx.flush()
    return result, None
