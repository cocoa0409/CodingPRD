"""
Cable-Broadband Franchise & PEG API — Python + Flask reference implementation.

All state is held in-memory (plain dicts keyed by id). No persistence, no
seeding: every entity is created by the test suite through the declared API.
The server maintains a logical clock (default 2026-05-01T00:00:00Z) used for
all time-gated rules; wall-clock time is used only for created_at / updated_at
and the response envelope timestamp.
"""

import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify, make_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
franchises = {}
row_segments = {}
row_permits = {}
buildout_milestones = {}
revenue_reports = {}
audits = {}
assessments = {}
complaints = {}
peg_contributions = {}
franchise_applications = {}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


# Logical clock ------------------------------------------------------------
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
clock = {}


def parse_instant(s):
    """Parse an ISO-8601 instant (date or datetime, Z or offset) -> aware UTC."""
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    if "T" not in t and len(t) == 10:
        t = t + "T00:00:00+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset_clock():
    clock["str"] = CLOCK_DEFAULT
    clock["dt"] = parse_instant(CLOCK_DEFAULT)


reset_clock()

KNOWN_ROLES = {"FranchiseAuthority", "Operator", "Resident"}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PER_HOME_DAMAGE_CENTS = 2500
DAILY_INTEREST_RATE = Decimal("0.0005")
PENALTY_CAP_CENTS = 5000000
ESCALATION_VIOLATION_THRESHOLD = 2
DEEMED_APPROVAL_DAYS = 120
PERMIT_BUFFER_HOURS = 24
SLA_HOURS = {
    "SERVICE_INTERRUPTION": 24,
    "BILLING": 72,
    "OTHER": 168,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time / rendering helpers
# ---------------------------------------------------------------------------
def now_iso():
    """Wall-clock UTC, ISO-8601 with exactly three fractional digits + Z."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def render_clock_ts(dt):
    """Render a clock-derived instant: whole seconds, or millis when nonzero."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_line(cents, rate):
    return rhu(Decimal(int(cents)) * Decimal(str(rate)))


def fee_due(res, com, adv, rate):
    return fee_line(res, rate) + fee_line(com, rate) + fee_line(adv, rate)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return make_response(jsonify(body), code)


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return make_response(jsonify(body), 200)


@app.after_request
def _no_keepalive(resp):
    resp.headers["Connection"] = "close"
    return resp


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return make_response(jsonify(body), e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return make_response(jsonify(body), 404)


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return make_response(jsonify(body), 404)


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def do_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown role.")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")


def get_body():
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        return {}
    return b


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_str(body, key, allow_empty=False):
    if key not in body or body[key] is None:
        bad(f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str):
        bad(f"Field {key} must be a string.")
    if not allow_empty and v == "":
        bad(f"Field {key} must not be empty.")
    return v


def req_int(body, key, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        bad(f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        bad(f"Field {key} must be an integer.")
    if minimum is not None and v < minimum:
        bad(f"Field {key} out of range.")
    if maximum is not None and v > maximum:
        bad(f"Field {key} out of range.")
    return v


def opt_int(body, key, default, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, minimum, maximum)


def req_num(body, key, minimum=None, maximum=None, incl_min=False, incl_max=True):
    if key not in body or body[key] is None:
        bad(f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad(f"Field {key} must be a number.")
    if minimum is not None:
        if incl_min:
            if v < minimum:
                bad(f"Field {key} out of range.")
        else:
            if v <= minimum:
                bad(f"Field {key} out of range.")
    if maximum is not None:
        if incl_max:
            if v > maximum:
                bad(f"Field {key} out of range.")
        else:
            if v >= maximum:
                bad(f"Field {key} out of range.")
    return v


def req_enum(body, key, choices):
    v = req_str(body, key)
    if v not in choices:
        bad(f"Field {key} must be one of {sorted(choices)}.")
    return v


def req_dt_str(body, key):
    """A required datetime/date field: keep verbatim, ensure parseable."""
    v = req_str(body, key)
    try:
        parse_instant(v)
    except Exception:
        bad(f"Field {key} is not a valid ISO-8601 instant.")
    return v


def get_or_404(store, _id):
    if _id is None or _id not in store:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
    return store[_id]


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def paginate(items):
    """items: already sorted list. Returns (page, limit, offset, total)."""
    total = len(items)
    limit = 10
    offset = 0
    ql = request.args.get("limit")
    qo = request.args.get("offset")
    if ql is not None:
        try:
            limit = int(ql)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if qo is not None:
        try:
            offset = int(qo)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return items[offset:offset + limit], limit, offset, total


def sorted_by_seq(values):
    return sorted(values, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Computed aggregates
# ---------------------------------------------------------------------------
def assessment_total(a):
    return a["principal_cents"] + a["interest_cents"] + a["penalty_cents"]


def compute_total_owed(fid):
    owed = 0
    for r in revenue_reports.values():
        if r["franchise_id"] == fid and r["status"] == "ACCEPTED":
            owed += r["fee_due_cents"] - r["amount_paid_cents"]
    for a in assessments.values():
        aud = audits.get(a["audit_id"])
        if aud is None:
            continue
        if aud["franchise_id"] == fid and a["status"] in ("ISSUED", "DISPUTED"):
            owed += assessment_total(a) - a["amount_paid_cents"]
    return owed


def compute_peg_credit(fid):
    return sum(c["amount_cents"] for c in peg_contributions.values()
               if c["franchise_id"] == fid and c["status"] == "RECORDED")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_franchise(f):
    return {
        "id": f["id"],
        "operator_name": f["operator_name"],
        "territory_name": f["territory_name"],
        "homes_in_territory": f["homes_in_territory"],
        "road_miles": f["road_miles"],
        "fee_rate_pct": f["fee_rate_pct"],
        "peg_fee_per_sub_cents": f["peg_fee_per_sub_cents"],
        "term_start_date": f["term_start_date"],
        "term_end_date": f["term_end_date"],
        "lifecycle_status": f["lifecycle_status"],
        "compliance_status": f["compliance_status"],
        "unresolved_complaint_count": f["unresolved_complaint_count"],
        "homes_passed": f["homes_passed"],
        "total_owed_cents": compute_total_owed(f["id"]),
        "peg_credit_cents": compute_peg_credit(f["id"]),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_segment(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "length_miles": s["length_miles"],
        "homes_along": s["homes_along"],
        "jurisdiction": s["jurisdiction"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "franchise_id": p["franchise_id"],
        "row_segment_id": p["row_segment_id"],
        "window_start": p["window_start"],
        "window_end": p["window_end"],
        "purpose": p["purpose"],
        "status": p["status"],
        "decided_by_user_id": p["decided_by_user_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_milestone(m):
    return {
        "id": m["id"],
        "franchise_id": m["franchise_id"],
        "label": m["label"],
        "deadline_date": m["deadline_date"],
        "required_pct": m["required_pct"],
        "required_homes": m["required_homes"],
        "homes_passed_certified": m["homes_passed_certified"],
        "status": m["status"],
        "provisional_damage_cents": m["provisional_damage_cents"],
        "final_damage_cents": m["final_damage_cents"],
        "last_certified_at": m["last_certified_at"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "franchise_id": r["franchise_id"],
        "period_start_date": r["period_start_date"],
        "period_end_date": r["period_end_date"],
        "residential_gross_cents": r["residential_gross_cents"],
        "commercial_gross_cents": r["commercial_gross_cents"],
        "advertising_gross_cents": r["advertising_gross_cents"],
        "fee_due_cents": r["fee_due_cents"],
        "amount_paid_cents": r["amount_paid_cents"],
        "status": r["status"],
        "fee_basis": r["fee_basis"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_audit(a):
    return {
        "id": a["id"],
        "franchise_id": a["franchise_id"],
        "target_report_id": a["target_report_id"],
        "period_start_date": a["period_start_date"],
        "period_end_date": a["period_end_date"],
        "audited_gross_residential_cents": a["audited_gross_residential_cents"],
        "audited_gross_commercial_cents": a["audited_gross_commercial_cents"],
        "audited_gross_advertising_cents": a["audited_gross_advertising_cents"],
        "status": a["status"],
        "finalized_by_user_id": a["finalized_by_user_id"],
        "finalized_at": a["finalized_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_assessment(a):
    return {
        "id": a["id"],
        "audit_id": a["audit_id"],
        "principal_cents": a["principal_cents"],
        "interest_cents": a["interest_cents"],
        "penalty_cents": a["penalty_cents"],
        "total_cents": assessment_total(a),
        "days_late": a["days_late"],
        "underpayment_pct": a["underpayment_pct"],
        "status": a["status"],
        "issued_by_user_id": a["issued_by_user_id"],
        "amount_paid_cents": a["amount_paid_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_complaint(c):
    return {
        "id": c["id"],
        "franchise_id": c["franchise_id"],
        "complainant_id": c["complainant_id"],
        "category": c["category"],
        "description": c["description"],
        "filed_at": c["filed_at"],
        "sla_deadline": c["sla_deadline"],
        "status": c["status"],
        "escalated_at": c["escalated_at"],
        "resolution_note": c["resolution_note"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_peg(c):
    return {
        "id": c["id"],
        "franchise_id": c["franchise_id"],
        "amount_cents": c["amount_cents"],
        "contribution_type": c["contribution_type"],
        "status": c["status"],
        "voided_reason": c["voided_reason"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "franchise_id": a["franchise_id"],
        "application_type": a["application_type"],
        "transferee_name": a["transferee_name"],
        "proposed_term_end_date": a["proposed_term_end_date"],
        "submitted_at": a["submitted_at"],
        "decision_deadline": a["decision_deadline"],
        "status": a["status"],
        "decided_by_user_id": a["decided_by_user_id"],
        "decision": a["decision"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# ---------------------------------------------------------------------------
# Cross-cutting state helpers
# ---------------------------------------------------------------------------
def flip_in_violation(fr):
    """Compliance COMPLIANT/CURED -> IN_VIOLATION cascade; holds SUBMITTED apps."""
    if fr["compliance_status"] == "IN_VIOLATION":
        return
    fr["compliance_status"] = "IN_VIOLATION"
    touch(fr)
    for a in franchise_applications.values():
        if a["franchise_id"] == fr["id"] and a["status"] == "SUBMITTED":
            a["status"] = "HELD"
            touch(a)


def apply_grant_lifecycle(appobj, fr):
    """Apply the lifecycle side-effects of an APPROVED/DEEMED_APPROVED application."""
    if appobj["application_type"] == "TRANSFER":
        fr["lifecycle_status"] = "TRANSFERRED"
        fr["operator_name"] = appobj["transferee_name"]
        touch(fr)
    else:  # RENEWAL
        fr["lifecycle_status"] = "RENEWED"
        fr["term_end_date"] = appobj["proposed_term_end_date"]
        touch(fr)


def check_owner(role, uid, franchise_id):
    """Operator ownership: X-User-ID must equal the resource's franchise_id."""
    if role == "Operator" and uid != franchise_id:
        raise ApiError("ERR_NOT_FRANCHISE_OWNER", 403,
                       "Operator does not own this franchise-scoped resource.")


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = do_auth()
    body = get_body()
    to_iso = req_dt_str(body, "to_iso8601")
    authorize(role, {"FranchiseAuthority"})
    clock["str"] = to_iso
    clock["dt"] = parse_instant(to_iso)
    return ok({"current_utc": clock["str"]}, 200)


# ===========================================================================
# Franchises
# ===========================================================================
@app.route("/franchises", methods=["POST"])
def create_franchise():
    uid, role = do_auth()
    body = get_body()
    operator_name = req_str(body, "operator_name")
    territory_name = req_str(body, "territory_name")
    homes = req_int(body, "homes_in_territory", minimum=1)
    road_miles = req_num(body, "road_miles", minimum=0, incl_min=False)
    fee_rate = req_num(body, "fee_rate_pct", minimum=0, maximum=0.05,
                       incl_min=False, incl_max=True)
    peg_fee = opt_int(body, "peg_fee_per_sub_cents", 0, minimum=0)
    term_start = req_dt_str(body, "term_start_date")
    term_end = req_dt_str(body, "term_end_date")
    if parse_instant(term_end) <= parse_instant(term_start):
        raise ApiError("ERR_VALIDATION_PERIOD_INVALID", 400,
                       "term_end_date must be after term_start_date.")
    authorize(role, {"FranchiseAuthority"})

    f = new_common()
    f.update({
        "operator_name": operator_name,
        "territory_name": territory_name,
        "homes_in_territory": homes,
        "road_miles": road_miles,
        "fee_rate_pct": fee_rate,
        "peg_fee_per_sub_cents": peg_fee,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "lifecycle_status": "DRAFT",
        "compliance_status": "COMPLIANT",
        "unresolved_complaint_count": 0,
        "homes_passed": 0,
    })
    franchises[f["id"]] = f
    return ok(ser_franchise(f), 201)


@app.route("/franchises/<fid>", methods=["GET"])
def get_franchise(fid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    f = get_or_404(franchises, fid)
    return ok(ser_franchise(f), 200)


@app.route("/franchises/<fid>/summary", methods=["GET"])
def franchise_summary(fid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    f = get_or_404(franchises, fid)
    return ok({
        "total_owed_cents": compute_total_owed(fid),
        "peg_credit_cents": compute_peg_credit(fid),
        "compliance_status": f["compliance_status"],
        "lifecycle_status": f["lifecycle_status"],
        "unresolved_complaint_count": f["unresolved_complaint_count"],
    }, 200)


@app.route("/franchises/<fid>/activate", methods=["POST"])
def activate_franchise(fid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority"})
    f = get_or_404(franchises, fid)
    if f["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Franchise is not in DRAFT.")
    f["lifecycle_status"] = "ACTIVE"
    touch(f)
    return ok(ser_franchise(f), 200)


@app.route("/franchises/<fid>/revoke", methods=["POST"])
def revoke_franchise(fid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority"})
    f = get_or_404(franchises, fid)
    if f["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Franchise is not ACTIVE.")
    f["lifecycle_status"] = "REVOKED"
    touch(f)
    return ok(ser_franchise(f), 200)


@app.route("/franchises/<fid>/cure", methods=["POST"])
def cure_franchise(fid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority"})
    f = get_or_404(franchises, fid)
    if f["compliance_status"] != "IN_VIOLATION":
        raise ApiError("ERR_INVALID_STATE", 409, "Franchise compliance is not IN_VIOLATION.")
    f["compliance_status"] = "CURED"
    f["unresolved_complaint_count"] = 0
    touch(f)
    for a in franchise_applications.values():
        if a["franchise_id"] == fid and a["status"] == "HELD":
            a["status"] = "SUBMITTED"
            touch(a)
    return ok(ser_franchise(f), 200)


# ===========================================================================
# Row segments
# ===========================================================================
@app.route("/row-segments", methods=["POST"])
def create_segment():
    uid, role = do_auth()
    body = get_body()
    name = req_str(body, "name")
    length = req_num(body, "length_miles", minimum=0, incl_min=False)
    homes_along = req_int(body, "homes_along", minimum=0)
    jurisdiction = body.get("jurisdiction")
    if jurisdiction is None:
        jurisdiction = "CITY"
    elif not isinstance(jurisdiction, str) or jurisdiction == "":
        bad("Field jurisdiction must be a non-empty string.")
    authorize(role, {"FranchiseAuthority"})

    s = new_common()
    s.update({
        "name": name,
        "length_miles": length,
        "homes_along": homes_along,
        "jurisdiction": jurisdiction,
    })
    row_segments[s["id"]] = s
    return ok(ser_segment(s), 201)


@app.route("/row-segments/<sid>", methods=["GET"])
def get_segment(sid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    s = get_or_404(row_segments, sid)
    return ok(ser_segment(s), 200)


# ===========================================================================
# Row permits
# ===========================================================================
def permit_overlaps(row_segment_id, new_start, new_end, exclude_id=None):
    buffer = timedelta(hours=PERMIT_BUFFER_HOURS)
    for p in row_permits.values():
        if p["id"] == exclude_id:
            continue
        if p["row_segment_id"] != row_segment_id:
            continue
        if p["status"] not in ("REQUESTED", "APPROVED"):
            continue
        p_start = parse_instant(p["window_start"])
        p_end = parse_instant(p["window_end"])
        clear = (new_start >= p_end + buffer) or (p_start >= new_end + buffer)
        if not clear:
            return True
    return False


@app.route("/row-permits", methods=["POST"])
def create_permit():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    row_segment_id = req_str(body, "row_segment_id")
    window_start = req_dt_str(body, "window_start")
    window_end = req_dt_str(body, "window_end")
    purpose = req_str(body, "purpose")
    if parse_instant(window_end) <= parse_instant(window_start):
        raise ApiError("ERR_VALIDATION_PERIOD_INVALID", 400,
                       "window_end must be after window_start.")
    authorize(role, {"Operator"})
    f = get_or_404(franchises, franchise_id)
    seg = get_or_404(row_segments, row_segment_id)
    check_owner(role, uid, franchise_id)
    # Domain: franchise active (priority 50), then window overlap (priority 60)
    if f["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_FRANCHISE_NOT_ACTIVE", 409, "Franchise is not ACTIVE.")
    if permit_overlaps(row_segment_id, parse_instant(window_start),
                       parse_instant(window_end)):
        raise ApiError("ERR_PERMIT_WINDOW_OVERLAP", 409,
                       "Permit window collides with an existing permit on the segment.")

    p = new_common()
    p.update({
        "franchise_id": franchise_id,
        "row_segment_id": row_segment_id,
        "window_start": window_start,
        "window_end": window_end,
        "purpose": purpose,
        "status": "REQUESTED",
        "decided_by_user_id": None,
    })
    row_permits[p["id"]] = p
    return ok(ser_permit(p), 201)


@app.route("/row-permits/<pid>", methods=["GET"])
def get_permit(pid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    p = get_or_404(row_permits, pid)
    return ok(ser_permit(p), 200)


@app.route("/row-permits", methods=["GET"])
def list_permits():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    sid = request.args.get("row_segment_id")
    items = [p for p in row_permits.values()
             if (fid is None or p["franchise_id"] == fid)
             and (sid is None or p["row_segment_id"] == sid)]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_permit(p) for p in page], limit, offset, total)


@app.route("/row-permits/<pid>/decide", methods=["POST"])
def decide_permit(pid):
    uid, role = do_auth()
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    authorize(role, {"FranchiseAuthority"})
    p = get_or_404(row_permits, pid)
    if p["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit is not REQUESTED.")
    if decision == "APPROVE":
        f = franchises.get(p["franchise_id"])
        if f is None or f["lifecycle_status"] != "ACTIVE":
            raise ApiError("ERR_FRANCHISE_NOT_ACTIVE", 409, "Franchise is not ACTIVE.")
        p["status"] = "APPROVED"
    else:
        p["status"] = "REJECTED"
    p["decided_by_user_id"] = uid
    touch(p)
    return ok(ser_permit(p), 200)


# ===========================================================================
# Build-out milestones
# ===========================================================================
@app.route("/buildout-milestones", methods=["POST"])
def create_milestone():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    label = req_str(body, "label")
    deadline = req_dt_str(body, "deadline_date")
    required_pct = req_num(body, "required_pct", minimum=0, maximum=1,
                           incl_min=False, incl_max=True)
    authorize(role, {"FranchiseAuthority"})
    f = get_or_404(franchises, franchise_id)

    required_homes = int((Decimal(str(required_pct)) * f["homes_in_territory"]).quantize(
        Decimal("1"), rounding=ROUND_CEILING))
    m = new_common()
    m.update({
        "franchise_id": franchise_id,
        "label": label,
        "deadline_date": deadline,
        "required_pct": required_pct,
        "required_homes": required_homes,
        "homes_passed_certified": 0,
        "status": "PENDING",
        "provisional_damage_cents": 0,
        "final_damage_cents": 0,
        "last_certified_at": None,
    })
    buildout_milestones[m["id"]] = m
    return ok(ser_milestone(m), 201)


@app.route("/buildout-milestones/<mid>", methods=["GET"])
def get_milestone(mid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    m = get_or_404(buildout_milestones, mid)
    return ok(ser_milestone(m), 200)


@app.route("/buildout-milestones", methods=["GET"])
def list_milestones():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    items = [m for m in buildout_milestones.values()
             if fid is None or m["franchise_id"] == fid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_milestone(m) for m in page], limit, offset, total)


@app.route("/buildout-milestones/<mid>/certify", methods=["POST"])
def certify_milestone(mid):
    uid, role = do_auth()
    body = get_body()
    homes_passed = req_int(body, "homes_passed", minimum=0)
    authorize(role, {"Operator"})
    m = get_or_404(buildout_milestones, mid)
    check_owner(role, uid, m["franchise_id"])
    if m["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Milestone is not PENDING.")

    f = franchises[m["franchise_id"]]
    homes_total = f["homes_in_territory"]
    required_homes = m["required_homes"]
    shortfall = max(0, required_homes - homes_passed)
    damage = shortfall * PER_HOME_DAMAGE_CENTS
    met = Decimal(homes_passed) >= (Decimal(str(m["required_pct"])) * homes_total)

    is_final = clock["dt"] >= parse_instant(m["deadline_date"])
    m["homes_passed_certified"] = homes_passed
    f["homes_passed"] = homes_passed
    m["last_certified_at"] = clock["str"]
    if not is_final:
        m["provisional_damage_cents"] = damage
        # status stays PENDING
    else:
        if met:
            m["status"] = "MET"
            m["final_damage_cents"] = 0
        else:
            m["status"] = "MISSED"
            m["final_damage_cents"] = damage
    touch(m)
    return ok(ser_milestone(m), 200)


# ===========================================================================
# Revenue reports
# ===========================================================================
@app.route("/revenue-reports", methods=["POST"])
def create_report():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    period_start = req_dt_str(body, "period_start_date")
    period_end = req_dt_str(body, "period_end_date")
    res = req_int(body, "residential_gross_cents", minimum=0)
    com = req_int(body, "commercial_gross_cents", minimum=0)
    adv = req_int(body, "advertising_gross_cents", minimum=0)
    if parse_instant(period_end) <= parse_instant(period_start):
        raise ApiError("ERR_VALIDATION_PERIOD_INVALID", 400,
                       "period_end_date must be after period_start_date.")
    authorize(role, {"Operator"})
    f = get_or_404(franchises, franchise_id)
    check_owner(role, uid, franchise_id)

    fee = fee_due(res, com, adv, f["fee_rate_pct"])
    r = new_common()
    r.update({
        "franchise_id": franchise_id,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "residential_gross_cents": res,
        "commercial_gross_cents": com,
        "advertising_gross_cents": adv,
        "fee_due_cents": fee,
        "amount_paid_cents": 0,
        "status": "FILED",
        "fee_basis": "AS_FILED",
        "pre_audit_status": None,
    })
    revenue_reports[r["id"]] = r
    return ok(ser_report(r), 201)


@app.route("/revenue-reports/<rid>", methods=["GET"])
def get_report(rid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    r = get_or_404(revenue_reports, rid)
    return ok(ser_report(r), 200)


@app.route("/revenue-reports", methods=["GET"])
def list_reports():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    items = [r for r in revenue_reports.values()
             if fid is None or r["franchise_id"] == fid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_report(r) for r in page], limit, offset, total)


@app.route("/revenue-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority"})
    r = get_or_404(revenue_reports, rid)
    if r["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not FILED.")
    r["status"] = "ACCEPTED"
    touch(r)
    return ok(ser_report(r), 200)


@app.route("/revenue-reports/<rid>/pay", methods=["POST"])
def pay_report(rid):
    uid, role = do_auth()
    body = get_body()
    amount = req_int(body, "amount_cents")
    authorize(role, {"Operator"})
    r = get_or_404(revenue_reports, rid)
    check_owner(role, uid, r["franchise_id"])
    if r["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not ACCEPTED.")
    outstanding = r["fee_due_cents"] - r["amount_paid_cents"]
    if amount != outstanding:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 402,
                       "Payment must equal the outstanding balance.")
    r["amount_paid_cents"] += amount
    r["status"] = "PAID"
    touch(r)
    return ok(ser_report(r), 200)


# ===========================================================================
# Audits
# ===========================================================================
def audit_period_overlaps(franchise_id, new_start, new_end):
    for a in audits.values():
        if a["franchise_id"] != franchise_id:
            continue
        a_start = parse_instant(a["period_start_date"])
        a_end = parse_instant(a["period_end_date"])
        if max(new_start, a_start) <= min(new_end, a_end):
            return True
    return False


@app.route("/audits", methods=["POST"])
def create_audit():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    target_report_id = req_str(body, "target_report_id")
    period_start = req_dt_str(body, "period_start_date")
    period_end = req_dt_str(body, "period_end_date")
    if parse_instant(period_end) < parse_instant(period_start):
        raise ApiError("ERR_VALIDATION_PERIOD_INVALID", 400,
                       "period_end_date must be on or after period_start_date.")
    authorize(role, {"FranchiseAuthority"})
    f = get_or_404(franchises, franchise_id)
    r = get_or_404(revenue_reports, target_report_id)
    # State: target report must be ACCEPTED or PAID
    if r["status"] not in ("ACCEPTED", "PAID"):
        raise ApiError("ERR_INVALID_STATE", 409, "Target report is not ACCEPTED or PAID.")
    # Domain: audit period overlap
    if audit_period_overlaps(franchise_id, parse_instant(period_start),
                             parse_instant(period_end)):
        raise ApiError("ERR_AUDIT_PERIOD_OVERLAP", 409,
                       "Audit period overlaps an existing audit on this franchise.")

    a = new_common()
    a.update({
        "franchise_id": franchise_id,
        "target_report_id": target_report_id,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "audited_gross_residential_cents": None,
        "audited_gross_commercial_cents": None,
        "audited_gross_advertising_cents": None,
        "status": "OPEN",
        "finalized_by_user_id": None,
        "finalized_at": None,
    })
    audits[a["id"]] = a
    # Report ACCEPTED|PAID -> UNDER_AUDIT (remember prior status)
    r["pre_audit_status"] = r["status"]
    r["status"] = "UNDER_AUDIT"
    touch(r)
    return ok(ser_audit(a), 201)


@app.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    a = get_or_404(audits, aid)
    return ok(ser_audit(a), 200)


@app.route("/audits", methods=["GET"])
def list_audits():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    trid = request.args.get("target_report_id")
    items = [a for a in audits.values()
             if (fid is None or a["franchise_id"] == fid)
             and (trid is None or a["target_report_id"] == trid)]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_audit(a) for a in page], limit, offset, total)


@app.route("/audits/<aid>/finalize", methods=["POST"])
def finalize_audit(aid):
    uid, role = do_auth()
    body = get_body()
    finding = req_enum(body, "finding", {"CLEAN", "FINDING"})
    a_res = a_com = a_adv = None
    if finding == "FINDING":
        a_res = req_int(body, "audited_gross_residential_cents", minimum=0)
        a_com = req_int(body, "audited_gross_commercial_cents", minimum=0)
        a_adv = req_int(body, "audited_gross_advertising_cents", minimum=0)
    authorize(role, {"FranchiseAuthority"})
    a = get_or_404(audits, aid)
    if a["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit is not OPEN.")

    report = revenue_reports[a["target_report_id"]]
    f = franchises[a["franchise_id"]]

    if finding == "CLEAN":
        a["status"] = "COMPLETED_CLEAN"
        a["finalized_by_user_id"] = uid
        a["finalized_at"] = clock["str"]
        touch(a)
        # Restore report to its pre-audit status
        if report["status"] == "UNDER_AUDIT":
            report["status"] = report.get("pre_audit_status") or "ACCEPTED"
            touch(report)
        return ok(ser_audit(a), 200)

    # FINDING: audited gross must strictly exceed reported gross
    reported_sum = (report["residential_gross_cents"]
                    + report["commercial_gross_cents"]
                    + report["advertising_gross_cents"])
    audited_sum = a_res + a_com + a_adv
    if audited_sum <= reported_sum:
        raise ApiError("ERR_AUDIT_NO_UNDERPAYMENT", 409,
                       "Audited gross does not exceed reported gross.")

    finalized_dt = clock["dt"]
    a["status"] = "COMPLETED_FINDING"
    a["finalized_by_user_id"] = uid
    a["finalized_at"] = clock["str"]
    a["audited_gross_residential_cents"] = a_res
    a["audited_gross_commercial_cents"] = a_com
    a["audited_gross_advertising_cents"] = a_adv
    touch(a)

    # --- Hop 1: create Assessment ---
    audited_fee = fee_due(a_res, a_com, a_adv, f["fee_rate_pct"])
    prior_paid = report["amount_paid_cents"]
    principal = audited_fee - prior_paid

    period_end_dt = parse_instant(report["period_end_date"])
    days_late = int((finalized_dt - period_end_dt).total_seconds() // 86400)
    interest = rhu(Decimal(principal) * DAILY_INTEREST_RATE * Decimal(days_late))

    if prior_paid > 0:
        pct_dec = Decimal(principal) / Decimal(prior_paid)
        underpayment_pct = float(pct_dec)
    else:
        pct_dec = None
        underpayment_pct = 0.0

    if pct_dec is None or pct_dec >= Decimal("0.10"):
        penalty_rate = Decimal("0.15")
    elif pct_dec >= Decimal("0.05"):
        penalty_rate = Decimal("0.10")
    else:
        penalty_rate = Decimal("0.05")
    penalty_raw = rhu(Decimal(principal) * penalty_rate)
    penalty = min(penalty_raw, PENALTY_CAP_CENTS)

    asmt = new_common()
    asmt.update({
        "audit_id": a["id"],
        "principal_cents": principal,
        "interest_cents": interest,
        "penalty_cents": penalty,
        "days_late": days_late,
        "underpayment_pct": underpayment_pct,
        "status": "ISSUED",
        "issued_by_user_id": a["finalized_by_user_id"],
        "amount_paid_cents": 0,
    })
    assessments[asmt["id"]] = asmt

    # --- Hop 2: target report UNDER_AUDIT -> ADJUSTED, fee AS_AUDITED ---
    report["status"] = "ADJUSTED"
    report["fee_basis"] = "AS_AUDITED"
    report["fee_due_cents"] = audited_fee
    touch(report)

    # --- Hop 3: Franchise compliance flip -> IN_VIOLATION (holds SUBMITTED apps) ---
    flip_in_violation(f)

    return ok(ser_audit(a), 200)


@app.route("/audits/<aid>/assessments", methods=["GET"])
def audit_assessments(aid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    get_or_404(audits, aid)
    items = [a for a in assessments.values() if a["audit_id"] == aid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_assessment(a) for a in page], limit, offset, total)


# ===========================================================================
# Assessments
# ===========================================================================
@app.route("/assessments/<asid>", methods=["GET"])
def get_assessment(asid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    a = get_or_404(assessments, asid)
    return ok(ser_assessment(a), 200)


def _assessment_franchise_id(a):
    aud = audits.get(a["audit_id"])
    return aud["franchise_id"] if aud else None


@app.route("/assessments/<asid>/pay", methods=["POST"])
def pay_assessment(asid):
    uid, role = do_auth()
    body = get_body()
    amount = req_int(body, "amount_cents")
    authorize(role, {"Operator"})
    a = get_or_404(assessments, asid)
    check_owner(role, uid, _assessment_franchise_id(a))
    if a["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not payable.")
    total = assessment_total(a)
    if amount != total:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 402,
                       "Payment must equal the assessment total.")
    a["amount_paid_cents"] = total
    a["status"] = "PAID"
    touch(a)
    return ok(ser_assessment(a), 200)


@app.route("/assessments/<asid>/dispute", methods=["POST"])
def dispute_assessment(asid):
    uid, role = do_auth()
    authorize(role, {"Operator"})
    a = get_or_404(assessments, asid)
    check_owner(role, uid, _assessment_franchise_id(a))
    if a["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not ISSUED.")
    a["status"] = "DISPUTED"
    touch(a)
    return ok(ser_assessment(a), 200)


@app.route("/assessments/<asid>/waive", methods=["POST"])
def waive_assessment(asid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority"})
    a = get_or_404(assessments, asid)
    # Segregation of duties (priority 40) precedes state (priority 45)
    if uid == a["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The issuer may not waive the assessment.")
    if a["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not waivable.")
    a["status"] = "WAIVED"
    touch(a)
    return ok(ser_assessment(a), 200)


# ===========================================================================
# Complaints
# ===========================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    category = req_enum(body, "category",
                        {"SERVICE_INTERRUPTION", "BILLING", "OTHER"})
    description = req_str(body, "description")
    authorize(role, {"Resident"})
    f = get_or_404(franchises, franchise_id)

    filed_dt = clock["dt"]
    sla_dt = filed_dt + timedelta(hours=SLA_HOURS[category])
    c = new_common()
    c.update({
        "franchise_id": franchise_id,
        "complainant_id": uid,
        "category": category,
        "description": description,
        "filed_at": clock["str"],
        "sla_deadline": render_clock_ts(sla_dt),
        "_sla_dt": sla_dt,
        "status": "OPEN",
        "escalated_at": None,
        "resolution_note": None,
    })
    complaints[c["id"]] = c
    return ok(ser_complaint(c), 201)


@app.route("/complaints/<cid>", methods=["GET"])
def get_complaint(cid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator", "Resident"})
    c = get_or_404(complaints, cid)
    return ok(ser_complaint(c), 200)


@app.route("/complaints", methods=["GET"])
def list_complaints():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    items = [c for c in complaints.values()
             if fid is None or c["franchise_id"] == fid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_complaint(c) for c in page], limit, offset, total)


@app.route("/complaints/<cid>/resolve", methods=["POST"])
def resolve_complaint(cid):
    uid, role = do_auth()
    body = get_body()
    note = req_str(body, "resolution_note")
    authorize(role, {"Operator"})
    c = get_or_404(complaints, cid)
    check_owner(role, uid, c["franchise_id"])
    if c["status"] not in ("OPEN", "REOPENED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint cannot be resolved from its state.")
    was_escalated = c["status"] == "ESCALATED"
    c["status"] = "RESOLVED"
    c["resolution_note"] = note
    touch(c)
    if was_escalated:
        f = franchises.get(c["franchise_id"])
        if f is not None:
            f["unresolved_complaint_count"] = max(0, f["unresolved_complaint_count"] - 1)
    return ok(ser_complaint(c), 200)


@app.route("/complaints/<cid>/escalate", methods=["POST"])
def escalate_complaint(cid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority"})
    c = get_or_404(complaints, cid)
    if c["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint cannot be escalated from its state.")
    if not (clock["dt"] > c["_sla_dt"]):
        raise ApiError("ERR_SLA_NOT_BREACHED", 409,
                       "SLA deadline has not been breached.")
    c["status"] = "ESCALATED"
    c["escalated_at"] = clock["str"]
    touch(c)
    f = franchises.get(c["franchise_id"])
    if f is not None:
        f["unresolved_complaint_count"] += 1
        if f["unresolved_complaint_count"] >= ESCALATION_VIOLATION_THRESHOLD:
            flip_in_violation(f)
    return ok(ser_complaint(c), 200)


@app.route("/complaints/<cid>/reopen", methods=["POST"])
def reopen_complaint(cid):
    uid, role = do_auth()
    authorize(role, {"Resident"})
    c = get_or_404(complaints, cid)
    if uid != c["complainant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the original complainant may reopen this complaint.")
    if c["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint is not RESOLVED.")
    c["status"] = "REOPENED"
    touch(c)
    return ok(ser_complaint(c), 200)


# ===========================================================================
# PEG contributions
# ===========================================================================
@app.route("/peg-contributions", methods=["POST"])
def create_peg():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    amount = req_int(body, "amount_cents", minimum=1)
    ctype = body.get("contribution_type")
    if ctype is None:
        ctype = "CAPITAL_GRANT"
    else:
        if not isinstance(ctype, str) or ctype not in ("CAPITAL_GRANT", "INET"):
            bad("contribution_type must be CAPITAL_GRANT or INET.")
    authorize(role, {"Operator"})
    f = get_or_404(franchises, franchise_id)
    check_owner(role, uid, franchise_id)

    c = new_common()
    c.update({
        "franchise_id": franchise_id,
        "amount_cents": amount,
        "contribution_type": ctype,
        "status": "RECORDED",
        "voided_reason": None,
    })
    peg_contributions[c["id"]] = c
    return ok(ser_peg(c), 201)


@app.route("/peg-contributions/<pid>", methods=["GET"])
def get_peg(pid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    c = get_or_404(peg_contributions, pid)
    return ok(ser_peg(c), 200)


@app.route("/peg-contributions", methods=["GET"])
def list_peg():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    items = [c for c in peg_contributions.values()
             if fid is None or c["franchise_id"] == fid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_peg(c) for c in page], limit, offset, total)


@app.route("/peg-contributions/<pid>/void", methods=["POST"])
def void_peg(pid):
    uid, role = do_auth()
    body = get_body()
    reason = req_str(body, "voided_reason")
    authorize(role, {"FranchiseAuthority"})
    c = get_or_404(peg_contributions, pid)
    if c["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contribution is not RECORDED.")
    c["status"] = "VOIDED"
    c["voided_reason"] = reason
    touch(c)
    return ok(ser_peg(c), 200)


# ===========================================================================
# Franchise applications (transfer / renewal)
# ===========================================================================
@app.route("/franchise-applications", methods=["POST"])
def create_application():
    uid, role = do_auth()
    body = get_body()
    franchise_id = req_str(body, "franchise_id")
    application_type = req_enum(body, "application_type", {"TRANSFER", "RENEWAL"})
    expected_version = req_int(body, "expected_franchise_version")
    transferee_name = None
    proposed_term_end = None
    if application_type == "TRANSFER":
        if body.get("transferee_name") is None or body.get("transferee_name") == "":
            raise ApiError("ERR_TRANSFEREE_REQUIRED", 400,
                           "transferee_name is required for a TRANSFER application.")
        if not isinstance(body["transferee_name"], str):
            bad("transferee_name must be a string.")
        transferee_name = body["transferee_name"]
    else:  # RENEWAL
        if body.get("proposed_term_end_date") is None:
            raise ApiError("ERR_TERM_REQUIRED", 400,
                           "proposed_term_end_date is required for a RENEWAL application.")
        proposed_term_end = req_dt_str(body, "proposed_term_end_date")
    authorize(role, {"Operator"})
    f = get_or_404(franchises, franchise_id)
    check_owner(role, uid, franchise_id)
    # OCC (priority 70)
    if expected_version != f["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_franchise_version does not match the franchise version.")

    # Supersede any prior SUBMITTED application on this franchise
    for prior in list(franchise_applications.values()):
        if prior["franchise_id"] == franchise_id and prior["status"] == "SUBMITTED":
            prior["status"] = "WITHDRAWN"
            touch(prior)

    submitted_dt = clock["dt"]
    deadline_dt = submitted_dt + timedelta(days=DEEMED_APPROVAL_DAYS)
    a = new_common()
    a.update({
        "franchise_id": franchise_id,
        "application_type": application_type,
        "transferee_name": transferee_name,
        "proposed_term_end_date": proposed_term_end,
        "submitted_at": clock["str"],
        "decision_deadline": render_clock_ts(deadline_dt),
        "_deadline_dt": deadline_dt,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "decision": None,
    })
    franchise_applications[a["id"]] = a

    # RENEWAL filing moves franchise ACTIVE -> RENEWAL_PENDING
    if application_type == "RENEWAL" and f["lifecycle_status"] == "ACTIVE":
        f["lifecycle_status"] = "RENEWAL_PENDING"
    # Filing bumps the franchise version by 1 (supersede guard)
    touch(f)
    return ok(ser_application(a), 201)


@app.route("/franchise-applications/<aid>", methods=["GET"])
def get_application(aid):
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    a = get_or_404(franchise_applications, aid)
    return ok(ser_application(a), 200)


@app.route("/franchise-applications", methods=["GET"])
def list_applications():
    uid, role = do_auth()
    authorize(role, {"FranchiseAuthority", "Operator"})
    fid = request.args.get("franchise_id")
    items = [a for a in franchise_applications.values()
             if fid is None or a["franchise_id"] == fid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ser_application(a) for a in page], limit, offset, total)


@app.route("/franchise-applications/<aid>/decide", methods=["POST"])
def decide_application(aid):
    uid, role = do_auth()
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "DENY"})
    authorize(role, {"FranchiseAuthority"})
    a = get_or_404(franchise_applications, aid)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not SUBMITTED.")
    f = franchises[a["franchise_id"]]

    if decision == "APPROVE":
        # Domain preconditions in priority order:
        if f["compliance_status"] == "IN_VIOLATION":
            raise ApiError("ERR_FRANCHISE_IN_VIOLATION", 409,
                           "Franchise compliance is IN_VIOLATION.")
        if a["application_type"] == "RENEWAL":
            for m in buildout_milestones.values():
                if m["franchise_id"] == f["id"] and m["status"] != "MET":
                    raise ApiError("ERR_MILESTONES_NOT_MET", 409,
                                   "All build-out milestones must be MET for renewal.")
        a["status"] = "APPROVED"
        a["decision"] = "APPROVE"
        a["decided_by_user_id"] = uid
        touch(a)
        apply_grant_lifecycle(a, f)
    else:  # DENY
        a["status"] = "DENIED"
        a["decision"] = "DENY"
        a["decided_by_user_id"] = uid
        touch(a)
        if a["application_type"] == "RENEWAL" and f["lifecycle_status"] == "RENEWAL_PENDING":
            f["lifecycle_status"] = "ACTIVE"
            touch(f)
    return ok(ser_application(a), 200)


@app.route("/franchise-applications/<aid>/deem", methods=["POST"])
def deem_application(aid):
    uid, role = do_auth()
    authorize(role, {"Operator"})
    a = get_or_404(franchise_applications, aid)
    check_owner(role, uid, a["franchise_id"])
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not SUBMITTED.")
    if not (clock["dt"] > a["_deadline_dt"]):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Decision deadline has not elapsed.")
    a["status"] = "DEEMED_APPROVED"
    touch(a)
    f = franchises[a["franchise_id"]]
    apply_grant_lifecycle(a, f)
    return ok(ser_application(a), 200)


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
