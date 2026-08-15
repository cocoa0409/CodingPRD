"""Shared business logic: validation helpers, derived counters, risk scoring,
audit population, and cascading state transitions (PRD sections 2.5-2.10, 3).

Derived counters (open_session_count, applied_lock_count,
outstanding_lock_count, is_currently_qualified, risk_score, risk_tier) are
computed live against the logical clock whenever an entity is serialized or a
guard reads them, so every recomputation rule in the PRD is honored by
construction.
"""

import uuid
from datetime import timedelta

from flask import request

import db
from clock import CLOCK, parse_iso, fmt
from errors import ApiError

# ---------------------------------------------------------------------------
# Status sets
# ---------------------------------------------------------------------------

OPEN_SESSION_STATUSES = ("SETUP", "LOCKED", "CLEARED")
NONTERMINAL_LOCK_STATUSES = ("ISSUED", "APPLIED")
# Locks that reached APPLIED (for the audit population) whether or not they
# have since come off the machine.
APPLIED_HISTORY_STATUSES = ("APPLIED", "REMOVED", "FORCE_REMOVED")

KIND_WEIGHT = {
    "NEAR_MISS": 1,
    "FIRST_AID": 2,
    "PROPERTY_DAMAGE": 3,
    "INJURY": 5,
}

TIER_MEDIUM_MIN = 5
TIER_HIGH_MIN = 10
WINDOW_DAYS = 365
ASSIGNMENT_DUE_DAYS = 30

DURATION_CAP = {"LOW": 480, "MEDIUM": 120, "HIGH": 0}


# ---------------------------------------------------------------------------
# Request-body schema helpers (validation pipeline stage 3 -> ERR_VALIDATION)
# ---------------------------------------------------------------------------

def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return b


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", 400,
                       f"{field} is required and must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a string")
    return v


def req_enum(body, field, members):
    v = body.get(field)
    if not isinstance(v, str) or v not in members:
        raise ApiError("ERR_VALIDATION", 400,
                       f"{field} must be one of {', '.join(members)}")
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"{field} is required and must be an integer")
    if min_v is not None and v < min_v:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be <= {max_v}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"{field} is required and must be a boolean")
    return v


def req_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400,
                       f"{field} is required and must be an ISO 8601 timestamp")
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400,
                       f"{field} must be a valid ISO 8601 timestamp")


def req_array(body, field, min_len=1, required_keys=None):
    v = body.get(field)
    if not isinstance(v, list) or len(v) < min_len:
        raise ApiError("ERR_VALIDATION", 400,
                       f"{field} must be an array with at least {min_len} entr{'y' if min_len == 1 else 'ies'}")
    if required_keys:
        for entry in v:
            if not isinstance(entry, dict) or any(k not in entry for k in required_keys):
                raise ApiError("ERR_VALIDATION", 400,
                               f"each {field} entry must record {', '.join(required_keys)}")
    return v


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(obj, with_version=True):
    """Attach id/created_at (+updated_at/version) system fields (PRD 2.5).

    MachineModification passes with_version=False: as an append-only log it
    carries only id and created_at.
    """
    ts = fmt(CLOCK.now())
    obj["created_at"] = ts
    if with_version:
        obj["updated_at"] = ts
        obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    """Refresh updated_at and increment version on a mutation (PRD 2.5/2.10)."""
    obj["updated_at"] = fmt(CLOCK.now())
    obj["version"] += 1


def get_or_404(table, rid, what):
    rec = db.DB[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{what} does not exist")
    return rec


def sorted_by_created(records):
    """List endpoints sort by created_at ascending (PRD 2.3); _seq breaks ties
    deterministically for resources created at the same clock instant."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Derived counters and computed fields (PRD 2.10, calculations table)
# ---------------------------------------------------------------------------

def open_session_count(machine_id):
    return sum(1 for s in db.DB["lockout_sessions"].values()
               if s["machine_id"] == machine_id and s["status"] in OPEN_SESSION_STATUSES)


def applied_lock_count(session_id):
    return sum(1 for l in db.DB["employee_locks"].values()
               if l["session_id"] == session_id and l["status"] == "APPLIED")


def outstanding_lock_count(employee_id):
    return sum(1 for l in db.DB["employee_locks"].values()
               if l["employee_id"] == employee_id and l["status"] in NONTERMINAL_LOCK_STATUSES)


def is_currently_qualified(emp):
    """AUTHORIZED qualification plus an unexpired COMPLETED authorized-course
    training record; expiry is a strict > against the clock (PRD 2.6/3.4)."""
    if emp["qualification"] != "AUTHORIZED":
        return False
    now = CLOCK.now()
    for t in db.DB["training_records"].values():
        if (t["employee_id"] == emp["id"]
                and t["course_code"] in ("LOTO_AUTHORIZED_INITIAL", "LOTO_AUTHORIZED_REFRESH")
                and t["status"] == "COMPLETED"
                and t["expires_at"] is not None
                and parse_iso(t["expires_at"]) > now):
            return True
    return False


def actor_qualified(user_id):
    emp = db.DB["employees"].get(user_id)
    return emp is not None and is_currently_qualified(emp)


def current_procedure(machine_id):
    """The machine's current procedure: the non-SUPERSEDED, non-RETIRED revision
    with the greatest revision_no (PRD 3.8)."""
    cands = [p for p in db.DB["lockout_procedures"].values()
             if p["machine_id"] == machine_id and p["status"] not in ("SUPERSEDED", "RETIRED")]
    if not cands:
        return None
    return max(cands, key=lambda p: p["revision_no"])


def risk_score(machine):
    """calculations.machine_risk_score: weighted sum over the machine's LINKED
    incidents inside the window selected by risk_window_policy."""
    linked = [i for i in db.DB["incident_reports"].values()
              if i["machine_id"] == machine["id"] and i["status"] == "LINKED"]
    if machine["risk_window_policy"] == "ROLLING_12MO":
        lo = CLOCK.now() - timedelta(days=WINDOW_DAYS)
        included = [i for i in linked if parse_iso(i["occurred_at"]) >= lo]
    else:  # SINCE_PROCEDURE_ACTIVATION
        proc = current_procedure(machine["id"])
        if proc is None or not proc["activated_at"]:
            included = []
        else:
            act = parse_iso(proc["activated_at"])
            included = [i for i in linked if parse_iso(i["occurred_at"]) >= act]
    return sum(KIND_WEIGHT[i["kind"]] for i in included)


def risk_tier_of(score):
    if score >= TIER_HIGH_MIN:
        return "HIGH"
    if score >= TIER_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def risk_tier(machine):
    return risk_tier_of(risk_score(machine))


def period_appliers(procedure_id, period_start, now):
    """calculations.audit_sample_minimum population: distinct employees whose
    locks reached APPLIED under the procedure with applied_at in the closed
    interval [period_start, now]."""
    if period_start is None:
        return set()
    ps = parse_iso(period_start)
    out = set()
    for l in db.DB["employee_locks"].values():
        if l["status"] not in APPLIED_HISTORY_STATUSES or l["applied_at"] is None:
            continue
        s = db.DB["lockout_sessions"].get(l["session_id"])
        if s is None or s["procedure_id"] != procedure_id:
            continue
        ap = parse_iso(l["applied_at"])
        if ps <= ap <= now:
            out.add(l["employee_id"])
    return out


# ---------------------------------------------------------------------------
# Cascades (PRD 2.10): each cascade-mutated entity gets its own
# updated_at refresh and version increment.
# ---------------------------------------------------------------------------

def cancel_setup_session(s):
    """LockoutSession SETUP -> CANCELLED with the ISSUED-lock voiding cascade.
    Shared by the manual cancel and every system-driven cancel."""
    s["status"] = "CANCELLED"
    touch(s)
    for l in db.DB["employee_locks"].values():
        if l["session_id"] == s["id"] and l["status"] == "ISSUED":
            l["status"] = "VOIDED"
            touch(l)


def machine_out_of_service(machine):
    """Machine IN_SERVICE -> OUT_OF_SERVICE: cancel its SETUP sessions and void
    their ISSUED locks. LOCKED / CLEARED sessions are work in progress and are
    left untouched (PRD 3.1/3.8)."""
    machine["status"] = "OUT_OF_SERVICE"
    touch(machine)
    for s in db.DB["lockout_sessions"].values():
        if s["machine_id"] == machine["id"] and s["status"] == "SETUP":
            cancel_setup_session(s)


def procedure_into_revision_on_modification(proc):
    """ACTIVE -> UNDER_REVISION on a registered modification: cancels the SETUP
    sessions referencing this procedure and voids their ISSUED locks (PRD 3.3)."""
    proc["status"] = "UNDER_REVISION"
    touch(proc)
    for s in db.DB["lockout_sessions"].values():
        if s["procedure_id"] == proc["id"] and s["status"] == "SETUP":
            cancel_setup_session(s)


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved at read time)
# ---------------------------------------------------------------------------

def machine_view(m):
    v = _public(m)
    v["risk_score"] = risk_score(m)
    v["risk_tier"] = risk_tier(m)
    v["open_session_count"] = open_session_count(m["id"])
    return v


def modification_view(mod):
    return _public(mod)


def employee_view(e):
    v = _public(e)
    v["is_currently_qualified"] = is_currently_qualified(e)
    v["outstanding_lock_count"] = outstanding_lock_count(e["id"])
    return v


def survey_view(sv):
    return _public(sv)


def procedure_view(p):
    return _public(p)


def training_view(t):
    return _public(t)


def session_view(s):
    v = _public(s)
    v["applied_lock_count"] = applied_lock_count(s["id"])
    return v


def lock_view(l):
    return _public(l)


def audit_view(a):
    return _public(a)


def incident_view(i):
    return _public(i)


def permit_view(p):
    return _public(p)


def exception_view(e):
    return _public(e)
