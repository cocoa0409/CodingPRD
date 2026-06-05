#!/usr/bin/env python3
"""Home Health Nurse Dispatch API.

In-memory REST API implemented with Flask. All state lives in module-level
Python dicts keyed by UUID string and is wiped on every process restart.
No database, no disk persistence, no seeding at startup.
"""
import math
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"IntakeCoordinator", "Clinician", "Scheduler", "BillingManager", "ComplianceOfficer"}
DISCIPLINES = {"RN", "PT", "OT", "SLP", "HHA"}
VISIT_DISCIPLINES = {"RN", "PT", "OT", "SLP"}
CLINICAL_GROUPS = {"MMTA_OTHER", "WOUND", "NEURO_REHAB", "COMPLEX_NURSING", "MS_REHAB"}
FUNCTIONAL_LEVELS = {"LOW", "MEDIUM", "HIGH"}
ASSESSMENT_TYPES = {"START_OF_CARE", "RECERTIFICATION"}

PER_VISIT_RATE = Decimal("165.00")
COMORBIDITY_NONE_MULT = Decimal("1.00")
COMORBIDITY_LOW_MULT = Decimal("1.06")
COMORBIDITY_HIGH_MULT = Decimal("1.18")

OVERCLAIM_TOLERANCE = Decimal("1.10")
FREE_TIER_MILES = Decimal("5.0")
TIER1_CAP = Decimal("20.0")
TIER1_RATE = Decimal("0.67")
TIER2_RATE = Decimal("0.50")

COMPANION_HOURLY_RATE = Decimal("24.05")

MAX_RECERT_REVISIONS = 3
RECERT_WINDOW_DAYS = 14
REOPEN_WINDOW_DAYS = 30

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.patients = {}
        self.clinicians = {}
        self.oasis = {}
        self.rate_configs = {}
        self.episodes = {}
        self.plans = {}
        self.visits = {}
        self.companion_shifts = {}
        self.mileage_claims = {}
        self.recert_requests = {}
        self.payment_ledgers = {}
        self.events = {}
        # logical clock (None -> use real wall clock)
        self.clock = None


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current server clock (logical if pinned, else real)."""
    if store.clock is not None:
        return store.clock
    return datetime.now(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(now())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, http_status, error_id, message=None):
        super().__init__(message or error_id)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_ok(items):
    meta = meta_base()
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(400, "ERR_VALIDATION", "body must be a JSON object")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_nonempty_str(value):
    return isinstance(value, str) and value.strip() != ""


def parse_dt(value):
    """Parse an ISO 8601 datetime string -> aware UTC datetime, or raise ERR_VALIDATION."""
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError(400, "ERR_VALIDATION", "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # try date-only
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            raise ApiError(400, "ERR_VALIDATION", "invalid datetime format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError(400, "ERR_VALIDATION", f"missing required field: {n}")


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    return user_id, role


def authorize(allowed_roles):
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError(403, "ERR_FORBIDDEN_ROLE", "role not permitted for this operation")
    return user_id, role


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items already sorted by created_at asc. Returns (page, meta_pagination)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(400, "ERR_VALIDATION", "invalid limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(400, "ERR_VALIDATION", "limit out of range")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(400, "ERR_VALIDATION", "invalid offset")
        if offset < 0:
            raise ApiError(400, "ERR_VALIDATION", "offset out of range")

    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------
def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_float(dec):
    return float(dec)


def comorbidity_mult(count):
    if count == 0:
        return COMORBIDITY_NONE_MULT
    if count <= 2:
        return COMORBIDITY_LOW_MULT
    return COMORBIDITY_HIGH_MULT


def active_rate_config(clinical_group):
    for rc in store.rate_configs.values():
        if rc["clinical_group"] == clinical_group and rc["active"]:
            return rc
    return None


def functional_weight(rate_config, functional_level):
    if functional_level == "LOW":
        return Decimal(str(rate_config["functional_weight_low"]))
    if functional_level == "MEDIUM":
        return Decimal(str(rate_config["functional_weight_medium"]))
    return Decimal(str(rate_config["functional_weight_high"]))


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.7613  # earth radius in miles
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def active_plan_for(episode_id):
    for p in store.plans.values():
        if p["episode_id"] == episode_id and p["status"] == "ACTIVE":
            return p
    return None


def soc_oasis_for(episode):
    return store.oasis.get(episode["soc_oasis_id"])


def recompute_provisional(episode):
    plan = active_plan_for(episode["id"])
    if plan is None:
        episode["provisional_payment"] = 0.0
        return
    rc = active_rate_config(episode["clinical_group"])
    soc = soc_oasis_for(episode)
    planned_total = (plan["planned_rn_visits"] + plan["planned_pt_visits"]
                     + plan["planned_ot_visits"] + plan["planned_slp_visits"])
    if rc is None or soc is None:
        # cannot compute case-mix; fall back to per-visit basis
        if planned_total >= (episode.get("lupa_threshold") or 1):
            episode["provisional_payment"] = 0.0
        else:
            episode["provisional_payment"] = to_float(round2(PER_VISIT_RATE * planned_total))
        return
    fw = functional_weight(rc, episode["functional_level"])
    cm = comorbidity_mult(soc["comorbidity_count"])
    case_mix = Decimal(str(rc["base_30day_rate"])) * fw * cm
    if planned_total >= episode["lupa_threshold"]:
        episode["provisional_payment"] = to_float(round2(case_mix * 2))
    else:
        episode["provisional_payment"] = to_float(round2(PER_VISIT_RATE * planned_total))


def iso_week_bounds(dt):
    """Monday 00:00 UTC .. next Monday 00:00 UTC containing dt."""
    d = dt.astimezone(timezone.utc)
    monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday, monday + timedelta(days=7)


def weekly_held_count(clinician_id, scheduled_start, exclude_visit_id=None):
    wk_start, wk_end = iso_week_bounds(scheduled_start)
    cnt = 0
    for v in store.visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v["clinician_id"] != clinician_id:
            continue
        if v["status"] not in ("CONFIRMED", "COMPLETED"):
            continue
        vs = v["_scheduled_start_dt"]
        if wk_start <= vs < wk_end:
            cnt += 1
    return cnt


def append_event(episode_id, event_type, detail=""):
    eid = new_id()
    ev = {
        "id": eid,
        "_seq": next_seq(),
        "episode_id": episode_id,
        "event_type": event_type,
        "detail": detail,
        "occurred_at": now_iso(),
        "created_at": now_iso(),
    }
    store.events[eid] = ev
    return ev


_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(record):
    record["updated_at"] = now_iso()
    record["version"] += 1


def patient_open_episode(patient_id):
    for e in store.episodes.values():
        if e["patient_id"] == patient_id and e["status"] in ("DRAFT", "ACTIVE", "RECERT_PENDING"):
            return e
    return None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def common_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_patient(p):
    out = common_out(p)
    out.update({
        "full_name": p["full_name"],
        "medicare_id": p["medicare_id"],
        "home_zip": p["home_zip"],
        "home_lat": p["home_lat"],
        "home_lon": p["home_lon"],
        "status": p["status"],
        "open_episode_id": (patient_open_episode(p["id"]) or {}).get("id"),
    })
    return out


def ser_clinician(c):
    out = common_out(c)
    out.update({
        "full_name": c["full_name"],
        "discipline": c["discipline"],
        "license_active": c["license_active"],
        "base_lat": c["base_lat"],
        "base_lon": c["base_lon"],
        "weekly_visit_cap": c["weekly_visit_cap"],
    })
    return out


def ser_oasis(o):
    out = common_out(o)
    out.update({
        "patient_id": o["patient_id"],
        "clinician_id": o["clinician_id"],
        "assessment_type": o["assessment_type"],
        "assessment_date": o["assessment_date"],
        "clinical_group": o["clinical_group"],
        "functional_level": o["functional_level"],
        "comorbidity_count": o["comorbidity_count"],
        "locked": o["locked"],
    })
    return out


def ser_rate_config(rc):
    return {
        "id": rc["id"],
        "created_at": rc["created_at"],
        "clinical_group": rc["clinical_group"],
        "base_30day_rate": rc["base_30day_rate"],
        "functional_weight_low": rc["functional_weight_low"],
        "functional_weight_medium": rc["functional_weight_medium"],
        "functional_weight_high": rc["functional_weight_high"],
        "lupa_threshold": rc["lupa_threshold"],
        "active": rc["active"],
    }


def ser_episode(e):
    out = common_out(e)
    out.update({
        "patient_id": e["patient_id"],
        "soc_oasis_id": e["soc_oasis_id"],
        "prior_episode_id": e["prior_episode_id"],
        "clinical_group": e["clinical_group"],
        "functional_level": e["functional_level"],
        "status": e["status"],
        "cert_start": e["cert_start"],
        "cert_end": e["cert_end"],
        "lupa_threshold": e["lupa_threshold"],
        "provisional_payment": e["provisional_payment"],
        "final_payment": e["final_payment"],
        "total_mileage_reimbursed": e["total_mileage_reimbursed"],
        "companion_hours_used": e["companion_hours_used"],
    })
    return out


def ser_plan(p):
    out = common_out(p)
    out.update({
        "episode_id": p["episode_id"],
        "planned_rn_visits": p["planned_rn_visits"],
        "planned_pt_visits": p["planned_pt_visits"],
        "planned_ot_visits": p["planned_ot_visits"],
        "planned_slp_visits": p["planned_slp_visits"],
        "companion_hours_authorized": p["companion_hours_authorized"],
        "status": p["status"],
    })
    return out


def ser_visit(v):
    out = common_out(v)
    out.update({
        "episode_id": v["episode_id"],
        "clinician_id": v["clinician_id"],
        "discipline": v["discipline"],
        "scheduled_start": v["scheduled_start"],
        "scheduled_end": v["scheduled_end"],
        "status": v["status"],
        "billable": v["billable"],
    })
    return out


def ser_shift(s):
    out = common_out(s)
    out.update({
        "episode_id": s["episode_id"],
        "clinician_id": s["clinician_id"],
        "shift_start": s["shift_start"],
        "shift_end": s["shift_end"],
        "hours": s["hours"],
        "status": s["status"],
    })
    return out


def ser_claim(m):
    out = common_out(m)
    out.update({
        "visit_id": m["visit_id"],
        "claimed_miles": m["claimed_miles"],
        "computed_miles": m["computed_miles"],
        "reimbursable_miles": m["reimbursable_miles"],
        "reimbursement": m["reimbursement"],
        "status": m["status"],
    })
    return out


def ser_recert(r):
    out = common_out(r)
    out.update({
        "episode_id": r["episode_id"],
        "recert_oasis_id": r["recert_oasis_id"],
        "status": r["status"],
        "revision_count": r["revision_count"],
        "review_note": r["review_note"],
    })
    return out


def ser_ledger(l):
    out = common_out(l)
    out.update({
        "episode_id": l["episode_id"],
        "payment_basis": l["payment_basis"],
        "gross_pdgm": l["gross_pdgm"],
        "mileage_offset": l["mileage_offset"],
        "companion_offset": l["companion_offset"],
        "net_settlement": l["net_settlement"],
        "reversed": l["reversed"],
    })
    return out


def ser_event(ev):
    return {
        "id": ev["id"],
        "created_at": ev["created_at"],
        "episode_id": ev["episode_id"],
        "event_type": ev["event_type"],
        "detail": ev["detail"],
        "occurred_at": ev["occurred_at"],
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        meta = meta_base()
        body = {"meta": meta, "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message}}
        resp = jsonify(body)
        resp.status_code = err.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(_):
        meta = meta_base()
        body = {"meta": meta, "response_type": "error",
                "data": {"error_id": "ERR_NOT_FOUND", "message": "resource does not exist"}}
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_):
        meta = meta_base()
        body = {"meta": meta, "response_type": "error",
                "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
        return jsonify(body), 404

    # ===================================================================
    # Clock (test-only)
    # ===================================================================
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authorize({"BillingManager", "IntakeCoordinator", "Scheduler", "ComplianceOfficer"})
        body = get_body()
        require_fields(body, ["now_utc"])
        store.clock = parse_dt(body["now_utc"])
        return ok({"now_utc": iso(store.clock)}, 200)

    # ===================================================================
    # Patients
    # ===================================================================
    @app.route("/patients", methods=["POST"])
    def create_patient():
        authorize({"IntakeCoordinator"})
        body = get_body()
        require_fields(body, ["full_name", "medicare_id", "home_zip", "home_lat", "home_lon"])
        if not is_nonempty_str(body["full_name"]):
            raise ApiError(400, "ERR_VALIDATION", "full_name invalid")
        if not is_nonempty_str(body["medicare_id"]):
            raise ApiError(400, "ERR_VALIDATION", "medicare_id invalid")
        zip_ = body["home_zip"]
        if not (isinstance(zip_, str) and zip_.isdigit() and len(zip_) == 5):
            raise ApiError(400, "ERR_VALIDATION", "home_zip must be 5 digits")
        if not is_number(body["home_lat"]) or not is_number(body["home_lon"]):
            raise ApiError(400, "ERR_VALIDATION", "coordinates must be numbers")
        for p in store.patients.values():
            if p["medicare_id"] == body["medicare_id"]:
                raise ApiError(400, "ERR_VALIDATION", "medicare_id must be unique")

        rec = base_record()
        rec.update({
            "full_name": body["full_name"],
            "medicare_id": body["medicare_id"],
            "home_zip": zip_,
            "home_lat": body["home_lat"],
            "home_lon": body["home_lon"],
            "status": "ACTIVE",
        })
        store.patients[rec["id"]] = rec
        return ok(ser_patient(rec), 201)

    @app.route("/patients/<pid>", methods=["GET"])
    def get_patient(pid):
        authorize({"IntakeCoordinator", "Scheduler", "BillingManager", "ComplianceOfficer"})
        p = store.patients.get(pid)
        if p is None:
            raise ApiError(404, "ERR_NOT_FOUND", "patient does not exist")
        return ok(ser_patient(p), 200)

    @app.route("/patients/<pid>/episodes", methods=["GET"])
    def list_patient_episodes(pid):
        authorize({"IntakeCoordinator", "Scheduler", "BillingManager", "ComplianceOfficer"})
        if pid not in store.patients:
            raise ApiError(404, "ERR_NOT_FOUND", "patient does not exist")
        items = [e for e in store.episodes.values() if e["patient_id"] == pid]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_episode(e) for e in page], 200, "array", pag)

    # ===================================================================
    # Clinicians
    # ===================================================================
    @app.route("/clinicians", methods=["POST"])
    def create_clinician():
        authorize({"Scheduler"})
        body = get_body()
        require_fields(body, ["full_name", "discipline", "base_lat", "base_lon"])
        if not is_nonempty_str(body["full_name"]):
            raise ApiError(400, "ERR_VALIDATION", "full_name invalid")
        if body["discipline"] not in DISCIPLINES:
            raise ApiError(400, "ERR_VALIDATION", "invalid discipline")
        if not is_number(body["base_lat"]) or not is_number(body["base_lon"]):
            raise ApiError(400, "ERR_VALIDATION", "coordinates must be numbers")

        license_active = body.get("license_active", True)
        if license_active is None:
            license_active = True
        if not isinstance(license_active, bool):
            raise ApiError(400, "ERR_VALIDATION", "license_active must be boolean")

        cap = body.get("weekly_visit_cap", 40)
        if cap is None:
            cap = 40
        if not is_int(cap) or cap < 1:
            raise ApiError(400, "ERR_VALIDATION", "weekly_visit_cap must be int >= 1")

        rec = base_record()
        rec.update({
            "full_name": body["full_name"],
            "discipline": body["discipline"],
            "license_active": license_active,
            "base_lat": body["base_lat"],
            "base_lon": body["base_lon"],
            "weekly_visit_cap": cap,
        })
        store.clinicians[rec["id"]] = rec
        return ok(ser_clinician(rec), 201)

    @app.route("/clinicians/<cid>", methods=["GET"])
    def get_clinician(cid):
        authorize({"Scheduler", "IntakeCoordinator", "BillingManager"})
        c = store.clinicians.get(cid)
        if c is None:
            raise ApiError(404, "ERR_NOT_FOUND", "clinician does not exist")
        return ok(ser_clinician(c), 200)

    @app.route("/clinicians/<cid>", methods=["PATCH"])
    def update_clinician(cid):
        authorize({"Scheduler"})
        c = store.clinicians.get(cid)
        if c is None:
            raise ApiError(404, "ERR_NOT_FOUND", "clinician does not exist")
        body = get_body()
        if "license_active" in body and body["license_active"] is not None:
            if not isinstance(body["license_active"], bool):
                raise ApiError(400, "ERR_VALIDATION", "license_active must be boolean")
            c["license_active"] = body["license_active"]
        if "weekly_visit_cap" in body and body["weekly_visit_cap"] is not None:
            cap = body["weekly_visit_cap"]
            if not is_int(cap) or cap < 1:
                raise ApiError(400, "ERR_VALIDATION", "weekly_visit_cap must be int >= 1")
            c["weekly_visit_cap"] = cap
        touch(c)
        return ok(ser_clinician(c), 200)

    @app.route("/clinicians/<cid>/visits", methods=["GET"])
    def list_clinician_visits(cid):
        authorize({"Scheduler", "Clinician", "BillingManager"})
        if cid not in store.clinicians:
            raise ApiError(404, "ERR_NOT_FOUND", "clinician does not exist")
        status = request.args.get("status")
        items = [v for v in store.visits.values() if v["clinician_id"] == cid]
        if status:
            items = [v for v in items if v["status"] == status]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_visit(v) for v in page], 200, "array", pag)

    # ===================================================================
    # OASIS assessments
    # ===================================================================
    @app.route("/oasis-assessments", methods=["POST"])
    def create_oasis():
        authorize({"IntakeCoordinator"})
        body = get_body()
        require_fields(body, ["patient_id", "clinician_id", "assessment_type",
                              "assessment_date", "clinical_group", "functional_level",
                              "comorbidity_count"])
        if body["assessment_type"] not in ASSESSMENT_TYPES:
            raise ApiError(400, "ERR_VALIDATION", "invalid assessment_type")
        if body["clinical_group"] not in CLINICAL_GROUPS:
            raise ApiError(400, "ERR_VALIDATION", "invalid clinical_group")
        if body["functional_level"] not in FUNCTIONAL_LEVELS:
            raise ApiError(400, "ERR_VALIDATION", "invalid functional_level")
        if not is_int(body["comorbidity_count"]) or body["comorbidity_count"] < 0:
            raise ApiError(400, "ERR_VALIDATION", "comorbidity_count must be int >= 0")
        assessment_dt = parse_dt(body["assessment_date"])

        if body["patient_id"] not in store.patients:
            raise ApiError(404, "ERR_NOT_FOUND", "patient does not exist")
        if body["clinician_id"] not in store.clinicians:
            raise ApiError(404, "ERR_NOT_FOUND", "clinician does not exist")

        rec = base_record()
        rec.update({
            "patient_id": body["patient_id"],
            "clinician_id": body["clinician_id"],
            "assessment_type": body["assessment_type"],
            "assessment_date": body["assessment_date"],
            "_assessment_dt": assessment_dt,
            "clinical_group": body["clinical_group"],
            "functional_level": body["functional_level"],
            "comorbidity_count": body["comorbidity_count"],
            "locked": False,
        })
        store.oasis[rec["id"]] = rec
        return ok(ser_oasis(rec), 201)

    @app.route("/oasis-assessments", methods=["GET"])
    def list_oasis():
        authorize({"IntakeCoordinator", "ComplianceOfficer"})
        items = list(store.oasis.values())
        pq = request.args.get("patient_id")
        cq = request.args.get("clinician_id")
        if pq:
            items = [o for o in items if o["patient_id"] == pq]
        if cq:
            items = [o for o in items if o["clinician_id"] == cq]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_oasis(o) for o in page], 200, "array", pag)

    @app.route("/oasis-assessments/<oid>", methods=["GET"])
    def get_oasis(oid):
        authorize({"IntakeCoordinator", "ComplianceOfficer"})
        o = store.oasis.get(oid)
        if o is None:
            raise ApiError(404, "ERR_NOT_FOUND", "oasis does not exist")
        return ok(ser_oasis(o), 200)

    @app.route("/oasis-assessments/<oid>/recert-requests", methods=["GET"])
    def list_oasis_recerts(oid):
        authorize({"IntakeCoordinator", "ComplianceOfficer"})
        if oid not in store.oasis:
            raise ApiError(404, "ERR_NOT_FOUND", "oasis does not exist")
        items = [r for r in store.recert_requests.values() if r["recert_oasis_id"] == oid]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_recert(r) for r in page], 200, "array", pag)

    # ===================================================================
    # PDGM rate configs
    # ===================================================================
    @app.route("/pdgm-rate-configs", methods=["POST"])
    def create_rate_config():
        authorize({"BillingManager"})
        body = get_body()
        require_fields(body, ["clinical_group", "base_30day_rate", "functional_weight_low",
                              "functional_weight_medium", "functional_weight_high",
                              "lupa_threshold"])
        if body["clinical_group"] not in CLINICAL_GROUPS:
            raise ApiError(400, "ERR_VALIDATION", "invalid clinical_group")
        if not is_number(body["base_30day_rate"]) or body["base_30day_rate"] <= 0:
            raise ApiError(400, "ERR_VALIDATION", "base_30day_rate must be > 0")
        for k in ("functional_weight_low", "functional_weight_medium", "functional_weight_high"):
            if not is_number(body[k]):
                raise ApiError(400, "ERR_VALIDATION", f"{k} must be a number")
        if not is_int(body["lupa_threshold"]) or body["lupa_threshold"] < 1:
            raise ApiError(400, "ERR_VALIDATION", "lupa_threshold must be int >= 1")
        active = body.get("active", True)
        if active is None:
            active = True
        if not isinstance(active, bool):
            raise ApiError(400, "ERR_VALIDATION", "active must be boolean")
        if active:
            for rc in store.rate_configs.values():
                if rc["clinical_group"] == body["clinical_group"] and rc["active"]:
                    raise ApiError(400, "ERR_VALIDATION", "active config already exists for group")

        ts = now_iso()
        rec = {
            "id": new_id(),
            "_seq": next_seq(),
            "created_at": ts,
            "clinical_group": body["clinical_group"],
            "base_30day_rate": body["base_30day_rate"],
            "functional_weight_low": body["functional_weight_low"],
            "functional_weight_medium": body["functional_weight_medium"],
            "functional_weight_high": body["functional_weight_high"],
            "lupa_threshold": body["lupa_threshold"],
            "active": active,
        }
        store.rate_configs[rec["id"]] = rec
        return ok(ser_rate_config(rec), 201)

    @app.route("/pdgm-rate-configs", methods=["GET"])
    def list_rate_configs():
        authorize({"BillingManager", "IntakeCoordinator"})
        items = list(store.rate_configs.values())
        cg = request.args.get("clinical_group")
        act = request.args.get("active")
        if cg:
            items = [r for r in items if r["clinical_group"] == cg]
        if act is not None:
            want = act.lower() == "true"
            items = [r for r in items if r["active"] == want]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_rate_config(r) for r in page], 200, "array", pag)

    # ===================================================================
    # Episodes
    # ===================================================================
    @app.route("/episodes", methods=["POST"])
    def create_episode():
        authorize({"IntakeCoordinator"})
        body = get_body()
        require_fields(body, ["patient_id", "soc_oasis_id"])
        prior_episode_id = body.get("prior_episode_id")

        # existence (left to right): patient, soc_oasis, prior episode
        patient = store.patients.get(body["patient_id"])
        if patient is None:
            raise ApiError(404, "ERR_NOT_FOUND", "patient does not exist")
        soc = store.oasis.get(body["soc_oasis_id"])
        if soc is None:
            raise ApiError(404, "ERR_NOT_FOUND", "soc_oasis does not exist")
        if prior_episode_id is not None:
            if prior_episode_id not in store.episodes:
                raise ApiError(404, "ERR_NOT_FOUND", "prior episode does not exist")

        # OASIS validity
        if (soc["assessment_type"] != "START_OF_CARE"
                or soc["patient_id"] != body["patient_id"]
                or soc["locked"]):
            raise ApiError(422, "ERR_OASIS_INVALID", "soc oasis invalid")

        # single open episode
        if patient_open_episode(body["patient_id"]) is not None:
            raise ApiError(409, "ERR_PATIENT_HAS_OPEN_EPISODE", "patient has an open episode")

        cert_start = soc["_assessment_dt"]
        cert_end = cert_start + timedelta(days=59)
        rc = active_rate_config(soc["clinical_group"])
        lupa = rc["lupa_threshold"] if rc else 1

        rec = base_record()
        rec.update({
            "patient_id": body["patient_id"],
            "soc_oasis_id": body["soc_oasis_id"],
            "prior_episode_id": prior_episode_id,
            "clinical_group": soc["clinical_group"],
            "functional_level": soc["functional_level"],
            "status": "DRAFT",
            "cert_start": soc["assessment_date"],
            "cert_end": iso(cert_end),
            "_cert_start_dt": cert_start,
            "_cert_end_dt": cert_end,
            "lupa_threshold": lupa,
            "provisional_payment": 0.0,
            "final_payment": 0.0,
            "total_mileage_reimbursed": 0.0,
            "companion_hours_used": 0.0,
            "_finalized_at": None,
        })
        store.episodes[rec["id"]] = rec
        soc["locked"] = True
        touch(soc)
        return ok(ser_episode(rec), 201)

    @app.route("/episodes", methods=["GET"])
    def list_episodes():
        authorize({"IntakeCoordinator", "Scheduler", "BillingManager", "ComplianceOfficer"})
        items = list(store.episodes.values())
        pq = request.args.get("patient_id")
        sq = request.args.get("soc_oasis_id")
        prq = request.args.get("prior_episode_id")
        if pq:
            items = [e for e in items if e["patient_id"] == pq]
        if sq:
            items = [e for e in items if e["soc_oasis_id"] == sq]
        if prq:
            items = [e for e in items if e["prior_episode_id"] == prq]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_episode(e) for e in page], 200, "array", pag)

    @app.route("/episodes/<eid>", methods=["GET"])
    def get_episode(eid):
        authorize({"IntakeCoordinator", "Scheduler", "BillingManager", "ComplianceOfficer"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        return ok(ser_episode(e), 200)

    @app.route("/episodes/<eid>/summary", methods=["GET"])
    def episode_summary(eid):
        authorize({"BillingManager", "IntakeCoordinator"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        return ok(ser_episode(e), 200)

    @app.route("/episodes/<eid>/events", methods=["GET"])
    def episode_events(eid):
        authorize({"BillingManager", "IntakeCoordinator", "ComplianceOfficer"})
        if eid not in store.episodes:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        items = [ev for ev in store.events.values() if ev["episode_id"] == eid]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_event(ev) for ev in page], 200, "array", pag)

    @app.route("/episodes/<eid>/payment-ledger", methods=["GET"])
    def episode_ledger(eid):
        authorize({"BillingManager"})
        if eid not in store.episodes:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        items = [l for l in store.payment_ledgers.values() if l["episode_id"] == eid]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_ledger(l) for l in page], 200, "array", pag)

    @app.route("/episodes/<eid>/activate", methods=["POST"])
    def activate_episode(eid):
        authorize({"IntakeCoordinator"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        if e["status"] != "DRAFT":
            raise ApiError(409, "ERR_INVALID_STATE", "episode not in DRAFT")
        plan = active_plan_for(eid)
        if plan is None:
            raise ApiError(422, "ERR_PLAN_REQUIRED", "episode has no active plan")
        e["status"] = "ACTIVE"
        recompute_provisional(e)
        append_event(eid, "ACTIVATED", "episode activated")
        touch(e)
        return ok(ser_episode(e), 200)

    @app.route("/episodes/<eid>/cancel", methods=["POST"])
    def cancel_episode(eid):
        authorize({"IntakeCoordinator"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        if e["status"] != "DRAFT":
            raise ApiError(409, "ERR_INVALID_STATE", "episode not in DRAFT")
        e["status"] = "CANCELLED"
        for p in store.plans.values():
            if p["episode_id"] == eid and p["status"] == "ACTIVE":
                p["status"] = "SUPERSEDED"
                touch(p)
        soc = store.oasis.get(e["soc_oasis_id"])
        if soc is not None:
            soc["locked"] = False
            touch(soc)
        append_event(eid, "CANCELLED", "episode cancelled")
        touch(e)
        return ok(ser_episode(e), 200)

    @app.route("/episodes/<eid>/finalize", methods=["POST"])
    def finalize_episode(eid):
        authorize({"BillingManager"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        if e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_INVALID_STATE", "episode not ACTIVE")
        # settleability
        for v in store.visits.values():
            if v["episode_id"] == eid and v["status"] in ("SCHEDULED", "CONFIRMED"):
                raise ApiError(409, "ERR_EPISODE_NOT_SETTLEABLE", "non-terminal visit exists")
        for r in store.recert_requests.values():
            if r["episode_id"] == eid and r["status"] == "SUBMITTED":
                raise ApiError(409, "ERR_EPISODE_NOT_SETTLEABLE", "submitted recert exists")

        completed = [v for v in store.visits.values()
                     if v["episode_id"] == eid and v["status"] == "COMPLETED"]
        n = len(completed)
        rc = active_rate_config(e["clinical_group"])
        soc = soc_oasis_for(e)
        if n < e["lupa_threshold"]:
            payment_basis = "LUPA_PER_VISIT"
            gross = round2(PER_VISIT_RATE * n)
        else:
            payment_basis = "FULL_PDGM"
            fw = functional_weight(rc, e["functional_level"])
            cm = comorbidity_mult(soc["comorbidity_count"])
            case_mix = Decimal(str(rc["base_30day_rate"])) * fw * cm
            gross = round2(case_mix * 2)

        # companion offset: per-shift round then sum
        companion_offset = Decimal("0.00")
        for s in store.companion_shifts.values():
            if s["episode_id"] == eid and s["status"] == "DELIVERED":
                companion_offset += round2(Decimal(str(s["hours"])) * COMPANION_HOURLY_RATE)

        mileage_offset = round2(Decimal(str(e["total_mileage_reimbursed"])))
        net = gross + mileage_offset + companion_offset

        e["final_payment"] = to_float(net)

        ledger = base_record()
        ledger.update({
            "episode_id": eid,
            "payment_basis": payment_basis,
            "gross_pdgm": to_float(gross),
            "mileage_offset": to_float(mileage_offset),
            "companion_offset": to_float(companion_offset),
            "net_settlement": to_float(net),
            "reversed": False,
        })
        store.payment_ledgers[ledger["id"]] = ledger

        e["status"] = "DISCHARGED"
        e["_finalized_at"] = now()
        append_event(eid, "FINALIZED", "episode finalized")
        append_event(eid, "DISCHARGED", "episode discharged")

        patient = store.patients.get(e["patient_id"])
        if patient is not None and patient_open_episode(e["patient_id"]) is None:
            patient["status"] = "DISCHARGED"
            touch(patient)
        touch(e)
        return ok(ser_episode(e), 200)

    @app.route("/episodes/<eid>/reopen", methods=["POST"])
    def reopen_episode(eid):
        authorize({"BillingManager"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        if e["status"] != "DISCHARGED":
            raise ApiError(409, "ERR_INVALID_STATE", "episode not DISCHARGED")
        ledger = None
        for l in store.payment_ledgers.values():
            if l["episode_id"] == eid and not l["reversed"]:
                ledger = l
        if ledger is None:
            raise ApiError(409, "ERR_INVALID_STATE", "no non-reversed ledger")
        # reopen window
        finalized_at = e.get("_finalized_at")
        if finalized_at is not None:
            if now() > finalized_at + timedelta(days=REOPEN_WINDOW_DAYS):
                raise ApiError(422, "ERR_REOPEN_WINDOW_CLOSED", "reopen window closed")

        ledger["reversed"] = True
        touch(ledger)
        e["final_payment"] = 0.0
        e["status"] = "ACTIVE"
        patient = store.patients.get(e["patient_id"])
        if patient is not None:
            patient["status"] = "ACTIVE"
            touch(patient)
        append_event(eid, "LEDGER_REVERSED", "ledger reversed on reopen")
        touch(e)
        return ok(ser_episode(e), 200)

    # ===================================================================
    # Plans of care
    # ===================================================================
    @app.route("/episodes/<eid>/plans-of-care", methods=["POST"])
    def create_plan(eid):
        authorize({"IntakeCoordinator"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        body = get_body()
        # required visit count fields + companion_hours_authorized
        for f in ("planned_rn_visits", "planned_pt_visits", "planned_ot_visits",
                  "planned_slp_visits", "companion_hours_authorized"):
            if f not in body or body[f] is None:
                raise ApiError(400, "ERR_VALIDATION", f"missing field: {f}")
        for f in ("planned_rn_visits", "planned_pt_visits", "planned_ot_visits", "planned_slp_visits"):
            if not is_int(body[f]) or body[f] < 0:
                raise ApiError(400, "ERR_VALIDATION", f"{f} must be int >= 0")
        if not is_number(body["companion_hours_authorized"]) or body["companion_hours_authorized"] < 0:
            raise ApiError(400, "ERR_VALIDATION", "companion_hours_authorized must be number >= 0")
        if "expected_episode_version" not in body or body["expected_episode_version"] is None:
            raise ApiError(400, "ERR_VERSION_REQUIRED", "expected_episode_version required")
        if not is_int(body["expected_episode_version"]):
            raise ApiError(400, "ERR_VALIDATION", "expected_episode_version must be int")

        # OCC check (last gate)
        if body["expected_episode_version"] != e["version"]:
            raise ApiError(412, "ERR_STALE_EPISODE_VERSION", "episode version is stale")

        # supersede prior active plan
        for p in store.plans.values():
            if p["episode_id"] == eid and p["status"] == "ACTIVE":
                p["status"] = "SUPERSEDED"
                touch(p)
                append_event(eid, "PLAN_SUPERSEDED", "plan superseded")

        rec = base_record()
        rec.update({
            "episode_id": eid,
            "planned_rn_visits": body["planned_rn_visits"],
            "planned_pt_visits": body["planned_pt_visits"],
            "planned_ot_visits": body["planned_ot_visits"],
            "planned_slp_visits": body["planned_slp_visits"],
            "companion_hours_authorized": body["companion_hours_authorized"],
            "status": "ACTIVE",
        })
        store.plans[rec["id"]] = rec
        recompute_provisional(e)
        touch(e)
        return ok(ser_plan(rec), 201)

    @app.route("/episodes/<eid>/plans-of-care", methods=["GET"])
    def list_plans(eid):
        authorize({"IntakeCoordinator", "BillingManager"})
        if eid not in store.episodes:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        items = [p for p in store.plans.values() if p["episode_id"] == eid]
        status = request.args.get("status")
        if status:
            items = [p for p in items if p["status"] == status]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_plan(p) for p in page], 200, "array", pag)

    # ===================================================================
    # Visits
    # ===================================================================
    @app.route("/episodes/<eid>/visits", methods=["POST"])
    def schedule_visit(eid):
        authorize({"Scheduler"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        body = get_body()
        require_fields(body, ["clinician_id", "discipline", "scheduled_start", "scheduled_end"])
        if body["discipline"] not in VISIT_DISCIPLINES:
            raise ApiError(400, "ERR_VALIDATION", "invalid discipline")
        start_dt = parse_dt(body["scheduled_start"])
        end_dt = parse_dt(body["scheduled_end"])

        clinician = store.clinicians.get(body["clinician_id"])
        if clinician is None:
            raise ApiError(404, "ERR_NOT_FOUND", "clinician does not exist")

        # state: episode active
        if e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_EPISODE_NOT_ACTIVE", "episode not active")

        # discipline match
        if body["discipline"] != clinician["discipline"]:
            raise ApiError(422, "ERR_DISCIPLINE_MISMATCH", "discipline does not match clinician")

        # cert window: start < end and both within [cert_start, cert_end]
        if not (start_dt < end_dt
                and e["_cert_start_dt"] <= start_dt <= e["_cert_end_dt"]
                and e["_cert_start_dt"] <= end_dt <= e["_cert_end_dt"]):
            raise ApiError(422, "ERR_VISIT_OUT_OF_CERT_WINDOW", "visit outside cert window")

        # double booking (half-open overlap) against same clinician's non-terminal visits
        for v in store.visits.values():
            if v["clinician_id"] != body["clinician_id"]:
                continue
            if v["status"] in ("COMPLETED", "MISSED", "CANCELLED"):
                continue
            if start_dt < v["_scheduled_end_dt"] and v["_scheduled_start_dt"] < end_dt:
                raise ApiError(409, "ERR_CLINICIAN_DOUBLE_BOOKED", "clinician double booked")

        # weekly cap at scheduling
        held = weekly_held_count(body["clinician_id"], start_dt)
        if held + 1 > clinician["weekly_visit_cap"]:
            raise ApiError(422, "ERR_WEEKLY_CAP_EXCEEDED", "weekly cap exceeded")

        rec = base_record()
        rec.update({
            "episode_id": eid,
            "clinician_id": body["clinician_id"],
            "discipline": body["discipline"],
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "_scheduled_start_dt": start_dt,
            "_scheduled_end_dt": end_dt,
            "status": "SCHEDULED",
            "billable": False,
        })
        store.visits[rec["id"]] = rec
        return ok(ser_visit(rec), 201)

    @app.route("/episodes/<eid>/visits", methods=["GET"])
    def list_episode_visits(eid):
        authorize({"Scheduler", "BillingManager", "IntakeCoordinator"})
        if eid not in store.episodes:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        items = [v for v in store.visits.values() if v["episode_id"] == eid]
        status = request.args.get("status")
        if status:
            items = [v for v in items if v["status"] == status]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_visit(v) for v in page], 200, "array", pag)

    @app.route("/visits/<vid>", methods=["GET"])
    def get_visit(vid):
        authorize({"Scheduler", "Clinician", "BillingManager"})
        v = store.visits.get(vid)
        if v is None:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        return ok(ser_visit(v), 200)

    @app.route("/visits/<vid>/confirm", methods=["POST"])
    def confirm_visit(vid):
        user_id, role = authorize({"Clinician"})
        v = store.visits.get(vid)
        if v is None:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        # ownership
        if user_id != v["clinician_id"]:
            raise ApiError(403, "ERR_NOT_RESOURCE_OWNER", "not assigned clinician")
        if v["status"] != "SCHEDULED":
            raise ApiError(409, "ERR_INVALID_STATE", "visit not SCHEDULED")
        e = store.episodes.get(v["episode_id"])
        if e is None or e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_EPISODE_NOT_ACTIVE", "episode not active")
        clinician = store.clinicians.get(v["clinician_id"])
        if not clinician["license_active"]:
            raise ApiError(422, "ERR_LICENSE_INACTIVE", "license inactive")
        # weekly cap on confirm
        held = weekly_held_count(v["clinician_id"], v["_scheduled_start_dt"], exclude_visit_id=vid)
        if held + 1 > clinician["weekly_visit_cap"]:
            raise ApiError(422, "ERR_WEEKLY_CAP_EXCEEDED", "weekly cap exceeded")
        v["status"] = "CONFIRMED"
        touch(v)
        return ok(ser_visit(v), 200)

    @app.route("/visits/<vid>/complete", methods=["POST"])
    def complete_visit(vid):
        user_id, role = authorize({"Clinician"})
        v = store.visits.get(vid)
        if v is None:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        if user_id != v["clinician_id"]:
            raise ApiError(403, "ERR_NOT_RESOURCE_OWNER", "not assigned clinician")
        if v["status"] != "CONFIRMED":
            raise ApiError(409, "ERR_INVALID_STATE", "visit not CONFIRMED")
        e = store.episodes.get(v["episode_id"])
        if e is None or e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_EPISODE_NOT_ACTIVE", "episode not active")
        if not (v["_scheduled_end_dt"] <= now()):
            raise ApiError(409, "ERR_INVALID_STATE", "visit window not elapsed")
        v["status"] = "COMPLETED"
        v["billable"] = True
        touch(v)
        recompute_provisional(e)
        append_event(v["episode_id"], "VISIT_COMPLETED", "visit completed")
        return ok(ser_visit(v), 200)

    @app.route("/visits/<vid>/mark-missed", methods=["POST"])
    def mark_missed(vid):
        authorize({"Scheduler"})
        v = store.visits.get(vid)
        if v is None:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        if v["status"] != "CONFIRMED":
            raise ApiError(409, "ERR_INVALID_STATE", "visit not CONFIRMED")
        if not (v["_scheduled_end_dt"] <= now()):
            raise ApiError(409, "ERR_INVALID_STATE", "visit window not elapsed")
        v["status"] = "MISSED"
        v["billable"] = False
        touch(v)
        append_event(v["episode_id"], "VISIT_MISSED", "visit missed")
        return ok(ser_visit(v), 200)

    @app.route("/visits/<vid>/cancel", methods=["POST"])
    def cancel_visit(vid):
        authorize({"Scheduler"})
        v = store.visits.get(vid)
        if v is None:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        if v["status"] not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError(409, "ERR_INVALID_STATE", "visit not cancellable")
        v["status"] = "CANCELLED"
        touch(v)
        return ok(ser_visit(v), 200)

    # ===================================================================
    # Companion shifts
    # ===================================================================
    @app.route("/episodes/<eid>/companion-shifts", methods=["POST"])
    def book_shift(eid):
        authorize({"Scheduler"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        body = get_body()
        require_fields(body, ["clinician_id", "shift_start", "shift_end"])
        start_dt = parse_dt(body["shift_start"])
        end_dt = parse_dt(body["shift_end"])
        clinician = store.clinicians.get(body["clinician_id"])
        if clinician is None:
            raise ApiError(404, "ERR_NOT_FOUND", "clinician does not exist")

        if e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_EPISODE_NOT_ACTIVE", "episode not active")
        if clinician["discipline"] != "HHA":
            raise ApiError(422, "ERR_DISCIPLINE_MISMATCH", "companion requires HHA clinician")
        if not (start_dt < end_dt):
            raise ApiError(400, "ERR_VALIDATION", "shift_start must be before shift_end")

        # overlap on same patient's episode + 30-min buffer for same HHA
        buffer = timedelta(minutes=30)
        for s in store.companion_shifts.values():
            if s["status"] == "CANCELLED":
                continue
            if s["episode_id"] == eid:
                # any non-terminal shift on episode: no overlap
                if start_dt < s["_shift_end_dt"] and s["_shift_start_dt"] < end_dt:
                    raise ApiError(409, "ERR_COMPANION_SHIFT_CONFLICT", "shift overlap")
            if s["clinician_id"] == body["clinician_id"]:
                # 30-min travel buffer between adjacent shifts of same HHA
                if (start_dt < s["_shift_end_dt"] + buffer
                        and s["_shift_start_dt"] - buffer < end_dt):
                    raise ApiError(409, "ERR_COMPANION_SHIFT_CONFLICT", "travel buffer violated")

        hours = round2((end_dt - start_dt).total_seconds() / 3600.0)
        rec = base_record()
        rec.update({
            "episode_id": eid,
            "clinician_id": body["clinician_id"],
            "shift_start": body["shift_start"],
            "shift_end": body["shift_end"],
            "_shift_start_dt": start_dt,
            "_shift_end_dt": end_dt,
            "hours": to_float(hours),
            "status": "BOOKED",
        })
        store.companion_shifts[rec["id"]] = rec
        return ok(ser_shift(rec), 201)

    @app.route("/episodes/<eid>/companion-shifts", methods=["GET"])
    def list_shifts(eid):
        authorize({"Scheduler", "BillingManager"})
        if eid not in store.episodes:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        items = [s for s in store.companion_shifts.values() if s["episode_id"] == eid]
        status = request.args.get("status")
        if status:
            items = [s for s in items if s["status"] == status]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_shift(s) for s in page], 200, "array", pag)

    @app.route("/companion-shifts/<sid>/deliver", methods=["POST"])
    def deliver_shift(sid):
        authorize({"Scheduler"})
        s = store.companion_shifts.get(sid)
        if s is None:
            raise ApiError(404, "ERR_NOT_FOUND", "shift does not exist")
        if s["status"] != "BOOKED":
            raise ApiError(409, "ERR_INVALID_STATE", "shift not BOOKED")
        e = store.episodes.get(s["episode_id"])
        if e is None or e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_EPISODE_NOT_ACTIVE", "episode not active")
        if not (s["_shift_end_dt"] <= now()):
            raise ApiError(409, "ERR_INVALID_STATE", "shift window not elapsed")
        plan = active_plan_for(e["id"])
        authorized = Decimal(str(plan["companion_hours_authorized"])) if plan else Decimal("0")
        used = Decimal(str(e["companion_hours_used"]))
        shift_hours = Decimal(str(s["hours"]))
        if used + shift_hours > authorized:
            raise ApiError(422, "ERR_COMPANION_HOURS_EXCEEDED", "companion hours exceeded")
        e["companion_hours_used"] = to_float(used + shift_hours)
        s["status"] = "DELIVERED"
        touch(s)
        return ok(ser_shift(s), 200)

    @app.route("/companion-shifts/<sid>/cancel", methods=["POST"])
    def cancel_shift(sid):
        authorize({"Scheduler"})
        s = store.companion_shifts.get(sid)
        if s is None:
            raise ApiError(404, "ERR_NOT_FOUND", "shift does not exist")
        if s["status"] != "BOOKED":
            raise ApiError(409, "ERR_INVALID_STATE", "shift not BOOKED")
        s["status"] = "CANCELLED"
        touch(s)
        return ok(ser_shift(s), 200)

    # ===================================================================
    # Mileage claims
    # ===================================================================
    @app.route("/visits/<vid>/mileage-claims", methods=["POST"])
    def file_claim(vid):
        user_id, role = authorize({"Clinician"})
        v = store.visits.get(vid)
        if v is None:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        if user_id != v["clinician_id"]:
            raise ApiError(403, "ERR_NOT_RESOURCE_OWNER", "not assigned clinician")
        body = get_body()
        require_fields(body, ["claimed_miles"])
        if not is_number(body["claimed_miles"]) or body["claimed_miles"] < 0:
            raise ApiError(400, "ERR_VALIDATION", "claimed_miles must be number >= 0")

        clinician = store.clinicians.get(v["clinician_id"])
        e = store.episodes.get(v["episode_id"])
        patient = store.patients.get(e["patient_id"]) if e else None
        if clinician is None or patient is None:
            raise ApiError(404, "ERR_NOT_FOUND", "related resource missing")

        computed = haversine_miles(clinician["base_lat"], clinician["base_lon"],
                                   patient["home_lat"], patient["home_lon"]) * 2

        rec = base_record()
        rec.update({
            "visit_id": vid,
            "claimed_miles": body["claimed_miles"],
            "computed_miles": to_float(round2(computed)),
            "_computed_miles_raw": computed,
            "reimbursable_miles": None,
            "reimbursement": None,
            "status": "PENDING",
        })
        store.mileage_claims[rec["id"]] = rec
        return ok(ser_claim(rec), 201)

    @app.route("/visits/<vid>/mileage-claims", methods=["GET"])
    def list_claims(vid):
        authorize({"Clinician", "BillingManager", "Scheduler"})
        if vid not in store.visits:
            raise ApiError(404, "ERR_NOT_FOUND", "visit does not exist")
        items = [m for m in store.mileage_claims.values() if m["visit_id"] == vid]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_claim(m) for m in page], 200, "array", pag)

    @app.route("/mileage-claims/<mid>/approve", methods=["POST"])
    def approve_claim(mid):
        authorize({"BillingManager"})
        m = store.mileage_claims.get(mid)
        if m is None:
            raise ApiError(404, "ERR_NOT_FOUND", "claim does not exist")
        if m["status"] != "PENDING":
            raise ApiError(409, "ERR_INVALID_STATE", "claim not PENDING")
        v = store.visits.get(m["visit_id"])
        if v is None or v["status"] != "COMPLETED":
            raise ApiError(409, "ERR_INVALID_STATE", "parent visit not completed")

        computed = Decimal(str(m["_computed_miles_raw"]))
        ceiling = round2(computed * OVERCLAIM_TOLERANCE)
        claimed = Decimal(str(m["claimed_miles"]))
        if claimed > ceiling:
            raise ApiError(422, "ERR_MILEAGE_OVERCLAIM", "claimed miles exceed tolerance")

        capped = min(claimed, ceiling)
        billable = max(Decimal("0"), capped - FREE_TIER_MILES)
        tier1 = min(billable, TIER1_CAP)
        tier2 = max(Decimal("0"), billable - TIER1_CAP)
        reimbursement = round2(tier1 * TIER1_RATE + tier2 * TIER2_RATE)

        m["reimbursable_miles"] = to_float(billable)
        m["reimbursement"] = to_float(reimbursement)
        m["status"] = "APPROVED"
        touch(m)

        e = store.episodes.get(v["episode_id"])
        if e is not None:
            e["total_mileage_reimbursed"] = to_float(
                Decimal(str(e["total_mileage_reimbursed"])) + reimbursement)
        return ok(ser_claim(m), 200)

    @app.route("/mileage-claims/<mid>/reject", methods=["POST"])
    def reject_claim(mid):
        authorize({"BillingManager"})
        m = store.mileage_claims.get(mid)
        if m is None:
            raise ApiError(404, "ERR_NOT_FOUND", "claim does not exist")
        if m["status"] != "PENDING":
            raise ApiError(409, "ERR_INVALID_STATE", "claim not PENDING")
        m["reimbursement"] = 0.0
        m["status"] = "REJECTED"
        touch(m)
        return ok(ser_claim(m), 200)

    # ===================================================================
    # Recert requests
    # ===================================================================
    @app.route("/episodes/<eid>/recert-requests", methods=["POST"])
    def create_recert(eid):
        authorize({"IntakeCoordinator"})
        e = store.episodes.get(eid)
        if e is None:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        body = get_body()
        require_fields(body, ["recert_oasis_id"])
        oasis = store.oasis.get(body["recert_oasis_id"])
        if oasis is None:
            raise ApiError(404, "ERR_NOT_FOUND", "recert oasis does not exist")

        if e["status"] != "ACTIVE":
            raise ApiError(409, "ERR_INVALID_STATE", "episode not ACTIVE")

        # recert oasis validity
        if (oasis["assessment_type"] != "RECERTIFICATION"
                or oasis["patient_id"] != e["patient_id"]
                or oasis["locked"]):
            raise ApiError(422, "ERR_RECERT_OASIS_INVALID", "recert oasis invalid")

        # recert window: within final 14 days before cert_end (by date)
        cur = now().date()
        cert_end_date = e["_cert_end_dt"].date()
        window_open = cert_end_date - timedelta(days=RECERT_WINDOW_DAYS)
        if not (window_open <= cur <= cert_end_date):
            raise ApiError(422, "ERR_RECERT_WINDOW_CLOSED", "recert window closed")

        review_note = body.get("review_note", "")
        rec = base_record()
        rec.update({
            "episode_id": eid,
            "recert_oasis_id": body["recert_oasis_id"],
            "status": "SUBMITTED",
            "revision_count": 0,
            "review_note": review_note if review_note is not None else "",
        })
        store.recert_requests[rec["id"]] = rec
        e["status"] = "RECERT_PENDING"
        touch(e)
        return ok(ser_recert(rec), 201)

    @app.route("/episodes/<eid>/recert-requests", methods=["GET"])
    def list_episode_recerts(eid):
        authorize({"IntakeCoordinator", "ComplianceOfficer"})
        if eid not in store.episodes:
            raise ApiError(404, "ERR_NOT_FOUND", "episode does not exist")
        items = [r for r in store.recert_requests.values() if r["episode_id"] == eid]
        page, pag = paginate(sorted_by_created(items))
        return ok([ser_recert(r) for r in page], 200, "array", pag)

    @app.route("/recert-requests/<rid>", methods=["GET"])
    def get_recert(rid):
        authorize({"IntakeCoordinator", "ComplianceOfficer"})
        r = store.recert_requests.get(rid)
        if r is None:
            raise ApiError(404, "ERR_NOT_FOUND", "recert does not exist")
        return ok(ser_recert(r), 200)

    @app.route("/recert-requests/<rid>/approve", methods=["POST"])
    def approve_recert(rid):
        authorize({"ComplianceOfficer"})
        r = store.recert_requests.get(rid)
        if r is None:
            raise ApiError(404, "ERR_NOT_FOUND", "recert does not exist")
        if r["status"] != "SUBMITTED":
            raise ApiError(409, "ERR_INVALID_STATE", "recert not SUBMITTED")
        oasis = store.oasis.get(r["recert_oasis_id"])
        if oasis is None or oasis["locked"]:
            raise ApiError(422, "ERR_RECERT_OASIS_INVALID", "recert oasis invalid")
        e = store.episodes.get(r["episode_id"])

        oasis["locked"] = True
        touch(oasis)
        r["status"] = "APPROVED"
        touch(r)

        # extend cert_end by 60 days
        new_end = e["_cert_end_dt"] + timedelta(days=60)
        e["_cert_end_dt"] = new_end
        e["cert_end"] = iso(new_end)
        e["clinical_group"] = oasis["clinical_group"]
        e["functional_level"] = oasis["functional_level"]
        rc = active_rate_config(e["clinical_group"])
        if rc is not None:
            e["lupa_threshold"] = rc["lupa_threshold"]
        e["status"] = "ACTIVE"
        append_event(e["id"], "RECERT_APPROVED", "recert approved")
        touch(e)
        return ok(ser_recert(r), 200)

    @app.route("/recert-requests/<rid>/deny", methods=["POST"])
    def deny_recert(rid):
        authorize({"ComplianceOfficer"})
        r = store.recert_requests.get(rid)
        if r is None:
            raise ApiError(404, "ERR_NOT_FOUND", "recert does not exist")
        if r["status"] != "SUBMITTED":
            raise ApiError(409, "ERR_INVALID_STATE", "recert not SUBMITTED")
        body = get_body()
        if "review_note" in body and body["review_note"] is not None:
            r["review_note"] = body["review_note"]
        r["status"] = "DENIED"
        touch(r)
        e = store.episodes.get(r["episode_id"])
        e["status"] = "ACTIVE"
        touch(e)
        return ok(ser_recert(r), 200)

    @app.route("/recert-requests/<rid>/return", methods=["POST"])
    def return_recert(rid):
        authorize({"ComplianceOfficer"})
        r = store.recert_requests.get(rid)
        if r is None:
            raise ApiError(404, "ERR_NOT_FOUND", "recert does not exist")
        if r["status"] != "SUBMITTED":
            raise ApiError(409, "ERR_INVALID_STATE", "recert not SUBMITTED")
        body = get_body()
        if "review_note" in body and body["review_note"] is not None:
            r["review_note"] = body["review_note"]
        r["status"] = "RETURNED"
        touch(r)
        return ok(ser_recert(r), 200)

    @app.route("/recert-requests/<rid>/resubmit", methods=["POST"])
    def resubmit_recert(rid):
        authorize({"IntakeCoordinator"})
        r = store.recert_requests.get(rid)
        if r is None:
            raise ApiError(404, "ERR_NOT_FOUND", "recert does not exist")
        if r["status"] != "RETURNED":
            raise ApiError(409, "ERR_INVALID_STATE", "recert not RETURNED")
        if r["revision_count"] >= MAX_RECERT_REVISIONS:
            raise ApiError(422, "ERR_MAX_REVISIONS_EXCEEDED", "max revisions exceeded")
        r["revision_count"] += 1
        r["status"] = "SUBMITTED"
        touch(r)
        return ok(ser_recert(r), 200)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
