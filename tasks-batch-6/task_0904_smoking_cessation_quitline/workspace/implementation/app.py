"""
Smoking-Cessation & Quitline Program API (Task 0904)
Single-file Flask implementation. In-memory storage only; the process starts
with an empty store on every boot (tests build all state via the API surface).
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 / PRD §2)
# ---------------------------------------------------------------------------
READINESS_PASS_THRESHOLD = 12
PROTOCOL_CALL_TARGET = 4
DEFAULT_SELF_PAY_NRT_COURSES = 2
COMPLETION_BONUS_RATE = Decimal("0.075")
COACH_BUFFER_MINUTES = 15
SCHEDULE_MIN_LEAD_MINUTES = 60
INCENTIVE_AMOUNTS = {
    "ENROLLMENT": 1000,
    "QUIT_DATE_SET": 1500,
    "SEVEN_DAY_ABSTINENT": 2500,
    "THIRTY_DAY_ABSTINENT": 5000,
    "PROTOCOL_COMPLETE": 2000,
}

ROLES = {"ProgramAdmin", "CaseManager", "Participant"}

PROTOCOL_ENUM = {"STANDARD", "INTENSIVE"}
QUIT_METHOD_ENUM = {"COLD_TURKEY", "NRT_ASSISTED", "MEDICATION", "GRADUAL_REDUCTION"}
MEDICATION_ENUM = {"PATCH", "GUM", "LOZENGE", "VARENICLINE", "BUPROPION"}
MILESTONE_ENUM = {
    "ENROLLMENT", "QUIT_DATE_SET", "SEVEN_DAY_ABSTINENT",
    "THIRTY_DAY_ABSTINENT", "PROTOCOL_COMPLETE", "DISCRETIONARY",
}
REFERRAL_ENUM = {"PROVIDER", "BENEFIT", "PHARMACY"}
QUIT_STATUS_ENUM = {"COMMITTED", "QUIT_ACHIEVED", "RELAPSED", "ABANDONED"}
CALL_STATUS_ENUM = {"SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELED"}
SHIP_STATUS_ENUM = {"REQUESTED", "APPROVED", "SHIPPED", "DELIVERED", "CANCELED", "RETURNED"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}

employer_programs = {}
coaches = {}
participants = {}
enrollments = {}
readiness_assessments = {}
quit_attempts = {}
coaching_calls = {}
nrt_shipments = {}
incentive_awards = {}
follow_ups = {}
referrals = {}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now():
    return CLOCK["now"]


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        dt = datetime.fromisoformat(t + "T00:00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": fmt_ts(now())}


def respond(data, response_type="object", status=200, pagination=None):
    m = meta_base()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    d = request.get_json(silent=True)
    if d is None:
        return {}
    if not isinstance(d, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return d


_MISSING = object()


def v_int(d, key, required=True, default=None, minimum=None, maximum=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if isinstance(val, bool) or not isinstance(val, int):
        err("ERR_VALIDATION", 400, "%s must be an integer" % key)
    if minimum is not None and val < minimum:
        err("ERR_VALIDATION", 400, "%s below minimum" % key)
    if maximum is not None and val > maximum:
        err("ERR_VALIDATION", 400, "%s above maximum" % key)
    return val


def v_str(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, str) or val == "":
        err("ERR_VALIDATION", 400, "%s must be a non-empty string" % key)
    return val


def v_enum(d, key, allowed, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, str) or val not in allowed:
        err("ERR_VALIDATION", 400, "%s is not a valid value" % key)
    return val


def v_bool(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, bool):
        err("ERR_VALIDATION", 400, "%s must be a boolean" % key)
    return val


def v_datetime(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    try:
        parse_iso(val)
    except Exception:
        err("ERR_VALIDATION", 400, "%s must be a valid ISO 8601 datetime" % key)
    return val


def v_array(d, key, required=True, default=None):
    if key not in d or d[key] is None:
        if required:
            err("ERR_VALIDATION", 400, "%s is required" % key)
        return default
    val = d[key]
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        err("ERR_VALIDATION", 400, "%s must be an array of strings" % key)
    return val


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    lim = request.args.get("limit")
    off = request.args.get("offset")
    if lim is None:
        limit = 10
    else:
        try:
            limit = int(lim)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit out of range")
    if off is None:
        offset = 0
    else:
        try:
            offset = int(off)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def paginate_and_respond(items, serializer):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return respond([serializer(x) for x in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = fmt_ts(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_event():
    ts = fmt_ts(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(now())


# ---------------------------------------------------------------------------
# Sponsor / budget helpers
# ---------------------------------------------------------------------------
def sponsor_program(enr):
    p = participants.get(enr["participant_id"])
    if not p:
        return None
    pid = p.get("employer_program_id")
    if not pid:
        return None
    return employer_programs.get(pid)


def enr_awards(enr_id):
    return [a for a in incentive_awards.values() if a["enrollment_id"] == enr_id]


def create_system_award(enr, milestone_type):
    prog = sponsor_program(enr)
    if not prog:
        return None
    amount = INCENTIVE_AMOUNTS[milestone_type]
    award = new_common()
    award.update({
        "enrollment_id": enr["id"],
        "milestone_type": milestone_type,
        "amount_cents": amount,
        "status": "EARNED",
        "source": "SYSTEM",
    })
    incentive_awards[award["id"]] = award
    prog["budget_remaining_cents"] -= amount
    bump(prog)
    return award


def forfeit_awards(enr, milestone_types):
    prog = sponsor_program(enr)
    awards = sorted(enr_awards(enr["id"]), key=lambda a: a["_seq"])
    for a in awards:
        if a["status"] == "EARNED" and a["milestone_type"] in milestone_types:
            a["status"] = "FORFEITED"
            bump(a)
            if prog:
                prog["budget_remaining_cents"] += a["amount_cents"]
                bump(prog)


# ---------------------------------------------------------------------------
# Derived enrollment fields
# ---------------------------------------------------------------------------
def enr_children(store, enr_id):
    return [x for x in store.values() if x["enrollment_id"] == enr_id]


def latest_assessment(enr_id):
    items = enr_children(readiness_assessments, enr_id)
    if not items:
        return None
    return max(items, key=lambda x: x["_seq"])


def nrt_used_count(enr_id):
    return sum(1 for s in nrt_shipments.values()
               if s["enrollment_id"] == enr_id and s["status"] == "DELIVERED")


def completed_calls_count(enr_id):
    return sum(1 for c in coaching_calls.values()
               if c["enrollment_id"] == enr_id and c["status"] == "COMPLETED")


def incentive_earned(enr_id):
    return sum(a["amount_cents"] for a in incentive_awards.values()
               if a["enrollment_id"] == enr_id and a["status"] in ("EARNED", "PAID"))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_program(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "name": p["name"],
        "budget_total_cents": p["budget_total_cents"],
        "budget_remaining_cents": p["budget_remaining_cents"],
        "coaching_protocol": p["coaching_protocol"],
        "nrt_courses_allotted": p["nrt_courses_allotted"], "status": p["status"],
    }


def s_coach(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "full_name": c["full_name"], "languages": c["languages"],
    }


def s_participant(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "full_name": p["full_name"], "email": p["email"],
        "primary_language": p["primary_language"],
        "cigarettes_per_day": p["cigarettes_per_day"],
        "employer_program_id": p["employer_program_id"],
    }


def s_enrollment(e):
    eid = e["id"]
    la = latest_assessment(eid)
    allotted = e["nrt_courses_allotted"]
    used = nrt_used_count(eid)
    remaining = allotted - used
    eligibility = "EXHAUSTED" if used >= allotted else "ELIGIBLE"
    ccalls = completed_calls_count(eid)
    return {
        "id": eid, "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "participant_id": e["participant_id"],
        "status": e["status"],
        "readiness_score": la["readiness_score"] if la else None,
        "readiness_result": la["result"] if la else None,
        "nrt_courses_allotted": allotted,
        "nrt_courses_used": used,
        "nrt_courses_remaining": remaining,
        "nrt_eligibility": eligibility,
        "incentive_earned_cents": incentive_earned(eid),
        "completed_calls": ccalls,
        "protocol_complete": ccalls >= PROTOCOL_CALL_TARGET,
    }


def s_assessment(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "enrollment_id": a["enrollment_id"],
        "motivation_score": a["motivation_score"], "confidence_score": a["confidence_score"],
        "prior_quit_attempts": a["prior_quit_attempts"],
        "cigarettes_per_day": a["cigarettes_per_day"],
        "readiness_score": a["readiness_score"], "result": a["result"],
    }


def s_quit(q):
    return {
        "id": q["id"], "created_at": q["created_at"], "updated_at": q["updated_at"],
        "version": q["version"], "enrollment_id": q["enrollment_id"],
        "quit_date": q["quit_date"], "method": q["method"], "status": q["status"],
        "attempt_number": q["attempt_number"],
    }


def s_call(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "enrollment_id": c["enrollment_id"],
        "coach_id": c["coach_id"], "scheduled_start": c["scheduled_start"],
        "duration_minutes": c["duration_minutes"], "status": c["status"],
    }


def s_ship(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "enrollment_id": s["enrollment_id"],
        "medication_type": s["medication_type"],
        "course_start_date": s["course_start_date"], "course_end_date": s["course_end_date"],
        "weeks_supply": s["weeks_supply"], "dose_mg": s["dose_mg"], "status": s["status"],
    }


def s_award(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "enrollment_id": a["enrollment_id"],
        "milestone_type": a["milestone_type"], "amount_cents": a["amount_cents"],
        "status": a["status"], "source": a["source"],
    }


def s_referral(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "enrollment_id": r["enrollment_id"],
        "referral_type": r["referral_type"], "target_name": r["target_name"],
        "status": r["status"],
    }


def s_followup(f):
    return {
        "id": f["id"], "created_at": f["created_at"], "enrollment_id": f["enrollment_id"],
        "day": f["day"], "abstinent": f["abstinent"], "recorded_at": f["recorded_at"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers (existence)
# ---------------------------------------------------------------------------
def get_program_or_404(pid):
    p = employer_programs.get(pid)
    if not p:
        err("ERR_EMPLOYER_PROGRAM_NOT_FOUND", 404, "Employer program not found")
    return p


def get_coach_or_404(cid):
    c = coaches.get(cid)
    if not c:
        err("ERR_COACH_NOT_FOUND", 404, "Coach not found")
    return c


def get_participant_or_404(pid):
    p = participants.get(pid)
    if not p:
        err("ERR_PARTICIPANT_NOT_FOUND", 404, "Participant not found")
    return p


def get_enrollment_or_404(eid):
    e = enrollments.get(eid)
    if not e:
        err("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    return e


def get_quit_or_404(qid):
    q = quit_attempts.get(qid)
    if not q:
        err("ERR_QUIT_ATTEMPT_NOT_FOUND", 404, "Quit attempt not found")
    return q


def get_call_or_404(cid):
    c = coaching_calls.get(cid)
    if not c:
        err("ERR_COACHING_CALL_NOT_FOUND", 404, "Coaching call not found")
    return c


def get_ship_or_404(sid):
    s = nrt_shipments.get(sid)
    if not s:
        err("ERR_NRT_SHIPMENT_NOT_FOUND", 404, "NRT shipment not found")
    return s


def require_owns_enrollment(role, uid, enr):
    if role == "Participant" and enr["participant_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Participant may only act on its own resources")


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    data = get_body()
    iso = v_datetime(data, "to_iso8601")
    CLOCK["now"] = parse_iso(iso)
    return respond({"current_utc": fmt_ts(CLOCK["now"])}, "object", 200)


# ===========================================================================
# EmployerProgram
# ===========================================================================
@app.route("/employer-programs", methods=["POST"])
def create_program():
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    data = get_body()
    name = v_str(data, "name")
    budget = v_int(data, "budget_total_cents", minimum=0)
    protocol = v_enum(data, "coaching_protocol", PROTOCOL_ENUM, required=False, default="STANDARD")
    allotted = v_int(data, "nrt_courses_allotted", required=False, default=3, minimum=0)
    p = new_common()
    p.update({
        "name": name, "budget_total_cents": budget, "budget_remaining_cents": budget,
        "coaching_protocol": protocol, "nrt_courses_allotted": allotted, "status": "ACTIVE",
    })
    employer_programs[p["id"]] = p
    return respond(s_program(p), "object", 201)


@app.route("/employer-programs/<pid>", methods=["GET"])
def get_program(pid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager"})
    p = get_program_or_404(pid)
    return respond(s_program(p), "object", 200)


@app.route("/employer-programs/<pid>/close", methods=["POST"])
def close_program(pid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    p = get_program_or_404(pid)
    data = get_body()
    expected = v_int(data, "expected_employer_program_version")
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Program is not ACTIVE")
    if expected != p["version"]:
        err("ERR_STALE_VERSION", 412, "Program version mismatch")
    p["status"] = "CLOSED"
    bump(p)
    return respond(s_program(p), "object", 200)


@app.route("/employer-programs/<pid>/participants", methods=["GET"])
def list_program_participants(pid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager"})
    get_program_or_404(pid)
    items = [p for p in participants.values() if p.get("employer_program_id") == pid]
    return paginate_and_respond(items, s_participant)


@app.route("/employer-programs/<pid>/outcome-report", methods=["GET"])
def outcome_report(pid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    get_program_or_404(pid)
    clock = now()
    # cohort: enrollments of participants sponsored by program with a matured quit attempt
    sponsored_pids = {p["id"] for p in participants.values() if p.get("employer_program_id") == pid}
    cohort = []
    for e in enrollments.values():
        if e["participant_id"] not in sponsored_pids:
            continue
        qas = enr_children(quit_attempts, e["id"])
        matured = any(
            clock >= parse_iso(q["quit_date"]) + timedelta(days=30)
            for q in qas if q.get("quit_date")
        )
        if matured:
            cohort.append(e)
    n = len(cohort)
    if n == 0:
        seven_rate = 0.0
        cont_rate = 0.0
    else:
        seven = 0
        cont = 0
        for e in cohort:
            fos = enr_children(follow_ups, e["id"])
            has7 = any(f["day"] == 7 and f["abstinent"] for f in fos)
            has30 = any(f["day"] == 30 and f["abstinent"] for f in fos)
            if has7:
                seven += 1
            if has7 and has30:
                cont += 1
        seven_rate = float(round_half_up(Decimal(100 * seven) / Decimal(n), 1))
        cont_rate = float(round_half_up(Decimal(100 * cont) / Decimal(n), 1))
    return respond({
        "cohort_size": n,
        "point_prevalence_7day_rate": seven_rate,
        "continuous_30day_rate": cont_rate,
    }, "object", 200)


# ===========================================================================
# Coach
# ===========================================================================
@app.route("/coaches", methods=["POST"])
def create_coach():
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    data = get_body()
    full_name = v_str(data, "full_name")
    languages = v_array(data, "languages")
    c = new_common()
    c.update({"full_name": full_name, "languages": languages})
    coaches[c["id"]] = c
    return respond(s_coach(c), "object", 201)


@app.route("/coaches/<cid>", methods=["GET"])
def get_coach(cid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager"})
    c = get_coach_or_404(cid)
    return respond(s_coach(c), "object", 200)


@app.route("/coaches/<cid>/coaching-calls", methods=["GET"])
def list_coach_calls(cid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager"})
    get_coach_or_404(cid)
    items = [c for c in coaching_calls.values() if c["coach_id"] == cid]
    return paginate_and_respond(items, s_call)


# ===========================================================================
# Participant
# ===========================================================================
@app.route("/participants", methods=["POST"])
def create_participant():
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager"})
    data = get_body()
    full_name = v_str(data, "full_name")
    email = v_str(data, "email")
    lang = v_str(data, "primary_language")
    cpd = v_int(data, "cigarettes_per_day", minimum=0)
    epid = data.get("employer_program_id")
    if epid is not None:
        if not isinstance(epid, str) or epid == "":
            err("ERR_VALIDATION", 400, "employer_program_id must be a string")
        get_program_or_404(epid)
    p = new_common()
    p.update({
        "full_name": full_name, "email": email, "primary_language": lang,
        "cigarettes_per_day": cpd, "employer_program_id": epid,
    })
    participants[p["id"]] = p
    return respond(s_participant(p), "object", 201)


@app.route("/participants/<pid>", methods=["GET"])
def get_participant(pid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    p = get_participant_or_404(pid)
    if role == "Participant" and pid != uid:
        err("ERR_UNAUTHORIZED", 403, "Participant may only read itself")
    return respond(s_participant(p), "object", 200)


@app.route("/participants/<pid>/enrollments", methods=["GET"])
def list_participant_enrollments(pid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    get_participant_or_404(pid)
    if role == "Participant" and pid != uid:
        err("ERR_UNAUTHORIZED", 403, "Participant may only read its own enrollments")
    items = [e for e in enrollments.values() if e["participant_id"] == pid]
    return paginate_and_respond(items, s_enrollment)


@app.route("/participants/<pid>/enrollments", methods=["POST"])
def create_enrollment(pid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    p = get_participant_or_404(pid)
    epid = p.get("employer_program_id")
    if epid and epid in employer_programs:
        allotted = employer_programs[epid]["nrt_courses_allotted"]
    else:
        allotted = DEFAULT_SELF_PAY_NRT_COURSES
    e = new_common()
    e.update({
        "participant_id": pid, "status": "PENDING_ASSESSMENT",
        "nrt_courses_allotted": allotted,
    })
    enrollments[e["id"]] = e
    return respond(s_enrollment(e), "object", 201)


# ===========================================================================
# Enrollment lifecycle
# ===========================================================================
@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return respond(s_enrollment(e), "object", 200)


@app.route("/enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    if e["status"] != "PENDING_ASSESSMENT":
        err("ERR_INVALID_STATE", 409, "Enrollment is not PENDING_ASSESSMENT")
    la = latest_assessment(eid)
    if la is None or la["result"] != "PASS":
        err("ERR_READINESS_NOT_MET", 422, "Latest readiness result is not PASS")
    e["status"] = "ACTIVE"
    bump(e)
    create_system_award(e, "ENROLLMENT")
    return respond(s_enrollment(e), "object", 200)


@app.route("/enrollments/<eid>/disenroll", methods=["POST"])
def disenroll_enrollment(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    status = e["status"]
    if status == "PENDING_ASSESSMENT":
        e["status"] = "DECLINED"
        bump(e)
        return respond(s_enrollment(e), "object", 200)
    if status != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Enrollment cannot be disenrolled from its current state")
    # ACTIVE -> DISENROLLED full cascade
    abandoned = False
    for q in sorted(enr_children(quit_attempts, eid), key=lambda x: x["_seq"]):
        if q["status"] in ("COMMITTED", "QUIT_ACHIEVED", "RELAPSED"):
            q["status"] = "ABANDONED"
            bump(q)
            abandoned = True
    if abandoned:
        forfeit_awards(e, {"QUIT_DATE_SET", "SEVEN_DAY_ABSTINENT", "THIRTY_DAY_ABSTINENT"})
    for c in enr_children(coaching_calls, eid):
        if c["status"] == "SCHEDULED":
            c["status"] = "CANCELED"
            bump(c)
    for s in enr_children(nrt_shipments, eid):
        if s["status"] in ("REQUESTED", "APPROVED", "SHIPPED"):
            s["status"] = "CANCELED"
            bump(s)
    for r in enr_children(referrals, eid):
        if r["status"] == "OPEN":
            r["status"] = "CLOSED"
            bump(r)
    e["status"] = "DISENROLLED"
    bump(e)
    return respond(s_enrollment(e), "object", 200)


# ===========================================================================
# ReadinessAssessment
# ===========================================================================
def compute_readiness(motivation, confidence, prior, cpd):
    if prior == 0:
        prior_bonus = 0
    elif 1 <= prior <= 2:
        prior_bonus = 1
    else:
        prior_bonus = 2
    if cpd <= 10:
        penalty = 0
    elif 11 <= cpd <= 20:
        penalty = 1
    else:
        penalty = 2
    score = motivation + confidence + prior_bonus - penalty
    result = "PASS" if score >= READINESS_PASS_THRESHOLD else "FAIL"
    return score, result


@app.route("/enrollments/<eid>/readiness-assessments", methods=["POST"])
def create_assessment(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    data = get_body()
    motivation = v_int(data, "motivation_score", minimum=1, maximum=10)
    confidence = v_int(data, "confidence_score", minimum=1, maximum=10)
    prior = v_int(data, "prior_quit_attempts", minimum=0)
    participant = participants[e["participant_id"]]
    cpd = participant["cigarettes_per_day"]
    score, result = compute_readiness(motivation, confidence, prior, cpd)
    a = new_event()
    a.update({
        "enrollment_id": eid, "motivation_score": motivation, "confidence_score": confidence,
        "prior_quit_attempts": prior, "cigarettes_per_day": cpd,
        "readiness_score": score, "result": result,
    })
    readiness_assessments[a["id"]] = a
    return respond(s_assessment(a), "object", 201)


@app.route("/enrollments/<eid>/readiness-assessments", methods=["GET"])
def list_assessments(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(readiness_assessments, eid), s_assessment)


# ===========================================================================
# QuitAttempt
# ===========================================================================
@app.route("/enrollments/<eid>/quit-attempts", methods=["POST"])
def create_quit(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    data = get_body()
    quit_date = v_datetime(data, "quit_date")
    method = v_enum(data, "method", QUIT_METHOD_ENUM)
    if e["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    existing = enr_children(quit_attempts, eid)
    attempt_number = len(existing) + 1
    q = new_common()
    q.update({
        "enrollment_id": eid, "quit_date": quit_date, "method": method,
        "status": "COMMITTED", "attempt_number": attempt_number,
    })
    quit_attempts[q["id"]] = q
    if attempt_number == 1:
        create_system_award(e, "QUIT_DATE_SET")
    return respond(s_quit(q), "object", 201)


@app.route("/enrollments/<eid>/quit-attempts", methods=["GET"])
def list_quits(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(quit_attempts, eid), s_quit)


@app.route("/quit-attempts/<qid>/transition", methods=["POST"])
def transition_quit(qid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    q = get_quit_or_404(qid)
    data = get_body()
    to_status = v_enum(data, "to_status", QUIT_STATUS_ENUM)
    e = enrollments[q["enrollment_id"]]
    current = q["status"]
    if to_status == "RELAPSED":
        if current not in ("COMMITTED", "QUIT_ACHIEVED"):
            err("ERR_INVALID_STATE", 409, "Cannot relapse from current state")
        q["status"] = "RELAPSED"
        bump(q)
        forfeit_awards(e, {"SEVEN_DAY_ABSTINENT", "THIRTY_DAY_ABSTINENT"})
    elif to_status == "COMMITTED":
        if current != "RELAPSED":
            err("ERR_INVALID_STATE", 409, "Recommit only allowed from RELAPSED")
        if e["status"] != "ACTIVE":
            err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
        new_date = data.get("quit_date")
        if new_date is None:
            err("ERR_VALIDATION", 400, "quit_date is required for recommit")
        v_datetime(data, "quit_date")
        q["status"] = "COMMITTED"
        q["quit_date"] = new_date
        bump(q)
    else:
        err("ERR_INVALID_STATE", 409, "Transition not allowed via this endpoint")
    return respond(s_quit(q), "object", 200)


# ===========================================================================
# CoachingCall
# ===========================================================================
def coach_has_conflict(coach_id, new_start, new_end):
    buf = timedelta(minutes=COACH_BUFFER_MINUTES)
    for c in coaching_calls.values():
        if c["coach_id"] != coach_id:
            continue
        if c["status"] not in ("SCHEDULED", "COMPLETED", "NO_SHOW"):
            continue
        cs = parse_iso(c["scheduled_start"])
        ce = cs + timedelta(minutes=c["duration_minutes"])
        if new_start < ce + buf and cs < new_end + buf:
            return True
    return False


@app.route("/enrollments/<eid>/coaching-calls", methods=["POST"])
def create_call(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    data = get_body()
    coach_id = v_str(data, "coach_id")
    scheduled_start = v_datetime(data, "scheduled_start")
    duration = v_int(data, "duration_minutes", minimum=1)
    coach = get_coach_or_404(coach_id)
    if e["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    participant = participants[e["participant_id"]]
    if participant["primary_language"] not in coach["languages"]:
        err("ERR_COACH_LANGUAGE_MISMATCH", 409, "Coach does not speak participant's language")
    start = parse_iso(scheduled_start)
    if start < now() + timedelta(minutes=SCHEDULE_MIN_LEAD_MINUTES):
        err("ERR_SCHEDULE_WINDOW_INVALID", 409, "Scheduled start is inside the lead window")
    end = start + timedelta(minutes=duration)
    if coach_has_conflict(coach_id, start, end):
        err("ERR_COACH_DOUBLE_BOOKED", 409, "Coach is double-booked")
    c = new_common()
    c.update({
        "enrollment_id": eid, "coach_id": coach_id, "scheduled_start": scheduled_start,
        "duration_minutes": duration, "status": "SCHEDULED",
    })
    coaching_calls[c["id"]] = c
    return respond(s_call(c), "object", 201)


@app.route("/enrollments/<eid>/coaching-calls", methods=["GET"])
def list_calls(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(coaching_calls, eid), s_call)


@app.route("/coaching-calls/<cid>/transition", methods=["POST"])
def transition_call(cid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    c = get_call_or_404(cid)
    data = get_body()
    to_status = v_enum(data, "to_status", CALL_STATUS_ENUM)
    e = enrollments[c["enrollment_id"]]
    current = c["status"]
    if to_status == "COMPLETED":
        if current != "SCHEDULED":
            err("ERR_INVALID_STATE", 409, "Only SCHEDULED calls can be completed")
        if e["status"] != "ACTIVE":
            err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
        c["status"] = "COMPLETED"
        bump(c)
        ccount = completed_calls_count(e["id"])
        if ccount == PROTOCOL_CALL_TARGET:
            has_protocol = any(a["milestone_type"] == "PROTOCOL_COMPLETE"
                               for a in enr_awards(e["id"]))
            if not has_protocol:
                create_system_award(e, "PROTOCOL_COMPLETE")
    elif to_status == "NO_SHOW":
        if current != "SCHEDULED":
            err("ERR_INVALID_STATE", 409, "Only SCHEDULED calls can be no-showed")
        c["status"] = "NO_SHOW"
        bump(c)
    elif to_status == "CANCELED":
        if current != "SCHEDULED":
            err("ERR_INVALID_STATE", 409, "Only SCHEDULED calls can be canceled")
        c["status"] = "CANCELED"
        bump(c)
    else:
        err("ERR_INVALID_STATE", 409, "Transition not allowed")
    return respond(s_call(c), "object", 200)


# ===========================================================================
# NRTShipment
# ===========================================================================
def compute_nrt(cpd, medication_type):
    if cpd >= 21:
        weeks = 12
    elif 11 <= cpd <= 20:
        weeks = 10
    else:
        weeks = 8
    if medication_type == "PATCH":
        dose = 21 if cpd >= 11 else 14
    else:
        dose = None
    return weeks, dose


def nrt_interval_overlap(eid, new_start, new_end):
    for s in nrt_shipments.values():
        if s["enrollment_id"] != eid:
            continue
        if s["status"] == "CANCELED":
            continue
        ss = parse_iso(s["course_start_date"])
        se = parse_iso(s["course_end_date"])
        if new_start <= se and ss <= new_end:
            return True
    return False


@app.route("/enrollments/<eid>/nrt-shipments", methods=["POST"])
def create_shipment(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    data = get_body()
    medication_type = v_enum(data, "medication_type", MEDICATION_ENUM)
    course_start = v_datetime(data, "course_start_date")
    course_end = v_datetime(data, "course_end_date")
    if e["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    ns = parse_iso(course_start)
    ne = parse_iso(course_end)
    if nrt_interval_overlap(eid, ns, ne):
        err("ERR_NRT_COURSE_OVERLAP", 409, "NRT course interval overlaps an existing course")
    used = nrt_used_count(eid)
    if used >= e["nrt_courses_allotted"]:
        err("ERR_NRT_EXHAUSTED", 422, "NRT allotment exhausted")
    participant = participants[e["participant_id"]]
    weeks, dose = compute_nrt(participant["cigarettes_per_day"], medication_type)
    s = new_common()
    s.update({
        "enrollment_id": eid, "medication_type": medication_type,
        "course_start_date": course_start, "course_end_date": course_end,
        "weeks_supply": weeks, "dose_mg": dose, "status": "REQUESTED",
    })
    nrt_shipments[s["id"]] = s
    return respond(s_ship(s), "object", 201)


@app.route("/enrollments/<eid>/nrt-shipments", methods=["GET"])
def list_shipments(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(nrt_shipments, eid), s_ship)


@app.route("/nrt-shipments/<sid>/transition", methods=["POST"])
def transition_shipment(sid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    s = get_ship_or_404(sid)
    data = get_body()
    to_status = v_enum(data, "to_status", SHIP_STATUS_ENUM)
    e = enrollments[s["enrollment_id"]]
    current = s["status"]
    if to_status == "APPROVED":
        if current != "REQUESTED":
            err("ERR_INVALID_STATE", 409, "Only REQUESTED shipments can be approved")
        if e["status"] != "ACTIVE":
            err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
        has_qa = any(q["status"] in ("COMMITTED", "QUIT_ACHIEVED")
                     for q in enr_children(quit_attempts, e["id"]))
        if not has_qa:
            err("ERR_NO_COMMITTED_QUIT_ATTEMPT", 409, "No committed/achieved quit attempt")
        s["status"] = "APPROVED"
        bump(s)
    elif to_status == "SHIPPED":
        if current != "APPROVED":
            err("ERR_INVALID_STATE", 409, "Only APPROVED shipments can be shipped")
        s["status"] = "SHIPPED"
        bump(s)
    elif to_status == "DELIVERED":
        if current != "SHIPPED":
            err("ERR_INVALID_STATE", 409, "Only SHIPPED shipments can be delivered")
        s["status"] = "DELIVERED"
        bump(s)
    elif to_status == "CANCELED":
        if current not in ("REQUESTED", "APPROVED", "SHIPPED"):
            err("ERR_INVALID_STATE", 409, "Shipment cannot be canceled from its current state")
        s["status"] = "CANCELED"
        bump(s)
    elif to_status == "RETURNED":
        if current != "DELIVERED":
            err("ERR_INVALID_STATE", 409, "Only DELIVERED shipments can be returned")
        s["status"] = "RETURNED"
        bump(s)
    else:
        err("ERR_INVALID_STATE", 409, "Transition not allowed")
    return respond(s_ship(s), "object", 200)


# ===========================================================================
# IncentiveAward
# ===========================================================================
@app.route("/enrollments/<eid>/incentive-awards", methods=["POST"])
def create_award(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    participant = participants[e["participant_id"]]
    epid = participant.get("employer_program_id")
    if not epid or epid not in employer_programs:
        err("ERR_EMPLOYER_PROGRAM_NOT_FOUND", 404, "Participant is self-pay; no sponsor program")
    prog = employer_programs[epid]
    data = get_body()
    milestone_type = v_enum(data, "milestone_type", MILESTONE_ENUM)
    amount = v_int(data, "amount_cents", minimum=0)
    expected = v_int(data, "expected_employer_program_version")
    if e["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    if expected != prog["version"]:
        err("ERR_STALE_VERSION", 412, "Program version mismatch")
    if prog["status"] == "CLOSED":
        err("ERR_PROGRAM_CLOSED", 409, "Employer program is closed")
    if amount > prog["budget_remaining_cents"]:
        err("ERR_PROGRAM_BUDGET_EXCEEDED", 402, "Award exceeds remaining budget")
    a = new_common()
    a.update({
        "enrollment_id": eid, "milestone_type": milestone_type, "amount_cents": amount,
        "status": "EARNED", "source": "MANUAL",
    })
    incentive_awards[a["id"]] = a
    prog["budget_remaining_cents"] -= amount
    bump(prog)
    return respond(s_award(a), "object", 201)


@app.route("/enrollments/<eid>/incentive-awards", methods=["GET"])
def list_awards(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(incentive_awards, eid), s_award)


@app.route("/enrollments/<eid>/incentive-summary", methods=["GET"])
def incentive_summary(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    awards = enr_awards(eid)
    provisional = sum(a["amount_cents"] for a in awards if a["status"] in ("EARNED", "PAID"))
    if e["status"] == "COMPLETED":
        bonus = 0
        for a in awards:
            if a["status"] in ("EARNED", "PAID"):
                bonus += int(round_half_up(Decimal(a["amount_cents"]) * COMPLETION_BONUS_RATE, 0))
        final_payout = provisional + bonus
    else:
        bonus = 0
        final_payout = provisional
    return respond({
        "provisional_earned_cents": provisional,
        "completion_bonus_cents": bonus,
        "final_payout_cents": final_payout,
    }, "object", 200)


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/enrollments/<eid>/referrals", methods=["POST"])
def create_referral(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    data = get_body()
    referral_type = v_enum(data, "referral_type", REFERRAL_ENUM)
    target_name = v_str(data, "target_name")
    if e["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    r = new_common()
    r.update({
        "enrollment_id": eid, "referral_type": referral_type,
        "target_name": target_name, "status": "OPEN",
    })
    referrals[r["id"]] = r
    return respond(s_referral(r), "object", 201)


@app.route("/enrollments/<eid>/referrals", methods=["GET"])
def list_referrals(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(referrals, eid), s_referral)


# ===========================================================================
# FollowUpOutcome
# ===========================================================================
def relevant_attempt_for_window(eid, day):
    attempts = enr_children(quit_attempts, eid)
    if not attempts:
        return None
    if day == 7:
        pool = [q for q in attempts if q["status"] == "COMMITTED"] or attempts
    else:
        pool = [q for q in attempts if q["status"] == "QUIT_ACHIEVED"] or attempts
    return max(pool, key=lambda q: q["attempt_number"])


def highest_by_status(eid, status):
    pool = [q for q in enr_children(quit_attempts, eid) if q["status"] == status]
    if not pool:
        return None
    return max(pool, key=lambda q: q["attempt_number"])


@app.route("/enrollments/<eid>/follow-up-outcomes", methods=["POST"])
def create_followup(eid):
    uid, role = authenticate()
    authorize(role, {"CaseManager"})
    e = get_enrollment_or_404(eid)
    data = get_body()
    day = v_int(data, "day")
    if day not in (7, 30):
        err("ERR_VALIDATION", 400, "day must be 7 or 30")
    abstinent = v_bool(data, "abstinent")
    if e["status"] != "ACTIVE":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    # temporal window
    rel = relevant_attempt_for_window(eid, day)
    if rel is None or not rel.get("quit_date"):
        err("ERR_FOLLOWUP_WINDOW_NOT_OPEN", 409, "Follow-up window is not open")
    if now() < parse_iso(rel["quit_date"]) + timedelta(days=day):
        err("ERR_FOLLOWUP_WINDOW_NOT_OPEN", 409, "Follow-up window is not open")
    # duplicate
    for f in enr_children(follow_ups, eid):
        if f["day"] == day:
            err("ERR_DUPLICATE_FOLLOWUP", 422, "Outcome already exists for this milestone day")
    # processing
    if day == 7 and abstinent:
        qa = highest_by_status(eid, "COMMITTED")
        if qa:
            qa["status"] = "QUIT_ACHIEVED"
            bump(qa)
            create_system_award(e, "SEVEN_DAY_ABSTINENT")
    elif day == 7 and not abstinent:
        qa = highest_by_status(eid, "COMMITTED")
        if qa:
            qa["status"] = "RELAPSED"
            bump(qa)
            forfeit_awards(e, {"SEVEN_DAY_ABSTINENT", "THIRTY_DAY_ABSTINENT"})
    elif day == 30 and abstinent:
        qa = highest_by_status(eid, "QUIT_ACHIEVED")
        if qa is None:
            err("ERR_INVALID_STATE", 409, "No QUIT_ACHIEVED quit attempt for 30-day milestone")
        create_system_award(e, "THIRTY_DAY_ABSTINENT")
        e["status"] = "COMPLETED"
        bump(e)
        for a in sorted(enr_awards(eid), key=lambda x: x["_seq"]):
            if a["status"] == "EARNED":
                a["status"] = "PAID"
                bump(a)
        for r in enr_children(referrals, eid):
            if r["status"] == "OPEN":
                r["status"] = "CLOSED"
                bump(r)
    elif day == 30 and not abstinent:
        qa = highest_by_status(eid, "QUIT_ACHIEVED")
        if qa:
            qa["status"] = "RELAPSED"
            bump(qa)
            forfeit_awards(e, {"SEVEN_DAY_ABSTINENT", "THIRTY_DAY_ABSTINENT"})
    f = new_event()
    f.update({
        "enrollment_id": eid, "day": day, "abstinent": abstinent,
        "recorded_at": fmt_ts(now()),
    })
    follow_ups[f["id"]] = f
    return respond(s_followup(f), "object", 201)


@app.route("/enrollments/<eid>/follow-up-outcomes", methods=["GET"])
def list_followups(eid):
    uid, role = authenticate()
    authorize(role, {"ProgramAdmin", "CaseManager", "Participant"})
    e = get_enrollment_or_404(eid)
    require_owns_enrollment(role, uid, e)
    return paginate_and_respond(enr_children(follow_ups, eid), s_followup)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
