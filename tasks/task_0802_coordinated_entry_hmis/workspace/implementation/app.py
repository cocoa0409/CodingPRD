"""Coordinated Entry & Homeless Services (HMIS) API — Python + Flask.

In-memory only. State is wiped on every process start (no persistence). The test
harness restarts this server before every test via start.sh.
"""
import os
import random
import string
import threading
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Roles
# ─────────────────────────────────────────────────────────────────────────────
INTAKE = "IntakeSpecialist"
SHELTER_MGR = "ShelterManager"
NAVIGATOR = "HousingNavigator"
ADMIN = "HMISAdmin"
ALL_ROLES = {INTAKE, SHELTER_MGR, NAVIGATOR, ADMIN}

# ─────────────────────────────────────────────────────────────────────────────
# Logical clock (startup default per PRD §2.4)
# ─────────────────────────────────────────────────────────────────────────────
CLOCK = datetime(2026, 3, 1, tzinfo=timezone.utc)
SEQ = 0
_LOCK = threading.RLock()

# ─────────────────────────────────────────────────────────────────────────────
# In-memory stores (id -> record dict)
# ─────────────────────────────────────────────────────────────────────────────
clients = {}
assessments = {}
consents = {}
screenings = {}
shelters = {}
beds = {}
reservations = {}
waitlists = {}
prio_entries = {}
navigators = {}
referrals = {}
exit_records = {}


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ─────────────────────────────────────────────────────────────────────────────
# Time / date helpers
# ─────────────────────────────────────────────────────────────────────────────
def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_instant(s):
    if not isinstance(s, str):
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a string")
    try:
        s2 = s.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "invalid ISO8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s, field="date"):
    if not isinstance(s, str):
        err("ERR_INVALID_REQUEST", 400, f"{field} must be a YYYY-MM-DD string")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        err("ERR_INVALID_REQUEST", 400, f"{field} must be a valid YYYY-MM-DD date")


def clock_date():
    return CLOCK.date()


# ─────────────────────────────────────────────────────────────────────────────
# Record helpers
# ─────────────────────────────────────────────────────────────────────────────
def base_record(mutable=True):
    global SEQ
    SEQ += 1
    r = {"id": str(uuid4()), "created_at": CLOCK, "_seq": SEQ}
    if mutable:
        r["updated_at"] = CLOCK
        r["version"] = 1
    return r


def touch(rec):
    rec["updated_at"] = CLOCK
    rec["version"] = rec.get("version", 1) + 1


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


# ─────────────────────────────────────────────────────────────────────────────
# Response envelope
# ─────────────────────────────────────────────────────────────────────────────
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": iso(CLOCK)}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pag=None):
    return jsonify({"meta": _meta(pag), "response_type": response_type, "data": data}), status


def ok_list(items, limit, offset, total):
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": offset + len(items) < total}
    return jsonify({"meta": _meta(pag), "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


# ─────────────────────────────────────────────────────────────────────────────
# Auth / RBAC
# ─────────────────────────────────────────────────────────────────────────────
def require(*roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        err("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID or X-User-Role header")
    if role not in roles:
        err("ERR_FORBIDDEN", 403, f"Role {role} not permitted for this operation")
    return uid, role


# ─────────────────────────────────────────────────────────────────────────────
# Body / field validation helpers
# ─────────────────────────────────────────────────────────────────────────────
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return b


def need(b, name):
    if name not in b or b[name] is None:
        err("ERR_INVALID_REQUEST", 400, f"{name} is required")
    return b[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 400, f"{name} must be a non-empty string")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, f"{name} must be an integer")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, f"{name} must be a boolean")
    return v


def as_enum(v, name, allowed):
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, f"{name} must be one of {sorted(allowed)}")
    return v


def get_or_404(store, rid):
    if rid is None or rid not in store:
        err("ERR_NOT_FOUND", 404, "referenced resource does not exist")
    return store[rid]


def pagination():
    a = request.args
    try:
        limit = int(a.get("limit", 10))
        offset = int(a.get("offset", 0))
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def do_list(values, filters):
    """filters: dict of query-param -> record field name."""
    items = list(values)
    for param, field in filters.items():
        v = request.args.get(param)
        if v is not None:
            items = [x for x in items if str(x.get(field)) == v]
    items.sort(key=sort_key)
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ─────────────────────────────────────────────────────────────────────────────
# Domain calculations
# ─────────────────────────────────────────────────────────────────────────────
def tier_of(score):
    if score is None:
        return None
    if score >= 8:
        return "HIGH"
    if score >= 4:
        return "MODERATE"
    return "LOW"


def track_of(tier):
    return {"HIGH": "PSH", "MODERATE": "RRH", "LOW": "PREVENTION"}.get(tier)


def rank_score_of(client):
    tier = client["acuity_tier"]
    tw = {"HIGH": 1000, "MODERATE": 500, "LOW": 100}.get(tier, 0)
    cb = 300 if client["chronic_homeless"] else 0
    m = client["months_homeless"]
    if m >= 12:
        t = 200
    elif m >= 6:
        t = 100
    else:
        t = m * 10
    hf = min(client["household_size"], 5) * 20
    return tw + cb + t + hf


def recompute_client_score(client):
    completed = [a for a in assessments.values()
                 if a["client_id"] == client["id"] and a["status"] == "COMPLETED"]
    if completed:
        latest = max(completed, key=sort_key)
        client["vulnerability_score"] = latest["verified_score"]
    else:
        client["vulnerability_score"] = None
    client["acuity_tier"] = tier_of(client["vulnerability_score"])


# ─────────────────────────────────────────────────────────────────────────────
# Interval helpers (dates stored as YYYY-MM-DD strings)
# ─────────────────────────────────────────────────────────────────────────────
def half_open_overlap(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def closed_overlap(a1, a2, b1, b2):
    return a1 <= b2 and b1 <= a2


def live_res_on_bed(bed_id):
    return [r for r in reservations.values()
            if r["bed_id"] == bed_id and r["status"] in ("RESERVED", "CHECKED_IN")]


def assign_bed(shelter_id, entry_s, exit_s):
    e, x = parse_date(entry_s), parse_date(exit_s)
    cands = []
    for b in beds.values():
        if b["shelter_id"] != shelter_id or b["status"] != "ACTIVE":
            continue
        conflict = False
        for r in live_res_on_bed(b["id"]):
            if half_open_overlap(e, x, parse_date(r["entry_date"]),
                                 parse_date(r["expected_exit_date"])):
                conflict = True
                break
        if not conflict:
            cands.append(b)
    if not cands:
        return None
    cands.sort(key=lambda b: (b["created_at"], b["label"]))
    return cands[0]


def bed_covered_today(bed_id):
    d = clock_date()
    for r in live_res_on_bed(bed_id):
        if parse_date(r["entry_date"]) <= d < parse_date(r["expected_exit_date"]):
            return True
    return False


def shelter_total_beds(shelter_id):
    return sum(1 for b in beds.values() if b["shelter_id"] == shelter_id)


def shelter_available_beds(shelter_id):
    n = 0
    for b in beds.values():
        if b["shelter_id"] == shelter_id and b["status"] == "ACTIVE" and not bed_covered_today(b["id"]):
            n += 1
    return n


def navigator_caseload(nav_id):
    return sum(1 for r in referrals.values()
               if r["navigator_id"] == nav_id and r["status"] == "ACCEPTED")


# ─────────────────────────────────────────────────────────────────────────────
# Shelter version + waitlist promotion (pinned capacity order, PRD §2.7)
# ─────────────────────────────────────────────────────────────────────────────
def bump_shelter(shelter):
    touch(shelter)


def mint_reservation(client_id, shelter, entry_s, exit_s):
    bed = assign_bed(shelter["id"], entry_s, exit_s)
    r = base_record()
    r.update({
        "client_id": client_id,
        "shelter_id": shelter["id"],
        "bed_id": bed["id"] if bed else None,
        "entry_date": entry_s,
        "expected_exit_date": exit_s,
        "exit_date": None,
        "status": "RESERVED",
    })
    reservations[r["id"]] = r
    bump_shelter(shelter)  # a minted reservation is a capacity change
    return r


def promote_once(shelter):
    """After a freeing event: promote at most one waiting entry against recomputed
    availability."""
    cands = []
    for w in waitlists.values():
        if w["shelter_id"] != shelter["id"] or w["status"] != "WAITING":
            continue
        if assign_bed(shelter["id"], w["entry_date"], w["expected_exit_date"]) is not None:
            cands.append(w)
    if not cands:
        return
    cands.sort(key=lambda w: (-w["priority_score"], w["created_at"], w["_seq"]))
    w = cands[0]
    res = mint_reservation(w["client_id"], shelter, w["entry_date"], w["expected_exit_date"])
    w["status"] = "PROMOTED"
    w["promoted_reservation_id"] = res["id"]
    touch(w)


# ─────────────────────────────────────────────────────────────────────────────
# Lazy transitions (evaluated on read/write, PRD §2.4)
# ─────────────────────────────────────────────────────────────────────────────
def refresh_assessment(a):
    if a["status"] == "DRAFT" and CLOCK >= a["created_at"] + timedelta(days=90):
        a["status"] = "EXPIRED"
        touch(a)


def refresh_consent(c):
    if c["status"] == "ACTIVE" and clock_date() >= parse_date(c["expiry_date"]):
        c["status"] = "EXPIRED"
        touch(c)


def requeue_pool_entry(pe):
    if pe and pe["status"] == "MATCHED":
        pe["status"] = "ACTIVE"
        pe["matched_referral_id"] = None
        client = clients.get(pe["client_id"])
        if client:
            pe["rank_score"] = rank_score_of(client)
        touch(pe)


def refresh_referral(r):
    if r["status"] == "PENDING" and CLOCK >= r["created_at"] + timedelta(days=14):
        r["status"] = "EXPIRED"
        touch(r)
        requeue_pool_entry(prio_entries.get(r["prioritization_entry_id"]))


def apply_lazy():
    for a in list(assessments.values()):
        refresh_assessment(a)
    for c in list(consents.values()):
        refresh_consent(c)
    for r in list(referrals.values()):
        refresh_referral(r)


def has_active_consent(client_id):
    active = False
    for c in consents.values():
        if c["client_id"] == client_id:
            refresh_consent(c)
            if c["status"] == "ACTIVE":
                active = True
    return active


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────
def _common(rec, mutable=True):
    d = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if mutable:
        d["updated_at"] = iso(rec["updated_at"])
        d["version"] = rec["version"]
    return d


def ser_client(c):
    d = _common(c)
    d.update({
        "full_name": c["full_name"], "dob": c["dob"], "ssn_last4": c["ssn_last4"],
        "household_size": c["household_size"], "months_homeless": c["months_homeless"],
        "chronic_homeless": c["chronic_homeless"], "status": c["status"],
        "master_client_id": c["master_client_id"],
        "vulnerability_score": c["vulnerability_score"], "acuity_tier": c["acuity_tier"],
    })
    return d


def ser_assessment(a):
    d = _common(a)
    d.update({
        "client_id": a["client_id"], "tool": a["tool"],
        "self_report_points": a["self_report_points"],
        "verification_delta": a["verification_delta"],
        "provisional_score": a["self_report_points"],
        "verified_score": a["verified_score"],
        "recommended_track": a["recommended_track"], "status": a["status"],
    })
    return d


def ser_consent(c):
    d = _common(c)
    d.update({
        "client_id": c["client_id"], "scope": c["scope"],
        "effective_date": c["effective_date"], "expiry_date": c["expiry_date"],
        "status": c["status"],
    })
    return d


def ser_screening(s):
    d = _common(s)
    d.update({
        "client_id": s["client_id"], "has_safe_alternative": s["has_safe_alternative"],
        "is_fleeing_dv": s["is_fleeing_dv"], "outcome": s["outcome"], "status": s["status"],
    })
    return d


def ser_shelter(s):
    d = _common(s)
    d.update({
        "name": s["name"], "project_type": s["project_type"],
        "total_beds": shelter_total_beds(s["id"]),
        "available_beds": shelter_available_beds(s["id"]),
    })
    return d


def ser_bed(b):
    d = _common(b)
    d.update({
        "shelter_id": b["shelter_id"], "label": b["label"],
        "status": b["status"], "current_reservation_id": b["current_reservation_id"],
    })
    return d


def ser_reservation(r):
    d = _common(r)
    d.update({
        "client_id": r["client_id"], "shelter_id": r["shelter_id"], "bed_id": r["bed_id"],
        "entry_date": r["entry_date"], "expected_exit_date": r["expected_exit_date"],
        "exit_date": r["exit_date"], "status": r["status"],
    })
    return d


def ser_waitlist(w):
    d = _common(w)
    d.update({
        "shelter_id": w["shelter_id"], "client_id": w["client_id"],
        "entry_date": w["entry_date"], "expected_exit_date": w["expected_exit_date"],
        "priority_score": w["priority_score"],
        "promoted_reservation_id": w["promoted_reservation_id"], "status": w["status"],
    })
    return d


def ser_prio(p):
    d = _common(p)
    d.update({
        "client_id": p["client_id"], "rank_score": p["rank_score"],
        "deferred_until": p["deferred_until"],
        "matched_referral_id": p["matched_referral_id"], "status": p["status"],
    })
    return d


def ser_navigator(n):
    d = _common(n)
    d.update({
        "name": n["name"], "max_caseload": n["max_caseload"],
        "current_caseload": navigator_caseload(n["id"]),
    })
    return d


def ser_referral(r):
    d = _common(r)
    d.update({
        "client_id": r["client_id"], "prioritization_entry_id": r["prioritization_entry_id"],
        "navigator_id": r["navigator_id"], "psh_project_name": r["psh_project_name"],
        "status": r["status"],
    })
    return d


def ser_exit(x):
    d = _common(x, mutable=False)
    d.update({
        "client_id": x["client_id"], "reservation_id": x["reservation_id"],
        "referral_id": x["referral_id"], "destination": x["destination"],
        "outcome": x["outcome"], "bed_nights": x["bed_nights"],
    })
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Request bracketing: serialize all requests + run lazy transitions
# ─────────────────────────────────────────────────────────────────────────────
@app.before_request
def _before():
    _LOCK.acquire()
    g._locked = True
    apply_lazy()


@app.teardown_request
def _teardown(exc):
    if getattr(g, "_locked", False):
        g._locked = False
        try:
            _LOCK.release()
        except RuntimeError:
            pass


@app.get("/")
def health():
    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# Clock
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/_clock/set_current_utc")
def set_clock():
    global CLOCK
    require(ADMIN)
    b = body()
    to = need(b, "to_iso8601")
    CLOCK = parse_instant(to)
    apply_lazy()
    return ok({"current_utc": iso(CLOCK)})


# ─────────────────────────────────────────────────────────────────────────────
# Clients
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/clients")
def create_client():
    require(INTAKE, ADMIN)
    b = body()
    full_name = as_str(need(b, "full_name"), "full_name")
    dob = as_str(need(b, "dob"), "dob")
    ssn = b.get("ssn_last4")
    if ssn is not None:
        if not isinstance(ssn, str) or len(ssn) != 4 or not ssn.isdigit():
            err("ERR_INVALID_REQUEST", 400, "ssn_last4 must be 4 digits or null")
    hh = b.get("household_size", 1)
    hh = as_int(hh, "household_size")
    if hh < 1:
        err("ERR_INVALID_REQUEST", 400, "household_size must be >= 1")
    mh = b.get("months_homeless", 0)
    mh = as_int(mh, "months_homeless")
    if mh < 0:
        err("ERR_INVALID_REQUEST", 400, "months_homeless must be >= 0")
    ch = b.get("chronic_homeless", False)
    ch = as_bool(ch, "chronic_homeless")
    c = base_record()
    c.update({
        "full_name": full_name, "dob": dob, "ssn_last4": ssn,
        "household_size": hh, "months_homeless": mh, "chronic_homeless": ch,
        "status": "INTAKE", "master_client_id": None,
        "vulnerability_score": None, "acuity_tier": None,
    })
    clients[c["id"]] = c
    return ok(ser_client(c), 201)


@app.get("/clients/<cid>")
def get_client(cid):
    require(*ALL_ROLES)
    return ok(ser_client(get_or_404(clients, cid)))


@app.get("/clients")
def list_clients():
    require(*ALL_ROLES)
    page, limit, offset, total = do_list(
        clients.values(), {"master_client_id": "master_client_id", "status": "status"})
    return ok_list([ser_client(x) for x in page], limit, offset, total)


@app.post("/clients/<cid>/merge")
def merge_client(cid):
    require(ADMIN)
    master = get_or_404(clients, cid)
    b = body()
    dup_id = b.get("duplicate_client_id")
    # existence: body FK
    if dup_id is not None and dup_id not in clients:
        err("ERR_NOT_FOUND", 404, "duplicate_client_id does not exist")
    # well-formed
    dup_id = as_str(need(b, "duplicate_client_id"), "duplicate_client_id")
    dup = clients[dup_id]
    # merge validity (self / already-merged)
    if dup["id"] == master["id"] or dup["status"] == "MERGED":
        err("ERR_MERGE_INVALID", 409, "duplicate equals master or already MERGED")
    # state: duplicate must be INTAKE or ACTIVE
    if dup["status"] not in ("INTAKE", "ACTIVE"):
        err("ERR_INVALID_STATE", 409, "duplicate not in a mergeable state")
    # consent prerequisite
    if not has_active_consent(dup["id"]):
        err("ERR_CONSENT_REQUIRED", 409, "duplicate lacks an ACTIVE ROIConsent")

    was_active = dup["status"] == "ACTIVE"
    dup["status"] = "MERGED"
    dup["master_client_id"] = master["id"]
    touch(dup)
    if was_active:
        # cascade: cancel live reservations, free beds, promote waitlist
        for r in list(reservations.values()):
            if r["client_id"] == dup["id"] and r["status"] in ("RESERVED", "CHECKED_IN"):
                if r["status"] == "CHECKED_IN":
                    bed = beds.get(r["bed_id"])
                    if bed and bed["current_reservation_id"] == r["id"]:
                        bed["current_reservation_id"] = None
                        touch(bed)
                r["status"] = "CANCELLED"
                touch(r)
                sh = shelters.get(r["shelter_id"])
                if sh:
                    bump_shelter(sh)
                    promote_once(sh)
        # cascade: remove ACTIVE prioritization entry
        for pe in prio_entries.values():
            if pe["client_id"] == dup["id"] and pe["status"] == "ACTIVE":
                pe["status"] = "REMOVED"
                touch(pe)
    return ok(ser_client(master))


@app.post("/clients/<cid>/deactivate")
def deactivate_client(cid):
    require(ADMIN)
    c = get_or_404(clients, cid)
    if c["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "client not ACTIVE")
    for r in reservations.values():
        if r["client_id"] == c["id"] and r["status"] in ("RESERVED", "CHECKED_IN"):
            err("ERR_INVALID_STATE", 409, "client holds an active reservation")
    c["status"] = "INACTIVE"
    touch(c)
    return ok(ser_client(c))


# ─────────────────────────────────────────────────────────────────────────────
# Assessments
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/assessments")
def create_assessment():
    require(INTAKE)
    b = body()
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    cid = as_str(need(b, "client_id"), "client_id")
    tool = b.get("tool", "VI_SPDAT")
    as_enum(tool, "tool", {"VI_SPDAT"})
    srp = as_int(need(b, "self_report_points"), "self_report_points")
    if srp < 0 or srp > 17:
        err("ERR_INVALID_REQUEST", 400, "self_report_points must be 0..17")
    vd = b.get("verification_delta", 0)
    vd = as_int(vd, "verification_delta")
    if vd < -5 or vd > 5:
        err("ERR_INVALID_REQUEST", 400, "verification_delta must be -5..5")
    a = base_record()
    a.update({
        "client_id": cid, "tool": tool, "self_report_points": srp,
        "verification_delta": vd, "verified_score": None,
        "recommended_track": None, "status": "DRAFT",
    })
    assessments[a["id"]] = a
    return ok(ser_assessment(a), 201)


@app.get("/assessments/<aid>")
def get_assessment(aid):
    require(INTAKE, NAVIGATOR, ADMIN)
    a = get_or_404(assessments, aid)
    refresh_assessment(a)
    return ok(ser_assessment(a))


@app.get("/assessments")
def list_assessments():
    require(INTAKE, NAVIGATOR, ADMIN)
    page, limit, offset, total = do_list(
        assessments.values(), {"client_id": "client_id", "status": "status"})
    return ok_list([ser_assessment(x) for x in page], limit, offset, total)


@app.post("/assessments/<aid>/complete")
def complete_assessment(aid):
    require(INTAKE)
    a = get_or_404(assessments, aid)
    refresh_assessment(a)
    if a["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "assessment not DRAFT")
    vs = a["self_report_points"] + a["verification_delta"]
    vs = max(0, min(17, vs))
    a["verified_score"] = vs
    a["recommended_track"] = track_of(tier_of(vs))
    a["status"] = "COMPLETED"
    touch(a)
    client = clients.get(a["client_id"])
    if client:
        recompute_client_score(client)
        if client["status"] == "INTAKE":
            client["status"] = "ACTIVE"
        touch(client)
    return ok(ser_assessment(a))


# ─────────────────────────────────────────────────────────────────────────────
# ROIConsent
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/consents")
def create_consent():
    require(INTAKE)
    b = body()
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    cid = as_str(need(b, "client_id"), "client_id")
    scope = as_enum(need(b, "scope"), "scope", {"SHARE_ALL", "SHARE_LIMITED"})
    eff = need(b, "effective_date")
    parse_date(eff, "effective_date")
    exp = need(b, "expiry_date")
    parse_date(exp, "expiry_date")
    c = base_record()
    c.update({
        "client_id": cid, "scope": scope, "effective_date": eff,
        "expiry_date": exp, "status": "PENDING",
    })
    consents[c["id"]] = c
    return ok(ser_consent(c), 201)


@app.get("/consents/<cid>")
def get_consent(cid):
    require(INTAKE, ADMIN)
    c = get_or_404(consents, cid)
    refresh_consent(c)
    return ok(ser_consent(c))


@app.get("/consents")
def list_consents():
    require(INTAKE, ADMIN)
    page, limit, offset, total = do_list(
        consents.values(), {"client_id": "client_id", "status": "status"})
    return ok_list([ser_consent(x) for x in page], limit, offset, total)


@app.post("/consents/<cid>/activate")
def activate_consent(cid):
    require(INTAKE)
    c = get_or_404(consents, cid)
    refresh_consent(c)
    if c["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "consent not PENDING")
    if clock_date() < parse_date(c["effective_date"]):
        err("ERR_INVALID_STATE", 409, "before effective_date")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(ser_consent(c))


@app.post("/consents/<cid>/revoke")
def revoke_consent(cid):
    require(INTAKE)
    c = get_or_404(consents, cid)
    refresh_consent(c)
    if c["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "consent not ACTIVE")
    c["status"] = "REVOKED"
    touch(c)
    for pe in prio_entries.values():
        if pe["client_id"] == c["client_id"] and pe["status"] == "ACTIVE":
            pe["status"] = "REMOVED"
            touch(pe)
    return ok(ser_consent(c))


# ─────────────────────────────────────────────────────────────────────────────
# DiversionScreening
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/screenings")
def create_screening():
    require(INTAKE)
    b = body()
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    cid = as_str(need(b, "client_id"), "client_id")
    hsa = as_bool(need(b, "has_safe_alternative"), "has_safe_alternative")
    fdv = b.get("is_fleeing_dv", False)
    fdv = as_bool(fdv, "is_fleeing_dv")
    s = base_record()
    s.update({
        "client_id": cid, "has_safe_alternative": hsa, "is_fleeing_dv": fdv,
        "outcome": None, "status": "OPEN",
    })
    screenings[s["id"]] = s
    return ok(ser_screening(s), 201)


@app.get("/screenings/<sid>")
def get_screening(sid):
    require(INTAKE, ADMIN)
    return ok(ser_screening(get_or_404(screenings, sid)))


@app.get("/screenings")
def list_screenings():
    require(INTAKE, ADMIN)
    page, limit, offset, total = do_list(screenings.values(), {"client_id": "client_id"})
    return ok_list([ser_screening(x) for x in page], limit, offset, total)


@app.post("/screenings/<sid>/resolve")
def resolve_screening(sid):
    require(INTAKE)
    s = get_or_404(screenings, sid)
    if s["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "screening not OPEN")
    if s["is_fleeing_dv"]:
        s["outcome"] = "PROCEED_TO_SHELTER"
    elif s["has_safe_alternative"]:
        s["outcome"] = "DIVERTED"
    else:
        s["outcome"] = "PROCEED_TO_PRIORITIZATION"
    s["status"] = "RESOLVED"
    touch(s)
    return ok(ser_screening(s))


# ─────────────────────────────────────────────────────────────────────────────
# Shelter / Bed
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/shelters")
def create_shelter():
    require(SHELTER_MGR, ADMIN)
    b = body()
    name = as_str(need(b, "name"), "name")
    pt = as_enum(need(b, "project_type"), "project_type", {"ES", "TH"})
    s = base_record()
    s.update({"name": name, "project_type": pt})
    shelters[s["id"]] = s
    return ok(ser_shelter(s), 201)


@app.get("/shelters/<sid>")
def get_shelter(sid):
    require(*ALL_ROLES)
    return ok(ser_shelter(get_or_404(shelters, sid)))


@app.get("/shelters")
def list_shelters():
    require(*ALL_ROLES)
    page, limit, offset, total = do_list(shelters.values(), {})
    return ok_list([ser_shelter(x) for x in page], limit, offset, total)


@app.post("/beds")
def create_bed():
    require(SHELTER_MGR)
    b = body()
    sid = b.get("shelter_id")
    if sid is not None and sid not in shelters:
        err("ERR_NOT_FOUND", 404, "shelter_id does not exist")
    sid = as_str(need(b, "shelter_id"), "shelter_id")
    label = as_str(need(b, "label"), "label")
    shelter = shelters[sid]
    for bed in beds.values():
        if bed["shelter_id"] == sid and bed["label"] == label:
            err("ERR_DUPLICATE_BED_LABEL", 409, "bed label already used in this shelter")
    rec = base_record()
    rec.update({"shelter_id": sid, "label": label, "status": "ACTIVE",
                "current_reservation_id": None})
    beds[rec["id"]] = rec
    bump_shelter(shelter)
    return ok(ser_bed(rec), 201)


@app.get("/beds/<bid>")
def get_bed(bid):
    require(SHELTER_MGR, ADMIN)
    return ok(ser_bed(get_or_404(beds, bid)))


@app.get("/beds")
def list_beds():
    require(SHELTER_MGR, ADMIN)
    page, limit, offset, total = do_list(beds.values(), {
        "shelter_id": "shelter_id", "current_reservation_id": "current_reservation_id",
        "status": "status"})
    return ok_list([ser_bed(x) for x in page], limit, offset, total)


@app.post("/beds/<bid>/offline")
def offline_bed(bid):
    require(SHELTER_MGR)
    bed = get_or_404(beds, bid)
    if bed["status"] != "ACTIVE" or bed["current_reservation_id"] is not None:
        err("ERR_INVALID_STATE", 409, "bed not ACTIVE/unoccupied")
    bed["status"] = "OFFLINE"
    touch(bed)
    sh = shelters.get(bed["shelter_id"])
    if sh:
        bump_shelter(sh)
    return ok(ser_bed(bed))


@app.post("/beds/<bid>/online")
def online_bed(bid):
    require(SHELTER_MGR)
    bed = get_or_404(beds, bid)
    if bed["status"] != "OFFLINE":
        err("ERR_INVALID_STATE", 409, "bed not OFFLINE")
    bed["status"] = "ACTIVE"
    touch(bed)
    sh = shelters.get(bed["shelter_id"])
    if sh:
        bump_shelter(sh)
        promote_once(sh)
    return ok(ser_bed(bed))


# ─────────────────────────────────────────────────────────────────────────────
# BedReservation
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/bed-reservations")
def create_reservation():
    require(SHELTER_MGR)
    b = body()
    # existence: body FKs left-to-right (client then shelter)
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    sid = b.get("shelter_id")
    if sid is not None and sid not in shelters:
        err("ERR_NOT_FOUND", 404, "shelter_id does not exist")
    # well-formedness
    cid = as_str(need(b, "client_id"), "client_id")
    sid = as_str(need(b, "shelter_id"), "shelter_id")
    entry = need(b, "entry_date")
    ed = parse_date(entry, "entry_date")
    xit = need(b, "expected_exit_date")
    xd = parse_date(xit, "expected_exit_date")
    esv = as_int(need(b, "expected_shelter_version"), "expected_shelter_version")
    if ed >= xd:
        err("ERR_INVALID_REQUEST", 400, "entry_date must be before expected_exit_date")
    shelter = shelters[sid]
    # OCC (rule 6)
    if esv != shelter["version"]:
        err("ERR_STALE_VERSION", 412, "expected_shelter_version does not match")
    # client double-booking (rule 10, inclusive turnover)
    for r in reservations.values():
        if r["client_id"] == cid and r["status"] in ("RESERVED", "CHECKED_IN"):
            if closed_overlap(ed, xd, parse_date(r["entry_date"]),
                              parse_date(r["expected_exit_date"])):
                err("ERR_CLIENT_DOUBLE_BOOKED", 409, "client already booked on an overlapping night")
    # capacity / bed-assignment (rule 14)
    bed = assign_bed(sid, entry, xit)
    if bed is None:
        err("ERR_SHELTER_AT_CAPACITY", 409, "no assignable bed for the requested window")
    r = base_record()
    r.update({
        "client_id": cid, "shelter_id": sid, "bed_id": bed["id"],
        "entry_date": entry, "expected_exit_date": xit, "exit_date": None,
        "status": "RESERVED",
    })
    reservations[r["id"]] = r
    bump_shelter(shelter)
    return ok(ser_reservation(r), 201)


@app.get("/bed-reservations/<rid>")
def get_reservation(rid):
    require(SHELTER_MGR, ADMIN)
    return ok(ser_reservation(get_or_404(reservations, rid)))


@app.get("/bed-reservations")
def list_reservations():
    require(SHELTER_MGR, ADMIN)
    page, limit, offset, total = do_list(reservations.values(), {
        "client_id": "client_id", "bed_id": "bed_id", "shelter_id": "shelter_id",
        "status": "status"})
    return ok_list([ser_reservation(x) for x in page], limit, offset, total)


@app.post("/bed-reservations/<rid>/check-in")
def check_in(rid):
    require(SHELTER_MGR)
    r = get_or_404(reservations, rid)
    if r["status"] != "RESERVED":
        err("ERR_INVALID_STATE", 409, "reservation not RESERVED")
    if not has_active_consent(r["client_id"]):
        err("ERR_CONSENT_REQUIRED", 409, "client lacks an ACTIVE ROIConsent")
    r["status"] = "CHECKED_IN"
    touch(r)
    bed = beds.get(r["bed_id"])
    if bed:
        bed["current_reservation_id"] = r["id"]
        touch(bed)
    sh = shelters.get(r["shelter_id"])
    if sh:
        bump_shelter(sh)
    return ok(ser_reservation(r))


@app.post("/bed-reservations/<rid>/check-out")
def check_out(rid):
    require(SHELTER_MGR)
    r = get_or_404(reservations, rid)
    if r["status"] != "CHECKED_IN":
        err("ERR_INVALID_STATE", 409, "reservation not CHECKED_IN")
    r["status"] = "CHECKED_OUT"
    r["exit_date"] = clock_date().isoformat()
    touch(r)
    bed = beds.get(r["bed_id"])
    if bed and bed["current_reservation_id"] == r["id"]:
        bed["current_reservation_id"] = None
        touch(bed)
    sh = shelters.get(r["shelter_id"])
    if sh:
        bump_shelter(sh)
        promote_once(sh)
    return ok(ser_reservation(r))


@app.post("/bed-reservations/<rid>/cancel")
def cancel_reservation(rid):
    require(SHELTER_MGR)
    r = get_or_404(reservations, rid)
    if r["status"] != "RESERVED":
        err("ERR_INVALID_STATE", 409, "reservation not RESERVED")
    r["status"] = "CANCELLED"
    touch(r)
    sh = shelters.get(r["shelter_id"])
    if sh:
        bump_shelter(sh)
        promote_once(sh)
    return ok(ser_reservation(r))


@app.post("/bed-reservations/<rid>/no-show")
def no_show(rid):
    require(SHELTER_MGR)
    r = get_or_404(reservations, rid)
    if r["status"] != "RESERVED":
        err("ERR_INVALID_STATE", 409, "reservation not RESERVED")
    if clock_date() <= parse_date(r["entry_date"]):
        err("ERR_INVALID_STATE", 409, "no-show only after entry_date has passed")
    r["status"] = "NO_SHOW"
    touch(r)
    sh = shelters.get(r["shelter_id"])
    if sh:
        bump_shelter(sh)
        promote_once(sh)
    return ok(ser_reservation(r))


# ─────────────────────────────────────────────────────────────────────────────
# WaitlistEntry
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/waitlist-entries")
def create_waitlist():
    require(SHELTER_MGR)
    b = body()
    sid = b.get("shelter_id")
    if sid is not None and sid not in shelters:
        err("ERR_NOT_FOUND", 404, "shelter_id does not exist")
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    sid = as_str(need(b, "shelter_id"), "shelter_id")
    cid = as_str(need(b, "client_id"), "client_id")
    entry = need(b, "entry_date")
    ed = parse_date(entry, "entry_date")
    xit = need(b, "expected_exit_date")
    xd = parse_date(xit, "expected_exit_date")
    if ed >= xd:
        err("ERR_INVALID_REQUEST", 400, "entry_date must be before expected_exit_date")
    for w in waitlists.values():
        if w["shelter_id"] == sid and w["client_id"] == cid and w["status"] == "WAITING":
            err("ERR_DUPLICATE_WAITLIST", 409, "client already WAITING at this shelter")
    client = clients[cid]
    w = base_record()
    w.update({
        "shelter_id": sid, "client_id": cid, "entry_date": entry,
        "expected_exit_date": xit, "priority_score": rank_score_of(client),
        "promoted_reservation_id": None, "status": "WAITING",
    })
    waitlists[w["id"]] = w
    return ok(ser_waitlist(w), 201)


@app.get("/waitlist-entries/<wid>")
def get_waitlist(wid):
    require(SHELTER_MGR, ADMIN)
    return ok(ser_waitlist(get_or_404(waitlists, wid)))


@app.get("/waitlist-entries")
def list_waitlist():
    require(SHELTER_MGR, ADMIN)
    page, limit, offset, total = do_list(waitlists.values(), {
        "shelter_id": "shelter_id", "client_id": "client_id",
        "promoted_reservation_id": "promoted_reservation_id", "status": "status"})
    return ok_list([ser_waitlist(x) for x in page], limit, offset, total)


@app.post("/waitlist-entries/<wid>/cancel")
def cancel_waitlist(wid):
    require(SHELTER_MGR)
    w = get_or_404(waitlists, wid)
    if w["status"] != "WAITING":
        err("ERR_INVALID_STATE", 409, "waitlist entry not WAITING")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(ser_waitlist(w))


# ─────────────────────────────────────────────────────────────────────────────
# PrioritizationEntry
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/prioritization-entries")
def create_prio():
    require(NAVIGATOR, ADMIN)
    b = body()
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    cid = as_str(need(b, "client_id"), "client_id")
    if not has_active_consent(cid):
        err("ERR_POOL_INELIGIBLE", 409, "client lacks ACTIVE consent")
    for pe in prio_entries.values():
        if pe["client_id"] == cid and pe["status"] in ("ACTIVE", "MATCHED", "DEFERRED"):
            err("ERR_POOL_INELIGIBLE", 409, "client already has a non-terminal pool entry")
    client = clients[cid]
    p = base_record()
    p.update({
        "client_id": cid, "rank_score": rank_score_of(client),
        "deferred_until": None, "matched_referral_id": None, "status": "ACTIVE",
    })
    prio_entries[p["id"]] = p
    return ok(ser_prio(p), 201)


@app.get("/prioritization-entries/<pid>")
def get_prio(pid):
    require(NAVIGATOR, ADMIN)
    return ok(ser_prio(get_or_404(prio_entries, pid)))


@app.get("/prioritization-entries")
def list_prio():
    require(NAVIGATOR, ADMIN)
    page, limit, offset, total = do_list(prio_entries.values(), {
        "client_id": "client_id", "matched_referral_id": "matched_referral_id",
        "status": "status"})
    return ok_list([ser_prio(x) for x in page], limit, offset, total)


@app.post("/prioritization-entries/<pid>/defer")
def defer_prio(pid):
    require(NAVIGATOR)
    p = get_or_404(prio_entries, pid)
    b = body()
    du = need(b, "deferred_until")
    parse_date(du, "deferred_until")
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "pool entry not ACTIVE")
    p["deferred_until"] = du
    p["status"] = "DEFERRED"
    touch(p)
    return ok(ser_prio(p))


@app.post("/prioritization-entries/<pid>/reactivate")
def reactivate_prio(pid):
    require(NAVIGATOR)
    p = get_or_404(prio_entries, pid)
    if p["status"] != "DEFERRED":
        err("ERR_INVALID_STATE", 409, "pool entry not DEFERRED")
    p["deferred_until"] = None
    p["status"] = "ACTIVE"
    client = clients.get(p["client_id"])
    if client:
        p["rank_score"] = rank_score_of(client)
    touch(p)
    return ok(ser_prio(p))


# ─────────────────────────────────────────────────────────────────────────────
# HousingNavigator
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/housing-navigators")
def create_navigator():
    require(ADMIN)
    b = body()
    name = as_str(need(b, "name"), "name")
    mc = as_int(need(b, "max_caseload"), "max_caseload")
    if mc < 1:
        err("ERR_INVALID_REQUEST", 400, "max_caseload must be >= 1")
    n = base_record()
    n.update({"name": name, "max_caseload": mc})
    navigators[n["id"]] = n
    return ok(ser_navigator(n), 201)


@app.get("/housing-navigators/<nid>")
def get_navigator(nid):
    require(NAVIGATOR, ADMIN)
    return ok(ser_navigator(get_or_404(navigators, nid)))


@app.get("/housing-navigators")
def list_navigators():
    require(NAVIGATOR, ADMIN)
    page, limit, offset, total = do_list(navigators.values(), {})
    return ok_list([ser_navigator(x) for x in page], limit, offset, total)


# ─────────────────────────────────────────────────────────────────────────────
# Referral
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/referrals")
def create_referral():
    require(NAVIGATOR)
    b = body()
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    peid = b.get("prioritization_entry_id")
    if peid is not None and peid not in prio_entries:
        err("ERR_NOT_FOUND", 404, "prioritization_entry_id does not exist")
    nid = b.get("navigator_id")
    if nid is not None and nid not in navigators:
        err("ERR_NOT_FOUND", 404, "navigator_id does not exist")
    cid = as_str(need(b, "client_id"), "client_id")
    peid = as_str(need(b, "prioritization_entry_id"), "prioritization_entry_id")
    nid = as_str(need(b, "navigator_id"), "navigator_id")
    psh = as_str(need(b, "psh_project_name"), "psh_project_name")
    pe = prio_entries[peid]
    # state (rule 5): pool entry must be ACTIVE
    if pe["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "pool entry not ACTIVE")
    # assessment prerequisite (rule 7)
    has_completed = any(a["client_id"] == cid and a["status"] == "COMPLETED"
                        for a in assessments.values())
    if not has_completed:
        err("ERR_ASSESSMENT_REQUIRED", 409, "client has no COMPLETED assessment")
    r = base_record()
    r.update({
        "client_id": cid, "prioritization_entry_id": peid, "navigator_id": nid,
        "psh_project_name": psh, "status": "PENDING",
    })
    referrals[r["id"]] = r
    pe["status"] = "MATCHED"
    pe["matched_referral_id"] = r["id"]
    touch(pe)
    return ok(ser_referral(r), 201)


@app.get("/referrals/<rid>")
def get_referral(rid):
    require(NAVIGATOR, ADMIN)
    r = get_or_404(referrals, rid)
    refresh_referral(r)
    return ok(ser_referral(r))


@app.get("/referrals")
def list_referrals():
    require(NAVIGATOR, ADMIN)
    page, limit, offset, total = do_list(referrals.values(), {
        "client_id": "client_id", "prioritization_entry_id": "prioritization_entry_id",
        "navigator_id": "navigator_id", "status": "status"})
    return ok_list([ser_referral(x) for x in page], limit, offset, total)


def _referral_owner_check(r, uid):
    if r["navigator_id"] != uid:
        err("ERR_FORBIDDEN", 403, "navigator does not own this referral")


@app.post("/referrals/<rid>/accept")
def accept_referral(rid):
    uid, _ = require(NAVIGATOR)
    r = get_or_404(referrals, rid)
    refresh_referral(r)
    _referral_owner_check(r, uid)
    if r["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "referral not PENDING")
    nav = navigators.get(r["navigator_id"])
    if nav and navigator_caseload(nav["id"]) >= nav["max_caseload"]:
        err("ERR_CASELOAD_FULL", 409, "navigator caseload is full")
    r["status"] = "ACCEPTED"
    touch(r)
    return ok(ser_referral(r))


@app.post("/referrals/<rid>/decline")
def decline_referral(rid):
    uid, _ = require(NAVIGATOR)
    r = get_or_404(referrals, rid)
    refresh_referral(r)
    _referral_owner_check(r, uid)
    if r["status"] not in ("PENDING", "ACCEPTED"):
        err("ERR_INVALID_STATE", 409, "referral not PENDING/ACCEPTED")
    r["status"] = "DECLINED"
    touch(r)
    requeue_pool_entry(prio_entries.get(r["prioritization_entry_id"]))
    return ok(ser_referral(r))


@app.post("/referrals/<rid>/enroll")
def enroll_referral(rid):
    uid, _ = require(NAVIGATOR)
    r = get_or_404(referrals, rid)
    refresh_referral(r)
    _referral_owner_check(r, uid)
    if r["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE", 409, "referral not ACCEPTED")
    r["status"] = "ENROLLED"
    touch(r)
    pe = prio_entries.get(r["prioritization_entry_id"])
    if pe and pe["status"] == "MATCHED":
        pe["status"] = "HOUSED"
        touch(pe)
    client = clients.get(r["client_id"])
    if client and client["status"] == "ACTIVE":
        client["status"] = "HOUSED"
        touch(client)
    return ok(ser_referral(r))


# ─────────────────────────────────────────────────────────────────────────────
# ExitRecord
# ─────────────────────────────────────────────────────────────────────────────
def exit_outcome(dest):
    if dest in ("PERMANENT_HOUSING", "RRH"):
        return "POSITIVE"
    if dest in ("TEMP_FAMILY", "INSTITUTION"):
        return "NEUTRAL"
    return "NEGATIVE"


EXIT_DESTINATIONS = {"PERMANENT_HOUSING", "RRH", "TEMP_FAMILY", "INSTITUTION",
                     "EMERGENCY_SHELTER", "STREET", "UNKNOWN"}


@app.post("/exit-records")
def create_exit():
    require(SHELTER_MGR, NAVIGATOR, ADMIN)
    b = body()
    cid = b.get("client_id")
    if cid is not None and cid not in clients:
        err("ERR_NOT_FOUND", 404, "client_id does not exist")
    resv_id = b.get("reservation_id")
    if resv_id is not None and resv_id not in reservations:
        err("ERR_NOT_FOUND", 404, "reservation_id does not exist")
    ref_id = b.get("referral_id")
    if ref_id is not None and ref_id not in referrals:
        err("ERR_NOT_FOUND", 404, "referral_id does not exist")
    cid = as_str(need(b, "client_id"), "client_id")
    dest = as_enum(need(b, "destination"), "destination", EXIT_DESTINATIONS)
    if (resv_id is None) == (ref_id is None):
        err("ERR_INVALID_REQUEST", 400, "exactly one of reservation_id / referral_id required")
    # already-exited (rule 16)
    for x in exit_records.values():
        if resv_id is not None and x["reservation_id"] == resv_id:
            err("ERR_ALREADY_EXITED", 409, "reservation already exited")
        if ref_id is not None and x["referral_id"] == ref_id:
            err("ERR_ALREADY_EXITED", 409, "referral already exited")
    if resv_id is not None:
        r = reservations[resv_id]
        end = r["exit_date"] or r["expected_exit_date"]
        bed_nights = (parse_date(end) - parse_date(r["entry_date"])).days
        if bed_nights < 0:
            bed_nights = 0
    else:
        bed_nights = 0
    x = base_record(mutable=False)
    x.update({
        "client_id": cid, "reservation_id": resv_id, "referral_id": ref_id,
        "destination": dest, "outcome": exit_outcome(dest), "bed_nights": bed_nights,
    })
    exit_records[x["id"]] = x
    return ok(ser_exit(x), 201)


@app.get("/exit-records/<xid>")
def get_exit(xid):
    require(SHELTER_MGR, NAVIGATOR, ADMIN)
    return ok(ser_exit(get_or_404(exit_records, xid)))


@app.get("/exit-records")
def list_exits():
    require(SHELTER_MGR, NAVIGATOR, ADMIN)
    page, limit, offset, total = do_list(exit_records.values(), {
        "client_id": "client_id", "reservation_id": "reservation_id",
        "referral_id": "referral_id"})
    return ok_list([ser_exit(x) for x in page], limit, offset, total)


# ─────────────────────────────────────────────────────────────────────────────
# APR Report
# ─────────────────────────────────────────────────────────────────────────────
def _round(value, dp):
    q = Decimal(1).scaleb(-dp)
    return float(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


@app.get("/reports/apr")
def apr():
    require(ADMIN)
    shelter_id = request.args.get("shelter_id")
    as_of = request.args.get("as_of_date")
    as_of_dt = None
    if as_of is not None:
        d = parse_date(as_of, "as_of_date")
        as_of_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    scope = []
    for x in exit_records.values():
        if as_of_dt is not None and not (x["created_at"] < as_of_dt):
            continue
        if shelter_id is not None:
            rid = x["reservation_id"]
            if rid is None or reservations.get(rid, {}).get("shelter_id") != shelter_id:
                continue
        scope.append(x)

    total_exited = len(scope)
    positive = sum(1 for x in scope if x["outcome"] == "POSITIVE")
    sum_bn = sum(x["bed_nights"] for x in scope)
    if total_exited == 0:
        positive_rate = 0.0
        avg_los = 0.0
    else:
        positive_rate = _round(Decimal(positive) * 100 / Decimal(total_exited), 1)
        avg_los = _round(Decimal(sum_bn) / Decimal(total_exited), 2)

    total_enrolled = (
        sum(1 for r in reservations.values() if r["status"] in ("RESERVED", "CHECKED_IN"))
        + sum(1 for r in referrals.values() if r["status"] in ("ACCEPTED", "ENROLLED"))
    )
    return ok({
        "total_enrolled": total_enrolled,
        "total_exited": total_exited,
        "positive_exit_rate": positive_rate,
        "avg_length_of_stay": avg_los,
    })


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
