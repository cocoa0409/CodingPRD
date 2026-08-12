"""Core infrastructure: in-memory store, logical clock, envelope, auth, validation, calculations."""
import re
import uuid
import random
import string
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Store (in-memory only; rebuilt empty on every process boot)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

DB = {
    "sites": {},
    "pods": {},
    "families": {},
    "students": {},
    "vouchers": {},
    "seats": {},
    "guides": {},
    "assignments": {},
    "plans": {},
    "conferences": {},
    "determinations": {},
    "policies": {},
    "invoices": {},
    "payments": {},
    "claims": {},
    "clock": DEFAULT_CLOCK,
    "seq": 0,
}

ROLES = ("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Registrar", "Guide", "Family")

GRADE_BANDS = ("LOWER_EL", "UPPER_EL", "MIDDLE", "HIGH")
ZONING_CLASSES = ("RESIDENTIAL_SINGLE", "RESIDENTIAL_MULTI", "COMMERCIAL", "MIXED_USE", "RELIGIOUS", "AGRICULTURAL")
EXEMPT_ZONING = ("RESIDENTIAL_SINGLE", "RELIGIOUS", "AGRICULTURAL")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def bad_request(msg):
    err("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Referenced resource does not exist"):
    err("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg):
    err("ERR_INVALID_STATE", 409, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    err("ERR_FORBIDDEN", 403, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def dt_iso(dt):
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def logical_now():
    return DB["clock"]


def logical_now_iso():
    return dt_iso(DB["clock"])


def logical_today():
    return DB["clock"].date()


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_date_val(v):
    """Parse an ISO-8601 date (or datetime, taking the date part) -> date or None."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        return None
    m = _DATE_RE.match(v.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_dt_val(v):
    """Parse an ISO-8601 datetime (or date -> midnight UTC) -> aware datetime or None."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not isinstance(v, str):
        return None
    s = v.strip()
    d = parse_date_val(s)
    if d is None:
        return None
    if len(s) == 10:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def meta():
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ok(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": public(data) if isinstance(data, dict) else data}), code


def ok_list(items, code=200):
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": m, "response_type": "array", "data": [public(r) for r in page]}), code


def error_response(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.status


def page_params():
    q = request.args
    raw_limit = q.get("limit")
    raw_offset = q.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def sorted_items(coll):
    return sorted(coll.values(), key=lambda r: r.get("_seq", 0))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def auth(*allowed):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES or uid is None or uid == "":
        err("ERR_UNAUTHENTICATED", 401, "Missing or malformed X-User-Role / X-User-ID headers")
    if allowed and role not in allowed:
        forbidden("Role %s is not permitted to invoke this endpoint" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing and field validation
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    b = request.get_json(silent=True)
    if b is None:
        bad_request("Request body is not valid JSON")
    if not isinstance(b, dict):
        bad_request("Request body must be a JSON object")
    return b


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_field(b, name):
    if name not in b or b[name] is None:
        bad_request("Required field '%s' is missing" % name)
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str) or v == "":
        bad_request("Field '%s' must be a non-empty string" % name)
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        bad_request("Field '%s' must be a string" % name)
    return v


def req_int(b, name, min_v=None, max_v=None):
    v = req_field(b, name)
    if not _is_int(v):
        bad_request("Field '%s' must be an integer" % name)
    if min_v is not None and v < min_v:
        bad_request("Field '%s' must be >= %s" % (name, min_v))
    if max_v is not None and v > max_v:
        bad_request("Field '%s' must be <= %s" % (name, max_v))
    return v


def opt_int(b, name, default=None, min_v=None, max_v=None):
    if name not in b or b[name] is None:
        return default
    return req_int(b, name, min_v=min_v, max_v=max_v)


def req_bool(b, name):
    v = req_field(b, name)
    if not isinstance(v, bool):
        bad_request("Field '%s' must be a boolean" % name)
    return v


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    return req_bool(b, name)


def req_enum(b, name, values):
    v = req_field(b, name)
    if not isinstance(v, str) or v not in values:
        bad_request("Field '%s' must be one of %s" % (name, list(values)))
    return v


def opt_enum(b, name, values, default=None):
    if name not in b or b[name] is None:
        return default
    return req_enum(b, name, values)


def req_date(b, name):
    v = req_field(b, name)
    d = parse_date_val(v)
    if d is None:
        bad_request("Field '%s' must be an ISO 8601 date" % name)
    return d


def req_dt(b, name):
    v = req_field(b, name)
    dt = parse_dt_val(v)
    if dt is None:
        bad_request("Field '%s' must be an ISO 8601 datetime" % name)
    return dt


# ---------------------------------------------------------------------------
# Resource plumbing
# ---------------------------------------------------------------------------

def new_resource():
    DB["seq"] += 1
    t = now_iso()
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t,
            "version": 1, "_seq": DB["seq"]}


def new_ledger_entry():
    """Payment: immutable ledger entry; only id + created_at."""
    DB["seq"] += 1
    return {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": DB["seq"]}


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()


def get_or_404(coll_name, rid, what="Resource"):
    rec = DB[coll_name].get(rid)
    if rec is None:
        not_found("%s '%s' does not exist" % (what, rid))
    return rec


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def rhu(x):
    """Round half up to integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pod derived state
# ---------------------------------------------------------------------------

def recompute_enrolled_count(pod):
    pod["enrolled_count"] = sum(
        1 for s in DB["seats"].values()
        if s["pod_id"] == pod["id"] and s["seat_status"] == "ENROLLED"
    )


def compute_posture(pod):
    st = pod["status"]
    if st in ("DISSOLVING", "DISSOLVED"):
        return "CLOSED"
    if st == "SUSPENDED":
        return "FROZEN"
    if st == "LICENSING_REVIEW":
        return "RESTRICTED"
    if st == "ACTIVE" and pod["enrolled_count"] >= pod["seat_capacity"]:
        return "RESTRICTED"
    return "OPEN"


def refresh_posture(pod):
    pod["posture"] = compute_posture(pod)


def pod_gate(pod, block_frozen=True, block_closed=True):
    """Posture gate for child mutations."""
    p = pod["posture"]
    if block_closed and p == "CLOSED":
        err("ERR_POD_FROZEN", 409, "Pod posture is CLOSED; child mutations are refused")
    if block_frozen and p == "FROZEN":
        err("ERR_POD_FROZEN", 409, "Pod posture is FROZEN; the requested child mutation is refused")


def guide_weight(guide, pod):
    if pod.get("_ratio_mode") == "HEADCOUNT":
        return Fraction(1)
    return Fraction(1, 2) if guide["certification_tier"] == "APPRENTICE" else Fraction(1)


def ratio_fraction(pod):
    today = logical_today()
    fte = Fraction(0)
    for a in DB["assignments"].values():
        if a["pod_id"] != pod["id"] or a["assignment_status"] != "ACTIVE":
            continue
        ws = parse_date_val(a["window_start_date"])
        we = parse_date_val(a["window_end_date"])
        if ws <= today <= we:
            g = DB["guides"].get(a["guide_id"])
            if g is None:
                continue
            hours_factor = min(Fraction(1), Fraction(a["weekly_hours"], 30))
            fte += guide_weight(g, pod) * hours_factor
    denom = max(1, pod["enrolled_count"])
    return fte / denom


def recompute_compliance(pod, allow_autosuspend=False):
    r = ratio_fraction(pod)
    if r >= Fraction(1, 10):
        flag = "COMPLIANT"
    elif r >= Fraction(1, 15):
        flag = "AT_RISK"
    else:
        flag = "VIOLATION"
    pod["compliance_flag"] = flag
    if flag == "VIOLATION" and pod["status"] == "ACTIVE" and allow_autosuspend:
        pod["status"] = "SUSPENDED"
        refresh_posture(pod)


# ---------------------------------------------------------------------------
# Voucher derived state
# ---------------------------------------------------------------------------

def recompute_funding(v):
    if v["funding_status"] == "FROZEN":
        return
    awarded = v["awarded_annual_cents"]
    if v.get("_release_schedule") == "MONTHLY":
        base = max(1, rhu(Decimal(awarded) / Decimal(10)))
    else:
        base = awarded
    b = v["disbursable_balance_cents"]
    if b == 0:
        v["funding_status"] = "DEPLETED"
    elif 2 * b >= base:
        v["funding_status"] = "FUNDED"
    else:
        v["funding_status"] = "PARTIALLY_DEPLETED"


def recompute_voucher_accepted(v):
    ok_status = (v["verification_status"] == "VERIFIED"
                 and v["funding_status"] in ("FUNDED", "PARTIALLY_DEPLETED"))
    pod_active = False
    for s in DB["seats"].values():
        if s["student_id"] == v["student_id"] and s["seat_status"] in ("RESERVED", "ENROLLED"):
            p = DB["pods"].get(s["pod_id"])
            if p is not None and p["status"] == "ACTIVE":
                pod_active = True
                break
    v["accepted_by_pod"] = bool(ok_status and pod_active)


def recompute_accepted_for_pod(pod):
    student_ids = {s["student_id"] for s in DB["seats"].values() if s["pod_id"] == pod["id"]}
    for v in DB["vouchers"].values():
        if v["student_id"] in student_ids:
            recompute_voucher_accepted(v)


# ---------------------------------------------------------------------------
# Ledger recompute (only CLEARED payments count; REFUND_REVERSAL excluded)
# ---------------------------------------------------------------------------

def recompute_invoice_paid(inv):
    inv["paid_cents"] = sum(
        p["amount_cents"] for p in DB["payments"].values()
        if p["invoice_id"] == inv["id"] and p["payment_status"] == "CLEARED"
        and p["source_kind"] != "REFUND_REVERSAL"
    )


def recompute_seat_paid(seat):
    seat["paid_cents"] = sum(
        p["amount_cents"] for p in DB["payments"].values()
        if p["seat_id"] == seat["id"] and p["payment_status"] == "CLEARED"
        and p["source_kind"] != "REFUND_REVERSAL"
    )


def settle_invoice_after_payment(inv):
    st = inv["invoice_status"]
    if st in ("ISSUED", "OVERDUE") and inv["paid_cents"] >= inv["total_cents"]:
        inv["invoice_status"] = "PAID"
        touch(inv)
    elif st == "PARTIALLY_PAID" and inv["paid_cents"] >= inv["total_cents"]:
        inv["invoice_status"] = "PAID"
        touch(inv)
    elif st == "ISSUED" and 0 < inv["paid_cents"] < inv["total_cents"]:
        inv["invoice_status"] = "PARTIALLY_PAID"
        touch(inv)


# ---------------------------------------------------------------------------
# Proration & refund calculations
# ---------------------------------------------------------------------------

def pod_total_days(pod):
    return (parse_date_val(pod["term_end_date"]) - parse_date_val(pod["term_start_date"])).days + 1


def _ceil_div(a, b):
    return -(-int(a) // int(b))


def prorated_enrollment(pod, enrolled_on):
    """Prorated tuition owed given a (possibly mid-year) enrollment date."""
    total = pod_total_days(pod)
    edays = (parse_date_val(pod["term_end_date"]) - enrolled_on).days + 1
    edays = max(0, min(edays, total))
    t = pod["tuition_full_year_cents"]
    if pod.get("_proration_mode") == "PER_WEEK":
        ew = _ceil_div(edays, 7)
        tw = _ceil_div(total, 7)
        return rhu(Decimal(t) * Decimal(ew) / Decimal(tw))
    return rhu(Decimal(t) * Decimal(edays) / Decimal(total))


def earned_through(pod, seat, upto):
    """Prorated earned tuition over [enrolled_on, upto] inclusive; always PER_DAY."""
    total = pod_total_days(pod)
    e = parse_date_val(seat["enrolled_on"])
    days = (upto - e).days + 1
    days = max(0, min(days, total))
    basis = seat.get("tuition_basis_cents") or pod["tuition_full_year_cents"]
    return rhu(Decimal(basis) * Decimal(days) / Decimal(total))


def withdrawal_refund(pod, seat):
    paid = seat["paid_cents"]
    if pod.get("_refund_mode") == "FLAT_FEE":
        return max(0, paid - int(pod.get("_flat_fee_cents") or 0))
    w = parse_date_val(seat["withdrawn_on"])
    e = parse_date_val(seat["enrolled_on"])
    days_enrolled = (w - e).days + 1
    earned = earned_through(pod, seat, w)
    unearned = max(0, paid - earned)
    if days_enrolled <= 14:
        pct = Decimal("1")
    elif days_enrolled <= 45:
        pct = Decimal("0.75")
    elif days_enrolled <= 90:
        pct = Decimal("0.5")
    else:
        pct = Decimal("0")
    return rhu(Decimal(unearned) * pct)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def admin_fee_pct(enrolled_count):
    if enrolled_count <= 8:
        return Decimal("0.04")
    if enrolled_count <= 16:
        return Decimal("0.03")
    if enrolled_count <= 24:
        return Decimal("0.02")
    return Decimal("0.015")


def compute_invoice_money(pod, inv):
    sub = 0
    for li in inv["line_items"]:
        ext = rhu(Decimal(str(li["quantity"])) * Decimal(li["unit_amount_cents"]))
        if li["kind"] == "CREDIT":
            sub -= ext
        else:
            sub += ext
    inv["subtotal_cents"] = sub
    inv["admin_fee_cents"] = rhu(Decimal(sub) * admin_fee_pct(pod["enrolled_count"]))
    inv["total_cents"] = inv["subtotal_cents"] + inv["admin_fee_cents"]


# ---------------------------------------------------------------------------
# Grade bands
# ---------------------------------------------------------------------------

def grade_band_for(dob, ref):
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    if age <= 7:
        return "LOWER_EL"
    if age <= 10:
        return "UPPER_EL"
    if age <= 13:
        return "MIDDLE"
    return "HIGH"


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def supersede_plan(plan):
    if plan["plan_status"] != "APPROVED":
        return
    plan["plan_status"] = "SUPERSEDED"
    touch(plan)
    for c in DB["conferences"].values():
        if c["curriculum_plan_id"] == plan["id"] and c["conference_status"] in ("REQUESTED", "SCHEDULED", "RESCHEDULED"):
            c["conference_status"] = "CANCELLED"
            touch(c)


def try_activate_pod(pod):
    """LICENSING_REVIEW -> ACTIVE when the latest determination grants and staffing covers term start."""
    if pod["status"] != "LICENSING_REVIEW":
        return
    ts = parse_date_val(pod["term_start_date"])
    covered = any(
        a["pod_id"] == pod["id"]
        and a["assignment_status"] in ("SCHEDULED", "ACTIVE")
        and parse_date_val(a["window_start_date"]) <= ts <= parse_date_val(a["window_end_date"])
        for a in DB["assignments"].values()
    )
    if not covered:
        return
    pod["status"] = "ACTIVE"
    pod["compliance_flag"] = "COMPLIANT"
    refresh_posture(pod)
    touch(pod)
    # PRD 3.4: "When the clock reaches a SCHEDULED assignment's
    # window_start_date while its pod is ACTIVE, the assignment becomes
    # ACTIVE." The clock may already sit past window_start when the pod
    # activates, so the aging transitions are evaluated at activation too.
    run_clock_transitions()
    recompute_accepted_for_pod(pod)


def create_claim(pod, seat, kind, amount, filed_by):
    c = new_resource()
    c.update({
        "pod_id": pod["id"],
        "seat_id": seat["id"],
        "claim_kind": kind,
        "claimed_amount_cents": int(amount),
        "approved_amount_cents": None,
        "claim_status": "FILED",
        "reviewed_by_user_id": None,
        "filed_by_user_id": filed_by,
    })
    DB["claims"][c["id"]] = c
    return c


def dissolution_pool_amounts(pod, withdrawn_seats):
    """Waterfall allocation of the dissolution refund pool. Returns {seat_id: cents}."""
    today = logical_today()
    gross = sum(s["paid_cents"] for s in withdrawn_seats)
    earned = sum(earned_through(pod, s, today) for s in withdrawn_seats)
    pool = max(0, gross - earned)

    def paid_by(seat, kind):
        return sum(
            p["amount_cents"] for p in DB["payments"].values()
            if p["seat_id"] == seat["id"] and p["payment_status"] == "CLEARED"
            and p["source_kind"] == kind
        )

    result = {s["id"]: 0 for s in withdrawn_seats}
    remaining = pool
    for kind in ("VOUCHER", "FAMILY", "SCHOLARSHIP"):
        claimants = [s for s in withdrawn_seats if paid_by(s, kind) > 0]
        bucket_total = sum(paid_by(s, kind) for s in claimants)
        if bucket_total == 0 or remaining == 0:
            continue
        amt = min(remaining, bucket_total)
        shares = {}
        for s in claimants:
            shares[s["id"]] = rhu(Decimal(amt) * Decimal(paid_by(s, kind)) / Decimal(bucket_total))
        rem = amt - sum(shares.values())
        if rem:
            earliest = min(claimants, key=lambda s: s.get("_seq", 0))
            shares[earliest["id"]] += rem
        for sid, share in shares.items():
            result[sid] += share
        remaining -= amt
    return result


def run_clock_transitions():
    today = logical_today()
    # GuideAssignment SCHEDULED -> ACTIVE when clock reaches window start.
    # Pod must be operating (ACTIVE); a SUSPENDED pod's scheduled guides still come into
    # force so the staffing ratio can recover and reinstatement becomes reachable.
    for a in list(DB["assignments"].values()):
        if a["assignment_status"] == "SCHEDULED" and parse_date_val(a["window_start_date"]) <= today:
            pod = DB["pods"].get(a["pod_id"])
            if pod is not None and pod["status"] in ("ACTIVE", "SUSPENDED"):
                a["assignment_status"] = "ACTIVE"
                touch(a)
                recompute_compliance(pod)
    # GuideAssignment ACTIVE -> ENDED once clock passes window end
    for a in list(DB["assignments"].values()):
        if a["assignment_status"] == "ACTIVE" and parse_date_val(a["window_end_date"]) < today:
            pod = DB["pods"].get(a["pod_id"])
            a["assignment_status"] = "ENDED"
            touch(a)
            if pod is not None:
                recompute_compliance(pod)
    # TuitionInvoice ISSUED/PARTIALLY_PAID -> OVERDUE past due date
    for inv in list(DB["invoices"].values()):
        if inv["invoice_status"] in ("ISSUED", "PARTIALLY_PAID"):
            if parse_date_val(inv["due_date"]) < today and inv["paid_cents"] < inv["total_cents"]:
                inv["invoice_status"] = "OVERDUE"
                touch(inv)
