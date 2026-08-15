"""Core plumbing for the Asbestos & Lead Abatement Project Management API.

Holds the Flask app, the in-memory store, the logical clock, the response
envelope, error types, auth, validators, serializers and every derived-field
recomputation / cascade helper.  Route modules import from here; nothing here
imports route modules (no circular imports).
"""
import itertools
import secrets
import threading
import uuid
from datetime import datetime, timezone, timedelta

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from flask import Flask, request, jsonify, g
from flask.json.provider import DefaultJSONProvider

# ------------------------------------------------------------------ constants
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = {
    "ContractorAdmin",
    "Supervisor",
    "IndustrialHygienist",
    "RegulatorClerk",
    "FacilityOperator",
}

WORK_TYPES = {"RENOVATION", "DEMOLITION"}
HAZARD_CLASSES = {"ASBESTOS", "LEAD", "MIXED"}
NOTIFICATION_TYPES = {"INITIAL", "REVISION", "EMERGENCY"}
CONTAINMENT_CLASSES = {"FULL", "MINI_ENCLOSURE", "GLOVE_BAG"}
AIR_PHASES = {"BASELINE", "DAILY", "CLEARANCE"}
CERT_LEVELS = {"SUPERVISOR", "HANDLER"}
LAB_RESULTS = {"PENDING", "POSITIVE", "NEGATIVE"}
MANIFEST_STATUSES = {
    "DRAFT", "SEALED", "IN_TRANSIT", "DELIVERED", "CONFIRMED", "REJECTED", "VOIDED",
}
HAZARDS = {"ASBESTOS", "LEAD"}

# calculation constants (SCAFFOLD 1.3 / PRD 3.x)
BAG_TARE_LBS = Decimal("2")
MACHINE_CFM = 2000
MACHINE_HOURLY_CUFT = Decimal(MACHINE_CFM * 60)  # 120,000
ACH_BY_CLASS = {"FULL": 4, "MINI_ENCLOSURE": 6, "GLOVE_BAG": 0}
TIER1_MAX_TONS = Decimal("10")
TIER1_CENTS_PER_TON = Decimal(15000)
TIER2_CENTS_PER_TON = Decimal(12500)
EST_LBS_PER_SQFT = Decimal("1.5")
SURCHARGE_RATE = Decimal("0.08")
CLEARANCE_PASS_F_CC = Decimal("0.010")
PRESSURE_MAX_INWG = Decimal("-0.020")
MIN_CLEARANCE_PASS_COUNT = 2
UNIT_CLEANING_BUFFER = timedelta(days=1)
LBS_PER_TON = Decimal(2000)

# manifest statuses that count toward a project's manifested weight
MANIFEST_WEIGHT_STATUSES = {"SEALED", "IN_TRANSIT", "DELIVERED", "CONFIRMED"}
# manifest statuses that count toward a facility's monthly tonnage
FACILITY_TON_STATUSES = {"DELIVERED", "CONFIRMED"}

# ------------------------------------------------------------------ rounding
_D2 = Decimal("0.01")
_D3 = Decimal("0.001")
_D4 = Decimal("0.0001")
_D0 = Decimal("1")


def q2(x):
    return x.quantize(_D2, rounding=ROUND_HALF_UP)


def q3(x):
    return x.quantize(_D3, rounding=ROUND_HALF_UP)


def q4(x):
    return x.quantize(_D4, rounding=ROUND_HALF_UP)


def q0i(x):
    return int(x.quantize(_D0, rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ app/store
app = Flask(__name__)
app.url_map.strict_slashes = False


class _Provider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return fmt_ts(o)
        return super().default(o)


app.json = _Provider(app)

DB = {
    "projects": {},
    "surveys": {},
    "samples": {},
    "workers": {},
    "assignments": {},
    "notifications": {},
    "containments": {},
    "air_tests": {},
    "manifests": {},
    "facilities": {},
    "units": {},
    "relocations": {},
}

NOT_FOUND_ERRORS = {
    "projects": "ERR_PROJECT_NOT_FOUND",
    "surveys": "ERR_SURVEY_NOT_FOUND",
    "samples": "ERR_SAMPLE_NOT_FOUND",
    "workers": "ERR_WORKER_NOT_FOUND",
    "assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "notifications": "ERR_NOTIFICATION_NOT_FOUND",
    "containments": "ERR_CONTAINMENT_NOT_FOUND",
    "air_tests": "ERR_AIR_TEST_NOT_FOUND",
    "manifests": "ERR_MANIFEST_NOT_FOUND",
    "facilities": "ERR_FACILITY_NOT_FOUND",
    "units": "ERR_UNIT_NOT_FOUND",
    "relocations": "ERR_RELOCATION_NOT_FOUND",
}

_SEQ = itertools.count(1)
CLOCK = {"now": CLOCK_START}
LOCK = threading.RLock()


# ------------------------------------------------------------------ time
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an ISO 8601 timestamp string")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    return CLOCK["now"]


def month_window(instant):
    start = instant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return start, nxt


def hours_between(start, end):
    """Exact half-open window length in hours at 2dp, round-half-up."""
    delta = end - start
    seconds = (
        Decimal(delta.days * 86400 + delta.seconds)
        + Decimal(delta.microseconds) / Decimal(1000000)
    )
    return q2(seconds / Decimal(3600))


# ------------------------------------------------------------------ errors
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def _handle_404(exc):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def _handle_405(exc):
    return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 405


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    import traceback

    traceback.print_exc()
    return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500


# ------------------------------------------------------------------ request lock
@app.before_request
def _acquire_lock():
    LOCK.acquire()
    g._lock_held = True


@app.teardown_request
def _release_lock(exc):
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        LOCK.release()


# ------------------------------------------------------------------ auth
def authenticate():
    """Rung 1: both headers present, role declared -> (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(role, *allowed):
    """Rung 2: role permitted for this endpoint."""
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE",
            403,
            f"Role {role} is not permitted for this endpoint",
        )


# ------------------------------------------------------------------ validation helpers
def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {name}")
    return data[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a string")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a boolean")
    return value


def as_enum(value, name, allowed):
    value = as_str(value, name)
    if value not in allowed:
        raise ApiError(
            "ERR_VALIDATION", 400, f"{name} must be one of {sorted(allowed)}"
        )
    return value


def as_int(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be >= {minimum}")
    return value


def as_num(value, name, gt=None, ge=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a number")
    dec = Decimal(str(value))
    if not dec.is_finite():
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a finite number")
    if gt is not None and not dec > gt:
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be > {gt}")
    if ge is not None and not dec >= ge:
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be >= {ge}")
    return dec


def as_dt(value, name):
    """Return the parsed datetime; the raw string is kept for echo separately."""
    return parse_iso(value, name)


def opt_dt(data, name):
    """Optional datetime field -> (raw, parsed) or None."""
    if name not in data or data[name] is None:
        return None
    raw = data[name]
    return raw, parse_iso(raw, name)


def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw, 10)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw, 10)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list(page, limit, offset, total)


# ------------------------------------------------------------------ records
def new_record(kind, fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    rec["_kind"] = kind
    rec["_seq"] = next(_SEQ)
    DB[kind][rec["id"]] = rec
    return rec


def touch(rec):
    """Mutation stamp: refreshed updated_at always; one version bump per request."""
    rec["updated_at"] = now()
    bumped = getattr(g, "_bumped", None)
    if bumped is None:
        bumped = set()
        g._bumped = bumped
    key = (rec["_kind"], rec["id"])
    if key not in bumped:
        rec["version"] += 1
        bumped.add(key)


def get_rec(kind, rec_id):
    rec = DB[kind].get(rec_id)
    if rec is None:
        label = kind[:-1].replace("_", " ")
        raise ApiError(NOT_FOUND_ERRORS[kind], 404, f"{label} {rec_id} not found")
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ------------------------------------------------------------------ derived fields
def samples_of(survey_id):
    return [s for s in DB["samples"].values() if s["survey_id"] == survey_id]


def survey_aggregates(survey_id):
    provisional = Decimal("0")
    final = Decimal("0")
    friable = Decimal("0")
    for s in samples_of(survey_id):
        qty = s["quantity_sq_ft"]
        if s["lab_result"] in ("PENDING", "POSITIVE"):
            provisional += qty
        if s["lab_result"] == "POSITIVE":
            final += qty
            if s["friable"]:
                friable += qty
    return q2(provisional), q2(final), q2(friable)


def sync_survey(survey):
    p, f, fr = survey_aggregates(survey["id"])
    changed = (
        survey["acm_sq_ft_provisional"] != p
        or survey["acm_sq_ft_final"] != f
        or survey["friable_acm_sq_ft_final"] != fr
    )
    survey["acm_sq_ft_provisional"] = p
    survey["acm_sq_ft_final"] = f
    survey["friable_acm_sq_ft_final"] = fr
    if changed:
        touch(survey)


def worker_hours(worker_id):
    total = Decimal("0")
    for a in DB["assignments"].values():
        if a["worker_id"] == worker_id and a["status"] == "SCHEDULED":
            total += a["scheduled_hours"]
    return q2(total)


def sync_worker_hours(worker):
    value = worker_hours(worker["id"])
    if worker["assigned_scheduled_hours"] != value:
        worker["assigned_scheduled_hours"] = value
        touch(worker)


def project_manifested_weight(project_id):
    total = Decimal("0")
    for m in DB["manifests"].values():
        if m["project_id"] == project_id and m["status"] in MANIFEST_WEIGHT_STATUSES:
            total += m["net_weight_lbs"]
    return q2(total)


def project_final_disposal(project_id):
    total = 0
    for m in DB["manifests"].values():
        if m["project_id"] == project_id and m["status"] == "CONFIRMED":
            total += m["fee_cents"] if m["fee_cents"] is not None else 0
    return total


def sync_project_ledger(project, rollup=False):
    """Refresh manifested weight / final disposal; rollup only where documented."""
    changed = False
    weight = project_manifested_weight(project["id"])
    disposal = project_final_disposal(project["id"])
    if project["manifested_weight_lbs"] != weight:
        project["manifested_weight_lbs"] = weight
        changed = True
    if project["final_disposal_cost_cents"] != disposal:
        project["final_disposal_cost_cents"] = disposal
        changed = True
    if rollup:
        subtotal = project["base_abatement_cost_cents"] + project["final_disposal_cost_cents"]
        surcharge = q0i(Decimal(subtotal) * SURCHARGE_RATE)
        total = subtotal + surcharge
        if project["insurance_surcharge_cents"] != surcharge:
            project["insurance_surcharge_cents"] = surcharge
            changed = True
        if project["total_project_cost_cents"] != total:
            project["total_project_cost_cents"] = total
            changed = True
    if changed:
        touch(project)


def containment_of_project(project_id):
    for c in DB["containments"].values():
        if c["project_id"] == project_id:
            return c
    return None


def reoccupancy(project):
    """clearance_readiness: OPEN iff 0 fails and >= 2 passes collected strictly
    after the containment's last verification instant (all if never verified)."""
    cont = containment_of_project(project["id"])
    verified_at = cont["last_verified_at"] if cont is not None else None
    passes = 0
    fails = 0
    for t in DB["air_tests"].values():
        if (
            t["project_id"] == project["id"]
            and t["phase"] == "CLEARANCE"
            and t["status"] == "REPORTED"
        ):
            if verified_at is None or t["_collected_at"] > verified_at:
                if t["outcome"] == "PASS":
                    passes += 1
                elif t["outcome"] == "FAIL":
                    fails += 1
    return "OPEN" if (fails == 0 and passes >= MIN_CLEARANCE_PASS_COUNT) else "BLOCKED"


def sync_reoccupancy(project):
    value = reoccupancy(project)
    if project["reoccupancy_status"] != value:
        project["reoccupancy_status"] = value
        touch(project)


def facility_tons(facility_id):
    start, nxt = month_window(now())
    total = Decimal("0")
    for m in DB["manifests"].values():
        if (
            m["facility_id"] == facility_id
            and m["status"] in FACILITY_TON_STATUSES
            and m["delivered_at"] is not None
            and start <= m["delivered_at"] < nxt
        ):
            total += m["net_tons"]
    return q4(total)


def sync_facility_tons(facility):
    value = facility_tons(facility["id"])
    if facility["delivered_tons_current_month"] != value:
        facility["delivered_tons_current_month"] = value
        touch(facility)


def latest_notification(project_id):
    candidates = [n for n in DB["notifications"].values() if n["project_id"] == project_id]
    if not candidates:
        return None
    return max(candidates, key=lambda n: (n["filed_at"], n["created_at"], n["_seq"]))


def supervisor_coverage(project_id, instant):
    for a in DB["assignments"].values():
        if (
            a["project_id"] == project_id
            and a["role_on_site"] == "SUPERVISOR"
            and a["status"] == "SCHEDULED"
            and a["_start_at"] <= instant < a["_end_at"]
        ):
            return True
    return False


def machine_count(volume_cuft, containment_class):
    """negative_air_machine_count: ceil first, then floor of one machine."""
    ach = ACH_BY_CLASS[containment_class]
    if containment_class == "GLOVE_BAG":
        return ach, 0
    machines = int(
        (volume_cuft * Decimal(ach) / MACHINE_HOURLY_CUFT).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    return ach, max(1, machines)


def estimated_disposal_cost(total_acm_sq_ft):
    """disposal_cost, estimated variant (survey finalize)."""
    tons_est = total_acm_sq_ft * EST_LBS_PER_SQFT / LBS_PER_TON
    rate = TIER1_CENTS_PER_TON if tons_est <= TIER1_MAX_TONS else TIER2_CENTS_PER_TON
    return q0i(tons_est * rate)


def manifest_fee(net_tons):
    """manifest_disposal_fee: per-manifest tier rate, rounded half-up to cents."""
    rate = TIER1_CENTS_PER_TON if net_tons <= TIER1_MAX_TONS else TIER2_CENTS_PER_TON
    return q0i(net_tons * rate)


# ------------------------------------------------------------------ sweeps
def run_sweeps():
    """Clock-advance sweeps, in the documented order (PRD 2.4)."""
    current = now()
    # 1. Worker lapse evaluation with its cascade.
    for w in list(DB["workers"].values()):
        if w["status"] != "ACTIVE":
            continue
        earliest = min(w["_cert_expires_at"], w["_medical_clearance_expires_at"], w["_respirator_fit_expires_at"])
        if current >= earliest:
            w["status"] = "LAPSED"
            touch(w)
            affected_projects = set()
            for a in list(DB["assignments"].values()):
                if a["worker_id"] == w["id"] and a["status"] == "SCHEDULED":
                    a["status"] = "SUSPENDED"
                    touch(a)
                    affected_projects.add(a["project_id"])
            sync_worker_hours(w)
            for pid in affected_projects:
                project = DB["projects"].get(pid)
                if (
                    project is not None
                    and project["status"] == "IN_PROGRESS"
                    and not supervisor_coverage(pid, current)
                ):
                    project["status"] = "SUSPENDED"
                    touch(project)
    # 2. Assignment completion.
    for a in list(DB["assignments"].values()):
        if a["status"] in ("SCHEDULED", "SUSPENDED") and a["_end_at"] <= current:
            was_scheduled = a["status"] == "SCHEDULED"
            a["status"] = "COMPLETED"
            touch(a)
            if was_scheduled:
                worker = DB["workers"].get(a["worker_id"])
                if worker is not None:
                    sync_worker_hours(worker)
    # 3. Unit cleaning release.
    for u in list(DB["units"].values()):
        if (
            u["status"] == "CLEANING"
            and u["cleaning_until"] is not None
            and current >= u["cleaning_until"]
        ):
            u["status"] = "AVAILABLE"
            touch(u)


# ------------------------------------------------------------------ serializers
def serialize_project(p):
    d = public(p)
    d["manifested_weight_lbs"] = project_manifested_weight(p["id"])
    d["final_disposal_cost_cents"] = project_final_disposal(p["id"])
    d["reoccupancy_status"] = reoccupancy(p)
    return d


def serialize_survey(s):
    d = public(s)
    p, f, fr = survey_aggregates(s["id"])
    d["acm_sq_ft_provisional"] = p
    d["acm_sq_ft_final"] = f
    d["friable_acm_sq_ft_final"] = fr
    return d


def serialize_sample(s):
    return public(s)


def serialize_worker(w):
    d = public(w)
    d["assigned_scheduled_hours"] = worker_hours(w["id"])
    return d


def serialize_assignment(a):
    return public(a)


def serialize_notification(n):
    return public(n)


def serialize_containment(c):
    return public(c)


def serialize_air_test(t):
    return public(t)


def serialize_manifest(m):
    return public(m)


def serialize_facility(f):
    d = public(f)
    d["delivered_tons_current_month"] = facility_tons(f["id"])
    return d


def serialize_unit(u):
    return public(u)


def serialize_relocation(r):
    return public(r)


def by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
