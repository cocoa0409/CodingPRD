"""Shared infrastructure: in-memory store, logical clock, errors, envelope, auth."""
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

API_PREFIX = "/battery-warranty"

R_ADMIN = "ProgramAdmin"
R_ADJ = "WarrantyAdjudicator"
R_TECH = "ServiceTechnician"
R_GATEWAY = "TelematicsGateway"
R_OWNER = "VehicleOwner"
R_LAB = "IndependentLab"
R_REG = "RegulatoryLiaison"

ALL_ROLES = (R_ADMIN, R_ADJ, R_TECH, R_GATEWAY, R_OWNER, R_LAB, R_REG)
# Every GET is open to all roles except TelematicsGateway.
READ_ROLES = (R_ADMIN, R_ADJ, R_TECH, R_OWNER, R_LAB, R_REG)
READ_ROLES_GW = ALL_ROLES

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def invalid(msg="Request payload failed validation."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.programs = {}
        self.vehicles = {}
        self.packs = {}
        self.modules = {}
        self.snapshots = {}
        self.assessments = {}
        self.centers = {}
        self.technicians = {}
        self.claims = {}
        self.events = {}
        self.campaigns = {}
        self.consents = {}
        self.disputes = {}
        self.shipments = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------- time helpers
def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    """The logical clock -- the only notion of 'now' in this service."""
    return db.clock


# ------------------------------------------------------------ decimal helpers
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ record plumbing
def new_record():
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def event_record():
    """A record that carries only id + created_at (TelematicsSnapshot)."""
    return {"id": str(uuid.uuid4()), "_seq": db.next_seq(), "created_at": now()}


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------- output shape
def _out(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_out(v) for v in value]
    if isinstance(value, tuple):
        return [_out(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _out(v)) for k, v in value.items() if not k.startswith("_"))
    return value


def serialize(rec):
    return _out(rec)


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data)}
    return jsonify(body), status


def ok_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": [serialize(r) for r in rows]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ----------------------------------------------------------------------- auth
def auth(allowed_roles, actor_required=False):
    """Priority 1 -> 2 -> 3 of the global precedence ladder."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognised X-User-Role.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s may not perform this operation." % role)
    user_id = request.headers.get("X-User-ID")
    if user_id is not None and user_id.strip() == "":
        user_id = None
    if actor_required and user_id is None:
        raise ApiError("ERR_ACTOR_REQUIRED", 400, "X-User-ID is required for this operation.")
    return role, user_id


def forbidden(msg="Caller is not the owner of this record."):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


# ------------------------------------------------------------------ list/page
def pagination():
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid("limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer.")
        if offset < 0:
            raise invalid("offset must be zero or greater.")
    return limit, offset


def page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ------------------------------------------------------------ body validation
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise invalid("Request body must be a JSON object.")
    if not isinstance(body, dict):
        raise invalid("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, allow_empty=False):
    if not present(body, name):
        raise invalid("%s is required." % name)
    value = body[name]
    if not isinstance(value, str):
        raise invalid("%s must be a string." % name)
    if not allow_empty and value.strip() == "":
        raise invalid("%s must not be blank." % name)
    return value


def opt_str(body, name, default=None, allow_empty=False):
    if not present(body, name):
        return default
    return req_str(body, name, allow_empty=allow_empty)


def req_int(body, name, minimum=None, maximum=None):
    if not present(body, name):
        raise invalid("%s is required." % name)
    return _as_int(body[name], name, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return _as_int(body[name], name, minimum, maximum)


def _as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be at most %s." % (name, maximum))
    return value


def req_dec(body, name, places, minimum=None, maximum=None, exclusive_min=None):
    if not present(body, name):
        raise invalid("%s is required." % name)
    return _as_dec(body[name], name, places, minimum, maximum, exclusive_min)


def opt_dec(body, name, places, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not present(body, name):
        return default
    return _as_dec(body[name], name, places, minimum, maximum, exclusive_min)


def _as_dec(value, name, places, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise invalid("%s must be a number." % name)
    # `places is None` means the PRD declares no scale for this field, so the
    # supplied precision is preserved verbatim.
    dec = D(value) if places is None else rhu(value, places)
    if minimum is not None and dec < D(minimum):
        raise invalid("%s must be at least %s." % (name, minimum))
    if maximum is not None and dec > D(maximum):
        raise invalid("%s must be at most %s." % (name, maximum))
    if exclusive_min is not None and dec <= D(exclusive_min):
        raise invalid("%s must be greater than %s." % (name, exclusive_min))
    return dec


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean." % name)
    return value


def req_dt(body, name):
    if not present(body, name):
        raise invalid("%s is required." % name)
    dt = parse_dt(body[name])
    if dt is None:
        raise invalid("%s must be an ISO-8601 timestamp." % name)
    return dt


def opt_dt(body, name, default=None):
    if not present(body, name):
        return default
    return req_dt(body, name)


def opt_id(body, name):
    if not present(body, name):
        return None
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("%s must be a string identifier." % name)
    return value


def req_int_list(body, name):
    """Optional array-of-integer input; absent -> []."""
    if not present(body, name):
        return []
    value = body[name]
    if not isinstance(value, list):
        raise invalid("%s must be an array of integers." % name)
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise invalid("%s must be an array of integers." % name)
        out.append(item)
    return out


def req_str_list(body, name):
    if not present(body, name):
        return []
    value = body[name]
    if not isinstance(value, list):
        raise invalid("%s must be an array of strings." % name)
    for item in value:
        if not isinstance(item, str):
            raise invalid("%s must be an array of strings." % name)
    return list(value)


# -------------------------------------------------------------- lookup by id
NOT_FOUND = {
    "programs": ("ERR_PROGRAM_NOT_FOUND", "Warranty program"),
    "vehicles": ("ERR_VEHICLE_NOT_FOUND", "Vehicle"),
    "packs": ("ERR_PACK_NOT_FOUND", "Battery pack"),
    "centers": ("ERR_CENTER_NOT_FOUND", "Service center"),
    "technicians": ("ERR_TECHNICIAN_NOT_FOUND", "Technician"),
    "assessments": ("ERR_ASSESSMENT_NOT_FOUND", "SoH assessment"),
    "claims": ("ERR_CLAIM_NOT_FOUND", "Warranty claim"),
    "events": ("ERR_EVENT_NOT_FOUND", "Thermal event"),
    "campaigns": ("ERR_CAMPAIGN_NOT_FOUND", "Remediation campaign"),
    "consents": ("ERR_CONSENT_NOT_FOUND", "Remediation consent"),
    "disputes": ("ERR_DISPUTE_NOT_FOUND", "Capacity dispute"),
    "shipments": ("ERR_SHIPMENT_NOT_FOUND", "Pack shipment"),
}


def must(collection_name, record_id):
    error_id, label = NOT_FOUND[collection_name]
    table = getattr(db, collection_name)
    if record_id is None or record_id not in table:
        raise ApiError(error_id, 404, "%s %s was not found." % (label, record_id))
    return table[record_id]


def fk(collection_name, record_id):
    """Body foreign key: None passes through, unknown id raises the 404."""
    if record_id is None:
        return None
    return must(collection_name, record_id)


# ------------------------------------------------------------ child accessors
def pack_modules(pack_id):
    rows = [m for m in db.modules.values() if m["pack_id"] == pack_id]
    return sorted(rows, key=lambda m: m["position_index"])


def vehicle_snapshots(vehicle_id):
    return by_created([s for s in db.snapshots.values() if s["vehicle_id"] == vehicle_id])


def center_technicians(center_id):
    return by_created([t for t in db.technicians.values() if t["service_center_id"] == center_id])


def claim_disputes(claim_id):
    return by_created([d for d in db.disputes.values() if d["claim_id"] == claim_id])


def vehicle_claims(vehicle_id):
    return by_created([c for c in db.claims.values() if c["vehicle_id"] == vehicle_id])


def pack_thermal_events(pack_id):
    return by_created([e for e in db.events.values() if e["pack_id"] == pack_id])


def vehicle_thermal_events(vehicle_id):
    return by_created([e for e in db.events.values() if e["vehicle_id"] == vehicle_id])


def campaign_consents(campaign_id):
    return by_created([c for c in db.consents.values() if c["campaign_id"] == campaign_id])


def vehicle_consents(vehicle_id):
    return by_created([c for c in db.consents.values() if c["vehicle_id"] == vehicle_id])


def vehicle_assessments(vehicle_id):
    return by_created([a for a in db.assessments.values() if a["vehicle_id"] == vehicle_id])


CERT_RANK = {"L1": 1, "L2": 2, "L3": 3}


def refresh_technician(tech):
    """Technician.status is derived on every read against the logical clock."""
    tech["status"] = "CERT_LAPSED" if tech["cert_expires_at"] <= now() else "ACTIVE"
    return tech


def program_for_vehicle(vehicle):
    return db.programs[vehicle["warranty_program_id"]]
