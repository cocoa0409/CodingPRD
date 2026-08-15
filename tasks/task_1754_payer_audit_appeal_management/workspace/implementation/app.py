#!/usr/bin/env python3
"""Payer Audit & Appeal Management API — in-memory Flask implementation."""
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml §constants)
# ---------------------------------------------------------------------------
DIRECTOR_CLOSE_THRESHOLD_CENTS = 2500000
CAP_EFFECTIVENESS_WINDOW_DAYS = 14
CAP_MAX_CYCLES = 3
DEFAULT_OVERTURN_BP = 5000
INTEREST_PERIOD_DAYS = 30
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

VALID_ROLES = {
    "RevenueCycleAdmin", "HIMCoordinator", "AppealsSpecialist",
    "DepartmentDirector", "PFSAccountant", "ComplianceOfficer",
    "InternalAuditor", "PayerAgent",
}

PAYER_TYPES = {"RAC", "COMMERCIAL"}
AUDIT_TYPES = {"RAC_COMPLEX", "RAC_AUTOMATED", "COMMERCIAL_POSTPAY",
               "COMMERCIAL_PREPAY", "TARGETED_PROBE"}
ISSUE_CATEGORIES = {"CLINICAL", "TECHNICAL"}
ITEM_TYPES = {"MEDICAL_RECORD", "PHYSICIAN_LETTER", "POLICY_CITATION",
              "EXPERT_REVIEW", "PRIOR_AUTH_DOC"}
APPEAL_LEVELS = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5"]
MEDICARE_LABELS = {"LEVEL_1": "REDETERMINATION", "LEVEL_2": "RECONSIDERATION",
                   "LEVEL_3": "ALJ", "LEVEL_4": "COUNCIL", "LEVEL_5": "FEDERAL"}
COMMERCIAL_LABELS = {"LEVEL_1": "INTERNAL_1", "LEVEL_2": "INTERNAL_2",
                     "LEVEL_3": "EXTERNAL_REVIEW"}
TRACK_MAX_LEVEL = {"MEDICARE": 5, "COMMERCIAL": 3}

DECIDED_STATES = {"DECIDED_FAVORABLE", "DECIDED_PARTIAL", "DECIDED_UNFAVORABLE"}
LINE_TERMINAL = {"PAID_AS_BILLED", "OVERTURNED", "FINAL"}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock = {"now": datetime(2026, 8, 1, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def parse_dt(s):
    """Parse an ISO-8601 timestamp (with optional fractional seconds / Z)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO-8601 UTC with Z suffix; omit the fractional part when zero so the
    rendered form matches the PRD's own examples (e.g. 2026-08-01T00:00:00Z).
    When microseconds are non-zero, render three fractional digits per §2.5."""
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    if millis:
        return base + f".{millis:03d}Z"
    return base + "Z"


def round_half_up(num, den=1):
    """Integer round-half-up of num/den for non-negative integers."""
    if num < 0:
        return -round_half_up(-num, den)
    return (2 * num + den) // (2 * den)


# ---------------------------------------------------------------------------
# In-memory store — empty on every boot, no seeding
# ---------------------------------------------------------------------------
db = {
    "payers": {},
    "issue_codes": {},
    "audit_cases": {},
    "claim_lines": {},
    "appeals": {},
    "evidence_packets": {},
    "packet_items": {},
    "recoupment_demands": {},
    "remittances": {},
    "offset_transactions": {},
    "corrective_action_plans": {},
    "audit_case_events": {},
}


def new_id():
    return str(uuid.uuid4())


_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def stamp_new(obj):
    now = fmt_dt(clock_now())
    obj["id"] = new_id()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    obj["updated_at"] = fmt_dt(clock_now())
    obj["version"] += 1


# ---------------------------------------------------------------------------
# Errors and response envelope (SCAFFOLD §1.0)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), code


def error_response(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_forbidden(msg="Caller role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def err_state(msg="Target resource state forbids this transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


# ---------------------------------------------------------------------------
# Auth middleware (validation priorities 1 & 2)
# ---------------------------------------------------------------------------
def auth(required_roles):
    """Returns (user_id, role) or raises ApiError. required_roles=None -> Any."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-Role header missing or malformed")
    if required_roles is not None and role not in required_roles:
        raise err_forbidden()
    return user_id, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    return data


def req_str(data, f):
    v = data.get(f)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"Field {f} must be a non-empty string")
    return v


def req_int(data, f, minimum=None):
    v = data.get(f)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {f} must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"Field {f} must be >= {minimum}")
    return v


def opt_str(data, f):
    v = data.get(f)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request(f"Field {f} must be a string")
    return v


def req_enum(data, f, allowed):
    v = data.get(f)
    if v not in allowed:
        raise err_invalid_request(f"Field {f} must be one of {sorted(allowed)}")
    return v


def req_dt(data, f):
    v = data.get(f)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {f} must be an ISO-8601 timestamp")


def opt_dt(data, f):
    v = data.get(f)
    if v is None:
        return None
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {f} must be an ISO-8601 timestamp")


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except ValueError:
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paged(items, limit, offset):
    items = sorted(items, key=lambda o: o.get("_seq", 0))
    total = len(items)
    return items[offset:offset + limit], total


def strip_internal(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Entity serializers
# ---------------------------------------------------------------------------
def payer_view(p):
    return strip_internal(p)


def issue_code_view(ic):
    return strip_internal(ic)


def case_view(c):
    return strip_internal(c)


def line_view(l):
    return strip_internal(l)


def appeal_view(a):
    return strip_internal(a)


def packet_view(p):
    return strip_internal(p)


def item_view(i):
    return strip_internal(i)


def demand_view(d):
    d = strip_internal(d)
    d["accrued_interest_cents"] = compute_interest(d)
    d["outstanding_principal_cents"] = compute_outstanding(d)
    return d


def remittance_view(r):
    r = strip_internal(r)
    r["available_cents"] = compute_available(r)
    return r


def offset_view(o):
    return strip_internal(o)


def cap_view(c):
    return strip_internal(c)


def event_view(e):
    return strip_internal(e)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def get_payer(pid):
    p = db["payers"].get(pid)
    if p is None:
        raise err_not_found("Payer not found")
    return p


def get_case(cid):
    c = db["audit_cases"].get(cid)
    if c is None:
        raise err_not_found("Audit case not found")
    return c


def get_line(lid):
    l = db["claim_lines"].get(lid)
    if l is None:
        raise err_not_found("Claim line not found")
    return l


def get_appeal(aid):
    a = db["appeals"].get(aid)
    if a is None:
        raise err_not_found("Appeal not found")
    return a


def get_packet(pid):
    p = db["evidence_packets"].get(pid)
    if p is None:
        raise err_not_found("Evidence packet not found")
    return p


def get_demand(did):
    d = db["recoupment_demands"].get(did)
    if d is None:
        raise err_not_found("Recoupment demand not found")
    return d


def get_remittance(rid):
    r = db["remittances"].get(rid)
    if r is None:
        raise err_not_found("Remittance not found")
    return r


def get_offset(oid):
    o = db["offset_transactions"].get(oid)
    if o is None:
        raise err_not_found("Offset transaction not found")
    return o


def get_cap(cid):
    c = db["corrective_action_plans"].get(cid)
    if c is None:
        raise err_not_found("Corrective action plan not found")
    return c


def case_lines(case_id):
    return [l for l in db["claim_lines"].values() if l["audit_case_id"] == case_id]


def case_appeals(case_id):
    return [a for a in db["appeals"].values() if a["audit_case_id"] == case_id]


def line_appeals(line_id):
    return [a for a in db["appeals"].values() if a["audit_claim_line_id"] == line_id]


def case_demands(case_id):
    return [d for d in db["recoupment_demands"].values()
            if d["audit_case_id"] == case_id]


def demand_offsets(demand_id, applied_only=False):
    out = [o for o in db["offset_transactions"].values()
           if o["recoupment_demand_id"] == demand_id]
    if applied_only:
        out = [o for o in out if o["status"] == "APPLIED"]
    return out


def remittance_offsets(remit_id, applied_only=False):
    out = [o for o in db["offset_transactions"].values()
           if o["remittance_id"] == remit_id]
    if applied_only:
        out = [o for o in out if o["status"] == "APPLIED"]
    return out


def recompute_case_totals(case):
    lines = case_lines(case["id"])
    case["total_billed_cents"] = sum(l["billed_amount_cents"] for l in lines)
    case["total_denied_active_cents"] = sum(
        l["denied_amount_cents"] for l in lines
        if l["status"] in ("DENIED", "PARTIALLY_DENIED"))
    case["total_final_denied_cents"] = sum(
        l["denied_amount_cents"] for l in lines if l["status"] == "FINAL")
    case["total_upheld_cents"] = sum(
        l["billed_amount_cents"] - l["denied_amount_cents"] for l in lines
        if l["status"] in ("PAID_AS_BILLED", "DENIED", "PARTIALLY_DENIED",
                           "OVERTURNED", "FINAL"))
    # total_overturned_cents is increment-only; not recomputed here.


def compute_outstanding(demand):
    applied_principal = sum(o["principal_portion_cents"]
                            for o in demand_offsets(demand["id"], applied_only=True))
    return (demand["principal_cents"] - applied_principal
            - demand["written_off_cents"])


def compute_interest(demand):
    """recoupment_interest_accrual calculation (SCAFFOLD §1.3)."""
    now = clock_now()
    issued_at = parse_dt(demand["issued_at"])
    eligible = (now - issued_at).total_seconds() - demand["accumulated_hold_seconds"]
    if demand["hold_started_at"] is not None:
        eligible -= (now - parse_dt(demand["hold_started_at"])).total_seconds()
    if eligible <= 0:
        return 0
    periods = int(eligible // (INTEREST_PERIOD_DAYS * 86400))
    if periods <= 0:
        return 0
    outstanding = compute_outstanding(demand)
    t1 = demand["rate_bps_tier1_snapshot"]
    t2 = demand["rate_bps_tier2_snapshot"]
    if periods <= 2:
        raw_num = outstanding * t1 * periods
    else:
        raw_num = outstanding * (t1 * 2 + t2 * (periods - 2))
    cap_num = demand["principal_at_issue_cents"] * demand["interest_cap_pct_snapshot"] * 10000
    # raw = raw_num / 10000 ; cap = cap_num / (100 * 10000)
    # min(raw, cap) then round half up to cents
    raw_scaled = raw_num * 100          # raw * 10000 * 100
    if raw_scaled > cap_num:
        scaled = cap_num                # in units of 1/(100*10000) cents
    else:
        scaled = raw_scaled
    return round_half_up(scaled, 100 * 10000)


def compute_available(remit):
    applied = sum(o["amount_cents"]
                  for o in remittance_offsets(remit["id"], applied_only=True))
    return remit["gross_amount_cents"] - applied


def recompute_demand_status(demand):
    """Recompute status after offset apply/reverse (not for terminal REVERSED/WRITTEN_OFF)."""
    if demand["status"] in ("REVERSED", "WRITTEN_OFF", "ON_HOLD"):
        return
    outstanding = compute_outstanding(demand)
    has_applied = any(True for _ in demand_offsets(demand["id"], applied_only=True))
    if outstanding == 0 and has_applied:
        demand["status"] = "FULLY_RECOUPED"
    elif has_applied:
        demand["status"] = "PARTIALLY_RECOUPED"
    else:
        demand["status"] = "DEMANDED"


def recompute_remittance_status(remit):
    avail = compute_available(remit)
    if avail == remit["gross_amount_cents"]:
        remit["status"] = "RECEIVED"
    elif avail == 0:
        remit["status"] = "FULLY_ALLOCATED"
    else:
        remit["status"] = "PARTIALLY_ALLOCATED"


def append_event(case_id, event_type, actor_role, actor_user_id, payload):
    ev = {
        "id": new_id(),
        "created_at": fmt_dt(clock_now()),
        "audit_case_id": case_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "payload": payload or {},
        "occurred_at": fmt_dt(clock_now()),
        "_seq": next_seq(),
    }
    db["audit_case_events"][ev["id"]] = ev
    return ev


def release_holds(case_id):
    """Release ON_HOLD demands of a case (appeal decided/withdrawn)."""
    now = clock_now()
    for d in case_demands(case_id):
        if d["status"] == "ON_HOLD":
            started = parse_dt(d["hold_started_at"])
            d["accumulated_hold_seconds"] += int((now - started).total_seconds())
            d["hold_started_at"] = None
            has_applied = any(True for _ in demand_offsets(d["id"], applied_only=True))
            d["status"] = "PARTIALLY_RECOUPED" if has_applied else "DEMANDED"
            touch(d)


def full_vindication_check(case):
    """If total_denied_active hits 0, reverse all live demands and their offsets."""
    if case["total_denied_active_cents"] != 0:
        return
    for d in case_demands(case["id"]):
        if d["status"] in ("DEMANDED", "ON_HOLD", "PARTIALLY_RECOUPED",
                           "FULLY_RECOUPED"):
            if d["status"] == "ON_HOLD" and d["hold_started_at"] is not None:
                started = parse_dt(d["hold_started_at"])
                d["accumulated_hold_seconds"] += int(
                    (clock_now() - started).total_seconds())
                d["hold_started_at"] = None
            for o in demand_offsets(d["id"], applied_only=True):
                o["status"] = "REVERSED"
                o["reversed_at"] = fmt_dt(clock_now())
                touch(o)
                remit = db["remittances"][o["remittance_id"]]
                recompute_remittance_status(remit)
                touch(remit)
            d["status"] = "REVERSED"
            touch(d)


def level_label(track, level):
    return (MEDICARE_LABELS if track == "MEDICARE" else COMMERCIAL_LABELS)[level]


def level_num(level):
    return int(level.split("_")[1])


# ---------------------------------------------------------------------------
# Clock sweeps
# ---------------------------------------------------------------------------
def sweep_clock():
    """Evaluate missed-deadline auto-denials and claim-line finalization."""
    now = clock_now()
    # Missed records deadline sweep
    for case in list(db["audit_cases"].values()):
        if case["status"] == "RECEIVED" and now > parse_dt(case["records_due_at"]):
            case["status"] = "MISSED_DEADLINE"
            touch(case)
            append_event(case["id"], "CASE_MISSED_DEADLINE", "System", "system",
                         {"records_due_at": case["records_due_at"]})
            auto_denied = []
            for line in case_lines(case["id"]):
                if line["status"] == "UNDER_AUDIT":
                    line["status"] = "DENIED"
                    line["denied_amount_cents"] = line["billed_amount_cents"]
                    line["denial_category"] = "TECHNICAL"
                    line["issue_code_id"] = None
                    line["auto_denied"] = True
                    touch(line)
                    auto_denied.append(line["id"])
            recompute_case_totals(case)
            touch(case)
            append_event(case["id"], "LINES_AUTO_DENIED", "System", "system",
                         {"claim_line_ids": auto_denied,
                          "total_denied_active_cents": case["total_denied_active_cents"]})
    # Claim-line finalization sweep
    for case in list(db["audit_cases"].values()):
        payer = db["payers"].get(case["payer_id"])
        for line in case_lines(case["id"]):
            if line["status"] not in ("DENIED", "PARTIALLY_DENIED"):
                continue
            appeals = line_appeals(line["id"])
            if any(a["status"] == "PENDING_DECISION" for a in appeals):
                continue
            if any(a["status"] == "DRAFT"
                   and parse_dt(a["filed_deadline_at"]) >= now for a in appeals):
                continue
            # Compute the next appeal level's would-be filed_deadline_at
            next_deadline = next_appeal_deadline(case, payer, line, appeals)
            if next_deadline is None:
                # No further level available in track: deadline of last appeal
                decided = [a for a in appeals if a["status"] in DECIDED_STATES]
                if decided:
                    last = max(decided, key=lambda a: parse_dt(a["decided_at"]))
                    next_deadline = parse_dt(last["filed_deadline_at"])
                else:
                    continue
            if now > next_deadline:
                line["status"] = "FINAL"
                touch(line)
                recompute_case_totals(case)
                touch(case)


def next_appeal_deadline(case, payer, line, appeals):
    """The filed_deadline_at the next appeal level would carry, or None if the
    track has no further level."""
    decided = [a for a in appeals if a["status"] in DECIDED_STATES]
    if not decided:
        # No prior decided appeal: next level is LEVEL_1
        if case["determination_issued_at"] is None:
            return None
        base = parse_dt(case["determination_issued_at"])
        return base + timedelta(days=payer["l1_deadline_days"])
    last = max(decided, key=lambda a: (level_num(a["level"]), parse_dt(a["decided_at"])))
    next_level = level_num(last["level"]) + 1
    track = payer["appeal_track"]
    if next_level > TRACK_MAX_LEVEL[track]:
        return None
    base = parse_dt(last["decided_at"])
    if next_level == 2:
        days = payer["l2_deadline_days"]
    elif next_level == 3:
        days = (payer["l3_deadline_days"] if track == "MEDICARE"
                else payer["external_review_deadline_days"])
    elif next_level == 4:
        days = payer["l4_deadline_days"]
    else:
        days = payer["l5_deadline_days"]
    return base + timedelta(days=days)


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth({"RevenueCycleAdmin"})
    data = body_json()
    require_fields(data, ["to_iso8601"])
    target = req_dt(data, "to_iso8601")
    _clock["now"] = target
    sweep_clock()
    return ok_object({"current_utc": fmt_dt(_clock["now"])})


# ===========================================================================
# Payers
# ===========================================================================
@app.route("/payers", methods=["POST"])
def create_payer():
    user_id, role = auth({"RevenueCycleAdmin"})
    data = body_json()
    require_fields(data, ["name", "payer_type", "records_submission_days",
                          "l1_deadline_days", "l2_deadline_days",
                          "l3_deadline_days", "l4_deadline_days",
                          "l5_deadline_days", "external_review_deadline_days",
                          "concurrent_audit_cap", "hold_levels",
                          "interest_rate_bps_tier1", "interest_rate_bps_tier2",
                          "interest_cap_pct"])
    name = req_str(data, "name")
    payer_type = req_enum(data, "payer_type", PAYER_TYPES)
    hold_levels = data.get("hold_levels")
    if not isinstance(hold_levels, list) or any(
            h not in ("LEVEL_1", "LEVEL_2") for h in hold_levels):
        raise err_invalid_request("hold_levels must be a subset of [LEVEL_1, LEVEL_2]")
    p = stamp_new({
        "name": name,
        "payer_type": payer_type,
        "appeal_track": "MEDICARE" if payer_type == "RAC" else "COMMERCIAL",
        "records_submission_days": req_int(data, "records_submission_days"),
        "l1_deadline_days": req_int(data, "l1_deadline_days"),
        "l2_deadline_days": req_int(data, "l2_deadline_days"),
        "l3_deadline_days": req_int(data, "l3_deadline_days"),
        "l4_deadline_days": req_int(data, "l4_deadline_days"),
        "l5_deadline_days": req_int(data, "l5_deadline_days"),
        "external_review_deadline_days": req_int(data, "external_review_deadline_days"),
        "concurrent_audit_cap": req_int(data, "concurrent_audit_cap"),
        "hold_levels": list(hold_levels),
        "interest_rate_bps_tier1": req_int(data, "interest_rate_bps_tier1"),
        "interest_rate_bps_tier2": req_int(data, "interest_rate_bps_tier2"),
        "interest_cap_pct": req_int(data, "interest_cap_pct"),
        "status": "ACTIVE",
    })
    db["payers"][p["id"]] = p
    return ok_object(payer_view(p), 201)


@app.route("/payers", methods=["GET"])
def list_payers():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["payers"].values())
    pt = request.args.get("payer_type")
    st = request.args.get("status")
    if pt is not None:
        items = [p for p in items if p["payer_type"] == pt]
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, total = paged(items, limit, offset)
    return ok_list([payer_view(p) for p in page], total, limit, offset)


@app.route("/payers/<pid>", methods=["GET"])
def get_payer_route(pid):
    auth(None)
    return ok_object(payer_view(get_payer(pid)))


@app.route("/payers/<pid>/suspend", methods=["POST"])
def suspend_payer(pid):
    auth({"RevenueCycleAdmin"})
    p = get_payer(pid)
    if p["status"] != "ACTIVE":
        raise err_state("Payer is not ACTIVE")
    p["status"] = "SUSPENDED"
    touch(p)
    return ok_object(payer_view(p))


@app.route("/payers/<pid>/reactivate", methods=["POST"])
def reactivate_payer(pid):
    auth({"RevenueCycleAdmin"})
    p = get_payer(pid)
    if p["status"] != "SUSPENDED":
        raise err_state("Payer is not SUSPENDED")
    p["status"] = "ACTIVE"
    touch(p)
    return ok_object(payer_view(p))


# ===========================================================================
# Issue codes
# ===========================================================================
@app.route("/issue-codes", methods=["POST"])
def create_issue_code():
    auth({"RevenueCycleAdmin"})
    data = body_json()
    require_fields(data, ["code", "category", "description"])
    code = req_str(data, "code")
    category = req_enum(data, "category", ISSUE_CATEGORIES)
    description = req_str(data, "description")
    if any(ic["code"] == code for ic in db["issue_codes"].values()):
        raise ApiError("ERR_DUPLICATE_ISSUE_CODE", 409,
                       "An issue code with this code already exists")
    ic = stamp_new({"code": code, "category": category,
                    "description": description, "active": True})
    db["issue_codes"][ic["id"]] = ic
    return ok_object(issue_code_view(ic), 201)


@app.route("/issue-codes", methods=["GET"])
def list_issue_codes():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["issue_codes"].values())
    cat = request.args.get("category")
    if cat is not None:
        items = [i for i in items if i["category"] == cat]
    page, total = paged(items, limit, offset)
    return ok_list([issue_code_view(i) for i in page], total, limit, offset)


@app.route("/issue-codes/<iid>", methods=["GET"])
def get_issue_code_route(iid):
    auth(None)
    ic = db["issue_codes"].get(iid)
    if ic is None:
        raise err_not_found("Issue code not found")
    return ok_object(issue_code_view(ic))


# ===========================================================================
# Audit cases & claim lines
# ===========================================================================
@app.route("/audit-cases", methods=["POST"])
def create_audit_case():
    user_id, role = auth({"HIMCoordinator", "RevenueCycleAdmin"})
    data = body_json()
    require_fields(data, ["payer_id", "audit_type", "received_at"])
    payer_id = req_str(data, "payer_id")
    audit_type = req_enum(data, "audit_type", AUDIT_TYPES)
    received_at = req_dt(data, "received_at")
    external_ref = opt_str(data, "external_audit_ref")
    payer = get_payer(payer_id)
    if payer["status"] != "ACTIVE":
        raise ApiError("ERR_PAYER_SUSPENDED", 409, "Payer is SUSPENDED")
    open_count = sum(1 for c in db["audit_cases"].values()
                     if c["payer_id"] == payer_id and c["status"] != "CLOSED")
    if open_count >= payer["concurrent_audit_cap"]:
        raise ApiError("ERR_CONCURRENT_AUDIT_CAP", 409,
                       "Payer concurrent audit cap reached")
    case = stamp_new({
        "payer_id": payer_id,
        "audit_type": audit_type,
        "received_at": fmt_dt(received_at),
        "external_audit_ref": external_ref,
        "status": "RECEIVED",
        "records_due_at": fmt_dt(received_at + timedelta(
            days=payer["records_submission_days"])),
        "records_submitted_at": None,
        "late_submission": False,
        "determination_issued_at": None,
        "total_billed_cents": 0,
        "total_upheld_cents": 0,
        "total_denied_active_cents": 0,
        "total_overturned_cents": 0,
        "total_final_denied_cents": 0,
        "closed_at": None,
    })
    db["audit_cases"][case["id"]] = case
    append_event(case["id"], "CASE_CREATED", role, user_id,
                 {"payer_id": payer_id, "audit_type": audit_type})
    return ok_object(case_view(case), 201)


@app.route("/audit-cases", methods=["GET"])
def list_audit_cases():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["audit_cases"].values())
    for param, field in (("payer_id", "payer_id"), ("status", "status"),
                         ("audit_type", "audit_type")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    page, total = paged(items, limit, offset)
    return ok_list([case_view(c) for c in page], total, limit, offset)


@app.route("/audit-cases/<cid>", methods=["GET"])
def get_audit_case(cid):
    auth(None)
    return ok_object(case_view(get_case(cid)))


@app.route("/audit-cases/<cid>/claim-lines", methods=["POST"])
def create_claim_line(cid):
    auth({"HIMCoordinator"})
    data = body_json()
    require_fields(data, ["claim_number", "patient_account_number",
                          "service_start_date", "service_end_date",
                          "billed_amount_cents"])
    claim_number = req_str(data, "claim_number")
    pan = req_str(data, "patient_account_number")
    start = req_dt(data, "service_start_date")
    end = req_dt(data, "service_end_date")
    billed = req_int(data, "billed_amount_cents", minimum=1)
    if end <= start:
        raise err_invalid_request("service_end_date must be > service_start_date")
    case = get_case(cid)
    if case["status"] == "CLOSED":
        raise err_state("Case is CLOSED")
    # Cross-case duplicate guard (same payer, other non-CLOSED case)
    for other in db["claim_lines"].values():
        if other["audit_case_id"] == cid:
            continue
        if other["claim_number"] != claim_number:
            continue
        other_case = db["audit_cases"].get(other["audit_case_id"])
        if other_case is None or other_case["payer_id"] != case["payer_id"]:
            continue
        if other_case["status"] == "CLOSED":
            continue
        o_start = parse_dt(other["service_start_date"])
        o_end = parse_dt(other["service_end_date"])
        if start < o_end and o_start < end:
            raise ApiError("ERR_DUPLICATE_CLAIM_IN_OPEN_AUDIT", 409,
                           "Claim overlaps a line in another open audit")
    line = stamp_new({
        "audit_case_id": cid,
        "claim_number": claim_number,
        "patient_account_number": pan,
        "service_start_date": fmt_dt(start),
        "service_end_date": fmt_dt(end),
        "billed_amount_cents": billed,
        "status": "UNDER_AUDIT",
        "denied_amount_cents": 0,
        "denial_category": None,
        "issue_code_id": None,
        "auto_denied": False,
    })
    db["claim_lines"][line["id"]] = line
    recompute_case_totals(case)
    touch(case)
    return ok_object(line_view(line), 201)


@app.route("/audit-cases/<cid>/claim-lines", methods=["GET"])
def list_case_claim_lines(cid):
    auth(None)
    case = get_case(cid)
    limit, offset = pagination_params()
    items = case_lines(case["id"])
    page, total = paged(items, limit, offset)
    return ok_list([line_view(l) for l in page], total, limit, offset)


@app.route("/claim-lines/<lid>", methods=["GET"])
def get_claim_line(lid):
    auth(None)
    return ok_object(line_view(get_line(lid)))


@app.route("/claim-lines", methods=["GET"])
def list_claim_lines():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["claim_lines"].values())
    for param in ("audit_case_id", "issue_code_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([line_view(l) for l in page], total, limit, offset)


@app.route("/audit-cases/<cid>/records-submissions", methods=["POST"])
def records_submission(cid):
    user_id, role = auth({"HIMCoordinator"})
    data = body_json()
    require_fields(data, ["manifest_ref", "expected_audit_case_version"])
    manifest_ref = req_str(data, "manifest_ref")
    expected = data.get("expected_audit_case_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_audit_case_version must be an integer")
    case = get_case(cid)
    # State guard (tier 6) then OCC
    if case["status"] in ("UNDER_PAYER_REVIEW", "DETERMINATION_ISSUED", "CLOSED"):
        raise err_state("Records submission not allowed in current state")
    if expected != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_audit_case_version does not match current version")
    now = clock_now()
    if case["status"] == "RECEIVED":
        if now > parse_dt(case["records_due_at"]):
            # Should have been swept; treat as missed path defensively
            case["status"] = "MISSED_DEADLINE"
        else:
            case["status"] = "RECORDS_SUBMITTED"
            case["records_submitted_at"] = fmt_dt(now)
            touch(case)
            append_event(case["id"], "RECORDS_SUBMITTED", role, user_id,
                         {"manifest_ref": manifest_ref, "late_submission": False})
            return ok_object(case_view(case))
    if case["status"] == "MISSED_DEADLINE":
        case["status"] = "RECORDS_SUBMITTED"
        case["records_submitted_at"] = fmt_dt(now)
        case["late_submission"] = True
        for line in case_lines(case["id"]):
            if line["auto_denied"]:
                line["status"] = "UNDER_AUDIT"
                line["denied_amount_cents"] = 0
                line["denial_category"] = None
                line["issue_code_id"] = None
                line["auto_denied"] = False
                touch(line)
        recompute_case_totals(case)
        touch(case)
        append_event(case["id"], "RECORDS_SUBMITTED", role, user_id,
                     {"manifest_ref": manifest_ref, "late_submission": True})
        return ok_object(case_view(case))
    # RECORDS_SUBMITTED amendment
    touch(case)
    return ok_object(case_view(case))


@app.route("/audit-cases/<cid>/begin-payer-review", methods=["POST"])
def begin_payer_review(cid):
    user_id, role = auth({"PayerAgent"})
    case = get_case(cid)
    if user_id != case["payer_id"]:
        raise ApiError("ERR_PAYER_MISMATCH", 403,
                       "X-User-ID must equal the case's payer_id")
    if case["status"] != "RECORDS_SUBMITTED":
        raise err_state("Case is not in RECORDS_SUBMITTED")
    case["status"] = "UNDER_PAYER_REVIEW"
    touch(case)
    append_event(case["id"], "REVIEW_BEGAN", role, user_id, {})
    return ok_object(case_view(case))


@app.route("/audit-cases/<cid>/determination", methods=["POST"])
def post_determination(cid):
    user_id, role = auth({"PayerAgent"})
    data = body_json()
    require_fields(data, ["outcomes"])
    outcomes = data.get("outcomes")
    if not isinstance(outcomes, list):
        raise err_invalid_request("outcomes must be a list")
    case = get_case(cid)
    if user_id != case["payer_id"]:
        raise ApiError("ERR_PAYER_MISMATCH", 403,
                       "X-User-ID must equal the case's payer_id")
    if case["status"] != "UNDER_PAYER_REVIEW":
        raise err_state("Case is not in UNDER_PAYER_REVIEW")
    # Content checks (tier 9): belonging, coverage, amounts
    under_audit = [l for l in case_lines(cid) if l["status"] == "UNDER_AUDIT"]
    under_ids = {l["id"] for l in under_audit}
    seen = []
    for o in outcomes:
        if not isinstance(o, dict):
            raise err_invalid_request("each outcome must be an object")
        clid = o.get("claim_line_id")
        if not isinstance(clid, str):
            raise err_invalid_request("claim_line_id is required")
        if clid not in {l["id"] for l in case_lines(cid)}:
            raise ApiError("ERR_DETERMINATION_LINE_INVALID", 422,
                           "claim_line_id does not belong to this case")
        seen.append(clid)
    if sorted(seen) != sorted(under_ids) or len(seen) != len(set(seen)):
        raise ApiError("ERR_DETERMINATION_INCOMPLETE", 422,
                       "outcomes must cover every UNDER_AUDIT line exactly once")
    # Validate amounts before mutating anything (atomicity)
    for o in outcomes:
        outcome = o.get("outcome")
        if outcome not in ("PAID_AS_BILLED", "DENIED", "PARTIALLY_DENIED"):
            raise err_invalid_request("invalid outcome")
        line = db["claim_lines"][o["claim_line_id"]]
        billed = line["billed_amount_cents"]
        if outcome == "PAID_AS_BILLED":
            continue
        denied = o.get("denied_amount_cents")
        if isinstance(denied, bool) or not isinstance(denied, int):
            raise err_invalid_request("denied_amount_cents must be an integer")
        category = o.get("denial_category")
        if category not in ISSUE_CATEGORIES:
            raise err_invalid_request("denial_category must be CLINICAL or TECHNICAL")
        issue_code_id = o.get("issue_code_id")
        if issue_code_id is not None and issue_code_id not in db["issue_codes"]:
            raise err_not_found("issue_code_id not found")
        if outcome == "DENIED" and denied != billed:
            raise ApiError("ERR_DETERMINATION_AMOUNT_INVALID", 422,
                           "DENIED outcome must deny exactly the billed amount")
        if outcome == "PARTIALLY_DENIED" and not (0 < denied < billed):
            raise ApiError("ERR_DETERMINATION_AMOUNT_INVALID", 422,
                           "PARTIALLY_DENIED amount must be strictly between 0 and billed")
    for o in outcomes:
        line = db["claim_lines"][o["claim_line_id"]]
        outcome = o["outcome"]
        if outcome == "PAID_AS_BILLED":
            line["status"] = "PAID_AS_BILLED"
            line["denied_amount_cents"] = 0
        else:
            line["status"] = outcome
            line["denied_amount_cents"] = o["denied_amount_cents"]
            line["denial_category"] = o["denial_category"]
            line["issue_code_id"] = o.get("issue_code_id")
        touch(line)
    case["determination_issued_at"] = fmt_dt(clock_now())
    case["status"] = "DETERMINATION_ISSUED"
    recompute_case_totals(case)
    touch(case)
    append_event(case["id"], "DETERMINATION_ISSUED", role, user_id,
                 {"outcome_count": len(outcomes),
                  "total_denied_active_cents": case["total_denied_active_cents"]})
    return ok_object(case_view(case))


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------
def prior_quarter_bounds(now):
    """(start, end) datetimes of the prior completed calendar quarter."""
    q_start_month = ((now.month - 1) // 3) * 3 + 1
    q_start = datetime(now.year, q_start_month, 1, tzinfo=timezone.utc)
    # prior quarter end = this quarter start; prior quarter start = 3 months earlier
    end = q_start
    m = q_start_month - 3
    y = now.year
    if m <= 0:
        m += 12
        y -= 1
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    return start, end


def dollar_weighted_rate(payer_id, issue_code_id, window_start, window_end):
    """Frozen snapshot success rate (bp) for (payer, issue) over decided appeals
    in the prior completed quarter. None when the group has no decisions."""
    num = 0
    den = 0
    for a in db["appeals"].values():
        if a["status"] not in DECIDED_STATES or a["decided_at"] is None:
            continue
        line = db["claim_lines"].get(a["audit_claim_line_id"])
        if line is None:
            continue
        case = db["audit_cases"].get(a["audit_case_id"])
        if case is None or case["payer_id"] != payer_id:
            continue
        if line["issue_code_id"] != issue_code_id:
            continue
        decided = parse_dt(a["decided_at"])
        if not (window_start <= decided < window_end):
            continue
        num += a["appealed_denied_cents"] - (a["upheld_cents"] or 0)
        den += a["appealed_denied_cents"]
    if den == 0:
        return None
    return round_half_up(10000 * num, den)


@app.route("/audit-cases/<cid>/exposure", methods=["GET"])
def case_exposure(cid):
    auth(None)
    case = get_case(cid)
    payer = db["payers"].get(case["payer_id"])
    now = clock_now()
    q_start, q_end = prior_quarter_bounds(now)
    gross = 0
    net = 0
    rate_cache = {}
    for line in case_lines(cid):
        if line["status"] in ("DENIED", "PARTIALLY_DENIED", "FINAL"):
            at_risk = line["denied_amount_cents"]
        elif line["status"] == "UNDER_AUDIT" and case["late_submission"]:
            at_risk = line["billed_amount_cents"]
        else:
            at_risk = 0
        gross += at_risk
        iid = line["issue_code_id"]
        if iid is None:
            bp = DEFAULT_OVERTURN_BP
        else:
            if iid not in rate_cache:
                rate_cache[iid] = dollar_weighted_rate(
                    case["payer_id"], iid, q_start, q_end)
            bp = rate_cache[iid]
            if bp is None:
                bp = DEFAULT_OVERTURN_BP
        net += round_half_up(at_risk * (10000 - bp), 10000)
    return ok_object({
        "gross_dollars_at_risk_cents": gross,
        "net_exposure_cents": net,
        "late_submission": case["late_submission"],
        "snapshot_quarter_start": fmt_dt(q_start),
    })


@app.route("/audit-cases/<cid>/close", methods=["POST"])
def close_case(cid):
    user_id, role = auth({"DepartmentDirector", "HIMCoordinator"})
    case = get_case(cid)
    if case["status"] != "DETERMINATION_ISSUED":
        raise err_state("Case is not in DETERMINATION_ISSUED")
    now = clock_now()
    lines = case_lines(cid)
    if any(l["status"] not in LINE_TERMINAL for l in lines):
        raise ApiError("ERR_OPEN_APPEALS_EXIST", 409,
                       "Case has claim lines not in a terminal state")
    for a in case_appeals(cid):
        if a["status"] == "PENDING_DECISION":
            raise ApiError("ERR_OPEN_APPEALS_EXIST", 409,
                           "Case has appeals in PENDING_DECISION")
        if a["status"] == "DRAFT" and parse_dt(a["filed_deadline_at"]) >= now:
            raise ApiError("ERR_OPEN_APPEALS_EXIST", 409,
                           "Case has an open DRAFT appeal")
    for d in case_demands(cid):
        if d["status"] not in ("FULLY_RECOUPED", "REVERSED", "WRITTEN_OFF"):
            raise ApiError("ERR_OPEN_APPEALS_EXIST", 409,
                           "Case has unsettled recoupment demands")
    # Director authority gradient (tier 7)
    exposure = case_exposure_compute(case)
    if exposure >= DIRECTOR_CLOSE_THRESHOLD_CENTS and role != "DepartmentDirector":
        raise ApiError("ERR_REQUIRES_DIRECTOR", 403,
                       "net_exposure at or above threshold requires DepartmentDirector")
    case["status"] = "CLOSED"
    case["closed_at"] = fmt_dt(now)
    touch(case)
    append_event(case["id"], "CASE_CLOSED", role, user_id, {})
    return ok_object(case_view(case))


def case_exposure_compute(case):
    now = clock_now()
    q_start, q_end = prior_quarter_bounds(now)
    net = 0
    rate_cache = {}
    for line in case_lines(case["id"]):
        if line["status"] in ("DENIED", "PARTIALLY_DENIED", "FINAL"):
            at_risk = line["denied_amount_cents"]
        elif line["status"] == "UNDER_AUDIT" and case["late_submission"]:
            at_risk = line["billed_amount_cents"]
        else:
            at_risk = 0
        iid = line["issue_code_id"]
        if iid is None:
            bp = DEFAULT_OVERTURN_BP
        else:
            if iid not in rate_cache:
                rate_cache[iid] = dollar_weighted_rate(
                    case["payer_id"], iid, q_start, q_end)
            bp = rate_cache[iid] if rate_cache[iid] is not None else DEFAULT_OVERTURN_BP
        net += round_half_up(at_risk * (10000 - bp), 10000)
    return net


@app.route("/audit-cases/<cid>/events", methods=["GET"])
def list_case_events(cid):
    auth(None)
    case = get_case(cid)
    limit, offset = pagination_params()
    items = [e for e in db["audit_case_events"].values()
             if e["audit_case_id"] == cid]
    page, total = paged(items, limit, offset)
    return ok_list([event_view(e) for e in page], total, limit, offset)


# ===========================================================================
# Appeals
# ===========================================================================
@app.route("/claim-lines/<lid>/appeals", methods=["POST"])
def create_appeal(lid):
    auth({"AppealsSpecialist"})
    data = body_json()
    notes = opt_str(data, "notes")
    line = get_line(lid)
    case = get_case(line["audit_case_id"])
    payer = db["payers"][case["payer_id"]]
    # Tier 6 state gate: line appealable + no open appeal on the line
    if line["status"] not in ("DENIED", "PARTIALLY_DENIED"):
        raise ApiError("ERR_LINE_NOT_APPEALABLE", 409,
                       "Claim line is not in DENIED or PARTIALLY_DENIED")
    existing = line_appeals(lid)
    if any(a["status"] in ("DRAFT", "PENDING_DECISION") for a in existing):
        raise ApiError("ERR_LINE_NOT_APPEALABLE", 409,
                       "Another appeal of this line is in DRAFT or PENDING_DECISION")
    # Tier 9: level availability
    decided = [a for a in existing if a["status"] in DECIDED_STATES]
    track = payer["appeal_track"]
    if not decided:
        level = "LEVEL_1"
        prior = None
        base = parse_dt(case["determination_issued_at"])
        deadline = base + timedelta(days=payer["l1_deadline_days"])
    else:
        prior = max(decided,
                    key=lambda a: (level_num(a["level"]), parse_dt(a["decided_at"])))
        nxt = level_num(prior["level"]) + 1
        if nxt > TRACK_MAX_LEVEL[track]:
            raise ApiError("ERR_APPEAL_LEVEL_NOT_AVAILABLE", 409,
                           "Next appeal level exceeds the payer track maximum")
        level = f"LEVEL_{nxt}"
        base = parse_dt(prior["decided_at"])
        if nxt == 2:
            days = payer["l2_deadline_days"]
        elif nxt == 3:
            days = (payer["l3_deadline_days"] if track == "MEDICARE"
                    else payer["external_review_deadline_days"])
        elif nxt == 4:
            days = payer["l4_deadline_days"]
        else:
            days = payer["l5_deadline_days"]
        deadline = base + timedelta(days=days)
    appeal = stamp_new({
        "audit_claim_line_id": lid,
        "audit_case_id": case["id"],
        "prior_appeal_id": prior["id"] if prior else None,
        "level": level,
        "level_label": level_label(track, level),
        "filed_deadline_at": fmt_dt(deadline),
        "appealed_denied_cents": line["denied_amount_cents"],
        "status": "DRAFT",
        "filed_at": None,
        "decided_at": None,
        "upheld_cents": None,
        "notes": notes,
    })
    db["appeals"][appeal["id"]] = appeal
    return ok_object(appeal_view(appeal), 201)


@app.route("/claim-lines/<lid>/appeals", methods=["GET"])
def list_line_appeals(lid):
    auth(None)
    line = get_line(lid)
    limit, offset = pagination_params()
    items = line_appeals(line["id"])
    page, total = paged(items, limit, offset)
    return ok_list([appeal_view(a) for a in page], total, limit, offset)


@app.route("/appeals", methods=["GET"])
def list_appeals():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["appeals"].values())
    for param in ("audit_case_id", "claim_line_id", "prior_appeal_id",
                  "status", "level"):
        v = request.args.get(param)
        if v is not None:
            key = "audit_claim_line_id" if param == "claim_line_id" else param
            items = [a for a in items if a[key] == v]
    page, total = paged(items, limit, offset)
    return ok_list([appeal_view(a) for a in page], total, limit, offset)


@app.route("/appeals/<aid>", methods=["GET"])
def get_appeal_route(aid):
    auth(None)
    return ok_object(appeal_view(get_appeal(aid)))


@app.route("/appeals/<aid>/file", methods=["POST"])
def file_appeal(aid):
    user_id, role = auth({"AppealsSpecialist"})
    appeal = get_appeal(aid)
    if appeal["status"] != "DRAFT":
        raise err_state("Appeal is not in DRAFT")
    now = clock_now()
    case = db["audit_cases"][appeal["audit_case_id"]]
    payer = db["payers"][case["payer_id"]]
    if now > parse_dt(appeal["filed_deadline_at"]):
        # Lazy expiry: attempt rejects AND moves the appeal to EXPIRED
        appeal["status"] = "EXPIRED"
        touch(appeal)
        raise ApiError("ERR_APPEAL_DEADLINE_PASSED", 409,
                       "Filing deadline has passed")
    if appeal["level"] == "LEVEL_3":
        packet = next((p for p in db["evidence_packets"].values()
                       if p["appeal_id"] == aid), None)
        if packet is None or packet["status"] not in ("READY", "SUBMITTED"):
            raise ApiError("ERR_EVIDENCE_PACKET_NOT_READY", 409,
                           "LEVEL_3 filing requires a READY or SUBMITTED packet")
    appeal["status"] = "PENDING_DECISION"
    appeal["filed_at"] = fmt_dt(now)
    touch(appeal)
    # Recoupment hold side effect
    if appeal["level"] in payer["hold_levels"]:
        for d in case_demands(case["id"]):
            if d["status"] in ("DEMANDED", "PARTIALLY_RECOUPED"):
                d["status"] = "ON_HOLD"
                d["hold_started_at"] = fmt_dt(now)
                touch(d)
    return ok_object(appeal_view(appeal))


@app.route("/appeals/<aid>/withdraw", methods=["POST"])
def withdraw_appeal(aid):
    auth({"AppealsSpecialist"})
    appeal = get_appeal(aid)
    if appeal["status"] not in ("DRAFT", "PENDING_DECISION"):
        raise err_state("Appeal cannot be withdrawn from its current state")
    was_pending = appeal["status"] == "PENDING_DECISION"
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    if was_pending:
        release_holds(appeal["audit_case_id"])
    return ok_object(appeal_view(appeal))


@app.route("/appeals/<aid>/decision", methods=["POST"])
def decide_appeal(aid):
    user_id, role = auth({"PayerAgent"})
    data = body_json()
    require_fields(data, ["outcome", "upheld_cents"])
    outcome = data.get("outcome")
    if outcome not in ("FAVORABLE", "PARTIAL", "UNFAVORABLE"):
        raise err_invalid_request("invalid outcome")
    upheld = data.get("upheld_cents")
    if isinstance(upheld, bool) or not isinstance(upheld, int) or upheld < 0:
        raise err_invalid_request("upheld_cents must be a non-negative integer")
    appeal = get_appeal(aid)
    case = db["audit_cases"][appeal["audit_case_id"]]
    if user_id != case["payer_id"]:
        raise ApiError("ERR_PAYER_MISMATCH", 403,
                       "X-User-ID must equal the appeal case's payer_id")
    if appeal["status"] != "PENDING_DECISION":
        raise err_state("Appeal is not in PENDING_DECISION")
    appealed = appeal["appealed_denied_cents"]
    if outcome == "FAVORABLE" and upheld != 0:
        raise ApiError("ERR_DETERMINATION_AMOUNT_INVALID", 422,
                       "FAVORABLE requires upheld_cents == 0")
    if outcome == "PARTIAL" and not (0 < upheld < appealed):
        raise ApiError("ERR_DETERMINATION_AMOUNT_INVALID", 422,
                       "PARTIAL requires 0 < upheld_cents < appealed_denied_cents")
    if outcome == "UNFAVORABLE" and upheld != appealed:
        raise ApiError("ERR_DETERMINATION_AMOUNT_INVALID", 422,
                       "UNFAVORABLE requires upheld_cents == appealed_denied_cents")
    line = db["claim_lines"][appeal["audit_claim_line_id"]]
    now = clock_now()
    appeal["decided_at"] = fmt_dt(now)
    appeal["upheld_cents"] = upheld
    if outcome == "FAVORABLE":
        appeal["status"] = "DECIDED_FAVORABLE"
        case["total_overturned_cents"] += line["denied_amount_cents"]
        line["denied_amount_cents"] = 0
        line["status"] = "OVERTURNED"
    elif outcome == "PARTIAL":
        appeal["status"] = "DECIDED_PARTIAL"
        case["total_overturned_cents"] += line["denied_amount_cents"] - upheld
        line["denied_amount_cents"] = upheld
        # line remains DENIED / PARTIALLY_DENIED
    else:
        appeal["status"] = "DECIDED_UNFAVORABLE"
    touch(appeal)
    touch(line)
    recompute_case_totals(case)
    touch(case)
    release_holds(case["id"])
    full_vindication_check(case)
    return ok_object(appeal_view(appeal))


# ===========================================================================
# Evidence packets & items
# ===========================================================================
def packet_readiness(packet):
    items = [i for i in db["packet_items"].values()
             if i["evidence_packet_id"] == packet["id"]]
    if packet["status"] == "SUBMITTED":
        return
    ready = all(i["status"] in ("ATTACHED", "WAIVED")
                for i in items if i["required"])
    new_status = "READY" if ready else "ASSEMBLING"
    if packet["status"] != new_status:
        packet["status"] = new_status
        touch(packet)


@app.route("/appeals/<aid>/evidence-packet", methods=["POST"])
def create_packet(aid):
    auth({"AppealsSpecialist"})
    appeal = get_appeal(aid)
    if any(p["appeal_id"] == aid for p in db["evidence_packets"].values()):
        raise ApiError("ERR_PACKET_ALREADY_EXISTS", 409,
                       "Appeal already has an evidence packet")
    packet = stamp_new({
        "appeal_id": aid,
        "status": "ASSEMBLING",
        "submitted_at": None,
    })
    db["evidence_packets"][packet["id"]] = packet
    packet_readiness(packet)
    return ok_object(packet_view(packet), 201)


@app.route("/appeals/<aid>/evidence-packet", methods=["GET"])
def get_appeal_packet(aid):
    auth(None)
    appeal = get_appeal(aid)
    packets = [p for p in db["evidence_packets"].values() if p["appeal_id"] == aid]
    limit, offset = pagination_params()
    page, total = paged(packets, limit, offset)
    return ok_list([packet_view(p) for p in page], total, limit, offset)


@app.route("/evidence-packets/<pid>", methods=["GET"])
def get_packet_route(pid):
    auth(None)
    return ok_object(packet_view(get_packet(pid)))


@app.route("/evidence-packets/<pid>/items", methods=["POST"])
def create_item(pid):
    auth({"AppealsSpecialist"})
    data = body_json()
    require_fields(data, ["item_type"])
    item_type = req_enum(data, "item_type", ITEM_TYPES)
    required = data.get("required", True)
    if not isinstance(required, bool):
        raise err_invalid_request("required must be a boolean")
    packet = get_packet(pid)
    if packet["status"] == "SUBMITTED":
        raise ApiError("ERR_PACKET_IMMUTABLE", 409, "Packet is SUBMITTED")
    item = stamp_new({
        "evidence_packet_id": pid,
        "item_type": item_type,
        "required": required,
        "status": "PENDING",
        "document_ref": None,
    })
    db["packet_items"][item["id"]] = item
    packet_readiness(packet)
    return ok_object(item_view(item), 201)


@app.route("/evidence-packets/<pid>/items", methods=["GET"])
def list_items(pid):
    auth(None)
    packet = get_packet(pid)
    limit, offset = pagination_params()
    items = [i for i in db["packet_items"].values()
             if i["evidence_packet_id"] == pid]
    page, total = paged(items, limit, offset)
    return ok_list([item_view(i) for i in page], total, limit, offset)


def _item_mutation(pid, item_id, roles):
    user_id, role = auth(roles)
    packet = get_packet(pid)
    item = db["packet_items"].get(item_id)
    if item is None or item["evidence_packet_id"] != pid:
        raise err_not_found("Packet item not found")
    if packet["status"] == "SUBMITTED":
        raise ApiError("ERR_PACKET_IMMUTABLE", 409, "Packet is SUBMITTED")
    return user_id, role, packet, item


@app.route("/evidence-packets/<pid>/items/<item_id>/attach", methods=["POST"])
def attach_item(pid, item_id):
    data = body_json()
    require_fields(data, ["document_ref"])
    document_ref = req_str(data, "document_ref")
    _, _, packet, item = _item_mutation(pid, item_id, {"AppealsSpecialist"})
    if item["status"] != "PENDING":
        raise err_state("Item is not PENDING")
    item["status"] = "ATTACHED"
    item["document_ref"] = document_ref
    touch(item)
    packet_readiness(packet)
    return ok_object(item_view(item))


@app.route("/evidence-packets/<pid>/items/<item_id>/waive", methods=["POST"])
def waive_item(pid, item_id):
    _, _, packet, item = _item_mutation(pid, item_id, {"DepartmentDirector"})
    if item["status"] != "PENDING":
        raise err_state("Item is not PENDING")
    item["status"] = "WAIVED"
    touch(item)
    packet_readiness(packet)
    return ok_object(item_view(item))


@app.route("/evidence-packets/<pid>/items/<item_id>/detach", methods=["POST"])
def detach_item(pid, item_id):
    _, _, packet, item = _item_mutation(pid, item_id, {"AppealsSpecialist"})
    if item["status"] != "ATTACHED":
        raise err_state("Item is not ATTACHED")
    item["status"] = "PENDING"
    item["document_ref"] = None
    touch(item)
    packet_readiness(packet)
    return ok_object(item_view(item))


@app.route("/evidence-packets/<pid>/submit", methods=["POST"])
def submit_packet(pid):
    auth({"AppealsSpecialist"})
    packet = get_packet(pid)
    appeal = db["appeals"].get(packet["appeal_id"])
    if appeal is None or appeal["status"] not in ("DRAFT", "PENDING_DECISION"):
        raise err_state("Owning appeal must be in DRAFT or PENDING_DECISION")
    if packet["status"] != "READY":
        raise err_state("Packet is not READY")
    packet["status"] = "SUBMITTED"
    packet["submitted_at"] = fmt_dt(clock_now())
    touch(packet)
    return ok_object(packet_view(packet))


# ===========================================================================
# Recoupment demands
# ===========================================================================
@app.route("/audit-cases/<cid>/recoupment-demands", methods=["POST"])
def create_demand(cid):
    user_id, role = auth({"PayerAgent"})
    data = body_json()
    require_fields(data, ["principal_cents"])
    principal = req_int(data, "principal_cents", minimum=1)
    issued_at = opt_dt(data, "issued_at")
    case = get_case(cid)
    if user_id != case["payer_id"]:
        raise ApiError("ERR_PAYER_MISMATCH", 403,
                       "X-User-ID must equal the case's payer_id")
    payer = db["payers"][case["payer_id"]]
    if principal > case["total_denied_active_cents"]:
        raise ApiError("ERR_DEMAND_EXCEEDS_DENIED", 409,
                       "principal exceeds case total_denied_active_cents")
    demand = stamp_new({
        "audit_case_id": cid,
        "payer_id": case["payer_id"],
        "principal_cents": principal,
        "principal_at_issue_cents": principal,
        "issued_at": fmt_dt(issued_at) if issued_at else fmt_dt(clock_now()),
        "status": "DEMANDED",
        "written_off_cents": 0,
        "hold_started_at": None,
        "accumulated_hold_seconds": 0,
        "rate_bps_tier1_snapshot": payer["interest_rate_bps_tier1"],
        "rate_bps_tier2_snapshot": payer["interest_rate_bps_tier2"],
        "interest_cap_pct_snapshot": payer["interest_cap_pct"],
    })
    db["recoupment_demands"][demand["id"]] = demand
    append_event(cid, "DEMAND_CREATED", role, user_id,
                 {"recoupment_demand_id": demand["id"],
                  "principal_cents": principal})
    return ok_object(demand_view(demand), 201)


@app.route("/audit-cases/<cid>/recoupment-demands", methods=["GET"])
def list_case_demands(cid):
    auth(None)
    case = get_case(cid)
    limit, offset = pagination_params()
    page, total = paged(case_demands(cid), limit, offset)
    return ok_list([demand_view(d) for d in page], total, limit, offset)


@app.route("/recoupment-demands", methods=["GET"])
def list_demands():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["recoupment_demands"].values())
    for param in ("payer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([demand_view(d) for d in page], total, limit, offset)


@app.route("/recoupment-demands/<did>", methods=["GET"])
def get_demand_route(did):
    auth(None)
    return ok_object(demand_view(get_demand(did)))


@app.route("/recoupment-demands/<did>/adjustments", methods=["POST"])
def adjust_demand(did):
    user_id, role = auth({"PayerAgent"})
    data = body_json()
    require_fields(data, ["new_principal_cents", "expected_recoupment_demand_version"])
    new_principal = req_int(data, "new_principal_cents", minimum=1)
    expected = data.get("expected_recoupment_demand_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request(
            "expected_recoupment_demand_version must be an integer")
    demand = get_demand(did)
    if user_id != demand["payer_id"]:
        raise ApiError("ERR_PAYER_MISMATCH", 403,
                       "X-User-ID must equal the demand's payer_id")
    if demand["status"] not in ("DEMANDED", "PARTIALLY_RECOUPED"):
        raise err_state("Adjustments allowed only in DEMANDED or PARTIALLY_RECOUPED")
    if expected != demand["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_recoupment_demand_version mismatch")
    applied_principal = sum(o["principal_portion_cents"]
                            for o in demand_offsets(did, applied_only=True))
    case = db["audit_cases"][demand["audit_case_id"]]
    if new_principal < applied_principal:
        raise ApiError("ERR_DEMAND_EXCEEDS_DENIED", 409,
                       "new principal below already-applied principal")
    if new_principal > case["total_denied_active_cents"]:
        raise ApiError("ERR_DEMAND_EXCEEDS_DENIED", 409,
                       "new principal exceeds case total_denied_active_cents")
    demand["principal_cents"] = new_principal
    touch(demand)
    recompute_demand_status(demand)
    return ok_object(demand_view(demand))


@app.route("/recoupment-demands/<did>/write-off", methods=["POST"])
def write_off_demand(did):
    auth({"PFSAccountant", "DepartmentDirector"})
    demand = get_demand(did)
    if demand["status"] not in ("DEMANDED", "PARTIALLY_RECOUPED"):
        raise err_state("Write-off allowed only in DEMANDED or PARTIALLY_RECOUPED")
    for a in case_appeals(demand["audit_case_id"]):
        if a["status"] in ("DRAFT", "PENDING_DECISION"):
            raise ApiError("ERR_OPEN_APPEALS_EXIST", 409,
                           "Appeals of the case are still open")
    demand["written_off_cents"] = compute_outstanding(demand)
    demand["status"] = "WRITTEN_OFF"
    touch(demand)
    return ok_object(demand_view(demand))


@app.route("/recoupment-demands/<did>/offsets", methods=["POST"])
def manual_offset(did):
    user_id, role = auth({"PFSAccountant"})
    data = body_json()
    require_fields(data, ["remittance_id", "amount_cents"])
    remit_id = req_str(data, "remittance_id")
    amount = req_int(data, "amount_cents", minimum=1)
    demand = get_demand(did)
    remit = get_remittance(remit_id)
    # State tier (6): specialized ON_HOLD first, then generic
    if demand["status"] == "ON_HOLD":
        raise ApiError("ERR_DEMAND_ON_HOLD", 409, "Demand is ON_HOLD")
    if demand["status"] not in ("DEMANDED", "PARTIALLY_RECOUPED"):
        raise err_state("Demand status does not allow offsets")
    # Tier 10: cross-payer linkage
    if remit["payer_id"] != demand["payer_id"]:
        raise ApiError("ERR_CROSS_PAYER_ALLOCATION", 409,
                       "Remittance and demand belong to different payers")
    # Tier 11: money ceilings
    interest_now = compute_interest(demand)
    outstanding = compute_outstanding(demand)
    ceiling = min(compute_available(remit), outstanding + interest_now)
    if amount > ceiling:
        raise ApiError("ERR_OFFSET_EXCEEDS_OUTSTANDING", 409,
                       "amount exceeds min(remittance available, demand outstanding)")
    interest_portion = min(amount, interest_now)
    principal_portion = min(amount - interest_portion, outstanding)
    offset = stamp_new({
        "remittance_id": remit["id"],
        "recoupment_demand_id": did,
        "amount_cents": interest_portion + principal_portion,
        "interest_portion_cents": interest_portion,
        "principal_portion_cents": principal_portion,
        "allocation_mode": "MANUAL",
        "status": "APPLIED",
        "applied_at": fmt_dt(clock_now()),
        "reversed_at": None,
    })
    db["offset_transactions"][offset["id"]] = offset
    recompute_demand_status(demand)
    touch(demand)
    recompute_remittance_status(remit)
    touch(remit)
    append_event(demand["audit_case_id"], "OFFSET_APPLIED", role, user_id,
                 {"offset_transaction_id": offset["id"],
                  "recoupment_demand_id": did,
                  "remittance_id": remit["id"],
                  "amount_cents": offset["amount_cents"]})
    return ok_object(offset_view(offset), 201)


# ===========================================================================
# Remittances / offsets
# ===========================================================================
@app.route("/remittances", methods=["POST"])
def create_remittance():
    user_id, role = auth({"PayerAgent"})
    data = body_json()
    require_fields(data, ["payer_id", "gross_amount_cents"])
    payer_id = req_str(data, "payer_id")
    gross = req_int(data, "gross_amount_cents", minimum=1)
    external_ref = opt_str(data, "external_ref")
    payer = get_payer(payer_id)
    if user_id != payer_id:
        raise ApiError("ERR_PAYER_MISMATCH", 403,
                       "X-User-ID must equal the remittance payer_id")
    remit = stamp_new({
        "payer_id": payer_id,
        "gross_amount_cents": gross,
        "external_ref": external_ref,
        "status": "RECEIVED",
    })
    db["remittances"][remit["id"]] = remit
    return ok_object(remittance_view(remit), 201)


@app.route("/remittances", methods=["GET"])
def list_remittances():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["remittances"].values())
    for param in ("payer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([remittance_view(r) for r in page], total, limit, offset)


@app.route("/remittances/<rid>", methods=["GET"])
def get_remittance_route(rid):
    auth(None)
    return ok_object(remittance_view(get_remittance(rid)))


@app.route("/remittances/<rid>/allocate", methods=["POST"])
def allocate_remittance(rid):
    user_id, role = auth({"PFSAccountant"})
    remit = get_remittance(rid)
    candidates = [d for d in db["recoupment_demands"].values()
                  if d["payer_id"] == remit["payer_id"]
                  and d["status"] in ("DEMANDED", "PARTIALLY_RECOUPED")]
    candidates.sort(key=lambda d: (d["issued_at"], d["created_at"], d["_seq"]))
    remaining = compute_available(remit)
    created = []
    for d in candidates:
        if remaining <= 0:
            break
        interest_now = compute_interest(d)  # rounded per demand
        interest_portion = min(remaining, interest_now)
        principal_portion = min(remaining - interest_portion,
                                compute_outstanding(d))
        applied = interest_portion + principal_portion
        if applied <= 0:
            continue
        offset = stamp_new({
            "remittance_id": rid,
            "recoupment_demand_id": d["id"],
            "amount_cents": applied,
            "interest_portion_cents": interest_portion,
            "principal_portion_cents": principal_portion,
            "allocation_mode": "AUTO_WATERFALL",
            "status": "APPLIED",
            "applied_at": fmt_dt(clock_now()),
            "reversed_at": None,
        })
        db["offset_transactions"][offset["id"]] = offset
        created.append(offset)
        remaining -= applied
        recompute_demand_status(d)
        touch(d)
        append_event(d["audit_case_id"], "OFFSET_APPLIED", role, user_id,
                     {"offset_transaction_id": offset["id"],
                      "recoupment_demand_id": d["id"],
                      "remittance_id": rid,
                      "amount_cents": applied})
    recompute_remittance_status(remit)
    touch(remit)
    return ok_list([offset_view(o) for o in created], len(created),
                   max(len(created), 1), 0, code=201)


@app.route("/remittances/<rid>/offset-transactions", methods=["GET"])
def list_remit_offsets(rid):
    auth(None)
    remit = get_remittance(rid)
    limit, offset = pagination_params()
    page, total = paged(remittance_offsets(rid), limit, offset)
    return ok_list([offset_view(o) for o in page], total, limit, offset)


@app.route("/recoupment-demands/<did>/offset-transactions", methods=["GET"])
def list_demand_offsets(did):
    auth(None)
    demand = get_demand(did)
    limit, offset = pagination_params()
    page, total = paged(demand_offsets(did), limit, offset)
    return ok_list([offset_view(o) for o in page], total, limit, offset)


@app.route("/offset-transactions/<oid>/reverse", methods=["POST"])
def reverse_offset(oid):
    user_id, role = auth({"PFSAccountant"})
    offset = get_offset(oid)
    if offset["status"] != "APPLIED":
        raise err_state("Offset is not APPLIED")
    offset["status"] = "REVERSED"
    offset["reversed_at"] = fmt_dt(clock_now())
    touch(offset)
    demand = db["recoupment_demands"][offset["recoupment_demand_id"]]
    recompute_demand_status(demand)
    touch(demand)
    remit = db["remittances"][offset["remittance_id"]]
    recompute_remittance_status(remit)
    touch(remit)
    append_event(demand["audit_case_id"], "OFFSET_REVERSED", role, user_id,
                 {"offset_transaction_id": oid,
                  "recoupment_demand_id": demand["id"],
                  "remittance_id": remit["id"]})
    return ok_object(offset_view(offset))


# ===========================================================================
# Corrective action plans
# ===========================================================================
@app.route("/corrective-action-plans", methods=["POST"])
def create_cap():
    user_id, role = auth({"ComplianceOfficer"})
    data = body_json()
    require_fields(data, ["payer_id", "issue_code_id", "title", "root_cause"])
    payer_id = req_str(data, "payer_id")
    issue_code_id = req_str(data, "issue_code_id")
    title = req_str(data, "title")
    root_cause = req_str(data, "root_cause")
    get_payer(payer_id)
    if issue_code_id not in db["issue_codes"]:
        raise err_not_found("Issue code not found")
    cap = stamp_new({
        "payer_id": payer_id,
        "issue_code_id": issue_code_id,
        "title": title,
        "root_cause": root_cause,
        "status": "PROPOSED",
        "proposed_by_user_id": user_id,
        "verified_by_user_id": None,
        "check_started_at": None,
        "cycle_count": 0,
    })
    db["corrective_action_plans"][cap["id"]] = cap
    return ok_object(cap_view(cap), 201)


@app.route("/corrective-action-plans", methods=["GET"])
def list_caps():
    auth(None)
    limit, offset = pagination_params()
    items = list(db["corrective_action_plans"].values())
    for param in ("payer_id", "issue_code_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([cap_view(c) for c in page], total, limit, offset)


@app.route("/corrective-action-plans/<cid>", methods=["GET"])
def get_cap_route(cid):
    auth(None)
    return ok_object(cap_view(get_cap(cid)))


@app.route("/corrective-action-plans/<cid>/activate", methods=["POST"])
def activate_cap(cid):
    auth({"DepartmentDirector"})
    cap = get_cap(cid)
    if cap["status"] != "PROPOSED":
        raise err_state("Plan is not PROPOSED")
    cap["status"] = "ACTIVE"
    touch(cap)
    return ok_object(cap_view(cap))


@app.route("/corrective-action-plans/<cid>/begin-effectiveness-check",
           methods=["POST"])
def begin_check_cap(cid):
    auth({"ComplianceOfficer"})
    cap = get_cap(cid)
    if cap["status"] != "ACTIVE":
        raise err_state("Plan is not ACTIVE")
    cap["status"] = "EFFECTIVENESS_CHECK"
    cap["check_started_at"] = fmt_dt(clock_now())
    touch(cap)
    return ok_object(cap_view(cap))


@app.route("/corrective-action-plans/<cid>/verify", methods=["POST"])
def verify_cap(cid):
    user_id, role = auth({"InternalAuditor"})
    cap = get_cap(cid)
    if cap["status"] != "EFFECTIVENESS_CHECK":
        raise err_state("Plan is not in EFFECTIVENESS_CHECK")
    if user_id == cap["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Verifier must differ from proposer")
    earliest = parse_dt(cap["check_started_at"]) + timedelta(
        days=CAP_EFFECTIVENESS_WINDOW_DAYS)
    if clock_now() < earliest:
        raise ApiError("ERR_CAP_WINDOW_NOT_ELAPSED", 409,
                       "Effectiveness window has not elapsed")
    cap["status"] = "VERIFIED"
    cap["verified_by_user_id"] = user_id
    touch(cap)
    return ok_object(cap_view(cap))


@app.route("/corrective-action-plans/<cid>/mark-ineffective", methods=["POST"])
def mark_ineffective_cap(cid):
    auth({"InternalAuditor"})
    cap = get_cap(cid)
    if cap["status"] != "EFFECTIVENESS_CHECK":
        raise err_state("Plan is not in EFFECTIVENESS_CHECK")
    cap["cycle_count"] += 1
    if cap["cycle_count"] >= CAP_MAX_CYCLES:
        cap["status"] = "FAILED"
    else:
        cap["status"] = "ACTIVE"
        cap["check_started_at"] = None
    touch(cap)
    return ok_object(cap_view(cap))


# ===========================================================================
# Analytics
# ===========================================================================
@app.route("/analytics/success-rates", methods=["GET"])
def success_rates():
    auth(None)
    variant = request.args.get("variant", "SIMPLE")
    if variant not in ("SIMPLE", "DOLLAR_WEIGHTED"):
        raise err_invalid_request("variant must be SIMPLE or DOLLAR_WEIGHTED")
    payer_filter = request.args.get("payer_id")
    issue_filter = request.args.get("issue_code_id")
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    try:
        from_dt = parse_dt(from_raw) if from_raw else None
        to_dt = parse_dt(to_raw) if to_raw else None
    except (ValueError, TypeError):
        raise err_invalid_request("from/to must be ISO-8601 timestamps")
    if from_dt is not None and to_dt is not None and from_dt >= to_dt:
        raise ApiError("ERR_ANALYTICS_WINDOW_INVALID", 422,
                       "from must be strictly before to")
    groups = {}
    for a in db["appeals"].values():
        if a["status"] not in DECIDED_STATES or a["decided_at"] is None:
            continue
        decided = parse_dt(a["decided_at"])
        if from_dt is not None and decided < from_dt:
            continue
        if to_dt is not None and decided >= to_dt:
            continue
        case = db["audit_cases"].get(a["audit_case_id"])
        if case is None:
            continue
        if payer_filter is not None and case["payer_id"] != payer_filter:
            continue
        line = db["claim_lines"].get(a["audit_claim_line_id"])
        issue_id = line["issue_code_id"] if line else None
        if issue_filter is not None and issue_id != issue_filter:
            continue
        key = (case["payer_id"], issue_id)
        g = groups.setdefault(key, {"favorable": 0, "partial": 0,
                                    "unfavorable": 0, "count": 0,
                                    "recovered": 0, "appealed": 0})
        g["count"] += 1
        if a["status"] == "DECIDED_FAVORABLE":
            g["favorable"] += 1
        elif a["status"] == "DECIDED_PARTIAL":
            g["partial"] += 1
        else:
            g["unfavorable"] += 1
        g["recovered"] += a["appealed_denied_cents"] - (a["upheld_cents"] or 0)
        g["appealed"] += a["appealed_denied_cents"]
    rows = []
    for (pid, iid), g in groups.items():
        if g["count"] == 0:
            continue
        if variant == "SIMPLE":
            # round_half_up(10000 * (fav + 0.5*partial) / count)
            bp = round_half_up(10000 * (2 * g["favorable"] + g["partial"]),
                               2 * g["count"])
        else:
            if g["appealed"] == 0:
                continue
            bp = round_half_up(10000 * g["recovered"], g["appealed"])
        rows.append({
            "payer_id": pid,
            "issue_code_id": iid,
            "decided_count": g["count"],
            "favorable_count": g["favorable"],
            "partial_count": g["partial"],
            "unfavorable_count": g["unfavorable"],
            "success_rate_bp": bp,
            "variant": variant,
        })
    rows.sort(key=lambda r: (r["payer_id"],
                             r["issue_code_id"] if r["issue_code_id"] else ""))
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": meta, "response_type": "object",
                    "data": {"rows": page}}), 200


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
