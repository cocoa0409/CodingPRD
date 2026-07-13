import os
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

ROLES = {"IncidentCommander", "ShelterCoordinator", "TrafficManager",
         "Registrar", "PublicInfoOfficer"}
ALL_ROLES = list(ROLES)

AVG_VEHICLE_OCCUPANCY = Decimal("2.5")
MIN_HANDOVER_BUFFER = timedelta(minutes=30)

HAZARD_TYPES = {"WILDFIRE", "FLOOD", "HURRICANE", "HAZMAT", "TSUNAMI"}
FUNCTIONAL_NEEDS = {"NONE", "MOBILITY", "MEDICAL_ELECTRICITY", "OXYGEN", "COGNITIVE"}
CREDENTIAL_TYPES = {"RESIDENT", "ESSENTIAL_WORKER", "UTILITY"}
SEVERITIES = {"ADVISORY", "WATCH", "WARNING", "EXTREME"}
CHANNELS = {"WEA", "EAS", "IPAWS", "SMS"}
DIRECTIONS = {"INBOUND_REVERSED", "OUTBOUND"}

ZONE_LEVELS = {"NONE", "VOLUNTARY", "MANDATORY", "RE_ENTRY_ALLOWED"}
INCIDENT_PHASES = {"DRAFT", "ACTIVE", "ALL_CLEAR", "STOOD_DOWN"}
SHELTER_STATES = {"STANDBY", "OPEN", "FULL", "CLOSED"}
ROUTE_STATES = {"PLANNED", "OPEN", "CONGESTED", "CLOSED"}
CONTRAFLOW_STATES = {"SCHEDULED", "ACTIVE", "CANCELLED", "COMPLETED"}
CREDENTIAL_STATES = {"ISSUED", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"}
ALERT_STATES = {"DRAFT", "QUEUED", "SENT", "PARTIAL", "FAILED", "CANCELLED"}
ASSIGN_ACTIONS = {"CHECK_IN", "CHECK_OUT", "CANCEL"}
CHANNEL_RESULTS = {"SENT", "FAILED"}

ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_SHELTER_NOT_FOUND": 404,
    "ERR_STAFF_SHIFT_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_CONTRAFLOW_NOT_FOUND": 404,
    "ERR_REGISTRANT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INCIDENT_NOT_ACTIVE": 409,
    "ERR_INVALID_ORDER_TRANSITION": 409,
    "ERR_ALL_CLEAR_BLOCKED": 409,
    "ERR_SHELTER_CLOSED": 409,
    "ERR_SHELTER_NOT_OPEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ZONE_NOT_REENTRY": 409,
    "ERR_ROUTE_NOT_OPEN": 409,
    "ERR_ZONE_NOT_UNDER_ORDER": 409,
    "ERR_SHELTER_NOT_POWER_CAPABLE": 409,
    "ERR_STAFF_SHIFT_OVERLAP": 409,
    "ERR_CONTRAFLOW_WINDOW_OVERLAP": 409,
    "ERR_CREDENTIAL_WINDOW_INVALID": 409,
    "ERR_SHELTER_CAPACITY_EXCEEDED": 409,
    "ERR_IPAWS_SLOTS_EXHAUSTED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# =============================================================================
# In-memory store
# =============================================================================
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.incidents = {}
        self.zones = {}
        self.shelters = {}
        self.staff_shifts = {}
        self.routes = {}
        self.contraflow = {}
        self.registrants = {}
        self.assignments = {}
        self.credentials = {}
        self.alerts = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# =============================================================================
# Helpers
# =============================================================================
def now():
    return store.clock


def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_dt(value):
    if value is None:
        raise ValueError("null datetime")
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
    else:
        raise ValueError("bad datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_str(v):
    return isinstance(v, str)


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_dec(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = fmt_dt(now())


def new_common():
    ts = fmt_dt(now())
    return {
        "id": gen_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


# =============================================================================
# Auth
# =============================================================================
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or not role.strip():
        raise ApiError("ERR_MISSING_USER_CONTEXT")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    g.user_role = role
    return role


def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


# =============================================================================
# Field validation helpers (raise ERR_VALIDATION / ERR_INVALID_ENUM)
# =============================================================================
def v_required(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")


def v_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return None
    if not is_str(body[field]) or body[field] == "":
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a non-empty string")
    return body[field]


def v_int(body, field, required=True, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    val = body[field]
    if not is_int(val):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be an integer")
    if min_v is not None and val < min_v:
        raise ApiError("ERR_VALIDATION", f"Field {field} below minimum")
    if max_v is not None and val > max_v:
        raise ApiError("ERR_VALIDATION", f"Field {field} above maximum")
    return val


def v_num(body, field, required=True, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    val = body[field]
    if not is_num(val):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a number")
    if min_v is not None and val < min_v:
        raise ApiError("ERR_VALIDATION", f"Field {field} below minimum")
    if max_v is not None and val > max_v:
        raise ApiError("ERR_VALIDATION", f"Field {field} above maximum")
    return val


def v_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    if not isinstance(body[field], bool):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a boolean")
    return body[field]


def v_datetime(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    try:
        parse_dt(body[field])
    except Exception:
        raise ApiError("ERR_VALIDATION", f"Field {field} must be an ISO-8601 datetime")
    return body[field]


def v_enum_present(body, field, required=True):
    # presence check only (ERR_VALIDATION); membership done separately
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return False
    return True


def v_enum_member(body, field, members, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    if body[field] not in members:
        raise ApiError("ERR_INVALID_ENUM", f"Field {field} has an invalid value")
    return body[field]


# =============================================================================
# Response envelope
# =============================================================================
def meta_base():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def respond(data, status=200, is_list=False, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def paginate(items):
    # items already sorted; parse limit/offset from query with validation
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, pagination


def sorted_list(collection):
    return sorted(collection.values(), key=lambda e: (e["created_at"], e["_seq"]))


# =============================================================================
# Computed fields
# =============================================================================
def zone_population(zone):
    hour = now().hour
    is_daytime = 6 <= hour < 18
    if is_daytime:
        val = (Decimal(zone["residential_population"]) *
               Decimal(str(zone["daytime_occupancy_factor"])) +
               Decimal(zone["transient_population"]))
    else:
        val = (Decimal(zone["residential_population"]) *
               Decimal(str(zone["nighttime_occupancy_factor"])))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def shelter_staffed_now(shelter):
    total = 0
    clk = now()
    for s in store.staff_shifts.values():
        if s["shelter_id"] == shelter["id"] and s["status"] == "SCHEDULED":
            st = parse_dt(s["start_utc"])
            en = parse_dt(s["end_utc"])
            if st <= clk <= en:
                total += s["staffed_beds"]
    return total


def shelter_effective_capacity(shelter):
    staffed = shelter_staffed_now(shelter)
    base = min(shelter["physical_capacity"], staffed)
    ada = ceil_dec(Decimal(base) * Decimal(str(shelter["ada_reserved_pct"])))
    return max(0, base - ada)


def shelter_reserved_beds(shelter):
    return sum(a["party_size"] for a in store.assignments.values()
               if a["shelter_id"] == shelter["id"] and a["status"] == "RESERVED")


def shelter_occupied_beds(shelter):
    return sum(a["party_size"] for a in store.assignments.values()
               if a["shelter_id"] == shelter["id"] and a["status"] == "CHECKED_IN")


def incident_zone_ids(incident):
    return {z["id"] for z in store.zones.values()
            if z["incident_id"] == incident["id"]}


def incident_ipaws_reserved(incident):
    zids = incident_zone_ids(incident)
    return sum(1 for a in store.alerts.values()
               if a["zone_id"] in zids and "IPAWS" in a["channels"]
               and a["overall_status"] == "QUEUED")


def incident_clearance_minutes(incident):
    total_vehicles = 0
    for z in store.zones.values():
        if z["incident_id"] == incident["id"] and z["order_level"] in ("VOLUNTARY", "MANDATORY"):
            pop = zone_population(z)
            total_vehicles += ceil_dec(Decimal(pop) / AVG_VEHICLE_OCCUPANCY)
    total_throughput = sum(r["throughput_vph"] for r in store.routes.values()
                           if r["incident_id"] == incident["id"]
                           and r["status"] in ("OPEN", "CONGESTED"))
    if total_throughput == 0:
        return None
    return ceil_dec(Decimal(total_vehicles) / Decimal(total_throughput) * Decimal(60))


# =============================================================================
# Serialization
# =============================================================================
def base_out(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def out_incident(e):
    o = base_out(e)
    o.update({
        "name": e["name"],
        "jurisdiction": e["jurisdiction"],
        "hazard_type": e["hazard_type"],
        "status": e["status"],
        "ipaws_daily_slot_budget": e["ipaws_daily_slot_budget"],
        "ipaws_slots_reserved": incident_ipaws_reserved(e),
        "activated_at": e["activated_at"],
        "all_clear_at": e["all_clear_at"],
        "clearance_estimate_minutes": incident_clearance_minutes(e),
    })
    return o


def out_zone(e):
    o = base_out(e)
    o.update({
        "incident_id": e["incident_id"],
        "name": e["name"],
        "geofence_wkt": e["geofence_wkt"],
        "residential_population": e["residential_population"],
        "transient_population": e["transient_population"],
        "daytime_occupancy_factor": e["daytime_occupancy_factor"],
        "nighttime_occupancy_factor": e["nighttime_occupancy_factor"],
        "order_level": e["order_level"],
        "population_at_risk": zone_population(e),
        "order_issued_at": e["order_issued_at"],
    })
    return o


def out_shelter(e):
    o = base_out(e)
    eff = shelter_effective_capacity(e)
    reserved = shelter_reserved_beds(e)
    occupied = shelter_occupied_beds(e)
    o.update({
        "incident_id": e["incident_id"],
        "name": e["name"],
        "physical_capacity": e["physical_capacity"],
        "ada_reserved_pct": e["ada_reserved_pct"],
        "power_backup": e["power_backup"],
        "status": e["status"],
        "staffed_capacity_now": shelter_staffed_now(e),
        "effective_capacity": eff,
        "reserved_beds": reserved,
        "occupied_beds": occupied,
        "provisional_available": eff - reserved - occupied,
        "confirmed_available": eff - occupied,
    })
    return o


def out_staff_shift(e):
    o = base_out(e)
    o.update({
        "shelter_id": e["shelter_id"],
        "role_label": e["role_label"],
        "staffed_beds": e["staffed_beds"],
        "start_utc": e["start_utc"],
        "end_utc": e["end_utc"],
        "status": e["status"],
    })
    return o


def out_route(e):
    o = base_out(e)
    o.update({
        "incident_id": e["incident_id"],
        "name": e["name"],
        "corridor_label": e["corridor_label"],
        "throughput_vph": e["throughput_vph"],
        "status": e["status"],
    })
    return o


def out_contraflow(e):
    o = base_out(e)
    o.update({
        "route_id": e["route_id"],
        "segment_key": e["segment_key"],
        "direction": e["direction"],
        "window_start_utc": e["window_start_utc"],
        "window_end_utc": e["window_end_utc"],
        "status": e["status"],
    })
    return o


def out_registrant(e):
    o = base_out(e)
    o.update({
        "zone_id": e["zone_id"],
        "household_name": e["household_name"],
        "party_size": e["party_size"],
        "functional_needs": e["functional_needs"],
        "transport_required": e["transport_required"],
        "status": e["status"],
        "current_assignment_id": e["current_assignment_id"],
    })
    return o


def out_assignment(e):
    o = base_out(e)
    o.update({
        "registrant_id": e["registrant_id"],
        "shelter_id": e["shelter_id"],
        "party_size": e["party_size"],
        "status": e["status"],
        "checked_in_at": e["checked_in_at"],
    })
    return o


def out_credential(e):
    o = base_out(e)
    o.update({
        "zone_id": e["zone_id"],
        "registrant_id": e["registrant_id"],
        "credential_type": e["credential_type"],
        "valid_from_utc": e["valid_from_utc"],
        "valid_until_utc": e["valid_until_utc"],
        "status": e["status"],
    })
    return o


def out_alert(e):
    o = base_out(e)
    o.update({
        "zone_id": e["zone_id"],
        "message": e["message"],
        "severity": e["severity"],
        "channels": e["channels"],
        "wea_status": e["wea_status"],
        "eas_status": e["eas_status"],
        "ipaws_status": e["ipaws_status"],
        "sms_status": e["sms_status"],
        "overall_status": e["overall_status"],
    })
    return o


# =============================================================================
# Lookups
# =============================================================================
def find_or_404(collection, rid, err):
    ent = collection.get(rid)
    if ent is None:
        raise ApiError(err)
    return ent


# =============================================================================
# Time-based reconciliation (system transitions on the logical clock)
# =============================================================================
def reconcile_time():
    clk = now()
    for c in store.credentials.values():
        if c["status"] in ("ISSUED", "ACTIVE"):
            if clk >= parse_dt(c["valid_until_utc"]):
                c["status"] = "EXPIRED"
                touch(c)
    for seg in store.contraflow.values():
        if seg["status"] == "ACTIVE":
            if clk >= parse_dt(seg["window_end_utc"]):
                seg["status"] = "COMPLETED"
                touch(seg)


@app.before_request
def _before():
    reconcile_time()


# =============================================================================
# Shelter FULL/OPEN re-evaluation
# =============================================================================
def eval_full_after_checkin(shelter):
    if shelter["status"] == "OPEN":
        if shelter_occupied_beds(shelter) >= shelter_effective_capacity(shelter):
            shelter["status"] = "FULL"
            touch(shelter)


def eval_open_after_release(shelter):
    if shelter["status"] == "FULL":
        if shelter_occupied_beds(shelter) < shelter_effective_capacity(shelter):
            shelter["status"] = "OPEN"
            touch(shelter)


# =============================================================================
# Error handler
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# =============================================================================
# Clock
# =============================================================================
@app.route("/evac/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["IncidentCommander"])
    body = get_body()
    v_datetime(body, "to_iso8601", required=True)
    store.clock = parse_dt(body["to_iso8601"])
    reconcile_time()
    return respond({}, 200)


# =============================================================================
# Incident
# =============================================================================
@app.route("/evac/incidents", methods=["POST"])
def create_incident():
    authenticate(["IncidentCommander"])
    body = get_body()
    # pass 1: required + type/range
    name = v_str(body, "name")
    jurisdiction = v_str(body, "jurisdiction")
    v_enum_present(body, "hazard_type")
    budget = v_int(body, "ipaws_daily_slot_budget", required=False, default=5, min_v=0)
    # pass 2: enum
    hazard = v_enum_member(body, "hazard_type", HAZARD_TYPES)
    e = new_common()
    e.update({
        "name": name,
        "jurisdiction": jurisdiction,
        "hazard_type": hazard,
        "status": "DRAFT",
        "ipaws_daily_slot_budget": budget,
        "activated_at": None,
        "all_clear_at": None,
    })
    store.incidents[e["id"]] = e
    return respond(out_incident(e), 201)


@app.route("/evac/incidents/<rid>", methods=["GET"])
def get_incident(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.incidents, rid, "ERR_INCIDENT_NOT_FOUND")
    return respond(out_incident(e), 200)


@app.route("/evac/incidents/<rid>/phase", methods=["POST"])
def incident_phase(rid):
    authenticate(["IncidentCommander"])
    e = find_or_404(store.incidents, rid, "ERR_INCIDENT_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "to_phase")
    to_phase = v_enum_member(body, "to_phase", INCIDENT_PHASES)

    if to_phase == "ACTIVE":
        if e["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        e["status"] = "ACTIVE"
        e["activated_at"] = fmt_dt(now())
        touch(e)
    elif to_phase == "ALL_CLEAR":
        if e["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        # blocked while any zone is MANDATORY
        for z in store.zones.values():
            if z["incident_id"] == e["id"] and z["order_level"] == "MANDATORY":
                raise ApiError("ERR_ALL_CLEAR_BLOCKED")
        e["all_clear_at"] = fmt_dt(now())
        _cascade_all_clear(e)
        touch(e)
    elif to_phase == "STOOD_DOWN":
        if e["status"] != "ALL_CLEAR":
            raise ApiError("ERR_INVALID_STATE")
        e["status"] = "STOOD_DOWN"
        _cascade_stood_down(e)
        touch(e)
    else:  # DRAFT target — no defined transition
        raise ApiError("ERR_INVALID_STATE")
    return respond(out_incident(e), 200)


def _cascade_all_clear(incident):
    incident["status"] = "ALL_CLEAR"
    clk_now = now()
    for z in store.zones.values():
        if z["incident_id"] == incident["id"] and z["order_level"] == "VOLUNTARY":
            # hop1: zone VOLUNTARY -> RE_ENTRY_ALLOWED
            z["order_level"] = "RE_ENTRY_ALLOWED"
            z["order_issued_at"] = fmt_dt(now())
            touch(z)
            # registrants ADVISED -> CLEARED_FOR_REENTRY
            for r in store.registrants.values():
                if r["zone_id"] == z["id"] and r["status"] == "ADVISED":
                    r["status"] = "CLEARED_FOR_REENTRY"
                    touch(r)
            # hop2: credentials ISSUED within window -> ACTIVE
            for c in store.credentials.values():
                if c["zone_id"] == z["id"] and c["status"] == "ISSUED":
                    vf = parse_dt(c["valid_from_utc"])
                    vu = parse_dt(c["valid_until_utc"])
                    if vf <= clk_now < vu:
                        c["status"] = "ACTIVE"
                        touch(c)


def _cascade_stood_down(incident):
    shelter_ids = {s["id"] for s in store.shelters.values()
                   if s["incident_id"] == incident["id"]}
    for s in store.shelters.values():
        if s["incident_id"] == incident["id"] and s["status"] in ("OPEN", "FULL"):
            s["status"] = "CLOSED"
            touch(s)
    for a in store.assignments.values():
        if a["shelter_id"] in shelter_ids and a["status"] == "RESERVED":
            # only cancel reserved assignments on shelters just closed
            shelter = store.shelters.get(a["shelter_id"])
            if shelter and shelter["status"] == "CLOSED":
                a["status"] = "CANCELLED"
                touch(a)
                reg = store.registrants.get(a["registrant_id"])
                if reg and reg["current_assignment_id"] == a["id"]:
                    reg["current_assignment_id"] = None


# =============================================================================
# Zone
# =============================================================================
@app.route("/evac/zones", methods=["POST"])
def create_zone():
    authenticate(["IncidentCommander"])
    body = get_body()
    # FK existence (priority 4)
    if body.get("incident_id") is not None:
        if body["incident_id"] not in store.incidents:
            raise ApiError("ERR_INCIDENT_NOT_FOUND")
    # pass1
    incident_id = v_str(body, "incident_id")
    name = v_str(body, "name")
    geofence = v_str(body, "geofence_wkt")
    residential = v_int(body, "residential_population", min_v=0)
    transient = v_int(body, "transient_population", required=False, default=0, min_v=0)
    day_factor = v_num(body, "daytime_occupancy_factor", required=False, default=1.0,
                       min_v=0, max_v=2)
    night_factor = v_num(body, "nighttime_occupancy_factor", required=False, default=1.0,
                         min_v=0, max_v=2)
    e = new_common()
    e.update({
        "incident_id": incident_id,
        "name": name,
        "geofence_wkt": geofence,
        "residential_population": residential,
        "transient_population": transient,
        "daytime_occupancy_factor": day_factor,
        "nighttime_occupancy_factor": night_factor,
        "order_level": "NONE",
        "order_issued_at": None,
    })
    store.zones[e["id"]] = e
    return respond(out_zone(e), 201)


@app.route("/evac/zones/<rid>", methods=["GET"])
def get_zone(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.zones, rid, "ERR_ZONE_NOT_FOUND")
    return respond(out_zone(e), 200)


@app.route("/evac/zones", methods=["GET"])
def list_zones():
    authenticate(ALL_ROLES)
    items = sorted_list(store.zones)
    inc = request.args.get("incident_id")
    if inc is not None:
        items = [z for z in items if z["incident_id"] == inc]
    page, pg = paginate(items)
    return respond([out_zone(z) for z in page], 200, is_list=True, pagination=pg)


ZONE_LEGAL = {
    ("NONE", "VOLUNTARY"),
    ("NONE", "MANDATORY"),
    ("VOLUNTARY", "MANDATORY"),
    ("MANDATORY", "VOLUNTARY"),
    ("VOLUNTARY", "NONE"),
    ("MANDATORY", "RE_ENTRY_ALLOWED"),
    ("RE_ENTRY_ALLOWED", "MANDATORY"),
}


@app.route("/evac/zones/<rid>/order", methods=["POST"])
def zone_order(rid):
    authenticate(["IncidentCommander"])
    zone = find_or_404(store.zones, rid, "ERR_ZONE_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "level")
    level = v_enum_member(body, "level", ZONE_LEVELS)

    incident = store.incidents.get(zone["incident_id"])
    # incident-active check (priority 8)
    if level == "RE_ENTRY_ALLOWED":
        if not incident or incident["status"] not in ("ACTIVE", "ALL_CLEAR"):
            raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
    else:
        if not incident or incident["status"] != "ACTIVE":
            raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
    # transition legality (priority 9)
    current = zone["order_level"]
    if (current, level) not in ZONE_LEGAL:
        raise ApiError("ERR_INVALID_ORDER_TRANSITION")

    _apply_zone_order(zone, current, level)
    return respond(out_zone(zone), 200)


def _apply_zone_order(zone, current, level):
    zid = zone["id"]

    def regs():
        return [r for r in store.registrants.values() if r["zone_id"] == zid]

    if level == "VOLUNTARY" and current == "NONE":
        for r in regs():
            if r["status"] == "REGISTERED":
                r["status"] = "ADVISED"
                touch(r)
    elif level == "MANDATORY" and current in ("NONE", "VOLUNTARY"):
        affected_shelters = set()
        for r in regs():
            if r["status"] in ("REGISTERED", "ADVISED"):
                r["status"] = "ORDERED"
                touch(r)
                # hop2: auto-check-in RESERVED assignment
                aid = r["current_assignment_id"]
                if aid and aid in store.assignments:
                    a = store.assignments[aid]
                    if a["status"] == "RESERVED":
                        a["status"] = "CHECKED_IN"
                        a["checked_in_at"] = fmt_dt(now())
                        touch(a)
                        r["status"] = "SHELTERED"
                        touch(r)
                        affected_shelters.add(a["shelter_id"])
        # hop3: shelters tip to FULL
        for sid in affected_shelters:
            sh = store.shelters.get(sid)
            if sh:
                eval_full_after_checkin(sh)
    elif level == "VOLUNTARY" and current == "MANDATORY":
        for r in regs():
            if r["status"] == "ORDERED":
                r["status"] = "ADVISED"
                touch(r)
    elif level == "NONE" and current == "VOLUNTARY":
        for r in regs():
            if r["status"] == "ADVISED":
                r["status"] = "REGISTERED"
                touch(r)
    elif level == "RE_ENTRY_ALLOWED" and current == "MANDATORY":
        for r in regs():
            if r["status"] in ("ORDERED", "SHELTERED"):
                r["status"] = "CLEARED_FOR_REENTRY"
                touch(r)
    elif level == "MANDATORY" and current == "RE_ENTRY_ALLOWED":
        # compensation: suspend ACTIVE credentials on the zone
        for c in store.credentials.values():
            if c["zone_id"] == zid and c["status"] == "ACTIVE":
                c["status"] = "SUSPENDED"
                touch(c)
        for r in regs():
            if r["status"] == "CLEARED_FOR_REENTRY":
                r["status"] = "ORDERED"
                touch(r)

    zone["order_level"] = level
    zone["order_issued_at"] = fmt_dt(now())
    touch(zone)


# =============================================================================
# Shelter
# =============================================================================
@app.route("/evac/shelters", methods=["POST"])
def create_shelter():
    authenticate(["ShelterCoordinator"])
    body = get_body()
    if body.get("incident_id") is not None:
        if body["incident_id"] not in store.incidents:
            raise ApiError("ERR_INCIDENT_NOT_FOUND")
    incident_id = v_str(body, "incident_id")
    name = v_str(body, "name")
    physical = v_int(body, "physical_capacity", min_v=0)
    ada = v_num(body, "ada_reserved_pct", required=False, default=0.10, min_v=0, max_v=1)
    power = v_bool(body, "power_backup", required=False, default=True)
    e = new_common()
    e.update({
        "incident_id": incident_id,
        "name": name,
        "physical_capacity": physical,
        "ada_reserved_pct": ada,
        "power_backup": power,
        "status": "STANDBY",
    })
    store.shelters[e["id"]] = e
    return respond(out_shelter(e), 201)


@app.route("/evac/shelters/<rid>", methods=["GET"])
def get_shelter(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.shelters, rid, "ERR_SHELTER_NOT_FOUND")
    return respond(out_shelter(e), 200)


@app.route("/evac/shelters", methods=["GET"])
def list_shelters():
    authenticate(ALL_ROLES)
    items = sorted_list(store.shelters)
    inc = request.args.get("incident_id")
    if inc is not None:
        items = [s for s in items if s["incident_id"] == inc]
    page, pg = paginate(items)
    return respond([out_shelter(s) for s in page], 200, is_list=True, pagination=pg)


@app.route("/evac/shelters/<rid>/status", methods=["POST"])
def shelter_status(rid):
    authenticate(["ShelterCoordinator"])
    shelter = find_or_404(store.shelters, rid, "ERR_SHELTER_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "state")
    state = v_enum_member(body, "state", SHELTER_STATES)

    if state == "OPEN":
        if shelter["status"] != "STANDBY":
            raise ApiError("ERR_INVALID_STATE")
        if shelter_staffed_now(shelter) <= 0:
            raise ApiError("ERR_INVALID_STATE")
        shelter["status"] = "OPEN"
        touch(shelter)
    elif state == "CLOSED":
        if shelter["status"] == "STANDBY":
            shelter["status"] = "CLOSED"
            touch(shelter)
        elif shelter["status"] == "OPEN":
            # no CHECKED_IN assignment allowed
            for a in store.assignments.values():
                if a["shelter_id"] == shelter["id"] and a["status"] == "CHECKED_IN":
                    raise ApiError("ERR_INVALID_STATE")
            shelter["status"] = "CLOSED"
            touch(shelter)
            for a in store.assignments.values():
                if a["shelter_id"] == shelter["id"] and a["status"] == "RESERVED":
                    a["status"] = "CANCELLED"
                    touch(a)
                    reg = store.registrants.get(a["registrant_id"])
                    if reg and reg["current_assignment_id"] == a["id"]:
                        reg["current_assignment_id"] = None
        else:
            raise ApiError("ERR_INVALID_STATE")
    else:  # STANDBY / FULL not operator targets
        raise ApiError("ERR_INVALID_STATE")
    return respond(out_shelter(shelter), 200)


@app.route("/evac/shelters/<rid>/staff-shifts", methods=["GET"])
def list_shelter_shifts(rid):
    authenticate(ALL_ROLES)
    find_or_404(store.shelters, rid, "ERR_SHELTER_NOT_FOUND")
    items = [s for s in sorted_list(store.staff_shifts) if s["shelter_id"] == rid]
    page, pg = paginate(items)
    return respond([out_staff_shift(s) for s in page], 200, is_list=True, pagination=pg)


# =============================================================================
# StaffShift
# =============================================================================
@app.route("/evac/staff-shifts", methods=["POST"])
def create_staff_shift():
    authenticate(["ShelterCoordinator"])
    body = get_body()
    if body.get("shelter_id") is not None:
        if body["shelter_id"] not in store.shelters:
            raise ApiError("ERR_SHELTER_NOT_FOUND")
    shelter_id = v_str(body, "shelter_id")
    role_label = v_str(body, "role_label")
    staffed = v_int(body, "staffed_beds", min_v=0)
    start = v_datetime(body, "start_utc")
    end = v_datetime(body, "end_utc")
    st = parse_dt(start)
    en = parse_dt(end)
    if not (en > st):
        raise ApiError("ERR_VALIDATION", "end_utc must be strictly after start_utc")
    # overlap / handover buffer (priority 18)
    for s in store.staff_shifts.values():
        if s["shelter_id"] == shelter_id and s["status"] == "SCHEDULED":
            e_st = parse_dt(s["start_utc"])
            e_en = parse_dt(s["end_utc"])
            gap_ok = (st - e_en >= MIN_HANDOVER_BUFFER) or (e_st - en >= MIN_HANDOVER_BUFFER)
            if not gap_ok:
                raise ApiError("ERR_STAFF_SHIFT_OVERLAP")
    e = new_common()
    e.update({
        "shelter_id": shelter_id,
        "role_label": role_label,
        "staffed_beds": staffed,
        "start_utc": start,
        "end_utc": end,
        "status": "SCHEDULED",
    })
    store.staff_shifts[e["id"]] = e
    return respond(out_staff_shift(e), 201)


@app.route("/evac/staff-shifts/<rid>/cancel", methods=["POST"])
def cancel_staff_shift(rid):
    authenticate(["ShelterCoordinator"])
    shift = find_or_404(store.staff_shifts, rid, "ERR_STAFF_SHIFT_NOT_FOUND")
    if shift["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    shift["status"] = "CANCELLED"
    touch(shift)
    return respond(out_staff_shift(shift), 200)


# =============================================================================
# EvacuationRoute
# =============================================================================
@app.route("/evac/routes", methods=["POST"])
def create_route():
    authenticate(["TrafficManager"])
    body = get_body()
    if body.get("incident_id") is not None:
        if body["incident_id"] not in store.incidents:
            raise ApiError("ERR_INCIDENT_NOT_FOUND")
    incident_id = v_str(body, "incident_id")
    name = v_str(body, "name")
    corridor = v_str(body, "corridor_label")
    throughput = v_int(body, "throughput_vph", min_v=1)
    e = new_common()
    e.update({
        "incident_id": incident_id,
        "name": name,
        "corridor_label": corridor,
        "throughput_vph": throughput,
        "status": "PLANNED",
    })
    store.routes[e["id"]] = e
    return respond(out_route(e), 201)


@app.route("/evac/routes/<rid>", methods=["GET"])
def get_route(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.routes, rid, "ERR_ROUTE_NOT_FOUND")
    return respond(out_route(e), 200)


@app.route("/evac/routes", methods=["GET"])
def list_routes():
    authenticate(ALL_ROLES)
    items = sorted_list(store.routes)
    inc = request.args.get("incident_id")
    if inc is not None:
        items = [r for r in items if r["incident_id"] == inc]
    page, pg = paginate(items)
    return respond([out_route(r) for r in page], 200, is_list=True, pagination=pg)


@app.route("/evac/routes/<rid>/status", methods=["POST"])
def route_status(rid):
    authenticate(["TrafficManager"])
    route = find_or_404(store.routes, rid, "ERR_ROUTE_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "state")
    state = v_enum_member(body, "state", ROUTE_STATES)

    if state == "OPEN":
        if route["status"] == "PLANNED":
            incident = store.incidents.get(route["incident_id"])
            if not incident or incident["status"] != "ACTIVE":
                raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
            route["status"] = "OPEN"
            touch(route)
        elif route["status"] == "CONGESTED":
            route["status"] = "OPEN"
            touch(route)
        else:
            raise ApiError("ERR_INVALID_STATE")
    elif state == "CONGESTED":
        if route["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        route["status"] = "CONGESTED"
        touch(route)
    elif state == "CLOSED":
        if route["status"] not in ("OPEN", "CONGESTED"):
            raise ApiError("ERR_INVALID_STATE")
        route["status"] = "CLOSED"
        touch(route)
        for seg in store.contraflow.values():
            if seg["route_id"] == route["id"] and seg["status"] in ("SCHEDULED", "ACTIVE"):
                seg["status"] = "CANCELLED"
                touch(seg)
    else:  # PLANNED not an operator target
        raise ApiError("ERR_INVALID_STATE")
    return respond(out_route(route), 200)


@app.route("/evac/routes/<rid>/contraflow-segments", methods=["GET"])
def list_route_segments(rid):
    authenticate(ALL_ROLES)
    find_or_404(store.routes, rid, "ERR_ROUTE_NOT_FOUND")
    items = [s for s in sorted_list(store.contraflow) if s["route_id"] == rid]
    page, pg = paginate(items)
    return respond([out_contraflow(s) for s in page], 200, is_list=True, pagination=pg)


# =============================================================================
# ContraflowSegment
# =============================================================================
@app.route("/evac/contraflow-segments", methods=["POST"])
def create_contraflow():
    authenticate(["TrafficManager"])
    body = get_body()
    if body.get("route_id") is not None:
        if body["route_id"] not in store.routes:
            raise ApiError("ERR_ROUTE_NOT_FOUND")
    route_id = v_str(body, "route_id")
    segment_key = v_str(body, "segment_key")
    v_enum_present(body, "direction")
    start = v_datetime(body, "window_start_utc")
    end = v_datetime(body, "window_end_utc")
    direction = v_enum_member(body, "direction", DIRECTIONS)
    st = parse_dt(start)
    en = parse_dt(end)
    if not (en > st):
        raise ApiError("ERR_VALIDATION", "window_end_utc must be strictly after window_start_utc")
    # overlap check (priority 19): same route_id + segment_key, SCHEDULED/ACTIVE
    for s in store.contraflow.values():
        if (s["route_id"] == route_id and s["segment_key"] == segment_key
                and s["status"] in ("SCHEDULED", "ACTIVE")):
            e_st = parse_dt(s["window_start_utc"])
            e_en = parse_dt(s["window_end_utc"])
            if st < e_en and e_st < en:  # half-open overlap
                raise ApiError("ERR_CONTRAFLOW_WINDOW_OVERLAP")
    e = new_common()
    e.update({
        "route_id": route_id,
        "segment_key": segment_key,
        "direction": direction,
        "window_start_utc": start,
        "window_end_utc": end,
        "status": "SCHEDULED",
    })
    store.contraflow[e["id"]] = e
    return respond(out_contraflow(e), 201)


@app.route("/evac/contraflow-segments/<rid>/status", methods=["POST"])
def contraflow_status(rid):
    authenticate(["TrafficManager"])
    seg = find_or_404(store.contraflow, rid, "ERR_CONTRAFLOW_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "state")
    state = v_enum_member(body, "state", CONTRAFLOW_STATES)

    if state == "ACTIVE":
        if seg["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        route = store.routes.get(seg["route_id"])
        if not route or route["status"] != "OPEN":
            raise ApiError("ERR_ROUTE_NOT_OPEN")
        st = parse_dt(seg["window_start_utc"])
        en = parse_dt(seg["window_end_utc"])
        if not (st <= now() < en):
            raise ApiError("ERR_INVALID_STATE")
        seg["status"] = "ACTIVE"
        touch(seg)
    elif state == "CANCELLED":
        if seg["status"] not in ("SCHEDULED", "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE")
        seg["status"] = "CANCELLED"
        touch(seg)
    else:  # SCHEDULED / COMPLETED not operator targets
        raise ApiError("ERR_INVALID_STATE")
    return respond(out_contraflow(seg), 200)


# =============================================================================
# Registrant
# =============================================================================
@app.route("/evac/registrants", methods=["POST"])
def create_registrant():
    authenticate(["Registrar"])
    body = get_body()
    if body.get("zone_id") is not None:
        if body["zone_id"] not in store.zones:
            raise ApiError("ERR_ZONE_NOT_FOUND")
    zone_id = v_str(body, "zone_id")
    household = v_str(body, "household_name")
    party = v_int(body, "party_size", min_v=1)
    v_enum_present(body, "functional_needs", required=False)
    transport = v_bool(body, "transport_required", required=False, default=False)
    fn = v_enum_member(body, "functional_needs", FUNCTIONAL_NEEDS,
                       required=False, default="NONE")
    zone = store.zones[zone_id]
    # initial status from zone order_level
    order_level = zone["order_level"]
    if order_level == "NONE":
        status = "REGISTERED"
    elif order_level == "VOLUNTARY":
        status = "ADVISED"
    elif order_level == "MANDATORY":
        status = "ORDERED"
    elif order_level == "RE_ENTRY_ALLOWED":
        status = "CLEARED_FOR_REENTRY"
    else:
        status = "REGISTERED"
    e = new_common()
    e.update({
        "zone_id": zone_id,
        "household_name": household,
        "party_size": party,
        "functional_needs": fn,
        "transport_required": transport,
        "status": status,
        "current_assignment_id": None,
    })
    store.registrants[e["id"]] = e
    return respond(out_registrant(e), 201)


@app.route("/evac/registrants/<rid>", methods=["GET"])
def get_registrant(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.registrants, rid, "ERR_REGISTRANT_NOT_FOUND")
    return respond(out_registrant(e), 200)


@app.route("/evac/registrants", methods=["GET"])
def list_registrants():
    authenticate(ALL_ROLES)
    items = sorted_list(store.registrants)
    zid = request.args.get("zone_id")
    if zid is not None:
        items = [r for r in items if r["zone_id"] == zid]
    page, pg = paginate(items)
    return respond([out_registrant(r) for r in page], 200, is_list=True, pagination=pg)


# =============================================================================
# ShelterAssignment
# =============================================================================
@app.route("/evac/shelter-assignments", methods=["POST"])
def create_assignment():
    authenticate(["ShelterCoordinator", "Registrar"])
    body = get_body()
    # FK existence (priority 4)
    registrant = None
    if body.get("registrant_id") is not None:
        registrant = store.registrants.get(body["registrant_id"])
        if registrant is None:
            raise ApiError("ERR_REGISTRANT_NOT_FOUND")
    if body.get("shelter_id") is not None:
        if body["shelter_id"] not in store.shelters:
            raise ApiError("ERR_SHELTER_NOT_FOUND")
    # OCC (priority 5) — before required-field validation
    if registrant is not None and "expected_registrant_version" in body \
            and is_int(body["expected_registrant_version"]):
        if body["expected_registrant_version"] != registrant["version"]:
            raise ApiError("ERR_STALE_VERSION")
    # pass1 required/type
    registrant_id = v_str(body, "registrant_id")
    shelter_id = v_str(body, "shelter_id")
    expected_version = v_int(body, "expected_registrant_version")
    registrant = store.registrants[registrant_id]
    shelter = store.shelters[shelter_id]
    # re-check OCC (covers the case where value passed type-check now)
    if expected_version != registrant["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # business: registrant's zone under order (priority 16)
    zone = store.zones.get(registrant["zone_id"])
    if not zone or zone["order_level"] not in ("VOLUNTARY", "MANDATORY"):
        raise ApiError("ERR_ZONE_NOT_UNDER_ORDER")

    # supersede prior active assignment
    prior_id = registrant["current_assignment_id"]
    if prior_id and prior_id in store.assignments:
        prior = store.assignments[prior_id]
        if prior["status"] in ("RESERVED", "CHECKED_IN"):
            was_checked_in = prior["status"] == "CHECKED_IN"
            prior["status"] = "CANCELLED"
            touch(prior)
            if was_checked_in:
                psh = store.shelters.get(prior["shelter_id"])
                if psh:
                    eval_open_after_release(psh)

    e = new_common()
    e.update({
        "registrant_id": registrant_id,
        "shelter_id": shelter_id,
        "party_size": registrant["party_size"],
        "status": "RESERVED",
        "checked_in_at": None,
    })
    store.assignments[e["id"]] = e
    registrant["current_assignment_id"] = e["id"]
    touch(registrant)
    return respond(out_assignment(e), 201)


@app.route("/evac/shelter-assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.assignments, rid, "ERR_ASSIGNMENT_NOT_FOUND")
    return respond(out_assignment(e), 200)


@app.route("/evac/shelter-assignments", methods=["GET"])
def list_assignments():
    authenticate(ALL_ROLES)
    items = sorted_list(store.assignments)
    reg = request.args.get("registrant_id")
    sh = request.args.get("shelter_id")
    if reg is not None:
        items = [a for a in items if a["registrant_id"] == reg]
    if sh is not None:
        items = [a for a in items if a["shelter_id"] == sh]
    page, pg = paginate(items)
    return respond([out_assignment(a) for a in page], 200, is_list=True, pagination=pg)


@app.route("/evac/shelter-assignments/<rid>/status", methods=["POST"])
def assignment_status(rid):
    authenticate(["ShelterCoordinator"])
    a = find_or_404(store.assignments, rid, "ERR_ASSIGNMENT_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "action")
    action = v_enum_member(body, "action", ASSIGN_ACTIONS)

    shelter = store.shelters.get(a["shelter_id"])
    registrant = store.registrants.get(a["registrant_id"])

    if action == "CHECK_IN":
        if shelter["status"] == "CLOSED":
            raise ApiError("ERR_SHELTER_CLOSED")
        if shelter["status"] == "STANDBY":
            raise ApiError("ERR_SHELTER_NOT_OPEN")
        if a["status"] != "RESERVED":
            raise ApiError("ERR_INVALID_STATE")
        if registrant and registrant["functional_needs"] in ("MEDICAL_ELECTRICITY", "OXYGEN") \
                and not shelter["power_backup"]:
            raise ApiError("ERR_SHELTER_NOT_POWER_CAPABLE")
        if shelter_occupied_beds(shelter) + a["party_size"] > shelter_effective_capacity(shelter):
            raise ApiError("ERR_SHELTER_CAPACITY_EXCEEDED")
        a["status"] = "CHECKED_IN"
        a["checked_in_at"] = fmt_dt(now())
        touch(a)
        if registrant:
            registrant["status"] = "SHELTERED"
            touch(registrant)
        eval_full_after_checkin(shelter)
    elif action == "CHECK_OUT":
        if a["status"] != "CHECKED_IN":
            raise ApiError("ERR_INVALID_STATE")
        a["status"] = "CHECKED_OUT"
        touch(a)
        if registrant and registrant["current_assignment_id"] == a["id"]:
            registrant["current_assignment_id"] = None
        eval_open_after_release(shelter)
    elif action == "CANCEL":
        if a["status"] != "RESERVED":
            raise ApiError("ERR_INVALID_STATE")
        a["status"] = "CANCELLED"
        touch(a)
        if registrant and registrant["current_assignment_id"] == a["id"]:
            registrant["current_assignment_id"] = None
        eval_open_after_release(shelter)
    return respond(out_assignment(a), 200)


# =============================================================================
# AccessCredential
# =============================================================================
@app.route("/evac/access-credentials", methods=["POST"])
def create_credential():
    authenticate(["Registrar"])
    body = get_body()
    if body.get("zone_id") is not None:
        if body["zone_id"] not in store.zones:
            raise ApiError("ERR_ZONE_NOT_FOUND")
    if body.get("registrant_id") is not None:
        if body["registrant_id"] not in store.registrants:
            raise ApiError("ERR_REGISTRANT_NOT_FOUND")
    zone_id = v_str(body, "zone_id")
    registrant_id = v_str(body, "registrant_id")
    v_enum_present(body, "credential_type")
    start = v_datetime(body, "valid_from_utc")
    end = v_datetime(body, "valid_until_utc")
    ctype = v_enum_member(body, "credential_type", CREDENTIAL_TYPES)
    st = parse_dt(start)
    en = parse_dt(end)
    if not (en > st):
        raise ApiError("ERR_VALIDATION", "valid_until_utc must be strictly after valid_from_utc")
    e = new_common()
    e.update({
        "zone_id": zone_id,
        "registrant_id": registrant_id,
        "credential_type": ctype,
        "valid_from_utc": start,
        "valid_until_utc": end,
        "status": "ISSUED",
    })
    store.credentials[e["id"]] = e
    return respond(out_credential(e), 201)


@app.route("/evac/access-credentials/<rid>", methods=["GET"])
def get_credential(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.credentials, rid, "ERR_CREDENTIAL_NOT_FOUND")
    return respond(out_credential(e), 200)


@app.route("/evac/access-credentials", methods=["GET"])
def list_credentials():
    authenticate(ALL_ROLES)
    items = sorted_list(store.credentials)
    zid = request.args.get("zone_id")
    reg = request.args.get("registrant_id")
    if zid is not None:
        items = [c for c in items if c["zone_id"] == zid]
    if reg is not None:
        items = [c for c in items if c["registrant_id"] == reg]
    page, pg = paginate(items)
    return respond([out_credential(c) for c in page], 200, is_list=True, pagination=pg)


@app.route("/evac/access-credentials/<rid>/status", methods=["POST"])
def credential_status(rid):
    authenticate(["Registrar"])
    cred = find_or_404(store.credentials, rid, "ERR_CREDENTIAL_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "state")
    state = v_enum_member(body, "state", CREDENTIAL_STATES)

    if state == "ACTIVE":
        if cred["status"] not in ("ISSUED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        zone = store.zones.get(cred["zone_id"])
        if not zone or zone["order_level"] != "RE_ENTRY_ALLOWED":
            raise ApiError("ERR_ZONE_NOT_REENTRY")
        vf = parse_dt(cred["valid_from_utc"])
        vu = parse_dt(cred["valid_until_utc"])
        if not (vf <= now() < vu):
            raise ApiError("ERR_CREDENTIAL_WINDOW_INVALID")
        cred["status"] = "ACTIVE"
        touch(cred)
    elif state == "REVOKED":
        if cred["status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        cred["status"] = "REVOKED"
        touch(cred)
    else:  # ISSUED / SUSPENDED / EXPIRED not operator targets
        raise ApiError("ERR_INVALID_STATE")
    return respond(out_credential(cred), 200)


# =============================================================================
# AlertDispatch
# =============================================================================
CHANNEL_FIELD = {"WEA": "wea_status", "EAS": "eas_status",
                 "IPAWS": "ipaws_status", "SMS": "sms_status"}


@app.route("/evac/alerts", methods=["POST"])
def create_alert():
    authenticate(["PublicInfoOfficer"])
    body = get_body()
    if body.get("zone_id") is not None:
        if body["zone_id"] not in store.zones:
            raise ApiError("ERR_ZONE_NOT_FOUND")
    zone_id = v_str(body, "zone_id")
    message = v_str(body, "message")
    v_enum_present(body, "severity")
    v_required(body, "channels")
    if not isinstance(body["channels"], list):
        raise ApiError("ERR_VALIDATION", "channels must be an array")
    severity = v_enum_member(body, "severity", SEVERITIES)
    channels = body["channels"]
    if len(channels) == 0 or any(ch not in CHANNELS for ch in channels):
        raise ApiError("ERR_INVALID_ENUM", "channels must be a non-empty subset of valid channels")
    # de-duplicate preserving order
    seen = []
    for ch in channels:
        if ch not in seen:
            seen.append(ch)
    channels = seen
    e = new_common()
    e.update({
        "zone_id": zone_id,
        "message": message,
        "severity": severity,
        "channels": channels,
        "wea_status": "PENDING" if "WEA" in channels else "NA",
        "eas_status": "PENDING" if "EAS" in channels else "NA",
        "ipaws_status": "PENDING" if "IPAWS" in channels else "NA",
        "sms_status": "PENDING" if "SMS" in channels else "NA",
        "overall_status": "DRAFT",
    })
    store.alerts[e["id"]] = e
    return respond(out_alert(e), 201)


@app.route("/evac/alerts/<rid>", methods=["GET"])
def get_alert(rid):
    authenticate(ALL_ROLES)
    e = find_or_404(store.alerts, rid, "ERR_ALERT_NOT_FOUND")
    return respond(out_alert(e), 200)


@app.route("/evac/alerts", methods=["GET"])
def list_alerts():
    authenticate(ALL_ROLES)
    items = sorted_list(store.alerts)
    zid = request.args.get("zone_id")
    if zid is not None:
        items = [a for a in items if a["zone_id"] == zid]
    page, pg = paginate(items)
    return respond([out_alert(a) for a in page], 200, is_list=True, pagination=pg)


def _incident_of_alert(alert):
    zone = store.zones.get(alert["zone_id"])
    if not zone:
        return None
    return store.incidents.get(zone["incident_id"])


@app.route("/evac/alerts/<rid>/status", methods=["POST"])
def alert_status(rid):
    authenticate(["PublicInfoOfficer"])
    alert = find_or_404(store.alerts, rid, "ERR_ALERT_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "state")
    state = v_enum_member(body, "state", ALERT_STATES)

    if state == "QUEUED":
        if alert["overall_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        if "IPAWS" in alert["channels"]:
            incident = _incident_of_alert(alert)
            budget = incident["ipaws_daily_slot_budget"] if incident else 0
            zids = incident_zone_ids(incident) if incident else set()
            in_flight = sum(1 for a in store.alerts.values()
                            if a["zone_id"] in zids and "IPAWS" in a["channels"]
                            and a["overall_status"] in ("QUEUED", "SENT", "PARTIAL"))
            if in_flight >= budget:
                raise ApiError("ERR_IPAWS_SLOTS_EXHAUSTED")
        alert["overall_status"] = "QUEUED"
        touch(alert)
    elif state == "CANCELLED":
        if alert["overall_status"] != "QUEUED":
            raise ApiError("ERR_INVALID_STATE")
        alert["overall_status"] = "CANCELLED"
        touch(alert)
    else:  # other states not operator targets
        raise ApiError("ERR_INVALID_STATE")
    return respond(out_alert(alert), 200)


@app.route("/evac/alerts/<rid>/channel-result", methods=["POST"])
def alert_channel_result(rid):
    authenticate(["PublicInfoOfficer"])
    alert = find_or_404(store.alerts, rid, "ERR_ALERT_NOT_FOUND")
    body = get_body()
    v_enum_present(body, "channel")
    v_enum_present(body, "result")
    channel = v_enum_member(body, "channel", CHANNELS)
    result = v_enum_member(body, "result", CHANNEL_RESULTS)

    if alert["overall_status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE")
    field = CHANNEL_FIELD[channel]
    if alert[field] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    alert[field] = result
    # rollup evaluation
    requested = alert["channels"]
    statuses = [alert[CHANNEL_FIELD[ch]] for ch in requested]
    if all(s in ("SENT", "FAILED") for s in statuses):
        if all(s == "SENT" for s in statuses):
            alert["overall_status"] = "SENT"
        elif all(s == "FAILED" for s in statuses):
            alert["overall_status"] = "FAILED"
        else:
            alert["overall_status"] = "PARTIAL"
    touch(alert)
    return respond(out_alert(alert), 200)


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
