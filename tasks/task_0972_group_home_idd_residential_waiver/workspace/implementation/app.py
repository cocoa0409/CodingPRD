#!/usr/bin/env python3
"""Group Home & IDD Residential Waiver API — in-memory Flask implementation."""
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ============================================================================
# In-memory store + logical clock
# ============================================================================


class Store:
    def __init__(self):
        self.agencies = {}
        self.homes = {}
        self.individuals = {}
        self.isps = {}
        self.auths = {}
        self.staff = {}
        self.shifts = {}
        self.beds = {}
        self.medorders = {}
        self.adminevents = {}
        self.bsps = {}
        self.incidents = {}
        self.visits = {}
        self.trips = {}
        self.claims = {}
        self.seq = 0
        # Logical clock: startup default is exactly 2026-05-01T00:00:00Z
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()

# ============================================================================
# Time helpers
# ============================================================================


def now():
    return db.clock


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(db.clock)


def today():
    return db.clock.date()


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_d(s):
    if not isinstance(s, str) or not DATE_RE.match(s.strip()):
        raise ValueError("not a date")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


# ============================================================================
# Errors + envelope
# ============================================================================


class ApiError(Exception):
    def __init__(self, eid, status, message):
        super().__init__(message)
        self.eid = eid
        self.status = status
        self.message = message


def err(eid, status, message):
    raise ApiError(eid, status, message)


def bad(msg):
    err("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Referenced resource does not exist"):
    err("ERR_NOT_FOUND", 404, msg)


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, rtype="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": rtype, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.eid, "message": e.message},
    }
    return jsonify(body), e.status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_500(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


# ============================================================================
# Validation helpers
# ============================================================================


def body():
    if request.content_length:
        b = request.get_json(silent=True)
        if b is None or not isinstance(b, dict):
            bad("Request body must be a JSON object")
        return b
    return {}


def no_unknown(b, allowed):
    extra = set(b.keys()) - set(allowed)
    if extra:
        bad("Unknown request fields: %s" % ", ".join(sorted(extra)))


def need(b, name):
    v = b.get(name)
    if v is None:
        bad("Missing required field: %s" % name)
    return v


def v_str(v, name, minlen=1):
    if not isinstance(v, str) or len(v) < minlen:
        bad("Field %s must be a string of length >= %d" % (name, minlen))
    return v


def v_int(v, name, minv=None):
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer" % name)
    if minv is not None and v < minv:
        bad("Field %s must be >= %d" % (name, minv))
    return v


def v_bool(v, name):
    if not isinstance(v, bool):
        bad("Field %s must be a boolean" % name)
    return v


def v_enum(v, name, choices):
    if not isinstance(v, str) or v not in choices:
        bad("Field %s must be one of %s" % (name, ", ".join(choices)))
    return v


def v_date(v, name):
    try:
        parse_d(v)
    except (ValueError, TypeError):
        bad("Field %s must be an ISO date YYYY-MM-DD" % name)
    return v.strip()


def v_datetime(v, name):
    try:
        dt = parse_dt(v)
    except (ValueError, TypeError):
        bad("Field %s must be an ISO 8601 datetime" % name)
    return fmt_dt(dt)


def v_list(v, name):
    if not isinstance(v, list):
        bad("Field %s must be an array" % name)
    return v


def get_or_404(store, key, msg="Referenced resource does not exist"):
    e = store.get(key)
    if e is None:
        not_found(msg)
    return e


def pagination_params():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (ValueError, TypeError):
        bad("limit and offset must be integers")
    if limit < 1 or limit > 100:
        bad("limit must be between 1 and 100")
    if offset < 0:
        bad("offset must be >= 0")
    return limit, offset


def list_page(items):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination_params()
    total = len(items)
    page = [serialize(e) for e in items[offset:offset + limit]]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return ok(page, "array", 200, pag)


def apply_filters(items, filters):
    out = []
    for e in items:
        if all(e.get(k) == v for k, v in filters.items()):
            out.append(e)
    return out


def opt_filter(name):
    v = request.args.get(name)
    return v if v is not None else None


# ============================================================================
# Auth
# ============================================================================

ALL_ROLES = {"AgencyAdmin", "CaseManager", "QIDP", "DSP", "BillingSpecialist", "ComplianceOfficer", "Any"}
ENTITY_ROLE_MAP = {"CaseManager": "CASE_MANAGER", "QIDP": "QIDP", "DSP": "DSP"}


def authenticate(allowed):
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in ALL_ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, "Unknown role: %s" % role)
    if role not in allowed:
        err("ERR_INSUFFICIENT_PERMISSIONS", 403, "Role %s is not permitted for this endpoint" % role)
    staff = None
    if role in ENTITY_ROLE_MAP:
        staff = db.staff.get(uid)
        want = ENTITY_ROLE_MAP[role]
        if staff is None or staff.get("status") != "ACTIVE" or staff.get("staff_role") != want:
            err("ERR_ROLE_IDENTITY_MISMATCH", 403,
                "X-User-ID does not resolve to an ACTIVE StaffMember with matching staff_role")
    return uid, role, staff


ANY = set(ALL_ROLES)

# ============================================================================
# Entity helpers
# ============================================================================


def new_id():
    # PRD 2.4: server-minted UUID with no type prefix — canonical dashed form.
    return str(uuid.uuid4())


def next_seq():
    db.seq += 1
    return db.seq


def base_entity():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def touch(e):
    e["version"] = e.get("version", 0) + 1
    e["updated_at"] = now_iso()


def serialize(e):
    out = {k: v for k, v in e.items() if not k.startswith("_")}
    # remaining_units is always derived
    if "authorized_units" in out and "consumed_units" in out:
        out["remaining_units"] = out["authorized_units"] - out["consumed_units"]
    return out


# ============================================================================
# Derived recomputes
# ============================================================================


def recompute_occupancy(home):
    cnt = 0
    for ba in db.beds.values():
        if ba["home_id"] == home["id"] and ba["status"] == "ACTIVE":
            cnt += 1
    home["current_occupancy"] = cnt


def compute_posture(home_id):
    open_statuses = ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO")
    has_critical = False
    has_high = False
    for inc in db.incidents.values():
        if inc["home_id"] == home_id and inc["status"] in open_statuses:
            if inc["severity"] == "CRITICAL":
                has_critical = True
            elif inc["severity"] == "HIGH":
                has_high = True
    if has_critical:
        return "CRITICAL"
    if has_high:
        return "PROVISIONAL"
    return "GOOD_STANDING"


def recompute_posture(home):
    home["compliance_posture"] = compute_posture(home["id"])
    return home["compliance_posture"]


def recompute_held_count(agency_id):
    agency = db.agencies.get(agency_id)
    if agency is None:
        return
    cnt = 0
    for c in db.claims.values():
        if c["status"] == "HOLD":
            ind = db.individuals.get(c["individual_id"])
            if ind is not None and ind["agency_id"] == agency_id:
                cnt += 1
    agency["held_claims_count"] = cnt


def residents_of_home(home_id):
    """Individuals with an ACTIVE bed assignment at the home."""
    out = set()
    for ba in db.beds.values():
        if ba["home_id"] == home_id and ba["status"] == "ACTIVE":
            out.add(ba["individual_id"])
    return out


def census_current(home_id, d):
    cnt = 0
    for ba in db.beds.values():
        if ba["home_id"] != home_id or ba["status"] != "ACTIVE":
            continue
        mi = parse_d(ba["move_in_date"])
        mo = parse_d(ba["move_out_date"]) if ba.get("move_out_date") else None
        if mi <= d and (mo is None or mo > d):
            cnt += 1
    return cnt


def census_projected(home_id, d):
    horizon = d + timedelta(days=14)
    cnt = census_current(home_id, d)
    for ba in db.beds.values():
        if ba["home_id"] != home_id or ba["status"] != "PENDING":
            continue
        mi = parse_d(ba["move_in_date"])
        if mi <= horizon:
            cnt += 1
    return cnt


# ============================================================================
# Time-based auto transitions (fired when the logical clock is set)
# ============================================================================


def fire_time_transitions():
    now_dt = now()
    today_d = now_dt.date()

    # ISP ACTIVE -> EXPIRED past plan_year_end (with 2-link cascade)
    for isp in list(db.isps.values()):
        if isp["status"] == "ACTIVE" and today_d > parse_d(isp["plan_year_end"]):
            isp["status"] = "EXPIRED"
            touch(isp)
            # link 1: every ACTIVE authorization of this individual -> SUSPENDED
            for auth in db.auths.values():
                if auth["individual_id"] == isp["individual_id"] and auth["status"] == "ACTIVE":
                    auth["status"] = "SUSPENDED"
                    touch(auth)
                    # link 2: its EVV visits in PENDING / EXCEPTION -> REJECTED
                    for v in db.visits.values():
                        if v["authorization_id"] == auth["id"] and v["verification_status"] in ("PENDING", "EXCEPTION"):
                            v["verification_status"] = "REJECTED"
                            touch(v)

    # Authorization APPROVED -> ACTIVE when clock reaches span
    for auth in list(db.auths.values()):
        if auth["status"] == "APPROVED":
            if parse_d(auth["span_start"]) <= today_d <= parse_d(auth["span_end"]):
                auth["status"] = "ACTIVE"
                touch(auth)

    # Authorization ACTIVE -> EXPIRED past span_end
    for auth in list(db.auths.values()):
        if auth["status"] == "ACTIVE" and today_d > parse_d(auth["span_end"]):
            auth["status"] = "EXPIRED"
            touch(auth)

    # BSP ACTIVE -> EXPIRED strictly past review_due_at
    for bp in list(db.bsps.values()):
        if bp["status"] == "ACTIVE" and bp.get("review_due_at"):
            if now_dt > parse_dt(bp["review_due_at"]):
                bp["status"] = "EXPIRED"
                touch(bp)

    # TransportTrip SCHEDULED -> COMPLETED past return_at
    for t in list(db.trips.values()):
        if t["status"] == "SCHEDULED" and now_dt > parse_dt(t["return_at"]):
            t["status"] = "COMPLETED"
            touch(t)


# ============================================================================
# Waterfall allocation
# ============================================================================


def waterfall_allocate(visit, units):
    own = db.auths[visit["authorization_id"]]
    svc_date = parse_d(visit["service_date"])
    candidates = [own]
    succ = []
    for a in db.auths.values():
        if a["id"] == own["id"]:
            continue
        if a["individual_id"] != visit["individual_id"]:
            continue
        if a["service_code"] != own["service_code"]:
            continue
        if a["status"] != "ACTIVE":
            continue
        if not (parse_d(a["span_start"]) <= svc_date <= parse_d(a["span_end"])):
            continue
        succ.append(a)
    succ.sort(key=lambda a: (parse_d(a["span_start"]), a["created_at"], a["_seq"]))
    candidates.extend(succ)

    # Plan first (atomic full placement), then commit.
    plan = []
    remaining = units
    for c in candidates:
        rem = c["authorized_units"] - c["consumed_units"]
        take = min(rem, remaining)
        if take > 0:
            plan.append((c, take))
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        err("ERR_AUTHORIZATION_UNITS_EXHAUSTED", 409,
            "Waterfall allocation cannot fully place the visit's units")

    entries = []
    for c, take in plan:
        c["consumed_units"] += take
        if c["consumed_units"] >= c["authorized_units"] and c["status"] == "ACTIVE":
            c["status"] = "EXHAUSTED"
        touch(c)
        entries.append({"authorization_id": c["id"], "units": take})
    visit["allocated_units_entries"] = entries


def complete_linked_shift(visit):
    sid = visit.get("shift_id")
    if not sid:
        return
    shift = db.shifts.get(sid)
    if shift is not None and shift["status"] == "CONFIRMED":
        shift["status"] = "COMPLETED"
        touch(shift)


# ============================================================================
# Agencies & clock
# ============================================================================


@app.post("/agencies")
def create_agency():
    uid, role, _ = authenticate({"AgencyAdmin"})
    b = body()
    name = need(b, "name")
    agency = base_entity()
    agency.update({
        "name": v_str(name, "name"),
        "day_staff_ratio": v_int(b.get("day_staff_ratio", 4), "day_staff_ratio", 1),
        "night_staff_ratio": v_int(b.get("night_staff_ratio", 8), "night_staff_ratio", 1),
        "evv_grace_minutes": v_int(b.get("evv_grace_minutes", 15), "evv_grace_minutes", 0),
        "cash_collected_cents": 0,
        "recoupment_balance_cents": 0,
        "held_claims_count": 0,
    })
    no_unknown(b, {"name", "day_staff_ratio", "night_staff_ratio", "evv_grace_minutes"})
    db.agencies[agency["id"]] = agency
    return ok(serialize(agency), "object", 201)


@app.get("/agencies/<agencyId>")
def get_agency(agencyId):
    authenticate(ANY)
    agency = get_or_404(db.agencies, agencyId)
    return ok(serialize(agency))


@app.post("/_clock/set_current_utc")
def set_clock():
    uid, role, _ = authenticate({"AgencyAdmin"})
    b = body()
    target = need(b, "to_iso8601")
    try:
        dt = parse_dt(target)
    except (ValueError, TypeError):
        bad("to_iso8601 must be an ISO 8601 datetime")
    db.clock = dt
    fire_time_transitions()
    return ok({"current_utc": now_iso()})


# ============================================================================
# Homes
# ============================================================================


@app.post("/homes")
def create_home():
    uid, role, _ = authenticate({"AgencyAdmin"})
    b = body()
    agency_id = need(b, "agency_id")
    if not isinstance(agency_id, str):
        bad("agency_id must be a string")
    get_or_404(db.agencies, agency_id, "Agency not found")
    name = need(b, "name")
    license_number = need(b, "license_number")
    beds = need(b, "certified_bed_count")
    home = base_entity()
    home.update({
        "agency_id": agency_id,
        "name": v_str(name, "name"),
        "license_number": v_str(license_number, "license_number"),
        "certified_bed_count": v_int(beds, "certified_bed_count", 1),
        "status": "ACTIVE",
        "compliance_posture": "GOOD_STANDING",
        "current_occupancy": 0,
    })
    for h in db.homes.values():
        if h["agency_id"] == agency_id and h["license_number"] == home["license_number"]:
            bad("license_number must be unique within the agency")
    no_unknown(b, {"agency_id", "name", "license_number", "certified_bed_count"})
    db.homes[home["id"]] = home
    return ok(serialize(home), "object", 201)


@app.get("/homes")
def list_homes():
    authenticate(ANY)
    filters = {}
    for f in ("agency_id", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.homes.values()), filters))


@app.get("/homes/<homeId>")
def get_home(homeId):
    authenticate(ANY)
    home = get_or_404(db.homes, homeId)
    return ok(serialize(home))


@app.post("/homes/<homeId>/suspend")
def suspend_home(homeId):
    uid, role, _ = authenticate({"ComplianceOfficer"})
    home = get_or_404(db.homes, homeId)
    b = body()
    no_unknown(b, set())
    if home["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Home must be ACTIVE to suspend")
    home["status"] = "SUSPENDED"
    touch(home)
    # conditional cascade: PENDING bed assignments -> CANCELLED
    for ba in db.beds.values():
        if ba["home_id"] == home["id"] and ba["status"] == "PENDING":
            ba["status"] = "CANCELLED"
            touch(ba)
    return ok(serialize(home))


@app.post("/homes/<homeId>/reinstate")
def reinstate_home(homeId):
    uid, role, _ = authenticate({"ComplianceOfficer"})
    home = get_or_404(db.homes, homeId)
    b = body()
    no_unknown(b, set())
    if home["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Home must be SUSPENDED to reinstate")
    home["status"] = "ACTIVE"
    touch(home)
    return ok(serialize(home))


@app.post("/homes/<homeId>/close")
def close_home(homeId):
    uid, role, _ = authenticate({"AgencyAdmin"})
    home = get_or_404(db.homes, homeId)
    b = body()
    no_unknown(b, set())
    if home["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Home must be ACTIVE to close")
    recompute_occupancy(home)
    pending = any(ba["home_id"] == home["id"] and ba["status"] == "PENDING" for ba in db.beds.values())
    if home["current_occupancy"] != 0 or pending:
        err("ERR_HOME_OCCUPIED", 409, "Home has ACTIVE residents or PENDING assignments")
    home["status"] = "CLOSED"
    touch(home)
    return ok(serialize(home))


@app.get("/homes/<homeId>/census")
def home_census(homeId):
    authenticate(ANY)
    home = get_or_404(db.homes, homeId)
    raw = request.args.get("as_of_date")
    if raw is None:
        bad("Query parameter as_of_date is required")
    try:
        d = parse_d(raw)
    except (ValueError, TypeError):
        bad("as_of_date must be an ISO date YYYY-MM-DD")
    recompute_occupancy(home)
    data = {
        "as_of_date": raw.strip(),
        "current_census": census_current(home["id"], d),
        "projected_census": census_projected(home["id"], d),
        "certified_bed_count": home["certified_bed_count"],
        "current_occupancy": home["current_occupancy"],
    }
    return ok(data)


@app.get("/homes/<homeId>/staffing-check")
def home_staffing_check(homeId):
    authenticate(ANY)
    home = get_or_404(db.homes, homeId)
    raw_date = request.args.get("shift_date")
    raw_type = request.args.get("shift_type")
    if raw_date is None:
        bad("Query parameter shift_date is required")
    if raw_type is None:
        bad("Query parameter shift_type is required")
    try:
        d = parse_d(raw_date)
    except (ValueError, TypeError):
        bad("shift_date must be an ISO date YYYY-MM-DD")
    if raw_type not in ("DAY", "NIGHT"):
        bad("shift_type must be DAY or NIGHT")
    agency = db.agencies.get(home["agency_id"])
    ratio = agency["day_staff_ratio"] if raw_type == "DAY" else agency["night_staff_ratio"]

    weighted = 0
    for ba in db.beds.values():
        if ba["home_id"] != home["id"] or ba["status"] != "ACTIVE":
            continue
        mi = parse_d(ba["move_in_date"])
        mo = parse_d(ba["move_out_date"]) if ba.get("move_out_date") else None
        if not (mi <= d and (mo is None or mo > d)):
            continue
        ind = db.individuals.get(ba["individual_id"])
        w = 2 if (ind is not None and ind.get("mobility_level") == "WHEELCHAIR") else 1
        weighted += w

    required = 0 if weighted == 0 else -(-weighted // ratio)

    date_str = d.strftime("%Y-%m-%d")
    home_shifts = []
    scheduled = 0
    for s in db.shifts.values():
        if s["home_id"] != home["id"]:
            continue
        if s["shift_type"] != raw_type:
            continue
        if s["window_start"][:10] != date_str:
            continue
        home_shifts.append(s)
        if s["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED"):
            scheduled += 1

    shift_ids = {s["id"] for s in home_shifts}
    actual_staff = set()
    for v in db.visits.values():
        if v.get("shift_id") in shift_ids and v["verification_status"] == "VERIFIED":
            actual_staff.add(v["staff_member_id"])
    actual = len(actual_staff)

    data = {
        "shift_date": date_str,
        "shift_type": raw_type,
        "weighted_census": weighted,
        "required_dsps": required,
        "scheduled_dsps": scheduled,
        "actual_dsps": actual,
        "compliant_scheduled": scheduled >= required,
        "compliant_actual": actual >= required,
    }
    return ok(data)


# ============================================================================
# Individuals
# ============================================================================


@app.post("/individuals")
def create_individual():
    uid, role, _ = authenticate({"CaseManager"})
    b = body()
    agency_id = need(b, "agency_id")
    if not isinstance(agency_id, str):
        bad("agency_id must be a string")
    get_or_404(db.agencies, agency_id, "Agency not found")
    ind = base_entity()
    ind.update({
        "agency_id": agency_id,
        "legal_name": v_str(need(b, "legal_name"), "legal_name"),
        "medicaid_id": v_str(need(b, "medicaid_id"), "medicaid_id"),
        "date_of_birth": v_date(need(b, "date_of_birth"), "date_of_birth"),
        "mobility_level": v_enum(need(b, "mobility_level"), "mobility_level",
                                 ("AMBULATORY", "ASSIST", "WHEELCHAIR")),
        "status": "APPLICANT",
        "enrolled_at": None,
    })
    for other in db.individuals.values():
        if other["medicaid_id"] == ind["medicaid_id"]:
            bad("medicaid_id must be unique across the system")
    no_unknown(b, {"agency_id", "legal_name", "medicaid_id", "date_of_birth", "mobility_level"})
    db.individuals[ind["id"]] = ind
    return ok(serialize(ind), "object", 201)


@app.get("/individuals")
def list_individuals():
    authenticate(ANY)
    filters = {}
    for f in ("agency_id", "status", "mobility_level"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.individuals.values()), filters))


@app.get("/individuals/<individualId>")
def get_individual(individualId):
    authenticate(ANY)
    ind = get_or_404(db.individuals, individualId)
    return ok(serialize(ind))


@app.post("/individuals/<individualId>/enroll")
def enroll_individual(individualId):
    uid, role, _ = authenticate({"QIDP"})
    ind = get_or_404(db.individuals, individualId)
    b = body()
    no_unknown(b, set())
    if ind["status"] != "APPLICANT":
        err("ERR_INVALID_STATE", 409, "Individual must be APPLICANT to enroll")
    ind["status"] = "ENROLLED"
    ind["enrolled_at"] = now_iso()
    touch(ind)
    return ok(serialize(ind))


@app.post("/individuals/<individualId>/discharge")
def discharge_individual(individualId):
    uid, role, _ = authenticate({"QIDP"})
    ind = get_or_404(db.individuals, individualId)
    b = body()
    no_unknown(b, set())
    if ind["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "Individual must be ENROLLED to discharge")
    ind["status"] = "DISCHARGED"
    touch(ind)
    today_str = today().strftime("%Y-%m-%d")
    affected_homes = set()
    for ba in db.beds.values():
        if ba["individual_id"] != ind["id"]:
            continue
        if ba["status"] == "ACTIVE":
            ba["status"] = "ENDED"
            ba["move_out_date"] = today_str
            touch(ba)
            affected_homes.add(ba["home_id"])
        elif ba["status"] == "PENDING":
            ba["status"] = "CANCELLED"
            touch(ba)
    for hid in affected_homes:
        home = db.homes.get(hid)
        if home is not None:
            recompute_occupancy(home)
    for auth in db.auths.values():
        if auth["individual_id"] == ind["id"] and auth["status"] in ("PENDING", "APPROVED", "ACTIVE", "SUSPENDED"):
            auth["status"] = "CANCELLED"
            touch(auth)
    for isp in db.isps.values():
        if isp["individual_id"] == ind["id"] and isp["status"] == "ACTIVE":
            isp["status"] = "DISCONTINUED"
            touch(isp)
    for bp in db.bsps.values():
        if bp["individual_id"] == ind["id"] and bp["status"] == "ACTIVE":
            bp["status"] = "EXPIRED"
            touch(bp)
    return ok(serialize(ind))


# ============================================================================
# ISPs
# ============================================================================


@app.post("/isps")
def create_isp():
    uid, role, _ = authenticate({"CaseManager", "QIDP"})
    b = body()
    individual_id = need(b, "individual_id")
    if not isinstance(individual_id, str):
        bad("individual_id must be a string")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    # OCC check (before business logic)
    exp = b.get("expected_individual_version")
    if exp is None or isinstance(exp, bool) or not isinstance(exp, int):
        bad("expected_individual_version is required and must be an integer")
    if exp != ind["version"]:
        err("ERR_STALE_VERSION", 412, "expected_individual_version does not match the individual's current version")
    # input shape
    pys = v_date(need(b, "plan_year_start"), "plan_year_start")
    pye = v_date(need(b, "plan_year_end"), "plan_year_end")
    if not parse_d(pye) > parse_d(pys):
        bad("plan_year_end must be after plan_year_start")
    goals = v_str(need(b, "goals_summary"), "goals_summary", 10)
    meeting_date = None
    if b.get("meeting_date") is not None:
        meeting_date = v_date(b["meeting_date"], "meeting_date")
    no_unknown(b, {"individual_id", "plan_year_start", "plan_year_end", "goals_summary",
                   "meeting_date", "expected_individual_version"})
    isp = base_entity()
    isp.update({
        "individual_id": individual_id,
        "authored_by_staff_id": uid,
        "plan_year_start": pys,
        "plan_year_end": pye,
        "goals_summary": goals,
        "meeting_date": meeting_date,
        "status": "DRAFT",
        "amendment_count": 0,
        "activated_at": None,
        "approved_by_staff_id": None,
    })
    # supersede existing DRAFT ISP of the same individual
    for other in db.isps.values():
        if other["individual_id"] == individual_id and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            touch(other)
    db.isps[isp["id"]] = isp
    touch(ind)  # creating an ISP increments the Individual's version
    return ok(serialize(isp), "object", 201)


@app.get("/isps")
def list_isps():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "status", "authored_by_staff_id", "approved_by_staff_id"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.isps.values()), filters))


@app.get("/isps/<ispId>")
def get_isp(ispId):
    authenticate(ANY)
    isp = get_or_404(db.isps, ispId)
    return ok(serialize(isp))


@app.post("/isps/<ispId>/submit-review")
def isp_submit_review(ispId):
    uid, role, _ = authenticate({"CaseManager", "QIDP"})
    isp = get_or_404(db.isps, ispId)
    b = body()
    no_unknown(b, set())
    if isp["status"] not in ("DRAFT", "AMENDMENT_DRAFT"):
        err("ERR_INVALID_STATE", 409, "ISP must be DRAFT or AMENDMENT_DRAFT to submit for review")
    if isp["status"] == "DRAFT" and len(isp.get("goals_summary") or "") < 10:
        err("ERR_INVALID_REQUEST", 400, "goals_summary must be at least 10 characters")
    isp["status"] = "PENDING_REVIEW"
    touch(isp)
    return ok(serialize(isp))


@app.post("/isps/<ispId>/approve")
def isp_approve(ispId):
    uid, role, _ = authenticate({"QIDP"})
    isp = get_or_404(db.isps, ispId)
    b = body()
    no_unknown(b, set())
    if isp["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE", 409, "ISP must be PENDING_REVIEW to approve")
    if uid == isp["authored_by_staff_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from the ISP author")
    isp["approved_by_staff_id"] = uid
    isp["status"] = "APPROVED"
    touch(isp)
    return ok(serialize(isp))


@app.post("/isps/<ispId>/return")
def isp_return(ispId):
    uid, role, _ = authenticate({"QIDP"})
    isp = get_or_404(db.isps, ispId)
    b = body()
    no_unknown(b, {"return_reason"})
    if isp["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE", 409, "ISP must be PENDING_REVIEW to return")
    isp["status"] = "DRAFT"
    touch(isp)
    return ok(serialize(isp))


@app.post("/isps/<ispId>/activate")
def isp_activate(ispId):
    uid, role, _ = authenticate({"QIDP"})
    isp = get_or_404(db.isps, ispId)
    b = body()
    no_unknown(b, set())
    if isp["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "ISP must be APPROVED to activate")
    ind = db.individuals.get(isp["individual_id"])
    if ind is None or ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED to activate an ISP")
    isp["status"] = "ACTIVE"
    isp["activated_at"] = now_iso()
    touch(isp)
    # create-with-supersede at activation
    for other in db.isps.values():
        if other["id"] != isp["id"] and other["individual_id"] == isp["individual_id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    return ok(serialize(isp))


@app.post("/isps/<ispId>/amend")
def isp_amend(ispId):
    uid, role, _ = authenticate({"CaseManager", "QIDP"})
    isp = get_or_404(db.isps, ispId)
    b = body()
    exp = b.get("expected_isp_version")
    if exp is None or isinstance(exp, bool) or not isinstance(exp, int):
        bad("expected_isp_version is required and must be an integer")
    if exp != isp["version"]:
        err("ERR_STALE_VERSION", 412, "expected_isp_version does not match the ISP's current version")
    if isp["status"] not in ("ACTIVE", "AMENDMENT_DRAFT"):
        err("ERR_INVALID_STATE", 409, "ISP must be ACTIVE or AMENDMENT_DRAFT to amend")
    if b.get("goals_summary") is not None:
        isp["goals_summary"] = v_str(b["goals_summary"], "goals_summary", 10)
    if b.get("plan_year_end") is not None:
        pye = v_date(b["plan_year_end"], "plan_year_end")
        if not parse_d(pye) > parse_d(isp["plan_year_start"]):
            bad("plan_year_end must be after plan_year_start")
        isp["plan_year_end"] = pye
    no_unknown(b, {"expected_isp_version", "goals_summary", "plan_year_end"})
    isp["amendment_count"] = isp.get("amendment_count", 0) + 1
    isp["status"] = "AMENDMENT_DRAFT"
    touch(isp)
    return ok(serialize(isp))


# ============================================================================
# Service authorizations
# ============================================================================

UNIT_CAP_CENTS = 5000000
INDIVIDUAL_CAP_CENTS = 20000000


@app.post("/authorizations")
def create_authorization():
    uid, role, _ = authenticate({"CaseManager"})
    b = body()
    individual_id = need(b, "individual_id")
    isp_id = need(b, "isp_id")
    if not isinstance(individual_id, str) or not isinstance(isp_id, str):
        bad("individual_id and isp_id must be strings")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    isp = get_or_404(db.isps, isp_id, "ISP not found")
    # domain state
    if ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED")
    if isp["status"] != "ACTIVE":
        err("ERR_ISP_NOT_ACTIVE", 409, "Anchored ISP must be ACTIVE")
    # span containment (temporal)
    span_start = v_date(need(b, "span_start"), "span_start")
    span_end = v_date(need(b, "span_end"), "span_end")
    ss = parse_d(span_start)
    se = parse_d(span_end)
    if ss < parse_d(isp["plan_year_start"]) or se < ss or se > parse_d(isp["plan_year_end"]):
        err("ERR_OUT_OF_SPAN", 422, "Authorization span must lie inside the linked ISP plan year")
    # fiscal caps (need integer fields)
    units = v_int(need(b, "authorized_units"), "authorized_units", 1)
    rate = v_int(need(b, "rate_cents"), "rate_cents", 1)
    if units * rate > UNIT_CAP_CENTS:
        err("ERR_UNIT_CAP_EXCEEDED", 422, "authorized_units * rate_cents exceeds the per-authorization cap")
    total = units * rate
    for a in db.auths.values():
        if a["individual_id"] == individual_id and a["status"] != "CANCELLED":
            total += a["authorized_units"] * a["rate_cents"]
    if total > INDIVIDUAL_CAP_CENTS:
        err("ERR_INDIVIDUAL_CAP_EXCEEDED", 422, "Aggregate authorized value exceeds the per-individual annual cap")
    # remaining shape
    service_code = v_enum(need(b, "service_code"), "service_code",
                          ("RES_HAB", "DAY_PROG", "RESPITE", "SUPPORTED_EMPLOYMENT"))
    unit_type = v_enum(need(b, "unit_type"), "unit_type", ("FIFTEEN_MIN", "DAY"))
    if isp["individual_id"] != individual_id:
        bad("isp_id does not belong to the stated individual")
    no_unknown(b, {"individual_id", "isp_id", "service_code", "unit_type",
                   "authorized_units", "rate_cents", "span_start", "span_end"})
    auth = base_entity()
    auth.update({
        "individual_id": individual_id,
        "isp_id": isp_id,
        "service_code": service_code,
        "unit_type": unit_type,
        "authorized_units": units,
        "rate_cents": rate,
        "span_start": span_start,
        "span_end": span_end,
        "consumed_units": 0,
        "status": "PENDING",
    })
    db.auths[auth["id"]] = auth
    return ok(serialize(auth), "object", 201)


@app.get("/authorizations")
def list_authorizations():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "isp_id", "service_code", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.auths.values()), filters))


@app.get("/authorizations/<authId>")
def get_authorization(authId):
    authenticate(ANY)
    auth = get_or_404(db.auths, authId)
    return ok(serialize(auth))


@app.post("/authorizations/<authId>/approve")
def approve_authorization(authId):
    uid, role, _ = authenticate({"QIDP"})
    auth = get_or_404(db.auths, authId)
    b = body()
    no_unknown(b, set())
    if auth["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Authorization must be PENDING to approve")
    auth["status"] = "APPROVED"
    today_d = today()
    if parse_d(auth["span_start"]) <= today_d <= parse_d(auth["span_end"]):
        auth["status"] = "ACTIVE"
    touch(auth)
    return ok(serialize(auth))


@app.post("/authorizations/<authId>/cancel")
def cancel_authorization(authId):
    uid, role, _ = authenticate({"CaseManager"})
    auth = get_or_404(db.auths, authId)
    b = body()
    no_unknown(b, set())
    if auth["status"] not in ("PENDING", "APPROVED", "ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "Authorization cannot be cancelled from its current state")
    auth["status"] = "CANCELLED"
    touch(auth)
    return ok(serialize(auth))


@app.post("/authorizations/<authId>/resume")
def resume_authorization(authId):
    uid, role, _ = authenticate({"QIDP"})
    auth = get_or_404(db.auths, authId)
    b = body()
    no_unknown(b, set())
    if auth["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Authorization must be SUSPENDED to resume")
    isp = db.isps.get(auth["isp_id"])
    if isp is None or isp["status"] != "ACTIVE":
        err("ERR_ISP_NOT_ACTIVE", 409, "Linked ISP must be ACTIVE to resume")
    today_d = today()
    if not (parse_d(auth["span_start"]) <= today_d <= parse_d(auth["span_end"])):
        err("ERR_OUT_OF_SPAN", 422, "Today is outside the authorization span")
    auth["status"] = "ACTIVE"
    touch(auth)
    return ok(serialize(auth))


# ============================================================================
# Staff
# ============================================================================


@app.post("/staff")
def create_staff():
    uid, role, _ = authenticate({"AgencyAdmin"})
    b = body()
    agency_id = need(b, "agency_id")
    if not isinstance(agency_id, str):
        bad("agency_id must be a string")
    get_or_404(db.agencies, agency_id, "Agency not found")
    certs = v_list(need(b, "certifications"), "certifications")
    for c in certs:
        if c not in ("MED_CERT", "BEHAVIOR_CERT", "CPR", "CDL"):
            bad("certifications must be a subset of [MED_CERT, BEHAVIOR_CERT, CPR, CDL]")
    staff = base_entity()
    staff.update({
        "agency_id": agency_id,
        "full_name": v_str(need(b, "full_name"), "full_name"),
        "staff_role": v_enum(need(b, "staff_role"), "staff_role", ("DSP", "CASE_MANAGER", "QIDP")),
        "certifications": certs,
        "hire_date": v_date(need(b, "hire_date"), "hire_date"),
        "status": "ACTIVE",
    })
    no_unknown(b, {"agency_id", "full_name", "staff_role", "certifications", "hire_date"})
    db.staff[staff["id"]] = staff
    return ok(serialize(staff), "object", 201)


@app.get("/staff")
def list_staff():
    authenticate(ANY)
    filters = {}
    for f in ("agency_id", "staff_role", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.staff.values()), filters))


@app.get("/staff/<staffId>")
def get_staff(staffId):
    authenticate(ANY)
    staff = get_or_404(db.staff, staffId)
    return ok(serialize(staff))


@app.post("/staff/<staffId>/terminate")
def terminate_staff(staffId):
    uid, role, _ = authenticate({"AgencyAdmin"})
    staff = get_or_404(db.staff, staffId)
    b = body()
    no_unknown(b, set())
    if staff["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "StaffMember must be ACTIVE to terminate")
    staff["status"] = "TERMINATED"
    touch(staff)
    now_dt = now()
    for s in db.shifts.values():
        if (s["staff_member_id"] == staff["id"] and s["status"] in ("SCHEDULED", "CONFIRMED")
                and parse_dt(s["window_start"]) > now_dt):
            s["status"] = "CANCELLED"
            touch(s)
    return ok(serialize(staff))


# ============================================================================
# Shifts
# ============================================================================


@app.post("/shifts")
def create_shift():
    uid, role, _ = authenticate({"AgencyAdmin"})
    b = body()
    home_id = need(b, "home_id")
    staff_member_id = need(b, "staff_member_id")
    if not isinstance(home_id, str) or not isinstance(staff_member_id, str):
        bad("home_id and staff_member_id must be strings")
    home = get_or_404(db.homes, home_id, "Home not found")
    staff = get_or_404(db.staff, staff_member_id, "Staff member not found")
    # domain state
    if home["status"] != "ACTIVE":
        err("ERR_HOME_NOT_ACTIVE", 409, "Home must be ACTIVE to create shifts")
    # safety: med pass certification
    rmp = b.get("requires_med_pass", False)
    if rmp is True and "MED_CERT" not in (staff.get("certifications") or []):
        err("ERR_CERTIFICATION_MISSING", 403, "Assigned staff must hold MED_CERT for a med-pass shift")
    # temporal: parse windows, 8h rest buffer
    ws = v_datetime(need(b, "window_start"), "window_start")
    we = v_datetime(need(b, "window_end"), "window_end")
    ws_dt = parse_dt(ws)
    we_dt = parse_dt(we)
    eight = timedelta(hours=8)
    for s in db.shifts.values():
        if s["staff_member_id"] != staff_member_id or s["status"] == "CANCELLED":
            continue
        e_ws = parse_dt(s["window_start"])
        e_we = parse_dt(s["window_end"])
        if ws_dt >= e_we + eight or we_dt + eight <= e_ws:
            continue
        err("ERR_SHIFT_OVERLAP", 409, "New shift violates the 8-hour rest buffer")
    # remaining shape
    if not ws_dt < we_dt:
        bad("window_start must be before window_end")
    shift_type = v_enum(need(b, "shift_type"), "shift_type", ("DAY", "NIGHT"))
    if not isinstance(rmp, bool):
        bad("requires_med_pass must be a boolean")
    no_unknown(b, {"home_id", "staff_member_id", "window_start", "window_end", "shift_type", "requires_med_pass"})
    shift = base_entity()
    shift.update({
        "home_id": home_id,
        "staff_member_id": staff_member_id,
        "window_start": ws,
        "window_end": we,
        "shift_type": shift_type,
        "requires_med_pass": rmp,
        "status": "SCHEDULED",
    })
    db.shifts[shift["id"]] = shift
    return ok(serialize(shift), "object", 201)


@app.get("/shifts")
def list_shifts():
    authenticate(ANY)
    filters = {}
    for f in ("home_id", "staff_member_id", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.shifts.values()), filters))


@app.get("/shifts/<shiftId>")
def get_shift(shiftId):
    authenticate(ANY)
    shift = get_or_404(db.shifts, shiftId)
    return ok(serialize(shift))


@app.post("/shifts/<shiftId>/confirm")
def confirm_shift(shiftId):
    uid, role, _ = authenticate({"DSP"})
    shift = get_or_404(db.shifts, shiftId)
    b = body()
    no_unknown(b, set())
    if shift["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Shift must be SCHEDULED to confirm")
    if uid != shift["staff_member_id"]:
        err("ERR_OWNERSHIP_MISMATCH", 403, "A DSP may confirm only their own shifts")
    shift["status"] = "CONFIRMED"
    touch(shift)
    return ok(serialize(shift))


@app.post("/shifts/<shiftId>/cancel")
def cancel_shift(shiftId):
    uid, role, _ = authenticate({"AgencyAdmin"})
    shift = get_or_404(db.shifts, shiftId)
    b = body()
    no_unknown(b, set())
    if shift["status"] not in ("SCHEDULED", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "Shift must be SCHEDULED or CONFIRMED to cancel")
    shift["status"] = "CANCELLED"
    touch(shift)
    return ok(serialize(shift))


# ============================================================================
# Bed assignments
# ============================================================================


def intervals_overlap(s1, e1, s2, e2):
    """Half-open [s,e) intersection; None end = open-ended."""
    if e1 is not None and s2 >= e1:
        return False
    if e2 is not None and s1 >= e2:
        return False
    return True


def bed_overlap_exists(home_id, bed_label, move_in, exclude_id=None, statuses=("PENDING", "ACTIVE")):
    for ba in db.beds.values():
        if ba["home_id"] != home_id or ba["bed_label"] != bed_label:
            continue
        if exclude_id is not None and ba["id"] == exclude_id:
            continue
        if ba["status"] not in statuses:
            continue
        e_mi = parse_d(ba["move_in_date"])
        e_mo = parse_d(ba["move_out_date"]) if ba.get("move_out_date") else None
        if intervals_overlap(move_in, None, e_mi, e_mo):
            return True
    return False


@app.post("/bed-assignments")
def create_bed_assignment():
    uid, role, _ = authenticate({"CaseManager"})
    b = body()
    home_id = need(b, "home_id")
    individual_id = need(b, "individual_id")
    if not isinstance(home_id, str) or not isinstance(individual_id, str):
        bad("home_id and individual_id must be strings")
    home = get_or_404(db.homes, home_id, "Home not found")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    # domain state
    if ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED")
    if home["status"] != "ACTIVE":
        err("ERR_HOME_NOT_ACTIVE", 409, "Home must be ACTIVE for admissions")
    # temporal: bed overlap against PENDING / ACTIVE
    move_in = v_date(need(b, "move_in_date"), "move_in_date")
    bed_label = v_str(need(b, "bed_label"), "bed_label")
    if bed_overlap_exists(home_id, bed_label, parse_d(move_in)):
        err("ERR_BED_OVERLAP", 409, "Overlapping assignment on the same bed")
    # constraint: posture gate
    recompute_posture(home)
    if home["compliance_posture"] == "CRITICAL":
        err("ERR_HOME_POSTURE_CRITICAL", 409, "Home compliance posture is CRITICAL")
    # constraint: capacity gate (projected census + 1 <= certified beds)
    if census_projected(home_id, parse_d(move_in)) + 1 > home["certified_bed_count"]:
        err("ERR_HOME_CAPACITY_EXCEEDED", 409, "Projected census plus the new admission exceeds certified_bed_count")
    no_unknown(b, {"home_id", "bed_label", "individual_id", "move_in_date"})
    ba = base_entity()
    ba.update({
        "home_id": home_id,
        "bed_label": bed_label,
        "individual_id": individual_id,
        "move_in_date": move_in,
        "move_out_date": None,
        "status": "PENDING",
    })
    db.beds[ba["id"]] = ba
    return ok(serialize(ba), "object", 201)


@app.get("/bed-assignments")
def list_bed_assignments():
    authenticate(ANY)
    filters = {}
    for f in ("home_id", "bed_label", "individual_id", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.beds.values()), filters))


@app.get("/bed-assignments/<baId>")
def get_bed_assignment(baId):
    authenticate(ANY)
    ba = get_or_404(db.beds, baId)
    return ok(serialize(ba))


@app.post("/bed-assignments/<baId>/move-in")
def bed_move_in(baId):
    uid, role, _ = authenticate({"QIDP"})
    ba = get_or_404(db.beds, baId)
    b = body()
    no_unknown(b, set())
    if ba["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Assignment must be PENDING to move in")
    home = get_or_404(db.homes, ba["home_id"], "Home not found")
    if home["status"] != "ACTIVE":
        err("ERR_HOME_NOT_ACTIVE", 409, "Home must be ACTIVE for move-in")
    if bed_overlap_exists(ba["home_id"], ba["bed_label"], parse_d(ba["move_in_date"]),
                          exclude_id=ba["id"], statuses=("ACTIVE",)):
        err("ERR_BED_OVERLAP", 409, "Overlapping ACTIVE assignment on the same bed")
    if parse_d(ba["move_in_date"]) > today():
        err("ERR_MOVE_IN_FUTURE", 422, "move_in_date is in the future")
    ba["status"] = "ACTIVE"
    touch(ba)
    recompute_occupancy(home)
    return ok(serialize(ba))


@app.post("/bed-assignments/<baId>/move-out")
def bed_move_out(baId):
    uid, role, _ = authenticate({"QIDP"})
    ba = get_or_404(db.beds, baId)
    b = body()
    if ba["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Assignment must be ACTIVE to move out")
    if b.get("move_out_date") is not None:
        mo = v_date(b["move_out_date"], "move_out_date")
    else:
        mo = today().strftime("%Y-%m-%d")
    no_unknown(b, {"move_out_date"})
    if not parse_d(mo) > parse_d(ba["move_in_date"]):
        bad("move_out_date must be after move_in_date")
    ba["move_out_date"] = mo
    ba["status"] = "ENDED"
    touch(ba)
    home = db.homes.get(ba["home_id"])
    if home is not None:
        recompute_occupancy(home)
    return ok(serialize(ba))


@app.post("/bed-assignments/<baId>/cancel")
def bed_cancel(baId):
    uid, role, _ = authenticate({"CaseManager"})
    ba = get_or_404(db.beds, baId)
    b = body()
    no_unknown(b, set())
    if ba["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Assignment must be PENDING to cancel")
    ba["status"] = "CANCELLED"
    touch(ba)
    return ok(serialize(ba))


# ============================================================================
# Medication orders & MAR events
# ============================================================================

HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@app.post("/medication-orders")
def create_med_order():
    uid, role, _ = authenticate({"QIDP"})
    b = body()
    individual_id = need(b, "individual_id")
    if not isinstance(individual_id, str):
        bad("individual_id must be a string")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    if ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED")
    sched = v_list(need(b, "schedule_times"), "schedule_times")
    if len(sched) == 0:
        bad("schedule_times must be a non-empty array")
    for t in sched:
        if not isinstance(t, str) or not HHMM_RE.match(t):
            bad("schedule_times entries must be HH:MM 24h strings")
    rw = b.get("requires_witness", False)
    if not isinstance(rw, bool):
        bad("requires_witness must be a boolean")
    mo = base_entity()
    mo.update({
        "individual_id": individual_id,
        "drug_name": v_str(need(b, "drug_name"), "drug_name"),
        "dosage": v_str(need(b, "dosage"), "dosage"),
        "schedule_times": sched,
        "requires_witness": rw,
        "start_date": v_date(need(b, "start_date"), "start_date"),
        "end_date": v_date(b["end_date"], "end_date") if b.get("end_date") is not None else None,
        "status": "ACTIVE",
    })
    no_unknown(b, {"individual_id", "drug_name", "dosage", "schedule_times",
                   "requires_witness", "start_date", "end_date"})
    db.medorders[mo["id"]] = mo
    return ok(serialize(mo), "object", 201)


@app.get("/medication-orders")
def list_med_orders():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.medorders.values()), filters))


@app.get("/medication-orders/<moId>")
def get_med_order(moId):
    authenticate(ANY)
    mo = get_or_404(db.medorders, moId)
    return ok(serialize(mo))


@app.post("/medication-orders/<moId>/discontinue")
def discontinue_med_order(moId):
    uid, role, _ = authenticate({"QIDP"})
    mo = get_or_404(db.medorders, moId)
    b = body()
    no_unknown(b, set())
    if mo["status"] != "ACTIVE":
        err("ERR_MED_ORDER_DISCONTINUED", 409, "Medication order is DISCONTINUED")
    mo["status"] = "DISCONTINUED"
    touch(mo)
    return ok(serialize(mo))


@app.post("/admin-events")
def create_admin_event():
    uid, role, staff = authenticate({"DSP"})
    b = body()
    mo_id = need(b, "medication_order_id")
    if not isinstance(mo_id, str):
        bad("medication_order_id must be a string")
    mo = get_or_404(db.medorders, mo_id, "Medication order not found")
    witness_id = b.get("witness_staff_id")
    if witness_id is not None:
        if not isinstance(witness_id, str):
            bad("witness_staff_id must be a string")
        get_or_404(db.staff, witness_id, "Witness staff member not found")
    # state: order must be ACTIVE
    if mo["status"] != "ACTIVE":
        err("ERR_MED_ORDER_DISCONTINUED", 409, "Medication order is DISCONTINUED")
    # safety: recording DSP must hold MED_CERT
    if "MED_CERT" not in (staff.get("certifications") or []):
        err("ERR_CERTIFICATION_MISSING", 403, "Recording DSP must hold MED_CERT")
    outcome = v_enum(need(b, "outcome"), "outcome", ("GIVEN", "REFUSED", "HELD", "MISSED"))
    # safety: witness rule
    if mo.get("requires_witness") and outcome == "GIVEN":
        if witness_id is None or witness_id == uid:
            err("ERR_WITNESS_REQUIRED", 400,
                "witness_staff_id is required and must differ from administered_by_staff_id")
    # temporal: administered_time within +/- 60 minutes of scheduled_time
    scheduled = v_datetime(need(b, "scheduled_time"), "scheduled_time")
    administered = None
    if b.get("administered_time") is not None:
        administered = v_datetime(b["administered_time"], "administered_time")
    if administered is None and outcome != "MISSED":
        bad("administered_time is required unless outcome is MISSED")
    if administered is not None:
        delta = abs((parse_dt(administered) - parse_dt(scheduled)).total_seconds())
        if delta > 60 * 60:
            err("ERR_OUT_OF_SPAN", 422, "administered_time is outside the +/- 60 minute window")
    no_unknown(b, {"medication_order_id", "scheduled_time", "outcome", "administered_time", "witness_staff_id"})
    ev = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "medication_order_id": mo_id,
        "administered_by_staff_id": uid,
        "witness_staff_id": witness_id,
        "scheduled_time": scheduled,
        "administered_time": administered,
        "outcome": outcome,
    }
    db.adminevents[ev["id"]] = ev
    return ok(serialize(ev), "object", 201)


@app.get("/admin-events")
def list_admin_events():
    authenticate(ANY)
    filters = {}
    for f in ("medication_order_id", "administered_by_staff_id", "witness_staff_id", "outcome"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.adminevents.values()), filters))


@app.get("/admin-events/<eventId>")
def get_admin_event(eventId):
    authenticate(ANY)
    ev = get_or_404(db.adminevents, eventId)
    return ok(serialize(ev))


@app.get("/individuals/<individualId>/med-adherence")
def med_adherence(individualId):
    authenticate(ANY)
    ind = get_or_404(db.individuals, individualId)
    raw = request.args.get("as_of")
    if raw is None:
        bad("Query parameter as_of is required")
    try:
        as_of = parse_dt(raw)
    except (ValueError, TypeError):
        bad("as_of must be an ISO 8601 datetime")
    window_start = as_of - timedelta(days=30)
    order_ids = {mo["id"] for mo in db.medorders.values() if mo["individual_id"] == ind["id"]}
    total = 0
    given = 0
    for ev in db.adminevents.values():
        if ev["medication_order_id"] not in order_ids:
            continue
        st = parse_dt(ev["scheduled_time"])
        if window_start <= st <= as_of:
            total += 1
            if ev["outcome"] == "GIVEN":
                given += 1
    pct = None if total == 0 else (100 * given) // total
    data = {
        "window_start": fmt_dt(window_start),
        "window_end": fmt_dt(as_of),
        "total_events": total,
        "given_count": given,
        "adherence_pct": pct,
    }
    return ok(data)


# ============================================================================
# Behavior support plans
# ============================================================================


@app.post("/behavior-plans")
def create_bsp():
    uid, role, _ = authenticate({"CaseManager", "QIDP"})
    b = body()
    individual_id = need(b, "individual_id")
    if not isinstance(individual_id, str):
        bad("individual_id must be a string")
    get_or_404(db.individuals, individual_id, "Individual not found")
    level = v_enum(need(b, "level"), "level", ("LEVEL_1", "LEVEL_2"))
    ri = v_list(need(b, "restrictive_interventions"), "restrictive_interventions")
    for item in ri:
        if not isinstance(item, str):
            bad("restrictive_interventions entries must be strings")
    no_unknown(b, {"individual_id", "level", "restrictive_interventions"})
    bp = base_entity()
    bp.update({
        "individual_id": individual_id,
        "authored_by_staff_id": uid,
        "level": level,
        "restrictive_interventions": ri,
        "status": "DRAFT",
        "approved_at": None,
        "review_due_at": None,
        "approved_by_staff_id": None,
    })
    db.bsps[bp["id"]] = bp
    return ok(serialize(bp), "object", 201)


@app.get("/behavior-plans")
def list_bsps():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "status", "level", "authored_by_staff_id", "approved_by_staff_id"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.bsps.values()), filters))


@app.get("/behavior-plans/<bpId>")
def get_bsp(bpId):
    authenticate(ANY)
    bp = get_or_404(db.bsps, bpId)
    return ok(serialize(bp))


@app.post("/behavior-plans/<bpId>/submit-hrc")
def bsp_submit_hrc(bpId):
    uid, role, _ = authenticate({"CaseManager", "QIDP"})
    bp = get_or_404(db.bsps, bpId)
    b = body()
    no_unknown(b, set())
    if bp["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Plan must be DRAFT to submit to HRC")
    ri = bp.get("restrictive_interventions") or []
    if bp["level"] == "LEVEL_2" and len(ri) == 0:
        err("ERR_RESTRICTIVE_INTERVENTION_MISMATCH", 400,
            "LEVEL_2 plans require non-empty restrictive_interventions")
    if bp["level"] == "LEVEL_1" and len(ri) != 0:
        err("ERR_RESTRICTIVE_INTERVENTION_MISMATCH", 400,
            "LEVEL_1 plans require empty restrictive_interventions")
    bp["status"] = "HRC_REVIEW"
    touch(bp)
    return ok(serialize(bp))


@app.post("/behavior-plans/<bpId>/hrc-approve")
def bsp_hrc_approve(bpId):
    uid, role, _ = authenticate({"QIDP"})
    bp = get_or_404(db.bsps, bpId)
    b = body()
    no_unknown(b, set())
    if bp["status"] != "HRC_REVIEW":
        err("ERR_INVALID_STATE", 409, "Plan must be HRC_REVIEW to approve")
    if uid == bp["authored_by_staff_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from the plan author")
    bp["approved_at"] = now_iso()
    bp["approved_by_staff_id"] = uid
    bp["status"] = "APPROVED"
    touch(bp)
    return ok(serialize(bp))


@app.post("/behavior-plans/<bpId>/hrc-reject")
def bsp_hrc_reject(bpId):
    uid, role, _ = authenticate({"QIDP"})
    bp = get_or_404(db.bsps, bpId)
    b = body()
    no_unknown(b, set())
    if bp["status"] != "HRC_REVIEW":
        err("ERR_INVALID_STATE", 409, "Plan must be HRC_REVIEW to reject")
    bp["status"] = "DRAFT"
    touch(bp)
    return ok(serialize(bp))


@app.post("/behavior-plans/<bpId>/activate")
def bsp_activate(bpId):
    uid, role, _ = authenticate({"QIDP"})
    bp = get_or_404(db.bsps, bpId)
    b = body()
    no_unknown(b, set())
    if bp["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Plan must be APPROVED to activate")
    ind = db.individuals.get(bp["individual_id"])
    if ind is None or ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED to activate a plan")
    days = 180 if bp["level"] == "LEVEL_2" else 365
    bp["review_due_at"] = fmt_dt(parse_dt(bp["approved_at"]) + timedelta(days=days))
    bp["status"] = "ACTIVE"
    touch(bp)
    for other in db.bsps.values():
        if other["id"] != bp["id"] and other["individual_id"] == bp["individual_id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    return ok(serialize(bp))


# ============================================================================
# Incidents
# ============================================================================

SEVERITY_WINDOW_HOURS = {"CRITICAL": 24, "HIGH": 48}


def hold_draft_claims_for_home(home):
    """Cascade link 2/3: DRAFT claims of this home's residents -> HOLD."""
    affected_agencies = {home["agency_id"]}
    for ind_id in residents_of_home(home["id"]):
        for c in db.claims.values():
            if c["individual_id"] == ind_id and c["status"] == "DRAFT":
                c["status"] = "HOLD"
                touch(c)
                ind = db.individuals.get(ind_id)
                if ind is not None:
                    affected_agencies.add(ind["agency_id"])
    for ag in affected_agencies:
        recompute_held_count(ag)


def release_hold_claims_for_home(home):
    """Close cascade: HOLD claims of this home's residents -> DRAFT."""
    affected_agencies = {home["agency_id"]}
    for ind_id in residents_of_home(home["id"]):
        for c in db.claims.values():
            if c["individual_id"] == ind_id and c["status"] == "HOLD":
                c["status"] = "DRAFT"
                touch(c)
                ind = db.individuals.get(ind_id)
                if ind is not None:
                    affected_agencies.add(ind["agency_id"])
    for ag in affected_agencies:
        recompute_held_count(ag)


@app.post("/incidents")
def create_incident():
    uid, role, _ = authenticate({"DSP", "QIDP"})
    b = body()
    individual_id = need(b, "individual_id")
    home_id = need(b, "home_id")
    if not isinstance(individual_id, str) or not isinstance(home_id, str):
        bad("individual_id and home_id must be strings")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    home = get_or_404(db.homes, home_id, "Home not found")
    if ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED")
    if home["status"] != "ACTIVE":
        err("ERR_HOME_NOT_ACTIVE", 409, "Home must be ACTIVE to record incidents")
    occurred = v_datetime(need(b, "occurred_at"), "occurred_at")
    discovered = v_datetime(need(b, "discovered_at"), "discovered_at")
    if parse_dt(discovered) < parse_dt(occurred):
        bad("discovered_at must be on or after occurred_at")
    inc = base_entity()
    inc.update({
        "individual_id": individual_id,
        "home_id": home_id,
        "submitted_by_staff_id": uid,
        "category": v_enum(need(b, "category"), "category",
                           ("MED_ERROR", "INJURY", "ABUSE_ALLEGATION", "BEHAVIOR", "ELOPEMENT")),
        "severity": v_enum(need(b, "severity"), "severity", ("LOW", "MEDIUM", "HIGH", "CRITICAL")),
        "occurred_at": occurred,
        "discovered_at": discovered,
        "description": v_str(need(b, "description"), "description", 10),
        "status": "DRAFT",
        "report_due_at": None,
        "submitted_at": None,
        "is_late": False,
    })
    no_unknown(b, {"individual_id", "home_id", "category", "severity",
                   "occurred_at", "discovered_at", "description"})
    db.incidents[inc["id"]] = inc
    return ok(serialize(inc), "object", 201)


@app.get("/incidents")
def list_incidents():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "home_id", "severity", "status", "submitted_by_staff_id"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.incidents.values()), filters))


@app.get("/incidents/<incidentId>")
def get_incident(incidentId):
    authenticate(ANY)
    inc = get_or_404(db.incidents, incidentId)
    return ok(serialize(inc))


def _submit_incident(inc):
    inc["submitted_at"] = now_iso()
    if inc.get("report_due_at") is None:
        hours = SEVERITY_WINDOW_HOURS.get(inc["severity"], 72)
        inc["report_due_at"] = fmt_dt(parse_dt(inc["discovered_at"]) + timedelta(hours=hours))
    inc["is_late"] = parse_dt(inc["submitted_at"]) > parse_dt(inc["report_due_at"])
    inc["status"] = "SUBMITTED"
    touch(inc)


@app.post("/incidents/<incidentId>/submit")
def submit_incident(incidentId):
    uid, role, _ = authenticate({"DSP", "QIDP"})
    inc = get_or_404(db.incidents, incidentId)
    b = body()
    no_unknown(b, set())
    if inc["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Incident must be DRAFT to submit")
    if uid != inc["submitted_by_staff_id"]:
        err("ERR_OWNERSHIP_MISMATCH", 403, "Only the incident submitter may submit it")
    _submit_incident(inc)
    # posture cascade (link 1) — recomputed on every submit
    home = db.homes.get(inc["home_id"])
    if home is not None:
        posture = recompute_posture(home)
        if posture == "CRITICAL":
            hold_draft_claims_for_home(home)
    return ok(serialize(inc))


@app.post("/incidents/<incidentId>/start-review")
def start_review_incident(incidentId):
    uid, role, _ = authenticate({"QIDP"})
    inc = get_or_404(db.incidents, incidentId)
    b = body()
    no_unknown(b, set())
    if inc["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Incident must be SUBMITTED to start review")
    inc["status"] = "UNDER_REVIEW"
    touch(inc)
    return ok(serialize(inc))


@app.post("/incidents/<incidentId>/request-info")
def request_info_incident(incidentId):
    uid, role, _ = authenticate({"QIDP"})
    inc = get_or_404(db.incidents, incidentId)
    b = body()
    no_unknown(b, set())
    if inc["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Incident must be UNDER_REVIEW to request info")
    inc["status"] = "NEEDS_INFO"
    touch(inc)
    return ok(serialize(inc))


@app.post("/incidents/<incidentId>/resubmit")
def resubmit_incident(incidentId):
    uid, role, _ = authenticate({"DSP", "QIDP"})
    inc = get_or_404(db.incidents, incidentId)
    b = body()
    no_unknown(b, set())
    if inc["status"] != "NEEDS_INFO":
        err("ERR_INVALID_STATE", 409, "Incident must be NEEDS_INFO to resubmit")
    if uid != inc["submitted_by_staff_id"]:
        err("ERR_OWNERSHIP_MISMATCH", 403, "Only the incident submitter may resubmit it")
    # resubmission recomputes is_late against the ORIGINAL report_due_at
    inc["submitted_at"] = now_iso()
    inc["is_late"] = parse_dt(inc["submitted_at"]) > parse_dt(inc["report_due_at"])
    inc["status"] = "SUBMITTED"
    touch(inc)
    return ok(serialize(inc))


@app.post("/incidents/<incidentId>/close")
def close_incident(incidentId):
    uid, role, _ = authenticate({"QIDP"})
    inc = get_or_404(db.incidents, incidentId)
    b = body()
    no_unknown(b, set())
    if inc["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Incident must be UNDER_REVIEW to close")
    if uid == inc["submitted_by_staff_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Closer must differ from the incident submitter")
    inc["status"] = "CLOSED"
    touch(inc)
    home = db.homes.get(inc["home_id"])
    if home is not None:
        posture = recompute_posture(home)
        if posture != "CRITICAL":
            release_hold_claims_for_home(home)
    return ok(serialize(inc))


# ============================================================================
# EVV visits
# ============================================================================


def compute_provisional_units(unit_type, check_in, check_out):
    dur = Decimal(str((parse_dt(check_out) - parse_dt(check_in)).total_seconds())) / Decimal(60)
    if unit_type == "FIFTEEN_MIN":
        units = int((dur / Decimal(15)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return max(1, units)
    # DAY
    return 1 if dur >= 360 else 0


@app.post("/evv-visits")
def create_evv_visit():
    uid, role, staff = authenticate({"DSP"})
    b = body()
    individual_id = need(b, "individual_id")
    authorization_id = need(b, "authorization_id")
    if not isinstance(individual_id, str) or not isinstance(authorization_id, str):
        bad("individual_id and authorization_id must be strings")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    auth = get_or_404(db.auths, authorization_id, "Authorization not found")
    shift = None
    shift_id = b.get("shift_id")
    if shift_id is not None:
        if not isinstance(shift_id, str):
            bad("shift_id must be a string")
        shift = get_or_404(db.shifts, shift_id, "Shift not found")
    # domain state
    if ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED")
    if auth["status"] != "ACTIVE":
        err("ERR_AUTHORIZATION_NOT_ACTIVE", 409, "Authorization must be ACTIVE")
    # temporal: span containment (inclusive both ends)
    service_date = v_date(need(b, "service_date"), "service_date")
    if not (parse_d(auth["span_start"]) <= parse_d(service_date) <= parse_d(auth["span_end"])):
        err("ERR_OUT_OF_SPAN", 422, "service_date is outside the authorization span")
    # referential: FK coherence
    if auth["individual_id"] != individual_id:
        bad("authorization_id does not belong to the stated individual")
    if shift is not None and shift["staff_member_id"] != uid:
        bad("shift_id does not belong to the visit's staff member")
    # remaining shape
    check_in = v_datetime(need(b, "check_in_at"), "check_in_at")
    check_out = v_datetime(need(b, "check_out_at"), "check_out_at")
    if not parse_dt(check_out) > parse_dt(check_in):
        bad("check_out_at must be after check_in_at")
    geo = v_bool(need(b, "geo_within_radius"), "geo_within_radius")
    no_unknown(b, {"individual_id", "authorization_id", "service_date", "check_in_at",
                   "check_out_at", "geo_within_radius", "shift_id"})
    visit = base_entity()
    visit.update({
        "individual_id": individual_id,
        "authorization_id": authorization_id,
        "staff_member_id": uid,
        "shift_id": shift_id,
        "service_date": service_date,
        "check_in_at": check_in,
        "check_out_at": check_out,
        "geo_within_radius": geo,
        "provisional_units": compute_provisional_units(auth["unit_type"], check_in, check_out),
        "final_units": None,
        "verification_status": "PENDING" if geo else "EXCEPTION",
        "billing_status": "UNBILLED",
        "billed_claim_id": None,
        "allocated_units_entries": [],
    })
    db.visits[visit["id"]] = visit
    return ok(serialize(visit), "object", 201)


@app.get("/evv-visits")
def list_evv_visits():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "authorization_id", "staff_member_id", "shift_id",
              "verification_status", "billing_status", "billed_claim_id"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.visits.values()), filters))


@app.get("/evv-visits/<visitId>")
def get_evv_visit(visitId):
    authenticate(ANY)
    v = get_or_404(db.visits, visitId)
    return ok(serialize(v))


@app.post("/evv-visits/<visitId>/verify")
def verify_evv_visit(visitId):
    uid, role, _ = authenticate({"QIDP"})
    visit = get_or_404(db.visits, visitId)
    b = body()
    no_unknown(b, set())
    if visit["verification_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Visit must be PENDING to verify")
    visit["final_units"] = visit["provisional_units"]
    waterfall_allocate(visit, visit["final_units"])
    visit["verification_status"] = "VERIFIED"
    touch(visit)
    complete_linked_shift(visit)
    return ok(serialize(visit))


@app.post("/evv-visits/<visitId>/flag-exception")
def flag_evv_exception(visitId):
    uid, role, _ = authenticate({"QIDP"})
    visit = get_or_404(db.visits, visitId)
    b = body()
    no_unknown(b, set())
    if visit["verification_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Visit must be PENDING to flag as exception")
    visit["verification_status"] = "EXCEPTION"
    touch(visit)
    return ok(serialize(visit))


@app.post("/evv-visits/<visitId>/resolve-exception")
def resolve_evv_exception(visitId):
    uid, role, _ = authenticate({"QIDP"})
    visit = get_or_404(db.visits, visitId)
    b = body()
    if visit["verification_status"] != "EXCEPTION":
        err("ERR_INVALID_STATE", 409, "Visit must be EXCEPTION to resolve")
    adjusted = b.get("adjusted_minutes")
    if adjusted is None or isinstance(adjusted, bool) or not isinstance(adjusted, int) \
            or adjusted <= 0 or adjusted % 15 != 0:
        bad("adjusted_minutes must be a positive multiple of 15")
    note = b.get("resolution_note")
    if note is None:
        bad("resolution_note is required")
    v_str(note, "resolution_note")
    no_unknown(b, {"adjusted_minutes", "resolution_note"})
    visit["final_units"] = adjusted // 15
    waterfall_allocate(visit, visit["final_units"])
    visit["verification_status"] = "VERIFIED"
    touch(visit)
    complete_linked_shift(visit)
    return ok(serialize(visit))


@app.post("/evv-visits/<visitId>/reject")
def reject_evv_visit(visitId):
    uid, role, _ = authenticate({"QIDP"})
    visit = get_or_404(db.visits, visitId)
    b = body()
    if visit["verification_status"] not in ("PENDING", "EXCEPTION"):
        err("ERR_INVALID_STATE", 409, "Visit must be PENDING or EXCEPTION to reject")
    reason = b.get("reason")
    if reason is None:
        bad("reason is required")
    v_str(reason, "reason")
    no_unknown(b, {"reason"})
    visit["verification_status"] = "REJECTED"
    touch(visit)
    return ok(serialize(visit))


# ============================================================================
# Transport trips
# ============================================================================

VEHICLE_CAPACITY = 8


@app.post("/transport-trips")
def create_trip():
    uid, role, _ = authenticate({"AgencyAdmin"})
    b = body()
    home_id = need(b, "home_id")
    vehicle_id = need(b, "vehicle_id")
    if not isinstance(home_id, str) or not isinstance(vehicle_id, str):
        bad("home_id and vehicle_id must be strings")
    home = get_or_404(db.homes, home_id, "Home not found")
    legs = b.get("legs")
    if legs is None:
        bad("Missing required field: legs")
    if not isinstance(legs, list):
        bad("legs must be an array")
    # existence of leg individuals
    leg_inds = []
    for leg in legs:
        if not isinstance(leg, dict):
            bad("each leg must be an object")
        li = leg.get("individual_id")
        if not isinstance(li, str):
            bad("each leg requires an individual_id string")
        leg_inds.append(get_or_404(db.individuals, li, "Leg individual not found"))
    # domain state: individuals ENROLLED, then home ACTIVE
    for ind in leg_inds:
        if ind["status"] != "ENROLLED":
            err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Every leg individual must be ENROLLED")
    if home["status"] != "ACTIVE":
        err("ERR_HOME_NOT_ACTIVE", 409, "Home must be ACTIVE to schedule transport")
    # temporal: vehicle overlap (half-open, touching endpoints allowed)
    trip_date = v_date(need(b, "trip_date"), "trip_date")
    depart = v_datetime(need(b, "depart_at"), "depart_at")
    ret = v_datetime(need(b, "return_at"), "return_at")
    dep_dt = parse_dt(depart)
    ret_dt = parse_dt(ret)
    for t in db.trips.values():
        if t["vehicle_id"] != vehicle_id or t["trip_date"] != trip_date or t["status"] == "CANCELLED":
            continue
        e_dep = parse_dt(t["depart_at"])
        e_ret = parse_dt(t["return_at"])
        if dep_dt < e_ret and e_dep < ret_dt:
            err("ERR_VEHICLE_OVERLAP", 409, "Trip window intersects a non-CANCELLED trip for this vehicle and date")
    # constraint: vehicle capacity
    slots = 0
    for leg in legs:
        ws = leg.get("wheelchair_seat")
        slots += 2 if ws is True else 1
    if slots > VEHICLE_CAPACITY:
        err("ERR_VEHICLE_CAPACITY_EXCEEDED", 409, "Leg slots exceed vehicle capacity of 8")
    # constraint: DAY_PROG authorization + residency per leg
    td = parse_d(trip_date)
    for ind in leg_inds:
        resident = False
        for ba in db.beds.values():
            if ba["home_id"] != home_id or ba["individual_id"] != ind["id"] or ba["status"] != "ACTIVE":
                continue
            mi = parse_d(ba["move_in_date"])
            mo = parse_d(ba["move_out_date"]) if ba.get("move_out_date") else None
            if mi <= td and (mo is None or mo > td):
                resident = True
                break
        has_dp = False
        for a in db.auths.values():
            if (a["individual_id"] == ind["id"] and a["service_code"] == "DAY_PROG"
                    and a["status"] == "ACTIVE"
                    and parse_d(a["span_start"]) <= td <= parse_d(a["span_end"])):
                has_dp = True
                break
        if not resident or not has_dp:
            err("ERR_NO_DAY_PROG_AUTHORIZATION", 409,
                "A leg's individual lacks residency at this home or an ACTIVE DAY_PROG authorization covering trip_date")
    # remaining shape
    if not ret_dt > dep_dt:
        bad("return_at must be after depart_at")
    for leg in legs:
        ws = leg.get("wheelchair_seat")
        if not isinstance(ws, bool):
            bad("wheelchair_seat must be a boolean")
        pick = v_datetime(leg.get("pickup_at"), "pickup_at")
        drop = v_datetime(leg.get("dropoff_at"), "dropoff_at")
        if not parse_dt(pick) < parse_dt(drop):
            bad("pickup_at must be before dropoff_at")
        if parse_dt(pick) < dep_dt or parse_dt(drop) > ret_dt:
            bad("leg times must lie inside [depart_at, return_at]")
        extra = set(leg.keys()) - {"individual_id", "wheelchair_seat", "pickup_at", "dropoff_at"}
        if extra:
            bad("Unknown leg fields: %s" % ", ".join(sorted(extra)))
        leg["pickup_at"] = pick
        leg["dropoff_at"] = drop
    no_unknown(b, {"home_id", "vehicle_id", "trip_date", "depart_at", "return_at", "legs"})
    trip = base_entity()
    trip.update({
        "home_id": home_id,
        "vehicle_id": vehicle_id,
        "trip_date": trip_date,
        "depart_at": depart,
        "return_at": ret,
        "legs": legs,
        "occupied_slots": slots,
        "status": "SCHEDULED",
    })
    db.trips[trip["id"]] = trip
    return ok(serialize(trip), "object", 201)


@app.get("/transport-trips")
def list_trips():
    authenticate(ANY)
    filters = {}
    for f in ("home_id", "vehicle_id", "trip_date", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.trips.values()), filters))


@app.get("/transport-trips/<tripId>")
def get_trip(tripId):
    authenticate(ANY)
    t = get_or_404(db.trips, tripId)
    return ok(serialize(t))


@app.post("/transport-trips/<tripId>/cancel")
def cancel_trip(tripId):
    uid, role, _ = authenticate({"AgencyAdmin"})
    t = get_or_404(db.trips, tripId)
    b = body()
    no_unknown(b, set())
    if t["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Trip must be SCHEDULED to cancel")
    t["status"] = "CANCELLED"
    touch(t)
    return ok(serialize(t))


# ============================================================================
# Billing claims
# ============================================================================


RECOUP_RATE_NUM = 10  # floor(gross * 0.10) == gross // 10


@app.post("/claims")
def create_claim():
    uid, role, _ = authenticate({"BillingSpecialist"})
    b = body()
    individual_id = need(b, "individual_id")
    if not isinstance(individual_id, str):
        bad("individual_id must be a string")
    ind = get_or_404(db.individuals, individual_id, "Individual not found")
    if ind["status"] != "ENROLLED":
        err("ERR_INDIVIDUAL_NOT_ENROLLED", 409, "Individual must be ENROLLED")
    p_start = v_date(need(b, "service_period_start"), "service_period_start")
    p_end = v_date(need(b, "service_period_end"), "service_period_end")
    # claim-period validity runs before sweep emptiness
    if parse_d(p_end) < parse_d(p_start):
        err("ERR_CLAIM_PERIOD_INVALID", 400, "service_period_end is earlier than service_period_start")
    no_unknown(b, {"individual_id", "service_period_start", "service_period_end"})
    # sweep
    swept = []
    for v in db.visits.values():
        if v["individual_id"] != individual_id:
            continue
        if v["verification_status"] != "VERIFIED" or v["billing_status"] != "UNBILLED":
            continue
        if not (parse_d(p_start) <= parse_d(v["service_date"]) <= parse_d(p_end)):
            continue
        swept.append(v)
    swept.sort(key=lambda v: (parse_d(v["service_date"]), v["created_at"], v["_seq"]))
    if not swept:
        err("ERR_NO_BILLABLE_VISITS", 422, "Claim period contains no VERIFIED + UNBILLED visits")
    # lines grouped by allocated authorization, in order of first appearance
    line_map = {}
    line_order = []
    for v in swept:
        for entry in v.get("allocated_units_entries") or []:
            aid = entry["authorization_id"]
            if aid not in line_map:
                auth = db.auths.get(aid)
                line_map[aid] = {
                    "authorization_id": aid,
                    "service_code": auth["service_code"] if auth else None,
                    "units": 0,
                    "rate_cents": auth["rate_cents"] if auth else 0,
                    "amount_cents": 0,
                }
                line_order.append(aid)
            line_map[aid]["units"] += entry["units"]
    lines = []
    for aid in line_order:
        ln = line_map[aid]
        ln["amount_cents"] = ln["units"] * ln["rate_cents"]
        lines.append(ln)
    total_units = sum(ln["units"] for ln in lines)
    total_amount = sum(ln["amount_cents"] for ln in lines)
    claim = base_entity()
    claim.update({
        "individual_id": individual_id,
        "service_period_start": p_start,
        "service_period_end": p_end,
        "lines": lines,
        "total_units": total_units,
        "total_amount_cents": total_amount,
        "paid_amount_cents": None,
        "posted_net_cents": None,
        "submitted_by_user_id": None,
        "submitted_at": None,
        "denial_reason": None,
        "status": "DRAFT",
    })
    db.claims[claim["id"]] = claim
    for v in swept:
        v["billing_status"] = "BILLED"
        v["billed_claim_id"] = claim["id"]
        touch(v)
    return ok(serialize(claim), "object", 201)


@app.get("/claims")
def list_claims():
    authenticate(ANY)
    filters = {}
    for f in ("individual_id", "status"):
        v = opt_filter(f)
        if v is not None:
            filters[f] = v
    return list_page(apply_filters(list(db.claims.values()), filters))


@app.get("/claims/<claimId>")
def get_claim(claimId):
    authenticate(ANY)
    c = get_or_404(db.claims, claimId)
    return ok(serialize(c))


@app.post("/claims/<claimId>/submit")
def submit_claim(claimId):
    uid, role, _ = authenticate({"BillingSpecialist"})
    claim = get_or_404(db.claims, claimId)
    b = body()
    no_unknown(b, set())
    if claim["status"] not in ("DRAFT", "CORRECTED"):
        err("ERR_INVALID_STATE", 409, "Claim must be DRAFT or CORRECTED to submit")
    if not claim.get("lines"):
        err("ERR_INVALID_STATE", 409, "Claim has no lines")
    # posture gate: any home where the individual is an ACTIVE resident
    for ba in db.beds.values():
        if ba["individual_id"] == claim["individual_id"] and ba["status"] == "ACTIVE":
            home = db.homes.get(ba["home_id"])
            if home is not None:
                if recompute_posture(home) == "CRITICAL":
                    err("ERR_HOME_POSTURE_CRITICAL", 409,
                        "Resident's home compliance posture is CRITICAL")
    claim["submitted_at"] = now_iso()
    claim["submitted_by_user_id"] = uid
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(serialize(claim))


@app.post("/claims/<claimId>/post-payment")
def post_payment(claimId):
    uid, role, _ = authenticate({"BillingSpecialist"})
    claim = get_or_404(db.claims, claimId)
    b = body()
    if claim["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Claim must be SUBMITTED to post payment")
    if uid == claim.get("submitted_by_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Payment poster must differ from the claim submitter")
    paid = b.get("paid_amount_cents")
    if paid is None or isinstance(paid, bool) or not isinstance(paid, int) or paid < 0:
        bad("paid_amount_cents is required and must be a non-negative integer")
    if paid > claim["total_amount_cents"]:
        err("ERR_OVERPAYMENT", 400, "paid_amount_cents exceeds total_amount_cents")
    no_unknown(b, {"paid_amount_cents"})
    ind = db.individuals.get(claim["individual_id"])
    agency = db.agencies.get(ind["agency_id"]) if ind is not None else None
    claim["paid_amount_cents"] = paid
    if paid == claim["total_amount_cents"]:
        # full payment: recoupment netting in pinned order
        gross = claim["total_amount_cents"]
        balance_pre = agency["recoupment_balance_cents"] if agency is not None else 0
        recoup = min(gross // RECOUP_RATE_NUM, balance_pre)
        posted_net = gross - recoup
        claim["posted_net_cents"] = posted_net
        if agency is not None:
            agency["cash_collected_cents"] += posted_net
            agency["recoupment_balance_cents"] = balance_pre - recoup
        claim["status"] = "PAID"
    else:
        # partial payment: no recoupment
        claim["posted_net_cents"] = paid
        if agency is not None:
            agency["cash_collected_cents"] += paid
        claim["status"] = "PARTIALLY_PAID"
    touch(claim)
    return ok(serialize(claim))


@app.post("/claims/<claimId>/deny")
def deny_claim(claimId):
    uid, role, _ = authenticate({"BillingSpecialist"})
    claim = get_or_404(db.claims, claimId)
    b = body()
    if claim["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Claim must be SUBMITTED to deny")
    reason = b.get("denial_reason")
    if reason is None:
        bad("denial_reason is required")
    v_str(reason, "denial_reason")
    no_unknown(b, {"denial_reason"})
    claim["denial_reason"] = reason
    claim["status"] = "DENIED"
    touch(claim)
    return ok(serialize(claim))


@app.post("/claims/<claimId>/correct")
def correct_claim(claimId):
    uid, role, _ = authenticate({"BillingSpecialist"})
    claim = get_or_404(db.claims, claimId)
    b = body()
    if claim["status"] != "DENIED":
        err("ERR_INVALID_STATE", 409, "Claim must be DENIED to correct")
    overrides = b.get("lines_override")
    if overrides is None:
        bad("lines_override is required")
    if not isinstance(overrides, list):
        bad("lines_override must be an array")
    line_by_auth = {ln["authorization_id"]: ln for ln in claim.get("lines", [])}
    parsed = {}
    for entry in overrides:
        if not isinstance(entry, dict):
            bad("each lines_override entry must be an object")
        aid = entry.get("authorization_id")
        units = entry.get("units")
        if not isinstance(aid, str) or aid not in line_by_auth:
            bad("each lines_override entry must reference an authorization on this claim")
        if isinstance(units, bool) or not isinstance(units, int) or units < 0:
            bad("units must be an integer >= 0")
        parsed[aid] = units
    no_unknown(b, {"lines_override"})
    # capacity check per corrected line
    for aid, units in parsed.items():
        auth = db.auths.get(aid)
        if auth is None:
            bad("authorization not found: %s" % aid)
        remaining = auth["authorized_units"] - auth["consumed_units"]
        billed_here = line_by_auth[aid]["units"]
        if units > remaining + billed_here:
            err("ERR_AUTHORIZATION_UNITS_EXHAUSTED", 409,
                "Corrected units exceed the authorization's remaining units plus units billed on this claim")
    # recompute lines
    new_lines = []
    for ln in claim["lines"]:
        aid = ln["authorization_id"]
        units = parsed.get(aid, ln["units"])
        new_lines.append({
            "authorization_id": aid,
            "service_code": ln["service_code"],
            "units": units,
            "rate_cents": ln["rate_cents"],
            "amount_cents": units * ln["rate_cents"],
        })
    claim["lines"] = new_lines
    claim["total_units"] = sum(ln["units"] for ln in new_lines)
    claim["total_amount_cents"] = sum(ln["amount_cents"] for ln in new_lines)
    claim["status"] = "CORRECTED"
    touch(claim)
    return ok(serialize(claim))


@app.post("/claims/<claimId>/void")
def void_claim(claimId):
    uid, role, _ = authenticate({"BillingSpecialist"})
    claim = get_or_404(db.claims, claimId)
    b = body()
    no_unknown(b, set())
    if claim["status"] not in ("PAID", "PARTIALLY_PAID"):
        err("ERR_INVALID_STATE", 409, "Claim must be PAID or PARTIALLY_PAID to void")
    # compensation: reverse cash, build recoupment balance
    ind = db.individuals.get(claim["individual_id"])
    agency = db.agencies.get(ind["agency_id"]) if ind is not None else None
    posted = claim.get("posted_net_cents") or 0
    if agency is not None:
        agency["cash_collected_cents"] -= posted
        agency["recoupment_balance_cents"] += posted
    # unbill swept visits; release units LIFO
    for v in db.visits.values():
        if v.get("billed_claim_id") != claim["id"]:
            continue
        v["billing_status"] = "UNBILLED"
        v["billed_claim_id"] = None
        entries = v.get("allocated_units_entries") or []
        for entry in reversed(entries):
            auth = db.auths.get(entry["authorization_id"])
            if auth is None:
                continue
            auth["consumed_units"] -= entry["units"]
            if auth["status"] == "EXHAUSTED" and auth["consumed_units"] < auth["authorized_units"]:
                auth["status"] = "ACTIVE"
            touch(auth)
        v["allocated_units_entries"] = []
        touch(v)
    claim["status"] = "VOIDED"
    touch(claim)
    return ok(serialize(claim))


# ============================================================================
# Main
# ============================================================================


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
