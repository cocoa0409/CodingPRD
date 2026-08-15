"""Livestock Health Certificate & Interstate Movement API.

In-memory Flask implementation. Single module by design: the domain is a web of
cross-entity cascades that is far easier to keep correct when every rule lives
in one place.
"""

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_START}


def clock_now():
    return _clock["now"]


# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; tests construct all state)
# ---------------------------------------------------------------------------

db = {
    "premises": {},
    "veterinarians": {},
    "entry_requirements": {},
    "test_records": {},
    "certificates": {},
    "movement_permits": {},
    "movement_records": {},
    "outbreak_zones": {},
    "quarantine_orders": {},
    "transmission_audits": {},
}

_seq = {"cvi": 0, "permit": 0}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPECIES = {"CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"}
TEST_TYPES = {"BRUCELLOSIS", "TUBERCULOSIS", "EIA", "PULLORUM"}
TEST_TYPES_WITH_NONE = TEST_TYPES | {"NONE"}
DISEASE_CODES = {
    "AVIAN_INFLUENZA", "BRUCELLOSIS", "TUBERCULOSIS", "EIA",
    "PULLORUM", "VESICULAR_STOMATITIS", "PSEUDORABIES",
}
SEVERITIES = {"LOW", "MODERATE", "HIGH"}
DISEASE_STATUSES = {"ACCREDITED_FREE", "MONITORED", "QUARANTINE_HOLD", "INFECTED"}
CHANNELS = {"XML_GATEWAY", "EMAIL", "PORTAL"}
ROLES = {"ProgramAdmin", "StateVetOfficer", "AccreditedVet", "LabTechnician", "StateAuditor"}

FEE_BASE_CENTS = 2500
FEE_CAP_CENTS = 20000
MONITORED_SURCHARGE_CENTS = 1000
PER_HEAD_RATE_CENTS = {
    "CATTLE": 150, "SWINE": 90, "POULTRY": 25, "SHEEP_GOAT": 60, "EQUINE": 200,
}
PER_HEAD_MOVEMENT_RATE_CENTS = {
    "CATTLE": Decimal("137.5"), "SWINE": Decimal("62.5"),
    "POULTRY": Decimal("10.25"), "SHEEP_GOAT": Decimal("45.5"),
    "EQUINE": Decimal("210.75"),
}
CVI_VALIDITY_DAYS = 30
QUARANTINE_AUTO_DAYS = 30
QUARANTINE_MIN_GAP_DAYS = 14

# Test type -> disease code for the auto-quarantine cascade.
TEST_TYPE_TO_DISEASE = {
    "BRUCELLOSIS": "BRUCELLOSIS",
    "TUBERCULOSIS": "TUBERCULOSIS",
    "EIA": "EIA",
    "PULLORUM": "PULLORUM",
}

ALL_READ_ROLES = ["ProgramAdmin", "StateVetOfficer", "AccreditedVet", "LabTechnician", "StateAuditor"]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (400, "X-User-ID or X-User-Role header missing or empty"),
    "ERR_FORBIDDEN": (403, "Role not permitted for this endpoint"),
    "ERR_NOT_CERTIFICATE_OWNER": (403, "Acting vet is not the certificate's vet of record"),
    "ERR_VALIDATION": (400, "Malformed request body"),
    "ERR_PREMISES_NOT_FOUND": (404, "Premises not found"),
    "ERR_VETERINARIAN_NOT_FOUND": (404, "Veterinarian not found"),
    "ERR_ENTRY_REQUIREMENT_NOT_FOUND": (404, "Entry requirement not found"),
    "ERR_TEST_RECORD_NOT_FOUND": (404, "Test record not found"),
    "ERR_CERTIFICATE_NOT_FOUND": (404, "Certificate not found"),
    "ERR_PERMIT_NOT_FOUND": (404, "Movement permit not found"),
    "ERR_MOVEMENT_RECORD_NOT_FOUND": (404, "Movement record not found"),
    "ERR_OUTBREAK_ZONE_NOT_FOUND": (404, "Outbreak zone not found"),
    "ERR_QUARANTINE_ORDER_NOT_FOUND": (404, "Quarantine order not found"),
    "ERR_TRANSMISSION_AUDIT_NOT_FOUND": (404, "Transmission audit not found"),
    "ERR_CERTIFICATE_NOT_SUBMITTABLE": (409, "Certificate is not in DRAFT"),
    "ERR_CERTIFICATE_NOT_PENDING_REVIEW": (409, "Certificate is not in PENDING_REVIEW"),
    "ERR_CERTIFICATE_NOT_REVISABLE": (409, "Certificate is not in REJECTED"),
    "ERR_CERTIFICATE_NOT_VOIDABLE": (409, "Certificate is not voidable"),
    "ERR_CERTIFICATE_NOT_TRANSMITTABLE": (409, "Certificate is not transmittable"),
    "ERR_PERMIT_NOT_ISSUABLE": (409, "Permit is not issuable"),
    "ERR_PERMIT_NOT_ADJUSTABLE": (409, "Permit is not adjustable"),
    "ERR_PERMIT_NOT_ISSUED": (409, "Permit is not ISSUED"),
    "ERR_MOVEMENT_NOT_ADVANCEABLE": (409, "Movement record cannot advance from its state"),
    "ERR_ZONE_INVALID_TRANSITION": (409, "Outbreak zone invalid transition"),
    "ERR_QUARANTINE_NOT_ACTIVE": (409, "Quarantine order is not ACTIVE"),
    "ERR_TRANSMISSION_NOT_ADVANCEABLE": (409, "Transmission audit is not QUEUED"),
    "ERR_TEST_RECORD_NOT_PENDING": (409, "Test record result already resolved"),
    "ERR_PREMISES_NOT_ACCREDITABLE": (409, "Premises is not accreditable"),
    "ERR_VET_NOT_SUSPENDABLE": (409, "Veterinarian is not ACTIVE"),
    "ERR_VET_NOT_CURRENT": (422, "Acting veterinarian credential is not current"),
    "ERR_PREMISES_DISEASE_HOLD": (422, "Origin premises is under disease hold"),
    "ERR_TEST_NOT_QUALIFYING": (422, "Relied-upon test result is not NEGATIVE"),
    "ERR_OUTBREAK_MOVEMENT_RESTRICTION": (422, "An ACTIVE outbreak zone covers the origin"),
    "ERR_NO_ACTIVE_ENTRY_REQUIREMENT": (422, "No ACTIVE entry requirement covers the inspection date"),
    "ERR_PREMISES_SPECIES_MISMATCH": (422, "Species does not match the premises' species"),
    "ERR_TEST_RECORD_MISMATCH": (422, "Test record does not match premises, species, or matrix test type"),
    "ERR_TEST_VALIDITY_EXPIRED": (422, "Test age exceeds matrix validity"),
    "ERR_VACCINATION_WINDOW_VIOLATION": (422, "Vaccination window violation"),
    "ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY": (422, "Permit window outside certificate validity"),
    "ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW": (422, "Movement instant outside permit window"),
    "ERR_HEAD_COUNT_EXCEEDS_INVENTORY": (422, "Head count exceeds premises inventory"),
    "ERR_PERMIT_HEADROOM_EXCEEDED": (422, "Head count exceeds permit committed headroom"),
    "ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT": (422, "Allocation below certificate head count"),
    "ERR_ALLOCATION_BELOW_CONSUMED": (422, "Allocation below already-consumed head count"),
    "ERR_ZONE_WINDOW_OVERLAP": (409, "Zone window overlaps another non-terminal zone"),
    "ERR_REQUIREMENT_WINDOW_OVERLAP": (409, "Requirement window overlaps another ACTIVE row"),
    "ERR_QUARANTINE_WINDOW_CONFLICT": (409, "Quarantine window overlaps an ACTIVE order"),
    "ERR_QUARANTINE_MIN_GAP_VIOLATION": (422, "Quarantine minimum 14-day gap violated"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The issuing officer may not lift their own order"),
    "ERR_STALE_PERMIT_VERSION": (412, "Stale permit version"),
    "ERR_STALE_REQUIREMENT_VERSION": (412, "Stale requirement version"),
}


def raise_err(error_id, message=None):
    status, default_msg = ERRORS[error_id]
    raise ApiError(error_id, status, message or default_msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _ts_instant(dt):
    """ISO 8601 UTC at second precision (logical-clock-derived timestamps).

    The PRD pins three fractional digits only for `api_request_timestamp`,
    `created_at`, and `updated_at`. All other timestamps are described as
    "ISO 8601 UTC instants" of the logical clock, and PRD §2.4 spells the
    clock's initial value without fractional digits (2026-08-01T00:00:00Z).
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def success(data, http_status=200, is_list=False, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _ts(clock_now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(clock_now()),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(clock_now()),
        },
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Unknown route"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(clock_now()),
        },
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def get_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise_err("ERR_FORBIDDEN")
    return user_id, role


# ---------------------------------------------------------------------------
# Field parsing / validation helpers
# ---------------------------------------------------------------------------


def get_body(required=False):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise_err("ERR_VALIDATION", "Request body must be JSON")
        body = {}
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None:
        raise_err("ERR_VALIDATION", f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        raise_err("ERR_VALIDATION", f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", f"Field {field} must be a string")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise_err("ERR_VALIDATION", f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        raise_err("ERR_VALIDATION", f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_VALIDATION", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise_err("ERR_VALIDATION", f"Field {field} must be >= {minimum}")
    return v


def opt_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_VALIDATION", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise_err("ERR_VALIDATION", f"Field {field} must be >= {minimum}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None:
        raise_err("ERR_VALIDATION", f"Missing required field: {field}")
    if not isinstance(v, bool):
        raise_err("ERR_VALIDATION", f"Field {field} must be a boolean")
    return v


def opt_bool(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise_err("ERR_VALIDATION", f"Field {field} must be a boolean")
    return v


def parse_dt(value, field):
    if not isinstance(value, str):
        raise_err("ERR_VALIDATION", f"Field {field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err("ERR_VALIDATION", f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(body, field):
    v = body.get(field)
    if v is None:
        raise_err("ERR_VALIDATION", f"Missing required field: {field}")
    return parse_dt(v, field)


def opt_dt(body, field):
    v = body.get(field)
    if v is None:
        return None
    return parse_dt(v, field)


def whole_days_between(earlier, later):
    """floor((later - earlier) / 86400)."""
    return (later - earlier).total_seconds() // 86400


def overlaps_half_open(a_from, a_until, b_from, b_until):
    """Half-open [from, until) overlap; until=None means open-ended."""
    a_end = a_until if a_until is not None else datetime.max.replace(tzinfo=timezone.utc)
    b_end = b_until if b_until is not None else datetime.max.replace(tzinfo=timezone.utc)
    return a_from < b_end and b_from < a_end


def closed_overlaps(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------


def new_entity():
    now = clock_now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = clock_now()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Lazy materialization
# ---------------------------------------------------------------------------


def materialize_certificate(cert):
    """Lazy LAPSED: ISSUED/TRANSMITTED/ENTRY_BLOCKED -> LAPSED when clock > valid_until."""
    if cert["status"] in ("ISSUED", "TRANSMITTED", "ENTRY_BLOCKED"):
        vu = cert.get("valid_until")
        if vu is not None and clock_now() > vu:
            cert["status"] = "LAPSED"
            if cert.get("pre_block_status") is not None:
                cert["pre_block_status"] = None
            touch(cert)


def reevaluate_premises_after_hold_release(premises):
    """After a quarantine/order/zone hold goes away: restore MONITORED if no hold remains."""
    if premises["disease_status"] != "QUARANTINE_HOLD":
        return
    # another ACTIVE quarantine order on (premises, species)?
    for q in db["quarantine_orders"].values():
        materialize_quarantine(q)
        if (q["status"] == "ACTIVE" and q["premises_id"] == premises["id"]
                and q["species_code"] == premises["species_code"]):
            return
    # an ACTIVE outbreak zone covering (county, species) at the logical clock?
    if zone_covers_premises(premises):
        return
    premises["disease_status"] = "MONITORED"
    touch(premises)


def materialize_quarantine(order):
    """Lazy EXPIRED: ACTIVE -> EXPIRED when clock > end_at, then re-evaluate premises."""
    if order["status"] == "ACTIVE" and clock_now() > order["end_at"]:
        order["status"] = "EXPIRED"
        touch(order)
        premises = db["premises"].get(order["premises_id"])
        if premises is not None:
            reevaluate_premises_after_hold_release(premises)


def materialize_premises_quarantines(premises):
    for q in db["quarantine_orders"].values():
        if q["premises_id"] == premises["id"]:
            materialize_quarantine(q)


# ---------------------------------------------------------------------------
# Zone coverage helpers
# ---------------------------------------------------------------------------


def zone_window_covers_now(zone):
    now = clock_now()
    if now < zone["effective_from"]:
        return False
    if zone["effective_until"] is not None and now >= zone["effective_until"]:
        return False
    return True


def active_zone_covers(county, species_code):
    for z in db["outbreak_zones"].values():
        if (z["status"] == "ACTIVE" and z["county"] == county
                and z["species_code"] == species_code and zone_window_covers_now(z)):
            return z
    return None


def zone_covers_premises(premises):
    return active_zone_covers(premises["county"], premises["species_code"]) is not None


# ---------------------------------------------------------------------------
# Inventory / headroom / fee computations
# ---------------------------------------------------------------------------


def compute_current_head_count(premises):
    total = premises["initial_head_count"]
    for mr in db["movement_records"].values():
        if mr["status"] not in ("IN_TRANSIT", "DELIVERED"):
            continue
        permit = db["movement_permits"].get(mr["permit_id"])
        if permit is None:
            continue
        cert = db["certificates"].get(permit["certificate_id"])
        if cert is None:
            continue
        if cert["origin_premises_id"] == premises["id"]:
            total -= mr["head_count"]
    return total


def permit_headrooms(permit):
    committed_used = 0
    projected_used = 0
    total_fees = 0
    for mr in db["movement_records"].values():
        if mr["permit_id"] != permit["id"]:
            continue
        if mr["status"] in ("SCHEDULED", "IN_TRANSIT", "DELIVERED"):
            committed_used += mr["head_count"]
            total_fees += mr["movement_fee_cents"]
        if mr["status"] in ("IN_TRANSIT", "DELIVERED"):
            projected_used += mr["head_count"]
    return (
        permit["allocated_head_count"] - committed_used,
        permit["allocated_head_count"] - projected_used,
        total_fees,
    )


def issuance_fee_cents(cert, premises):
    rate = PER_HEAD_RATE_CENTS[cert["species_code"]]
    surcharge = MONITORED_SURCHARGE_CENTS if premises["disease_status"] == "MONITORED" else 0
    raw = FEE_BASE_CENTS + rate * cert["head_count"] + surcharge
    return min(FEE_CAP_CENTS, raw)


def movement_fee_cents(head_count, species_code):
    rate = PER_HEAD_MOVEMENT_RATE_CENTS[species_code]
    return int((rate * head_count).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Serializers (convert internal datetimes to wire format)
# ---------------------------------------------------------------------------

DT_FIELDS = {
    "premises": [],
    "veterinarians": ["accreditation_expires_at"],
    "entry_requirements": ["effective_from", "effective_until"],
    "test_records": ["test_date"],
    "certificates": ["inspection_date", "vaccination_date", "issued_at", "valid_until"],
    "movement_permits": ["valid_from", "valid_until"],
    "movement_records": ["planned_ship_date", "departed_at", "arrived_at"],
    "outbreak_zones": ["effective_from", "effective_until"],
    "quarantine_orders": ["start_at", "end_at"],
    "transmission_audits": ["acknowledged_at"],
}


def serialize(kind, entity):
    out = {}
    dt_fields = set(DT_FIELDS.get(kind, [])) | {"created_at", "updated_at"}
    for k, v in entity.items():
        if isinstance(v, datetime) or (k in dt_fields and v is None):
            if not isinstance(v, datetime):
                out[k] = None
            elif k in ("created_at", "updated_at"):
                out[k] = _ts(v)
            else:
                out[k] = _ts_instant(v)
        else:
            out[k] = v
    return out


def serialize_premises(p):
    out = serialize("premises", p)
    out["current_head_count"] = compute_current_head_count(p)
    return out


def serialize_veterinarian(v):
    out = serialize("veterinarians", v)
    out["is_credential_current"] = (
        v["status"] == "ACTIVE" and v["accreditation_expires_at"] >= clock_now()
    )
    return out


def serialize_permit(p):
    out = serialize("movement_permits", p)
    committed, projected, total_fees = permit_headrooms(p)
    out["committed_headroom"] = committed
    out["projected_headroom"] = projected
    out["total_movement_fees_cents"] = total_fees
    return out


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err("ERR_VALIDATION", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def sorted_entities(entities):
    return sorted(entities, key=lambda e: (e["created_at"], e["id"]))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get_premises(pid):
    p = db["premises"].get(pid)
    if p is None:
        raise_err("ERR_PREMISES_NOT_FOUND")
    return p


def get_veterinarian(vid):
    v = db["veterinarians"].get(vid)
    if v is None:
        raise_err("ERR_VETERINARIAN_NOT_FOUND")
    return v


def get_requirement(rid):
    r = db["entry_requirements"].get(rid)
    if r is None:
        raise_err("ERR_ENTRY_REQUIREMENT_NOT_FOUND")
    return r


def get_test_record(tid):
    t = db["test_records"].get(tid)
    if t is None:
        raise_err("ERR_TEST_RECORD_NOT_FOUND")
    return t


def get_certificate(cid):
    c = db["certificates"].get(cid)
    if c is None:
        raise_err("ERR_CERTIFICATE_NOT_FOUND")
    return c


def get_permit(pid):
    p = db["movement_permits"].get(pid)
    if p is None:
        raise_err("ERR_PERMIT_NOT_FOUND")
    return p


def get_movement_record(mid):
    m = db["movement_records"].get(mid)
    if m is None:
        raise_err("ERR_MOVEMENT_RECORD_NOT_FOUND")
    return m


def get_zone(zid):
    z = db["outbreak_zones"].get(zid)
    if z is None:
        raise_err("ERR_OUTBREAK_ZONE_NOT_FOUND")
    return z


def get_quarantine(qid):
    q = db["quarantine_orders"].get(qid)
    if q is None:
        raise_err("ERR_QUARANTINE_ORDER_NOT_FOUND")
    return q


def get_audit(aid):
    a = db["transmission_audits"].get(aid)
    if a is None:
        raise_err("ERR_TRANSMISSION_AUDIT_NOT_FOUND")
    return a


def acting_vet(user_id):
    """AccreditedVet identity must resolve to a Veterinarian row."""
    return get_veterinarian(user_id)


def vet_is_current(vet):
    return vet["status"] == "ACTIVE" and vet["accreditation_expires_at"] >= clock_now()


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ProgramAdmin")
    body = get_body(required=True)
    to_dt = req_dt(body, "to_iso8601")
    _clock["now"] = to_dt
    return success({"current_utc": _ts_instant(to_dt)}, 200)


# ---------------------------------------------------------------------------
# Premises
# ---------------------------------------------------------------------------


@app.route("/api/premises", methods=["POST"])
def create_premises():
    require_roles("ProgramAdmin")
    body = get_body(required=True)
    name = req_str(body, "name")
    county = req_str(body, "county")
    state_code = req_str(body, "state_code")
    species_code = req_enum(body, "species_code", SPECIES)
    initial_head_count = req_int(body, "initial_head_count", minimum=0)
    disease_status = body.get("disease_status", "MONITORED")
    if disease_status is not None and disease_status not in DISEASE_STATUSES:
        raise_err("ERR_VALIDATION", "disease_status out of range")
    if disease_status is None:
        disease_status = "MONITORED"

    ent = new_entity()
    ent.update({
        "name": name,
        "county": county,
        "state_code": state_code,
        "species_code": species_code,
        "initial_head_count": initial_head_count,
        "disease_status": disease_status,
    })
    db["premises"][ent["id"]] = ent
    return success(serialize_premises(ent), 201)


@app.route("/api/premises/<pid>", methods=["GET"])
def read_premises(pid):
    require_roles(*ALL_READ_ROLES)
    p = get_premises(pid)
    materialize_premises_quarantines(p)
    return success(serialize_premises(p), 200)


@app.route("/api/premises/<pid>/accredit", methods=["POST"])
def accredit_premises(pid):
    require_roles("StateVetOfficer")
    p = get_premises(pid)
    materialize_premises_quarantines(p)
    if p["disease_status"] != "MONITORED":
        raise_err("ERR_PREMISES_NOT_ACCREDITABLE")
    for q in db["quarantine_orders"].values():
        if (q["status"] == "ACTIVE" and q["premises_id"] == p["id"]
                and q["species_code"] == p["species_code"]):
            raise_err("ERR_PREMISES_NOT_ACCREDITABLE")
    p["disease_status"] = "ACCREDITED_FREE"
    touch(p)
    return success(serialize_premises(p), 200)


# ---------------------------------------------------------------------------
# Veterinarians
# ---------------------------------------------------------------------------


@app.route("/api/veterinarians", methods=["POST"])
def create_veterinarian():
    require_roles("ProgramAdmin")
    body = get_body(required=True)
    full_name = req_str(body, "full_name")
    accreditation_number = req_str(body, "accreditation_number")
    accreditation_expires_at = req_dt(body, "accreditation_expires_at")

    ent = new_entity()
    ent.update({
        "full_name": full_name,
        "accreditation_number": accreditation_number,
        "accreditation_expires_at": accreditation_expires_at,
        "status": "ACTIVE",
    })
    db["veterinarians"][ent["id"]] = ent
    return success(serialize_veterinarian(ent), 201)


@app.route("/api/veterinarians/<vid>/suspend", methods=["POST"])
def suspend_veterinarian(vid):
    require_roles("StateVetOfficer")
    v = get_veterinarian(vid)
    if v["status"] != "ACTIVE":
        raise_err("ERR_VET_NOT_SUSPENDABLE")
    v["status"] = "SUSPENDED"
    touch(v)
    return success(serialize_veterinarian(v), 200)


# ---------------------------------------------------------------------------
# Entry requirements
# ---------------------------------------------------------------------------


def requirement_window_overlaps(candidate, exclude_id=None):
    for r in db["entry_requirements"].values():
        if r["id"] == exclude_id:
            continue
        if r["status"] != "ACTIVE":
            continue
        if (r["destination_state_code"] == candidate["destination_state_code"]
                and r["species_code"] == candidate["species_code"]
                and r["test_type"] == candidate["test_type"]
                and overlaps_half_open(candidate["effective_from"], candidate["effective_until"],
                                       r["effective_from"], r["effective_until"])):
            return True
    return False


@app.route("/api/entry-requirements", methods=["POST"])
def create_entry_requirement():
    require_roles("ProgramAdmin")
    body = get_body(required=True)
    destination_state_code = req_str(body, "destination_state_code")
    species_code = req_enum(body, "species_code", SPECIES)
    test_type = req_enum(body, "test_type", TEST_TYPES_WITH_NONE)
    test_validity_days = req_int(body, "test_validity_days", minimum=1)
    vaccination_required = req_bool(body, "vaccination_required")
    vaccination_min_days = opt_int(body, "vaccination_min_days_before_inspection", minimum=0)
    if vaccination_min_days is None:
        vaccination_min_days = 0
    permit_required = req_bool(body, "permit_required")
    effective_from = req_dt(body, "effective_from")
    effective_until = opt_dt(body, "effective_until")
    if effective_until is not None and effective_until <= effective_from:
        raise_err("ERR_VALIDATION", "effective_until must be later than effective_from")

    ent = new_entity()
    ent.update({
        "destination_state_code": destination_state_code,
        "species_code": species_code,
        "test_type": test_type,
        "test_validity_days": test_validity_days,
        "vaccination_required": vaccination_required,
        "vaccination_min_days_before_inspection": vaccination_min_days,
        "permit_required": permit_required,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "ACTIVE",
    })
    if requirement_window_overlaps(ent):
        raise_err("ERR_REQUIREMENT_WINDOW_OVERLAP")
    db["entry_requirements"][ent["id"]] = ent
    return success(serialize("entry_requirements", ent), 201)


@app.route("/api/entry-requirements/<rid>", methods=["PATCH"])
def amend_entry_requirement(rid):
    require_roles("ProgramAdmin")
    body = get_body(required=True)
    r = get_requirement(rid)

    new_test_validity_days = opt_int(body, "test_validity_days", minimum=1)
    new_vaccination_required = opt_bool(body, "vaccination_required")
    new_vaccination_min_days = opt_int(body, "vaccination_min_days_before_inspection", minimum=0)
    new_permit_required = opt_bool(body, "permit_required")
    new_effective_until_provided = "effective_until" in body
    new_effective_until = opt_dt(body, "effective_until")

    if new_effective_until_provided and new_effective_until is not None \
            and new_effective_until <= r["effective_from"]:
        raise_err("ERR_VALIDATION", "effective_until must be later than effective_from")

    # Window-overlap re-evaluated when effective_until changes (before OCC per catalog order).
    if new_effective_until_provided:
        candidate = dict(r)
        candidate["effective_until"] = new_effective_until
        if requirement_window_overlaps(candidate, exclude_id=r["id"]):
            raise_err("ERR_REQUIREMENT_WINDOW_OVERLAP")

    expected = req_int(body, "expected_requirement_version")
    if expected != r["version"]:
        raise_err("ERR_STALE_REQUIREMENT_VERSION")

    if new_test_validity_days is not None:
        r["test_validity_days"] = new_test_validity_days
    if new_vaccination_required is not None:
        r["vaccination_required"] = new_vaccination_required
    if new_vaccination_min_days is not None:
        r["vaccination_min_days_before_inspection"] = new_vaccination_min_days
    if new_permit_required is not None:
        r["permit_required"] = new_permit_required
    if new_effective_until_provided:
        r["effective_until"] = new_effective_until
    touch(r)
    return success(serialize("entry_requirements", r), 200)


@app.route("/api/entry-requirements", methods=["GET"])
def list_entry_requirements():
    require_roles(*ALL_READ_ROLES)
    dest = request.args.get("destination_state_code")
    species = request.args.get("species_code")
    status = request.args.get("status")
    items = []
    for r in db["entry_requirements"].values():
        if dest is not None and r["destination_state_code"] != dest:
            continue
        if species is not None and r["species_code"] != species:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    items = sorted_entities(items)
    page, pagination = paginate(items)
    return success([serialize("entry_requirements", r) for r in page], 200,
                   is_list=True, pagination=pagination)


# ---------------------------------------------------------------------------
# Test records and the infection cascade
# ---------------------------------------------------------------------------


def auto_quarantine_disease_code(test_type):
    return TEST_TYPE_TO_DISEASE.get(test_type, test_type)


def active_quarantine_covers(premises_id, species_code):
    for q in db["quarantine_orders"].values():
        materialize_quarantine(q)
        if (q["status"] == "ACTIVE" and q["premises_id"] == premises_id
                and q["species_code"] == species_code):
            return True
    return False


def run_infection_cascade(premises, test_record):
    """POSITIVE result cascade, atomic within the request."""
    premises["disease_status"] = "INFECTED"
    touch(premises)

    # Auto-create a quarantine order unless an ACTIVE one already covers (premises, species).
    if not active_quarantine_covers(premises["id"], test_record["species_code"]):
        now = clock_now()
        order = new_entity()
        order.update({
            "premises_id": premises["id"],
            "species_code": test_record["species_code"],
            "disease_code": auto_quarantine_disease_code(test_record["test_type"]),
            "start_at": now,
            "end_at": now + timedelta(days=QUARANTINE_AUTO_DAYS),
            "reason": f"AUTO_POSITIVE_TEST:{test_record['id']}",
            "issued_by_user_id": "system",
            "status": "ACTIVE",
        })
        db["quarantine_orders"][order["id"]] = order

    # Reject DRAFT / PENDING_REVIEW certificates originating at this premises.
    for cert in db["certificates"].values():
        if cert["origin_premises_id"] == premises["id"] and cert["status"] in ("DRAFT", "PENDING_REVIEW"):
            cert["status"] = "REJECTED"
            cert["reject_reason"] = "AUTO_POSITIVE_TEST"
            touch(cert)


@app.route("/api/test-records", methods=["POST"])
def create_test_record():
    require_roles("LabTechnician")
    body = get_body(required=True)
    premises_id = req_str(body, "premises_id")
    species_code = req_enum(body, "species_code", SPECIES)
    test_type = req_enum(body, "test_type", TEST_TYPES)
    test_date = req_dt(body, "test_date")
    lab_reference = req_str(body, "lab_reference")

    get_premises(premises_id)

    ent = new_entity()
    ent.update({
        "premises_id": premises_id,
        "species_code": species_code,
        "test_type": test_type,
        "test_date": test_date,
        "lab_reference": lab_reference,
        "result": "RESULT_PENDING",
    })
    db["test_records"][ent["id"]] = ent
    return success(serialize("test_records", ent), 201)


@app.route("/api/test-records/<tid>/result", methods=["POST"])
def report_test_result(tid):
    require_roles("LabTechnician")
    body = get_body(required=True)
    result = body.get("result")
    if result not in ("NEGATIVE", "POSITIVE"):
        raise_err("ERR_VALIDATION", "result must be NEGATIVE or POSITIVE")
    t = get_test_record(tid)
    if t["result"] != "RESULT_PENDING":
        raise_err("ERR_TEST_RECORD_NOT_PENDING")
    t["result"] = result
    touch(t)
    if result == "POSITIVE":
        premises = db["premises"].get(t["premises_id"])
        if premises is not None:
            run_infection_cascade(premises, t)
    return success(serialize("test_records", t), 200)


@app.route("/api/premises/<pid>/test-records", methods=["GET"])
def list_test_records_for_premises(pid):
    require_roles(*ALL_READ_ROLES)
    p = get_premises(pid)
    materialize_premises_quarantines(p)
    items = sorted_entities([t for t in db["test_records"].values() if t["premises_id"] == pid])
    page, pagination = paginate(items)
    return success([serialize("test_records", t) for t in page], 200,
                   is_list=True, pagination=pagination)


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


def find_active_requirement(destination_state_code, species_code, inspection_date):
    """ACTIVE rows for (dest, species) whose half-open window covers inspection_date."""
    matches = []
    for r in db["entry_requirements"].values():
        if r["status"] != "ACTIVE":
            continue
        if r["destination_state_code"] != destination_state_code:
            continue
        if r["species_code"] != species_code:
            continue
        if inspection_date < r["effective_from"]:
            continue
        if r["effective_until"] is not None and inspection_date >= r["effective_until"]:
            continue
        matches.append(r)
    return matches


@app.route("/api/certificates", methods=["POST"])
def create_certificate():
    user_id, role = require_roles("AccreditedVet")
    body = get_body(required=True)
    origin_premises_id = req_str(body, "origin_premises_id")
    destination_state_code = req_str(body, "destination_state_code")
    species_code = req_enum(body, "species_code", SPECIES)
    head_count = req_int(body, "head_count", minimum=1)
    inspection_date = req_dt(body, "inspection_date")
    test_record_id = opt_str(body, "test_record_id")
    vaccination_date = opt_dt(body, "vaccination_date")
    consignment_description = opt_str(body, "consignment_description")

    # Body-schema temporal check: inspection_date must not be after the logical clock.
    if inspection_date > clock_now():
        raise_err("ERR_VALIDATION", "inspection_date must not be after the logical clock")

    # Existence (priority 4): body FKs and the acting vet's identity.
    get_premises(origin_premises_id)
    if test_record_id is not None:
        tr = get_test_record(test_record_id)
        if tr["test_date"] > inspection_date:
            raise_err("ERR_VALIDATION", "test_date must not be after inspection_date")
    acting_vet(user_id)

    ent = new_entity()
    ent.update({
        "origin_premises_id": origin_premises_id,
        "vet_id": user_id,
        "destination_state_code": destination_state_code,
        "species_code": species_code,
        "head_count": head_count,
        "inspection_date": inspection_date,
        "test_record_id": test_record_id,
        "vaccination_date": vaccination_date,
        "consignment_description": consignment_description,
        "status": "DRAFT",
        "pre_block_status": None,
        "reject_reason": None,
        "void_reason": None,
        "cvi_number": None,
        "issued_at": None,
        "valid_until": None,
        "provisional_fee_cents": None,
        "final_fee_cents": None,
    })
    db["certificates"][ent["id"]] = ent
    return success(serialize("certificates", ent), 201)


@app.route("/api/certificates/<cid>", methods=["GET"])
def read_certificate(cid):
    require_roles(*ALL_READ_ROLES)
    c = get_certificate(cid)
    materialize_certificate(c)
    return success(serialize("certificates", c), 200)


@app.route("/api/certificates", methods=["GET"])
def list_certificates():
    require_roles(*ALL_READ_ROLES)
    vet_id = request.args.get("vet_id")
    origin_premises_id = request.args.get("origin_premises_id")
    test_record_id = request.args.get("test_record_id")
    status = request.args.get("status")
    destination_state_code = request.args.get("destination_state_code")
    items = []
    for c in db["certificates"].values():
        materialize_certificate(c)
        if vet_id is not None and c["vet_id"] != vet_id:
            continue
        if origin_premises_id is not None and c["origin_premises_id"] != origin_premises_id:
            continue
        if test_record_id is not None and c["test_record_id"] != test_record_id:
            continue
        if status is not None and c["status"] != status:
            continue
        if destination_state_code is not None and c["destination_state_code"] != destination_state_code:
            continue
        items.append(c)
    items = sorted_entities(items)
    page, pagination = paginate(items)
    return success([serialize("certificates", c) for c in page], 200,
                   is_list=True, pagination=pagination)


@app.route("/api/certificates/<cid>/submit", methods=["POST"])
def submit_certificate(cid):
    user_id, role = require_roles("AccreditedVet")
    c = get_certificate(cid)
    materialize_certificate(c)
    vet = acting_vet(user_id)
    # Ownership (priority 5)
    if c["vet_id"] != user_id:
        raise_err("ERR_NOT_CERTIFICATE_OWNER")
    # State (priority 6)
    if c["status"] != "DRAFT":
        raise_err("ERR_CERTIFICATE_NOT_SUBMITTABLE")
    # Safety gates (priority 7): credential, disease hold, test result
    if not vet_is_current(vet):
        raise_err("ERR_VET_NOT_CURRENT")
    premises = db["premises"][c["origin_premises_id"]]
    if premises["disease_status"] in ("QUARANTINE_HOLD", "INFECTED"):
        raise_err("ERR_PREMISES_DISEASE_HOLD")

    # Matrix and linkage (priority 8)
    rows = find_active_requirement(c["destination_state_code"], c["species_code"], c["inspection_date"])
    if not rows:
        raise_err("ERR_NO_ACTIVE_ENTRY_REQUIREMENT")
    row = rows[0]
    if c["species_code"] != premises["species_code"]:
        raise_err("ERR_PREMISES_SPECIES_MISMATCH")

    test_record = None
    if row["test_type"] != "NONE":
        if c.get("test_record_id") is None:
            raise_err("ERR_TEST_RECORD_MISMATCH", "test_record_id is required by the matrix row")
        test_record = db["test_records"].get(c["test_record_id"])
        if test_record is None:
            raise_err("ERR_TEST_RECORD_NOT_FOUND")
        # Test-result safety gate (priority 7c) before linkage detail.
        if test_record["result"] != "NEGATIVE":
            raise_err("ERR_TEST_NOT_QUALIFYING")
        if (test_record["premises_id"] != c["origin_premises_id"]
                or test_record["species_code"] != c["species_code"]
                or test_record["test_type"] != row["test_type"]):
            raise_err("ERR_TEST_RECORD_MISMATCH")
        # Temporal (priority 9a): whole-day age <= test_validity_days (inclusive)
        age = whole_days_between(test_record["test_date"], c["inspection_date"])
        if age < 0:
            raise_err("ERR_VALIDATION", "test_date must not be after inspection_date")
        if age > row["test_validity_days"]:
            raise_err("ERR_TEST_VALIDITY_EXPIRED")

    if row["vaccination_required"]:
        vd = c.get("vaccination_date")
        if vd is None:
            raise_err("ERR_VACCINATION_WINDOW_VIOLATION", "vaccination_date is required by the matrix row")
        vage = whole_days_between(vd, c["inspection_date"])
        if vage < row["vaccination_min_days_before_inspection"]:
            raise_err("ERR_VACCINATION_WINDOW_VIOLATION")

    # Constraint (priority 10): inventory
    if c["head_count"] > compute_current_head_count(premises):
        raise_err("ERR_HEAD_COUNT_EXCEEDS_INVENTORY")

    c["status"] = "PENDING_REVIEW"
    c["provisional_fee_cents"] = issuance_fee_cents(c, premises)
    touch(c)
    return success(serialize("certificates", c), 200)


@app.route("/api/certificates/<cid>/issue", methods=["POST"])
def issue_certificate(cid):
    user_id, role = require_roles("StateVetOfficer")
    c = get_certificate(cid)
    materialize_certificate(c)
    if c["status"] != "PENDING_REVIEW":
        raise_err("ERR_CERTIFICATE_NOT_PENDING_REVIEW")
    # Safety gates (priority 7a, 7b) re-run at issue.
    vet = db["veterinarians"].get(c["vet_id"])
    if vet is None or not vet_is_current(vet):
        raise_err("ERR_VET_NOT_CURRENT")
    premises = db["premises"][c["origin_premises_id"]]
    if premises["disease_status"] in ("QUARANTINE_HOLD", "INFECTED"):
        raise_err("ERR_PREMISES_DISEASE_HOLD")

    now = clock_now()
    _seq["cvi"] += 1
    c["cvi_number"] = f"CVI-{premises['state_code']}-{_seq['cvi']:06d}"
    c["issued_at"] = now
    c["valid_until"] = now + timedelta(days=CVI_VALIDITY_DAYS)
    c["final_fee_cents"] = issuance_fee_cents(c, premises)
    c["status"] = "ISSUED"
    touch(c)
    return success(serialize("certificates", c), 200)


@app.route("/api/certificates/<cid>/reject", methods=["POST"])
def reject_certificate(cid):
    require_roles("StateVetOfficer")
    body = get_body(required=True)
    reason_code = req_str(body, "reason_code")
    c = get_certificate(cid)
    materialize_certificate(c)
    if c["status"] != "PENDING_REVIEW":
        raise_err("ERR_CERTIFICATE_NOT_PENDING_REVIEW")
    c["status"] = "REJECTED"
    c["reject_reason"] = reason_code
    touch(c)
    return success(serialize("certificates", c), 200)


@app.route("/api/certificates/<cid>/revise", methods=["POST"])
def revise_certificate(cid):
    user_id, role = require_roles("AccreditedVet")
    c = get_certificate(cid)
    materialize_certificate(c)
    acting_vet(user_id)
    if c["vet_id"] != user_id:
        raise_err("ERR_NOT_CERTIFICATE_OWNER")
    if c["status"] != "REJECTED":
        raise_err("ERR_CERTIFICATE_NOT_REVISABLE")
    c["status"] = "DRAFT"
    c["reject_reason"] = None
    touch(c)
    return success(serialize("certificates", c), 200)


@app.route("/api/certificates/<cid>/void", methods=["POST"])
def void_certificate(cid):
    require_roles("StateVetOfficer")
    body = get_body(required=True)
    reason = req_str(body, "reason")
    c = get_certificate(cid)
    materialize_certificate(c)
    if c["status"] not in ("ISSUED", "TRANSMITTED", "ENTRY_BLOCKED"):
        raise_err("ERR_CERTIFICATE_NOT_VOIDABLE")
    c["status"] = "VOID"
    c["void_reason"] = reason
    c["pre_block_status"] = None
    touch(c)

    # Cascade: permits {REQUESTED, ISSUED, SUSPENDED} -> VOIDED
    for permit in db["movement_permits"].values():
        if permit["certificate_id"] != c["id"]:
            continue
        if permit["status"] not in ("REQUESTED", "ISSUED", "SUSPENDED"):
            continue
        permit["status"] = "VOIDED"
        touch(permit)
        # Cascade depth 2: movement records {SCHEDULED, IN_TRANSIT} -> CANCELLED
        for mr in db["movement_records"].values():
            if mr["permit_id"] != permit["id"]:
                continue
            if mr["status"] in ("SCHEDULED", "IN_TRANSIT"):
                mr["status"] = "CANCELLED"
                touch(mr)
    return success(serialize("certificates", c), 200)


@app.route("/api/certificates/<cid>/transmit", methods=["POST"])
def transmit_certificate(cid):
    require_roles("StateVetOfficer")
    body = get_body(required=True)
    channel = req_enum(body, "channel", CHANNELS)
    c = get_certificate(cid)
    materialize_certificate(c)
    if c["status"] not in ("ISSUED", "TRANSMITTED"):
        raise_err("ERR_CERTIFICATE_NOT_TRANSMITTABLE")

    canonical = (
        f"{c['id']}|{c.get('cvi_number') or ''}|{c['destination_state_code']}|"
        f"{c['species_code']}|{c['head_count']}|"
        f"{_ts(c['issued_at']) if c['issued_at'] else ''}|"
        f"{_ts(c['valid_until']) if c['valid_until'] else ''}|{channel}"
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    ent = new_entity()
    ent.update({
        "certificate_id": c["id"],
        "destination_state_code": c["destination_state_code"],
        "channel": channel,
        "payload_digest": digest,
        "status": "QUEUED",
        "failure_reason": None,
        "acknowledged_at": None,
    })
    db["transmission_audits"][ent["id"]] = ent
    return success(serialize("transmission_audits", ent), 201)


# ---------------------------------------------------------------------------
# Movement permits
# ---------------------------------------------------------------------------


@app.route("/api/movement-permits", methods=["POST"])
def create_movement_permit():
    user_id, role = require_roles("AccreditedVet")
    body = get_body(required=True)
    certificate_id = req_str(body, "certificate_id")
    allocated_head_count = req_int(body, "allocated_head_count", minimum=1)
    valid_from = req_dt(body, "valid_from")
    valid_until = req_dt(body, "valid_until")
    if valid_until < valid_from:
        raise_err("ERR_VALIDATION", "valid_until must not be earlier than valid_from")
    cert = get_certificate(certificate_id)
    materialize_certificate(cert)
    acting_vet(user_id)

    ent = new_entity()
    ent.update({
        "certificate_id": certificate_id,
        "allocated_head_count": allocated_head_count,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "REQUESTED",
        "permit_number": None,
    })
    db["movement_permits"][ent["id"]] = ent
    return success(serialize_permit(ent), 201)


@app.route("/api/movement-permits/<pid>", methods=["GET"])
def read_movement_permit(pid):
    require_roles(*ALL_READ_ROLES)
    p = get_permit(pid)
    return success(serialize_permit(p), 200)


@app.route("/api/certificates/<cid>/movement-permits", methods=["GET"])
def list_permits_for_certificate(cid):
    require_roles(*ALL_READ_ROLES)
    c = get_certificate(cid)
    materialize_certificate(c)
    items = sorted_entities([p for p in db["movement_permits"].values() if p["certificate_id"] == cid])
    page, pagination = paginate(items)
    return success([serialize_permit(p) for p in page], 200, is_list=True, pagination=pagination)


@app.route("/api/movement-permits/<pid>/issue", methods=["POST"])
def issue_movement_permit(pid):
    require_roles("StateVetOfficer")
    p = get_permit(pid)
    cert = db["certificates"].get(p["certificate_id"])
    if cert is not None:
        materialize_certificate(cert)
    # State (priority 6): permit REQUESTED and certificate ISSUED/TRANSMITTED
    if p["status"] != "REQUESTED":
        raise_err("ERR_PERMIT_NOT_ISSUABLE")
    if cert is None or cert["status"] not in ("ISSUED", "TRANSMITTED"):
        raise_err("ERR_PERMIT_NOT_ISSUABLE")
    # Temporal window (priority 9c) before allocation constraint ordering per §3.5.
    # PRD §3.5 lists allocation then window; scaffold validations list window (9) before constraint (10).
    # PRD pipeline §2.5: temporal (9) precedes constraint (10). PRD wins.
    if not (p["valid_from"] >= cert["issued_at"] and p["valid_until"] <= cert["valid_until"]):
        raise_err("ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY")
    if p["allocated_head_count"] < cert["head_count"]:
        raise_err("ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT")

    _seq["permit"] += 1
    p["permit_number"] = f"EP-{cert['destination_state_code']}-{_seq['permit']:06d}"
    p["status"] = "ISSUED"
    touch(p)
    return success(serialize_permit(p), 200)


@app.route("/api/movement-permits/<pid>", methods=["PATCH"])
def adjust_movement_permit(pid):
    require_roles("StateVetOfficer")
    body = get_body(required=True)
    p = get_permit(pid)

    new_alloc = opt_int(body, "allocated_head_count", minimum=1)
    new_valid_until = opt_dt(body, "valid_until")

    # Body schema: window not inverted against the (possibly unchanged) start.
    if new_valid_until is not None and new_valid_until < p["valid_from"]:
        raise_err("ERR_VALIDATION", "valid_until must not be earlier than valid_from")

    # State (priority 6)
    if p["status"] != "ISSUED":
        raise_err("ERR_PERMIT_NOT_ADJUSTABLE")

    # Constraint (priority 10): allocation may not drop below consumed.
    if new_alloc is not None:
        committed, projected, _ = permit_headrooms(p)
        consumed = p["allocated_head_count"] - committed
        if new_alloc < consumed:
            raise_err("ERR_ALLOCATION_BELOW_CONSUMED")

    # OCC (priority 11)
    expected = req_int(body, "expected_permit_version")
    if expected != p["version"]:
        raise_err("ERR_STALE_PERMIT_VERSION")

    if new_alloc is not None:
        p["allocated_head_count"] = new_alloc
    if new_valid_until is not None:
        p["valid_until"] = new_valid_until
    touch(p)
    return success(serialize_permit(p), 200)


# ---------------------------------------------------------------------------
# Movement records
# ---------------------------------------------------------------------------


def movement_chain(record):
    permit = db["movement_permits"].get(record["permit_id"])
    cert = db["certificates"].get(permit["certificate_id"]) if permit else None
    premises = db["premises"].get(cert["origin_premises_id"]) if cert else None
    return permit, cert, premises


def check_movement_ownership(user_id, record):
    permit, cert, _ = movement_chain(record)
    if cert is None or cert["vet_id"] != user_id:
        raise_err("ERR_NOT_CERTIFICATE_OWNER")


def check_movement_window(permit, cert, instant):
    if not (permit["valid_from"] <= instant <= permit["valid_until"]):
        raise_err("ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW")
    if cert["valid_until"] is not None and instant > cert["valid_until"]:
        raise_err("ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW")


@app.route("/api/movement-records", methods=["POST"])
def create_movement_record():
    user_id, role = require_roles("AccreditedVet")
    body = get_body(required=True)
    permit_id = req_str(body, "permit_id")
    head_count = req_int(body, "head_count", minimum=1)
    destination_name = req_str(body, "destination_name")
    destination_county = opt_str(body, "destination_county")
    planned_ship_date = req_dt(body, "planned_ship_date")

    permit = get_permit(permit_id)
    cert = db["certificates"].get(permit["certificate_id"])
    if cert is not None:
        materialize_certificate(cert)
    premises = db["premises"].get(cert["origin_premises_id"]) if cert else None
    acting_vet(user_id)

    # Ownership (priority 5)
    if cert is None or cert["vet_id"] != user_id:
        raise_err("ERR_NOT_CERTIFICATE_OWNER")
    # State (priority 6)
    if permit["status"] != "ISSUED":
        raise_err("ERR_PERMIT_NOT_ISSUED")
    # Safety gates (priority 7b, 7d)
    if premises["disease_status"] in ("QUARANTINE_HOLD", "INFECTED"):
        raise_err("ERR_PREMISES_DISEASE_HOLD")
    if zone_covers_premises(premises):
        raise_err("ERR_OUTBREAK_MOVEMENT_RESTRICTION")
    # Temporal (priority 9d)
    check_movement_window(permit, cert, planned_ship_date)
    # Constraint (priority 10): committed headroom
    committed, _, _ = permit_headrooms(permit)
    if head_count > committed:
        raise_err("ERR_PERMIT_HEADROOM_EXCEEDED")

    ent = new_entity()
    ent.update({
        "permit_id": permit_id,
        "head_count": head_count,
        "destination_name": destination_name,
        "destination_county": destination_county,
        "planned_ship_date": planned_ship_date,
        "status": "SCHEDULED",
        "departed_at": None,
        "arrived_at": None,
        "movement_fee_cents": movement_fee_cents(head_count, cert["species_code"]),
    })
    db["movement_records"][ent["id"]] = ent
    return success(serialize("movement_records", ent), 201)


@app.route("/api/movement-records/<mid>/depart", methods=["POST"])
def depart_movement_record(mid):
    user_id, role = require_roles("AccreditedVet")
    mr = get_movement_record(mid)
    permit, cert, premises = movement_chain(mr)
    if cert is not None:
        materialize_certificate(cert)
    acting_vet(user_id)
    check_movement_ownership(user_id, mr)
    # State (priority 6)
    if mr["status"] != "SCHEDULED":
        raise_err("ERR_MOVEMENT_NOT_ADVANCEABLE")
    if permit["status"] != "ISSUED":
        raise_err("ERR_PERMIT_NOT_ISSUED")
    # Safety gates (priority 7b, 7d)
    if premises["disease_status"] in ("QUARANTINE_HOLD", "INFECTED"):
        raise_err("ERR_PREMISES_DISEASE_HOLD")
    if zone_covers_premises(premises):
        raise_err("ERR_OUTBREAK_MOVEMENT_RESTRICTION")
    # Temporal (priority 9d)
    check_movement_window(permit, cert, clock_now())
    # Constraint (priority 10): inventory
    if mr["head_count"] > compute_current_head_count(premises):
        raise_err("ERR_HEAD_COUNT_EXCEEDS_INVENTORY")

    mr["status"] = "IN_TRANSIT"
    mr["departed_at"] = clock_now()
    touch(mr)
    return success(serialize("movement_records", mr), 200)


@app.route("/api/movement-records/<mid>/arrive", methods=["POST"])
def arrive_movement_record(mid):
    user_id, role = require_roles("AccreditedVet")
    mr = get_movement_record(mid)
    if cert_of(mr) is not None:
        materialize_certificate(cert_of(mr))
    acting_vet(user_id)
    check_movement_ownership(user_id, mr)
    if mr["status"] != "IN_TRANSIT":
        raise_err("ERR_MOVEMENT_NOT_ADVANCEABLE")
    mr["status"] = "DELIVERED"
    mr["arrived_at"] = clock_now()
    touch(mr)
    return success(serialize("movement_records", mr), 200)


def cert_of(record):
    permit = db["movement_permits"].get(record["permit_id"])
    if permit is None:
        return None
    return db["certificates"].get(permit["certificate_id"])


@app.route("/api/movement-records/<mid>/cancel", methods=["POST"])
def cancel_movement_record(mid):
    user_id, role = require_roles("AccreditedVet")
    mr = get_movement_record(mid)
    if cert_of(mr) is not None:
        materialize_certificate(cert_of(mr))
    acting_vet(user_id)
    check_movement_ownership(user_id, mr)
    if mr["status"] not in ("SCHEDULED", "IN_TRANSIT"):
        raise_err("ERR_MOVEMENT_NOT_ADVANCEABLE")
    was_in_transit = mr["status"] == "IN_TRANSIT"
    mr["status"] = "CANCELLED"
    touch(mr)
    # Inventory restore happens derivatively: current_head_count counts only
    # IN_TRANSIT/DELIVERED records, so cancelling from IN_TRANSIT restores it.
    return success(serialize("movement_records", mr), 200)


@app.route("/api/movement-permits/<pid>/movement-records", methods=["GET"])
def list_movement_records_for_permit(pid):
    require_roles(*ALL_READ_ROLES)
    get_permit(pid)
    items = sorted_entities([m for m in db["movement_records"].values() if m["permit_id"] == pid])
    page, pagination = paginate(items)
    return success([serialize("movement_records", m) for m in page], 200,
                   is_list=True, pagination=pagination)


# ---------------------------------------------------------------------------
# Outbreak zones
# ---------------------------------------------------------------------------


def zone_overlap_exists(candidate, exclude_id=None):
    for z in db["outbreak_zones"].values():
        if z["id"] == exclude_id:
            continue
        if z["status"] not in ("MONITORING", "ACTIVE", "CONTAINED"):
            continue
        if (z["county"] == candidate["county"]
                and z["disease_code"] == candidate["disease_code"]
                and z["species_code"] == candidate["species_code"]
                and overlaps_half_open(candidate["effective_from"], candidate["effective_until"],
                                       z["effective_from"], z["effective_until"])):
            return True
    return False


@app.route("/api/outbreak-zones", methods=["POST"])
def create_outbreak_zone():
    require_roles("StateVetOfficer")
    body = get_body(required=True)
    county = req_str(body, "county")
    state_code = req_str(body, "state_code")
    disease_code = req_enum(body, "disease_code", DISEASE_CODES)
    species_code = req_enum(body, "species_code", SPECIES)
    severity = req_enum(body, "severity", SEVERITIES)
    effective_from = req_dt(body, "effective_from")
    effective_until = opt_dt(body, "effective_until")
    if effective_until is not None and effective_until <= effective_from:
        raise_err("ERR_VALIDATION", "effective_until must be later than effective_from")

    ent = new_entity()
    ent.update({
        "county": county,
        "state_code": state_code,
        "disease_code": disease_code,
        "species_code": species_code,
        "severity": severity,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "MONITORING",
    })
    if zone_overlap_exists(ent):
        raise_err("ERR_ZONE_WINDOW_OVERLAP")
    db["outbreak_zones"][ent["id"]] = ent
    return success(serialize("outbreak_zones", ent), 201)


def escalate_cascade(zone):
    """Three-link hold cascade on zone -> ACTIVE."""
    # Link 1: premises -> QUARANTINE_HOLD
    held_premises_ids = set()
    for p in db["premises"].values():
        if (p["county"] == zone["county"] and p["species_code"] == zone["species_code"]
                and p["disease_status"] != "INFECTED"):
            if p["disease_status"] != "QUARANTINE_HOLD":
                p["disease_status"] = "QUARANTINE_HOLD"
                touch(p)
            held_premises_ids.add(p["id"])
    # Link 2: certificates {ISSUED, TRANSMITTED} from held premises -> ENTRY_BLOCKED
    blocked_cert_ids = set()
    for c in db["certificates"].values():
        if c["origin_premises_id"] in held_premises_ids and c["status"] in ("ISSUED", "TRANSMITTED"):
            materialize_certificate(c)
            if c["status"] not in ("ISSUED", "TRANSMITTED"):
                continue
            c["pre_block_status"] = c["status"]
            c["status"] = "ENTRY_BLOCKED"
            touch(c)
            blocked_cert_ids.add(c["id"])
    # Link 3: ISSUED permits on blocked certificates -> SUSPENDED
    for permit in db["movement_permits"].values():
        if permit["certificate_id"] in blocked_cert_ids and permit["status"] == "ISSUED":
            permit["status"] = "SUSPENDED"
            touch(permit)


def resolve_cascade(zone):
    """Restore cascade on zone (CONTAINED) -> RESOLVED."""
    # Link 1: held premises -> MONITORED when no other hold remains
    restored_premises_ids = set()
    for p in db["premises"].values():
        if (p["county"] == zone["county"] and p["species_code"] == zone["species_code"]
                and p["disease_status"] == "QUARANTINE_HOLD"):
            # no other ACTIVE zone covering it, no ACTIVE quarantine order
            other_zone = None
            for z in db["outbreak_zones"].values():
                if z["id"] == zone["id"]:
                    continue
                if (z["status"] == "ACTIVE" and z["county"] == p["county"]
                        and z["species_code"] == p["species_code"] and zone_window_covers_now(z)):
                    other_zone = z
                    break
            if other_zone is not None:
                continue
            if active_quarantine_covers(p["id"], p["species_code"]):
                continue
            p["disease_status"] = "MONITORED"
            touch(p)
            restored_premises_ids.add(p["id"])
    # Link 2: ENTRY_BLOCKED certs on just-restored premises -> pre_block_status
    restored_cert_ids = set()
    for c in db["certificates"].values():
        if c["origin_premises_id"] in restored_premises_ids and c["status"] == "ENTRY_BLOCKED":
            materialize_certificate(c)
            if c["status"] != "ENTRY_BLOCKED":
                continue
            target = c.get("pre_block_status")
            if target in ("ISSUED", "TRANSMITTED"):
                c["status"] = target
                c["pre_block_status"] = None
                touch(c)
                restored_cert_ids.add(c["id"])
    # Link 3: SUSPENDED permits on just-restored certificates -> ISSUED
    for permit in db["movement_permits"].values():
        if permit["certificate_id"] in restored_cert_ids and permit["status"] == "SUSPENDED":
            permit["status"] = "ISSUED"
            touch(permit)


@app.route("/api/outbreak-zones/<zid>/escalate", methods=["POST"])
def escalate_zone(zid):
    require_roles("StateVetOfficer")
    z = get_zone(zid)
    if z["status"] not in ("MONITORING", "CONTAINED"):
        raise_err("ERR_ZONE_INVALID_TRANSITION")
    z["status"] = "ACTIVE"
    touch(z)
    escalate_cascade(z)
    return success(serialize("outbreak_zones", z), 200)


@app.route("/api/outbreak-zones/<zid>/contain", methods=["POST"])
def contain_zone(zid):
    require_roles("StateVetOfficer")
    z = get_zone(zid)
    if z["status"] != "ACTIVE":
        raise_err("ERR_ZONE_INVALID_TRANSITION")
    z["status"] = "CONTAINED"
    touch(z)
    return success(serialize("outbreak_zones", z), 200)


@app.route("/api/outbreak-zones/<zid>/resolve", methods=["POST"])
def resolve_zone(zid):
    require_roles("StateVetOfficer")
    z = get_zone(zid)
    if z["status"] not in ("MONITORING", "CONTAINED"):
        raise_err("ERR_ZONE_INVALID_TRANSITION")
    was_contained = z["status"] == "CONTAINED"
    z["status"] = "RESOLVED"
    touch(z)
    if was_contained:
        resolve_cascade(z)
    return success(serialize("outbreak_zones", z), 200)


# ---------------------------------------------------------------------------
# Quarantine orders
# ---------------------------------------------------------------------------


@app.route("/api/quarantine-orders", methods=["POST"])
def create_quarantine_order():
    user_id, role = require_roles("StateVetOfficer")
    body = get_body(required=True)
    premises_id = req_str(body, "premises_id")
    species_code = req_enum(body, "species_code", SPECIES)
    disease_code = req_enum(body, "disease_code", DISEASE_CODES)
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    reason = req_str(body, "reason")
    if end_at <= start_at:
        raise_err("ERR_VALIDATION", "end_at must be later than start_at")

    premises = get_premises(premises_id)
    materialize_premises_quarantines(premises)

    # Matrix/linkage (priority 8b)
    if species_code != premises["species_code"]:
        raise_err("ERR_PREMISES_SPECIES_MISMATCH")

    # Constraint (priority 10): closed-interval overlap against ACTIVE orders
    for q in db["quarantine_orders"].values():
        if (q["status"] == "ACTIVE" and q["premises_id"] == premises_id
                and q["species_code"] == species_code
                and closed_overlaps(start_at, end_at, q["start_at"], q["end_at"])):
            raise_err("ERR_QUARANTINE_WINDOW_CONFLICT")

    # 14-day minimum gap after the most recent LIFTED/EXPIRED order
    prior_ends = [
        q["end_at"] for q in db["quarantine_orders"].values()
        if q["status"] in ("LIFTED", "EXPIRED") and q["premises_id"] == premises_id
        and q["species_code"] == species_code
    ]
    if prior_ends:
        most_recent_end = max(prior_ends)
        if start_at < most_recent_end + timedelta(days=QUARANTINE_MIN_GAP_DAYS):
            raise_err("ERR_QUARANTINE_MIN_GAP_VIOLATION")

    ent = new_entity()
    ent.update({
        "premises_id": premises_id,
        "species_code": species_code,
        "disease_code": disease_code,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
        "issued_by_user_id": user_id,
        "status": "ACTIVE",
    })
    db["quarantine_orders"][ent["id"]] = ent

    if premises["disease_status"] != "INFECTED":
        if premises["disease_status"] != "QUARANTINE_HOLD":
            premises["disease_status"] = "QUARANTINE_HOLD"
            touch(premises)

    return success(serialize("quarantine_orders", ent), 201)


@app.route("/api/quarantine-orders/<qid>/lift", methods=["POST"])
def lift_quarantine_order(qid):
    user_id, role = require_roles("StateVetOfficer")
    q = get_quarantine(qid)
    materialize_quarantine(q)
    # State (priority 6)
    if q["status"] != "ACTIVE":
        raise_err("ERR_QUARANTINE_NOT_ACTIVE")
    # Segregation of duties (priority 10)
    if user_id == q["issued_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES")
    q["status"] = "LIFTED"
    touch(q)
    premises = db["premises"].get(q["premises_id"])
    if premises is not None:
        reevaluate_premises_after_hold_release(premises)
    return success(serialize("quarantine_orders", q), 200)


@app.route("/api/premises/<pid>/quarantine-orders", methods=["GET"])
def list_quarantine_orders_for_premises(pid):
    require_roles(*ALL_READ_ROLES)
    p = get_premises(pid)
    materialize_premises_quarantines(p)
    items = sorted_entities([q for q in db["quarantine_orders"].values() if q["premises_id"] == pid])
    page, pagination = paginate(items)
    return success([serialize("quarantine_orders", q) for q in page], 200,
                   is_list=True, pagination=pagination)


# ---------------------------------------------------------------------------
# Transmission audits
# ---------------------------------------------------------------------------


@app.route("/api/certificates/<cid>/transmissions", methods=["GET"])
def list_transmissions_for_certificate(cid):
    require_roles(*ALL_READ_ROLES)
    c = get_certificate(cid)
    materialize_certificate(c)
    items = sorted_entities([a for a in db["transmission_audits"].values() if a["certificate_id"] == cid])
    page, pagination = paginate(items)
    return success([serialize("transmission_audits", a) for a in page], 200,
                   is_list=True, pagination=pagination)


@app.route("/api/transmission-audits/<aid>/acknowledge", methods=["POST"])
def acknowledge_transmission(aid):
    require_roles("StateVetOfficer")
    a = get_audit(aid)
    if a["status"] != "QUEUED":
        raise_err("ERR_TRANSMISSION_NOT_ADVANCEABLE")
    a["status"] = "ACKNOWLEDGED"
    a["acknowledged_at"] = clock_now()
    touch(a)
    cert = db["certificates"].get(a["certificate_id"])
    if cert is not None:
        materialize_certificate(cert)
        if cert["status"] == "ISSUED":
            cert["status"] = "TRANSMITTED"
            touch(cert)
    return success(serialize("transmission_audits", a), 200)


@app.route("/api/transmission-audits/<aid>/fail", methods=["POST"])
def fail_transmission(aid):
    require_roles("StateVetOfficer")
    body = get_body(required=True)
    failure_reason = req_str(body, "failure_reason")
    a = get_audit(aid)
    if a["status"] != "QUEUED":
        raise_err("ERR_TRANSMISSION_NOT_ADVANCEABLE")
    a["status"] = "FAILED"
    a["failure_reason"] = failure_reason
    touch(a)
    return success(serialize("transmission_audits", a), 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
