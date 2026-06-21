import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NBBP_CENTS = 3470          # Part D national base beneficiary premium
PARTB_STD_CENTS = 17470    # Standard Part B premium
DEDUCTIBLE_CENTS = 54500
ICL_CENTS = 503000
TROOP_CENTS = 800000

ROLE_ADMIN = "EnrollmentAdmin"
ROLE_COMPLIANCE = "ComplianceOfficer"
VALID_ROLES = {ROLE_ADMIN, ROLE_COMPLIANCE}

STAR_RATINGS = {1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0}

# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.beneficiaries = {}
        self.plans = {}
        self.enrollment_periods = {}
        self.part_b_enrollments = {}
        self.part_c_enrollments = {}
        self.part_d_enrollments = {}
        self.drug_claims = {}
        self.medigap_policies = {}
        self.penalty_assessments = {}
        self._seq = 0
        # Logical system clock; default to real wall time at boot.
        self.clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now_clock():
    return db.clock


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def first_of_month(year, month):
    return datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)


def add_months(year, month, delta):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, (idx % 12) + 1


def last_instant_of_month(year, month):
    ny, nm = add_months(year, month, 1)
    return first_of_month(ny, nm) - timedelta(microseconds=1)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": iso_now()}
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", 422, str(e)))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    g.role = role
    g.uid = uid


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_json_body():
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Body must be a JSON object.")
    return data


def invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", 422, msg)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def stamp_create(rec, versioned=True):
    ts = fmt_ts(now_clock())
    rec["created_at"] = ts
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = db.next_seq()


def touch(rec):
    rec["updated_at"] = fmt_ts(now_clock())
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION_PAGINATION", 422, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION_PAGINATION", 422, "limit out of bounds (1-100).")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION_PAGINATION", 422, "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION_PAGINATION", 422, "offset must be >= 0.")
    return limit, offset


def paginate(items):
    """items: list of records (with _seq). Sort by created_at asc (tie _seq)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return [public(r) for r in page], meta_extra


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def must_get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found.")
    return rec


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def partd_lep_cents(uncovered_months):
    raw = Decimal("0.01") * Decimal(NBBP_CENTS) * Decimal(uncovered_months)
    dimes = round_half_up(raw / Decimal(10))
    return dimes * 10


def partb_lep_cents(uncovered_months):
    full_periods = uncovered_months // 12
    penalty_pct = 10 * full_periods
    return (PARTB_STD_CENTS * penalty_pct) // 100


def compute_partd_uncovered_months(beneficiary):
    """anchor = part_d_creditable_since, else IEP window_end."""
    anchor_str = beneficiary.get("part_d_creditable_since")
    if anchor_str:
        anchor = parse_iso(anchor_str)
    else:
        ieps = [p for p in db.enrollment_periods.values()
                if p["beneficiary_id"] == beneficiary["id"] and p["period_type"] == "IEP"]
        if not ieps:
            anchor = now_clock()
        else:
            ieps.sort(key=lambda p: (p.get("created_at", ""), p.get("_seq", 0)))
            anchor = parse_iso(ieps[-1]["window_end"])
    eff = now_clock()
    months_between = (eff.year * 12 + (eff.month - 1)) - (anchor.year * 12 + (anchor.month - 1)) - 1
    return max(0, months_between)


def adjudicate_claim(enrollment, list_price_cents):
    """Returns (phase_at_post, member_share_cents). Advances T and O on enrollment."""
    T = enrollment["total_drug_cost_cents"]
    O = enrollment["member_oop_cents"]
    remaining = list_price_cents
    member_share = 0
    phase_at_post = None

    def current_phase(t, o):
        if t < DEDUCTIBLE_CENTS:
            return "DEDUCTIBLE"
        if t < ICL_CENTS:
            return "INITIAL"
        if o < TROOP_CENTS:
            return "GAP"
        return "CATASTROPHIC"

    while remaining > 0:
        phase = current_phase(T, O)
        if phase_at_post is None:
            phase_at_post = phase

        if phase == "DEDUCTIBLE":
            seg = min(remaining, DEDUCTIBLE_CENTS - T)
            seg_share = seg  # 100%
        elif phase == "INITIAL":
            seg = min(remaining, ICL_CENTS - T)
            seg_share = round_half_up(Decimal(seg) * Decimal("0.25"))
        elif phase == "GAP":
            # Gap continues until O reaches TROOP. Member pays 25% of segment.
            # Determine cents until O hits TROOP given 25% member share rate.
            # O advances by member_share, not list price. Compute max list cents
            # such that the resulting member share keeps O below the boundary,
            # but boundary is checked on O reaching TROOP (>=). We advance until
            # O would reach TROOP. Member share per cent = 0.25 -> find cents.
            seg = remaining
            seg_share = round_half_up(Decimal(seg) * Decimal("0.25"))
            # Check if this segment pushes O to/over TROOP; if so, split.
            if O + seg_share >= TROOP_CENTS:
                # Find the cent count where O first reaches TROOP.
                need = TROOP_CENTS - O  # member-share cents needed to hit boundary
                # member share for k cents = round_half_up(k*0.25). Find smallest k
                # such that share >= need. Then that k completes the GAP segment.
                k = _cents_for_share(need)
                if k > remaining:
                    k = remaining
                seg = k
                seg_share = round_half_up(Decimal(seg) * Decimal("0.25"))
        else:  # CATASTROPHIC
            seg = remaining
            seg_share = 0

        if seg <= 0:
            # Safety: avoid infinite loop; consume remainder in current phase.
            seg = remaining
            if phase == "DEDUCTIBLE":
                seg_share = seg
            elif phase in ("INITIAL", "GAP"):
                seg_share = round_half_up(Decimal(seg) * Decimal("0.25"))
            else:
                seg_share = 0

        member_share += seg_share
        T += seg
        O += seg_share
        remaining -= seg

    enrollment["total_drug_cost_cents"] = T
    enrollment["member_oop_cents"] = O
    return phase_at_post, member_share


def _cents_for_share(need_share):
    """Smallest integer k such that round_half_up(k*0.25) >= need_share."""
    if need_share <= 0:
        return 0
    # round_half_up(k*0.25) = floor(k*0.25 + 0.5) for non-negative.
    # Solve k*0.25 + 0.5 >= need_share roughly -> k >= 4*(need_share - 0.5)
    k = max(0, int((need_share - Decimal("0.5")) * 4))
    while round_half_up(Decimal(k) * Decimal("0.25")) < need_share:
        k += 1
    return k


# ---------------------------------------------------------------------------
# Beneficiary endpoints
# ---------------------------------------------------------------------------
@app.route("/beneficiaries", methods=["POST"])
def create_beneficiary():
    require_auth({ROLE_ADMIN})
    body = get_json_body()

    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        invalid("full_name is required and must be a non-empty string.")

    dob_raw = body.get("date_of_birth")
    if not isinstance(dob_raw, str) or not dob_raw.strip():
        invalid("date_of_birth is required.")
    try:
        dob = parse_iso(dob_raw)
    except ValueError:
        invalid("date_of_birth must be a valid ISO 8601 date-time.")
    if dob.day == 1:
        invalid("date_of_birth day-of-month must not be the 1st.")

    creditable = body.get("part_d_creditable_since")
    if creditable is not None:
        if not isinstance(creditable, str):
            invalid("part_d_creditable_since must be an ISO 8601 string or null.")
        try:
            parse_iso(creditable)
        except ValueError:
            invalid("part_d_creditable_since must be a valid ISO 8601 date-time.")

    rec = {
        "id": str(uuid.uuid4()),
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "part_a_status": "NONE",
        "part_b_status": "NONE",
        "part_b_effective_date": None,
        "part_d_creditable_since": creditable,
        "enrollment_lock": False,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.beneficiaries[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/beneficiaries/<bid>", methods=["GET"])
def get_beneficiary(bid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.beneficiaries, bid)
    return success(public(rec), 200)


@app.route("/beneficiaries", methods=["GET"])
def list_beneficiaries():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    data, meta_extra = paginate(list(db.beneficiaries.values()))
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/beneficiaries/<bid>/establish-part-a", methods=["POST"])
def establish_part_a(bid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.beneficiaries, bid)
    rec["part_a_status"] = "ENROLLED"
    touch(rec)
    return success(public(rec), 200)


@app.route("/beneficiaries/<bid>/fraud-hold", methods=["POST"])
def fraud_hold(bid):
    require_auth({ROLE_COMPLIANCE})
    rec = must_get(db.beneficiaries, bid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary must be ACTIVE.")
    rec["status"] = "FRAUD_HOLD"
    rec["enrollment_lock"] = True
    touch(rec)
    return success(public(rec), 200)


@app.route("/beneficiaries/<bid>/clear-hold", methods=["POST"])
def clear_hold(bid):
    require_auth({ROLE_COMPLIANCE})
    rec = must_get(db.beneficiaries, bid)
    if rec["status"] != "FRAUD_HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary must be in FRAUD_HOLD.")
    rec["status"] = "ACTIVE"
    rec["enrollment_lock"] = False
    touch(rec)
    return success(public(rec), 200)


@app.route("/beneficiaries/<bid>/record-death", methods=["POST"])
def record_death(bid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.beneficiaries, bid)
    if rec["status"] not in ("ACTIVE", "FRAUD_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary is already DECEASED.")
    rec["status"] = "DECEASED"

    for e in db.part_c_enrollments.values():
        if e["beneficiary_id"] == bid and e["status"] in ("PENDING", "ACTIVE"):
            e["status"] = "VOIDED"
            touch(e)
    for e in db.part_d_enrollments.values():
        if e["beneficiary_id"] == bid and e["status"] in ("PENDING", "ACTIVE"):
            e["status"] = "VOIDED"
            touch(e)
    for m in db.medigap_policies.values():
        if m["beneficiary_id"] == bid and m["status"] == "ISSUED":
            m["status"] = "VOIDED"
            touch(m)
    for e in db.part_b_enrollments.values():
        if e["beneficiary_id"] == bid and e["status"] in ("FILED", "ACTIVE"):
            was_active = e["status"] == "ACTIVE"
            e["status"] = "VOIDED"
            touch(e)
            if was_active:
                rec["part_b_status"] = "NONE"

    touch(rec)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# EnrollmentPeriod endpoints
# ---------------------------------------------------------------------------
def derive_iep_window(beneficiary):
    dob = parse_iso(beneficiary["date_of_birth"])
    # window_start: first-of-month 3 months before birth month
    sy, sm = add_months(dob.year, dob.month, -3)
    window_start = first_of_month(sy, sm)
    # IEP spans 7 months: 3 before, birth month, 3 after -> ends last instant
    # of the 3rd month after birth month.
    ey, em = add_months(dob.year, dob.month, 3)
    window_end = last_instant_of_month(ey, em)
    return window_start, window_end


def periods_overlap_closed(s1, e1, s2, e2):
    # closed [s,e]: overlap if s1 <= e2 and s2 <= e1
    return s1 <= e2 and s2 <= e1


@app.route("/beneficiaries/<bid>/enrollment-periods", methods=["POST"])
def create_enrollment_period(bid):
    require_auth({ROLE_ADMIN})
    beneficiary = must_get(db.beneficiaries, bid)
    body = get_json_body()

    period_type = body.get("period_type")
    if period_type not in ("IEP", "AEP", "SEP_5STAR", "GI_MEDIGAP"):
        invalid("period_type must be one of IEP, AEP, SEP_5STAR, GI_MEDIGAP.")

    source_event_date = None
    window_start = None
    window_end = None

    if period_type == "IEP":
        window_start, window_end = derive_iep_window(beneficiary)
    elif period_type == "AEP":
        aep_year = body.get("aep_year")
        if not is_int(aep_year):
            invalid("aep_year is required for AEP and must be an integer.")
        window_start = first_of_month(aep_year, 10).replace(day=15)
        window_end = datetime(aep_year, 12, 7, 23, 59, 59, 999999, tzinfo=timezone.utc)
    elif period_type == "SEP_5STAR":
        aep_year = body.get("aep_year")
        if not is_int(aep_year):
            invalid("aep_year is required for SEP_5STAR and must be an integer.")
        window_start = datetime(aep_year, 12, 8, 0, 0, 0, tzinfo=timezone.utc)
        window_end = datetime(aep_year + 1, 11, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)
    else:  # GI_MEDIGAP
        sed_raw = body.get("source_event_date")
        if sed_raw is None:
            raise ApiError("ERR_MISSING_SOURCE_EVENT_DATE", 422,
                           "GI_MEDIGAP requires source_event_date.")
        if not isinstance(sed_raw, str):
            invalid("source_event_date must be an ISO 8601 string.")
        try:
            sed = parse_iso(sed_raw)
        except ValueError:
            invalid("source_event_date must be a valid ISO 8601 date-time.")
        source_event_date = sed_raw
        window_start = sed
        window_end = sed + timedelta(days=63)

    # Overlap guard for same-type IEP/AEP
    if period_type in ("IEP", "AEP"):
        for p in db.enrollment_periods.values():
            if p["beneficiary_id"] == bid and p["period_type"] == period_type:
                es = parse_iso(p["window_start"])
                ee = parse_iso(p["window_end"])
                if periods_overlap_closed(window_start, window_end, es, ee):
                    raise ApiError("ERR_PERIOD_OVERLAP", 409,
                                   "Overlapping same-type enrollment period.")

    rec = {
        "id": str(uuid.uuid4()),
        "beneficiary_id": bid,
        "period_type": period_type,
        "window_start": fmt_ts(window_start),
        "window_end": fmt_ts(window_end),
        "source_event_date": source_event_date,
    }
    stamp_create(rec, versioned=False)
    db.enrollment_periods[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/beneficiaries/<bid>/enrollment-periods", methods=["GET"])
def list_enrollment_periods(bid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    must_get(db.beneficiaries, bid)
    items = [p for p in db.enrollment_periods.values() if p["beneficiary_id"] == bid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/enrollment-periods/<pid>", methods=["GET"])
def get_enrollment_period(pid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.enrollment_periods, pid)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# Plan endpoints
# ---------------------------------------------------------------------------
@app.route("/plans", methods=["POST"])
def create_plan():
    require_auth({ROLE_ADMIN})
    body = get_json_body()

    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        invalid("name is required.")

    part_type = body.get("part_type")
    if part_type not in ("PART_C", "PART_D"):
        invalid("part_type must be PART_C or PART_D.")

    premium = body.get("monthly_premium_cents")
    if not is_int(premium) or premium < 0:
        invalid("monthly_premium_cents must be an integer >= 0.")

    star = body.get("star_rating")
    if isinstance(star, bool) or not isinstance(star, (int, float)):
        invalid("star_rating must be a number.")
    star = float(star)
    if star not in STAR_RATINGS:
        invalid("star_rating must be one of the valid CMS ratings.")

    includes = body.get("includes_drug_coverage")
    if includes is None:
        includes = (part_type == "PART_D")
    elif not isinstance(includes, bool):
        invalid("includes_drug_coverage must be a boolean.")

    if part_type == "PART_D" and includes is not True:
        invalid("PART_D plans must set includes_drug_coverage to true.")

    rec = {
        "id": str(uuid.uuid4()),
        "name": name,
        "part_type": part_type,
        "monthly_premium_cents": premium,
        "star_rating": star,
        "includes_drug_coverage": includes,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.plans[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.plans, pid)
    return success(public(rec), 200)


@app.route("/plans/<pid>/retire", methods=["POST"])
def retire_plan(pid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.plans, pid)
    rec["status"] = "RETIRED"
    touch(rec)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# Shared enrollment-create validation helpers
# ---------------------------------------------------------------------------
def in_closed_window(period):
    ws = parse_iso(period["window_start"])
    we = parse_iso(period["window_end"])
    nowt = now_clock()
    return ws <= nowt <= we


def compute_partc_effective_date():
    """First-of-month effective date. Use the month after the current clock month."""
    nowt = now_clock()
    ey, em = add_months(nowt.year, nowt.month, 1)
    return first_of_month(ey, em)


# ---------------------------------------------------------------------------
# PartBEnrollment endpoints
# ---------------------------------------------------------------------------
@app.route("/part-b-enrollments", methods=["POST"])
def create_part_b():
    require_auth({ROLE_ADMIN})
    body = get_json_body()

    bid = body.get("beneficiary_id")
    pid = body.get("enrollment_period_id")
    # existence (body FK) - priority 4
    if not isinstance(bid, str):
        invalid("beneficiary_id is required.")
    if not isinstance(pid, str):
        invalid("enrollment_period_id is required.")
    beneficiary = db.beneficiaries.get(bid)
    if beneficiary is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Beneficiary not found.")
    period = db.enrollment_periods.get(pid)
    if period is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EnrollmentPeriod not found.")

    # priority 8: period belongs to beneficiary
    if period["beneficiary_id"] != bid:
        raise ApiError("ERR_PERIOD_BENEFICIARY_MISMATCH", 422,
                       "Period does not belong to beneficiary.")
    # priority 9: wrong period type (Part B requires IEP)
    if period["period_type"] != "IEP":
        raise ApiError("ERR_WRONG_PERIOD_TYPE", 422, "Part B requires an IEP period.")
    # priority 10: enrollment lock
    if beneficiary["enrollment_lock"]:
        raise ApiError("ERR_ENROLLMENT_LOCKED", 409, "Beneficiary enrollment is locked.")
    # priority 11: within window
    if not in_closed_window(period):
        raise ApiError("ERR_OUTSIDE_ENROLLMENT_WINDOW", 422, "Outside enrollment window.")

    rec = {
        "id": str(uuid.uuid4()),
        "beneficiary_id": bid,
        "enrollment_period_id": pid,
        "requested_at": fmt_ts(now_clock()),
        "effective_date": fmt_ts(compute_partc_effective_date()),
        "status": "FILED",
    }
    stamp_create(rec)
    db.part_b_enrollments[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/part-b-enrollments", methods=["GET"])
def list_part_b():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    items = list(db.part_b_enrollments.values())
    bid = request.args.get("beneficiary_id")
    pid = request.args.get("enrollment_period_id")
    if bid is not None:
        items = [e for e in items if e["beneficiary_id"] == bid]
    if pid is not None:
        items = [e for e in items if e["enrollment_period_id"] == pid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/part-b-enrollments/<eid>", methods=["GET"])
def get_part_b(eid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.part_b_enrollments, eid)
    return success(public(rec), 200)


@app.route("/part-b-enrollments/<eid>/activate", methods=["POST"])
def activate_part_b(eid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.part_b_enrollments, eid)
    if rec["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Part B enrollment must be FILED.")
    beneficiary = db.beneficiaries[rec["beneficiary_id"]]
    if beneficiary["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary must be ACTIVE.")
    if beneficiary["part_a_status"] != "ENROLLED":
        raise ApiError("ERR_PART_A_REQUIRED", 409, "Part A must be established first.")
    rec["status"] = "ACTIVE"
    touch(rec)
    beneficiary["part_b_status"] = "ENROLLED"
    beneficiary["part_b_effective_date"] = rec["effective_date"]
    touch(beneficiary)
    return success(public(rec), 200)


@app.route("/part-b-enrollments/<eid>/drop", methods=["POST"])
def drop_part_b(eid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.part_b_enrollments, eid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Part B enrollment must be ACTIVE.")
    beneficiary = db.beneficiaries[rec["beneficiary_id"]]
    if beneficiary["status"] == "DECEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary is DECEASED.")
    rec["status"] = "DROPPED"
    touch(rec)
    beneficiary["part_b_status"] = "NONE"
    touch(beneficiary)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# PartCEnrollment endpoints
# ---------------------------------------------------------------------------
@app.route("/part-c-enrollments", methods=["POST"])
def create_part_c():
    require_auth({ROLE_ADMIN})
    body = get_json_body()

    bid = body.get("beneficiary_id")
    plan_id = body.get("plan_id")
    pid = body.get("enrollment_period_id")
    if not isinstance(bid, str):
        invalid("beneficiary_id is required.")
    if not isinstance(plan_id, str):
        invalid("plan_id is required.")
    if not isinstance(pid, str):
        invalid("enrollment_period_id is required.")

    beneficiary = db.beneficiaries.get(bid)
    if beneficiary is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Beneficiary not found.")
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Plan not found.")
    period = db.enrollment_periods.get(pid)
    if period is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EnrollmentPeriod not found.")

    # 8: period beneficiary mismatch
    if period["beneficiary_id"] != bid:
        raise ApiError("ERR_PERIOD_BENEFICIARY_MISMATCH", 422,
                       "Period does not belong to beneficiary.")
    # 9: wrong period type
    if period["period_type"] not in ("IEP", "AEP", "SEP_5STAR"):
        raise ApiError("ERR_WRONG_PERIOD_TYPE", 422, "Invalid period type for Part C.")
    # 10: enrollment lock
    if beneficiary["enrollment_lock"]:
        raise ApiError("ERR_ENROLLMENT_LOCKED", 409, "Beneficiary enrollment is locked.")
    # 11: within window
    if not in_closed_window(period):
        raise ApiError("ERR_OUTSIDE_ENROLLMENT_WINDOW", 422, "Outside enrollment window.")
    # 13: five-star
    if period["period_type"] == "SEP_5STAR" and plan["star_rating"] != 5.0:
        raise ApiError("ERR_NOT_FIVE_STAR", 422, "SEP_5STAR requires a 5.0-star plan.")
    # 14: drug coverage conflict (plan must be PART_C)
    if plan["part_type"] != "PART_C":
        raise ApiError("ERR_DRUG_COVERAGE_CONFLICT", 409, "Part C requires a PART_C plan.")

    rec = {
        "id": str(uuid.uuid4()),
        "beneficiary_id": bid,
        "plan_id": plan_id,
        "enrollment_period_id": pid,
        "requested_at": fmt_ts(now_clock()),
        "effective_date": fmt_ts(compute_partc_effective_date()),
        "status": "PENDING",
    }
    stamp_create(rec)
    db.part_c_enrollments[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/part-c-enrollments", methods=["GET"])
def list_part_c():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    items = list(db.part_c_enrollments.values())
    bid = request.args.get("beneficiary_id")
    plan_id = request.args.get("plan_id")
    pid = request.args.get("enrollment_period_id")
    if bid is not None:
        items = [e for e in items if e["beneficiary_id"] == bid]
    if plan_id is not None:
        items = [e for e in items if e["plan_id"] == plan_id]
    if pid is not None:
        items = [e for e in items if e["enrollment_period_id"] == pid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/part-c-enrollments/<eid>", methods=["GET"])
def get_part_c(eid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.part_c_enrollments, eid)
    return success(public(rec), 200)


@app.route("/part-c-enrollments/<eid>/confirm", methods=["POST"])
def confirm_part_c(eid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.part_c_enrollments, eid)
    body = get_json_body()

    # priority 5: required field present & typed (expected_beneficiary_version)
    expected = body.get("expected_beneficiary_version")
    if not is_int(expected):
        invalid("expected_beneficiary_version is required and must be an integer.")

    # priority 6: from-state
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Part C enrollment must be PENDING.")

    beneficiary = db.beneficiaries[rec["beneficiary_id"]]
    # priority 7: OCC
    if expected != beneficiary["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Beneficiary version is stale.")

    # remaining preconditions
    if beneficiary["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary must be ACTIVE.")
    if beneficiary["part_b_status"] != "ENROLLED":
        raise ApiError("ERR_PART_B_REQUIRED", 409, "Part C requires active Part B.")
    plan = db.plans[rec["plan_id"]]
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED", 409, "Plan is retired.")

    # supersede prior ACTIVE Part C of this beneficiary
    for other in db.part_c_enrollments.values():
        if other["id"] == rec["id"]:
            continue
        if other["beneficiary_id"] == beneficiary["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
            other_plan = db.plans.get(other["plan_id"])
            if other_plan and other_plan.get("includes_drug_coverage"):
                for d in db.part_d_enrollments.values():
                    if d["beneficiary_id"] == beneficiary["id"] and d["status"] == "ACTIVE":
                        d["status"] = "DISENROLLED"
                        touch(d)

    rec["status"] = "ACTIVE"
    touch(rec)
    touch(beneficiary)
    return success(public(rec), 200)


@app.route("/part-c-enrollments/<eid>/disenroll", methods=["POST"])
def disenroll_part_c(eid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.part_c_enrollments, eid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Part C enrollment must be ACTIVE.")
    beneficiary = db.beneficiaries[rec["beneficiary_id"]]
    if beneficiary["status"] == "DECEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary is DECEASED.")
    rec["status"] = "DISENROLLED"
    touch(rec)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# PartDEnrollment endpoints
# ---------------------------------------------------------------------------
@app.route("/part-d-enrollments", methods=["POST"])
def create_part_d():
    require_auth({ROLE_ADMIN})
    body = get_json_body()

    bid = body.get("beneficiary_id")
    plan_id = body.get("plan_id")
    pid = body.get("enrollment_period_id")
    if not isinstance(bid, str):
        invalid("beneficiary_id is required.")
    if not isinstance(plan_id, str):
        invalid("plan_id is required.")
    if not isinstance(pid, str):
        invalid("enrollment_period_id is required.")

    beneficiary = db.beneficiaries.get(bid)
    if beneficiary is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Beneficiary not found.")
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Plan not found.")
    period = db.enrollment_periods.get(pid)
    if period is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EnrollmentPeriod not found.")

    # 8: mismatch
    if period["beneficiary_id"] != bid:
        raise ApiError("ERR_PERIOD_BENEFICIARY_MISMATCH", 422,
                       "Period does not belong to beneficiary.")
    # 9: wrong period type
    if period["period_type"] not in ("IEP", "AEP", "SEP_5STAR"):
        raise ApiError("ERR_WRONG_PERIOD_TYPE", 422, "Invalid period type for Part D.")
    # 10: enrollment lock
    if beneficiary["enrollment_lock"]:
        raise ApiError("ERR_ENROLLMENT_LOCKED", 409, "Beneficiary enrollment is locked.")
    # 11: within window
    if not in_closed_window(period):
        raise ApiError("ERR_OUTSIDE_ENROLLMENT_WINDOW", 422, "Outside enrollment window.")
    # 13: five-star
    if period["period_type"] == "SEP_5STAR" and plan["star_rating"] != 5.0:
        raise ApiError("ERR_NOT_FIVE_STAR", 422, "SEP_5STAR requires a 5.0-star plan.")
    # 14: drug coverage conflict — plan must be PART_D; and no MAPD stacking
    if plan["part_type"] != "PART_D":
        raise ApiError("ERR_DRUG_COVERAGE_CONFLICT", 409, "Part D requires a PART_D plan.")
    for c in db.part_c_enrollments.values():
        if c["beneficiary_id"] == bid and c["status"] == "ACTIVE":
            cplan = db.plans.get(c["plan_id"])
            if cplan and cplan.get("includes_drug_coverage"):
                raise ApiError("ERR_DRUG_COVERAGE_CONFLICT", 409,
                               "Cannot stack standalone Part D on an MAPD.")

    rec = {
        "id": str(uuid.uuid4()),
        "beneficiary_id": bid,
        "plan_id": plan_id,
        "enrollment_period_id": pid,
        "requested_at": fmt_ts(now_clock()),
        "uncovered_months": 0,
        "lep_premium_cents": 0,
        "total_drug_cost_cents": 0,
        "member_oop_cents": 0,
        "status": "PENDING",
    }
    stamp_create(rec)
    db.part_d_enrollments[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/part-d-enrollments", methods=["GET"])
def list_part_d():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    items = list(db.part_d_enrollments.values())
    bid = request.args.get("beneficiary_id")
    plan_id = request.args.get("plan_id")
    pid = request.args.get("enrollment_period_id")
    if bid is not None:
        items = [e for e in items if e["beneficiary_id"] == bid]
    if plan_id is not None:
        items = [e for e in items if e["plan_id"] == plan_id]
    if pid is not None:
        items = [e for e in items if e["enrollment_period_id"] == pid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/part-d-enrollments/<eid>", methods=["GET"])
def get_part_d(eid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.part_d_enrollments, eid)
    return success(public(rec), 200)


@app.route("/part-d-enrollments/<eid>/confirm", methods=["POST"])
def confirm_part_d(eid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.part_d_enrollments, eid)
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Part D enrollment must be PENDING.")
    beneficiary = db.beneficiaries[rec["beneficiary_id"]]
    if beneficiary["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary must be ACTIVE.")
    plan = db.plans[rec["plan_id"]]
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED", 409, "Plan is retired.")

    uncovered = compute_partd_uncovered_months(beneficiary)
    rec["uncovered_months"] = uncovered
    rec["lep_premium_cents"] = partd_lep_cents(uncovered)
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(public(rec), 200)


@app.route("/part-d-enrollments/<eid>/disenroll", methods=["POST"])
def disenroll_part_d(eid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.part_d_enrollments, eid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Part D enrollment must be ACTIVE.")
    rec["status"] = "DISENROLLED"
    touch(rec)
    return success(public(rec), 200)


@app.route("/part-d-enrollments/<eid>/claims", methods=["POST"])
def post_drug_claim(eid):
    require_auth({ROLE_ADMIN})
    enrollment = must_get(db.part_d_enrollments, eid)
    body = get_json_body()

    list_price = body.get("list_price_cents")
    if not is_int(list_price) or list_price <= 0:
        invalid("list_price_cents must be an integer > 0.")
    incurred_raw = body.get("incurred_at")
    if not isinstance(incurred_raw, str):
        invalid("incurred_at is required.")
    try:
        parse_iso(incurred_raw)
    except ValueError:
        invalid("incurred_at must be a valid ISO 8601 date-time.")

    # state check (priority 17)
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Part D enrollment must be ACTIVE.")

    phase, member_share = adjudicate_claim(enrollment, list_price)

    rec = {
        "id": str(uuid.uuid4()),
        "part_d_enrollment_id": eid,
        "list_price_cents": list_price,
        "incurred_at": incurred_raw,
        "phase_at_post": phase,
        "member_share_cents": member_share,
    }
    stamp_create(rec, versioned=False)
    db.drug_claims[rec["id"]] = rec
    touch(enrollment)
    return success(public(rec), 201)


@app.route("/part-d-enrollments/<eid>/claims", methods=["GET"])
def list_drug_claims(eid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    must_get(db.part_d_enrollments, eid)
    items = [c for c in db.drug_claims.values() if c["part_d_enrollment_id"] == eid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


# ---------------------------------------------------------------------------
# MedigapPolicy endpoints
# ---------------------------------------------------------------------------
def medigap_overlap_halfopen(s1, e1, s2, e2):
    # half-open [s,e): overlap if s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@app.route("/medigap-policies", methods=["POST"])
def create_medigap():
    require_auth({ROLE_ADMIN})
    body = get_json_body()

    bid = body.get("beneficiary_id")
    pid = body.get("enrollment_period_id")
    cs_raw = body.get("coverage_start")
    ce_raw = body.get("coverage_end")
    if not isinstance(bid, str):
        invalid("beneficiary_id is required.")
    if not isinstance(pid, str):
        invalid("enrollment_period_id is required.")

    beneficiary = db.beneficiaries.get(bid)
    if beneficiary is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Beneficiary not found.")
    period = db.enrollment_periods.get(pid)
    if period is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EnrollmentPeriod not found.")

    # priority 5: required body fields well-typed
    if not isinstance(cs_raw, str):
        invalid("coverage_start is required.")
    if not isinstance(ce_raw, str):
        invalid("coverage_end is required.")
    try:
        cs = parse_iso(cs_raw)
    except ValueError:
        invalid("coverage_start must be a valid ISO 8601 date-time.")
    try:
        ce = parse_iso(ce_raw)
    except ValueError:
        invalid("coverage_end must be a valid ISO 8601 date-time.")

    # 8: period beneficiary mismatch
    if period["beneficiary_id"] != bid:
        raise ApiError("ERR_PERIOD_BENEFICIARY_MISMATCH", 422,
                       "Period does not belong to beneficiary.")
    # 9: wrong period type (must be GI_MEDIGAP)
    if period["period_type"] != "GI_MEDIGAP":
        raise ApiError("ERR_WRONG_PERIOD_TYPE", 422, "Medigap requires a GI_MEDIGAP period.")
    # 10: enrollment lock
    if beneficiary["enrollment_lock"]:
        raise ApiError("ERR_ENROLLMENT_LOCKED", 409, "Beneficiary enrollment is locked.")
    # 12: 63-day GI window: now >= source_event_date and now <= source_event_date+63d
    sed = parse_iso(period["source_event_date"])
    nowt = now_clock()
    if not (sed <= nowt <= sed + timedelta(days=63)):
        raise ApiError("ERR_GI_WINDOW_EXPIRED", 422, "Outside 63-day guaranteed-issue window.")
    # 16: medigap coverage overlap (half-open) vs existing ISSUED
    for m in db.medigap_policies.values():
        if m["beneficiary_id"] == bid and m["status"] == "ISSUED":
            ms = parse_iso(m["coverage_start"])
            me = parse_iso(m["coverage_end"])
            if medigap_overlap_halfopen(cs, ce, ms, me):
                raise ApiError("ERR_MEDIGAP_OVERLAP", 409, "Overlapping Medigap coverage.")

    rec = {
        "id": str(uuid.uuid4()),
        "beneficiary_id": bid,
        "enrollment_period_id": pid,
        "requested_at": fmt_ts(now_clock()),
        "coverage_start": cs_raw,
        "coverage_end": ce_raw,
        "guaranteed_issue": True,
        "status": "ISSUED",
    }
    stamp_create(rec)
    db.medigap_policies[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/medigap-policies", methods=["GET"])
def list_medigap():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    items = list(db.medigap_policies.values())
    bid = request.args.get("beneficiary_id")
    pid = request.args.get("enrollment_period_id")
    if bid is not None:
        items = [m for m in items if m["beneficiary_id"] == bid]
    if pid is not None:
        items = [m for m in items if m["enrollment_period_id"] == pid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/medigap-policies/<mid>", methods=["GET"])
def get_medigap(mid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.medigap_policies, mid)
    return success(public(rec), 200)


@app.route("/medigap-policies/<mid>/lapse", methods=["POST"])
def lapse_medigap(mid):
    require_auth({ROLE_ADMIN})
    rec = must_get(db.medigap_policies, mid)
    if rec["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Medigap policy must be ISSUED.")
    beneficiary = db.beneficiaries[rec["beneficiary_id"]]
    if beneficiary["status"] == "DECEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "Beneficiary is DECEASED.")
    rec["status"] = "LAPSED"
    touch(rec)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# PenaltyAssessment endpoints
# ---------------------------------------------------------------------------
@app.route("/penalty-assessments", methods=["POST"])
def create_penalty():
    require_auth({ROLE_COMPLIANCE})
    body = get_json_body()

    bid = body.get("beneficiary_id")
    if not isinstance(bid, str):
        invalid("beneficiary_id is required.")
    beneficiary = db.beneficiaries.get(bid)
    if beneficiary is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Beneficiary not found.")

    penalty_type = body.get("penalty_type")
    if penalty_type not in ("PART_B", "PART_D"):
        invalid("penalty_type must be PART_B or PART_D.")
    uncovered = body.get("uncovered_months")
    if not is_int(uncovered) or uncovered < 0:
        invalid("uncovered_months must be an integer >= 0.")

    if penalty_type == "PART_D":
        monthly = partd_lep_cents(uncovered)
    else:
        monthly = partb_lep_cents(uncovered)

    rec = {
        "id": str(uuid.uuid4()),
        "beneficiary_id": bid,
        "penalty_type": penalty_type,
        "uncovered_months": uncovered,
        "monthly_penalty_cents": monthly,
        "status": "ASSESSED",
    }
    stamp_create(rec)
    db.penalty_assessments[rec["id"]] = rec
    return success(public(rec), 201)


@app.route("/penalty-assessments", methods=["GET"])
def list_penalties():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    items = list(db.penalty_assessments.values())
    bid = request.args.get("beneficiary_id")
    if bid is not None:
        items = [p for p in items if p["beneficiary_id"] == bid]
    data, meta_extra = paginate(items)
    return success(data, 200, response_type="array", meta_extra=meta_extra)


@app.route("/penalty-assessments/<pid>", methods=["GET"])
def get_penalty(pid):
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    rec = must_get(db.penalty_assessments, pid)
    return success(public(rec), 200)


@app.route("/penalty-assessments/<pid>/waive", methods=["POST"])
def waive_penalty(pid):
    require_auth({ROLE_COMPLIANCE})
    rec = must_get(db.penalty_assessments, pid)
    if rec["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Penalty must be ASSESSED.")
    rec["status"] = "WAIVED"
    rec["monthly_penalty_cents"] = 0
    touch(rec)
    return success(public(rec), 200)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({ROLE_ADMIN, ROLE_COMPLIANCE})
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        invalid("to_iso8601 is required.")
    try:
        db.clock = parse_iso(to_iso)
    except ValueError:
        invalid("to_iso8601 must be a valid ISO 8601 date-time.")
    return success({}, 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
