"""Municipal Film & Location Permit Office API.

Single-file Flask implementation. All state is in-memory (module-level dicts);
every boot starts empty. No seeding, no persistence.
"""
import os
import math
import uuid
import random
import string
from datetime import datetime, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (keyed by id). Start empty on every boot.
# ---------------------------------------------------------------------------
companies = {}
departments = {}
officers = {}
segments = {}
applications = {}
locations = {}
reviews = {}
certificates = {}
bookings = {}
assignments = {}
riders = {}
notifications = {}
ledger = {}

_seq = 0

# Logical clock. Startup default per PRD 2.7.
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}

ALL_ROLES = {"FilmOfficeCoordinator", "ProductionCompany",
             "DepartmentReviewer", "FieldOfficer"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def err(error_id, http, message=None):
    raise ApiError(error_id, http, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_dt():
    return datetime.now(timezone.utc)


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def epoch(dt):
    return dt.timestamp()


def clock_iso():
    return fmt_iso(CLOCK["now"])


# ---------------------------------------------------------------------------
# Entity bases
# ---------------------------------------------------------------------------
def next_seq():
    global _seq
    _seq += 1
    return _seq


def base_versioned():
    ts = fmt_iso(now_dt())
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def base_immutable():
    ts = fmt_iso(now_dt())
    return {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}


def touch(e):
    e["updated_at"] = fmt_iso(now_dt())
    e["version"] = e.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base(pagination=None):
    m = {"api_request_id": gen_req_id(),
         "api_request_timestamp": fmt_iso(now_dt())}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": meta_base(pagination),
            "response_type": response_type,
            "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": meta_base(),
            "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def auth_role(allowed):
    uid, role = authenticate()
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing / validation
# ---------------------------------------------------------------------------
def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def need(body, field):
    if field not in body or body[field] is None:
        err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field)
    return body[field]


def need_str(body, field):
    v = need(body, field)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "%s must be a string" % field)
    return v


def need_int(body, field, minv=None):
    v = need(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "%s must be an integer" % field)
    if minv is not None and v < minv:
        err("ERR_INVALID_REQUEST", 400, "%s out of range" % field)
    return v


def need_enum(body, field, choices):
    v = need(body, field)
    if v not in choices:
        err("ERR_INVALID_REQUEST", 400, "%s invalid value" % field)
    return v


def need_dt(body, field):
    v = need(body, field)
    dt = parse_iso(v)
    if dt is None:
        err("ERR_INVALID_REQUEST", 400, "%s malformed datetime" % field)
    return v, dt


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, "%s must be a boolean" % field)
    return v


def opt_int(body, field, minv=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "%s must be an integer" % field)
    if minv is not None and v < minv:
        err("ERR_INVALID_REQUEST", 400, "%s out of range" % field)
    return v


def get_pagination():
    lim = request.args.get("limit")
    off = request.args.get("offset")
    if lim is None:
        limit = 10
    else:
        try:
            limit = int(lim)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "invalid limit")
    if off is None:
        offset = 0
    else:
        try:
            offset = int(off)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "invalid offset")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", 400, "limit out of range")
    if offset < 0:
        err("ERR_INVALID_REQUEST", 400, "offset out of range")
    return limit, offset


def paginate(items):
    items = sorted(items, key=lambda x: x["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + limit < total}
    return page, pagination


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def ser(e, extra=None):
    d = {k: v for k, v in e.items() if not k.startswith("_")}
    if extra:
        d.update(extra)
    return d


def compliance(c):
    s = 100 - 10 * c["late_wrap_count"] - 15 * c["damage_incident_count"] \
        - 20 * c["missed_notification_count"]
    return max(0, min(100, s))


def ser_company(c):
    return ser(c, {"compliance_score": compliance(c)})


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def find(store, _id):
    e = store.get(_id)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return e


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def crew_surcharge(crew):
    if crew <= 15:
        return 0
    if crew <= 50:
        return 20000
    if crew <= 150:
        return 50000
    return 100000


def compute_subtotal(a, booking_count, drone_count, still_count):
    sub = 25000
    sub += 15000 * a["shoot_days"]
    sub += crew_surcharge(a["crew_size"])
    if a["requires_road_closure"]:
        sub += 40000 * booking_count
    if a["requires_parking"]:
        sub += 10000 * a["shoot_days"]
    sub += 30000 * drone_count + 5000 * still_count
    return sub


def municipal_surcharge(subtotal):
    if subtotal < 100000:
        bps = 300
    elif subtotal < 300000:
        bps = 500
    else:
        bps = 700
    return (subtotal * bps) // 10000


def estimate_fee(a):
    bc = len([b for b in bookings.values()
              if b["application_id"] == a["id"] and b["status"] in ("PENDING", "CONFIRMED")])
    dc = len([r for r in riders.values()
              if r["application_id"] == a["id"] and r["rider_type"] == "DRONE"
              and r["status"] in ("REQUESTED", "APPROVED")])
    sc = len([r for r in riders.values()
              if r["application_id"] == a["id"] and r["rider_type"] == "STILL_PHOTO"
              and r["status"] in ("REQUESTED", "APPROVED")])
    sub = compute_subtotal(a, bc, dc, sc)
    return sub + municipal_surcharge(sub)


# ---------------------------------------------------------------------------
# Overlap helpers
# ---------------------------------------------------------------------------
BUFFER_SECONDS = 60 * 60  # 60 minutes


def segment_conflict(a_s, a_e, b_s, b_e):
    # buffer-expanded overlap (expanding either side by 60 min is equivalent).
    return (epoch(a_s) - BUFFER_SECONDS < epoch(b_e)) and \
           (epoch(b_s) < epoch(a_e) + BUFFER_SECONDS)


def officer_conflict(a_s, a_e, b_s, b_e):
    # half-open [start,end), no buffer
    return (epoch(a_s) < epoch(b_e)) and (epoch(b_s) < epoch(a_e))


def booking_window(b):
    return parse_iso(b["closure_start_at"]), parse_iso(b["closure_end_at"])


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def create_ledger_entry(a, entry_type, direction, amount, memo):
    e = base_immutable()
    e.update({"application_id": a["id"], "entry_type": entry_type,
              "direction": direction, "amount_cents": amount, "memo": memo})
    ledger[e["id"]] = e
    return e


def restore_blocked(segment_id):
    blocked = sorted([b for b in bookings.values()
                      if b["street_segment_id"] == segment_id and b["status"] == "BLOCKED"],
                     key=lambda x: x["_seq"])
    for b in blocked:
        bs, be = booking_window(b)
        confirmed = [c for c in bookings.values()
                     if c["street_segment_id"] == segment_id and c["status"] == "CONFIRMED"]
        overlaps = False
        for c in confirmed:
            cs, ce = booking_window(c)
            if segment_conflict(bs, be, cs, ce):
                overlaps = True
                break
        if not overlaps:
            b["status"] = "PENDING"
            touch(b)


def release_bookings_and_restore(a, statuses):
    segs = set()
    for b in list(bookings.values()):
        if b["application_id"] == a["id"] and b["status"] in statuses:
            b["status"] = "RELEASED"
            touch(b)
            segs.add(b["street_segment_id"])
    for s in segs:
        restore_blocked(s)


def cancel_assignments(a, statuses):
    for asg in list(assignments.values()):
        if asg["application_id"] == a["id"] and asg["status"] in statuses:
            asg["status"] = "CANCELLED"
            touch(asg)


def dept_matches(dept, a):
    tc = dept["trigger_condition"]
    if tc == "ALL_APPLICATIONS":
        return True
    if tc == "ROAD_CLOSURE_ONLY":
        return a["requires_road_closure"]
    if tc == "PARKING_ONLY":
        return a["requires_parking"]
    if tc == "DRONE_ONLY":
        return any(r["application_id"] == a["id"] and r["rider_type"] == "DRONE"
                   for r in riders.values())
    return False


# ===========================================================================
# Health
# ===========================================================================
@app.route("/", methods=["GET"])
def health():
    return ok({}, 200)


# ===========================================================================
# ProductionCompany
# ===========================================================================
@app.route("/production-companies", methods=["POST"])
def create_company():
    auth_role({"FilmOfficeCoordinator"})
    body = body_json()
    legal_name = need_str(body, "legal_name")
    contact_email = need_str(body, "contact_email")
    primary_contact = need_str(body, "primary_contact")
    c = base_versioned()
    c.update({"legal_name": legal_name, "contact_email": contact_email,
              "primary_contact": primary_contact, "late_wrap_count": 0,
              "damage_incident_count": 0, "missed_notification_count": 0})
    companies[c["id"]] = c
    return ok(ser_company(c), 201)


@app.route("/production-companies/<cid>", methods=["GET"])
def get_company(cid):
    auth_role(ALL_ROLES)
    c = find(companies, cid)
    return ok(ser_company(c), 200)


# ===========================================================================
# Department
# ===========================================================================
@app.route("/departments", methods=["POST"])
def create_department():
    auth_role({"FilmOfficeCoordinator"})
    body = body_json()
    code = need_enum(body, "code", {"POLICE", "PARKING", "FIRE", "PUBLIC_WORKS"})
    name = need_str(body, "name")
    tc = need_enum(body, "trigger_condition",
                   {"ALL_APPLICATIONS", "ROAD_CLOSURE_ONLY", "PARKING_ONLY", "DRONE_ONLY"})
    d = base_immutable()
    d.update({"code": code, "name": name, "trigger_condition": tc})
    departments[d["id"]] = d
    return ok(ser(d), 201)


@app.route("/departments/<did>", methods=["GET"])
def get_department(did):
    auth_role(ALL_ROLES)
    d = find(departments, did)
    return ok(ser(d), 200)


# ===========================================================================
# Officer
# ===========================================================================
@app.route("/officers", methods=["POST"])
def create_officer():
    auth_role({"FilmOfficeCoordinator"})
    body = body_json()
    full_name = need_str(body, "full_name")
    badge_number = need_str(body, "badge_number")
    rank = need_enum(body, "rank", {"OFFICER", "SERGEANT", "LIEUTENANT"})
    rate = need_int(body, "hourly_rate_cents", minv=0)
    o = base_versioned()
    o.update({"full_name": full_name, "badge_number": badge_number,
              "rank": rank, "hourly_rate_cents": rate, "status": "ACTIVE"})
    officers[o["id"]] = o
    return ok(ser(o), 201)


@app.route("/officers/<oid>", methods=["GET"])
def get_officer(oid):
    auth_role(ALL_ROLES)
    o = find(officers, oid)
    return ok(ser(o), 200)


@app.route("/officers/<oid>", methods=["PATCH"])
def patch_officer(oid):
    auth_role({"FilmOfficeCoordinator"})
    o = find(officers, oid)
    body = body_json()
    status = need_enum(body, "status", {"ACTIVE", "INACTIVE"})
    o["status"] = status
    touch(o)
    return ok(ser(o), 200)


# ===========================================================================
# StreetSegment
# ===========================================================================
@app.route("/street-segments", methods=["POST"])
def create_segment():
    auth_role({"FilmOfficeCoordinator"})
    body = body_json()
    segment_code = need_str(body, "segment_code")
    name = need_str(body, "name")
    length_m = need(body, "length_m")
    if isinstance(length_m, bool) or not isinstance(length_m, (int, float)):
        err("ERR_INVALID_REQUEST", 400, "length_m must be a number")
    if length_m <= 0:
        err("ERR_INVALID_REQUEST", 400, "length_m must be > 0")
    s = base_immutable()
    s.update({"segment_code": segment_code, "name": name, "length_m": length_m})
    segments[s["id"]] = s
    return ok(ser(s), 201)


@app.route("/street-segments/<sid>", methods=["GET"])
def get_segment(sid):
    auth_role(ALL_ROLES)
    s = find(segments, sid)
    return ok(ser(s), 200)


# ===========================================================================
# PermitApplication
# ===========================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    auth_role({"ProductionCompany"})
    body = body_json()
    # FK existence (before body well-formedness) for provided FK values
    pcid = body.get("production_company_id")
    if pcid is not None and pcid not in companies:
        err("ERR_NOT_FOUND", 404, "production_company_id not found")
    # body well-formed
    pcid = need_str(body, "production_company_id")
    if pcid not in companies:
        err("ERR_NOT_FOUND", 404, "production_company_id not found")
    title = need_str(body, "title")
    synopsis = need_str(body, "synopsis")
    ss, ss_dt = need_dt(body, "shoot_start_at")
    se, se_dt = need_dt(body, "shoot_end_at")
    crew = need_int(body, "crew_size", minv=1)
    rrc = opt_bool(body, "requires_road_closure", False)
    rp = opt_bool(body, "requires_parking", False)
    # time range
    if epoch(se_dt) <= epoch(ss_dt):
        err("ERR_INVALID_TIME_RANGE", 422, "shoot_end_at must be after shoot_start_at")
    shoot_days = (se_dt.date() - ss_dt.date()).days + 1
    a = base_versioned()
    a.update({
        "production_company_id": pcid, "title": title, "synopsis": synopsis,
        "shoot_start_at": ss, "shoot_end_at": se, "crew_size": crew,
        "requires_road_closure": rrc, "requires_parking": rp,
        "status": "DRAFT", "shoot_days": shoot_days,
        "estimated_fee_cents": 0, "final_fee_cents": 0,
        "municipal_surcharge_cents": 0, "total_fee_cents": 0,
        "deposit_cents": 0, "amount_paid_cents": 0, "deposit_held_cents": 0,
        "issued_at": None, "permitted_end_at": None, "actual_end_at": None,
        "damage_cost_cents": 0, "late_wrap_penalty_cents": 0,
        "deposit_refund_cents": 0,
    })
    applications[a["id"]] = a
    return ok(ser(a), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    auth_role(ALL_ROLES)
    a = find(applications, aid)
    return ok(ser(a), 200)


@app.route("/applications", methods=["GET"])
def list_applications():
    auth_role(ALL_ROLES)
    items = list(applications.values())
    pcid = request.args.get("production_company_id")
    status = request.args.get("status")
    if pcid is not None:
        items = [a for a in items if a["production_company_id"] == pcid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pg = paginate(items)
    return ok([ser(a) for a in page], 200, "array", pg)


@app.route("/applications/<aid>/location-details", methods=["POST"])
def create_location(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    body = body_json()
    address = need_str(body, "address")
    geo_zone = need_str(body, "geo_zone")
    activity_type = need_enum(body, "activity_type",
                              {"FILMING", "EQUIPMENT_STAGING", "BASECAMP"})
    rs, _ = need_dt(body, "requested_start_at")
    re_, _ = need_dt(body, "requested_end_at")
    uses_rc = opt_bool(body, "uses_road_closure", False)
    if a["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED"):
        err("ERR_INVALID_STATE", 409, "application not editable")
    loc = base_immutable()
    loc.update({"application_id": a["id"], "address": address, "geo_zone": geo_zone,
                "activity_type": activity_type, "requested_start_at": rs,
                "requested_end_at": re_, "uses_road_closure": uses_rc})
    locations[loc["id"]] = loc
    touch(a)  # child attachment bumps application version
    return ok(ser(loc), 201)


@app.route("/applications/<aid>/location-details", methods=["GET"])
def list_locations(aid):
    auth_role(ALL_ROLES)
    find(applications, aid)
    items = [l for l in locations.values() if l["application_id"] == aid]
    page, pg = paginate(items)
    return ok([ser(l) for l in page], 200, "array", pg)


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    if a["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        err("ERR_INVALID_STATE", 409, "cannot submit from current state")
    has_loc = any(l["application_id"] == a["id"] for l in locations.values())
    if not has_loc:
        err("ERR_NO_LOCATIONS", 422, "application has no locations")
    prev = a["status"]
    if prev == "DRAFT":
        # department fan-out
        for d in sorted(departments.values(), key=lambda x: x["_seq"]):
            if dept_matches(d, a):
                rv = base_versioned()
                rv.update({"application_id": a["id"], "department_id": d["id"],
                           "status": "PENDING", "decision_notes": None,
                           "decided_at": None})
                reviews[rv["id"]] = rv
    else:
        # resubmit: reset rejected / revision-requested reviews to PENDING
        for rv in reviews.values():
            if rv["application_id"] == a["id"] and \
                    rv["status"] in ("REJECTED", "REVISION_REQUESTED"):
                rv["status"] = "PENDING"
                touch(rv)
    a["status"] = "UNDER_REVIEW"
    a["estimated_fee_cents"] = estimate_fee(a)
    touch(a)
    return ok(ser(a), 200)


@app.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    st = a["status"]
    if st not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED", "ISSUED"):
        err("ERR_INVALID_STATE", 409, "cannot withdraw from current state")
    if st == "UNDER_REVIEW":
        release_bookings_and_restore(a, ("PENDING", "CONFIRMED"))
        cancel_assignments(a, ("PROPOSED", "CONFIRMED"))
    elif st == "ISSUED":
        release_bookings_and_restore(a, ("CONFIRMED",))
        cancel_assignments(a, ("CONFIRMED",))
        if a["deposit_held_cents"] > 0:
            create_ledger_entry(a, "REFUND", "CREDIT", a["deposit_held_cents"],
                                "Deposit refund on withdrawal")
            a["deposit_held_cents"] = 0
    a["status"] = "WITHDRAWN"
    touch(a)
    return ok(ser(a), 200)


@app.route("/applications/<aid>/issue", methods=["POST"])
def issue_application(aid):
    uid, role = auth_role({"FilmOfficeCoordinator"})
    a = find(applications, aid)
    body = body_json()
    # priority 30: generic state guard
    if a["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "issue only from UNDER_REVIEW")
    # priority 40: reviews complete
    app_reviews = [r for r in reviews.values() if r["application_id"] == a["id"]]
    if not all(r["status"] == "APPROVED" for r in app_reviews):
        err("ERR_REVIEWS_INCOMPLETE", 409, "not all department reviews are approved")
    # priority 42: OCC (only when provided)
    if "expected_application_version" in body and body["expected_application_version"] is not None:
        if body["expected_application_version"] != a["version"]:
            err("ERR_STALE_APPLICATION_VERSION", 412, "stale application version")
    # priority 45: COI verified
    if not any(c["application_id"] == a["id"] and c["status"] == "VERIFIED"
               for c in certificates.values()):
        err("ERR_COI_NOT_VERIFIED", 422, "no verified insurance certificate")
    # priority 60: permit fee paid
    if a["amount_paid_cents"] < a["estimated_fee_cents"]:
        err("ERR_FEE_UNPAID", 402, "permit fee not fully paid")

    # ---- side effects in pinned order ----
    # 1. confirm PENDING bookings (Cascade B)
    app_bookings = sorted([b for b in bookings.values()
                           if b["application_id"] == a["id"] and b["status"] == "PENDING"],
                          key=lambda x: x["_seq"])
    newly_confirmed = []
    for b in app_bookings:
        b["status"] = "CONFIRMED"
        touch(b)
        newly_confirmed.append(b)
    # 2. each confirmed booking blocks still-PENDING competitors on same segment
    newly_blocked = []
    for cb in newly_confirmed:
        cbs, cbe = booking_window(cb)
        comps = sorted([x for x in bookings.values()
                        if x["street_segment_id"] == cb["street_segment_id"]
                        and x["status"] == "PENDING" and x["id"] != cb["id"]],
                       key=lambda x: x["_seq"])
        for comp in comps:
            bs, be = booking_window(comp)
            if segment_conflict(cbs, cbe, bs, be):
                comp["status"] = "BLOCKED"
                touch(comp)
                newly_blocked.append(comp)
    # 3. blocked booking cancels its own application's PROPOSED officer assignments
    for bb in newly_blocked:
        for asg in list(assignments.values()):
            if asg["application_id"] == bb["application_id"] and asg["status"] == "PROPOSED":
                asg["status"] = "CANCELLED"
                touch(asg)
    # confirm this application's PROPOSED officer assignments
    for asg in list(assignments.values()):
        if asg["application_id"] == a["id"] and asg["status"] == "PROPOSED":
            asg["status"] = "CONFIRMED"
            touch(asg)
    # FINAL fee against confirmed bookings + approved riders
    confirmed_count = len([b for b in bookings.values()
                           if b["application_id"] == a["id"] and b["status"] == "CONFIRMED"])
    drone = len([r for r in riders.values()
                 if r["application_id"] == a["id"] and r["rider_type"] == "DRONE"
                 and r["status"] == "APPROVED"])
    still = len([r for r in riders.values()
                 if r["application_id"] == a["id"] and r["rider_type"] == "STILL_PHOTO"
                 and r["status"] == "APPROVED"])
    subtotal = compute_subtotal(a, confirmed_count, drone, still)
    sur = municipal_surcharge(subtotal)
    a["final_fee_cents"] = subtotal
    a["municipal_surcharge_cents"] = sur
    a["total_fee_cents"] = subtotal + sur
    pct = 2500 if a["total_fee_cents"] >= 500000 else 2000
    a["deposit_cents"] = (a["total_fee_cents"] * pct) // 10000 + 50000 * confirmed_count
    a["issued_at"] = clock_iso()
    a["permitted_end_at"] = a["shoot_end_at"]
    a["status"] = "ISSUED"
    touch(a)
    return ok(ser(a), 200)


@app.route("/applications/<aid>/wrap-request", methods=["POST"])
def wrap_request(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    if a["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "wrap-request only from ISSUED")
    if a["deposit_held_cents"] < a["deposit_cents"]:
        err("ERR_DEPOSIT_UNPAID", 402, "deposit not paid")
    a["status"] = "WRAP_REQUESTED"
    touch(a)
    return ok(ser(a), 200)


@app.route("/applications/<aid>/wrap-close", methods=["POST"])
def wrap_close(aid):
    auth_role({"FieldOfficer"})
    a = find(applications, aid)
    body = body_json()
    actual, actual_dt = need_dt(body, "actual_end_at")
    damages_reported = need(body, "damages_reported")
    if not isinstance(damages_reported, bool):
        err("ERR_INVALID_REQUEST", 400, "damages_reported must be a boolean")
    dc = opt_int(body, "damage_cost_cents", minv=0)
    if a["status"] != "WRAP_REQUESTED":
        err("ERR_INVALID_STATE", 409, "wrap-close only from WRAP_REQUESTED")
    damage = dc if (damages_reported and dc is not None) else 0
    a["actual_end_at"] = actual
    a["damage_cost_cents"] = damage
    # late wrap penalty
    permitted_dt = parse_iso(a["permitted_end_at"]) if a["permitted_end_at"] else None
    overage = 0
    if permitted_dt is not None:
        overage = max(0, epoch(actual_dt) - epoch(permitted_dt))
    overage_hours = math.ceil(overage / 3600) if overage > 0 else 0
    penalty = 20000 * overage_hours
    a["late_wrap_penalty_cents"] = penalty
    gross = a["deposit_held_cents"] - damage - penalty
    refund = max(0, gross)
    a["deposit_refund_cents"] = refund
    create_ledger_entry(a, "REFUND", "CREDIT", refund, "Deposit refund at wrap-close")
    a["deposit_held_cents"] = a["deposit_held_cents"] - refund
    # complete confirmed assignments
    for asg in list(assignments.values()):
        if asg["application_id"] == a["id"] and asg["status"] == "CONFIRMED":
            asg["status"] = "COMPLETED"
            touch(asg)
    # company counters
    c = companies.get(a["production_company_id"])
    if c is not None:
        if permitted_dt is not None and epoch(actual_dt) > epoch(permitted_dt):
            c["late_wrap_count"] += 1
        if damage > 0:
            c["damage_incident_count"] += 1
    a["status"] = "WRAPPED"
    touch(a)
    return ok(ser(a), 200)


# ===========================================================================
# InsuranceCertificate (COI)
# ===========================================================================
@app.route("/applications/<aid>/insurance-certificates", methods=["POST"])
def create_coi(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    body = body_json()
    policy_number = need_str(body, "policy_number")
    coverage = need_int(body, "coverage_amount_cents", minv=0)
    aviation = opt_bool(body, "aviation_coverage", False)
    eff, eff_dt = need_dt(body, "effective_date")
    exp, exp_dt = need_dt(body, "expiration_date")
    if epoch(exp_dt) <= epoch(eff_dt):
        err("ERR_INVALID_TIME_RANGE", 422, "expiration_date must be after effective_date")
    if a["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED"):
        err("ERR_INVALID_STATE", 409, "application not editable")
    if "expected_application_version" in body and body["expected_application_version"] is not None:
        if body["expected_application_version"] != a["version"]:
            err("ERR_STALE_APPLICATION_VERSION", 412, "stale application version")
    # supersede prior active COIs
    for c in certificates.values():
        if c["application_id"] == a["id"] and c["status"] in ("SUBMITTED", "VERIFIED"):
            c["status"] = "SUPERSEDED"
            touch(c)
    cert = base_versioned()
    cert.update({"application_id": a["id"], "policy_number": policy_number,
                 "coverage_amount_cents": coverage, "aviation_coverage": aviation,
                 "effective_date": eff, "expiration_date": exp, "status": "SUBMITTED"})
    certificates[cert["id"]] = cert
    touch(a)  # child attachment advances application version
    return ok(ser(cert), 201)


@app.route("/applications/<aid>/insurance-certificates", methods=["GET"])
def list_coi(aid):
    auth_role(ALL_ROLES)
    find(applications, aid)
    items = [c for c in certificates.values() if c["application_id"] == aid]
    page, pg = paginate(items)
    return ok([ser(c) for c in page], 200, "array", pg)


@app.route("/insurance-certificates/<cid>/verify", methods=["POST"])
def verify_coi(cid):
    auth_role({"FilmOfficeCoordinator"})
    cert = find(certificates, cid)
    body = body_json()
    decision = need_enum(body, "decision", {"VERIFY", "REJECT"})
    if cert["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "certificate not in SUBMITTED state")
    cert["status"] = "VERIFIED" if decision == "VERIFY" else "REJECTED"
    touch(cert)
    return ok(ser(cert), 200)


# ===========================================================================
# Rider
# ===========================================================================
@app.route("/applications/<aid>/riders", methods=["POST"])
def create_rider(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    body = body_json()
    rider_type = need_enum(body, "rider_type", {"DRONE", "STILL_PHOTO"})
    faa = body.get("faa_waiver_number")
    max_alt = body.get("max_altitude_ft")
    fs = body.get("flight_start_at")
    fe = body.get("flight_end_at")
    fs_dt = parse_iso(fs) if fs is not None else None
    fe_dt = parse_iso(fe) if fe is not None else None
    if a["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED"):
        err("ERR_INVALID_STATE", 409, "application not editable")
    if rider_type == "DRONE":
        # aviation coverage check (before flight-window containment)
        has_av = any(c["application_id"] == a["id"] and c["status"] == "VERIFIED"
                     and c["aviation_coverage"] for c in certificates.values())
        if not has_av:
            err("ERR_AVIATION_COVERAGE_MISSING", 422, "no verified aviation COI")
        if fs_dt is not None and fe_dt is not None:
            ss_dt = parse_iso(a["shoot_start_at"])
            se_dt = parse_iso(a["shoot_end_at"])
            if epoch(fs_dt) < epoch(ss_dt) or epoch(fe_dt) > epoch(se_dt):
                err("ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT", 422,
                    "flight window outside shoot window")
    r = base_versioned()
    r.update({"application_id": a["id"], "rider_type": rider_type,
              "faa_waiver_number": faa, "max_altitude_ft": max_alt,
              "flight_start_at": fs, "flight_end_at": fe, "status": "REQUESTED"})
    riders[r["id"]] = r
    touch(a)  # child attachment advances application version
    return ok(ser(r), 201)


@app.route("/applications/<aid>/riders", methods=["GET"])
def list_riders(aid):
    auth_role(ALL_ROLES)
    find(applications, aid)
    items = [r for r in riders.values() if r["application_id"] == aid]
    page, pg = paginate(items)
    return ok([ser(r) for r in page], 200, "array", pg)


@app.route("/riders/<rid>/decision", methods=["POST"])
def rider_decision(rid):
    auth_role({"FilmOfficeCoordinator"})
    r = find(riders, rid)
    body = body_json()
    decision = need_enum(body, "decision", {"APPROVE", "DENY"})
    a = applications.get(r["application_id"])
    if r["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "rider already decided")
    if a is None or a["status"] not in ("UNDER_REVIEW", "REVISION_REQUIRED"):
        err("ERR_INVALID_STATE", 409, "application not in a reviewable state")
    r["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    touch(r)
    return ok(ser(r), 200)


# ===========================================================================
# NeighborhoodNotification
# ===========================================================================
@app.route("/applications/<aid>/notifications", methods=["POST"])
def create_notification(aid):
    auth_role({"FilmOfficeCoordinator"})
    a = find(applications, aid)
    body = body_json()
    geo_zone = need_str(body, "geo_zone")
    notice_method = need_enum(body, "notice_method", {"MAILED", "POSTED", "DOOR_HANGER"})
    ss_dt = parse_iso(a["shoot_start_at"])
    lead_days = math.floor((epoch(ss_dt) - epoch(CLOCK["now"])) / 86400)
    if lead_days < 7:
        # rejected-too-late feeds the company's missed_notification_count
        c = companies.get(a["production_company_id"])
        if c is not None:
            c["missed_notification_count"] += 1
        err("ERR_NOTICE_TOO_LATE", 422, "notification lead time too short")
    n = base_immutable()
    n.update({"application_id": a["id"], "geo_zone": geo_zone,
              "notice_method": notice_method, "sent_at": clock_iso(),
              "lead_days": lead_days})
    notifications[n["id"]] = n
    return ok(ser(n), 201)


@app.route("/applications/<aid>/notifications", methods=["GET"])
def list_notifications(aid):
    auth_role(ALL_ROLES)
    find(applications, aid)
    items = [n for n in notifications.values() if n["application_id"] == aid]
    page, pg = paginate(items)
    return ok([ser(n) for n in page], 200, "array", pg)


# ===========================================================================
# LedgerEntry (payments)
# ===========================================================================
@app.route("/applications/<aid>/payments", methods=["POST"])
def create_payment(aid):
    auth_role({"ProductionCompany"})
    a = find(applications, aid)
    body = body_json()
    entry_type = need_enum(body, "entry_type", {"PERMIT_FEE", "DEPOSIT"})
    amount = need_int(body, "amount_cents", minv=1)
    # state: permitted timing per entry_type
    if entry_type == "PERMIT_FEE":
        if a["status"] not in ("UNDER_REVIEW", "REVISION_REQUIRED"):
            err("ERR_PAYMENT_NOT_ALLOWED", 409, "PERMIT_FEE not allowed in current state")
    else:  # DEPOSIT
        if a["status"] != "ISSUED":
            err("ERR_PAYMENT_NOT_ALLOWED", 409, "DEPOSIT not allowed in current state")
    e = create_ledger_entry(a, entry_type, "DEBIT", amount,
                            "%s payment" % entry_type)
    if entry_type == "PERMIT_FEE":
        a["amount_paid_cents"] += amount
    else:
        a["deposit_held_cents"] += amount
    return ok(ser(e), 201)


@app.route("/applications/<aid>/payments", methods=["GET"])
def list_payments(aid):
    auth_role(ALL_ROLES)
    find(applications, aid)
    items = [e for e in ledger.values() if e["application_id"] == aid]
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, "array", pg)


# ===========================================================================
# DepartmentReview
# ===========================================================================
@app.route("/department-reviews/<rvid>", methods=["GET"])
def get_review(rvid):
    auth_role(ALL_ROLES)
    rv = find(reviews, rvid)
    return ok(ser(rv), 200)


@app.route("/department-reviews", methods=["GET"])
def list_reviews():
    auth_role(ALL_ROLES)
    items = list(reviews.values())
    aid = request.args.get("application_id")
    did = request.args.get("department_id")
    status = request.args.get("status")
    if aid is not None:
        items = [r for r in items if r["application_id"] == aid]
    if did is not None:
        items = [r for r in items if r["department_id"] == did]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pg = paginate(items)
    return ok([ser(r) for r in page], 200, "array", pg)


@app.route("/department-reviews/<rvid>/decision", methods=["POST"])
def review_decision(rvid):
    uid, role = auth_role({"DepartmentReviewer"})
    rv = find(reviews, rvid)
    body = body_json()
    decision = need_enum(body, "decision", {"APPROVE", "REJECT", "REQUEST_REVISION"})
    notes = body.get("decision_notes")
    if notes is not None and not isinstance(notes, str):
        err("ERR_INVALID_REQUEST", 400, "decision_notes must be a string")
    # priority 20: reviewer may only decide its own department's review
    if uid != rv["department_id"]:
        err("ERR_UNAUTHORIZED", 403, "reviewer department mismatch")
    a = applications.get(rv["application_id"])
    # priority 30: state guards
    if rv["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "review already decided")
    if a is None or a["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "application not UNDER_REVIEW")
    rv["decided_at"] = clock_iso()
    if notes is not None:
        rv["decision_notes"] = notes
    if decision == "APPROVE":
        rv["status"] = "APPROVED"
        touch(rv)
    elif decision == "REQUEST_REVISION":
        rv["status"] = "REVISION_REQUESTED"
        touch(rv)
    else:  # REJECT -> Cascade A
        rv["status"] = "REJECTED"
        touch(rv)
        a["status"] = "REVISION_REQUIRED"
        release_bookings_and_restore(a, ("PENDING", "CONFIRMED"))
        touch(a)
    return ok(ser(rv), 200)


# ===========================================================================
# RoadClosureBooking
# ===========================================================================
@app.route("/road-closure-bookings", methods=["POST"])
def create_booking():
    auth_role({"ProductionCompany"})
    body = body_json()
    # FK existence first
    aid = body.get("application_id")
    if aid is not None and aid not in applications:
        err("ERR_NOT_FOUND", 404, "application_id not found")
    sid = body.get("street_segment_id")
    if sid is not None and sid not in segments:
        err("ERR_NOT_FOUND", 404, "street_segment_id not found")
    # body well-formed
    aid = need_str(body, "application_id")
    if aid not in applications:
        err("ERR_NOT_FOUND", 404, "application_id not found")
    sid = need_str(body, "street_segment_id")
    if sid not in segments:
        err("ERR_NOT_FOUND", 404, "street_segment_id not found")
    cs, cs_dt = need_dt(body, "closure_start_at")
    ce, ce_dt = need_dt(body, "closure_end_at")
    if epoch(ce_dt) <= epoch(cs_dt):
        err("ERR_INVALID_TIME_RANGE", 422, "closure_end_at must be after closure_start_at")
    a = applications[aid]
    if a["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED"):
        err("ERR_INVALID_STATE", 409, "application not editable")
    # double-booking against CONFIRMED bookings on same segment (buffer-expanded)
    for b in bookings.values():
        if b["street_segment_id"] == sid and b["status"] == "CONFIRMED":
            bs, be = booking_window(b)
            if segment_conflict(cs_dt, ce_dt, bs, be):
                err("ERR_SEGMENT_DOUBLE_BOOKED", 409, "segment already booked")
    b = base_versioned()
    b.update({"application_id": aid, "street_segment_id": sid,
              "closure_start_at": cs, "closure_end_at": ce, "status": "PENDING"})
    bookings[b["id"]] = b
    return ok(ser(b), 201)


@app.route("/road-closure-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    auth_role(ALL_ROLES)
    b = find(bookings, bid)
    return ok(ser(b), 200)


@app.route("/road-closure-bookings", methods=["GET"])
def list_bookings():
    auth_role(ALL_ROLES)
    items = list(bookings.values())
    aid = request.args.get("application_id")
    sid = request.args.get("street_segment_id")
    status = request.args.get("status")
    if aid is not None:
        items = [b for b in items if b["application_id"] == aid]
    if sid is not None:
        items = [b for b in items if b["street_segment_id"] == sid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, pg = paginate(items)
    return ok([ser(b) for b in page], 200, "array", pg)


# ===========================================================================
# OfficerAssignment
# ===========================================================================
@app.route("/officer-assignments", methods=["POST"])
def create_assignment():
    auth_role({"FilmOfficeCoordinator"})
    body = body_json()
    # FK existence first
    aid = body.get("application_id")
    if aid is not None and aid not in applications:
        err("ERR_NOT_FOUND", 404, "application_id not found")
    oid = body.get("officer_id")
    if oid is not None and oid not in officers:
        err("ERR_NOT_FOUND", 404, "officer_id not found")
    # body well-formed
    aid = need_str(body, "application_id")
    if aid not in applications:
        err("ERR_NOT_FOUND", 404, "application_id not found")
    oid = need_str(body, "officer_id")
    if oid not in officers:
        err("ERR_NOT_FOUND", 404, "officer_id not found")
    ss, ss_dt = need_dt(body, "shift_start_at")
    se, se_dt = need_dt(body, "shift_end_at")
    # order: time-range, app-state, officer-active, officer-overlap
    if epoch(se_dt) <= epoch(ss_dt):
        err("ERR_INVALID_TIME_RANGE", 422, "shift_end_at must be after shift_start_at")
    a = applications[aid]
    if a["status"] not in ("UNDER_REVIEW", "ISSUED"):
        err("ERR_INVALID_STATE", 409, "application not in UNDER_REVIEW or ISSUED")
    o = officers[oid]
    if o["status"] != "ACTIVE":
        err("ERR_OFFICER_INACTIVE", 409, "officer is inactive")
    for asg in assignments.values():
        if asg["officer_id"] == oid and asg["status"] in ("PROPOSED", "CONFIRMED"):
            bs = parse_iso(asg["shift_start_at"])
            be = parse_iso(asg["shift_end_at"])
            if officer_conflict(ss_dt, se_dt, bs, be):
                err("ERR_OFFICER_DOUBLE_BOOKED", 409, "officer double-booked")
    shift_hours = math.ceil((epoch(se_dt) - epoch(ss_dt)) / 3600)
    billed = o["hourly_rate_cents"] * shift_hours
    asg = base_versioned()
    asg.update({"application_id": aid, "officer_id": oid, "shift_start_at": ss,
                "shift_end_at": se, "status": "PROPOSED", "billed_cost_cents": billed})
    assignments[asg["id"]] = asg
    return ok(ser(asg), 201)


@app.route("/officer-assignments/<asid>", methods=["GET"])
def get_assignment(asid):
    auth_role(ALL_ROLES)
    asg = find(assignments, asid)
    return ok(ser(asg), 200)


@app.route("/officer-assignments", methods=["GET"])
def list_assignments():
    auth_role(ALL_ROLES)
    items = list(assignments.values())
    aid = request.args.get("application_id")
    oid = request.args.get("officer_id")
    status = request.args.get("status")
    if aid is not None:
        items = [x for x in items if x["application_id"] == aid]
    if oid is not None:
        items = [x for x in items if x["officer_id"] == oid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pg = paginate(items)
    return ok([ser(x) for x in page], 200, "array", pg)


@app.route("/officer-assignments/<asid>/cancel", methods=["POST"])
def cancel_assignment(asid):
    auth_role({"FilmOfficeCoordinator"})
    asg = find(assignments, asid)
    if asg["status"] not in ("PROPOSED", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "assignment cannot be cancelled")
    asg["status"] = "CANCELLED"
    touch(asg)
    return ok(ser(asg), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_role({"FilmOfficeCoordinator"})
    body = body_json()
    to_iso = need(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 malformed")
    CLOCK["now"] = dt
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
