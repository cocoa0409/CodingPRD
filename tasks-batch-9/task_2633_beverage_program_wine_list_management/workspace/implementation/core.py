"""Core infrastructure: logical clock, in-memory store, errors, envelope, auth, validation."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from flask import jsonify, request

API_PREFIX = "/beverage-program"

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

ROLES = (
    "BeverageDirector",
    "VenueSommelier",
    "DistributorRep",
    "Controller",
    "ComplianceOfficer",
)
ALL_ROLES = list(ROLES)

WINE_CATEGORIES = ["SPARKLING", "WHITE", "ROSE", "RED", "DESSERT", "FORTIFIED"]

BTG_SPOILAGE_ALLOWANCE_POURS = 1
EVENT_POUR_SIZE_ML = 100
EVENT_TURNOVER_BUFFER_MINUTES = 120
MAX_REVISION_ROUNDS = 3
REPRINT_THRESHOLD_ENTRIES = 2
MAX_PRESERVATION_HOURS = 720
LARGE_PARTY_THRESHOLD = 8
LARGE_PARTY_CORKAGE_DISCOUNT_PCT = Decimal("25.0")
PAR_URGENT_FRACTION = Decimal("0.5")
VARIANCE_RESTRICTED_PCT = Decimal("3.00")
VARIANCE_FROZEN_PCT = Decimal("6.00")

PRESERVATION_BASE_HOURS = {
    "SPARKLING": 24,
    "WHITE": 72,
    "ROSE": 72,
    "RED": 96,
    "DESSERT": 168,
    "FORTIFIED": 336,
}
PRESERVATION_METHOD_FACTOR = {
    "ARGON": Decimal("2.0"),
    "VACUUM": Decimal("1.0"),
    "COOLER": Decimal("1.5"),
    "NONE": Decimal("0.5"),
}

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VENUE_SCOPE_VIOLATION": 403,
    "ERR_DISTRIBUTOR_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_DISTRIBUTOR_NOT_FOUND": 404,
    "ERR_WINE_NOT_FOUND": 404,
    "ERR_BIN_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_DEPLETION_ENTRY_NOT_FOUND": 404,
    "ERR_WINE_LIST_NOT_FOUND": 404,
    "ERR_LIST_VERSION_NOT_FOUND": 404,
    "ERR_LIST_ENTRY_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_WRITE_OFF_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_POUR_SIZE_REQUIRED": 400,
    "ERR_INVALID_EVENT_WINDOW": 422,
    "ERR_INVALID_PERIOD": 422,
    # uniqueness
    "ERR_VENUE_CODE_TAKEN": 409,
    "ERR_BIN_CODE_TAKEN": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_DUPLICATE_LIST_ENTRY_WINE": 409,
    # concurrency
    "ERR_STALE_VERSION": 412,
    # state
    "ERR_LIST_VERSION_NOT_DRAFT": 409,
    "ERR_LIST_VERSION_NOT_IN_REVIEW": 409,
    "ERR_LIST_VERSION_NOT_REPRINT_PENDING": 409,
    "ERR_LIST_VERSION_NOT_PUBLISHED": 409,
    "ERR_OFFER_NOT_OPEN": 409,
    "ERR_CLAIM_NOT_GRANTED": 409,
    "ERR_CLAIM_NOT_WITHDRAWABLE": 409,
    "ERR_LOT_NOT_ON_HAND": 409,
    "ERR_SLOT_NOT_OPEN": 409,
    "ERR_WRITE_OFF_NOT_SUBMITTED": 409,
    "ERR_WRITE_OFF_NOT_APPROVED": 409,
    "ERR_EVENT_INVALID_STATE": 409,
    "ERR_INVESTIGATION_NOT_ACTIONABLE": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_EMPTY_LIST_VERSION": 422,
    # business safety
    "ERR_DISTRIBUTOR_COMPLIANCE_HOLD": 422,
    "ERR_OFFER_COMPLIANCE_BLOCKED": 422,
    "ERR_BYO_CATEGORY_PROHIBITED": 422,
    # business temporal
    "ERR_OFFER_DEADLINE_PASSED": 422,
    "ERR_RECEIVED_AT_IN_FUTURE": 422,
    "ERR_SLOT_OCCUPIED": 409,
    "ERR_EVENT_WINDOW_CONFLICT": 409,
    # business referential
    "ERR_LOT_VENUE_MISMATCH": 422,
    "ERR_SLOT_WINE_MISMATCH": 422,
    "ERR_ENTRY_NOT_BY_THE_GLASS": 422,
    "ERR_POUR_PLAN_ENTRY_MISMATCH": 422,
    "ERR_SLOT_WRITE_OFF_INVALID": 422,
    "ERR_PINNED_LIST_VERSION_STALE": 409,
    # business constraint
    "ERR_BIN_ZONE_MISMATCH": 422,
    "ERR_BIN_CAPACITY_EXCEEDED": 409,
    "ERR_REQUEST_EXCEEDS_OFFER": 422,
    "ERR_NO_ELIGIBLE_CLAIMS": 422,
    "ERR_POUR_SIZE_TOO_LARGE": 422,
    "ERR_POURS_EXCEED_BOTTLE": 422,
    "ERR_BYO_LIMIT_EXCEEDED": 422,
    # business fiscal
    "ERR_VENUE_PROGRAM_FROZEN": 409,
    "ERR_VENUE_PROGRAM_RESTRICTED": 409,
    "ERR_INSUFFICIENT_BOTTLES": 409,
    "ERR_NO_REVENUE_IN_PERIOD": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    text = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % text


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Numeric helpers (money is always integer cents; rounding is always half-up)
# ---------------------------------------------------------------------------
def D(value):
    """Decimal from anything without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """round half up to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_to_multiple(value, multiple):
    """Raise to the next whole multiple; a value already on the multiple is untouched."""
    v = D(value)
    m = D(multiple)
    return int((v / m).to_integral_value(rounding=ROUND_CEILING) * m)


def floor_div_dec(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_dec(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant; returns tz-aware UTC datetime truncated to ms, or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


# ---------------------------------------------------------------------------
# In-memory store. Starts completely empty on every process boot; nothing is
# ever seeded, preloaded or hardcoded here.
# ---------------------------------------------------------------------------
COLLECTIONS = (
    "venues",
    "distributors",
    "wines",
    "allocation_offers",
    "allocation_claims",
    "cellar_bins",
    "inventory_lots",
    "depletion_entries",
    "wine_lists",
    "list_versions",
    "list_entries",
    "btg_slots",
    "spoilage_write_offs",
    "wine_dinner_events",
    "variance_investigations",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.seq = 0
        self.clock = parse_iso(DEFAULT_CLOCK_UTC)

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    """The logical clock. No business rule ever reads the wall clock."""
    return store.clock


def new_record(fields, common_fields=True):
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = store.clock
    if common_fields:
        rec["updated_at"] = store.clock
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    if "version" in rec:
        rec["updated_at"] = store.clock
        rec["version"] = rec["version"] + 1
    return rec


def _ser(value):
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _ser(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ser(v) for v in value]
    return value


def serialize(rec):
    return {k: _ser(v) for k, v in rec.items() if not k.startswith("_")}


def sort_default(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def sort_by(records, field):
    return sorted(records, key=lambda r: (r[field], r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def respond_object(data, status=200, page_meta=None):
    meta = _meta()
    if page_meta:
        meta.update(page_meta)
    body = {"meta": meta, "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, page_meta, status=200):
    meta = _meta()
    meta.update(page_meta)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Authentication / authorization (PRD 2.1 and 2.8 steps 1-5)
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    return user_id, role


def authorize(*allowed_roles):
    user_id, role = authenticate()
    allowed = []
    for entry in allowed_roles:
        if isinstance(entry, (list, tuple)):
            allowed.extend(entry)
        else:
            allowed.append(entry)
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s is not authorised for this operation." % role)
    return user_id, role


def check_venue_scope(role, user_id, venue_id):
    """A VenueSommelier may only act on the venue whose id is its X-User-ID."""
    if role == "VenueSommelier" and venue_id is not None and str(venue_id) != str(user_id):
        fail("ERR_VENUE_SCOPE_VIOLATION", "This sommelier is scoped to another venue.")


def check_distributor_scope(role, user_id, distributor_id):
    if role == "DistributorRep" and distributor_id is not None and str(distributor_id) != str(user_id):
        fail("ERR_DISTRIBUTOR_SCOPE_VIOLATION", "This representative is scoped to another distributor.")


# ---------------------------------------------------------------------------
# Body parsing and the ordered validation passes (PRD 2.8 steps 8-10)
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "datetime":
        return isinstance(value, str) and parse_iso(value) is not None
    return True


def validate_body(body, spec):
    """spec entries: dict(name, type, required=False, enum=None, min=None, max=None,
    min_len=None, max_len=None). Passes run in the PRD's pinned order: presence and
    JSON type first, then enum membership, then declared ranges."""
    for field in spec:
        name = field["name"]
        present = name in body and body[name] is not None
        if field.get("required") and not present:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        if present and not _type_ok(body[name], field["type"]):
            fail("ERR_INVALID_REQUEST", "Field '%s' has the wrong type." % name)
    for field in spec:
        name = field["name"]
        if field.get("enum") and name in body and body[name] is not None:
            if body[name] not in field["enum"]:
                fail("ERR_INVALID_ENUM_VALUE", "Field '%s' carries an undeclared value." % name)
    for field in spec:
        name = field["name"]
        if name not in body or body[name] is None:
            continue
        value = body[name]
        if field.get("min") is not None and D(value) < D(field["min"]):
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is below its minimum." % name)
        if field.get("max") is not None and D(value) > D(field["max"]):
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is above its maximum." % name)
        if field.get("min_len") is not None and len(value) < field["min_len"]:
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is shorter than allowed." % name)
        if field.get("max_len") is not None and len(value) > field["max_len"]:
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is longer than allowed." % name)


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be a non-negative integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be non-negative.")
    return limit, offset


def paginate(records):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return str(raw).strip().lower() in ("true", "1", "yes")


def q(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


# ---------------------------------------------------------------------------
# Lookup helpers (path ids resolve left to right; each type has its own error)
# ---------------------------------------------------------------------------
def _lookup(collection, ident, error_id):
    rec = getattr(store, collection).get(ident)
    if rec is None:
        fail(error_id)
    return rec


def get_venue(ident):
    return _lookup("venues", ident, "ERR_VENUE_NOT_FOUND")


def get_distributor(ident):
    return _lookup("distributors", ident, "ERR_DISTRIBUTOR_NOT_FOUND")


def get_wine(ident):
    return _lookup("wines", ident, "ERR_WINE_NOT_FOUND")


def get_bin(ident):
    return _lookup("cellar_bins", ident, "ERR_BIN_NOT_FOUND")


def get_offer(ident):
    return _lookup("allocation_offers", ident, "ERR_OFFER_NOT_FOUND")


def get_claim(ident):
    return _lookup("allocation_claims", ident, "ERR_CLAIM_NOT_FOUND")


def get_lot(ident):
    return _lookup("inventory_lots", ident, "ERR_LOT_NOT_FOUND")


def get_depletion_entry(ident):
    return _lookup("depletion_entries", ident, "ERR_DEPLETION_ENTRY_NOT_FOUND")


def get_wine_list(ident):
    return _lookup("wine_lists", ident, "ERR_WINE_LIST_NOT_FOUND")


def get_list_version(ident):
    return _lookup("list_versions", ident, "ERR_LIST_VERSION_NOT_FOUND")


def get_list_entry(ident):
    return _lookup("list_entries", ident, "ERR_LIST_ENTRY_NOT_FOUND")


def get_slot(ident):
    return _lookup("btg_slots", ident, "ERR_SLOT_NOT_FOUND")


def get_write_off(ident):
    return _lookup("spoilage_write_offs", ident, "ERR_WRITE_OFF_NOT_FOUND")


def get_event(ident):
    return _lookup("wine_dinner_events", ident, "ERR_EVENT_NOT_FOUND")


def get_investigation(ident):
    return _lookup("variance_investigations", ident, "ERR_INVESTIGATION_NOT_FOUND")


def venue_of_list_version(version):
    wine_list = store.wine_lists.get(version["wine_list_id"])
    if wine_list is None:
        return None
    return wine_list["venue_id"]


def venue_of_list_entry(entry):
    version = store.list_versions.get(entry["list_version_id"])
    if version is None:
        return None
    return venue_of_list_version(version)
